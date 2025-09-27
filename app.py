
import os
import sys
import json
import traceback
import logging
from logging.handlers import RotatingFileHandler
from typing import Any, List, Dict, Optional
import datetime
from datetime import datetime as _dt
from werkzeug.utils import secure_filename

from markupsafe import escape, Markup
from flask import Flask, render_template, request, redirect, url_for, send_file, flash, jsonify, session

import requests
import pandas as pd

# local mydata helper
from fetch import request_docs

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

DATA_DIR = os.path.join(BASE_DIR, "data")
UPLOADS_DIR = os.path.join(BASE_DIR, "uploads")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(UPLOADS_DIR, exist_ok=True)

CACHE_FILE = os.path.join(DATA_DIR, "invoices_cache.json")
SUMMARY_FILE = os.path.join(DATA_DIR, "summary.json")
CREDENTIALS_FILE = os.path.join(DATA_DIR, "credentials.json")
DEFAULT_EXCEL_FILE = os.path.join(UPLOADS_DIR, "invoices.xlsx")
ERROR_LOG = os.path.join(DATA_DIR, "error.log")

AADE_USER_ENV = os.getenv("AADE_USER_ID", "")
AADE_KEY_ENV = os.getenv("AADE_SUBSCRIPTION_KEY", "")
MYDATA_ENV = (os.getenv("MYDATA_ENV") or "sandbox").lower()

app = Flask(__name__, template_folder=TEMPLATES_DIR)
app.secret_key = os.getenv("FLASK_SECRET", "change-me")
app.config["UPLOAD_FOLDER"] = UPLOADS_DIR

