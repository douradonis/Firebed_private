# app.py
# Fixed/robust Flask app for Firebed_private (bulk-fetch-cache)
# - expects a utils.py with helper functions (if absent, app will warn)
# - uses templates/ if present; otherwise renders inline templates
# - safe handling for missing Pillow / mydatanaut packages
# - ensures datetime is available inside Jinja templates

import os
import sys
import json
import traceback
import datetime
from urllib.parse import urlparse

from dotenv import load_dotenv
from flask import (
    Flask, request, render_template, render_template_string,
    url_for, redirect, send_file, flash
)
import pandas as pd

# --- base paths ---
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
DATA_DIR = os.path.join(BASE_DIR, "data")
UPLOADS_DIR = os.path.join(BASE_DIR, "uploads")
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(UPLOADS_DIR, exist_ok=True)

# config file used by the UI to persist AADE credentials (safe local file)
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
CACHE_FILE = os.path.join(DATA_DIR, "invoices_cache.json")
CREDENTIALS_FILE = os.path.join(DATA_DIR, "credentials.json")
EXCEL_FILE = os.path.join(UPLOADS_DIR, "invoices.xlsx")

# load .env if present
load_dotenv()

# add vendor to sys.path (for vendorized mydatanaut)
VENDOR_DIR = os.path.join(BASE_DIR, "vendor")
if os.path.isdir(VENDOR_DIR) and VENDOR_DIR not in sys.path:
    sys.path.insert(0, VENDOR_DIR)

# try import optional 3rd-party helper package mydatanaut (vendorized or from pip)
HAS_MYDATANAUT = False
try:
    import mydatanaut as mydatanaut_pkg  # optional, may be vendorized
    HAS_MYDATANAUT = True
except Exception:
    HAS_MYDATANAUT = False

# try Pillow (PIL) for image handling in utils
HAS_PIL = True
try:
    from PIL import Image  # noqa: F401
except Exception:
    HAS_PIL = False

# try import utils.py (should exist in repo)
try:
    from utils import (
        extract_marks_from_url, extract_marks_from_text, decode_qr_from_file,
        extract_vat_categories, summarize_invoice, format_euro_str,
        is_mark_transmitted as utils_is_mark_transmitted,
        fetch_by_mark, save_summary_to_excel, EXCEL_FILE as UTIL_EXCEL_FILE
    )
    UTIL_AVAILABLE = True
except Exception:
    UTIL_AVAILABLE = False

# If utils defines EXCEL_FILE we prefer to use it (optional)
if UTIL_AVAILABLE and 'UTIL_EXCEL_FILE' in globals() and UTIL_EXCEL_FILE:
    # only override if util defines an absolute path or relative; keep our UPLOADS_DIR location
    try:
        # prefer the project's EXCEL_FILE if provided
        EXCEL_FILE = UTIL_EXCEL_FILE
    except Exception:
        pass

# --- Flask app setup ---
app = Flask(__name__, template_folder=TEMPLATES_DIR)
app.secret_key = os.getenv("FLASK_SECRET", "change-me-secret")

# make datetime available in templates to fix 'datetime is undefined'
app.jinja_env.globals['datetime'] = datetime

# --- helpers: config / credentials / cache ---
def load_json_file(path, default=None):
    if default is None:
        default = []
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return default

def save_json_file(path, obj):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2)

def load_config():
    cfg = {}
    # from CONFIG_FILE then environment fallback
    if os.path.exists(CONFIG_FILE):
        try:
            cfg = load_json_file(CONFIG_FILE, {})
        except Exception:
            cfg = {}
    cfg.setdefault("AADE_USER_ID", os.getenv("AADE_USER_ID", ""))
    cfg.setdefault("AADE_SUBSCRIPTION_KEY", os.getenv("AADE_SUBSCRIPTION_KEY", ""))
    cfg.setdefault("MYDATA_ENV", os.getenv("MYDATA_ENV", "sandbox"))
    return cfg

