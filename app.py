# app.py  (πλήρες, αντικατάστησε το παλιό app.py με αυτό)
import os
import sys
import json
import traceback
import logging
from logging.handlers import RotatingFileHandler
from typing import Any, Optional
import datetime
from datetime import datetime as _dt
from werkzeug.utils import secure_filename

from markupsafe import escape
from flask import Flask, render_template, request, redirect, url_for, send_file, flash, jsonify

import requests
import pandas as pd
import re

# local mydata helper (your fetch.py)
from fetch import request_docs

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

DATA_DIR = os.path.join(BASE_DIR, "data")
UPLOADS_DIR = os.path.join(BASE_DIR, "uploads")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(UPLOADS_DIR, exist_ok=True)
os.makedirs(TEMPLATES_DIR, exist_ok=True)

CACHE_FILE = os.path.join(DATA_DIR, "invoices_cache.json")
CREDENTIALS_FILE = os.path.join(DATA_DIR, "credentials.json")
EXCEL_FILE = os.path.join(UPLOADS_DIR, "invoices.xlsx")
SUMMARY_FILE = os.path.join(DATA_DIR, "summary.json")
ERROR_LOG = os.path.join(DATA_DIR, "error.log")

# ENV / defaults
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

# parse dd/mm/YYYY -> ISO; strict
def parse_ddmmyyyy_to_iso(s: str) -> Optional[str]:
    if not s:
        return None
    s = s.strip()
    try:
        dt = _dt.strptime(s, "%d/%m/%Y")
        return dt.date().isoformat()
    except Exception:
        return None

# euro parsing helpers (for display/aggregation)
def parse_euro_to_float(s):
    try:
        if s is None:
            return 0.0
        t = str(s).strip()
        if t == "":
            return 0.0
        t = re.sub(r"[^\d\-,\.]", "", t)
        if "," in t and "." in t:
            if t.rfind(",") > t.rfind("."):
                t = t.replace(".", "").replace(",", ".")
            else:
                t = t.replace(",", "")
        elif "," in t and "." not in t:
            t = t.replace(".", "").replace(",", ".")
        else:
            t = t.replace(",", "")
        return float(t)
    except Exception:
        try:
            return float(re.sub(r"[^\d\.]", "", str(s)))
        except Exception:
            return 0.0

def format_number_for_display(v):
    try:
        f = float(v)
        out = "{:,.2f}".format(f)  # "1,234.56"
        out = out.replace(",", "X").replace(".", ",").replace("X", ".")
        return out
    except Exception:
        return str(v)

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
    return safe_render("base.html")

# credentials CRUD pages (kept minimal)
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
            creds = load_credentials()
            if any(c.get("name")==name for c in creds):
                flash("Credential with that name exists", "error")
            else:
                creds.append({"name": name, "user": user, "key": key, "env": env, "vat": vat})
                save_credentials(creds)
                flash("Saved", "success")
        return redirect(url_for("credentials"))
    creds = load_credentials()
    return safe_render("credentials_list.html", credentials=creds)

@app.route("/credentials/delete/<name>", methods=["POST"])
def credentials_delete(name):
    creds = load_credentials()
    new = [c for c in creds if c.get("name") != name]
    save_credentials(new)
    flash("Deleted", "success")
    return redirect(url_for("credentials"))

