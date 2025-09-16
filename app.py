#!/usr/bin/env python3
# app.py - myDATA webapp (Flask) with mydatanaut integration + cache + credentials management
from __future__ import annotations
import os
import io
import json
import hashlib
import datetime
from typing import Any, Dict, List, Optional
from flask import Flask, request, redirect, url_for, send_file, render_template_string, abort
import requests
import xmltodict

# Optional libs (may be not installed in minimal env)
try:
    import pandas as pd
except Exception:
    pd = None

# try to import mydatanaut (best-effort). If installed via pip from github it will be available.
try:
    import mydatanaut  # type: ignore
except Exception:
    mydatanaut = None  # fallback to direct API

# Config paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
UPLOADS_DIR = os.path.join(BASE_DIR, "uploads")
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(UPLOADS_DIR, exist_ok=True)

CACHE_FILE = os.path.join(DATA_DIR, "invoices_cache.json")
CREDS_FILE = os.path.join(DATA_DIR, "credentials.json")
EXCEL_FILE = os.path.join(UPLOADS_DIR, "invoices.xlsx")

# Env defaults
AADE_USER_ENV = os.getenv("AADE_USER_ID", "") or ""
AADE_KEY_ENV = os.getenv("AADE_SUBSCRIPTION_KEY", "") or ""
ENV_MODE = (os.getenv("MYDATA_ENV", "sandbox") or "sandbox").lower()
ENTITY_VAT_ENV = os.getenv("ENTITY_VAT", "") or ""
CRON_SECRET_ENV = os.getenv("CRON_SECRET", "") or ""

REQUESTDOCS_URL = (
    "https://mydataapidev.aade.gr/myDATA/RequestDocs"
    if ENV_MODE in ("sandbox", "demo", "dev")
    else "https://mydatapi.aade.gr/myDATA/RequestDocs"
)
TRANSMITTED_URL = (
    "https://mydataapidev.aade.gr/RequestTransmittedDocs"
    if ENV_MODE in ("sandbox", "demo", "dev")
    else "https://mydatapi.aade.gr/myDATA/RequestTransmittedDocs"
)

app = Flask(__name__, static_folder=None)


# ----------------------
# JSON file helpers
def json_read_file(path: str) -> List[Any]:
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
            return data if data is not None else []
    except Exception:
        return []


def json_write_file(path: str, data: Any) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ----------------------
# credentials management
def load_credentials() -> List[Dict[str, Any]]:
    return json_read_file(CREDS_FILE)


def save_credentials(all_creds: List[Dict[str, Any]]) -> None:
    json_write_file(CREDS_FILE, all_creds)


def add_credential(entry: Dict[str, Any]) -> bool:
    creds = load_credentials()
    # unique by name
    if any(str(c.get("name")) == str(entry.get("name")) for c in creds):
        return False
    creds.append(entry)
    save_credentials(creds)
    return True


def update_credential(name: str, new_entry: Dict[str, Any]) -> bool:
    creds = load_credentials()
    for i, c in enumerate(creds):
        if str(c.get("name")) == str(name):
            creds[i] = new_entry
            save_credentials(creds)
            return True
    return False


def delete_credential(name: str) -> bool:
    creds = load_credentials()
    new = [c for c in creds if str(c.get("name")) != str(name)]
    if len(new) == len(creds):
        return False
    save_credentials(new)
    return True


# ----------------------
# cache (documents)
def load_cache() -> List[Dict[str, Any]]:
    return json_read_file(CACHE_FILE)


def save_cache(docs: List[Dict[str, Any]]) -> None:
    json_write_file(CACHE_FILE, docs)


