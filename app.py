# app.py
# Revised: fixes RequestDocs/Transmitted endpoints, restores template context and default MARK
import os
import sys
import json
import traceback
import datetime
from urllib.parse import urlparse

from dotenv import load_dotenv
from flask import Flask, request, render_template, render_template_string, url_for, redirect, send_file, flash

import requests
import xmltodict
import pandas as pd

# --- setup paths ---
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
DATA_DIR = os.path.join(BASE_DIR, "data")
UPLOADS_DIR = os.path.join(BASE_DIR, "uploads")
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(UPLOADS_DIR, exist_ok=True)

CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
CACHE_FILE = os.path.join(DATA_DIR, "invoices_cache.json")
CREDENTIALS_FILE = os.path.join(DATA_DIR, "credentials.json")
EXCEL_FILE = os.path.join(UPLOADS_DIR, "invoices.xlsx")

# load .env if present
load_dotenv()

# vendor path (if you vendorized libraries)
VENDOR_DIR = os.path.join(BASE_DIR, "vendor")
if os.path.isdir(VENDOR_DIR) and VENDOR_DIR not in sys.path:
    sys.path.insert(0, VENDOR_DIR)

# Attempt import of utils (your helper functions). If missing, app still runs with fallbacks.
UTIL_AVAILABLE = False
try:
    from utils import (
        decode_qr_from_file,
        extract_marks_from_url,
        extract_marks_from_text,
        extract_vat_categories,
        fetch_by_mark,
        save_summary_to_excel,
        is_mark_transmitted as utils_is_mark_transmitted
    )
    UTIL_AVAILABLE = True
except Exception:
    UTIL_AVAILABLE = False

# Flask app
app = Flask(__name__, template_folder=TEMPLATES_DIR)
app.secret_key = os.getenv("FLASK_SECRET", "change-me")
# make datetime available in templates
app.jinja_env.globals['datetime'] = datetime

USE_TEMPLATES = os.path.isdir(TEMPLATES_DIR)

# Default MARK as requested
DEFAULT_MARK = "12345678901234"

# Helper: load/save JSON helpers
def _read_json(path, default=None):
    if default is None: default = []
    try:
        if not os.path.exists(path): return default
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def _write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_config():
    cfg = {}
    if os.path.exists(CONFIG_FILE):
        try:
            cfg = _read_json(CONFIG_FILE, {})
        except Exception:
            cfg = {}
    cfg.setdefault("AADE_USER_ID", os.getenv("AADE_USER_ID", ""))
    cfg.setdefault("AADE_SUBSCRIPTION_KEY", os.getenv("AADE_SUBSCRIPTION_KEY", ""))
    cfg.setdefault("MYDATA_ENV", os.getenv("MYDATA_ENV", "sandbox"))
    return cfg

def save_config(cfg):
    _write_json(CONFIG_FILE, cfg)

def load_credentials():
    creds = _read_json(CREDENTIALS_FILE, [])
    return creds if isinstance(creds, list) else []

def save_credentials(creds):
    _write_json(CREDENTIALS_FILE, creds)

def load_cache(limit=None):
    docs = _read_json(CACHE_FILE, [])
    if not isinstance(docs, list): return []
    return docs[:limit] if limit and len(docs)>limit else docs

def append_doc_to_cache(doc):
    docs = _read_json(CACHE_FILE, [])
    sig = json.dumps(doc, sort_keys=True, ensure_ascii=False)
    for d in docs:
        if json.dumps(d, sort_keys=True, ensure_ascii=False) == sig:
            return False
    docs.append(doc)
    _write_json(CACHE_FILE, docs)
    return True

# endpoints by environment (fixed mapping)
def endpoints_for_env(env):
    env = (env or "sandbox").lower()
    if env in ("sandbox", "dev", "demo"):
        return {
            "REQUESTDOCS_URL": "https://mydataapidev.aade.gr/myDATA/RequestDocs",
            "TRANSMITTED_URL": "https://mydataapidev.aade.gr/myDATA/RequestTransmittedDocs"
        }
    return {
        "REQUESTDOCS_URL": "https://mydatapi.aade.gr/myDATA/RequestDocs",
        "TRANSMITTED_URL": "https://mydatapi.aade.gr/myDATA/RequestTransmittedDocs"
    }

