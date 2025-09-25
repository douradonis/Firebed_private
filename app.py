# app.py (διορθωμένο, πλήρες)

import os
import sys
import json
import traceback
import logging
from logging.handlers import RotatingFileHandler
from typing import Any
import datetime
from datetime import datetime as _dt
from werkzeug.utils import secure_filename

from markupsafe import escape
from flask import Flask, render_template, request, redirect, url_for, send_file, flash

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
EXCEL_FILE = os.path.join(UPLOADS_DIR, "invoices.xlsx")
ERROR_LOG = os.path.join(DATA_DIR, "error.log")

AADE_USER_ENV = os.getenv("AADE_USER_ID", "")
AADE_KEY_ENV = os.getenv("AADE_SUBSCRIPTION_KEY", "")
MYDATA_ENV = (os.getenv("MYDATA_ENV") or "sandbox").lower()

app = Flask(__name__, template_folder=TEMPLATES_DIR)
app.secret_key = os.getenv("FLASK_SECRET", "change-me")
app.config["UPLOAD_FOLDER"] = UPLOADS_DIR

# Logging
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

# ---------------- Helpers ----------------
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

# ---------------- Summary helpers ----------------
def load_summary():
    data = json_read(SUMMARY_FILE)
    return data if isinstance(data, list) else []

def save_summary(summary_list):
    """
    Save/merge summary_list into SUMMARY_FILE.
    Avoid duplicate summaries by 'mark' field (if present).
    If summary_list is not a list, try to wrap it.
    """
    if summary_list is None:
        return
    if not isinstance(summary_list, list):
        try:
            summary_list = list(summary_list)
        except Exception:
            summary_list = [summary_list]

    existing = load_summary()
    # build index by mark if possible
    existing_by_mark = {}
    for e in existing:
        try:
            mk = str(e.get("mark")).strip()
        except Exception:
            mk = ""
        if mk:
            existing_by_mark[mk] = e

    changed = False
    for s in summary_list:
        if not isinstance(s, dict):
            continue
        mk = str(s.get("mark") or s.get("MARK") or "").strip()
        if mk:
            if mk not in existing_by_mark:
                existing.append(s)
                existing_by_mark[mk] = s
                changed = True
            else:
                # if mark exists, consider updating the existing entry (optional)
                # keep existing as-is to avoid overwriting
                pass
        else:
            # no mark -> try to avoid exact duplicate
            try:
                if s not in existing:
                    existing.append(s)
                    changed = True
            except Exception:
                existing.append(s)
                changed = True

    if changed:
        try:
            json_write(SUMMARY_FILE, existing)
        except Exception:
            log.exception("Could not write summary file")

# ---------------- Validation helper ----------------
def normalize_input_date_to_iso(s: str):
    """
    Δέχεται ημερομηνίες μόνο στη μορφή dd/mm/YYYY
    Επιστρέφει ISO μορφή YYYY-MM-DD ή None αν αποτύχει.
    """
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
    return safe_render("nav.html")

# credentials CRUD
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

# ---------------- Bulk fetch (/fetch) ----------------
@app.route("/fetch", methods=["GET", "POST"])
def fetch():
    message = None
    error = None
    creds = load_credentials()
    preview = load_cache()[:40]

    if request.method == "POST":
        date_from_raw = request.form.get("date_from", "").strip()
        date_to_raw = request.form.get("date_to", "").strip()

        date_from_iso = normalize_input_date_to_iso(date_from_raw)
        date_to_iso = normalize_input_date_to_iso(date_to_raw)

        if not date_from_iso or not date_to_iso:
            error = "Παρακαλώ συμπλήρωσε έγκυρες από-έως ημερομηνίες (dd/mm/YYYY)."
            return safe_render("fetch.html", credentials=creds, message=message, error=error, preview=preview)

        # μετατροπή ISO -> dd/mm/YYYY για fetch.py
        def iso_to_ddmmyyyy(iso_s: str) -> str:
            return datetime.datetime.fromisoformat(iso_s).strftime("%d/%m/%Y")

        d1 = iso_to_ddmmyyyy(date_from_iso)
        d2 = iso_to_ddmmyyyy(date_to_iso)

        # Επιλεγμένο credential
        selected = request.form.get("use_credential") or ""
        vat = request.form.get("vat_number", "").strip()
        aade_user = AADE_USER_ENV
        aade_key = AADE_KEY_ENV
        if selected:
            c = next((x for x in creds if x.get("name") == selected), None)
            if c:
                aade_user = c.get("user") or aade_user
                aade_key = c.get("key") or aade_key
                vat = vat or c.get("vat", "")

        if not aade_user or not aade_key:
            error = "Δεν υπάρχουν αποθηκευμένα credentials για την κλήση."
            return safe_render("fetch.html", credentials=creds, message=message, error=error, preview=preview)

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

            added = 0
            for d in all_rows:
                if append_doc_to_cache(d, aade_user, aade_key):
                    added += 1

            # ΑΠΟΘΗΚΕΥΣΗ summary_list στο data/summary.json
            try:
                save_summary(summary_list)
            except Exception:
                log.exception("Saving summary_list failed")

            message = f"Fetched {len(all_rows)} items, newly cached: {added}"
            preview = load_cache()[:40]

        except Exception as e:
            error = f"Σφάλμα λήψης: {str(e)[:400]}"

    return safe_render("fetch.html", credentials=creds, message=message, error=error, preview=preview)