def save_config(cfg):
    save_json_file(CONFIG_FILE, cfg)

def load_credentials():
    creds = load_json_file(CREDENTIALS_FILE, [])
    return creds if isinstance(creds, list) else []

def save_credentials(creds):
    save_json_file(CREDENTIALS_FILE, creds)

def append_doc_to_cache(doc):
    docs = load_json_file(CACHE_FILE, [])
    # canonical JSON signature to avoid dupes
    sig = json.dumps(doc, sort_keys=True, ensure_ascii=False)
    for d in docs:
        if json.dumps(d, sort_keys=True, ensure_ascii=False) == sig:
            return False
    docs.append(doc)
    save_json_file(CACHE_FILE, docs)
    return True

def load_cache_preview(limit=50):
    docs = load_json_file(CACHE_FILE, [])
    if not isinstance(docs, list):
        return []
    return docs[:limit]

# wrapper for transmitted check - adapt to utils if available
def is_mark_transmitted(mark, aade_user, aade_key, transmitted_url):
    if UTIL_AVAILABLE and callable(utils_is_mark_transmitted):
        try:
            return utils_is_mark_transmitted(mark, aade_user, aade_key, transmitted_url)
        except Exception:
            app.logger.exception("utils.is_mark_transmitted failed")
            return False
    # fallback: attempt a minimal transmitted check via requests (best-effort)
    import requests
    headers = {
        "aade-user-id": aade_user,
        "ocp-apim-subscription-key": aade_key,
        "Accept": "application/xml"
    }
    try:
        r = requests.get(transmitted_url, params={"mark": mark}, headers=headers, timeout=20)
        if r.status_code >= 400:
            return False
        txt = (r.text or "").lower()
        if "invoicemark" in txt or "invoiceuid" in txt or "classification" in txt or "e3_" in txt:
            return True
    except Exception:
        app.logger.debug("transmitted-check failed", exc_info=True)
    return False

# --- templates fallback (if templates/ dir missing) ---
USE_TEMPLATES = os.path.isdir(TEMPLATES_DIR)

# If templates directory missing, define minimal inline templates here (the repository has templates, normally)
NAV_INLINE = """<!doctype html>
<html><head><meta charset="utf-8"><title>myDATA - Menu</title></head><body>
<h1>myDATA</h1>
<ul>
<li><a href="{{ url_for('viewer') }}">Viewer</a></li>
<li><a href="{{ url_for('fetch') }}">Bulk Fetch</a></li>
<li><a href="{{ url_for('list_invoices') }}">List</a></li>
<li><a href="{{ url_for('config') }}">Config</a></li>
</ul>
</body></html>
"""

# --- endpoint URLs based on environment ---
def endpoints_for_env(env):
    env = (env or "sandbox").lower()
    if env in ("sandbox", "demo", "dev"):
        return {
            "REQUESTDOCS_URL": "https://mydataapidev.aade.gr/RequestDocs",
            "TRANSMITTED_URL": "https://mydataapidev.aade.gr/RequestTransmittedDocs"
        }
    return {
        "REQUESTDOCS_URL": "https://mydatapi.aade.gr/myDATA/RequestDocs",
        "TRANSMITTED_URL": "https://mydatapi.aade.gr/myDATA/RequestTransmittedDocs"
    }

# ---------------- Routes ----------------

@app.route("/")
def home():
    if USE_TEMPLATES:
        # if nav.html present, use it; otherwise fallback
        try:
            return render_template("nav.html")
        except Exception:
            return render_template_string(NAV_INLINE)
    return render_template_string(NAV_INLINE)

