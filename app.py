# app.py
from flask import Flask, render_template, request, redirect, url_for, send_file, flash, jsonify
import os, json, datetime, traceback
import requests
import xmltodict
from werkzeug.utils import secure_filename
import pandas as pd

# Optional import for mydatanaut (vendorized) - best-effort
try:
    # if you vendorized mydatanaut under vendor/mydatanaut and added to PYTHONPATH or via relative import
    import mydatanaut as mydatanaut_pkg  # vendor: vendor/mydatanaut/__init__.py
    HAS_MYDATANAUT = True
except Exception:
    HAS_MYDATANAUT = False

# ---- Config ----
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
UPLOADS_DIR = os.path.join(BASE_DIR, "uploads")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")  # Flask auto-detects
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(UPLOADS_DIR, exist_ok=True)

CACHE_FILE = os.path.join(DATA_DIR, "invoices_cache.json")
CREDENTIALS_FILE = os.path.join(DATA_DIR, "credentials.json")
EXCEL_FILE = os.path.join(UPLOADS_DIR, "invoices.xlsx")

# env defaults
AADE_USER_ENV = os.getenv("AADE_USER_ID", "")
AADE_KEY_ENV = os.getenv("AADE_SUBSCRIPTION_KEY", "")
MYDATA_ENV = (os.getenv("MYDATA_ENV") or "sandbox").lower()

# endpoints (bulk request docs)
REQUESTDOCS_URL = "https://mydataapidev.aade.gr/RequestDocs" if MYDATA_ENV in ("sandbox","demo","dev") else "https://mydatapi.aade.gr/myDATA/RequestDocs"
TRANSMITTED_URL = "https://mydataapidev.aade.gr/RequestTransmittedDocs" if MYDATA_ENV in ("sandbox","demo","dev") else "https://mydatapi.aade.gr/myDATA/RequestTransmittedDocs"

app = Flask(__name__, template_folder=TEMPLATES_DIR)
app.secret_key = os.getenv("FLASK_SECRET", "change-me-for-prod")

# ---- Utilities ----
def json_read(path):
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def json_write(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_credentials():
    data = json_read(CREDENTIALS_FILE)
    return data if isinstance(data, list) else []

def save_credentials(creds):
    json_write(CREDENTIALS_FILE, creds)

def add_credential(entry):
    creds = load_credentials()
    # dedupe by name
    for c in creds:
        if c.get("name") == entry.get("name"):
            return False, "Credential with that name exists"
    creds.append(entry)
    save_credentials(creds)
    return True, ""

def update_credential(name, new_entry):
    creds = load_credentials()
    for i,c in enumerate(creds):
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

def append_doc_to_cache(doc):
    docs = load_cache()
    # detect duplicate by serialized signature
    sig = json.dumps(doc, sort_keys=True, ensure_ascii=False)
    for d in docs:
        if json.dumps(d, sort_keys=True, ensure_ascii=False) == sig:
            return False
    docs.append(doc)
    save_cache(docs)
    return True

def find_invoice_by_mark_exact(mark):
    # exact string match anywhere in cached doc values
    docs = load_cache()
    for doc in docs:
        if doc_contains_mark_exact(doc, mark):
            return doc
    return None

def doc_contains_mark_exact(doc, mark):
    # search recursively for string equal to mark
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

# Check if a mark is already transmitted (call RequestTransmittedDocs)
def is_mark_transmitted(mark, aade_user, aade_key):
    headers = {
        "aade-user-id": aade_user,
        "ocp-apim-subscription-key": aade_key,
        "Accept": "application/xml"
    }
    try:
        r = requests.get(TRANSMITTED_URL, headers=headers, params={"mark": mark}, timeout=30)
        if r.status_code >= 400:
            return False
        raw = r.text or ""
        # quick heuristics: presence of invoiceMark/invoiceUid/classification or E3_/VAT_
        if "invoiceMark" in raw or "invoiceUid" in raw or "<classification" in raw or "E3_" in raw or "VAT_" in raw:
            return True
    except Exception:
        pass
    return False

# ---- Fetch implementations ----
def fetch_docs_with_mydatanaut(date_from, date_to, vat, aade_user, aade_key):
    if not HAS_MYDATANAUT:
        return None  # not available
    try:
        # mydatanaut usage may vary; try common entrypoints
        # If you vendorized the library adjust import usage accordingly.
        client = None
        # try multiple names
        try:
            client = mydatanaut_pkg.Client(user=aade_user, key=aade_key, env=MYDATA_ENV)
        except Exception:
            try:
                client = mydatanaut_pkg.MydatanautClient(user=aade_user, key=aade_key, env=MYDATA_ENV)
            except Exception:
                client = None
        if client is None:
            return None
        # library should provide a request_docs / fetch / request_transmitted or similar
        if hasattr(client, "request_docs"):
            res = client.request_docs(date_from, date_to, vat)
            return res
        if hasattr(client, "fetch_docs"):
            res = client.fetch_docs(date_from, date_to, vat)
            return res
    except Exception:
        app.logger.exception("mydatanaut fetch failed")
    return None

def fetch_docs_via_requestdocs(date_from, date_to, vat, aade_user, aade_key):
    # RequestDocs expects dd/MM/YYYY in many implementations — convert
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
        "aade-user-id": aade_user,
        "ocp-apim-subscription-key": aade_key,
        "Accept": "application/xml"
    }
    r = requests.get(REQUESTDOCS_URL, headers=headers, params=params, timeout=60)
    if r.status_code >= 400:
        raise Exception(f"API error {r.status_code}: {r.text[:500]}")
    # parse XML -> dict
    try:
        parsed_outer = xmltodict.parse(r.text)
        # The AADE response often wraps XML in <string> ... inner xml ...
        inner = None
        if isinstance(parsed_outer, dict) and "string" in parsed_outer:
            s = parsed_outer.get("string")
            if isinstance(s, dict) and "#text" in s:
                inner = s["#text"]
            elif isinstance(s, str):
                inner = s
        parsed = xmltodict.parse(inner) if inner else parsed_outer
        # return parsed structure; caller will handle extracting list
        return parsed
    except Exception:
        # if parse fails, return raw text
        return r.text