# Logging (unchanged)
log = logging.getLogger("mydata_app")
log.setLevel(logging.INFO)
if not log.handlers:
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(sh)

    fh = RotatingFileHandler(ERROR_LOG, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
    fh.setLevel(logging.INFO)
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s\n"))
    log.addHandler(fh)

log.info("Starting app - MYDATA_ENV=%s", MYDATA_ENV)

# ---------------- Helpers ---------------- (most unchanged)
def json_read(path: str):
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        log.exception("json_read failed for %s", path)
        return []

def json_write(path: str, data: Any):
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

def load_cache():
    data = json_read(CACHE_FILE)
    return data if isinstance(data, list) else []

def save_cache(docs):
    json_write(CACHE_FILE, docs)

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
    docs.append(doc)
    save_cache(docs)
    return True

def save_summary_list(summary_list: List[Dict]):
    """Save summary_list to SUMMARY_FILE (overwrites)."""
    try:
        json_write(SUMMARY_FILE, summary_list)
    except Exception:
        log.exception("Could not write summary file")

# ---------------- small new helpers for per-customer files ----------------
def get_cred_by_name(name: str) -> Optional[Dict]:
    if not name:
        return None
    creds = load_credentials()
    return next((c for c in creds if c.get("name") == name), None)

def excel_path_for(cred_name: Optional[str] = None, vat: Optional[str] = None) -> str:
    """
    Return path to excel file for given credential. Priority: vat -> cred_name -> default.
    Filenames: {vat}_invoices.xlsx  OR  {cred_name}_invoices.xlsx  OR default invoices.xlsx
    """
    if vat:
        fn = f"{vat}_invoices.xlsx"
        return os.path.join(UPLOADS_DIR, secure_filename(fn))
    if cred_name:
        fn = f"{cred_name}_invoices.xlsx"
        return os.path.join(UPLOADS_DIR, secure_filename(fn))
    return DEFAULT_EXCEL_FILE

def get_active_credential_from_session() -> Optional[Dict]:
    name = session.get("active_credential")
    return get_cred_by_name(name) if name else None

# στο app.py — κάτω από get_active_credential_from_session()
@app.context_processor
def inject_active_credential():
    """
    Εισάγει αυτόματα στα templates:
      - active_credential: όνομα credential ή None
      - active_credential_vat: ΑΦΜ του active credential (ή empty string)
    """
    active = get_active_credential_from_session()
    name = active.get("name") if active else None
    vat = active.get("vat") if active else ""
    return dict(active_credential=name, active_credential_vat=vat)

# ---------------- Validation helper ----------------
def normalize_input_date_to_iso(s: str):
    if not s:
        return None
    s = s.strip()
    try:
        dt = datetime.datetime.strptime(s, "%d/%m/%Y")
        return dt.date().isoformat()
    except ValueError:
        return None

# ---------------- safe render ----------------
def safe_render(template_name, **ctx):
    try:
        return render_template(template_name, **ctx)
    except Exception as e:
        tb = traceback.format_exc()
        log.error("Template rendering failed for %s: %s\n%s", template_name, str(e), tb)
        debug = os.getenv("FLASK_DEBUG", "0") == "1"
        body = "<h2>Template error</h2><p>" + escape(str(e)) + "</p>"
        if debug:
            body += "<pre>" + escape(tb) + "</pre>"
        return body

# ---------------- Routes ----------------
@app.route("/")
def home():
    return safe_render("nav.html", active_page="home")

# credentials CRUD (unchanged behaviour) but pass active credential to template
@app.route("/credentials", methods=["GET", "POST"])
def credentials():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        user = request.form.get("user", "").strip()
        key = request.form.get("key", "").strip()
        env = MYDATA_ENV
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
    active = session.get("active_credential")
    return safe_render("credentials_list.html", credentials=creds, active_credential=active, active_page="credentials")

@app.route("/credentials/edit/<name>", methods=["GET", "POST"])
def credentials_edit(name):
    creds = load_credentials()
    credential = next((c for c in creds if c.get("name") == name), None)
    if not credential:
        flash("Credential not found", "error")
        return redirect(url_for("credentials"))

    if request.method == "POST":
        new_name = (request.form.get("name") or "").strip()
        user = (request.form.get("user") or "").strip()
        key = (request.form.get("key") or "").strip()
        env = (request.form.get("env") or MYDATA_ENV).strip()
        vat = (request.form.get("vat") or "").strip()

        if not new_name:
            flash("Name required", "error")
            return redirect(url_for("credentials_edit", name=name))

        if new_name != name and any(c.get("name") == new_name for c in creds):
            flash("Another credential with that name already exists", "error")
            return redirect(url_for("credentials_edit", name=name))

        new_entry = {"name": new_name, "user": user, "key": key, "env": env, "vat": vat}
        updated = False
        for i, c in enumerate(creds):
            if c.get("name") == name:
                creds[i] = new_entry
                updated = True
                break
        if not updated:
            creds.append(new_entry)

        save_credentials(creds)

        # if the edited credential was active, update session to new name
        if session.get("active_credential") == name:
            session["active_credential"] = new_name

        flash("Updated", "success")
        return redirect(url_for("credentials"))

    flash(f"Editing credential: {credential.get('name')}", "success")
    return safe_render("credentials_edit.html", credential=credential, active_page="credentials")

@app.route("/credentials/delete/<name>", methods=["POST"])
def credentials_delete(name):
    # if deleting active credential, unset session active
    if session.get("active_credential") == name:
        session.pop("active_credential", None)
    delete_credential(name)
    flash("Deleted", "success")
    return redirect(url_for("credentials"))

# New route: set active credential
@app.route("/set_active", methods=["POST"])
def set_active_credential():
    name = request.form.get("active_name")
    if not name:
        flash("No credential selected", "error")
    else:
        cred = get_cred_by_name(name)
        if not cred:
            flash("Credential not found", "error")
        else:
            session["active_credential"] = name
            flash(f"Active credential set to {name}", "success")
    return redirect(url_for("credentials"))

# ---------------- Fetch page ----------------
# ---------------- Helpers for per-customer JSON & summary ----------------
def json_read(path: str):
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        log.exception("json_read failed for %s", path)
        return []

def json_write(path: str, data: Any):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)