# configuration page to input AADE credentials (saved to CONFIG_FILE)
@app.route("/config", methods=["GET", "POST"])
def config():
    cfg = load_config()
    if request.method == "POST":
        cfg["AADE_USER_ID"] = request.form.get("aade_user_id", "").strip()
        cfg["AADE_SUBSCRIPTION_KEY"] = request.form.get("aade_subscription_key", "").strip()
        cfg["MYDATA_ENV"] = request.form.get("mydata_env", "sandbox").strip()
        save_config(cfg)
        flash("Configuration saved", "success")
        return redirect(url_for("home"))
    # render config template if exists
    if USE_TEMPLATES:
        try:
            return render_template("config.html", config=cfg)
        except Exception:
            pass
    # fallback basic form
    html = """
    <h1>Config</h1>
    <form method="post">
      AADE_USER_ID: <input name="aade_user_id" value="{{config.AADE_USER_ID}}"><br>
      AADE_SUBSCRIPTION_KEY: <input name="aade_subscription_key" value="{{config.AADE_SUBSCRIPTION_KEY}}"><br>
      Env: <select name="mydata_env"><option value="sandbox">sandbox</option><option value="production">production</option></select><br>
      <button>Save</button>
    </form>
    """
    return render_template_string(html, config=cfg)

# credentials management (stored credentials list)
@app.route("/credentials", methods=["GET","POST"])
def credentials():
    msg = None
    creds = load_credentials()
    if request.method == "POST":
        name = request.form.get("name","").strip()
        user = request.form.get("user","").strip()
        key = request.form.get("key","").strip()
        env = request.form.get("env","sandbox").strip()
        vat = request.form.get("vat","").strip()
        if not name:
            flash("Name required", "error")
        else:
            # dedupe by name
            if any(c.get("name")==name for c in creds):
                flash("Credential name exists", "error")
            else:
                creds.append({"name":name,"user":user,"key":key,"env":env,"vat":vat})
                save_credentials(creds)
                flash("Saved", "success")
                return redirect(url_for("credentials"))
    if USE_TEMPLATES:
        try:
            return render_template("credentials_list.html", credentials=creds)
        except Exception:
            pass
    # fallback
    return render_template_string("<h1>Credentials</h1><pre>{{creds}}</pre><p><a href='{{url_for(\"home\")}}'>Home</a></p>", creds=creds)