# ---------------- Bulk fetch page (bulk_fetch) ----------------
@app.route("/bulk_fetch", methods=["GET", "POST"])
def bulk_fetch():
    creds = load_credentials()
    preview = load_cache()[:40]
    message = None
    error = None

    default_vat = ""
    if request.method == "POST":
        user = (request.form.get("use_credential") or "").strip()
        vat_input = request.form.get("vat_number", "").strip()

        # Επιλογή credential
        aade_user = AADE_USER_ENV
        aade_key = AADE_KEY_ENV
        vat = vat_input
        if user:
            c = next((x for x in creds if x.get("name") == user), None)
            if c:
                aade_user = c.get("user") or aade_user
                aade_key = c.get("key") or aade_key
                vat = vat or c.get("vat", "")

        # Dates
        date_from_raw = request.form.get("date_from", "").strip()
        date_to_raw = request.form.get("date_to", "").strip()

        def validate_ddmmyyyy(s):
            try:
                return _dt.strptime(s, "%d/%m/%Y")
            except Exception:
                return None

        d_from = validate_ddmmyyyy(date_from_raw)
        d_to = validate_ddmmyyyy(date_to_raw)

        if not d_from or not d_to:
            error = "Παρακαλώ συμπλήρωσε έγκυρες ημερομηνίες (dd/mm/YYYY)."
            return safe_render("bulk_fetch.html",
                               credentials=creds,
                               message=message,
                               error=error,
                               preview=preview,
                               default_vat=vat)

        try:
            all_rows, summary_list = request_docs(
                date_from=date_from_raw,
                date_to=date_to_raw,
                mark="000000000000000",
                aade_user=aade_user,
                aade_key=aade_key,
                debug=True,
                save_excel=False
            )

            added = 0
            for d in all_rows:
                if append_doc_to_cache(d, aade_user, aade_key):
                    added += 1

            # ΑΠΟΘΗΚΕΥΣΗ summary_list στο data/summary.json
            try:
                save_summary(summary_list)
            except Exception:
                log.exception("Saving summary_list failed (bulk_fetch)")

            message = f"Fetched {len(all_rows)} items, newly cached: {added}"
            preview = load_cache()[:40]

        except Exception as e:
            import traceback
            log.exception("Bulk fetch error")
            error = f"Σφάλμα λήψης: {str(e)[:400]}\n{traceback.format_exc()[:1000]}"

    return safe_render("bulk_fetch.html",
                       credentials=creds,
                       message=message,
                       error=error,
                       preview=preview,
                       default_vat="")

# ---------------- MARK search ----------------
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
            doc = next((d for d in load_cache() if d.get("mark") == mark), None)
            if not doc:
                error = f"MARK {mark} όχι στην cache. Κάνε πρώτα Bulk Fetch."
            else:
                result = doc
    return safe_render("search.html", result=result, error=error, mark=mark)

# ---------------- Save Excel ----------------
@app.route("/save_excel", methods=["POST"])
def save_excel():
    summ_json = request.form.get("summary_json")
    if summ_json:
        try:
            row = json.loads(summ_json)
            df = pd.DataFrame([row])
            if os.path.exists(EXCEL_FILE):
                df_existing = pd.read_excel(EXCEL_FILE, engine="openpyxl", dtype=str)
                df_concat = pd.concat([df_existing, df], ignore_index=True, sort=False)
                df_concat.to_excel(EXCEL_FILE, index=False, engine="openpyxl")
            else:
                df.to_excel(EXCEL_FILE, index=False, engine="openpyxl")
            flash("Saved to Excel", "success")
        except Exception as e:
            log.exception("Excel save error")
            flash(f"Excel save error: {e}", "error")
    return redirect(url_for("search"))

# ---------------- List / download ----------------
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
            table = load_cache()
    else:
        table = load_cache()
    return safe_render("list.html", table=table)

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
    port = int(os.getenv("PORT", "5000"))
    debug_flag = True  # πάντα debug στο dev
    app.run(host="0.0.0.0", port=port, debug=debug_flag, use_reloader=True)
