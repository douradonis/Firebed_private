#!/usr/bin/env python3
# app.py - myDATA webapp (Flask)
# Features:
# - Stored credentials (local JSON)
# - Bulk fetch (RequestDocs) saving parsed responses to local cache JSON
# - Exact MARK search only against cache (no fallback)
# - Save summary rows to Excel (pandas/openpyxl) or CSV fallback
# - List cached invoices, download excel, delete selected
# - Optional QR decode from uploaded images/PDFs (requires pyzbar/pdf2image/poppler)

import os
import io
import re
import json
import datetime
from urllib.parse import urlparse, parse_qs
from flask import (
    Flask, request, render_template_string, url_for, send_file, redirect, flash, abort
)
from dotenv import load_dotenv
import requests
import xmltodict
import pandas as pd

# optional image/qr libs
from PIL import Image
try:
    from pyzbar.pyzbar import decode as qr_decode
except Exception:
    qr_decode = None
try:
    from pdf2image import convert_from_bytes
except Exception:
    convert_from_bytes = None

# ---------------------- Config ----------------------
load_dotenv()
AADE_USER = os.getenv("AADE_USER_ID", "")
AADE_KEY = os.getenv("AADE_SUBSCRIPTION_KEY", "")
ENTITY_VAT = os.getenv("ENTITY_VAT", "")
ENV = (os.getenv("MYDATA_ENV", "sandbox") or "sandbox").lower()

# endpoints (RequestDocs)
MYDOCS_URL = (
    "https://mydataapidev.aade.gr/myDATA/RequestDocs"
    if ENV in ("sandbox", "demo", "dev")
    else "https://mydatapi.aade.gr/myDATA/RequestDocs"
)

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET", "change-me-in-production")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

EXCEL_FILE = os.path.join(UPLOAD_DIR, "invoices.xlsx")
CACHE_FILE = os.path.join(DATA_DIR, "invoices_cache.json")
CREDENTIALS_FILE = os.path.join(DATA_DIR, "credentials.json")

# ---------------------- Utilities ----------------------
def json_read_file(path):
    try:
        if not os.path.exists(path):
            return []
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f) or []
    except Exception:
        return []

def json_write_file(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)

# ---------------------- Credentials helpers ----------------------
def load_credentials(file=CREDENTIALS_FILE):
    creds = json_read_file(file)
    if not isinstance(creds, list):
        return []
    return creds

def save_credential_entry(entry, file=CREDENTIALS_FILE):
    """
    entry: {'name','user','key','env','vat'}
    returns (True, None) or (False, reason)
    """
    if not entry.get("name"):
        return (False, "Missing name")
    creds = load_credentials(file)
    for c in creds:
        if str(c.get("name")) == str(entry.get("name")):
            return (False, "Όνομα credential υπάρχει ήδη")
    entry_to_save = {
        "name": str(entry.get("name")),
        "user": str(entry.get("user", "")),
        "key": str(entry.get("key", "")),
        "env": str(entry.get("env", "") or "sandbox"),
        "vat": str(entry.get("vat", "") or ""),
        "created": datetime.datetime.utcnow().isoformat() + "Z"
    }
    creds.append(entry_to_save)
    json_write_file(file, creds)
    return (True, None)

def delete_credential(name, file=CREDENTIALS_FILE):
    creds = load_credentials(file)
    new = [c for c in creds if c.get("name") != name]
    if len(new) == len(creds):
        return False
    json_write_file(file, new)
    return True

def mask_key(k):
    if not k:
        return ""
    s = str(k)
    if len(s) <= 8:
        return "****"
    return "****" + s[-6:]

# ---------------------- Cache helpers ----------------------
def doc_contains_mark_exact(obj, mark):
    """Recursively check whether any string field exactly equals the mark."""
    if obj is None:
        return False
    if isinstance(obj, str):
        return obj.strip() == str(mark).strip()
    if isinstance(obj, dict):
        for v in obj.values():
            if doc_contains_mark_exact(v, mark):
                return True
    if isinstance(obj, list):
        for v in obj:
            if doc_contains_mark_exact(v, mark):
                return True
    return False

def load_cached_invoices(file=CACHE_FILE):
    docs = json_read_file(file)
    if not isinstance(docs, list):
        return []
    return docs