# bulk fetch page (date range UI)
@app.route("/fetch", methods=["GET","POST"])
def fetch():
    cfg = load_config()
    creds = load_credentials()
    preview = load_cache_preview(40)
    message = None
    error = None
    env = cfg.get("MYDATA_ENV", "sandbox")
    endpoints = endpoints_for_env(env)
    if request.method == "POST":
        date_from = request.form.get("date_from")
        date_to = request.form.get("date_to")
        vat = request.form.get("vat_number","").strip()
        selected_cred = request.form.get("use_credential","").strip()
        # resolve credentials
        if selected_cred:
            sel = next((c for c in creds if c.get("name")==selected_cred), None)
            if sel:
                aade_user = sel.get("user","")
                aade_key = sel.get("key","")
                vat = vat or sel.get("vat","")
                env = sel.get("env", env)
        else:
            cfg = load_config()
            aade_user = cfg.get("AADE_USER_ID","")
            aade_key = cfg.get("AADE_SUBSCRIPTION_KEY","")
        # set endpoints for selected env (if credential has its own env, use it)
        endpoints = endpoints_for_env(env)
        try:
            # try mydatanaut if available & vendorized
            if HAS_MYDATANAUT:
                try:
                    # attempt to call a generic client pattern
                    client = None
                    try:
                        client = mydatanaut_pkg.Client(user=aade_user, key=aade_key, env=env)
                    except Exception:
                        try:
                            client = mydatanaut_pkg.MyDataClient(user=aade_user, key=aade_key, env=env)
                        except Exception:
                            client = None
                    if client:
                        # try client.request_docs or client.fetch_docs
                        if hasattr(client, "request_docs"):
                            docs = client.request_docs(date_from, date_to, vat)
                        elif hasattr(client, "fetch_docs"):
                            docs = client.fetch_docs(date_from, date_to, vat)
                        else:
                            docs = None
                        # normalize docs list
                        if docs is None:
                            fetched_list = []
                        elif isinstance(docs, dict):
                            fetched_list = docs.get("docs") or ([docs] if docs else [])
                        elif isinstance(docs, list):
                            fetched_list = docs
                        else:
                            fetched_list = [docs]
                        added = 0
                        for d in fetched_list:
                            if append_doc_to_cache(d):
                                added += 1
                        message = f"Fetched {len(fetched_list)} items via mydatanaut, newly cached: {added}"
                        preview = load_cache_preview(40)
                        return render_template("fetch.html", credentials=creds, message=message, error=error, preview=preview, env=env, endpoints=endpoints)
                except Exception:
                    app.logger.exception("mydatanaut fetch failed; falling back to RequestDocs")

            # fallback: call RequestDocs endpoint via utils.fetch_by_mark? No - we use a generic RequestDocs caller here
            # If utils provides a helper to call RequestDocs bulk, use it; else, run a minimal request->xml parse
            import requests, xmltodict  # xmltodict is in requirements
            # RequestDocs expects dd/MM/YYYY dates
            try:
                d1 = datetime.datetime.fromisoformat(date_from).strftime("%d/%m/%Y")
                d2 = datetime.datetime.fromisoformat(date_to).strftime("%d/%m/%Y")
            except Exception:
                d1, d2 = date_from, date_to
            params = {"dateFrom": d1, "dateTo": d2}
            if vat:
                params["vatNumber"] = vat
            headers = {
                "aade-user-id": aade_user,
                "ocp-apim-subscription-key": aade_key,
                "Accept": "application/xml"
            }
            r = requests.get(endpoints["REQUESTDOCS_URL"], params=params, headers=headers, timeout=90)
            if r.status_code >= 400:
                raise Exception(f"API error {r.status_code}: {r.text[:500]}")
            parsed_outer = None
            try:
                parsed_outer = xmltodict.parse(r.text)
            except Exception:
                # sometimes the response wraps an inner xml string; try to locate "string" node
                try:
                    parsed_outer = xmltodict.parse(r.text)
                except Exception:
                    parsed_outer = None
            docs_list = []
            if isinstance(parsed_outer, dict):
                # common shapes: {..., 'RequestedDoc': {...}} or {..., 'string': {'#text': '...inner xml...'}}
                if "RequestedDoc" in parsed_outer:
                    maybe = parsed_outer.get("RequestedDoc")
                    docs_list = maybe if isinstance(maybe, list) else [maybe]
                elif "string" in parsed_outer:
                    inner = parsed_outer.get("string")
                    # inner might contain '#text' or be a string with xml; try parse
                    inner_text = ""
                    if isinstance(inner, dict) and "#text" in inner:
                        inner_text = inner["#text"]
                    elif isinstance(inner, str):
                        inner_text = inner
                    if inner_text:
                        try:
                            inner_parsed = xmltodict.parse(inner_text)
                            if "RequestedDoc" in inner_parsed:
                                maybe = inner_parsed.get("RequestedDoc")
                                docs_list = maybe if isinstance(maybe, list) else [maybe]
                            else:
                                docs_list = [inner_parsed]
                        except Exception:
                            docs_list = [inner_text]
                elif "docs" in parsed_outer:
                    docs_list = parsed_outer.get("docs") or []
                else:
                    # fallback: treat whole response as a single item
                    docs_list = [parsed_outer]
            elif isinstance(parsed_outer, list):
                docs_list = parsed_outer
            else:
                docs_list = []

            added = 0
            for d in docs_list:
                if append_doc_to_cache(d):
                    added += 1
            message = f"Fetched {len(docs_list)} items, newly cached: {added}"
            preview = load_cache_preview(40)
        except Exception as e:
            app.logger.exception("fetch error")
            error = f"Σφάλμα λήψης: {e}"
    # render templates if available
    if USE_TEMPLATES:
        try:
            return render_template("fetch.html", credentials=creds, message=message, error=error, preview=preview, env=env, endpoints=endpoints)
        except Exception:
            app.logger.exception("render fetch.html failed, falling back")
    # fallback minimal page
    fallback_html = """
    <h1>Bulk Fetch</h1>
    {% if error %}<div style="color:red">{{error}}</div>{% endif %}
    {% if message %}<div style="color:green">{{message}}</div>{% endif %}
    <form method="post">
      Από: <input type="date" name="date_from" required> Έως: <input type="date" name="date_to" required><br>
      VAT: <input name="vat_number"><br>
      <button>Fetch</button>
    </form>
    <h3>Preview (first {{preview|length}} cached)</h3>
    <pre>{{preview|tojson(indent=2)}}</pre>
    """
    return render_template_string(fallback_html, credentials=creds, message=message, error=error, preview=preview)

