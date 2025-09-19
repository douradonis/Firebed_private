# app.py
import os
import sys
import json
import datetime
import traceback
import re
from typing import Any, Dict, List, Optional, Set

from flask import Flask, render_template, request, redirect, url_for, send_file, flash
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

# --- Directories ---
DATA_DIR = os.path.join(BASE_DIR, "data")
UPLOADS_DIR = os.path.join(BASE_DIR, "uploads")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(UPLOADS_DIR, exist_ok=True)

CACHE_FILE = os.path.join(DATA_DIR, "invoices_cache.json")
CREDENTIALS_FILE = os.path.join(DATA_DIR, "credentials.json")
EXCEL_FILE = os.path.join(UPLOADS_DIR, "invoices.xlsx")

# ENV defaults
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
app.secret_key = os.getenv("FLASK_SECRET", "change-me")

# Basic logger note
app.logger.info("Starting app - HAS_MYDATANAUT=%s MYDATA_ENV=%s", HAS_MYDATANAUT, MYDATA_ENV)


# ---------------- Utilities ----------------
def json_read(path: str) -> Any:
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        app.logger.exception("Failed to read JSON %s", path)
        return []


def json_write(path: str, data: Any) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def load_credentials() -> List[Dict[str, Any]]:
    data = json_read(CREDENTIALS_FILE)
    return data if isinstance(data, list) else []


def save_credentials(creds: List[Dict[str, Any]]) -> None:
    json_write(CREDENTIALS_FILE, creds)


def add_credential(entry: Dict[str, str]) -> (bool, str):
    creds = load_credentials()
    for c in creds:
        if c.get("name") == entry.get("name"):
            return False, "Credential with that name exists"
    creds.append(entry)
    save_credentials(creds)
    return True, ""


def update_credential(name: str, new_entry: Dict[str, str]) -> bool:
    creds = load_credentials()
    for i, c in enumerate(creds):
        if c.get("name") == name:
            creds[i] = new_entry
            save_credentials(creds)
            return True
    return False


def delete_credential(name: str) -> bool:
    creds = load_credentials()
    new = [c for c in creds if c.get("name") != name]
    save_credentials(new)
    return True


# Cache helpers
def load_cache() -> List[Any]:
    data = json_read(CACHE_FILE)
    return data if isinstance(data, list) else []


def save_cache(docs: List[Any]) -> None:
    json_write(CACHE_FILE, docs)


def _extract_15digit_marks_from_obj(obj: Any) -> Set[str]:
    """Recursively find 15-digit numeric strings in a nested structure."""
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


def append_doc_to_cache(doc: Any, aade_user: Optional[str] = None, aade_key: Optional[str] = None) -> bool:
    """
    Append doc to cache if not already present.
    Deduplicate by exact JSON signature OR by MARK (if present).
    If aade_user/aade_key provided, skip adding if is_mark_transmitted() is True for any mark found.
    """
    docs = load_cache()
    # signature dedupe
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

    # mark-based dedupe
    marks = _extract_15digit_marks_from_obj(doc)
    if marks:
        # if any existing doc contains same mark -> duplicate
        for m in marks:
            for d in docs:
                if _extract_15digit_marks_from_obj(d) and m in _extract_15digit_marks_from_obj(d):
                    return False
        # check transmitted if credentials provided
        if aade_user and aade_key:
            for m in marks:
                try:
                    if is_mark_transmitted(m, aade_user, aade_key):
                        app.logger.info("Skipping cached doc because mark %s is already transmitted", m)
                        return False
                except Exception:
                    app.logger.exception("is_mark_transmitted failed for %s", m)
                    # continue trying others

    docs.append(doc)
    save_cache(docs)
    return True


def doc_contains_mark_exact(doc: Any, mark: str) -> bool:
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


def find_invoice_by_mark_exact(mark: str) -> Optional[Any]:
    docs = load_cache()
    for doc in docs:
        if doc_contains_mark_exact(doc, mark):
            return doc
    return None


def is_mark_transmitted(mark: str, aade_user: str, aade_key: str) -> bool:
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
        # heuristics to detect presence
        if "invoiceMark" in raw or "invoiceUid" in raw or "<classification" in raw or "E3_" in raw or "VAT_" in raw:
            return True
    except Exception:
        app.logger.exception("transmitted check failed for mark=%s", mark)
    return False


# ---------------- Fetch implementations ----------------
def fetch_docs_with_mydatanaut(df: str, dt: str, vat: str, aade_user: str, aade_key: str):
    if not HAS_MYDATANAUT:
        return None
    try:
        client = None
        # try common constructor patterns used by external libs
        try:
            client = mydatanaut_pkg.Client(user=aade_user, key=aade_key, env=MYDATA_ENV)
        except Exception:
            try:
                client = mydatanaut_pkg.MyDataClient(user=aade_user, key=aade_key, env=MYDATA_ENV)
            except Exception:
                client = None
        if client is None:
            return None

        # try request method patterns
        if hasattr(client, "request_docs"):
            return client.request_docs(df, dt, vat)
        if hasattr(client, "fetch_docs"):
            return client.fetch_docs(df, dt, vat)
        if hasattr(client, "docs"):
            return client.docs(df, dt, vat)
    except Exception:
        app.logger.exception("mydatanaut error")
    return None