def save_doc_to_cache(file, doc):
    """
    Save doc to cache if does not already contain the same mark
    or identical JSON signature.
    """
    docs = load_cached_invoices(file)
    # signature check
    try:
        new_sig = md5_of_json(doc)
    except Exception:
        new_sig = None
    # existing signatures
    for d in docs:
        try:
            if new_sig is not None and md5_of_json(d) == new_sig:
                return False
        except Exception:
            pass
    # try extract any mark strings in doc and ensure not present already
    marks_found = find_marks_in_obj(doc)
    for m in marks_found:
        for d in docs:
            if doc_contains_mark_exact(d, m):
                return False
    docs.append(doc)
    json_write_file(file, docs)
    return True

def md5_of_json(obj):
    import hashlib
    s = json.dumps(obj, ensure_ascii=False, sort_keys=True)
    return hashlib.md5(s.encode("utf-8")).hexdigest()

def find_marks_in_obj(obj):
    """
    Search recursively for any 15-digit strings inside obj; return list of unique marks.
    """
    marks = set()
    if obj is None:
        return []
    if isinstance(obj, str):
        for m in re.findall(r"\b\d{15}\b", obj):
            marks.add(m)
        return list(marks)
    if isinstance(obj, dict):
        for v in obj.values():
            for m in find_marks_in_obj(v):
                marks.add(m)
    if isinstance(obj, list):
        for v in obj:
            for m in find_marks_in_obj(v):
                marks.add(m)
    return list(marks)

def find_invoice_in_cache_by_mark(file, mark):
    docs = load_cached_invoices(file)
    for d in docs:
        if doc_contains_mark_exact(d, mark):
            return d
    return None

def delete_marks_from_cache(file, marks):
    if not marks:
        return 0
    docs = load_cached_invoices(file)
    remain = [d for d in docs if not any(doc_contains_mark_exact(d, m) for m in marks)]
    removed = len(docs) - len(remain)
    if removed > 0:
        json_write_file(file, remain)
    return removed

# ---------------------- QR decode helper (optional) ----------------------
def decode_qr_from_file_bytes(file_bytes, filename):
    """
    If pyzbar and pdf2image are present, try to decode a QR from image or PDF.
    Returns first decoded text or None.
    """
    try:
        if filename.lower().endswith(".pdf") and convert_from_bytes:
            images = convert_from_bytes(file_bytes)
            for img in images:
                if qr_decode:
                    codes = qr_decode(img)
                    for c in codes:
                        try:
                            return c.data.decode("utf-8")
                        except Exception:
                            return str(c.data)
            return None
        else:
            if not qr_decode:
                return None
            img = Image.open(io.BytesIO(file_bytes))
            codes = qr_decode(img)
            if not codes:
                return None
            try:
                return codes[0].data.decode("utf-8")
            except Exception:
                return str(codes[0].data)
    except Exception:
        return None

# ---------------------- API fetch helpers ----------------------
def fetch_docs_via_api(request_docs_url, date_from, date_to, vat, aade_user, aade_key):
    """
    Call RequestDocs with dateFrom/dateTo (YYYY-MM-DD or other) and vatNumber.
    Returns parsed dict (xmltodict) or raises Exception on error.
    """
    # convert to dd/MM/YYYY
    try:
        d1 = datetime.datetime.strptime(date_from, "%Y-%m-%d").strftime("%d/%m/%Y")
    except Exception:
        d1 = date_from
    try:
        d2 = datetime.datetime.strptime(date_to, "%Y-%m-%d").strftime("%d/%m/%Y")
    except Exception:
        d2 = date_to

    params = {"dateFrom": d1, "dateTo": d2}
    if vat:
        params["vatNumber"] = vat

    headers = {
        "aade-user-id": aade_user or AADE_USER,
        "ocp-apim-subscription-key": aade_key or AADE_KEY,
        "Accept": "application/xml",
    }

    r = requests.get(request_docs_url, headers=headers, params=params, timeout=60)
    if r.status_code >= 400:
        raise Exception(f"API error {r.status_code}: {r.text}")

    # parse XML (handle wrapper with <string> containing XML text)
    outer = xmltodict.parse(r.text)
    inner = None
    if isinstance(outer.get("string"), dict):
        inner = outer.get("string").get("#text")
    parsed = None
    if inner:
        parsed = xmltodict.parse(inner)
    else:
        parsed = outer
    return parsed