# Viewer (MARK input / file upload)
@app.route("/viewer", methods=["GET","POST"])
def viewer():
    cfg = load_config()
    if not cfg.get("AADE_USER_ID") or not cfg.get("AADE_SUBSCRIPTION_KEY"):
        flash("Please configure AADE credentials first", "error")
        return redirect(url_for("config"))

    payload = None
    raw = None
    summary = None
    message = None
    error = None

    if request.method == "POST":
        input_text = request.form.get("mark","").strip()
        marks = []
        # file upload
        if "file" in request.files:
            f = request.files["file"]
            if f and f.filename:
                data = f.read()
                try:
                    if UTIL_AVAILABLE and callable(decode_qr_from_file):
                        detected = decode_qr_from_file(data, f.filename)
                    else:
                        detected = None
                    if detected:
                        marks = [detected]
                    else:
                        # no detection: try to extract marks from text file
                        text_marks = []
                        try:
                            text = data.decode("utf-8", errors="ignore")
                            from re import findall
                            text_marks = [m for m in findall(r"\b\d{15}\b", text)]
                        except Exception:
                            text_marks = []
                        if text_marks:
                            marks = text_marks
                        else:
                            error = "Δεν βρέθηκε MARK στο αρχείο."
                except Exception:
                    app.logger.exception("file decode error")
                    error = "Σφάλμα στην επεξεργασία αρχείου."

        # if no file marks, try input_text (could be URL or direct mark or page with marks)
        if not marks and input_text:
            try:
                parsed_url = urlparse(input_text)
                if parsed_url.scheme in ("http", "https") and parsed_url.netloc:
                    # attempt to fetch marks from page (utils function preferred)
                    if UTIL_AVAILABLE and callable(extract_marks_from_url):
                        try:
                            marks = extract_marks_from_url(input_text) or []
                        except Exception:
                            app.logger.exception("extract_marks_from_url failed")
                            marks = []
                    else:
                        # fallback: simple regex on the page content
                        import requests, re
                        try:
                            r = requests.get(input_text, timeout=20)
                            marks = re.findall(r"\b\d{15}\b", r.text)
                        except Exception:
                            marks = []
                else:
                    # treat input_text as plain text / mark
                    if UTIL_AVAILABLE and callable(extract_marks_from_text):
                        try:
                            marks = extract_marks_from_text(input_text)
                        except Exception:
                            marks = []
                    else:
                        # fallback:
                        if input_text.isdigit() and len(input_text.strip())==15:
                            marks = [input_text.strip()]
            except Exception:
                marks = []

        if not marks:
            if not error:
                error = "Δεν βρέθηκε ΜΑΡΚ (εισάγετε έγκυρο 15-ψήφιο MARK ή URL που περιέχει MARK)."
        else:
            successes = []
            duplicates = []
            api_errors = []
            last_summary = None
            last_payload = None
            last_raw = None
            cfg_local = load_config()
            endpoints = endpoints_for_env(cfg_local.get("MYDATA_ENV","sandbox"))
            for m in marks:
                # check transmitted
                try:
                    if is_mark_transmitted(m, cfg_local.get("AADE_USER_ID",""), cfg_local.get("AADE_SUBSCRIPTION_KEY",""), endpoints["TRANSMITTED_URL"]):
                        api_errors.append((m, "Το παραστατικό είναι ήδη καταχωρημένο / χαρακτηρισμένο (transmitted)."))
                        continue
                except Exception:
                    app.logger.exception("transmitted check failed")

                # fetch the doc by mark
                try:
                    if UTIL_AVAILABLE and callable(fetch_by_mark):
                        err, parsed_obj, raw_xml, summ = fetch_by_mark(m, cfg_local.get("AADE_USER_ID",""), cfg_local.get("AADE_SUBSCRIPTION_KEY",""), endpoints["REQUESTDOCS_URL"])
                    else:
                        # no helper: minimal RequestDocs by mark (may not be supported by AADE — prefer utils)
                        err = "No fetch_by_mark available in utils"
                        parsed_obj = None; raw_xml = None; summ = None
                    if err:
                        api_errors.append((m, err))
                        continue
                    if not parsed_obj:
                        api_errors.append((m, "Empty response or parse error"))
                        continue
                    # extract VAT categories (if helper exists)
                    try:
                        vat_cats = extract_vat_categories(parsed_obj) if UTIL_AVAILABLE and callable(extract_vat_categories) else {}
                    except Exception:
                        vat_cats = {}
                    # save summary row using helper save_summary_to_excel
                    try:
                        saved = False
                        if UTIL_AVAILABLE and callable(save_summary_to_excel):
                            saved = save_summary_to_excel(summ, m, vat_categories=vat_cats)  # your util signature
                        else:
                            # fallback: simple CSV append to EXCEL_FILE (will be CSV if openpyxl missing)
                            import csv
                            headless = not os.path.exists(EXCEL_FILE)
                            row = summ if isinstance(summ, dict) else {"MARK": m}
                            with open(EXCEL_FILE, "a", newline="", encoding="utf-8") as fh:
                                writer = csv.writer(fh)
                                if headless:
                                    writer.writerow(list(row.keys()))
                                writer.writerow([str(v) for v in row.values()])
                            saved = True
                        if saved:
                            successes.append(m)
                        else:
                            duplicates.append(m)
                    except Exception as ee:
                        api_errors.append((m, f"Σφάλμα αποθήκευσης: {ee}"))
                        continue

                    last_summary = summ
                    last_payload = json.dumps(parsed_obj, ensure_ascii=False, indent=2)
                    last_raw = raw_xml
                except Exception as e:
                    app.logger.exception("fetch_by_mark failed")
                    api_errors.append((m, f"Exception: {e}"))
                    continue

            parts = []
            if successes:
                parts.append(f"Αποθηκεύτηκαν: {len(successes)} ({', '.join(successes)})")
            if duplicates:
                parts.append(f"Διπλοεγγραφές (παραλήφθηκαν): {len(duplicates)} ({', '.join(duplicates)})")
            if api_errors:
                parts.append(f"Σφάλματα/Μηνύματα: {len(api_errors)}")
                parts += [f"- {m}: {e}" for m, e in api_errors[:20]]
            message = "\n".join(parts) if parts else None

            if last_summary:
                summary = last_summary
                payload = last_payload
                raw = last_raw

            if not successes and not duplicates and api_errors and not summary:
                error = "Απέτυχαν όλες οι προσπάθειες. Δες λεπτομέρειες στα μηνύματα."

    # render: prefer templates/viewer.html if present
    if USE_TEMPLATES:
        try:
            return render_template("viewer.html", payload=payload, raw=raw, summary=summary, env=load_config().get("MYDATA_ENV","sandbox"), endpoint=endpoints_for_env(load_config().get("MYDATA_ENV","sandbox"))["REQUESTDOCS_URL"], message=message, error=error)
        except Exception:
            app.logger.exception("render viewer template failed")
    # fallback render inline (very basic)
    inline = "<h1>Viewer</h1>{% if error %}<div style='color:red;'>{{error}}</div>{% endif %}{% if message %}<pre>{{message}}</pre>{% endif %}<form method='post'><input name='mark' placeholder='MARK or URL'><button>Submit</button></form>"
    return render_template_string(inline, payload=payload, raw=raw, summary=summary, message=message, error=error)