def append_doc_to_customer_file(doc, vat):
    """
    Add a doc to per-customer JSON file, avoiding duplicates.
    Filename: data/{VAT}_invoices.json
    """
    if not vat:
        return False
    customer_file = os.path.join(DATA_DIR, f"{vat}_invoices.json")
    cache = json_read(customer_file)
    sig = json.dumps(doc, sort_keys=True, ensure_ascii=False)
    for d in cache:
        try:
            if json.dumps(d, sort_keys=True, ensure_ascii=False) == sig:
                return False
        except Exception:
            if str(d) == str(doc):
                return False
    cache.append(doc)
    json_write(customer_file, cache)
    return True

def append_summary_to_customer_file(summary, vat):
    """
    Save summary for a customer into per-customer summary JSON
    Filename: data/{VAT}_summary.json
    """
    if not vat:
        return False
    summary_file = os.path.join(DATA_DIR, f"{vat}_summary.json")
    summaries = json_read(summary_file)
    # avoid duplicate by MARK
    mark = str(summary.get("mark", "")).strip()
    if any(str(s.get("mark", "")).strip() == mark for s in summaries):
        return False
    summaries.append(summary)
    json_write(summary_file, summaries)
    return True

def get_customer_summary_file(vat):
    return os.path.join(DATA_DIR, f"{vat}_summary.json")

def get_customer_docs_file(vat):
    return os.path.join(DATA_DIR, f"{vat}_invoices.json")



# ---------------- Fetch page (updated with per-customer summary) ----------------

@app.route("/fetch", methods=["GET", "POST"])
def fetch():
    message = None
    error = None
    preview = []  # <-- preview για template
    creds = load_credentials()
    active_cred = get_active_credential_from_session()
    active_name = active_cred.get("name") if active_cred else None

    def float_from_comma(value):
        """Convert string with ',' decimal or '.' thousand separator to float safely."""
        if value is None:
            return 0.0
        if isinstance(value, (int, float)):
            return float(value)
        s = str(value).strip().replace(".", "").replace(",", ".")
        try:
            return float(s)
        except Exception:
            return 0.0

    if request.method == "POST":
        date_from_raw = request.form.get("date_from", "").strip()
        date_to_raw = request.form.get("date_to", "").strip()

        date_from_iso = normalize_input_date_to_iso(date_from_raw)
        date_to_iso = normalize_input_date_to_iso(date_to_raw)

        if not date_from_iso or not date_to_iso:
            error = "Παρακαλώ συμπλήρωσε έγκυρες ημερομηνίες (dd/mm/YYYY)."
            return safe_render(
                "fetch.html",
                credentials=creds,
                message=message,
                error=error,
                preview=preview,
                active_page="fetch",
                active_credential=active_name
            )

        d1 = datetime.datetime.fromisoformat(date_from_iso).strftime("%d/%m/%Y")
        d2 = datetime.datetime.fromisoformat(date_to_iso).strftime("%d/%m/%Y")

        selected = request.form.get("use_credential") or session.get("active_credential") or ""
        vat = request.form.get("vat_number", "").strip()
        aade_user = AADE_USER_ENV
        aade_key = AADE_KEY_ENV
        if selected:
            c = next((x for x in creds if x.get("name") == selected), None)
            if c:
                aade_user = c.get("user") or aade_user
                aade_key = c.get("key") or aade_key
                vat = vat or c.get("vat", "")
                session["active_credential"] = c.get("name")

        if not aade_user or not aade_key:
            error = "Δεν υπάρχουν αποθηκευμένα credentials για την κλήση."
            return safe_render(
                "fetch.html",
                credentials=creds,
                message=message,
                error=error,
                preview=preview,
                active_page="fetch",
                active_credential=active_name
            )

        try:
            all_rows, summary_list = request_docs(
                date_from=d1,
                date_to=d2,
                mark="000000000000000",
                aade_user=aade_user,
                aade_key=aade_key,
                debug=True,
                save_excel=False
            )

            # Αποθήκευση σε per-customer JSON
            added_docs = 0
            added_summaries = 0
            for d in all_rows:
                if append_doc_to_customer_file(d, vat):
                    added_docs += 1

            for s in summary_list:
                if append_summary_to_customer_file(s, vat):
                    added_summaries += 1

            message = (f"Fetched {len(all_rows)} items, newly saved for VAT {vat}: "
                       f"{added_docs} docs, {added_summaries} summaries.")

            # Προετοιμασία preview πρώτων 40 εγγραφών
            preview = all_rows[:40]

        except Exception as e:
            log.exception("Fetch error")
            error = f"Σφάλμα λήψης: {str(e)[:400]}"

    return safe_render(
        "fetch.html",
        credentials=creds,
        message=message,
        error=error,
        preview=preview,  # <-- περνάμε το preview στο template
        active_page="fetch",
        active_credential=active_name
    )