# wrapper for checking transmitted status (use utils if available)
def is_mark_transmitted(mark, aade_user, aade_key, transmitted_url):
    if UTIL_AVAILABLE and callable(utils_is_mark_transmitted):
        try:
            return utils_is_mark_transmitted(mark, aade_user, aade_key, transmitted_url)
        except Exception:
            app.logger.exception("utils_is_mark_transmitted failed")
            return False
    try:
        headers = {
            "aade-user-id": aade_user,
            "ocp-apim-subscription-key": aade_key,
            "Accept": "application/xml"
        }
        r = requests.get(transmitted_url, params={"mark": mark}, headers=headers, timeout=20)
        if r.status_code >= 400:
            return False
        raw = (r.text or "").lower()
        if "invoicemark" in raw or "invoiceuid" in raw or "classification" in raw:
            return True
    except Exception:
        app.logger.debug("transmitted check failed", exc_info=True)
    return False

# --- Routes ---

@app.route("/")
def home():
    if USE_TEMPLATES:
        try:
            return render_template("nav.html")
        except Exception:
            app.logger.exception("render nav.html failed, falling back")
    return render_template_string("<h1>myDATA</h1><p><a href='{{url_for(\"viewer\")}}'>Viewer</a> | <a href='{{url_for(\"fetch\")}}'>Bulk fetch</a></p>")

@app.route("/config", methods=["GET","POST"])
def config():
    cfg = load_config()
    if request.method == "POST":
        cfg["AADE_USER_ID"] = request.form.get("aade_user_id","").strip()
        cfg["AADE_SUBSCRIPTION_KEY"] = request.form.get("aade_subscription_key","").strip()
        cfg["MYDATA_ENV"] = request.form.get("mydata_env","sandbox").strip()
        save_config(cfg)
        flash("Saved configuration", "success")
        return redirect(url_for("home"))
    if USE_TEMPLATES:
        try:
            return render_template("config.html", config=cfg)
        except Exception:
            app.logger.exception("render config.html failed")
    return render_template_string("<form method='post'>AADE_USER_ID: <input name='aade_user_id' value='{{config.AADE_USER_ID}}'><br>AADE_KEY: <input name='aade_subscription_key' value='{{config.AADE_SUBSCRIPTION_KEY}}'><br>Env: <select name='mydata_env'><option value='sandbox'>sandbox</option><option value='production'>production</option></select><button>Save</button></form>", config=cfg)

@app.route("/credentials", methods=["GET","POST"])
def credentials():
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
            app.logger.exception("render credentials_list failed")
    return render_template_string("<h1>Credentials</h1><pre>{{creds}}</pre>", creds=creds)