# list / download / delete routes (use EXCEL_FILE or fallback to cache)
@app.route("/list", methods=["GET"])
def list_invoices():
    file_exists = os.path.exists(EXCEL_FILE)
    table_html = ""
    error = None
    css_numcols = ""
    if file_exists:
        try:
            df = pd.read_excel(EXCEL_FILE, engine="openpyxl", dtype=str).fillna("")
            if "ΦΠΑ_ΑΝΑΛΥΣΗ" in df.columns:
                df = df.drop(columns=["ΦΠΑ_ΑΝΑΛΥΣΗ"])
            if "MARK" in df.columns:
                checkboxes = df["MARK"].apply(lambda v: f'<input type="checkbox" name="delete_mark" value="{str(v)}">')
                df.insert(0, "✓", checkboxes)
            table_html = df.to_html(classes="summary-table", index=False, escape=False)
            table_html = table_html.replace("<th>✓</th>", '<th><input type="checkbox" id="selectAll"></th>')
            table_html = table_html.replace("<td>", '<td><div style=\"white-space:pre-wrap;word-break:break-word;max-width:360px;\">').replace("</td>", "</div></td>")
            # compute numeric column css
            headers = [h.strip() for h in list(df.columns)]
            num_indices = []
            for i,h in enumerate(headers):
                if any(k in h for k in ("Καθαρή Αξία","ΦΠΑ","Σύνολο","TOTAL","NET","VAT","ΠΟΣΟ")):
                    num_indices.append(i+1)
            css_rules = []
            for idx in num_indices:
                css_rules.append(f".summary-table td:nth-child({idx}), .summary-table th:nth-child({idx}) {{ text-align: right; }}")
            css_numcols = "\n".join(css_rules)
        except Exception as e:
            app.logger.exception("read excel error")
            error = f"Σφάλμα ανάγνωσης Excel: {e}"
    else:
        # fallback to cache
        cached = load_json_file(CACHE_FILE, [])
        table_html = "<pre>" + json.dumps(cached[:200], ensure_ascii=False, indent=2) + "</pre>" if cached else ""
    # prefer template if available
    if USE_TEMPLATES:
        try:
            return render_template("list.html", table_html=table_html, error=error, file_exists=file_exists, css_numcols=css_numcols)
        except Exception:
            app.logger.exception("render list.html failed")
    # fallback
    return render_template_string("<h1>List</h1>{% if error %}<div style='color:red;'>{{error}}</div>{% endif %}{{table_html|safe}}", error=error, table_html=table_html)

@app.route("/delete", methods=["POST"])
def delete_invoices():
    marks_to_delete = request.form.getlist("delete_mark")
    if not marks_to_delete:
        return redirect(url_for("list_invoices"))
    if os.path.exists(EXCEL_FILE):
        try:
            df = pd.read_excel(EXCEL_FILE, engine="openpyxl", dtype=str).fillna("")
            if "MARK" in df.columns:
                before = len(df)
                df = df[~df["MARK"].astype(str).isin([str(m).strip() for m in marks_to_delete])]
                after = len(df)
                if after != before:
                    df.to_excel(EXCEL_FILE, index=False, engine="openpyxl")
        except Exception:
            app.logger.exception("delete invoices error")
    return redirect(url_for("list_invoices"))

@app.route("/download", methods=["GET"])
def download_excel():
    if not os.path.exists(EXCEL_FILE):
        return ("Το αρχείο .xlsx δεν υπάρχει.", 404)
    return send_file(EXCEL_FILE, as_attachment=True, download_name="invoices.xlsx", mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# health
@app.route("/health")
def health():
    return "OK"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "0") in ("1", "true", "True")
    app.run(host="0.0.0.0", port=port, debug=debug)
