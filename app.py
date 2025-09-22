# app.py - improved debugging & robust rendering for your myDATA app (mydatanaut integrated)
import os
import sys
import json
import datetime
import traceback
import logging
from logging.handlers import RotatingFileHandler
from typing import Any, Dict, List, Optional

from flask import Flask, render_template, request, redirect, url_for, send_file, flash
from markupsafe import Markup

import requests
import xmltodict
import pandas as pd

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

DEFAULT_MARK = "12345678901234"

app = Flask(__name__, template_folder=TEMPLATES_DIR)
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
def fetch_docs_with_mydatanaut(date_from, date_to, vat, aade_user, aade_key):
    """Fetch using vendorized mydatanaut"""
    if not HAS_MYDATANAUT:
        return None
    try:
        client = mydatanaut_pkg.Client(user=aade_user, key=aade_key, env=MYDATA_ENV)
        docs = client.bulk_fetch(
            date_from=date_from,
            date_to=date_to,
            vat=vat,
            mark=DEFAULT_MARK
        )
        return docs
    except Exception:
        log.exception("mydatanaut fetch failed")
        return None


def fetch_docs_via_requestdocs(date_from, date_to, vat, aade_user, aade_key):
    try:
        d1 = datetime.datetime.fromisoformat(date_from).strftime("%d/%m/%Y")
        d2 = datetime.datetime.fromisoformat(date_to).strftime("%d/%m/%Y")
    except Exception:
        d1 = date_from
        d2 = date_to
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
    try:
        return render_template(template_name, **ctx)
    except Exception as e:
        tb = traceback.format_exc()
        log.error("Template rendering failed for %s: %s\n%s", template_name, str(e), tb)
        debug = os.getenv("FLASK_DEBUG", "0") == "1"
        body = "<h2>Template error</h2><p>" + str(e) + "</p>"
        if debug:
            body += "<pre>" + tb + "</pre>"
        return body


# ---------------- Routes ----------------
@app.route("/")
def home():
    return safe_render("nav.html")

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
    return safe_render("fetch.html", result=result, error=error, mark=mark, credentials=load_credentials(), preview=load_cache()[:40])



@app.route("/fetch", methods=["GET", "POST"])
def fetch():
    message = None
    error = None
    creds = load_credentials()
    preview = load_cache()[:40]

    if request.method == "POST":
        date_from = request.form.get("date_from")
        date_to = request.form.get("date_to")
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
                res = fetch_docs_with_mydatanaut(date_from, date_to, vat, aade_user, aade_key)

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
            error = f"Σφάλμα λήψης: {e}"

    return safe_render("fetch.html", credentials=creds, message=message, error=error, preview=preview)


# The rest of your routes (search, save_excel, list, cron_fetch, last_error, health) remain unchanged
# Simply copy them from your existing app.py (as in the code you provided), unchanged.


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    debug_flag = os.getenv("FLASK_DEBUG", "0") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug_flag)