# ---------------- Fetch (single) ----------------
@app.route("/fetch", methods=["GET", "POST"])
def fetch():
    message = None
    error = None
    creds = load_credentials()
    preview = load_cache()[:40]
    default_vat = ""

    if request.method == "POST":
        date_from_raw = request.form.get("date_from", "").strip()
        date_to_raw = request.form.get("date_to", "").strip()

        # server-side strict validation dd/mm/YYYY
        d1_iso = parse_ddmmyyyy_to_iso(date_from_raw)
        d2_iso = parse_ddmmyyyy_to_iso(date_to_raw)
        if not d1_iso or not d2_iso:
            error = "Παρακαλώ συμπλήρωσε έγκυρες από-έως ημερομηνίες (dd/mm/YYYY)."
            return safe_render("fetch.html", credentials=creds, message=message, error=error, preview=preview, default_vat=default_vat)

        # selected credential
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
            return safe_render("fetch.html", credentials=creds, message=message, error=error, preview=preview, default_vat=default_vat)

        # call request_docs -> d1,d2 in dd/mm/YYYY as fetch.request expects
        try:
            d1 = date_from_raw
            d2 = date_to_raw
            all_rows, summary_list = request_docs(
                date_from=d1,
                date_to=d2,
                mark="000000000000000",
                aade_user=aade_user,
                aade_key=aade_key,
                debug=False,
                save_excel=False
            )

            # save summary_list to SUMMARY_FILE
            try:
                if summary_list is not None:
                    json_write(SUMMARY_FILE, summary_list)
            except Exception:
                log.exception("Could not save summary_list to %s", SUMMARY_FILE)

            added = 0
            for d in all_rows:
                if append_doc_to_cache(d, aade_user, aade_key):
                    added += 1

            message = f"Fetched {len(all_rows)} items, newly cached: {added}"
            preview = load_cache()[:40]
        except Exception as e:
            log.exception("Fetch error")
            error = f"Σφάλμα λήψης: {str(e)[:400]}"

    return safe_render("fetch.html", credentials=creds, message=message, error=error, preview=preview, default_vat=default_vat)

# ---------------- Bulk fetch (runs via form; similar to fetch but different UI)
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

        aade_user = AADE_USER_ENV
        aade_key = AADE_KEY_ENV
        vat = vat_input
        if user:
            c = next((x for x in creds if x.get("name") == user), None)
            if c:
                aade_user = c.get("user") or aade_user
                aade_key = c.get("key") or aade_key
                vat = vat or c.get("vat", "")

        date_from_raw = request.form.get("date_from", "").strip()
        date_to_raw = request.form.get("date_to", "").strip()

        d_from_iso = parse_ddmmyyyy_to_iso(date_from_raw)
        d_to_iso = parse_ddmmyyyy_to_iso(date_to_raw)

        if not d_from_iso or not d_to_iso:
            error = "Παρακαλώ συμπλήρωσε έγκυρες ημερομηνίες (dd/mm/YYYY)."
            return safe_render("bulk_fetch.html", credentials=creds, message=message, error=error, preview=preview, default_vat=default_vat)

        try:
            all_rows, summary_list = request_docs(
                date_from=date_from_raw,
                date_to=date_to_raw,
                mark="000000000000000",
                aade_user=aade_user,
                aade_key=aade_key,
                debug=False,
                save_excel=False
            )

            # save summary_list
            try:
                if summary_list is not None:
                    json_write(SUMMARY_FILE, summary_list)
            except Exception:
                log.exception("Could not save summary_list to %s", SUMMARY_FILE)

            added = 0
            for d in all_rows:
                if append_doc_to_cache(d, aade_user, aade_key):
                    added += 1

            message = f"Fetched {len(all_rows)} items, newly cached: {added}"
            preview = load_cache()[:40]
        except Exception as e:
            log.exception("Bulk fetch error")
            error = f"Σφάλμα λήψης: {str(e)[:400]}"

    return safe_render("bulk_fetch.html", credentials=creds, message=message, error=error, preview=preview, default_vat=default_vat)