def extract_docs_from_parsed(parsed):
    """
    Try to extract a list of logical 'docs' from parsed xml/dict.
    Returns list (maybe empty) of doc dicts.
    """
    if not parsed:
        return []
    docs = []
    # common shapes: parsed.get('docs'), parsed.get('RequestedDoc'), parsed.get('RequestedDocs'), parsed.get('Docs')
    if isinstance(parsed, dict):
        for k in ("docs", "Docs", "RequestedDoc", "RequestedDocs", "docsList", "RequestedDocument"):
            if k in parsed:
                item = parsed[k]
                if isinstance(item, list):
                    docs.extend(item)
                else:
                    # sometimes docs is dict with 'RequestedDoc' child
                    docs.append(item)
                # don't break; continue searching deeper
        # fallback: if parsed has 'RequestedDoc' nested deeper
        # flatten any dict values that look like docs
        if not docs:
            # scan keys for something that contains 'invoice' or 'RequestedDoc'
            def walk(o):
                if isinstance(o, dict):
                    for kk, vv in o.items():
                        if isinstance(vv, (dict, list)):
                            for x in walk(vv):
                                yield x
                        else:
                            pass
                elif isinstance(o, list):
                    for item in o:
                        for x in walk(item):
                            yield x
                else:
                    return
            # best-effort: return the original parsed as a single doc
            return [parsed]
    elif isinstance(parsed, list):
        return parsed
    return docs or [parsed]

# ---------------------- Summarize & Excel helpers ----------------------
INVOICE_TYPE_MAP = {
    "1.1": "Τιμολόγιο Πώλησης",
    "1.2": "Τιμολόγιο Πώλησης / Ενδοκοινοτικές Παραδόσεις",
    "2.1": "Τιμολόγιο Παροχής Υπηρεσιών",
    "17.6": "Λοιπές Εγγραφές Τακτοποίησης Εξόδων - Φορολογική Βάση",
}