# ---- Routes ----

@app.route("/")
def home():
    return render_template("nav.html")  # use your existing nav template

# Credentials management (list / add / edit / delete)
@app.route("/credentials", methods=["GET", "POST"])
def credentials():
    msg = None
    if request.method == "POST":
        # add
        name = request.form.get("name", "").strip()
        user = request.form.get("user", "").strip()
        key = request.form.get("key", "").strip()
        env = request.form.get("env", MYDATA_ENV).strip()
        vat = request.form.get("vat", "").strip()
        if not name:
            msg = ("error", "Name required")
        else:
            ok, err = add_credential({"name": name, "user": user, "key": key, "env": env, "vat": vat})
            if ok:
                msg = ("success", "Saved")
            else:
                msg = ("error", err or "Could not save")
    creds = load_credentials()
    return render_template("credentials_list.html", credentials=creds, message=msg)

@app.route("/credentials/edit/<name>", methods=["GET","POST"])
def credentials_edit(name):
    creds = load_credentials()
    credential = next((c for c in creds if c.get("name")==name), None)
    if not credential:
        flash("Credential not found", "error")
        return redirect(url_for("credentials"))
    if request.method == "POST":
        user = request.form.get("user","").strip()
        key = request.form.get("key","").strip()
        env = request.form.get("env", MYDATA_ENV).strip()
        vat = request.form.get("vat","").strip()
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