# ---------------- Search MARK (popup summary)
@app.route("/search", methods=["GET", "POST"])
def search():
    result = None
    error = None
    mark = ""
    summary_for_mark = None
    if request.method == "POST":
        mark = request.form.get("mark", "").strip()
        if not mark or not mark.isdigit() or len(mark) != 15:
            error = "Πρέπει να δώσεις έγκυρο 15ψήφιο MARK."
        else:
            # try cache
            doc = next((d for d in load_cache() if (isinstance(d, dict) and d.get("mark")==mark)), None)
            if not doc:
                error = f"MARK {mark} όχι στην cache. Κάνε πρώτα Bulk Fetch."
            else:
                result = doc
                # try load summary.json and pick first summary matching mark (if any)
                try:
                    sums = json_read(SUMMARY_FILE)
                    if isinstance(sums, list):
                        # summary entries may have mark field or key 'mark' or 'mark' inside structure
                        for s in sums:
                            s_mark = None
                            if isinstance(s, dict):
                                s_mark = s.get("mark") or s.get("MARK") or s.get("invoiceMark")
                                # also search nested
                                if not s_mark:
                                    for v in s.values():
                                        if isinstance(v, str) and v.strip()==mark:
                                            s_mark = mark
                                            break
                            if s_mark and str(s_mark).strip()==mark:
                                summary_for_mark = s
                                break
                        # fallback: if no explicit mark, but only one summary present and not empty, show it
                        if not summary_for_mark and len(sums)==1:
                            summary_for_mark = sums[0]
                except Exception:
                    log.exception("Failed to read summary file")

    return safe_render("search.html", result=result, error=error, mark=mark, summary=summary_for_mark)

# ---------------- Save summary to Excel (from modal save)
@app.route("/save_summary", methods=["POST"])
def save_summary():
    """
    Expects JSON-like form field 'summary_json' with a summary dict and optional vat_categories.
    We'll append rows to EXCEL_FILE similar to your previous logic (one row per VAT category if needed).
    """
    try:
        raw = request.form.get("summary_json")
        if not raw:
            flash("No summary provided", "error")
            return redirect(url_for("search"))
        summary = json.loads(raw)
        vat_cats = summary.get("vat_categories") if isinstance(summary, dict) else None

        # Build rows (reuse the logic from earlier program)
        rows_to_add = []
        def get_safe(d,k):
            return (d.get(k) or d.get(k.lower()) or "") if isinstance(d, dict) else ""

        if vat_cats and any(str(vc.get("category"))!="1" for vc in vat_cats):
            for vc in vat_cats:
                row = {
                    "MARK": str(summary.get("MARK") or summary.get("mark") or ""),
                    "ΑΦΜ": get_safe(summary.get("Εκδότης", {}), "ΑΦΜ"),
                    "Επωνυμία": get_safe(summary.get("Εκδότης", {}), "Επωνυμία"),
                    "Σειρά": get_safe(summary.get("Στοιχεία Παραστατικού", {}), "Σειρά"),
                    "Αριθμός": get_safe(summary.get("Στοιχεία Παραστατικού", {}), "Αριθμός"),
                    "Ημερομηνία": get_safe(summary.get("Στοιχεία Παραστατικού", {}), "Ημερομηνία"),
                    "Είδος": get_safe(summary.get("Στοιχεία Παραστατικού", {}), "Είδος"),
                    "ΦΠΑ_ΚΑΤΗΓΟΡΙΑ": str(vc.get("category") or ""),
                    "Καθαρή Αξία": vc.get("net", 0.0),
                    "ΦΠΑ": vc.get("vat", 0.0),
                    "Σύνολο": vc.get("gross", 0.0)
                }
                rows_to_add.append(row)
        else:
            row = {
                "MARK": str(summary.get("MARK") or summary.get("mark") or ""),
                "ΑΦΜ": get_safe(summary.get("Εκδότης", {}), "ΑΦΜ"),
                "Επωνυμία": get_safe(summary.get("Εκδότης", {}), "Επωνυμία"),
                "Σειρά": get_safe(summary.get("Στοιχεία Παραστατικού", {}), "Σειρά"),
                "Αριθμός": get_safe(summary.get("Στοιχεία Παραστατικού", {}), "Αριθμός"),
                "Ημερομηνία": get_safe(summary.get("Στοιχεία Παραστατικού", {}), "Ημερομηνία"),
                "Είδος": get_safe(summary.get("Στοιχεία Παραστατικού", {}), "Είδος"),
                "ΦΠΑ_ΚΑΤΗΓΟΡΙΑ": "",
                "Καθαρή Αξία": summary.get("Σύνολα", {}).get("Καθαρή Αξία") or "",
                "ΦΠΑ": summary.get("Σύνολα", {}).get("ΦΠΑ") or "",
                "Σύνολο": summary.get("Σύνολα", {}).get("Σύνολο") or ""
            }
            rows_to_add.append(row)

        df_new = pd.DataFrame(rows_to_add)
        # format numeric columns
        for col in ("Καθαρή Αξία","ΦΠΑ","Σύνολο"):
            if col in df_new.columns:
                df_new[col] = df_new[col].apply(lambda v: format_number_for_display(v) if v not in (None,"") else "")

        # append to EXCEL_FILE with duplicate handling: if MARK present and exact duplicate skip
        if os.path.exists(EXCEL_FILE):
            try:
                df_existing = pd.read_excel(EXCEL_FILE, engine="openpyxl", dtype=str).fillna("")
                # simple duplicate check: if single-row and MARK present, skip
                if len(df_new)==1 and "MARK" in df_existing.columns:
                    if str(df_new.at[0,"MARK"]).strip() in df_existing["MARK"].astype(str).str.strip().tolist():
                        flash("Already present (duplicate).", "warning")
                        return redirect(url_for("list_invoices"))
                df_concat = pd.concat([df_existing, df_new], ignore_index=True, sort=False)
                df_concat.to_excel(EXCEL_FILE, index=False, engine="openpyxl")
            except Exception:
                # fallback: create new
                df_new.to_excel(EXCEL_FILE, index=False, engine="openpyxl")
        else:
            df_new.to_excel(EXCEL_FILE, index=False, engine="openpyxl")

        flash("Saved to Excel", "success")
    except Exception as e:
        log.exception("save_summary error")
        flash(f"Save error: {e}", "error")
    return redirect(url_for("list_invoices"))

