# app.py
import os
import io
import json
import re
import datetime
from urllib.parse import urlparse, parse_qs

from flask import Flask, request, render_template, url_for, send_file, redirect, flash
import requests
import xmltodict
import pandas as pd

# ---------------------- Config ----------------------
ENV = (os.getenv("MYDATA_ENV", "sandbox") or "sandbox").lower()
AADE_USER = os.getenv("AADE_USER_ID", "")
AADE_KEY = os.getenv("AADE_SUBSCRIPTION_KEY", "")
ENTITY_VAT = os.getenv("ENTITY_VAT", "")

MYDOCS_URL = (
    "https://mydataapidev.aade.gr/myDATA/RequestDocs"
    if ENV in ("sandbox", "demo", "dev")
    else "https://mydatapi.aade.gr/myDATA/RequestDocs"
)

# ---------------------- Flask ----------------------
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET", "dev-secret")

ROOT = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(ROOT, "uploads")
DATA_FOLDER = os.path.join(ROOT, "data")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(DATA_FOLDER, exist_ok=True)

EXCEL_FILE = os.path.join(UPLOAD_FOLDER, "invoices.xlsx")
CACHE_FILE = os.path.join(DATA_FOLDER, "invoices_cache.json")
CREDENTIALS_FILE = os.path.join(DATA_FOLDER, "credentials.json")

# ---------------------- Helpers ----------------------
def json_read_file(path):
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f) or []
    except Exception:
        return []