def summarize_parsed_doc(parsed):
    summary = {
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
    try:
        # find any mark
        marks = find_marks_in_obj(parsed)
        if marks:
            summary["MARK"] = marks[0]
        issuer = parsed.get("issuer") if isinstance(parsed, dict) else None
        if isinstance(issuer, dict):
            summary["ΑΦΜ"] = issuer.get("vatNumber", "") or issuer.get("VATNumber", "") or summary["ΑΦΜ"]
            summary["Επωνυμία"] = issuer.get("name", "") or issuer.get("companyName", "") or summary["Επωνυμία"]
        header = parsed.get("invoiceHeader") if isinstance(parsed, dict) else {}
        if isinstance(header, dict):
            summary["Σειρά"] = header.get("series") or header.get("Series") or summary["Σειρά"]
            summary["Αριθμός"] = header.get("aa") or header.get("AA") or header.get("number") or summary["Αριθμός"]
            datev = header.get("issueDate") or header.get("IssueDate") or header.get("date")
            if datev:
                # try to format
                try:
                    dt = datetime.datetime.strptime(datev[:10], "%Y-%m-%d")
                    summary["Ημερομηνία"] = dt.strftime("%d/%m/%Y")
                except Exception:
                    summary["Ημερομηνία"] = datev
            itype = header.get("invoiceType") or header.get("InvoiceType") or ""
            summary["Είδος"] = INVOICE_TYPE_MAP.get(str(itype).strip(), str(itype).strip())
        totals = parsed.get("invoiceSummary") if isinstance(parsed, dict) else {}
        if isinstance(totals, dict):
            summary["Καθαρή Αξία"] = totals.get("totalNetValue") or totals.get("TotalNetValue") or summary["Καθαρή Αξία"]
            summary["ΦΠΑ"] = totals.get("totalVatAmount") or totals.get("TotalVatAmount") or summary["ΦΠΑ"]
            summary["Σύνολο"] = totals.get("totalGrossValue") or totals.get("TotalGrossValue") or summary["Σύνολο"]
    except Exception:
        pass
    return summary

def save_summary_to_excel_file(summary_rows, filepath=EXCEL_FILE):
    """
    summary_rows: list of dicts with keys matching header.
    If pandas+openpyxl available, append/update excel; else fallback CSV.
    """
    df_new = pd.DataFrame(summary_rows)
    # normalize columns order
    desired = ["MARK","ΑΦΜ","Επωνυμία","Σειρά","Αριθμός","Ημερομηνία","Είδος","Καθαρή Αξία","ΦΠΑ","Σύνολο"]
    cols = [c for c in desired if c in df_new.columns] + [c for c in df_new.columns if c not in desired]
    df_new = df_new[cols]
    # try append intelligently
    try:
        if os.path.exists(filepath):
            try:
                df_old = pd.read_excel(filepath, engine="openpyxl", dtype=str).fillna("")
            except Exception:
                df_old = None
            if df_old is not None:
                # avoid duplicates by MARK + ΑΦΜ + Αριθμός maybe
                if "MARK" in df_old.columns:
                    existing_marks = set(df_old["MARK"].astype(str).str.strip().tolist())
                    to_append = df_new[~df_new["MARK"].astype(str).str.strip().isin(existing_marks)]
                    if to_append.empty:
                        return False
                    df_out = pd.concat([df_old, to_append], ignore_index=True, sort=False)
                else:
                    df_out = pd.concat([df_old, df_new], ignore_index=True, sort=False)
                df_out.to_excel(filepath, index=False, engine="openpyxl")
                return True
        # write new file
        df_new.to_excel(filepath, index=False, engine="openpyxl")
        return True
    except Exception:
        # fallback CSV
        try:
            headless = not os.path.exists(filepath)
            with open(filepath, "a", encoding="utf-8", newline="") as f:
                if headless:
                    f.write(",".join(cols) + "\n")
                for _, row in df_new.iterrows():
                    vals = []
                    for c in cols:
                        v = row.get(c, "")
                        if pd.isna(v):
                            v = ""
                        vals.append('"' + str(v).replace('"', '""') + '"')
                    f.write(",".join(vals) + "\n")
            return True
        except Exception:
            return False

# ---------------------- Templates ----------------------
# Using render_template_string for simplicity; keep HTML minimal but functional.

NAV_HTML = """<!doctype html>
<html lang="el"><head><meta charset="utf-8"><title>myDATA - Μενού</title>
<style>body{font-family:Arial,sans-serif;max-width:900px;margin:20px auto;background:#fafafa}.card{background:white;padding:16px;margin:16px 0;border-radius:12px;box-shadow:0 2px 6px rgba(0,0,0,0.05)}.menu{display:flex;gap:12px;flex-wrap:wrap}.menu a{display:block;padding:12px 18px;background:#0d6efd;color:#fff;border-radius:10px;text-decoration:none}.menu a.secondary{background:#6c757d}</style></head><body>
<div class="card"><h1>myDATA - Κεντρικό Μενού</h1>
<p>Επέλεξε λειτουργία:</p>
<div class="menu">
<a href="{{ url_for('viewer') }}">Εισαγωγή Παραστατικού</a>
<a href="{{ url_for('fetch_route') }}">Λήψη Παραστατικών (bulk)</a>
<a href="{{ url_for('list_invoices') }}">Λίστα Παραστατικών</a>
<a href="{{ url_for('options') }}" class="secondary">Επιλογές / Credentials</a>
</div></div></body></html>"""

VIEWER_HTML = """<!doctype html>
<html lang="el"><head><meta charset="utf-8"><title>Viewer</title>
<style>body{font-family:Arial,sans-serif;max-width:900px;margin:20px auto;background:#fafafa}.card{background:#fff;padding:16px;margin:16px 0;border-radius:12px;box-shadow:0 2px 6px rgba(0,0,0,0.05)}input,button{width:100%;padding:8px;margin:6px 0;border-radius:8px}button{background:#0d6efd;color:white;border:0;cursor:pointer}pre{white-space:pre-wrap;background:#f7f7f7;padding:10px;border-radius:8px}</style></head><body>
<h1>myDATA - Viewer</h1>
<p><a href="{{ url_for('home') }}">⬅ Επιστροφή στο μενού</a></p>
<div class="card">
<h3>Αναζήτηση MARK (ακριβής, από cache)</h3>
<form method="post" enctype="multipart/form-data">
<input type="text" name="mark" placeholder="π.χ. 123456789012345">
<input type="file" name="file">
<button type="submit">Αναζήτηση</button>
</form>
</div>

{% if message %}<div class="card" style="background:#e6ffed;"><pre>{{ message }}</pre></div>{% endif %}
{% if error %}<div class="card" style="background:#fff5f5;"><pre>{{ error }}</pre></div>{% endif %}
{% if invoice %}
<div class="card"><h3>Παραστατικό</h3><pre>{{ invoice }}</pre></div>
<form method="post" action="{{ url_for('save_excel') }}">
  <input type="hidden" name="mark" value="{{ found_mark }}">
  {% for k,v in summary.items() %}
    <input type="hidden" name="summ[{{ k }}]" value="{{ v }}">
  {% endfor %}
  <button type="submit">Αποθήκευση Περίληψης στο Excel</button>
</form>
{% endif %}

</body></html>"""

FETCH_HTML = """<!doctype html>
<html lang="el"><head><meta charset="utf-8"><title>Λήψη Παραστατικών</title>
<style>body{font-family:Arial,sans-serif;max-width:900px;margin:20px auto;background:#fafafa}.card{background:#fff;padding:16px;margin:16px 0;border-radius:12px;box-shadow:0 2px 6px rgba(0,0,0,0.05)}input,button,select{padding:8px;margin:6px 0;border-radius:8px}button{background:#0d6efd;color:#fff;border:0;cursor:pointer}.small{display:inline-block;padding:6px 10px;border-radius:8px;background:#6c757d;color:#fff}</style></head><body>
<h1>Λήψη Παραστατικών (Bulk)</h1>
<p><a href="{{ url_for('home') }}">⬅ Επιστροφή</a></p>
<div class="card">
<form method="post">
<p>Ημερομηνία Από: <input type="date" name="date_from" required value="{{ date_from }}"></p>
<p>Έως: <input type="date" name="date_to" required value="{{ date_to }}"></p>
<p>VAT Number (entity): <input type="text" name="vat_number" placeholder="π.χ. 123456789" value="{{ vat }}"></p>
<p>Ή επέλεξε stored credential:
  <select name="use_credential">
    <option value="">(ENV / Default)</option>
    {% for c in credentials %}
      <option value="{{ c.name }}">{{ c.name }} {{ c.vat and '('~c.vat~')' }}</option>
    {% endfor %}
  </select>
</p>
<button type="submit">Λήψη & Αποθήκευση Cache</button>
</form>
</div>

{% if message %}<div class="card" style="background:#e6ffed;"><pre>{{ message }}</pre></div>{% endif %}
{% if error %}<div class="card" style="background:#fff5f5;"><pre>{{ error }}</pre></div>{% endif %}

<div class="card">
<h3>Cache Preview</h3>
{% if cache_preview %}
  <div style="max-height:400px;overflow:auto;">{{ cache_preview | safe }}</div>
{% else %}
  <div>Δεν υπάρχουν cached παραστατικά.</div>
{% endif %}
</div>

</body></html>"""

LIST_HTML = """<!doctype html>
<html lang="el"><head><meta charset="utf-8"><title>Λίστα Παραστατικών</title>
<style>body{font-family:Arial,sans-serif;max-width:1200px;margin:20px auto;background:#fafafa}.card{background:#fff;padding:16px;margin:16px 0;border-radius:12px}table{border-collapse:collapse;width:100%}th,td{border:1px solid #ddd;padding:8px;text-align:left}th{background:#0d6efd;color:#fff}tr:nth-child(even){background:#f9f9f9}button.small{padding:8px 12px;border-radius:6px}</style></head><body>
<div class="card">
<h1>Λίστα Παραστατικών</h1>
<div style="margin-bottom:12px;">
<a href="{{ url_for('home') }}">⬅ Επιστροφή</a>
<a href="{{ url_for('list_invoices') }}?download=1"><button class="small">⬇️ Κατέβασμα .xlsx</button></a>
</div>

{% if table_html %}
<form method="post" action="{{ url_for('delete_invoices') }}">
<div style="overflow:auto;">{{ table_html | safe }}</div>
<div style="margin-top:10px;">
<button type="submit" class="small" style="background:#dc3545;color:#fff;padding:8px 12px;border:none;border-radius:6px;">Διαγραφή Επιλεγμένων</button>
</div>
</form>
{% else %}
  <div>Δεν υπάρχουν εγγραφές προς εμφάνιση.</div>
{% endif %}

</div></body></html>"""

OPTIONS_HTML = """<!doctype html><html lang="el"><head><meta charset="utf-8"><title>Options</title>
<style>body{font-family:Arial,sans-serif;max-width:900px;margin:20px auto;background:#fafafa}.card{background:#fff;padding:16px;margin:16px 0;border-radius:12px}table{width:100%;border-collapse:collapse}th,td{border:1px solid #ddd;padding:8px;text-align:left}th{background:#0d6efd;color:#fff}</style></head><body>
<div class="card"><h1>Credentials / Διαχείριση</h1>
<p>Τα credentials αποθηκεύονται τοπικά στο server (data/credentials.json). Τα πλήρη κλειδιά δεν εμφανίζονται.</p>
{% if msg %}<div style="background:#e6ffed;padding:8px;margin-bottom:8px;">{{ msg }}</div>{% endif %}
{% if err %}<div style="background:#fff5f5;padding:8px;margin-bottom:8px;">{{ err }}</div>{% endif %}
<h3>Προσθήκη νέου credential</h3>
<form method="post">
<p>Όνομα (προβολή/επιλογή):<br><input name="name" required style="width:60%"></p>
<p>AADE User ID:<br><input name="user" style="width:60%"></p>
<p>AADE Subscription Key:<br><input name="key" style="width:60%"></p>
<p>Env:<br><select name="env"><option value="sandbox">sandbox</option><option value="production">production</option></select></p>
<p>Default VAT (optional):<br><input name="vat" style="width:40%"></p>
<p><button type="submit">Αποθήκευση Credential</button></p>
</form>

<h3>Αποθηκευμένα Credentials</h3>
{% if credentials %}
<table><thead><tr><th>Όνομα</th><th>VAT</th><th>Env</th><th>AADE User</th><th>Key</th><th>Δράσεις</th></tr></thead><tbody>
{% for c in credentials %}
<tr>
<td>{{ c.name }}</td>
<td>{{ c.vat }}</td>
<td>{{ c.env }}</td>
<td>{{ c.user }}</td>
<td>{{ c._key_masked }}</td>
<td>
<form method="post" action="{{ url_for('credentials_delete') }}" style="display:inline">
<input type="hidden" name="name" value="{{ c.name }}">
<button type="submit" onclick="return confirm('Διαγραφή credential;')">Διαγραφή</button>
</form>
</td>
</tr>
{% endfor %}
</tbody></table>
{% else %}
<div>Δεν υπάρχουν αποθηκευμένα credentials.</div>
{% endif %}

<p><a href="{{ url_for('home') }}">⬅ Επιστροφή</a></p>
</div></body></html>"""

# ---------------------- Routes ----------------------
@app.route("/")
def home():
    return render_template_string(NAV_HTML)

@app.route("/options", methods=["GET", "POST"])
def options():
    msg = ""
    err = ""
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        user = (request.form.get("user") or "").strip()
        key = (request.form.get("key") or "").strip()
        env = (request.form.get("env") or "sandbox").strip()
        vat = (request.form.get("vat") or "").strip()
        if not name:
            err = "Συμπλήρωσε όνομα για το credential."
        else:
            ok, reason = save_credential_entry({"name": name, "user": user, "key": key, "env": env, "vat": vat})
            if ok:
                msg = "Το credential αποθηκεύτηκε."
            else:
                err = reason or "Αποτυχία αποθήκευσης."
    creds = load_credentials()
    for c in creds:
        c["_key_masked"] = mask_key(c.get("key", ""))
    return render_template_string(OPTIONS_HTML, credentials=creds, msg=msg, err=err)

@app.route("/credentials/delete", methods=["POST"])
def credentials_delete():
    name = request.form.get("name")
    if not name:
        flash("Missing credential name to delete", "error")
        return redirect(url_for("options"))
    ok = delete_credential(name)
    if ok:
        flash("Credential διαγράφηκε.", "success")
    else:
        flash("Το credential δεν βρέθηκε.", "error")
    return redirect(url_for("options"))

@app.route("/viewer", methods=["GET", "POST"])
def viewer():
    message = ""
    error = ""
    invoice = None
    summary = None
    found_mark = None
    if request.method == "POST":
        mark_input = (request.form.get("mark") or "").strip()
        file = request.files.get("file")
        mark = None
        if file and file.filename:
            data = file.read()
            decoded = decode_qr_from_file_bytes(data, file.filename)
            if decoded:
                # try extract mark from decoded text
                m = re.search(r"\b\d{15}\b", decoded)
                if m:
                    mark = m.group(0)
            # if not decoded, fallback to input text
        if not mark and mark_input:
            if re.fullmatch(r"\d{15}", mark_input):
                mark = mark_input
            else:
                # try extract any 15-digit in the input (URL or text)
                m = re.search(r"\d{15}", mark_input)
                if m:
                    mark = m.group(0)
        if not mark:
            error = "Δεν βρέθηκε έγκυρο MARK."
        else:
            found_mark = mark
            doc = find_invoice_in_cache_by_mark(CACHE_FILE, mark)
            if not doc:
                error = f"Δεν βρέθηκε παραστατικό με MARK {mark} στην cache. Πρέπει πρώτα να κάνεις Bulk fetch."
            else:
                invoice = json.dumps(doc, ensure_ascii=False, indent=2)
                summary = summarize_parsed_doc(doc)
                message = f"Βρέθηκε παραστατικό στην cache (MARK {mark})."
    return render_template_string(VIEWER_HTML, message=message, error=error, invoice=invoice, summary=summary, found_mark=found_mark)

@app.route("/save_excel", methods=["POST"])
def save_excel():
    if request.method == "POST":
        summ = request.form.getlist("summ")
        # older form may post summ as dict; try reading from request.form dict
        summ_dict = {}
        for k in request.form:
            if k.startswith("summ["):
                # name like summ[MARK]
                m = re.match(r"summ\[(.+?)\]", k)
                if m:
                    summ_dict[m.group(1)] = request.form.get(k)
        if not summ_dict:
            # try request.form.get('summ') - sometimes it's nested; fallback parse
            # Or try JSON in 'summ' key
            s = request.form.get("summ")
            try:
                if s:
                    summ_dict = json.loads(s)
            except Exception:
                summ_dict = {}
        # If still empty, try 'summ' as multi-value fields (Flask returns lists)
        if not summ_dict and "summ" in request.form:
            try:
                summ_dict = request.form.get("summ")
            except Exception:
                summ_dict = {}
        if summ_dict:
            # convert to list with single row
            ok = save_summary_to_excel_file([summ_dict])
            if ok:
                flash("Η περίληψη αποθηκεύτηκε στο αρχείο Excel.", "success")
            else:
                flash("Αποτυχία αποθήκευσης στο Excel.", "error")
    return redirect(url_for("list_invoices"))

@app.route("/fetch", methods=["GET", "POST"])
def fetch_route():
    message = ""
    error = ""
    cache_preview = ""
    date_from = (request.form.get("date_from") if request.method == "POST" else (datetime.date.today() - datetime.timedelta(days=30)).isoformat())
    date_to = (request.form.get("date_to") if request.method == "POST" else datetime.date.today().isoformat())
    vat = (request.form.get("vat_number") if request.method == "POST" else ENTITY_VAT or "")
    credentials = load_credentials()

    if request.method == "POST":
        use_credential = request.form.get("use_credential") or ""
        aade_user = AADE_USER
        aade_key = AADE_KEY
        req_env = ENV
        if use_credential:
            for c in credentials:
                if c.get("name") == use_credential:
                    aade_user = c.get("user") or aade_user
                    aade_key = c.get("key") or aade_key
                    req_env = c.get("env") or req_env
                    vat = c.get("vat") or vat
                    break
        try:
            parsed = fetch_docs_via_api(MYDOCS_URL, date_from, date_to, vat, aade_user, aade_key)
            docs = extract_docs_from_parsed(parsed)
            saved = 0
            for d in docs:
                if save_doc_to_cache(CACHE_FILE, d):
                    saved += 1
            message = f"Λήφθηκαν {len(docs)} αντικείμενα. Νέα αποθηκεύτηκαν: {saved}."
        except Exception as e:
            error = f"Σφάλμα λήψης: {e}"

    # show small preview of cache
    cached = load_cached_invoices(CACHE_FILE)
    if cached:
        rows = []
        for i, d in enumerate(cached[:200]):
            s = summarize_parsed_doc(d)
            rows.append(s)
        try:
            df = pd.DataFrame(rows)
            table_html = df.to_html(classes="summary-table", index=False, escape=False)
            cache_preview = table_html
        except Exception:
            # fallback manual table
            table_html = "<table><thead><tr>"
            headers = ["MARK","ΑΦΜ","Επωνυμία","Σειρά","Αριθμός","Ημερομηνία","Είδος","Καθαρή Αξία","ΦΠΑ","Σύνολο"]
            for h in headers:
                table_html += f"<th>{h}</th>"
            table_html += "</tr></thead><tbody>"
            for s in rows:
                table_html += "<tr>"
                for h in headers:
                    table_html += "<td>" + str(s.get(h, "")) + "</td>"
                table_html += "</tr>"
            table_html += "</tbody></table>"
            cache_preview = table_html

    return render_template_string(FETCH_HTML, message=message, error=error, cache_preview=cache_preview, date_from=date_from, date_to=date_to, vat=vat, credentials=credentials)

@app.route("/list", methods=["GET"])
def list_invoices():
    # download excel?
    if request.args.get("download"):
        # produce excel from cache summary on the fly
        cached = load_cached_invoices(CACHE_FILE)
        rows = [summarize_parsed_doc(d) for d in cached]
        if not rows:
            return render_template_string(PLACEHOLDER_HTML(), title="Εξαγωγή", message="Δεν υπάρχουν εγγραφές.")
        # attempt excel
        try:
            df = pd.DataFrame(rows)
            tmp = io.BytesIO()
            with pd.ExcelWriter(tmp, engine="openpyxl") as writer:
                df.to_excel(writer, index=False)
            tmp.seek(0)
            return send_file(tmp, as_attachment=True, download_name="invoices.xlsx", mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        except Exception:
            # csv fallback
            tmp = io.BytesIO()
            csv = pd.DataFrame(rows).to_csv(index=False).encode("utf-8")
            tmp.write(csv)
            tmp.seek(0)
            return send_file(tmp, as_attachment=True, download_name="invoices.csv", mimetype="text/csv")

    # render table from cache
    cached = load_cached_invoices(CACHE_FILE)
    rows = [summarize_parsed_doc(d) for d in cached]
    table_html = ""
    if rows:
        try:
            df = pd.DataFrame(rows)
            # add checkbox column
            df.insert(0, "✓", ['<input type="checkbox" name="delete_mark" value="{}">'.format(r.get("MARK","")) for r in rows])
            table_html = df.to_html(classes="summary-table", index=False, escape=False)
            table_html = table_html.replace("<th>✓</th>", '<th><input type="checkbox" id="selectAll" onclick="toggleAll(this)"></th>')
            table_html = table_html.replace("<td>", '<td><div style="white-space:pre-wrap;word-break:break-word;">').replace("</td>", "</div></td>")
        except Exception:
            # manual
            headers = ["✓","MARK","ΑΦΜ","Επωνυμία","Σειρά","Αριθμός","Ημερομηνία","Είδος","Καθαρή Αξία","ΦΠΑ","Σύνολο"]
            table_html = "<table class='summary-table'><thead><tr>"
            for h in headers:
                table_html += f"<th>{h}</th>"
            table_html += "</tr></thead><tbody>"
            for r in rows:
                table_html += "<tr>"
                table_html += '<td><input type="checkbox" name="delete_mark" value="{}"></td>'.format(r.get("MARK",""))
                for h in headers[1:]:
                    table_html += "<td>{}</td>".format(r.get(h,""))
                table_html += "</tr>"
            table_html += "</tbody></table>"
    return render_template_string(LIST_HTML, table_html=table_html)

@app.route("/delete", methods=["POST"])
def delete_invoices():
    marks = request.form.getlist("delete_mark")
    if not marks:
        return redirect(url_for("list_invoices"))
    removed = delete_marks_from_cache(CACHE_FILE, marks)
    # Also remove matching rows from EXCEL file if it's excel
    if os.path.exists(EXCEL_FILE):
        try:
            df = pd.read_excel(EXCEL_FILE, engine="openpyxl", dtype=str).fillna("")
            if "MARK" in df.columns:
                df = df[~df["MARK"].astype(str).isin([str(m).strip() for m in marks])]
                df.to_excel(EXCEL_FILE, index=False, engine="openpyxl")
        except Exception:
            # CSV fallback
            try:
                lines = []
                with open(EXCEL_FILE, "r", encoding="utf-8") as f:
                    for i, line in enumerate(f):
                        if i == 0:
                            lines.append(line)
                        else:
                            if any(m in line for m in marks):
                                continue
                            lines.append(line)
                with open(EXCEL_FILE, "w", encoding="utf-8") as f:
                    f.writelines(lines)
            except Exception:
                pass
    flash(f"Διαγράφηκαν {removed} αντικείμενα από cache (εάν υπήρχαν).", "info")
    return redirect(url_for("list_invoices"))

@app.route("/export_excel")
def export_excel():
    # convenience endpoint - produce excel from cache
    cached = load_cached_invoices(CACHE_FILE)
    rows = [summarize_parsed_doc(d) for d in cached]
    if not rows:
        return render_template_string(PLACEHOLDER_HTML(), title="Export", message="Δεν υπάρχουν εγγραφές.")
    try:
        df = pd.DataFrame(rows)
        tmp = io.BytesIO()
        with pd.ExcelWriter(tmp, engine="openpyxl") as writer:
            df.to_excel(writer, index=False)
        tmp.seek(0)
        return send_file(tmp, as_attachment=True, download_name="invoices.xlsx", mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    except Exception:
        tmp = io.BytesIO()
        csv = pd.DataFrame(rows).to_csv(index=False).encode("utf-8")
        tmp.write(csv)
        tmp.seek(0)
        return send_file(tmp, as_attachment=True, download_name="invoices.csv", mimetype="text/csv")

# small placeholder template function for download errors
def PLACEHOLDER_HTML():
    return """<!doctype html><html lang="el"><head><meta charset="utf-8"><title>{{ title }}</title></head><body><div style="max-width:900px;margin:20px auto;"><h1>{{ title }}</h1><p>{{ message }}</p><p><a href='{}'>⬅ Επιστροφή</a></p></div></body></html>""".format(url_for("home"))

# ---------------------- Run ----------------------
if __name__ == "__main__":
    # run local dev server
    app.run(debug=True, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
