# app.py - updated: robust mydatanaut integration, dd/mm/yyyy handling, Flask/Markup fixes
import os
import sys
import json
import datetime
import traceback
import logging
from logging.handlers import RotatingFileHandler
from typing import Any, Dict, List, Optional

from flask import (
    Flask, render_template, request, redirect, url_for, send_file, flash
)
import requests
import xmltodict
import pandas as pd
from markupsafe import Markup, escape

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# vendor path for vendorized dependencies (eg. vendor/mydatanaut)
VENDOR_DIR = os.path.join(BASE_DIR, "vendor")
if VENDOR_DIR not in sys.path:
    sys.path.insert(0, VENDOR_DIR)

# Try import mydatanaut if vendorized
HAS_MYDATANAUT = False
mydatanaut_pkg = None
try:
    import importlib
    mydatanaut_pkg = importlib.import_module("mydatanaut")
    HAS_MYDATANAUT = True
except Exception:
    HAS_MYDATANAUT = False

# Directories
DATA_DIR = os.path.join(BASE_DIR, "data")
UPLOADS_DIR = os.path.join(BASE_DIR, "uploads")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(UPLOADS_DIR, exist_ok=True)

CACHE_FILE = os.path.join(DATA_DIR, "invoices_cache.json")
CREDENTIALS_FILE = os.path.join(DATA_DIR, "credentials.json")
EXCEL_FILE = os.path.join(UPLOADS_DIR, "invoices.xlsx")
ERROR_LOG = os.path.join(DATA_DIR, "error.log")

# ENV / endpoints
AADE_USER_ENV = os.getenv("AADE_USER_ID", "")
AADE_KEY_ENV = os.getenv("AADE_SUBSCRIPTION_KEY", "")
MYDATA_ENV = (os.getenv("MYDATA_ENV") or "sandbox").lower()

REQUESTDOCS_URL = (
    "https://mydataapidev.aade.gr/RequestDocs"
    if MYDATA_ENV in ("sandbox", "demo", "dev")
    else "https://mydatapi.aade.gr/myDATA/RequestDocs"
)
TRANSMITTED_URL = (
    "https://mydataapidev.aade.gr/RequestTransmittedDocs"
    if MYDATA_ENV in ("sandbox", "demo", "dev")
    else "https://mydatapi.aade.gr/myDATA/RequestTransmittedDocs"
)

app = Flask(__name__, template_folder=TEMPLATES_DIR)
# make datetime available in Jinja templates (fix for 'datetime' is undefined)
app.jinja_env.globals['datetime'] = datetime
app.secret_key = os.getenv("FLASK_SECRET", "change-me")

# Setup logging: stdout + rotating file
log = logging.getLogger("mydata_app")
log.setLevel(logging.INFO)
if not log.handlers:
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(sh)

    fh = RotatingFileHandler(ERROR_LOG, maxBytes=5*1024*1024, backupCount=3, encoding="utf-8")
    fh.setLevel(logging.INFO)
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s\n"))
    log.addHandler(fh)

log.info("App start - HAS_MYDATANAUT=%s MYDATA_ENV=%s", HAS_MYDATANAUT, MYDATA_ENV)


# ---------------- Utilities ----------------
def json_read(path: str):
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        log.exception("Failed to read JSON: %s", path)
        return []