# ---------------- MARK search ----------------
@app.route("/search", methods=["GET", "POST"])
def search():
    result = None
    error = None
    mark = ""
    modal_summary = None

    def _map_invoice_type_local(code):
        INVOICE_TYPE_MAP = {
            "1.1": "Τιμολόγιο Πώλησης",
            "1.2": "Τιμολόγιο Πώλησης / Ενδοκοινοτικές Παραδόσεις",
            "1.3": "Τιμολόγιο Πώλησης / Παραδόσεις Τρίτων Χωρών",
            "1.4": "Τιμολόγιο Πώλησης / Πώληση για Λογαριασμό Τρίτων",
            "1.5": "Τιμολόγιο Πώλησης / Εκκαθάριση Πωλήσεων Τρίτων - Αμοιβή από Πωλήσεις Τρίτων",
            "1.6": "Τιμολόγιο Πώλησης / Συμπληρωματικό Παραστατικό",
            "2.1": "Τιμολόγιο Παροχής Υπηρεσιών",
        }
        return INVOICE_TYPE_MAP.get(str(code), str(code) or "")

    mapper = globals().get("map_invoice_type", None) or _map_invoice_type_local

    def float_from_comma(value):
        if value is None:
            return 0.0
        if isinstance(value, (int, float)):
            return float(value)
        s = str(value).strip().replace(".", "").replace(",", ".")
        try:
            return float(s)
        except Exception:
            return 0.0

    if request.method == "POST":
        mark = request.form.get("mark", "").strip()
        active_cred = get_active_credential_from_session()
        vat = active_cred.get("vat") if active_cred else None

        if not vat:
            error = "Επέλεξε πρώτα έναν πελάτη (ΑΦΜ) για αναζήτηση."
        elif not mark or not mark.isdigit() or len(mark) != 15:
            error = "Πρέπει να δώσεις έγκυρο 15ψήφιο MARK."
        else:
            # load per-customer JSON file
            customer_file = os.path.join(DATA_DIR, f"{vat}_invoices.json")
            cache = json_read(customer_file)
            doc = next((d for d in cache if str(d.get("mark", "")).strip() == mark), None)

            if not doc:
                error = f"MARK {mark} όχι στην cache του πελάτη {vat}. Κάνε πρώτα Fetch."
            else:
                result = doc

                def pick(src: dict, *keys, default=""):
                    for k in keys:
                        if k in src and src.get(k) not in (None, ""):
                            return src.get(k)
                    return default

                total_net_f = float_from_comma(pick(doc, "totalNetValue", "totalNet", "net", default=0))
                total_vat_f = float_from_comma(pick(doc, "totalVatAmount", "totalVat", "vat", default=0))
                total_value_f = total_net_f + total_vat_f

                modal_summary = {
                    "mark": mark,
                    "AA": pick(doc, "AA", "aa", default=""),
                    "AFM": pick(doc, "AFM", default=""),
                    "Name": pick(doc, "Name", "Name_issuer", default=""),
                    "series": pick(doc, "series", "Series", "serie", default=""),
                    "number": pick(doc, "number", "aa", "AA", default=""),
                    "issueDate": pick(doc, "issueDate", "issue_date", default=""),
                    "totalNetValue": pick(doc, "totalNetValue", "totalNet", 0),
                    "totalVatAmount": pick(doc, "totalVatAmount", "totalVat", 0),
                    "totalValue": f"{total_value_f:.2f}",
                    "type": pick(doc, "type", "invoiceType", default=""),
                    "type_name": mapper(pick(doc, "type", "invoiceType", default=""))
                }

    return safe_render(
        "search.html",
        result=result,
        error=error,
        mark=mark,
        modal_summary=modal_summary,
        active_page="search"
    )