def json_write_file(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def extract_mark_from_text(text):
    if not text:
        return None
    text = text.strip()
    if re.fullmatch(r"\d{15}", text):
        return text
    try:
        parsed = urlparse(text)
        qs = parse_qs(parsed.query or "")
        for k in ("mark", "MARK", "invoiceMark", "invMark"):
            if k in qs and re.fullmatch(r"\d{15}", qs[k][0]):
                return qs[k][0]
    except Exception:
        pass
    m = re.search(r"\b\d{15}\b", text)
    return m.group(0) if m else None

def find_invoice_in_cache_by_mark(mark):
    docs = json_read_file(CACHE_FILE)
    for d in docs:
        if contains_mark_exact(d, str(mark)):
            return d
    return None

def contains_mark_exact(node, mark):
    """Recursively search dict/list/str for exact string equal to mark."""
    if node is None:
        return False
    if isinstance(node, str):
        return node.strip() == str(mark).strip()
    if isinstance(node, (int, float)):
        return str(node) == str(mark)
    if isinstance(node, dict):
        for v in node.values():
            if contains_mark_exact(v, mark):
                return True
    if isinstance(node, list):
        for i in node:
            if contains_mark_exact(i, mark):
                return True
    return False

def save_doc_to_cache(doc):
    docs = json_read_file(CACHE_FILE)
    # uniqueness by serialized content (prevents exact dupes)
    sig = json.dumps(doc, sort_keys=True, ensure_ascii=False)
    for d in docs:
        if json.dumps(d, sort_keys=True, ensure_ascii=False) == sig:
            return False
    docs.append(doc)
    json_write_file(CACHE_FILE, docs)
    return True

def save_summary_to_excel(summary_row):
    # Try pandas/openpyxl if available, else simple CSV fallback
    df_new = pd.DataFrame([summary_row])
    if os.path.exists(EXCEL_FILE):
        try:
            df_old = pd.read_excel(EXCEL_FILE, engine="openpyxl", dtype=str).fillna("")
            # avoid duplicate row with same MARK and totals
            if "MARK" in df_old.columns and str(summary_row.get("MARK")) in df_old["MARK"].astype(str).values:
                return False
            df_all = pd.concat([df_old, df_new], ignore_index=True, sort=False)
        except Exception:
            df_all = pd.concat([pd.DataFrame(columns=df_new.columns), df_new], ignore_index=True, sort=False)
    else:
        df_all = df_new
    # write
    df_all.to_excel(EXCEL_FILE, index=False, engine="openpyxl")
    return True

def parse_requestdocs_xml(xml_text):
    """Parse RequestDocs response to python dict via xmltodict (best-effort)."""
    try:
        outer = xmltodict.parse(xml_text)
        inner = outer.get("string", {}).get("#text") if isinstance(outer.get("string"), dict) else None
        parsed = xmltodict.parse(inner) if inner else outer
        return parsed
    except Exception:
        # last resort: empty
        return None

def fetch_docs(date_from, date_to, vat_number, user_id=None, subscription_key=None):
    """Call RequestDocs endpoint and return parsed data structure (dict)"""
    headers = {
        "aade-user-id": user_id or AADE_USER,
        "ocp-apim-subscription-key": subscription_key or AADE_KEY,
        "Accept": "application/xml"
    }
    # API expects dd/MM/YYYY
    try:
        d1 = datetime.datetime.strptime(date_from, "%Y-%m-%d").strftime("%d/%m/%Y")
        d2 = datetime.datetime.strptime(date_to, "%Y-%m-%d").strftime("%d/%m/%Y")
    except Exception:
        d1 = date_from
        d2 = date_to
    params = {"dateFrom": d1, "dateTo": d2, "vatNumber": vat_number}
    r = requests.get(MYDOCS_URL, headers=headers, params=params, timeout=60)
    if r.status_code >= 400:
        raise Exception(f"API error {r.status_code}: {r.text}")
    parsed = parse_requestdocs_xml(r.text)
    return parsed

def summarize_parsed_doc(parsed):
    """Small heuristic summarizer used when saving to Excel"""
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
        "Σύνολο": ""
    }
    if not parsed:
        return row
    # try common paths
    def get(d, *keys):
        for k in keys:
            if isinstance(d, dict) and k in d:
                return d[k]
        return None
    # try several places
    docs_candidate = None
    if isinstance(parsed, dict):
        # typical shapes: parsed['docs'], parsed['RequestedDoc'], parsed.get('Docs')
        if "RequestedDoc" in parsed:
            docs_candidate = parsed["RequestedDoc"]
        elif "docs" in parsed:
            docs_candidate = parsed["docs"]
        elif "Docs" in parsed:
            docs_candidate = parsed["Docs"]
        else:
            docs_candidate = parsed
    else:
        docs_candidate = parsed
    # try to get first invoice-like node
    invoice = None
    if isinstance(docs_candidate, dict):
        # many shapes -> try to find 'invoice' key
        if "invoice" in docs_candidate:
            invoice = docs_candidate["invoice"]
        else:
            # take first meaningful child
            for v in docs_candidate.values():
                if isinstance(v, (dict, list)):
                    invoice = v
                    break
    elif isinstance(docs_candidate, list):
        invoice = docs_candidate[0] if docs_candidate else None
    if isinstance(invoice, list):
        invoice = invoice[0]
    if isinstance(invoice, dict):
        issuer = invoice.get("issuer", {})
        header = invoice.get("invoiceHeader", {}) or {}
        summary = invoice.get("invoiceSummary", {}) or {}
        # simple assignments
        row["ΑΦΜ"] = issuer.get("vatNumber") or issuer.get("VATNumber") or row["ΑΦΜ"]
        row["Επωνυμία"] = issuer.get("name") or issuer.get("companyName") or row["Επωνυμία"]
        row["Σειρά"] = header.get("series") or header.get("Series") or row["Σειρά"]
        row["Αριθμός"] = header.get("aa") or header.get("AA") or header.get("Number") or row["Αριθμός"]
        dateval = header.get("issueDate") or header.get("IssueDate") or None
        if dateval:
            try:
                dt = datetime.datetime.strptime(dateval[:10], "%Y-%m-%d")
                row["Ημερομηνία"] = dt.strftime("%d/%m/%Y")
            except Exception:
                row["Ημερομηνία"] = dateval
        row["Είδος"] = header.get("invoiceType") or header.get("InvoiceType") or row["Είδος"]
        row["Καθαρή Αξία"] = summary.get("totalNetValue") or summary.get("TotalNetValue") or row["Καθαρή Αξία"]
        row["ΦΠΑ"] = summary.get("totalVatAmount") or summary.get("TotalVatAmount") or row["ΦΠΑ"]
        row["Σύνολο"] = summary.get("totalGrossValue") or summary.get("TotalGrossValue") or row["Σύνολο"]
        # find mark if present anywhere
        def walker(o):
            if o is None:
                return None
            if isinstance(o, str) and re.fullmatch(r"\d{15}", o):
                return o
            if isinstance(o, dict):
                for k, v in o.items():
                    if re.search(r"mark", k, re.IGNORECASE) and isinstance(v, str) and re.fullmatch(r"\d{15}", v):
                        return v
                    r = walker(v)
                    if r:
                        return r
            if isinstance(o, list):
                for i in o:
                    r = walker(i)
                    if r:
                        return r
            return None
        found_mark = walker(invoice)
        if found_mark:
            row["MARK"] = found_mark
    return row

# ---------------------- Routes ----------------------
@app.route("/")
def home():
    return render_template("nav.html")

@app.route("/viewer", methods=["GET","POST"])
def viewer():
    message = ""
    error = ""
    invoice = None
    if request.method == "POST":
        mark_input = (request.form.get("mark") or "").strip()
        file = request.files.get("file")
        mark = None
        if file and file.filename:
            # we don't implement QR decode in this version; try extracting text-like mark from filename
            mark = extract_mark_from_text(file.filename)
        if not mark and mark_input:
            mark = extract_mark_from_text(mark_input)
        if not mark:
            error = "Δεν δόθηκε έγκυρος MARK (15 ψηφία)."
        else:
            doc = find_invoice_in_cache_by_mark(mark)
            if doc:
                invoice = json.dumps(doc, ensure_ascii=False, indent=2)
                message = f"Παραστατικό με MARK {mark} βρέθηκε στην cache."
            else:
                error = f"Δεν βρέθηκε παραστατικό με MARK {mark} στην cache. Πρέπει πρώτα να κάνεις λήψη (Bulk)."
    return render_template("viewer.html", message=message, error=error, invoice=invoice)