# Bulk fetch page (date inputs + choose credential)
@app.route("/fetch", methods=["GET","POST"])
def fetch():
    message = None
    error = None
    creds = load_credentials()
    cached_preview = load_cache()[:40]  # preview top 40
    if request.method == "POST":
        date_from = request.form.get("date_from")
        date_to = request.form.get("date_to")
        selected = request.form.get("use_credential") or ""
        vat = request.form.get("vat_number","").strip()
        # choose credentials
        aade_user = AADE_USER_ENV
        aade_key = AADE_KEY_ENV
        if selected:
            c = next((x for x in creds if x.get("name")==selected), None)
            if c:
                aade_user = c.get("user","")
                aade_key = c.get("key","")
                vat = vat or c.get("vat","")
        # try mydatanaut first if vendored
        try:
            res = None
            if HAS_MYDATANAUT:
                res = fetch_docs_with_mydatanaut(date_from, date_to, vat, aade_user, aade_key)
            if res is None:
                parsed = fetch_docs_via_requestdocs(date_from, date_to, vat, aade_user, aade_key)
                # try to extract docs array - common keys
                docs_list = []
                if isinstance(parsed, dict):
                    if "RequestedDoc" in parsed:
                        maybe = parsed.get("RequestedDoc")
                        if isinstance(maybe, list):
                            docs_list = maybe
                        else:
                            docs_list = [maybe]
                    elif "docs" in parsed:
                        docs_list = parsed.get("docs") or []
                    else:
                        # fallback: wrap parsed
                        docs_list = [parsed]
                elif isinstance(parsed, list):
                    docs_list = parsed
                else:
                    docs_list = []
                added = 0
                for d in docs_list:
                    if append_doc_to_cache(d):
                        added += 1
                message = f"Fetched {len(docs_list)} items, newly cached: {added}"
            else:
                # mydatanaut returned something - try to normalize to list
                if isinstance(res, list):
                    docs = res
                elif isinstance(res, dict) and "docs" in res:
                    docs = res["docs"]
                else:
                    docs = [res]
                added = 0
                for d in docs:
                    if append_doc_to_cache(d):
                        added += 1
                message = f"Fetched {len(docs)} items via mydatanaut, newly cached: {added}"
        except Exception as e:
            traceback.print_exc()
            error = f"Σφάλμα λήψης: {e}"
    return render_template("fetch.html", credentials=creds, message=message, error=error, preview=cached_preview)

# Viewer / search MARK exact
@app.route("/search", methods=["GET","POST"])
def search():
    result = None
    error = None
    mark = ""
    if request.method == "POST":
        mark = request.form.get("mark","").strip()
        if not mark or not mark.isdigit() or len(mark)!=15:
            error = "Πρέπει να δώσεις έγκυρο 15ψήφιο MARK."
        else:
            doc = find_invoice_by_mark_exact(mark)
            if not doc:
                error = f"MARK {mark} όχι στην cache. Κάνε πρώτα Bulk Fetch."
            else:
                result = doc
    return render_template("search.html", result=result, error=error, mark=mark)

# Save summary to Excel (uses pandas & openpyxl)
@app.route("/save_excel", methods=["POST"])
def save_excel():
    summ = request.form.get("summary_json")
    if summ:
        try:
            row = json.loads(summ)
            df = pd.DataFrame([row])
            if os.path.exists(EXCEL_FILE):
                df_existing = pd.read_excel(EXCEL_FILE, engine="openpyxl", dtype=str)
                df_concat = pd.concat([df_existing, df], ignore_index=True, sort=False)
                df_concat.to_excel(EXCEL_FILE, index=False, engine="openpyxl")
            else:
                df.to_excel(EXCEL_FILE, index=False, engine="openpyxl")
            flash("Saved to Excel", "success")
        except Exception as e:
            flash(f"Excel save error: {e}", "error")
    return redirect(url_for("search"))

# List & download excel
@app.route("/list", methods=["GET"])
def list_invoices():
    download = request.args.get("download")
    if download and os.path.exists(EXCEL_FILE):
        return send_file(EXCEL_FILE, as_attachment=True, download_name="invoices.xlsx")
    # render simple table from cache or excel
    table = []
    if os.path.exists(EXCEL_FILE):
        try:
            df = pd.read_excel(EXCEL_FILE, engine="openpyxl", dtype=str).fillna("")
            table = df.to_dict(orient="records")
        except Exception:
            pass
    else:
        table = load_cache()
    return render_template("list.html", table=table)

# Cron-like endpoint (protected by secret)
@app.route("/cron_fetch", methods=["GET"])
def cron_fetch():
    secret = request.args.get("secret")
    CRON_SECRET = os.getenv("CRON_SECRET","")
    if not CRON_SECRET or secret != CRON_SECRET:
        return ("Forbidden", 403)
    # use ENV credentials or first saved credential
    creds = load_credentials()
    if creds:
        aade_user = creds[0].get("user","")
        aade_key = creds[0].get("key","")
        vat = creds[0].get("vat","")
    else:
        aade_user = AADE_USER_ENV
        aade_key = AADE_KEY_ENV
        vat = os.getenv("ENTITY_VAT","")
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
            if append_doc_to_cache(d):
                added += 1
        return f"Cron fetch done. New: {added}\n"
    except Exception as e:
        return (f"Cron fetch error: {e}", 500)

# static files, health
@app.route("/health")
def health():
    return "OK"

# ---- start ----
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=True)