def json_write(path: str, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def load_credentials():
    data = json_read(CREDENTIALS_FILE)
    return data if isinstance(data, list) else []


def save_credentials(creds):
    json_write(CREDENTIALS_FILE, creds)


def add_credential(entry):
    creds = load_credentials()
    for c in creds:
        if c.get("name") == entry.get("name"):
            return False, "Credential with that name exists"
    creds.append(entry)
    save_credentials(creds)
    return True, ""


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


# Cache helpers
def load_cache():
    data = json_read(CACHE_FILE)
    return data if isinstance(data, list) else []


def save_cache(docs):
    json_write(CACHE_FILE, docs)


def _extract_15digit_marks_from_obj(obj):
    import re
    marks = set()
    if obj is None:
        return marks
    if isinstance(obj, str):
        for m in re.findall(r"\b(\d{15})\b", obj):
            marks.add(m)
        return marks
    if isinstance(obj, (int, float)):
        s = str(int(obj)) if isinstance(obj, int) else str(obj)
        if re.fullmatch(r"\d{15}", s):
            marks.add(s)
        return marks
    if isinstance(obj, dict):
        for v in obj.values():
            marks.update(_extract_15digit_marks_from_obj(v))
    if isinstance(obj, list):
        for v in obj:
            marks.update(_extract_15digit_marks_from_obj(v))
    return marks


def append_doc_to_cache(doc, aade_user=None, aade_key=None):
    docs = load_cache()
    try:
        sig = json.dumps(doc, sort_keys=True, ensure_ascii=False)
    except Exception:
        sig = json.dumps(str(doc), ensure_ascii=False)
    for d in docs:
        try:
            if json.dumps(d, sort_keys=True, ensure_ascii=False) == sig:
                return False
        except Exception:
            if str(d) == str(doc):
                return False

    marks = _extract_15digit_marks_from_obj(doc)
    if marks:
        for m in marks:
            for d in docs:
                if m in _extract_15digit_marks_from_obj(d):
                    return False
        if aade_user and aade_key:
            for m in marks:
                try:
                    if is_mark_transmitted(m, aade_user, aade_key):
                        log.info("Skipping doc because mark %s already transmitted", m)
                        return False
                except Exception:
                    log.exception("transmitted-check failed for %s", m)

    docs.append(doc)
    save_cache(docs)
    return True


def doc_contains_mark_exact(doc, mark):
    if doc is None:
        return False
    if isinstance(doc, str):
        return doc.strip() == str(mark).strip()
    if isinstance(doc, (int, float)):
        return str(doc) == str(mark).strip()
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
    docs = load_cache()
    for doc in docs:
        if doc_contains_mark_exact(doc, mark):
            return doc
    return None


def is_mark_transmitted(mark, aade_user, aade_key):
    headers = {
        "aade-user-id": aade_user,
        "ocp-apim-subscription-key": aade_key,
        "Accept": "application/xml",
    }
    try:
        r = requests.get(TRANSMITTED_URL, params={"mark": mark}, headers=headers, timeout=30)
        if r.status_code >= 400:
            return False
        raw = r.text or ""
        if "invoiceMark" in raw or "invoiceUid" in raw or "<classification" in raw or "E3_" in raw or "VAT_" in raw:
            return True
    except Exception:
        log.exception("transmitted-check request failed")
    return False


# ---------------- Fetch implementations ----------------
def _ensure_ddmmyyyy(datestr: str) -> str:
    """
    Ensure returned string in DD/MM/YYYY.
    Accepts either DD/MM/YYYY or YYYY-MM-DD (HTML date input).
    """
    if not datestr:
        return datestr
    datestr = datestr.strip()
    # already dd/mm/yyyy?
    if len(datestr) == 10 and datestr[2] == '/' and datestr[5] == '/':
        return datestr
    # convert from iso yyyy-mm-dd
    try:
        if len(datestr) >= 10 and "-" in datestr:
            d = datetime.datetime.fromisoformat(datestr[:10])
            return d.strftime("%d/%m/%Y")
    except Exception:
        pass
    # fallback: return as-is (caller will handle)
    return datestr


def fetch_docs_with_mydatanaut(date_from: str, date_to: str, vat: str, aade_user: str, aade_key: str):
    """
    Attempt to use vendored mydatanaut package. Be defensive: try multiple common client names
    and multiple method names until something works. Return parsed docs (list or dict) or None.
    """
    if not HAS_MYDATANAUT:
        return None

    d1 = _ensure_ddmmyyyy(date_from)
    d2 = _ensure_ddmmyyyy(date_to)

    try:
        # try common client constructors
        client = None
        for clsname in ("MyDataClient", "Client", "ClientAPI"):
            try:
                ClientClass = getattr(mydatanaut_pkg, clsname, None) or getattr(getattr(mydatanaut_pkg, "mydata", {}), clsname, None)
                if ClientClass:
                    try:
                        client = ClientClass(user=aade_user, key=aade_key, env=MYDATA_ENV)
                        break
                    except TypeError:
                        # maybe names differ
                        try:
                            client = ClientClass(aade_user, aade_key, MYDATA_ENV)
                            break
                        except Exception:
                            client = None
            except Exception:
                client = None

        # last attempt: mydatanaut.mydata.MyDataClient
        if client is None:
            try:
                mmod = getattr(mydatanaut_pkg, "mydata", None)
                if mmod and hasattr(mmod, "MyDataClient"):
                    ClientClass = getattr(mmod, "MyDataClient")
                    try:
                        client = ClientClass(user=aade_user, key=aade_key, env=MYDATA_ENV)
                    except Exception:
                        try:
                            client = ClientClass(aade_user, aade_key, MYDATA_ENV)
                        except Exception:
                            client = None
            except Exception:
                client = None

        if client is None:
            log.info("mydatanaut available but no usable client found")
            return None

        # try several possible API method names
        tried = []
        for method_name in (
            "request_docs", "requestDocuments", "requestDocs", "fetch_docs",
            "fetchDocuments", "get_docs", "get_documents", "request_documents_range",
            "request_docs_range", "requestDocsRange", "docs", "documents", "request_documents"
        ):
            if hasattr(client, method_name):
                tried.append(method_name)
                method = getattr(client, method_name)
                try:
                    # try common signatures
                    # 1) (date_from, date_to, vat)
                    try:
                        res = method(d1, d2, vat)
                        return res
                    except TypeError:
                        pass
                    # 2) named args
                    try:
                        res = method(dateFrom=d1, dateTo=d2, vatNumber=vat)
                        return res
                    except TypeError:
                        pass
                    try:
                        res = method(date_from=d1, date_to=d2, vat=vat)
                        return res
                    except TypeError:
                        pass
                    # 3) pass dict
                    try:
                        res = method({"dateFrom": d1, "dateTo": d2, "vatNumber": vat})
                        return res
                    except TypeError:
                        pass
                except Exception:
                    log.exception("mydatanaut method %s failed", method_name)
                    continue
        log.info("mydatanaut client present but none of tried methods (%s) returned results", tried)
    except Exception:
        log.exception("mydatanaut integration failed")
    return None


def fetch_docs_via_requestdocs(date_from, date_to, vat, aade_user, aade_key):
    # ensure dd/mm/yyyy format
    d1 = _ensure_ddmmyyyy(date_from)
    d2 = _ensure_ddmmyyyy(date_to)
    params = {"dateFrom": d1, "dateTo": d2}
    if vat:
        params["vatNumber"] = vat
    headers = {
        "aade-user-id": aade_user or "",
        "ocp-apim-subscription-key": aade_key or "",
        "Accept": "application/xml",
    }
    r = requests.get(REQUESTDOCS_URL, params=params, headers=headers, timeout=60)
    if r.status_code >= 400:
        raise Exception(f"API error {r.status_code}: {r.text[:1000]}")
    try:
        parsed_outer = xmltodict.parse(r.text)
        # unwrap nested <string> wrapper if exists
        if isinstance(parsed_outer, dict) and "string" in parsed_outer:
            s = parsed_outer.get("string")
            inner = None
            if isinstance(s, dict) and "#text" in s:
                inner = s["#text"]
            elif isinstance(s, str):
                inner = s
            if inner:
                try:
                    return xmltodict.parse(inner)
                except Exception:
                    return inner
        return parsed_outer
    except Exception:
        return r.text


# ---------------- Robust template rendering ----------------
def safe_render(template_name: str, **ctx):
    """
    Try to render template; if an exception occurs (missing template, Jinja error),
    log it and return a simple fallback HTML with the error (and stacktrace if debug).
    """
    try:
        return render_template(template_name, **ctx)
    except Exception as e:
        tb = traceback.format_exc()
        log.error("Template rendering failed for %s: %s\n%s", template_name, str(e), tb)
        debug = os.getenv("FLASK_DEBUG", "0") == "1"
        body = "<h2>Template error</h2><p>" + escape(str(e)) + "</p>"
        if debug:
            body += "<pre>" + escape(tb) + "</pre>"
        # keep the app alive with minimal UI
        return Markup(body)


# ---------------- Routes ----------------
@app.route("/")
def home():
    return safe_render("nav.html")


# Credentials management
@app.route("/credentials", methods=["GET", "POST"])
def credentials():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        user = request.form.get("user", "").strip()
        key = request.form.get("key", "").strip()
        env = request.form.get("env", MYDATA_ENV).strip()
        vat = request.form.get("vat", "").strip()
        if not name:
            flash("Name required", "error")
        else:
            ok, err = add_credential({"name": name, "user": user, "key": key, "env": env, "vat": vat})
            if ok:
                flash("Saved", "success")
            else:
                flash(err or "Could not save", "error")
        return redirect(url_for("credentials"))
    creds = load_credentials()
    return safe_render("credentials_list.html", credentials=creds)


@app.route("/credentials/edit/<name>", methods=["GET", "POST"])
def credentials_edit(name):
    creds = load_credentials()
    credential = next((c for c in creds if c.get("name") == name), None)
    if not credential:
        flash("Credential not found", "error")
        return redirect(url_for("credentials"))
    if request.method == "POST":
        user = request.form.get("user", "").strip()
        key = request.form.get("key", "").strip()
        env = request.form.get("env", MYDATA_ENV).strip()
        vat = request.form.get("vat", "").strip()
        new = {"name": name, "user": user, "key": key, "env": env, "vat": vat}
        update_credential(name, new)
        flash("Updated", "success")
        return redirect(url_for("credentials"))
    return safe_render("credentials_edit.html", credential=credential)


@app.route("/credentials/delete/<name>", methods=["POST"])
def credentials_delete(name):
    delete_credential(name)
    flash("Deleted", "success")
    return redirect(url_for("credentials"))


# Fetch (bulk)
@app.route("/fetch", methods=["GET", "POST"])
def fetch():
    message = None
    error = None
    creds = load_credentials()
    preview = load_cache()[:40]

    if request.method == "POST":
        # Accept user dates in DD/MM/YYYY (preferred) OR YYYY-MM-DD (html date)
        date_from = request.form.get("date_from", "").strip()
        date_to = request.form.get("date_to", "").strip()
        # if user used html date inputs they may be ISO -> _ensure_ddmmyyyy will convert
        selected = request.form.get("use_credential") or ""
        vat = request.form.get("vat_number", "").strip()
        aade_user = AADE_USER_ENV
        aade_key = AADE_KEY_ENV
        if selected:
            c = next((x for x in creds if x.get("name") == selected), None)
            if c:
                aade_user = c.get("user", "") or aade_user
                aade_key = c.get("key", "") or aade_key
                vat = vat or c.get("vat", "")

        if not date_from or not date_to:
            error = "Παρακαλώ συμπλήρωσε από-έως ημερομηνίες."
            return safe_render("fetch.html", credentials=creds, message=message, error=error, preview=preview)

        try:
            res = None
            if HAS_MYDATANAUT:
                try:
                    res = fetch_docs_with_mydatanaut(date_from, date_to, vat, aade_user, aade_key)
                except Exception:
                    log.exception("mydatanaut failed")

            if res is None:
                parsed = fetch_docs_via_requestdocs(date_from, date_to, vat, aade_user, aade_key)
                docs_list = []
                if isinstance(parsed, dict):
                    if "RequestedDoc" in parsed:
                        maybe = parsed.get("RequestedDoc")
                        docs_list = maybe if isinstance(maybe, list) else [maybe]
                    elif "docs" in parsed:
                        docs_list = parsed.get("docs") or []
                    else:
                        # try find list children
                        found = False
                        for k, v in parsed.items():
                            if isinstance(v, list):
                                docs_list = v
                                found = True
                                break
                        if not found:
                            docs_list = [parsed]
                elif isinstance(parsed, list):
                    docs_list = parsed
                else:
                    docs_list = []
                added = 0
                for d in docs_list:
                    if append_doc_to_cache(d, aade_user or None, aade_key or None):
                        added += 1
                message = f"Fetched {len(docs_list)} items, newly cached: {added}"
            else:
                docs = res if isinstance(res, list) else (res.get("docs") if isinstance(res, dict) else [res])
                added = 0
                for d in docs:
                    if append_doc_to_cache(d, aade_user or None, aade_key or None):
                        added += 1
                message = f"Fetched {len(docs)} items via mydatanaut, newly cached: {added}"
            preview = load_cache()[:40]
        except Exception as e:
            log.exception("Fetch error")
            # surface helpful message for auth/403 issues
            if isinstance(e, Exception) and "403" in str(e):
                error = f"Σφάλμα λήψης: API error 403: Έλεγξε τα credentials (aade-user-id / subscription key) και το περιβάλλον (sandbox/production)."
            else:
                error = f"Σφάλμα λήψης: {e}"

    return safe_render("fetch.html", credentials=creds, message=message, error=error, preview=preview)


# Search by MARK exact
@app.route("/search", methods=["GET", "POST"])
def search():
    result = None
    error = None
    mark = ""
    if request.method == "POST":
        mark = request.form.get("mark", "").strip()
        if not mark or not mark.isdigit() or len(mark) != 15:
            error = "Πρέπει να δώσεις έγκυρο 15ψήφιο MARK."
        else:
            doc = find_invoice_by_mark_exact(mark)
            if not doc:
                error = f"MARK {mark} όχι στην cache. Κάνε πρώτα Bulk Fetch."
            else:
                result = doc
    return safe_render("search.html", result=result, error=error, mark=mark)


# Save summary to Excel (expects JSON string in summary_json)
@app.route("/save_excel", methods=["POST"])
def save_excel():
    summ_json = request.form.get("summary_json")
    if summ_json:
        try:
            row = json.loads(summ_json)
            df = pd.DataFrame([row])
            if os.path.exists(EXCEL_FILE):
                try:
                    df_existing = pd.read_excel(EXCEL_FILE, engine="openpyxl", dtype=str)
                    df_concat = pd.concat([df_existing, df], ignore_index=True, sort=False)
                    df_concat.to_excel(EXCEL_FILE, index=False, engine="openpyxl")
                except Exception:
                    df.to_csv(EXCEL_FILE, mode="a", index=False, header=not os.path.exists(EXCEL_FILE))
            else:
                try:
                    df.to_excel(EXCEL_FILE, index=False, engine="openpyxl")
                except Exception:
                    df.to_csv(EXCEL_FILE, index=False)
            flash("Saved to Excel", "success")
        except Exception as e:
            log.exception("Excel save error")
            flash(f"Excel save error: {e}", "error")
    return redirect(url_for("search"))


# List / download
@app.route("/list")
def list_invoices():
    if request.args.get("download") and os.path.exists(EXCEL_FILE):
        return send_file(EXCEL_FILE, as_attachment=True, download_name="invoices.xlsx")
    table = []
    if os.path.exists(EXCEL_FILE):
        try:
            df = pd.read_excel(EXCEL_FILE, engine="openpyxl", dtype=str).fillna("")
            table = df.to_dict(orient="records")
        except Exception:
            log.exception("Failed to read Excel - fallback to cache")
            table = load_cache()
    else:
        table = load_cache()
    return safe_render("list.html", table=table)


# Cron protected
@app.route("/cron_fetch")
def cron_fetch():
    secret = request.args.get("secret", "")
    CRON_SECRET = os.getenv("CRON_SECRET", "")
    if not CRON_SECRET or secret != CRON_SECRET:
        return ("Forbidden", 403)
    creds = load_credentials()
    if creds:
        aade_user = creds[0].get("user", "")
        aade_key = creds[0].get("key", "")
        vat = creds[0].get("vat", "")
    else:
        aade_user = AADE_USER_ENV
        aade_key = AADE_KEY_ENV
        vat = os.getenv("ENTITY_VAT", "")
    d1 = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()
    d2 = datetime.date.today().isoformat()
    try:
        parsed = fetch_docs_via_requestdocs(d1, d2, vat, aade_user, aade_key)
        docs_list = []
        if isinstance(parsed, dict):
            if "RequestedDoc" in parsed:
                maybe = parsed["RequestedDoc"]
                docs_list = maybe if isinstance(maybe, list) else [maybe]
            else:
                docs_list = [parsed]
        elif isinstance(parsed, list):
            docs_list = parsed
        added = 0
        for d in docs_list:
            if append_doc_to_cache(d, aade_user or None, aade_key or None):
                added += 1
        return f"Cron fetch done. New: {added}\n"
    except Exception as e:
        log.exception("Cron fetch error")
        return (f"Cron fetch error: {e}", 500)


# Diagnostics: return last error log (protected by debug or CRON_SECRET)
@app.route("/last_error")
def last_error():
    if os.getenv("FLASK_DEBUG", "0") == "1":
        if os.path.exists(ERROR_LOG):
            try:
                with open(ERROR_LOG, "r", encoding="utf-8") as f:
                    data = f.read()[-20000:]
                return "<pre>" + escape(data) + "</pre>"
            except Exception:
                return "Could not read error log", 500
        return "No error log", 200
    # else require secret
    secret = request.args.get("secret", "")
    if secret and secret == os.getenv("CRON_SECRET", ""):
        try:
            with open(ERROR_LOG, "r", encoding="utf-8") as f:
                data = f.read()[-20000:]
            return "<pre>" + escape(data) + "</pre>"
        except Exception:
            return "Could not read error log", 500
    return ("Forbidden", 403)


@app.route("/health")
def health():
    return "OK"


# Global error handler — logs stacktrace and shows friendly page (or traceback if debug)
@app.errorhandler(Exception)
def handle_unexpected_error(e):
    tb = traceback.format_exc()
    log.error("Unhandled exception: %s\n%s", str(e), tb)
    # also append to error.log explicitly
    try:
        with open(ERROR_LOG, "a", encoding="utf-8") as ef:
            ef.write(f"\n\n{datetime.datetime.utcnow().isoformat()} - {str(e)}\n{tb}\n")
    except Exception:
        log.exception("Could not write to error log")

    debug = os.getenv("FLASK_DEBUG", "0") == "1"
    if debug:
        # show full traceback in browser (temporary debug only)
        return "<h2>Server Error (debug)</h2><pre>{}</pre>".format(escape(tb)), 500
    else:
        # user-friendly generic page
        return safe_render("error_generic.html", message="Συνέβη σφάλμα στον server. Δες logs."), 500


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    debug_flag = os.getenv("FLASK_DEBUG", "0") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug_flag)
