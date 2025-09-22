# app.py
import os
import sys
import json
import re
import datetime
import traceback
from urllib.parse import urlparse
from dotenv import load_dotenv
from flask import (
    Flask, request, render_template_string, url_for, send_file,
    redirect, session, flash
)
import pandas as pd

# --- Ensure project root / paths ---
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
UPLOADS_DIR = os.path.join(BASE_DIR, "uploads")
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(UPLOADS_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

# --- Import helpers from utils (must exist) ---
# utils should provide the functions used below
try:
    from utils import (
        extract_marks_from_url, extract_mark, decode_qr_from_file,
        extract_vat_categories, summarize_invoice, format_euro_str,
        is_mark_transmitted as util_is_mark_transmitted,
        fetch_by_mark, save_summary_to_excel as util_save_summary_to_excel,
        extract_marks_from_text
    )
except Exception as e:
    # Defensive fallback: if utils can't be imported, log and continue;
    # routes will fail more gracefully with error messages.
    print("WARNING: could not import utils:", e)
    extract_marks_from_url = None
    extract_mark = None
    decode_qr_from_file = None
    extract_vat_categories = None
    summarize_invoice = None
    format_euro_str = None
    util_is_mark_transmitted = None
    fetch_by_mark = None
    util_save_summary_to_excel = None
    extract_marks_from_text = None

# Local EXCEL_FILE path (consistent usage across app)
EXCEL_FILE = os.path.join(UPLOADS_DIR, "invoices.xlsx")
CONFIG_FILE = os.path.join(UPLOADS_DIR, "config.json")
CACHE_FILE = os.path.join(DATA_DIR, "invoices_cache.json")
CREDENTIALS_FILE = os.path.join(DATA_DIR, "credentials.json")

# load .env if present
load_dotenv()

# --- Flask app (single instance) ---
app = Flask(__name__, template_folder=TEMPLATES_DIR)
app.secret_key = os.getenv("FLASK_SECRET", "change-me")
# expose datetime to templates (fixes 'datetime is undefined')
app.jinja_env.globals['datetime'] = datetime

# Upload config (for compatibility with older code)
app.config["UPLOAD_FOLDER"] = UPLOADS_DIR

# --- Config helpers ---
def load_config_file():
    cfg = {}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception as e:
            print("Could not read config file:", e)
    # fallback to env vars if keys missing
    cfg.setdefault("AADE_USER_ID", os.getenv("AADE_USER_ID", ""))
    cfg.setdefault("AADE_SUBSCRIPTION_KEY", os.getenv("AADE_SUBSCRIPTION_KEY", ""))
    cfg.setdefault("MYDATA_ENV", os.getenv("MYDATA_ENV", "sandbox"))
    return cfg

def save_config_file(cfg):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print("Could not write config file:", e)
        return False

# credentials store (list)
def load_credentials():
    if os.path.exists(CREDENTIALS_FILE):
        try:
            with open(CREDENTIALS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
        except Exception:
            return []
    return []

def save_credentials(creds):
    try:
        with open(CREDENTIALS_FILE, "w", encoding="utf-8") as f:
            json.dump(creds, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print("save_credentials error:", e)
        return False

def add_credential(entry):
    creds = load_credentials()
    # dedupe by name
    for c in creds:
        if c.get("name") == entry.get("name"):
            return False, "Credential with that name exists"
    creds.append(entry)
    save_credentials(creds)
    return True, None

def update_credential(name, new_entry):
    creds = load_credentials()
    for i, c in enumerate(creds):
        if c.get("name") == name:
            creds[i] = new_entry
            save_credentials(creds)
            return True
    return False

def delete_credential(name):
    creds = load_credentials()
    new = [c for c in creds if c.get("name") != name]
    save_credentials(new)
    return True

# --- Cache helpers (simple JSON file) ---
def load_cache():
    if not os.path.exists(CACHE_FILE):
        return []
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception:
        return []

def save_cache(docs):
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(docs, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print("save_cache error:", e)
        return False

def append_doc_to_cache(doc):
    docs = load_cache()
    # use canonical JSON string as signature
    try:
        sig = json.dumps(doc, sort_keys=True, ensure_ascii=False)
    except Exception:
        sig = str(doc)
    for d in docs:
        try:
            if json.dumps(d, sort_keys=True, ensure_ascii=False) == sig:
                return False
        except Exception:
            if str(d) == sig:
                return False
    docs.append(doc)
    save_cache(docs)
    return True

def doc_contains_mark_exact(doc, mark):
    if doc is None:
        return False
    if isinstance(doc, (str, int, float)):
        return str(doc).strip() == str(mark).strip()
    if isinstance(doc, dict):
        for v in doc.values():
            if doc_contains_mark_exact(v, mark):
                return True
    if isinstance(doc, list):
        for v in doc:
            if doc_contains_mark_exact(v, mark):
                return True
    return False

def find_invoice_by_mark_exact(mark):
    for doc in load_cache():
        try:
            if doc_contains_mark_exact(doc, mark):
                return doc
        except Exception:
            continue
    return None

# --- Endpoint builders (based on config env) ---
def endpoints_for_env(env):
    env = (env or "sandbox").lower()
    if env in ("sandbox", "dev", "demo"):
        base = "https://mydataapidev.aade.gr/myDATA"
    else:
        base = "https://mydatapi.aade.gr/myDATA"
    return {
        "REQUESTDOCS": f"{base}/RequestDocs",
        "TRANSMITTED": f"{base}/RequestTransmittedDocs"
    }

# --- HTML templates (we reuse the ones you provided via strings) ---
# For brevity I will refer to your existing template-strings (NAV_HTML, VIEWER_HTML, etc.)
# If your repo already has /templates/*.html you can switch to render_template instead.
# For compatibility we will use render_template_string with your templates if templates folder missing.

# attempt to load template files if available under templates/
def load_template_file(name, default):
    path = os.path.join(TEMPLATES_DIR, name)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            pass
    return default

# Load templates from files if present, else use your embedded strings.
# (Assumes NAV_HTML, VIEWER_HTML, LIST_HTML, CONFIG_HTML, PLACEHOLDER_HTML defined in your repo)
# To keep this file self-contained, try to import them from a 'templates_bundle' module if present.
try:
    # if you have a Python module that defines the template strings, you can import it
    from templates_bundle import NAV_HTML, VIEWER_HTML, LIST_HTML, CONFIG_HTML, PLACEHOLDER_HTML
except Exception:
    # fallback to reading files or minimal placeholders
    NAV_HTML = load_template_file("nav.html", """<!doctype html><html><body><h1>myDATA</h1><p><a href="{{ url_for('viewer') }}">Viewer</a></p></body></html>""")
    VIEWER_HTML = load_template_file("viewer.html", """<!doctype html><html><body><h1>Viewer</h1>{% if message %}<pre>{{ message }}</pre>{% endif %}</body></html>""")
    LIST_HTML = load_template_file("list.html", """<!doctype html><html><body><h1>List</h1>{{ table_html | safe }}</body></html>""")
    CONFIG_HTML = load_template_file("config.html", """<!doctype html><html><body><h1>Config</h1></body></html>""")
    PLACEHOLDER_HTML = load_template_file("placeholder.html", """<!doctype html><html><body><h1>{{ title }}</h1><p>{{ message }}</p></body></html>""")

# But if your repo already included the long template strings you showed earlier in the conversation,
# they will be used (the code above loads from /templates/* or templates_bundle if present).

# ---------------- Routes ----------------

@app.route("/")
def home():
    # show main menu (use NAV_HTML)
    return render_template_string(NAV_HTML)

@app.route("/config", methods=["GET", "POST"])
def config():
    # save config to CONFIG_FILE (uploads/config.json)
    if request.method == "POST":
        user = request.form.get("aade_user_id", "").strip()
        key = request.form.get("aade_subscription_key", "").strip()
        env = request.form.get("mydata_env", "sandbox").strip()
        cfg = {"AADE_USER_ID": user, "AADE_SUBSCRIPTION_KEY": key, "MYDATA_ENV": env}
        ok = save_config_file(cfg)
        if not ok:
            return "Error saving config", 500
        return redirect(url_for("home"))
    # GET -> show form with existing values
    cfg = load_config_file()
    return render_template_string(CONFIG_HTML, config=cfg)

@app.route("/viewer", methods=["GET", "POST"])
def viewer():
    # load config first (if missing, redirect to config)
    cfg = load_config_file()
    AADE_USER = cfg.get("AADE_USER_ID", "")
    AADE_KEY = cfg.get("AADE_SUBSCRIPTION_KEY", "")
    ENV = cfg.get("MYDATA_ENV", "sandbox").lower()
    endpoints = endpoints_for_env(ENV)
    REQUESTDOCS_URL = endpoints["REQUESTDOCS"]
    TRANSMITTED_URL = endpoints["TRANSMITTED"]

    # if not configured, redirect user to config page
    if not AADE_USER or not AADE_KEY:
        return redirect(url_for("config"))

    error = None
    message = None
    payload = None
    raw = None
    summary = None

    if request.method == "POST":
        input_text = request.form.get("mark", "").strip()
        marks = []

        # 1) file uploaded?
        if "file" in request.files:
            f = request.files["file"]
            if f and f.filename:
                try:
                    data = f.read()
                    if decode_qr_from_file:
                        mark_from_file = decode_qr_from_file(data, f.filename)
                    else:
                        mark_from_file = None
                    if mark_from_file:
                        marks = [mark_from_file]
                    else:
                        # optional: try to extract marks from text file content
                        try:
                            text = data.decode("utf-8", errors="ignore")
                            if extract_marks_from_text:
                                marks = extract_marks_from_text(text)
                        except Exception:
                            pass
                        if not marks:
                            error = "Δεν βρέθηκε ΜΑΡΚ στο αρχείο."
                except Exception as e:
                    error = f"Upload processing error: {e}"

        # 2) input text (url or mark)
        if not marks and input_text:
            try:
                parsed = urlparse(input_text)
                if parsed.scheme in ("http", "https") and parsed.netloc:
                    # try to extract marks from URL / page
                    if extract_marks_from_url:
                        try:
                            marks = extract_marks_from_url(input_text)
                        except Exception as e:
                            print("extract_marks_from_url error:", e)
                            marks = []
                    else:
                        marks = []
                    if not marks:
                        # maybe the URL contains a GET param with mark
                        q = parsed.query or ""
                        from urllib.parse import parse_qs
                        params = parse_qs(q)
                        for k, vals in params.items():
                            for v in vals:
                                if re.fullmatch(r"\d{15}", v):
                                    marks.append(v)
                else:
                    # plain mark(s) in text
                    if extract_marks_from_text:
                        marks = extract_marks_from_text(input_text)
                    else:
                        # fallback: any 15-digit sequences
                        marks = re.findall(r"\d{15}", input_text)
            except Exception as e:
                print("input_text parsing error:", e)
                marks = re.findall(r"\d{15}", input_text)

        if not marks:
            if not error:
                error = "Δεν βρέθηκε ΜΑΡΚ. Δώσε έγκυρο 15ψήφιο MARK, URL ή ανέβασε αρχείο."
        else:
            successes = []
            duplicates = []
            api_errors = []
            last_summary = None
            last_payload = None
            last_raw = None

            # iterate found marks
            for m in marks:
                m = str(m).strip()
                if not re.fullmatch(r"\d{15}", m):
                    api_errors.append((m, "Μη έγκυρο MARK (πρέπει να είναι 15 ψηφία)"))
                    continue

                # check transmitted status using util_is_mark_transmitted if available
                try:
                    transmitted = False
                    if util_is_mark_transmitted:
                        # try both signature styles defensively
                        try:
                            transmitted = util_is_mark_transmitted(m, AADE_USER, AADE_KEY, TRANSMITTED_URL)
                        except TypeError:
                            try:
                                transmitted = util_is_mark_transmitted(m, AADE_USER, AADE_KEY)
                            except Exception:
                                transmitted = False
                    else:
                        transmitted = False
                except Exception as e:
                    print("is_mark_transmitted internal error:", e)
                    transmitted = False

                if transmitted:
                    api_errors.append((m, "Το παραστατικό φέρεται ως ήδη καταχωρημένο/χαρακτηρισμένο"))
                    continue

                # fetch by mark using fetch_by_mark from utils (signature: mark, user, key, requestdocs_url)
                try:
                    if not fetch_by_mark:
                        api_errors.append((m, "fetch_by_mark helper όχι διαθέσιμο"))
                        continue
                    # fetch_by_mark should return (err, parsed, raw_xml, summary_dict) per your previous code
                    try:
                        err, parsed, raw_xml, summ = fetch_by_mark(m, AADE_USER, AADE_KEY, REQUESTDOCS_URL)
                    except TypeError:
                        # fallback signature older/newer
                        result = fetch_by_mark(m, AADE_USER, AADE_KEY)
                        # try to normalize result
                        if isinstance(result, tuple) and len(result) >= 4:
                            err, parsed, raw_xml, summ = result[0], result[1], result[2], result[3]
                        else:
                            err = "Unexpected fetch_by_mark result"
                            parsed = None; raw_xml = None; summ = None

                except Exception as e:
                    tb = traceback.format_exc()
                    print("fetch_by_mark exception:", tb)
                    api_errors.append((m, f"Exception during fetch_by_mark: {e}"))
                    continue

                if err:
                    api_errors.append((m, err))
                    continue
                if not parsed or not summ:
                    api_errors.append((m, "Κενά δεδομένα μετά την ανάκτηση/παράσιξη"))
                    continue

                # extract vat categories (best-effort)
                try:
                    vat_cats = extract_vat_categories(parsed) if extract_vat_categories else {}
                except Exception:
                    vat_cats = {}

                # attempt to save summary to excel / CSV using util_save_summary_to_excel
                try:
                    saved = False
                    if util_save_summary_to_excel:
                        try:
                            # try both possible signatures: (summary, mark, vat_categories=...)
                            saved = util_save_summary_to_excel(summ, m, vat_categories=vat_cats)
                        except TypeError:
                            # try (excel_file, summary_row) style
                            try:
                                saved = util_save_summary_to_excel(summ)
                            except Exception:
                                saved = False
                    else:
                        # fallback: append to EXCEL as csv if openpyxl unavailable
                        # create a simple CSV append
                        row = summ if isinstance(summ, dict) else {"MARK": m}
                        csv_path = EXCEL_FILE
                        header_needed = not os.path.exists(csv_path)
                        cols = list(row.keys())
                        import csv
                        with open(csv_path, "a", newline="", encoding="utf-8") as cf:
                            writer = csv.DictWriter(cf, fieldnames=cols)
                            if header_needed:
                                writer.writeheader()
                            writer.writerow(row)
                        saved = True
                except Exception as e:
                    print("save summary error:", e)
                    saved = False

                if saved:
                    successes.append(m)
                else:
                    # if not saved because duplicate, record duplicate; otherwise record error
                    # We attempt to detect duplicate by looking into EXCEL_FILE or cache
                    already = False
                    # check excel
                    try:
                        if os.path.exists(EXCEL_FILE):
                            df = pd.read_excel(EXCEL_FILE, engine="openpyxl", dtype=str).fillna("")
                            if "MARK" in df.columns and str(m) in df["MARK"].astype(str).tolist():
                                already = True
                    except Exception:
                        pass
                    # check cache too
                    if not already:
                        if find_invoice_by_mark_exact(m):
                            already = True
                    if already:
                        duplicates.append(m)
                    else:
                        api_errors.append((m, "Αποτυχία αποθήκευσης (άγνωστη αιτία)"))

                last_summary = summ
                last_payload = json.dumps(parsed, ensure_ascii=False, indent=2)
                last_raw = raw_xml

            # prepare message
            parts = []
            if successes:
                parts.append(f"Αποθηκεύτηκαν: {len(successes)} ({', '.join(successes)})")
            if duplicates:
                parts.append(f"Διπλοεγγραφές (παραλήφθηκαν): {len(duplicates)} ({', '.join(duplicates)})")
            if api_errors:
                parts.append(f"Σφάλματα/Μηνύματα: {len(api_errors)}")
                # include first 12 errors for display
                for m, e in api_errors[:12]:
                    parts.append(f"- {m}: {e}")
            message = "\n".join(parts) if parts else None

            if last_summary:
                summary = last_summary
                payload = last_payload
                raw = last_raw

            if not successes and not duplicates and api_errors and not summary:
                error = "Απέτυχαν όλες οι προσπάθειες. Δες λεπτομέρειες στο μήνυμα."

    # render viewer template string (either from file or bundled string)
    return render_template_string(
        VIEWER_HTML,
        error=error,
        payload=payload,
        raw=raw,
        summary=summary,
        env=ENV,
        endpoint=REQUESTDOCS_URL,
        message=message
    )

@app.route("/list", methods=["GET"])
def list_invoices():
    filepath = EXCEL_FILE
    table_html = ""
    error = ""
    css_numcols = ""

    if os.path.exists(filepath):
        try:
            df = pd.read_excel(filepath, engine="openpyxl", dtype=str).fillna("")
            df = df.astype(str)

            # Drop technical columns if present
            if "ΦΠΑ_ΑΝΑΛΥΣΗ" in df.columns:
                df = df.drop(columns=["ΦΠΑ_ΑΝΑΛΥΣΗ"])

            # Add checkboxes column using MARK if available
            if "MARK" in df.columns:
                checkboxes = df["MARK"].apply(lambda v: f'<input type="checkbox" name="delete_mark" value="{str(v)}">')
                df.insert(0, "✓", checkboxes)

            table_html = df.to_html(classes="summary-table", index=False, escape=False)

            # Replace header for checkbox
            table_html = table_html.replace("<th>✓</th>", '<th><input type="checkbox" id="selectAll" title="Επιλογή όλων"></th>')

            # wrap cells
            table_html = table_html.replace("<td>", '<td><div class="cell-wrap">').replace("</td>", "</div></td>")

            # numeric alignment heuristics
            headers = re.findall(r'<th[^>]*>(.*?)</th>', table_html, flags=re.S)
            num_indices = []
            for i, h in enumerate(headers):
                text = re.sub(r'<.*?>', '', h).strip()
                if text in ("Καθαρή Αξία", "ΦΠΑ", "Σύνολο", "Total", "Net", "VAT") or "ΦΠΑ" in text or "ΠΟΣΟ" in text:
                    num_indices.append(i+1)
            css_rules = []
            for idx in num_indices:
                css_rules.append(f".summary-table td:nth-child({idx}), .summary-table th:nth-child({idx}) {{ text-align: right; }}")
            css_numcols = "\n".join(css_rules)

        except Exception as e:
            error = f"Σφάλμα ανάγνωσης Excel: {e}"
    else:
        error = "Δεν βρέθηκε το αρχείο invoices.xlsx."

    return render_template_string(
        LIST_HTML,
        table_html=table_html,
        error=error,
        file_exists=os.path.exists(filepath),
        css_numcols=css_numcols
    )

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
        except Exception as e:
            print("Delete invoices error:", e)

    return redirect(url_for("list_invoices"))

@app.route("/download", methods=["GET"])
def download_excel():
    if not os.path.exists(EXCEL_FILE):
        return ("Το αρχείο .xlsx δεν υπάρχει.", 404)
    return send_file(
        EXCEL_FILE,
        as_attachment=True,
        download_name="invoices.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

@app.route("/credentials", methods=["GET", "POST"])
def credentials_page():
    msg = None
    if request.method == "POST":
        name = request.form.get("name","").strip()
        user = request.form.get("user","").strip()
        key = request.form.get("key","").strip()
        env = request.form.get("env","sandbox").strip()
        vat = request.form.get("vat","").strip()
        if not name:
            msg = ("error","Name required")
        else:
            ok, err = add_credential({"name":name,"user":user,"key":key,"env":env,"vat":vat})
            msg = ("success","Saved") if ok else ("error", err or "Could not save")
    creds = load_credentials()
    # simple HTML listing (if you have template file use render_template instead)
    html = "<h1>Credentials</h1><p><a href='/'>Back</a></p><ul>"
    for c in creds:
        html += f"<li><strong>{c.get('name')}</strong> - VAT: {c.get('vat','')}</li>"
    html += "</ul>"
    return html

@app.route("/health")
def health():
    return "OK"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    # debug False for Render; set True locally if you want debug
    app.run(host="0.0.0.0", port=port, debug=False)