# ---------------- Save summary from modal to Excel & cache ----------------
# ---------------- Save summary from modal to Excel & per-customer JSON ----------------
@app.route("/save_summary", methods=["POST"])
def save_summary():
    try:
        payload = request.form.get("summary_json") or request.get_data(as_text=True)
        if not payload:
            flash("No summary provided", "error")
            return redirect(url_for("search"))
        summary = json.loads(payload)
    except Exception as e:
        flash(f"Invalid summary data: {e}", "error")
        return redirect(url_for("search"))

    # Επιλέγουμε τον πελάτη από session
    active = get_active_credential_from_session()
    vat = active.get("vat") if active else summary.get("AFM")
    if not vat:
        flash("No active customer selected (VAT)", "error")
        return redirect(url_for("search"))

    # Helper για float
    def float_from_comma(value):
        if value is None:
            return 0.0
        if isinstance(value, (int, float)):
            return float(value)
        s = str(value).strip().replace(".", "").replace(",", ".")
        try:
            return float(s)
        except Exception:
            return 0.0

    # Row για Excel
    total_net = float_from_comma(summary.get("totalNetValue", 0))
    total_vat = float_from_comma(summary.get("totalVatAmount", 0))
    total_value = float_from_comma(summary.get("totalValue", total_net + total_vat))

    row = {
        "MARK": str(summary.get("mark", "")),
        "ΑΦΜ": vat,
        "Επωνυμία": summary.get("Name", ""),
        "Σειρά": summary.get("series", ""),
        "Αριθμός": summary.get("number", ""),
        "Ημερομηνία": summary.get("issueDate", ""),
        "Είδος": summary.get("type", ""),
        "ΦΠΑ_ΚΑΤΗΓΟΡΙΑ": summary.get("vatCategory", ""),
        "Καθαρή Αξία": f"{total_net:.2f}",
        "ΦΠΑ": f"{total_vat:.2f}",
        "Σύνολο": f"{total_value:.2f}"
    }

    # Αποθήκευση σε per-customer summary JSON
    append_summary_to_customer_file(summary, vat)

    # Αποθήκευση σε Excel ανά πελάτη
    excel_path = excel_path_for(vat=vat)
    try:
        df_new = pd.DataFrame([row]).astype(str).fillna("")
        if os.path.exists(excel_path):
            df_existing = pd.read_excel(excel_path, engine="openpyxl", dtype=str).fillna("")
            df_concat = pd.concat([df_existing, df_new], ignore_index=True, sort=False)
            df_concat.to_excel(excel_path, index=False, engine="openpyxl")
        else:
            os.makedirs(os.path.dirname(excel_path) or ".", exist_ok=True)
            df_new.to_excel(excel_path, index=False, engine="openpyxl")
    except Exception as e:
        log.exception("save_summary: Excel write failed")
        flash(f"Excel save failed: {e}", "error")
        return redirect(url_for("search"))

    flash(f"Saved summary for VAT {vat} to JSON and Excel", "success")
    return redirect(url_for("list_invoices"))