# Bulk fetch (date range) - FIXED to use RequestDocs endpoint properly
@app.route("/fetch", methods=["GET","POST"])
def fetch():
    cfg = load_config()
    creds = load_credentials()
    preview = load_cache(limit=40)
    message = None
    error = None

    # default dates
    default_to = datetime.date.today().isoformat()
    default_from = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()

    env = cfg.get("MYDATA_ENV","sandbox")
    endpoints = endpoints_for_env(env)

    if request.method == "POST":
        date_from = request.form.get("date_from", default_from)
        date_to = request.form.get("date_to", default_to)
        vat = request.form.get("vat_number","").strip()
        selected_cred = request.form.get("use_credential","").strip()

        # resolve which credentials to use
        if selected_cred:
            sel = next((c for c in creds if c.get("name")==selected_cred), None)
            if sel:
                aade_user = sel.get("user","")
                aade_key = sel.get("key","")
                vat = vat or sel.get("vat","")
                env = sel.get("env", env)
                endpoints = endpoints_for_env(env)
        else:
            a_cfg = load_config()
            aade_user = a_cfg.get("AADE_USER_ID","")
            aade_key = a_cfg.get("AADE_SUBSCRIPTION_KEY","")

        # perform fetch - try utilities first if available
        try:
            fetched_list = []
            # If you have a helper in utils for bulk RequestDocs, prefer it (not assumed here)
            # Fallback: call the RequestDocs endpoint with dateFrom/dateTo (+ optional vatNumber)
            # Note: RequestDocs expects dates in dd/MM/YYYY
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
                # bubble up message to user with trimmed output
                raise Exception(f"API error {r.status_code}: {r.text[:800]}")

            # parse xml response (many shapes)
            parsed_outer = None
            try:
                parsed_outer = xmltodict.parse(r.text)
            except Exception:
                parsed_outer = None

            # extract docs list heuristically
            docs_list = []
            if isinstance(parsed_outer, dict):
                if "RequestedDoc" in parsed_outer:
                    maybe = parsed_outer.get("RequestedDoc")
                    docs_list = maybe if isinstance(maybe, list) else [maybe]
                elif "string" in parsed_outer:
                    inner = parsed_outer.get("string")
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
            preview = load_cache(limit=40)

        except Exception as e:
            app.logger.exception("fetch error")
            error = f"Σφάλμα λήψης: {e}"

    # pass many context vars so templates (yours) find what they expect
    context = {
        "credentials": creds,
        "preview": preview,
        "message": message,
        "error": error,
        "date_from": default_from,
        "date_to": default_to,
        "vat_default": os.getenv("ENTITY_VAT",""),
        "endpoint": endpoints["REQUESTDOCS_URL"],
        "env": env
    }
    if USE_TEMPLATES:
        try:
            return render_template("fetch.html", **context)
        except Exception:
            app.logger.exception("render fetch.html failed; falling back to inline")

    # fallback simple page
    return render_template_string("""
        <h1>Bulk Fetch</h1>
        {% if error %}<div style="color:red">{{error}}</div>{% endif %}
        {% if message %}<div style="color:green">{{message}}</div>{% endif %}
        <form method="post">
          Από: <input type="date" name="date_from" value="{{date_from}}"> Έως: <input type="date" name="date_to" value="{{date_to}}"><br>
          VAT: <input name="vat_number" value="{{vat_default}}"><br>
          <button>Fetch</button>
        </form>
        <h3>Preview (cached first items)</h3>
        <pre>{{ preview|tojson(indent=2) }}</pre>
    """, **context)