# ---------------- List / DataTables using pandas ----------------
@app.route("/list")
def list_invoices():
    # render a template that includes the HTML table generated by pandas
    file_exists = os.path.exists(EXCEL_FILE)
    table_html = ""
    error = ""
    try:
        if file_exists:
            df = pd.read_excel(EXCEL_FILE, engine="openpyxl", dtype=str).fillna("")
        else:
            # fallback to cache list-of-dicts; convert to df for HTML
            cache = load_cache()
            if cache and isinstance(cache, list):
                df = pd.DataFrame(cache)
            else:
                df = pd.DataFrame()
        if not df.empty:
            # ensure MARK column exists as first column (if present)
            cols = list(df.columns)
            if "MARK" in cols:
                cols.remove("MARK")
                cols = ["MARK"] + cols
                df = df[cols]
            # Insert checkbox column html (first col)
            if "MARK" in df.columns:
                checkboxes = df["MARK"].apply(lambda v: f'<input type="checkbox" class="row-select" value="{escape(str(v))}">')
                df.insert(0, "✓", checkboxes)
            # convert certain numeric headers to right aligned (we'll add CSS)
            table_html = df.to_html(classes="pandas-table table table-sm", index=False, escape=False)
    except Exception as e:
        log.exception("list_invoices error")
        error = f"Could not read invoices: {e}"

    return safe_render("list_pandas.html", table_html=table_html, file_exists=file_exists, error=error)