@app.route("/fetch", methods=["GET","POST"])
def fetch_route():
    message = ""
    error = ""
    table_preview = None
    creds = json_read_file(CREDENTIALS_FILE)
    if request.method == "POST":
        date_from = request.form.get("date_from")
        date_to = request.form.get("date_to")
        vat = request.form.get("vat_number") or ENTITY_VAT
        use_cred = request.form.get("use_credential") or ""
        aade_user = AADE_USER
        aade_key = AADE_KEY
        if use_cred:
            for c in creds:
                if c.get("name") == use_cred:
                    aade_user = c.get("user") or aade_user
                    aade_key = c.get("key") or aade_key
                    vat = c.get("vat") or vat
                    break
        try:
            parsed = fetch_docs(date_from, date_to, vat, user_id=aade_user, subscription_key=aade_key)
            # parsed may contain a list or nested structure; we attempt to extract docs list
            docs_list = []
            if isinstance(parsed, dict):
                # common containers
                if "docs" in parsed and isinstance(parsed["docs"], list):
                    docs_list = parsed["docs"]
                elif "RequestedDoc" in parsed:
                    rd = parsed["RequestedDoc"]
                    if isinstance(rd, list):
                        docs_list = rd
                    else:
                        docs_list = [rd]
                else:
                    # fallback: try to find any dict/list children
                    found = []
                    def walk_for_docs(o):
                        if isinstance(o, dict):
                            for k, v in o.items():
                                if isinstance(v, list):
                                    found.append(v)
                                else:
                                    walk_for_docs(v)
                        elif isinstance(o, list):
                            for i in o:
                                walk_for_docs(i)
                    walk_for_docs(parsed)
                    if found:
                        # flatten first found list
                        docs_list = found[0]
                    else:
                        docs_list = [parsed]
            elif isinstance(parsed, list):
                docs_list = parsed
            # save docs to cache
            new_count = 0
            for d in docs_list:
                if save_doc_to_cache(d):
                    new_count += 1
            message = f"Λήφθηκαν {len(docs_list)} αντικείμενα. Νέα αποθηκεύτηκαν: {new_count}."
        except Exception as e:
            error = f"Σφάλμα κατά την κλήση API: {e}"
    # prepare preview of cache
    cached = json_read_file(CACHE_FILE)
    if cached:
        table_preview = cached[:200]  # limit preview size
    return render_template("fetch.html", message=message, error=error, preview=table_preview, credentials=creds, default_vat=ENTITY_VAT)

@app.route("/list", methods=["GET","POST"])
def list_route():
    # allow delete marks (from cache & excel)
    if request.method == "POST":
        to_delete = request.form.getlist("delete_mark")
        if to_delete:
            # delete from cache
            docs = json_read_file(CACHE_FILE)
            docs = [d for d in docs if not any(contains_mark_exact(v, m) for m in to_delete for v in [d])]
            json_write_file(CACHE_FILE, docs)
            # delete from excel if exists
            if os.path.exists(EXCEL_FILE):
                try:
                    df = pd.read_excel(EXCEL_FILE, engine="openpyxl", dtype=str).fillna("")
                    if "MARK" in df.columns:
                        df = df[~df["MARK"].astype(str).isin([str(x) for x in to_delete])]
                        df.to_excel(EXCEL_FILE, index=False, engine="openpyxl")
                except Exception:
                    pass
    # show excel or csv
    table_html = None
    error = ""
    if os.path.exists(EXCEL_FILE):
        try:
            df = pd.read_excel(EXCEL_FILE, engine="openpyxl", dtype=str).fillna("")
            table_html = df.to_html(classes="summary-table", index=False, escape=False)
        except Exception as e:
            error = f"Σφάλμα ανάγνωσης Excel: {e}"
    else:
        error = "Δεν υπάρχει αρχείο Excel με αποθηκευμένες περιλήψεις."
    return render_template("list.html", table_html=table_html, error=error)

@app.route("/save_excel", methods=["POST"])
def save_excel_route():
    summ = request.form.get("summ")
    if not summ:
        flash("Δεν δόθηκε περίληψη.")
        return redirect(url_for("viewer"))
    try:
        parsed = json.loads(summ)
    except Exception:
        parsed = {}
    row = summarize_parsed_doc(parsed)
    if save_summary_to_excel(row):
        flash("Αποθηκεύτηκε στο Excel.")
    else:
        flash("Ήδη υπάρχει η εγγραφή στο Excel.")
    return redirect(url_for("list_route"))

@app.route("/download_excel")
def download_excel():
    if os.path.exists(EXCEL_FILE):
        return send_file(EXCEL_FILE, as_attachment=True)
    return "Δεν υπάρχει αρχείο Excel.", 404

# ---------------------- Templates folder ----------------------
# Ensure templates directory exists (Flask will load templates from 'templates')
# Place the HTML files listed below into templates/ directory.

# ---------------------- Run ----------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=(os.getenv("FLASK_DEBUG", "0") == "1"))