def append_doc_to_cache(doc: Dict[str, Any]) -> bool:
    """Append if not present (md5 signature or existing MARK) -> returns True if appended"""
    docs = load_cache()
    sig = hashlib.md5(json.dumps(doc, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    for d in docs:
        existing_sig = hashlib.md5(json.dumps(d, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
        if existing_sig == sig:
            return False
    docs.append(doc)
    save_cache(docs)
    return True


def doc_contains_mark_exact(doc: Any, mark: str) -> bool:
    """Recursive exact equality string match (only if a string equals mark)"""
    if doc is None:
        return False
    if isinstance(doc, str):
        return doc.strip() == mark
    if isinstance(doc, dict):
        for v in doc.values():
            if doc_contains_mark_exact(v, mark):
                return True
    if isinstance(doc, list):
        for v in doc:
            if doc_contains_mark_exact(v, mark):
                return True
    return False


def find_by_mark(mark: str) -> Optional[Dict[str, Any]]:
    docs = load_cache()
    for d in docs:
        if doc_contains_mark_exact(d, mark):
            return d
    return None


# ----------------------
# API helpers: check transmitted and fetch bulk
def is_mark_transmitted(mark: str, aade_user: str, aade_key: str) -> bool:
    headers = {
        "aade-user-id": aade_user,
        "ocp-apim-subscription-key": aade_key,
        "Accept": "application/xml",
    }
    try:
        r = requests.get(TRANSMITTED_URL, headers=headers, params={"mark": mark}, timeout=30)
    except Exception:
        return False
    if r.status_code >= 400:
        return False
    txt = (r.text or "")
    # quick detection of invoice indicators
    if any(tok in txt for tok in ("<classification", "<invoiceUid", "invoiceMark", "E3_", "VAT_", "NOT_VAT_")):
        return True
    try:
        # try parse xml wrapped string
        outer = xmltodict.parse(txt)
        inner = outer.get("string", {}).get("#text") if isinstance(outer.get("string"), dict) else None
        parsed = xmltodict.parse(inner) if inner else outer
        # scan for mark or classification
        def walk(o):
            if isinstance(o, dict):
                for k, v in o.items():
                    if isinstance(k, str) and ("E3_" in k or "VAT_" in k or "NOT_VAT" in k):
                        return True
                    if isinstance(v, (str, int, float)) and str(v).strip() == str(mark).strip():
                        return True
                    if walk(v):
                        return True
            elif isinstance(o, list):
                for i in o:
                    if walk(i):
                        return True
            return False
        return walk(parsed)
    except Exception:
        return False


def fetch_docs_via_api(date_from: str, date_to: str, vat: str, aade_user: str, aade_key: str) -> List[Dict[str, Any]]:
    # date format: accept yyyy-mm-dd inputs; convert to dd/MM/YYYY for endpoint
    try:
        d1 = datetime.datetime.fromisoformat(date_from).strftime("%d/%m/%Y")
    except Exception:
        d1 = date_from
    try:
        d2 = datetime.datetime.fromisoformat(date_to).strftime("%d/%m/%Y")
    except Exception:
        d2 = date_to
    params = {"dateFrom": d1, "dateTo": d2}
    if vat:
        params["vatNumber"] = vat
    headers = {
        "aade-user-id": aade_user,
        "ocp-apim-subscription-key": aade_key,
        "Accept": "application/xml",
    }
    r = requests.get(REQUESTDOCS_URL, headers=headers, params=params, timeout=60)
    if r.status_code >= 400:
        raise RuntimeError(f"API error {r.status_code}: {r.text}")
    txt = r.text or ""
    # parse xml -> dict
    try:
        parsed_outer = xmltodict.parse(txt)
        # sometimes inner text under <string> contains xml
        inner = parsed_outer.get("string", {}).get("#text") if isinstance(parsed_outer.get("string"), dict) else None
        if inner:
            parsed = xmltodict.parse(inner)
        else:
            parsed = parsed_outer
    except Exception:
        # if parsing fails return empty
        return []
    # try to normalize to list of docs
    docs: List[Dict[str, Any]] = []
    if isinstance(parsed, dict):
        # look for RequestedDoc / invoicesDoc / RequestedDocs / docs
        for key in ("RequestedDoc", "RequestedDocs", "RequestedDocuments", "invoicesDoc", "doc", "docs"):
            if key in parsed:
                v = parsed[key]
                if isinstance(v, list):
                    docs.extend(v)
                elif isinstance(v, dict):
                    # maybe it contains invoice array
                    if "invoice" in v and isinstance(v["invoice"], list):
                        docs.extend(v["invoice"])
                    else:
                        docs.append(v)
                break
        else:
            # fallback: treat parsed as single doc
            docs.append(parsed)
    elif isinstance(parsed, list):
        docs = parsed
    return docs


def fetch_docs_with_mydatanaut(date_from: str, date_to: str, vat: str, aade_user: str, aade_key: str) -> Optional[List[Dict[str, Any]]]:
    """Attempt to use mydatanaut Python package. Best-effort (APIs may vary)."""
    if not mydatanaut:
        return None
    try:
        # Try common patterns (best-effort)
        # 1) package might expose a client class
        if hasattr(mydatanaut, "AADEClient"):
            Client = getattr(mydatanaut, "AADEClient")
            client = Client(user=aade_user or None, key=aade_key or None, env=ENV_MODE)
            if hasattr(client, "request_docs"):
                return client.request_docs(date_from=date_from, date_to=date_to, vatNumber=vat)
        if hasattr(mydatanaut, "Client"):
            Client = getattr(mydatanaut, "Client")
            client = Client(user=aade_user or None, key=aade_key or None, env=ENV_MODE)
            if hasattr(client, "request_docs"):
                return client.request_docs(date_from=date_from, date_to=date_to, vatNumber=vat)
        # fallback: package-level helper
        if hasattr(mydatanaut, "request_docs"):
            return getattr(mydatanaut, "request_docs")(date_from=date_from, date_to=date_to, vatNumber=vat, user=aade_user, key=aade_key)
    except Exception as e:
        # if anything fails, return None so fallback HTTP is used
        app.logger.warning("mydatanaut call failed: %s", e)
        return None
    return None


# ----------------------
# Summarizer: extract a few useful fields for Excel row
def summarize_parsed_doc(parsed: Dict[str, Any]) -> Dict[str, Any]:
    row = {
        "MARK": "",
        "ΑΦΜ": "",
        "Επωνυμία": "",
        "Σειρά": "",
        "Αριθμός": "",
        "Ημερομηνία": "",
        "Είδος": "",
        "Καθαρή Αξία": "",
        "ΦΠΑ": "",
        "Σύνολο": "",
    }
    if not isinstance(parsed, dict):
        return row
    # shallow known fields
    issuer = parsed.get("issuer") or {}
    if isinstance(issuer, dict):
        row["ΑΦΜ"] = issuer.get("vatNumber") or issuer.get("VATNumber") or row["ΑΦΜ"]
        row["Επωνυμία"] = issuer.get("name") or issuer.get("companyName") or row["Επωνυμία"]
    header = parsed.get("invoiceHeader") or {}
    if isinstance(header, dict):
        row["Σειρά"] = header.get("series") or header.get("Series") or row["Σειρά"]
        row["Αριθμός"] = header.get("aa") or header.get("AA") or header.get("Number") or row["Αριθμός"]
        row["Ημερομηνία"] = header.get("issueDate") or header.get("IssueDate") or row["Ημερομηνία"]
        row["Είδος"] = header.get("invoiceType") or header.get("InvoiceType") or row["Είδος"]
    summary = parsed.get("invoiceSummary") or {}
    if isinstance(summary, dict):
        row["Καθαρή Αξία"] = summary.get("totalNetValue") or summary.get("TotalNetValue") or row["Καθαρή Αξία"]
        row["ΦΠΑ"] = summary.get("totalVatAmount") or summary.get("TotalVatAmount") or row["ΦΠΑ"]
        row["Σύνολο"] = summary.get("totalGrossValue") or summary.get("TotalGrossValue") or row["Σύνολο"]
    # try to find any 15-digit mark in the whole doc (if present)
    def walker(o):
        if isinstance(o, str):
            import re
            m = re.search(r"\b(\d{15})\b", o)
            if m:
                return m.group(1)
            return None
        if isinstance(o, dict):
            for k, v in o.items():
                r = walker(v)
                if r:
                    return r
        if isinstance(o, list):
            for i in o:
                r = walker(i)
                if r:
                    return r
        return None
    found_mark = walker(parsed)
    if found_mark:
        row["MARK"] = found_mark
    return row


def save_summary_to_excel_row(row: Dict[str, Any]) -> bool:
    """Use pandas/openpyxl if available, else append CSV."""
    if pd is None:
        # fallback CSV
        headless = not os.path.exists(EXCEL_FILE)
        try:
            import csv
            with open(EXCEL_FILE, "a", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                if headless:
                    w.writerow(list(row.keys()))
                w.writerow([row.get(k, "") for k in row.keys()])
            return True
        except Exception as e:
            app.logger.error("CSV save error: %s", e)
            return False
    try:
        df = pd.DataFrame([row])
        if os.path.exists(EXCEL_FILE):
            old = pd.read_excel(EXCEL_FILE, engine="openpyxl", dtype=str).fillna("")
            combined = pd.concat([old, df], ignore_index=True, sort=False)
            combined.to_excel(EXCEL_FILE, index=False, engine="openpyxl")
        else:
            df.to_excel(EXCEL_FILE, index=False, engine="openpyxl")
        return True
    except Exception as e:
        app.logger.error("Excel save error: %s", e)
        return False


# ----------------------
# HTML templates (simple, can be moved to templates/ files)
NAV_HTML = """
<!doctype html><html lang="el"><head><meta charset="utf-8"><title>myDATA - Μενού</title>
<style>body{font-family:Arial,sans-serif;max-width:1000px;margin:20px auto;background:#fafafa}.card{background:#fff;padding:16px;margin:16px 0;border-radius:12px;box-shadow:0 2px 6px rgba(0,0,0,0.05)}.menu{display:flex;gap:12px;flex-wrap:wrap}.menu a{display:block;padding:12px 18px;background:#0d6efd;color:#fff;border-radius:10px;text-decoration:none}.menu a.secondary{background:#6c757d}</style></head><body>
<div class="card"><h1>myDATA - Κεντρικό Μενού</h1><p>Επέλεξε λειτουργία:</p><div class="menu">
<a href="/viewer">Εισαγωγή Παραστατικού</a>
<a href="/fetch">Λήψη Παραστατικών (bulk)</a>
<a href="/list">Λίστα Παραστατικών</a>
<a href="/options" class="secondary">Επιλογές / Credentials</a>
</div></div></body></html>
"""

VIEWER_HTML = """
<!doctype html><html lang="el"><head><meta charset="utf-8"><title>Viewer</title>
<style>body{font-family:Arial,sans-serif;max-width:900px;margin:20px auto;background:#fafafa}.card{background:#fff;padding:16px;margin:16px 0;border-radius:12px;box-shadow:0 2px 6px rgba(0,0,0,0.05)}input,button{width:100%;padding:8px;margin:6px 0;border-radius:8px}button{background:#0d6efd;color:white;border:0;cursor:pointer}</style></head><body>
<h1>myDATA - Viewer</h1><p><a href="/">↩ Επιστροφή στο μενού</a></p>
<div class="card">
<h3>Αναζήτηση MARK (ακριβής)</h3>
<form method="post" enctype="multipart/form-data" action="/viewer">
<input type="text" name="mark" placeholder="π.χ. 123456789012345">
<button type="submit">Αναζήτηση</button>
</form>
</div>
{message}{error}{result}
</body></html>
"""

FETCH_HTML = """
<!doctype html><html lang="el"><head><meta charset="utf-8"><title>Λήψη Παραστατικών</title>
<style>body{font-family:Arial,sans-serif;max-width:1000px;margin:20px auto;background:#fafafa}.card{background:#fff;padding:16px;margin:16px 0;border-radius:12px;box-shadow:0 2px 6px rgba(0,0,0,0.05)}input,button,select{padding:8px;margin:6px 0;border-radius:8px}button{background:#0d6efd;color:#fff;border:0;cursor:pointer}.small{width:auto;display:inline-block}</style></head><body>
<h1>Λήψη Παραστατικών (Bulk)</h1><p><a href="/">↩ Επιστροφή</a></p>
<div class="card">
<form method="post" action="/fetch">
<p>Επίλεξε stored credential: <select name="use_credential">{cred_opts}</select></p>
<p>Ή δώσε manual AADE User/Key (θα χρησιμοποιηθούν αν δεν επιλέξεις credential):</p>
<p>User: <input name="user" value="{user_env}"></p>
<p>Key: <input name="key" value="{key_env}"></p>
<p>Ημερομηνία Από: <input type="date" name="date_from" required value="{df}"></p>
<p>Έως: <input type="date" name="date_to" required value="{dt}"></p>
<p>VAT Number (entity): <input type="text" name="vat_number" placeholder="π.χ. 123456789" value="{vat}"></p>
<button type="submit">Λήψη & Αποθήκευση Cache</button>
</form>
</div>
{message}{error}
<h3>Cache preview</h3>
{table}
</body></html>
"""

OPTIONS_HTML = """
<!doctype html><html lang="el"><head><meta charset="utf-8"><title>Options / Credentials</title>
<style>body{font-family:Arial,sans-serif;max-width:900px;margin:20px auto;background:#fafafa}.card{background:#fff;padding:16px;margin:16px 0;border-radius:12px;box-shadow:0 2px 6px rgba(0,0,0,0.05)}input,button{padding:8px;margin:6px 0;border-radius:8px}button{background:#0d6efd;color:#fff;border:0;cursor:pointer}.danger{background:#dc3545;color:#fff;padding:6px 10px;border:none;border-radius:6px}</style></head><body>
<h1>Επιλογές / Credentials</h1><p><a href="/">↩ Επιστροφή</a></p>
<div class="card">
<h3>Προσθήκη νέου credential</h3>
<form method="post" action="/options">
<p>Όνομα (unique): <input name="name" required></p>
<p>AADE User ID: <input name="user"></p>
<p>AADE Subscription Key: <input name="key"></p>
<p>Env: <select name="env"><option value="sandbox">sandbox</option><option value="production">production</option></select></p>
<p>Default VAT: <input name="vat"></p>
<button type="submit">Αποθήκευση</button>
</form>
</div>
<div class="card">
<h3>Αποθηκευμένα credentials</h3>
{creds_html}
</div>
</body></html>
"""

LIST_HTML = """
<!doctype html><html lang="el"><head><meta charset="utf-8"><title>Λίστα Παραστατικών</title>
<style>body{font-family:Arial,sans-serif;max-width:1200px;margin:20px auto;background:#fafafa}.card{background:#fff;padding:16px;margin:16px 0;border-radius:12px;box-shadow:0 2px 6px rgba(0,0,0,0.05)}table{border-collapse:collapse;width:100%}th,td{border:1px solid #ddd;padding:8px;text-align:left}th{background:#0d6efd;color:#fff}tr:nth-child(even){background:#f9f9f9}.small-btn{display:inline-block;padding:8px 12px;border-radius:6px;background:#198754;color:#fff;text-decoration:none}</style></head><body>
<div class="card"><h1>Λίστα Παραστατικών (Excel)</h1>
<div style="margin-bottom:12px;">
<a class="small-btn" href="/">⬅ Επιστροφή</a>
<a class="small-btn" href="/list?download=1">⬇️ Κατέβασμα .xlsx / .csv</a>
</div>
{table_html}
</div></body></html>
"""

# ----------------------
# Routes
@app.route("/")
def home():
    return NAV_HTML


@app.route("/options", methods=["GET", "POST"])
def options():
    msg = ""
    err = ""
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        user = request.form.get("user", "").strip()
        key = request.form.get("key", "").strip()
        envv = request.form.get("env", "sandbox").strip()
        vat = request.form.get("vat", "").strip()
        if not name:
            err = "Συμπλήρωσε όνομα για το credential."
        else:
            entry = {"name": name, "user": user, "key": key, "env": envv, "vat": vat}
            if add_credential(entry):
                msg = "Credential αποθηκεύτηκε."
            else:
                err = "Το όνομα credential υπάρχει ήδη. Χρησιμοποίησε edit."
    creds = load_credentials()
    if creds:
        creds_html = "<ul>"
        for c in creds:
            creds_html += "<li><strong>{name}</strong> — VAT:{vat} — env:{env} &nbsp; <form style='display:inline' method='post' action='/options/edit' onsubmit=\"return confirm('Διαγραφή;');\"><input type='hidden' name='del_name' value='{name}'><button class='danger'>Διαγραφή</button></form> &nbsp; <form style='display:inline' method='get' action='/options/edit_form'><input type='hidden' name='name' value='{name}'><button>Επεξεργασία</button></form></li>".format(
                name=c.get("name", ""), vat=c.get("vat", ""), env=c.get("env", ""))
        creds_html += "</ul>"
    else:
        creds_html = "<div> Δεν υπάρχουν αποθηκευμένα credentials. </div>"
    if err:
        err_html = f"<div style='background:#fff5f5;padding:8px;border-radius:6px'>{err}</div>"
    else:
        err_html = ""
    if msg:
        msg_html = f"<div style='background:#e6ffed;padding:8px;border-radius:6px'>{msg}</div>"
    else:
        msg_html = ""
    return render_template_string(OPTIONS_HTML, creds_html=creds_html) .replace("{creds_html}", creds_html)


@app.route("/options/edit", methods=["POST"])
def options_edit_delete():
    # handle delete from options listing
    del_name = request.form.get("del_name", "").strip()
    if del_name:
        if delete_credential(del_name):
            return redirect(url_for("options"))
        else:
            return "Not found", 404
    return redirect(url_for("options"))


@app.route("/options/edit_form", methods=["GET", "POST"])
def options_edit_form():
    # show form for editing and handle update
    if request.method == "GET":
        name = request.args.get("name", "")
        creds = load_credentials()
        entry = None
        for c in creds:
            if c.get("name") == name:
                entry = c
                break
        if not entry:
            return "Not found", 404
        # render simple html form
        html = f"""
        <!doctype html><html><body>
        <h1>Edit credential {name}</h1>
        <form method="post">
        <input type="hidden" name="orig_name" value="{name}">
        Όνομα: <input name="name" value="{entry.get('name','')}"><br>
        User: <input name="user" value="{entry.get('user','')}"><br>
        Key: <input name="key" value="{entry.get('key','')}"><br>
        Env: <select name="env"><option value="sandbox" {'selected' if entry.get('env')=='sandbox' else ''}>sandbox</option><option value="production" {'selected' if entry.get('env')=='production' else ''}>production</option></select><br>
        VAT: <input name="vat" value="{entry.get('vat','')}"><br>
        <button type="submit">Save</button>
        </form>
        <p><a href="/options">Back</a></p>
        </body></html>
        """
        return html
    # POST => update
    orig = request.form.get("orig_name", "")
    name = request.form.get("name", "").strip()
    user = request.form.get("user", "").strip()
    key = request.form.get("key", "").strip()
    envv = request.form.get("env", "sandbox").strip()
    vat = request.form.get("vat", "").strip()
    if not orig:
        return "Bad request", 400
    creds = load_credentials()
    found = False
    for i, c in enumerate(creds):
        if c.get("name") == orig:
            creds[i] = {"name": name, "user": user, "key": key, "env": envv, "vat": vat}
            found = True
            break
    if not found:
        return "Not found", 404
    save_credentials(creds)
    return redirect(url_for("options"))


@app.route("/fetch", methods=["GET", "POST"])
def fetch_bulk():
    message = ""
    error = ""
    table_html = ""
    df_default = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()
    dt_default = datetime.date.today().isoformat()
    if request.method == "POST":
        use_cred = request.form.get("use_credential", "")
        # choose aade creds either from selected credential or from manual input or env
        aade_user = AADE_USER_ENV
        aade_key = AADE_KEY_ENV
        vat = request.form.get("vat_number", "").strip() or ENTITY_VAT_ENV
        if use_cred:
            creds = load_credentials()
            for c in creds:
                if c.get("name") == use_cred:
                    aade_user = c.get("user", "") or aade_user
                    aade_key = c.get("key", "") or aade_key
                    vat = c.get("vat", "") or vat
                    break
        # manual override fields (if given)
        if request.form.get("user"):
            aade_user = request.form.get("user").strip()
        if request.form.get("key"):
            aade_key = request.form.get("key").strip()
        d1 = request.form.get("date_from", df_default)
        d2 = request.form.get("date_to", dt_default)
        try:
            # try mydatanaut first
            docs = None
            if mydatanaut:
                docs = fetch_docs_with_mydatanaut(d1, d2, vat, aade_user, aade_key)
            if docs is None:
                # fallback to direct API fetch
                docs = fetch_docs_via_api(d1, d2, vat, aade_user, aade_key)
            # docs expected as list of parsed dicts
            new_count = 0
            for doc in docs:
                try:
                    if append_doc_to_cache(doc):
                        new_count += 1
                except Exception:
                    # ignore single bad doc
                    pass
            message = f"Λήφθηκαν {len(docs)} αντικείμενα. Νέα αποθηκεύτηκαν: {new_count}."
        except Exception as e:
            error = f"Σφάλμα λήψης: {e}"
    # prepare cache preview
    cached = load_cache()
    if cached:
        rows = []
        for i, d in enumerate(cached):
            short = json.dumps(d, ensure_ascii=False)[:400]
            rows.append(f"<tr><td>{i+1}</td><td style='white-space:pre-wrap'>{short}</td></tr>")
        table_html = "<div style='max-height:400px;overflow:auto'><table style='width:100%;border-collapse:collapse'><thead><tr><th>#</th><th>Σύντομη Παρουσίαση</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>"
    else:
        table_html = "<div>Δεν υπάρχουν cached παραστατικά.</div>"
    # credentials options
    creds = load_credentials()
    cred_opts = "<option value=''>-- use env/default --</option>"
    for c in creds:
        cred_opts += f"<option value='{c.get('name')}'>{c.get('name')}</option>"
    # render
    return render_template_string(FETCH_HTML.format(
        cred_opts=cred_opts,
        df=request.form.get("date_from", df_default),
        dt=request.form.get("date_to", dt_default),
        vat=request.form.get("vat_number", ENTITY_VAT_ENV),
        user_env=AADE_USER_ENV,
        key_env=AADE_KEY_ENV,
        message=f"<div style='background:#e6ffed;padding:8px'>{message}</div>" if message else "",
        error=f"<div style='background:#fff5f5;padding:8px'>{error}</div>" if error else "",
        table=table_html
    ))


@app.route("/viewer", methods=["GET", "POST"])
def viewer():
    message = ""
    error = ""
    result_html = ""
    if request.method == "POST":
        mark = (request.form.get("mark", "") or "").strip()
        if not mark or not mark.isdigit() or len(mark) != 15:
            error = "<div style='background:#fff5f5;padding:12px'>Δεν δόθηκε έγκυρος MARK (15 ψηφία)</div>"
        else:
            doc = find_by_mark(mark)
            if not doc:
                error = f"<div style='background:#fff5f5;padding:12px'>Δεν βρέθηκε παραστατικό με MARK {mark} στην cache. Πρέπει πρώτα να εκτελέσεις λήψη (Bulk).</div>"
            else:
                pretty = json.dumps(doc, ensure_ascii=False, indent=2)
                result_html = f"<div class='card'><h3>Παραστατικό (MARK {mark})</h3><pre style='white-space:pre-wrap'>{pretty}</pre>"
                summ = summarize_parsed_doc(doc)
                # form to save to excel
                hidden_inputs = "".join([f"<input type='hidden' name='summ[{k}]' value='{str(v)}'>" for k, v in summ.items()])
                result_html += f"<form method='post' action='/save_excel'>{hidden_inputs}<button type='submit'>Αποθήκευση στο Excel</button></form></div>"
                message = "<div style='background:#e6ffed;padding:8px'>Βρέθηκε παραστατικό στην cache.</div>"
    return render_template_string(VIEWER_HTML.format(message=message, error=error, result=result_html))


@app.route("/save_excel", methods=["POST"])
def save_excel():
    summ = request.form.getlist("summ")
    # request.form.getlist won't parse dict-style inputs reliably; handle alternative
    if "summ" in request.form:
        # ignore
        pass
    # better: reconstruct from keys
    summ_dict = {}
    for k in request.form:
        if k.startswith("summ[") and k.endswith("]"):
            kk = k[5:-1]
            summ_dict[kk] = request.form.get(k)
    # fallback: maybe user posted non-dict hidden inputs; try parsing 'summ' dict style
    if not summ_dict:
        for k, v in request.form.items():
            if k.startswith("summ[") and k.endswith("]"):
                summ_dict[k[5:-1]] = v
    if not summ_dict:
        # try a simpler route: trust fields that match known headers
        known = ["MARK", "ΑΦΜ", "Επωνυμία", "Σειρά", "Αριθμός", "Ημερομηνία", "Είδος", "Καθαρή Αξία", "ΦΠΑ", "Σύνολο"]
        for kk in known:
            if kk in request.form:
                summ_dict[kk] = request.form.get(kk)
    if not summ_dict:
        return redirect(url_for("viewer"))
    save_summary_to_excel_row(summ_dict)
    return redirect(url_for("list_invoices"))


@app.route("/list", methods=["GET"])
def list_invoices():
    # download
    if request.args.get("download"):
        if os.path.exists(EXCEL_FILE):
            return send_file(EXCEL_FILE, as_attachment=True, download_name=os.path.basename(EXCEL_FILE))
        else:
            # serve CSV fallback
            return "No excel file available", 404
    # render HTML from excel or CSV fallback
    table_html = "<div>Δεν υπάρχει αρχείο Excel.</div>"
    if os.path.exists(EXCEL_FILE):
        if pd:
            try:
                df = pd.read_excel(EXCEL_FILE, engine="openpyxl", dtype=str).fillna("")
                table_html = df.to_html(classes="summary-table", index=False, escape=False)
            except Exception as e:
                table_html = f"<div>Σφάλμα ανάγνωσης Excel: {e}</div>"
        else:
            # CSV fallback
            try:
                import csv
                rows = []
                with open(EXCEL_FILE, newline="", encoding="utf-8") as f:
                    rdr = csv.reader(f)
                    for r in rdr:
                        rows.append(r)
                if rows:
                    ths = "".join(f"<th>{c}</th>" for c in rows[0])
                    trs = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows[1:])
                    table_html = f"<table><thead><tr>{ths}</tr></thead><tbody>{trs}</tbody></table>"
            except Exception as e:
                table_html = f"<div>Σφάλμα ανάγνωσης αρχείου: {e}</div>"
    return render_template_string(LIST_HTML.format(table_html=table_html))


# optional cron route
@app.route("/cron", methods=["GET"])
def cron_fetch():
    secret = request.args.get("secret", "")
    if not CRON_SECRET_ENV or secret != CRON_SECRET_ENV:
        abort(403)
    # fetch last 7 days by default
    d1 = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()
    d2 = datetime.date.today().isoformat()
    vat = ENTITY_VAT_ENV
    try:
        docs = fetch_docs_via_api(d1, d2, vat, AADE_USER_ENV, AADE_KEY_ENV)
        new = 0
        for doc in docs:
            if append_doc_to_cache(doc):
                new += 1
        return f"Cron fetched {len(docs)}, new {new}"
    except Exception as e:
        return f"Error: {e}", 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