# ---------------- API for DataTables-like interaction ----------------
@app.route("/api/invoices", methods=["GET"])
def api_invoices():
    try:
        if os.path.exists(EXCEL_FILE):
            df = pd.read_excel(EXCEL_FILE, engine="openpyxl", dtype=str).fillna("")
        else:
            cache = load_cache()
            df = pd.DataFrame(cache)
        if df.empty:
            return jsonify([])

        if "MARK" in df.columns:
            possible_num_cols = ["Καθαρή Αξία", "ΦΠΑ", "Σύνολο", "Total", "Net", "VAT"]
            numeric_cols = [c for c in df.columns if c in possible_num_cols]
            agg_dict = {}
            for c in numeric_cols:
                agg_dict[c] = lambda s, c=c: sum(parse_euro_to_float(v) for v in s)
            for c in df.columns:
                if c not in numeric_cols and c != "MARK":
                    agg_dict[c] = "first"
            df_summary = df.groupby("MARK", as_index=False).agg(agg_dict)
            for c in numeric_cols:
                if c in df_summary.columns:
                    df_summary[c] = df_summary[c].apply(format_number_for_display)
            records = df_summary.to_dict(orient="records")
            return jsonify(records)
        else:
            return jsonify(df.to_dict(orient="records"))
    except Exception as e:
        log.exception("api_invoices error")
        return jsonify({"error": str(e)}), 500

# ---------------- Delete AJAX (deletes by MARKs) ----------------
@app.route("/delete_ajax", methods=["POST"])
def delete_ajax():
    try:
        payload = request.get_json(force=True, silent=True) or {}
        marks = payload.get("marks") or []
        if not marks:
            return jsonify({"deleted": 0})
        if not os.path.exists(EXCEL_FILE):
            return jsonify({"deleted": 0})
        df = pd.read_excel(EXCEL_FILE, engine="openpyxl", dtype=str).fillna("")
        if "MARK" not in df.columns:
            return jsonify({"deleted": 0})
        before = len(df)
        df_filtered = df[~df["MARK"].astype(str).isin([str(m).strip() for m in marks])]
        after = len(df_filtered)
        deleted = before - after
        if deleted > 0:
            df_filtered.to_excel(EXCEL_FILE, index=False, engine="openpyxl")
        # update cache as well
        try:
            cache = load_cache()
            new_cache = [d for d in cache if not (isinstance(d, dict) and d.get("mark") in marks)]
            if len(new_cache) != len(cache):
                save_cache(new_cache)
        except Exception:
            log.exception("delete_ajax: cache update failed")
        return jsonify({"deleted": deleted})
    except Exception as e:
        log.exception("delete_ajax failed")
        return jsonify({"error": str(e)}), 500

# Health / favicon
@app.route("/health")
def health():
    return "OK"

@app.route('/favicon.ico')
def favicon():
    return '', 204

# Global error handler
@app.errorhandler(Exception)
def handle_unexpected_error(e):
    tb = traceback.format_exc()
    log.error("Unhandled exception: %s\n%s", str(e), tb)
    debug = os.getenv("FLASK_DEBUG", "0") == "1"
    if debug:
        return "<pre>{}</pre>".format(escape(tb)), 500
    return safe_render("error_generic.html", message="Συνέβη σφάλμα στον server. Δες logs."), 500

@app.route("/download_excel")
def download_excel():
    # use the same EXCEL_FILE variable you have defined at top of app.py
    if not os.path.exists(EXCEL_FILE):
        # επιστρέφουμε 404 με φιλικό μήνυμα
        return ("Το αρχείο invoices.xlsx δεν βρέθηκε.", 404)
    # send_file με download_name (Flask >= 2.2). Αν έχεις παλαιότερη Flask, δοκίμασε attachment_filename
    try:
        return send_file(
            EXCEL_FILE,
            as_attachment=True,
            download_name="invoices.xlsx",
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    except TypeError:
        # fallback για παλαιότερες Flask εκδόσεις που δεν καταλαβαίνουν download_name
        return send_file(
            EXCEL_FILE,
            as_attachment=True,
            attachment_filename="invoices.xlsx",
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    debug_flag = True
    app.run(host="0.0.0.0", port=port, debug=debug_flag, use_reloader=True)