# ---------------- List / download ----------------
@app.route("/list", methods=["GET"])
def list_invoices():
    # choose excel file based on active session credential
    active = get_active_credential_from_session()
    excel_path = DEFAULT_EXCEL_FILE
    if active and active.get("vat"):
        excel_path = excel_path_for(vat=active.get("vat"))
    elif active and active.get("name"):
        excel_path = excel_path_for(cred_name=active.get("name"))
    else:
        excel_path = DEFAULT_EXCEL_FILE

    if request.args.get("download") and os.path.exists(excel_path):
        # download the active client's file
        return send_file(excel_path, as_attachment=True, download_name=os.path.basename(excel_path),
                         mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    table_html = ""
    error = ""
    css_numcols = ""

    if os.path.exists(excel_path):
        try:
            df = pd.read_excel(excel_path, engine="openpyxl", dtype=str).fillna("")
            df = df.astype(str)

            if "ΦΠΑ_ΑΝΑΛΥΣΗ" in df.columns:
                df = df.drop(columns=["ΦΠΑ_ΑΝΑΛΥΣΗ"])

            if "MARK" in df.columns:
                checkboxes = df["MARK"].apply(lambda v: f'<input type="checkbox" name="delete_mark" value="{str(v)}">')
                df.insert(0, "✓", checkboxes)

            table_html = df.to_html(classes="summary-table", index=False, escape=False)
            table_html = table_html.replace("<th>✓</th>", '<th><input type="checkbox" id="selectAll" title="Επιλογή όλων"></th>')
            table_html = table_html.replace("<td>", '<td><div class="cell-wrap">').replace("</td>", "</div></td>")

            import re
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
        error = f"Δεν βρέθηκε το αρχείο {os.path.basename(excel_path)}."

    # pass active_credential name so navbar and templates can reflect it
    active_name = session.get("active_credential")
    return safe_render("list.html",
                       table_html=Markup(table_html),
                       error=error,
                       file_exists=os.path.exists(excel_path),
                       css_numcols=css_numcols,
                       active_page="list_invoices",
                       active_credential=active_name)

# ---------------- Delete invoices ----------------
@app.route("/delete", methods=["POST"])
def delete_invoices():
    marks_to_delete = request.form.getlist("delete_mark")
    if not marks_to_delete:
        flash("No marks selected", "error")
        return redirect(url_for("list_invoices"))

    # delete from active client's excel file (same logic as list)
    active = get_active_credential_from_session()
    excel_path = DEFAULT_EXCEL_FILE
    if active and active.get("vat"):
        excel_path = excel_path_for(vat=active.get("vat"))
    elif active and active.get("name"):
        excel_path = excel_path_for(cred_name=active.get("name"))
    else:
        excel_path = DEFAULT_EXCEL_FILE

    if os.path.exists(excel_path):
        try:
            df = pd.read_excel(excel_path, engine="openpyxl", dtype=str).fillna("")
            if "MARK" in df.columns:
                before = len(df)
                df = df[~df["MARK"].astype(str).isin([str(m).strip() for m in marks_to_delete])]
                after = len(df)
                if after != before:
                    df.to_excel(excel_path, index=False, engine="openpyxl")
        except Exception:
            log.exception("Σφάλμα διαγραφής")

    flash(f"Deleted {len(marks_to_delete)} rows (if existed)", "success")
    return redirect(url_for("list_invoices"))

# ---------------- Health ----------------
@app.route("/health")
def health():
    return "OK"

# ---------------- Global error handler ----------------
@app.errorhandler(Exception)
def handle_unexpected_error(e):
    tb = traceback.format_exc()
    log.error("Unhandled exception: %s\n%s", str(e), tb)
    debug = os.getenv("FLASK_DEBUG", "0") == "1"
    if debug:
        return "<pre>{}</pre>".format(escape(tb)), 500
    return safe_render("error_generic.html", message="Συνέβη σφάλμα στον server. Δες logs."), 500

@app.route('/favicon.ico')
def favicon():
    return '', 204

if __name__ == "__main__":
    port = int(os.getenv("PORT", "5001"))
    debug_flag = True
    app.run(host="0.0.0.0", port=port, debug=debug_flag, use_reloader=True)