def fetch_docs_via_requestdocs(date_from: str, date_to: str, vat: str, aade_user: str, aade_key: str):
    """
    Call RequestDocs endpoint and return parsed xml->dict or raw text on fallback.
    Expects date_from/date_to in ISO 'YYYY-MM-DD' from the UI; will convert to dd/MM/YYYY.
    """
    try:
        d1 = datetime.datetime.fromisoformat(date_from).strftime("%d/%m/%Y")
        d2 = datetime.datetime.fromisoformat(date_to).strftime("%d/%m/%Y")
    except Exception:
        # if input already in dd/mm/YYYY
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
    resp = requests.get(REQUESTDOCS_URL, params=params, headers=headers, timeout=60)
    if resp.status_code >= 400:
        raise Exception(f"API error {resp.status_code}: {resp.text[:1000]!s}")
    text = resp.text or ""
    # Try to unwrap nested string wrappers and parse XML to dict
    try:
        outer = xmltodict.parse(text)
        # some endpoints wrap the real XML inside <string>..escaped xml..</string>
        if isinstance(outer, dict) and "string" in outer:
            s = outer.get("string")
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
        return outer
    except Exception:
        # return raw text as last resort
        return text


# ---------------- Routes ----------------
@app.route("/")
def home():
    return render_template("nav.html")


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
    return render_template("credentials_list.html", credentials=creds)


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
    return render_template("credentials_edit.html", credential=credential)


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
        date_from = request.form.get("date_from")
        date_to = request.form.get("date_to")
        selected = request.form.get("use_credential") or ""
        vat = request.form.get("vat_number", "").strip()
        aade_user = AADE_USER_ENV
        aade_key = AADE_KEY_ENV
        # override with selected stored credential
        if selected:
            c = next((x for x in creds if x.get("name") == selected), None)
            if c:
                aade_user = c.get("user", "") or aade_user
                aade_key = c.get("key", "") or aade_key
                vat = vat or c.get("vat", "")

        if not date_from or not date_to:
            error = "Παρακαλώ συμπλήρωσε από-έως ημερομηνίες."
            return render_template("fetch.html", credentials=creds, message=message, error=error, preview=preview)

        try:
            res = None
            # try mydatanaut vendorized client first (if available)
            if HAS_MYDATANAUT:
                try:
                    res = fetch_docs_with_mydatanaut(date_from, date_to, vat, aade_user, aade_key)
                except Exception:
                    app.logger.exception("mydatanaut client failed")
                    res = None

            if res is None:
                parsed = fetch_docs_via_requestdocs(date_from, date_to, vat, aade_user, aade_key)
                docs_list = []
                if isinstance(parsed, dict):
                    # many shapes possible; try to find RequestedDoc or docs containers
                    if "RequestedDoc" in parsed:
                        maybe = parsed.get("RequestedDoc")
                        docs_list = maybe if isinstance(maybe, list) else [maybe]
                    elif "docs" in parsed:
                        docs_list = parsed.get("docs") or []
                    else:
                        # heuristics: search nested dicts for list-like children
                        found = False
                        for k, v in parsed.items():
                            if isinstance(v, list):
                                docs_list = v
                                found = True
                                break
                            if isinstance(v, dict) and "RequestedDoc" in v:
                                md = v.get("RequestedDoc")
                                docs_list = md if isinstance(md, list) else [md]
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
            # refresh preview
            preview = load_cache()[:40]
        except Exception as e:
            app.logger.exception("Fetch error")
            error = f"Σφάλμα λήψης: {e}"

    return render_template("fetch.html", credentials=creds, message=message, error=error, preview=preview)


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
    return render_template("search.html", result=result, error=error, mark=mark)


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
                    # fallback: append CSV
                    df.to_csv(EXCEL_FILE, mode="a", index=False, header=not os.path.exists(EXCEL_FILE))
            else:
                # try to write Excel first, fallback to csv
                try:
                    df.to_excel(EXCEL_FILE, index=False, engine="openpyxl")
                except Exception:
                    df.to_csv(EXCEL_FILE, index=False)
            flash("Saved to Excel", "success")
        except Exception as e:
            app.logger.exception("Excel save error")
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
            app.logger.exception("Failed to read Excel, falling back to cache")
            table = load_cache()
    else:
        table = load_cache()
    return render_template("list.html", table=table)


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
        app.logger.exception("Cron fetch error")
        return (f"Cron fetch error: {e}", 500)


@app.route("/health")
def health():
    return "OK"


if __name__ == "__main__":
    # Use the environment PORT (Render sets it) or default 5000
    port = int(os.getenv("PORT", "5000"))
    debug_flag = os.getenv("FLASK_DEBUG", "0") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug_flag)