# Viewer: single MARK or file upload
@app.route("/viewer", methods=["GET","POST"])
def viewer():
    cfg = load_config()
    # ensure config present
    if not cfg.get("AADE_USER_ID") or not cfg.get("AADE_SUBSCRIPTION_KEY"):
        flash("Βάλε πρώτα τα AADE credentials στη σελίδα Ρυθμίσεις", "warning")
        return redirect(url_for("config"))

    payload = None
    raw = None
    summary = None
    message = None
    error = None

    if request.method == "POST":
        input_text = request.form.get("mark","").strip() or DEFAULT_MARK
        marks = []

        # file upload priority
        if "file" in request.files:
            f = request.files["file"]
            if f and f.filename:
                data = f.read()
                if UTIL_AVAILABLE and callable(decode_qr_from_file):
                    try:
                        m = decode_qr_from_file(data, f.filename)
                        if m:
                            marks = [m]
                    except Exception:
                        app.logger.exception("decode_qr error")
                # else fallback: no decode available

        # if no file or decode, handle input_text
        if not marks and input_text:
            # if input_text is URL -> try to extract marks from page via util or regex
            try:
                parsed_url = urlparse(input_text)
                if parsed_url.scheme in ("http","https") and parsed_url.netloc:
                    if UTIL_AVAILABLE and callable(extract_marks_from_url):
                        try:
                            marks = extract_marks_from_url(input_text) or []
                        except Exception:
                            app.logger.exception("extract_marks_from_url failed")
                            marks = []
                    else:
                        # fallback to simple GET + regex
                        try:
                            r = requests.get(input_text, timeout=20)
                            marks = list({m for m in __import__("re").findall(r"\b\d{14,15}\b", r.text)})
                        except Exception:
                            marks = []
                else:
                    if UTIL_AVAILABLE and callable(extract_marks_from_text):
                        try:
                            marks = extract_marks_from_text(input_text) or []
                        except Exception:
                            marks = []
                    else:
                        if input_text.isdigit() and len(input_text.strip()) in (14,15):
                            marks = [input_text.strip()]
            except Exception:
                marks = []

        # if still empty, set default MARK as requested
        if not marks:
            marks = [DEFAULT_MARK]

        successes, duplicates, api_errors = [], [], []
        last_summary = None
        last_payload = None
        last_raw = None

        env = cfg.get("MYDATA_ENV","sandbox")
        endpoints = endpoints_for_env(env)
        aade_user = cfg.get("AADE_USER_ID","")
        aade_key = cfg.get("AADE_SUBSCRIPTION_KEY","")

        for m in marks:
            # check transmitted first
            try:
                if is_mark_transmitted(m, aade_user, aade_key, endpoints["TRANSMITTED_URL"]):
                    api_errors.append((m, "το παραστατικο ειναι ηδη καταχωρημενο/χαρακτηρισμενο"))
                    continue
            except Exception:
                app.logger.exception("transmitted check error")

            # fetch by mark: prefer util function if present
            try:
                if UTIL_AVAILABLE and callable(fetch_by_mark):
                    err, parsed_obj, raw_xml, summ = fetch_by_mark(m, aade_user, aade_key, endpoints["REQUESTDOCS_URL"])
                else:
                    err = "No fetch_by_mark utility available"
                    parsed_obj = None; raw_xml = None; summ = None

                if err:
                    api_errors.append((m, err))
                    continue
                if not parsed_obj:
                    api_errors.append((m, "Empty response or parse error"))
                    continue

                # save summary row
                try:
                    vat_cats = extract_vat_categories(parsed_obj) if UTIL_AVAILABLE and callable(extract_vat_categories) else {}
                except Exception:
                    vat_cats = {}

                try:
                    saved = False
                    if UTIL_AVAILABLE and callable(save_summary_to_excel):
                        saved = save_summary_to_excel(summ, m, vat_categories=vat_cats)
                    else:
                        # csv fallback append
                        import csv
                        headless = not os.path.exists(EXCEL_FILE)
                        with open(EXCEL_FILE, "a", newline="", encoding="utf-8") as fh:
                            writer = csv.writer(fh)
                            if headless:
                                writer.writerow(list((summ or {"MARK":m}).keys()))
                            writer.writerow(list((summ or {"MARK":m}).values()))
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
                app.logger.exception("fetch_by_mark exception")
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
            error = "Απέτυχαν όλες προσπάθειες. Δες λεπτομέρειες στο μήνυμα."

    # pass big context so templates render identical UI
    context = {
        "env": load_config().get("MYDATA_ENV","sandbox"),
        "endpoint": endpoints_for_env(load_config().get("MYDATA_ENV","sandbox"))["REQUESTDOCS_URL"],
        "message": message,
        "error": error,
        "payload": payload,
        "raw": raw,
        "summary": summary,
        "default_mark": DEFAULT_MARK
    }

    if USE_TEMPLATES:
        try:
            return render_template("viewer.html", **context)
        except Exception:
            app.logger.exception("render viewer.html failed, falling back")

    # fallback:
    return render_template_string("<h1>Viewer</h1><form method='post'><input name='mark' value='{{default_mark}}'><button>Fetch</button></form>{% if message %}<pre>{{message}}</pre>{% endif %}{% if error %}<div style='color:red;'>{{error}}</div>{% endif %}", **context)

# list / download / delete routes (use EXCEL_FILE or cache fallback)
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
            table_html = table_html.replace("<td>", '<td><div style="white-space:pre-wrap;word-break:break-word;max-width:360px;">').replace("</td>", "</div></td>")
            headers = list(df.columns)
            num_indices = []
            for i,h in enumerate(headers):
                if any(k in h for k in ("Καθαρή Αξία","ΦΠΑ","Σύνολο","TOTAL","NET","VAT","ΠΟΣΟ")):
                    num_indices.append(i+1)
            css_rules = [f".summary-table td:nth-child({idx}), .summary-table th:nth-child({idx}) {{ text-align: right; }}" for idx in num_indices]
            css_numcols = "\n".join(css_rules)
        except Exception as e:
            app.logger.exception("read excel error")
            error = f"Σφάλμα ανάγνωσης Excel: {e}"
    else:
        cached = load_cache(limit=200)
        table_html = "<pre>" + json.dumps(cached, ensure_ascii=False, indent=2) + "</pre>" if cached else "<div>Δεν υπάρχουν εγγραφές.</div>"

    if USE_TEMPLATES:
        try:
            return render_template("list.html", table_html=table_html, error=error, file_exists=file_exists, css_numcols=css_numcols)
        except Exception:
            app.logger.exception("render list.html failed")
    return render_template_string("<h1>List</h1>{{table_html|safe}}", table_html=table_html)

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

@app.route("/health")
def health():
    return "OK"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG","0") in ("1","true","True")
    app.run(host="0.0.0.0", port=port, debug=debug)
