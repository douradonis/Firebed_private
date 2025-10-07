# app.py (ολοκληρωμένο, με ενσωματωμένη λογική για per-line categorization -> epsilon per-vat files)
import os
import sys
import json
import traceback
import logging
from logging.handlers import RotatingFileHandler
import datetime
from typing import Any, List, Dict, Optional
from datetime import datetime as _dt
from werkzeug.utils import secure_filename
from datetime import timezone
from markupsafe import escape, Markup
from flask import Flask, render_template, request, redirect, url_for, send_file, flash, jsonify, session
import tempfile
from scraper import scrape_wedoconnect, scrape_mydatapi, scrape_einvoice, scrape_impact, scrape_epsilon
import re
import requests
import pandas as pd
from shutil import move
import importlib

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
ALLOWED_CLIENT_EXT = {'.xlsx', '.xls', '.csv'}



app = Flask(__name__, template_folder=TEMPLATES_DIR)
app.secret_key = os.getenv("FLASK_SECRET", "change-me")
app.config["UPLOAD_FOLDER"] = UPLOADS_DIR
FISCAL_META = 'fiscal.meta.json'   # αποθηκεύεται μέσα στο DATA_DIR



@app.before_request
def log_request_path():
    log.info("Incoming request: method=%s path=%s remote=%s ref=%s", request.method, request.path, request.remote_addr, request.referrer)
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
GLOBAL_ACCOUNTS_NAME = "__global_accounts__"
# keep settings inside data/ so it's co-located with other app files
SETTINGS_FILE = os.path.join(DATA_DIR, "credentials_settings.json")
VAT_MAP = {
    "1": "ΦΠΑ 24%",
    "2": "ΦΠΑ 13%",
    "3": "ΦΠΑ 6%",
    "4": "ΦΠΑ 17%",
    "5": "ΦΠΑ 9%",
    "6": "ΦΠΑ 4%",
    "7": "Εξαιρούμενο άρθρο 39α",
    "8": "Εξαιρούμενο άρθρο 47β",
    "9": "Άνευ ΦΠΑ",
}
def create_empty_excel_for_vat(vat, fiscal_year=None):
    """
    Ensure an empty excel file exists for the given VAT and fiscal_year.
    Filename: <safe_vat>_<fiscal_year>_invoices.xlsx, placed under DATA_DIR/excel (created if missing).
    Returns the path created (or existing).
    """
    try:
        safe_vat = secure_filename(str(vat))
    except Exception:
        safe_vat = str(vat)

    # try to resolve fiscal_year from existing function if available, else current year
    if fiscal_year is None:
        getter = globals().get("get_active_fiscal_year")
        try:
            if callable(getter):
                fiscal_year = getter()
        except Exception:
            fiscal_year = None
    if fiscal_year is None:
        from datetime import datetime
        fiscal_year = datetime.now().year

    # prefer an "excel" subdir inside DATA_DIR (keeps things tidy)
    excel_dir = os.path.join(DATA_DIR, "excel")
    os.makedirs(excel_dir, exist_ok=True)

    excel_fname = f"{safe_vat}_{fiscal_year}_invoices.xlsx"
    excel_path = os.path.join(excel_dir, excel_fname)

    if os.path.exists(excel_path):
        log.debug("create_empty_excel_for_vat: excel already exists: %s", excel_path)
        return excel_path

    # create an empty dataframe with the columns your app expects
    try:
        import pandas as pd
    except Exception:
        log.exception("create_empty_excel_for_vat: pandas not available")
        raise

    cols = [
        "MARK",
        "ΑΦΜ",
        "Επωνυμία",
        "Σειρά",
        "Αριθμός",
        "Ημερομηνία",
        "Είδος",
        "ΦΠΑ_ΚΑΤΗΓΟΡΙΑ",
        "Καθαρή Αξία",
        "ΦΠΑ",
        "Σύνολο"
    ]
    df = pd.DataFrame(columns=cols).astype(str)

    try:
        df.to_excel(excel_path, index=False, engine="openpyxl")
        log.info("create_empty_excel_for_vat: created empty excel %s", excel_path)
    except Exception:
        log.exception("create_empty_excel_for_vat: failed creating excel %s", excel_path)
        raise

    return excel_path





import re
def _fiscal_meta_path():
    """Return path to fiscal meta file inside DATA_DIR."""
    return os.path.join(DATA_DIR, "fiscal_meta.json")
def epsilon_item_has_detail(item):
    """
    True αν το item φαίνεται 'πραγματικό' (περιέχει αρκετά πεδία).
    False αν είναι placeholder (π.χ. μόνο mark/AFM/AA + empty lines).
    Κανόνες:
      - issueDate OR
      - lines με πραγματικά πεδία (description/amount/vat) OR
      - totalNetValue/totalValue OR
      - AFM_issuer + (AA ή issueDate ή totalValue)
    """
    try:
        if not item or not isinstance(item, dict):
            return False
        if item.get("issueDate"):
            return True
        if item.get("totalNetValue") or item.get("totalValue"):
            return True
        lines = item.get("lines") or []
        if isinstance(lines, list):
            for l in lines:
                if l and (l.get("description") or l.get("amount") or l.get("vat")):
                    return True
        # AFM_issuer alone is not enough; require some other info
        if item.get("AFM_issuer") or item.get("AFM"):
            if item.get("aa") or item.get("AA") or item.get("issueDate") or item.get("totalValue"):
                return True
    except Exception:
        pass
    return False



# --- Ensure _safe_save_epsilon_cache exists (put this near top of app.py, after imports) ---
def _safe_save_epsilon_cache(vat_code, epsilon_list):
    """
    Compatible safe writer used across the app.
    Returns the path of the saved file on success.
    Raises on failure.
    """
    epsilon_dir = os.path.join(DATA_DIR, "epsilon")
    os.makedirs(epsilon_dir, exist_ok=True)
    safe_vat = secure_filename(str(vat_code))
    epsilon_path = os.path.join(epsilon_dir, f"{safe_vat}_epsilon_invoices.json")

    # coerce to list
    if epsilon_list is None:
        epsilon_list = []
    if not isinstance(epsilon_list, list):
        if isinstance(epsilon_list, dict):
            epsilon_list = [epsilon_list]
        else:
            try:
                epsilon_list = list(epsilon_list)
            except Exception:
                epsilon_list = [epsilon_list]

    # quick sanity: avoid overwriting with mostly-placeholders if file exists
    incomplete = 0
    try:
        for it in epsilon_list:
            if not (it and (it.get("lines") or it.get("issueDate") or it.get("AFM_issuer") or it.get("AFM"))):
                incomplete += 1
    except Exception:
        incomplete = 0

    try:
        if len(epsilon_list) > 0 and incomplete >= max(1, int(len(epsilon_list) * 0.9)):
            if os.path.exists(epsilon_path):
                log.warning("_safe_save_epsilon_cache: skipping overwrite (looks like placeholders) %s", epsilon_path)
                return epsilon_path
    except Exception:
        pass

    # Try to use json_write if defined; otherwise do atomic tmp write here
    try:
        # prefer json_write helper if present
        if 'json_write' in globals() and callable(globals().get('json_write')):
            json_write(epsilon_path, epsilon_list)
            try:
                log.info("_safe_save_epsilon_cache: saved epsilon to %s", epsilon_path)
            except Exception:
                pass
            return epsilon_path
    except Exception:
        log.exception("_safe_save_epsilon_cache: json_write failed, falling back to direct atomic write")

    # fallback atomic write
    tmp = None
    try:
        text = json.dumps(epsilon_list, ensure_ascii=False, indent=2)
        fd, tmp = tempfile.mkstemp(prefix=".tmp_epsilon_", dir=epsilon_dir)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            try:
                os.fsync(fh.fileno())
            except Exception:
                pass
        os.replace(tmp, epsilon_path)
        try:
            log.info("_safe_save_epsilon_cache: saved epsilon (fallback) to %s", epsilon_path)
        except Exception:
            pass
        return epsilon_path
    except Exception:
        try:
            log.exception("_safe_save_epsilon_cache: fallback write failed")
        except Exception:
            print("fallback write failed for", epsilon_path)
        # cleanup tmp
        try:
            if tmp and os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass
        raise
# --- end _safe_save_epsilon_cache ---




def get_active_fiscal_year():
    """
    Read persisted fiscal year (int) from DATA_DIR/fiscal_meta.json.
    Returns integer fiscal year or None if not found / on error.
    """
    try:
        p = _fiscal_meta_path()
        if not os.path.exists(p):
            return None
        with open(p, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not data:
            return None
        fy = data.get("fiscal_year")
        if fy is None:
            return None
        try:
            return int(fy)
        except Exception:
            # stored value not an int
            return None
    except Exception:
        try:
            log.exception("get_active_fiscal_year: failed to read fiscal meta")
        except Exception:
            pass
        return None


def set_active_fiscal_year(year):
    """Persist fiscal year (int). Returns True on success, False on failure."""
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        p = _fiscal_meta_path()
        with open(p, "w", encoding="utf-8") as fh:
            json.dump({"fiscal_year": int(year)}, fh)
        try:
            log.info("Set active fiscal year: %s", year)
        except Exception:
            pass
        return True
    except Exception:
        try:
            log.exception("Failed to write fiscal meta")
        except Exception:
            pass
        return False
# ---------------- normalize helper (paste/replace existing) ----------------
def _normalize_afm(raw):
    """Καθαρίζει AFM: κρατά μόνο digits, κόβει περιττά και επιστρέφει None αν άδειο."""
    if not raw:
        return None
    s = str(raw).strip()
    # extract digits
    digits = re.sub(r'\D', '', s)
    if not digits:
        return None
    # common AFM length = 9, but αν έχει περισσότερα κρατάμε τα *πρώτα* 9 (αν αυτό θέλεις)
    if len(digits) > 9:
        digits = digits[-9:]  # καλύτερο να πάρουμε τα **τελευταία 9** (συχνά οι σελίδες έχουν πρόσθετα prefix)
    return digits
# --- νέο helper: update or append a summary row into excel ---
def _normalize_summary_row_for_excel(summary):
    """Return dict with keys aligned to DEFAULT EXCEL columns used in your app."""
    return {
        "MARK": str(summary.get("mark","") or ""),
        "AA": str(summary.get("AA","") or ""),
        "AFM": str(summary.get("AFM","") or ""),
        "Name": str(summary.get("Name","") or ""),
        "issueDate": str(summary.get("issueDate","") or ""),
        "totalValue": str(summary.get("totalValue","") or ""),
        "category": str(summary.get("category","") or ""),
        "note": str(summary.get("note","") or ""),
        "created_at": str(summary.get("created_at","") or ""),
    }

def _ensure_excel_and_update_or_append(summary: dict, vat: Optional[str] = None, cred_name: Optional[str] = None):
    """
    Ensure an excel exists (create if missing) and either update existing row matching mark or append new row.
    Uses pandas to load/edit/save — simpler and reliable for small files.
    """
    path = excel_path_for(cred_name=cred_name, vat=vat)
    # headers consistent with DEFAULT_EXCEL_FILE usage above
    headers = ["MARK","AA","AFM","Name","issueDate","totalValue","category","note","created_at"]

    # create file if missing with headers
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        df = pd.DataFrame(columns=headers)
        df.to_excel(path, index=False)
    # load existing
    try:
        df = pd.read_excel(path, dtype=str)
    except Exception:
        # fallback: make empty DF with headers
        df = pd.DataFrame(columns=headers)

    # normalize types: ensure all header cols exist
    for h in headers:
        if h not in df.columns:
            df[h] = ""

    row = _normalize_summary_row_for_excel(summary)
    mark_val = str(row.get("MARK","")).strip()

    # try to find existing row by mark (use _match_row_by_mark logic)
    found = False
    if mark_val:
        # use vectorized comparison across likely colnames
        mask = pd.Series([False]*len(df), index=df.index)
        # prefer 'MARK' column, else try any object/string column
        if "MARK" in df.columns:
            try:
                mask = df["MARK"].fillna("").astype(str).str.strip() == mark_val
            except Exception:
                mask = (df["MARK"].fillna("") == mark_val)
        if not mask.any():
            # scan other string columns
            for c in df.columns:
                try:
                    if df[c].dtype == 'O' or df[c].dtype == 'string':
                        m2 = df[c].fillna("").astype(str).str.strip() == mark_val
                        if m2.any():
                            mask = m2
                            break
                except Exception:
                    continue

        if mask.any():
            # update first match
            idx = mask[mask].index[0]
            for h in headers:
                # don't overwrite MARK,AA if blank in new row? We'll overwrite with new data
                df.at[idx, h] = row.get(h,"")
            found = True

    if not found:
        # append new row
        df = df.append(row, ignore_index=True)

    # ensure AFM and MARK are saved as text in Excel: pandas will save as strings; that's OK
    try:
        df.to_excel(path, index=False)
    except Exception:
        # final fallback - try openpyxl write: create workbook with headers then append row
        try:
            from openpyxl import Workbook, load_workbook
            if not os.path.exists(path):
                wb = Workbook()
                ws = wb.active
                ws.append(headers)
                wb.save(path)
            wb = load_workbook(path)
            ws = wb.active
            # if updated, easier to rewrite entire excel from df
            for r in dataframe_to_rows(df, index=False, header=True):
                pass
            # simpler: use pandas to_excel in a temp file and replace
            tmp = path + ".tmp.xlsx"
            df.to_excel(tmp, index=False)
            os.replace(tmp, path)
        except Exception:
            log.exception("Failed to write excel for summary for mark=%s", mark_val)

def _normalize_receipt_summary(summary: dict) -> dict:
    s = dict(summary or {})
    out = {}
    out['MARK'] = (s.get('MARK') or s.get('mark') or '').strip()
    out['AA'] = (s.get('AA') or s.get('progressive_aa') or s.get('id') or '').strip()
    # prefer issuer_vat, but normalize to AFM field (9 digits)
    raw_vat = (s.get('issuer_vat') or s.get('AFM') or s.get('vat') or s.get('issuerVat') or '')
    out['AFM'] = _normalize_afm(raw_vat) or ''
    out['issuer_vat_raw'] = (raw_vat or '').strip()
    out['Name'] = (s.get('issuer_name') or s.get('Name') or s.get('company') or '').strip()
    # date normalization: keep raw (you may reformat if you want)
    out['issueDate'] = (s.get('issue_date') or s.get('issueDate') or s.get('date') or '').strip()
    # total amount normalization: reuse your existing _clean_amount_to_comma if present
    total = s.get('total_amount') or s.get('totalValue') or s.get('total') or ''
    try:
        # try to keep same formatting used in invoices (comma decimal)
        out['totalValue'] = _clean_amount_to_comma(total) or str(total)
    except Exception:
        out['totalValue'] = str(total)
    out['type_name'] = (s.get('type_name') or s.get('doc_type') or 'Απόδειξη').strip()
    out['lines'] = s.get('lines') or []
    out['_saved_at'] = datetime.utcnow().isoformat() + 'Z'
    # keep category if any line already had it
    out['category'] = ''
    for ln in out['lines']:
        if isinstance(ln, dict) and ln.get('category'):
            out['category'] = ln.get('category')
            break
    return out


def _normalize_key_val(x):
    try:
        if x is None:
            return ""
        # convert numbers to str, strip whitespace, lower-case for robust comparison
        return str(x).strip()
    except Exception:
        return ""

def _find_afm_in_epsilon(mark: str = None, aa: str = None) -> str:
    """
    Search data/epsilon/*.json for an invoice matching mark or AA.
    Return AFM_issuer or AFM if found, else empty string.
    """
    try:
        epsilon_dir = os.path.join(DATA_DIR, "epsilon")
        if not os.path.isdir(epsilon_dir):
            return ""
        for fname in os.listdir(epsilon_dir):
            if not fname.endswith("_epsilon_invoices.json"):
                continue
            try:
                path = os.path.join(epsilon_dir, fname)
                with open(path, "r", encoding="utf-8") as fh:
                    items = json.load(fh)
                if not isinstance(items, list):
                    continue
                for it in items:
                    try:
                        if mark and str(it.get("mark", "")).strip() and str(it.get("mark", "")).strip() == str(mark).strip():
                            return (it.get("AFM_issuer") or it.get("AFM") or "").strip()
                        if aa and str(it.get("AA", "")).strip() and str(it.get("AA", "")).strip() == str(aa).strip():
                            return (it.get("AFM_issuer") or it.get("AFM") or "").strip()
                    except Exception:
                        continue
            except Exception:
                # ignore corrupt epsilon files
                continue
    except Exception:
        try:
            log.exception("_find_afm_in_epsilon failed")
        except Exception:
            pass
    return ""



def _append_to_excel(rec_dict, vat: Optional[str] = None, cred_name: Optional[str] = None):
    """
    Append a single record as a row to the per-vat Excel file determined by excel_path_for().
    Uses AFM from rec_dict first, otherwise looks into epsilon cache (by mark / AA).
    """
    # determine vat to use for per-vat excel filename (fallbacks)
    vat_candidate = vat or rec_dict.get('issuer_vat') or rec_dict.get('issuer_vat_raw') or rec_dict.get('AFM') or ""
    safe_vat = secure_filename(str(vat_candidate)) if vat_candidate else ""
    path = excel_path_for(cred_name=cred_name, vat=safe_vat)

    # ensure directory exists
    os.makedirs(os.path.dirname(path), exist_ok=True)

    # Try to resolve AFM: prefer explicit issuer fields, else search epsilon cache by mark/AA
    afm = (
        (rec_dict.get('issuer_vat') or rec_dict.get('AFM_issuer') or rec_dict.get('AFM') or rec_dict.get('issuer_vat_raw') or "")
        .strip()
    )
    if not afm:
        # attempt to find AFM in epsilon cache using mark / AA
        mark = rec_dict.get("MARK") or rec_dict.get("mark") or rec_dict.get("mark_id") or ""
        aa = rec_dict.get("AA") or rec_dict.get("aa") or rec_dict.get("invoice_number") or ""
        found = _find_afm_in_epsilon(mark=mark, aa=aa)
        if found:
            afm = found.strip()

    # build row (add/adjust fields as your app expects)
    row = {
        'saved_at': rec_dict.get('_saved_at'),
        'MARK': rec_dict.get('MARK') or rec_dict.get('mark'),
        'AA': rec_dict.get('AA') or rec_dict.get('aa'),
        'AFM': afm,
        'Name': rec_dict.get('Name') or rec_dict.get('Name_issuer') or rec_dict.get('Name_counterparty') or "",
        'issueDate': rec_dict.get('issueDate') or rec_dict.get('issueDate_raw') or rec_dict.get('issue_date') or "",
        'totalValue': rec_dict.get('totalValue') or rec_dict.get('total_value') or rec_dict.get('total') or "",
        'category': rec_dict.get('category') or rec_dict.get('classification') or ""
    }

    headers = list(row.keys())

    # debug log
    try:
        log.info("append_to_excel -> path=%s vat_candidate=%s resolved_afm=%s mark=%s AA=%s",
                 path, safe_vat, row['AFM'], row.get('MARK'), row.get('AA'))
    except Exception:
        pass

    # Try pandas path first (preferred)
    try:
        import pandas as pd
        if os.path.exists(path):
            df_existing = pd.read_excel(path, engine='openpyxl', dtype=str)
        else:
            df_existing = pd.DataFrame(columns=headers)

        df_new = pd.DataFrame([row])
        df_concat = pd.concat([df_existing, df_new], ignore_index=True, sort=False)

        # Ensure all headers exist (order)
        for h in headers:
            if h not in df_concat.columns:
                df_concat[h] = ""

        df_concat.to_excel(path, index=False, engine='openpyxl')
        return True

    except Exception as e_pandas:
        # Fallback to openpyxl direct append/create
        try:
            from openpyxl import load_workbook, Workbook
            if not os.path.exists(path):
                wb = Workbook()
                ws = wb.active
                ws.append(headers)
                ws.append([row.get(k, '') for k in headers])
                wb.save(path)
                return True

            wb = load_workbook(path)
            ws = wb.active
            # ensure header row exists and matches headers; if not, add header if missing
            existing_headers = [cell.value for cell in next(ws.iter_rows(min_row=1, max_row=1))]
            if not existing_headers or all(h is None for h in existing_headers):
                # insert header then continue
                ws.insert_rows(1)
                for idx, h in enumerate(headers, start=1):
                    ws.cell(row=1, column=idx, value=h)
            ws.append([row.get(k, '') for k in headers])
            wb.save(path)
            return True

        except Exception as e_openpyxl:
            try:
                log.exception("append_to_excel failed (pandas err=%s, openpyxl err=%s)", e_pandas, e_openpyxl)
            except Exception:
                print("append_to_excel failed:", e_pandas, e_openpyxl)
            return False
    """
    Append a single record as a row to EXCEL_FILE.
    Columns: saved_at, MARK, AA, AFM, Name, issueDate, totalValue, category
    Uses pandas (openpyxl engine).
    """
    row = {
        'saved_at': rec_dict.get('_saved_at'),
        'MARK': rec_dict.get('MARK'),
        'AA': rec_dict.get('AA'),
        'AFM': rec_dict.get('AFM'),
        'Name': rec_dict.get('Name'),
        'issueDate': rec_dict.get('issueDate'),
        'totalValue': rec_dict.get('totalValue'),
        'category': rec_dict.get('category') or ''
    }
    try:
        if os.path.exists(EXCEL_FILE):
            df_existing = pd.read_excel(EXCEL_FILE, engine='openpyxl')
        else:
            df_existing = pd.DataFrame(columns=list(row.keys()))
        df_new = pd.DataFrame([row])
        df_concat = pd.concat([df_existing, df_new], ignore_index=True, sort=False)
        df_concat.to_excel(EXCEL_FILE, index=False, engine='openpyxl')
        return True
    except Exception as e:
        current_app.logger.exception("excel append failed: %s", e)
        return False


def set_active_fiscal_year(year):
    """Persist fiscal year (int)."""
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        p = _fiscal_meta_path()
        with open(p, 'w', encoding='utf-8') as fh:
            json.dump({'fiscal_year': int(year)}, fh)
        log.info("Set active fiscal year: %s", year)
        return True
    except Exception:
        log.exception("Failed to write fiscal meta")
        return False
def _client_meta_path():
    """Full path to metadata JSON for client_db inside DATA_DIR."""
    return os.path.join(DATA_DIR, 'client_db.meta.json')

def read_client_meta():
    """Read metadata if exists, return dict or None."""
    meta_path = _client_meta_path()
    try:
        if os.path.exists(meta_path):
            with open(meta_path, 'r', encoding='utf-8') as fh:
                return json.load(fh)
    except Exception:
        log.exception("Failed reading client_db.meta.json")
    return None

def write_client_meta(filename, uploaded_at_iso):
    """Write metadata (filename, uploaded_at iso) to meta file."""
    meta = {
        'filename': filename,
        'uploaded_at': uploaded_at_iso
    }
    meta_path = _client_meta_path()
    try:
        with open(meta_path, 'w', encoding='utf-8') as fh:
            json.dump(meta, fh, ensure_ascii=False, indent=2)
    except Exception:
        log.exception("Failed writing client_db.meta.json")

def normalize_vat_key(raw):
    """
    Normalize different vat-category representations into a canonical form like '24%','0%','6%','13%'
    Examples:
      'ΦΠΑ 24%' -> '24%'
      '24%' -> '24%'
      '24' -> '24%'
      'VAT 24%' -> '24%'
      '0%' -> '0%'
    Returns empty string for unknown/empty.
    """
    if raw is None:
        return ""
    s = str(raw).strip().lower()
    if not s:
        return ""
    # remove common words like 'φπα' or 'vat'
    s = re.sub(r'φπα|\bvat\b', '', s, flags=re.IGNORECASE).strip()
    # find a number (integer or decimal) optionally followed by %
    m = re.search(r'(\d+(?:[.,]\d+)?)\s*%?', s)
    if m:
        num = m.group(1).replace(',', '.')
        # if it's integer-like, keep integer
        if '.' in num:
            # keep as-is (rare), but normalize trailing .0
            try:
                f = float(num)
                if f.is_integer():
                    num = str(int(f))
                else:
                    # keep one or two decimals? keep as original trimmed
                    num = num.rstrip('0').rstrip('.') if '.' in num else num
            except:
                num = num
        # canonical form: without decimals if integer, with '%' suffix
        return f"{num}%"
    # if there is something else like 'μηδεν' -> map to 0%
    if re.search(r'0|μηδ', s):
        return "0%"
    return ""
def read_credentials_list():
    try:
        with open(CREDENTIALS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return []
    except Exception:
        log.exception("read_credentials_list failed")
        return []

def write_credentials_list(data_list):
    tmp = CREDENTIALS_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data_list, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CREDENTIALS_FILE)

def find_active_client_index(creds_list, vat=None):
    # priority: match vat, else find 'active': true, else first
    if vat:
        for i,c in enumerate(creds_list):
            if str(c.get('vat','')).strip() == str(vat).strip():
                return i
    for i,c in enumerate(creds_list):
        if c.get('active'):
            return i
    return 0 if creds_list else None

def load_invoices():
    if os.path.exists(INVOICES_FILE):
        with open(INVOICES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

# φορτώνουμε epsilon_invoices.json
def load_epsilon():
    if os.path.exists(EPSILON_FILE):
        with open(EPSILON_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []
def get_global_accounts_from_credentials() -> Dict:
    """
    Διαβάζει το credentials.json και επιστρέφει το αντικείμενο accounts
    αν υπάρχει ως credential με name == GLOBAL_ACCOUNTS_NAME.
    """
    creds = load_credentials()
    for c in creds:
        if c.get("name") == GLOBAL_ACCOUNTS_NAME:
            return c.get("accounts", {})
    return {}

def save_global_accounts_to_credentials(accounts: Dict) -> None:
    """
    Αποθηκεύει/ενημερώνει την εγγραφή GLOBAL_ACCOUNTS_NAME στο credentials.json
    με τα παρεχόμενα accounts mapping.
    """
    creds = load_credentials()
    found = False
    for i, c in enumerate(creds):
        if c.get("name") == GLOBAL_ACCOUNTS_NAME:
            creds[i]["accounts"] = accounts
            found = True
            break
    if not found:
        # προσθέτουμε ένα ειδικό credential αντικείμενο κρατώντας μόνο το accounts πεδίο
        creds.append({
            "name": GLOBAL_ACCOUNTS_NAME,
            "user": "",
            "key": "",
            "vat": "",
            "env": MYDATA_ENV,
            "accounts": accounts
        })
    save_credentials(creds)

# ---------------- Helpers ---------------- (most unchanged)
# -------------------------
# Robust JSON helpers
# -------------------------
def json_read(path, default=None):
    """
    Safe JSON read.
    - If file missing -> return default (default default: [] for lists, {} if you prefer)
    - If file empty/corrupt -> log and return default (do NOT raise).
    - Avoid recursive logging traps: use try/except carefully.
    """
    if default is None:
        default = []
    try:
        if not path or not os.path.exists(path):
            return default
        with open(path, "r", encoding="utf-8") as fh:
            txt = fh.read()
            if not txt or not txt.strip():
                return default
            # load
            return json.loads(txt)
    except Exception as e:
        # try a safe fallback: don't re-call json_read here (would recurse)
        try:
            log.error("json_read failed for %s: %s", path, str(e))
        except Exception:
            # if logging itself fails, fall back to print (rare)
            try:
                print("json_read failed for", path, str(e))
            except Exception:
                pass
        # return default to avoid crashing the app (caller should handle None/default)
        return default

def json_write(path, obj):
    """
    Atomic JSON write:
    - write to a tmp file, fsync, os.replace -> atomic replace
    - raises on failure so callers can handle/log
    """
    tmp = None
    try:
        dirp = os.path.dirname(path) or "."
        os.makedirs(dirp, exist_ok=True)
        text = json.dumps(obj, ensure_ascii=False, indent=2)
        # write to tmp file in same dir (for atomic replace)
        fd, tmp = tempfile.mkstemp(prefix=".tmp_json_", dir=dirp)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            try:
                os.fsync(fh.fileno())
            except Exception:
                # some file systems may not support fsync; ignore if fails
                pass
        # atomic replace
        os.replace(tmp, path)
        return True
    except Exception as e:
        try:
            log.exception("json_write failed for %s: %s", path, str(e))
        except Exception:
            print("json_write failed for", path, str(e))
        # cleanup tmp if present
        try:
            if tmp and os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass
        raise


def load_credentials():
    if os.path.exists(CREDENTIALS_FILE):
        with open(CREDENTIALS_FILE,'r',encoding='utf-8') as f:
            return json.load(f)
    return []

def save_credentials(credentials):
    with open(CREDENTIALS_FILE,'w',encoding='utf-8') as f:
        json.dump(credentials, f, ensure_ascii=False, indent=2)

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE,'r',encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_settings(settings):
    with open(SETTINGS_FILE,'w',encoding='utf-8') as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)

def get_active_credential():
    creds = load_credentials()
    for c in creds:
        if c.get('active'):
            return c
    return None

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
    Return the best path for the excel summary for a client.
    Prefers file with fiscal year: <vat>_<fiscal_year>_invoices.xlsx, then <vat>_invoices.xlsx, then DEFAULT_EXCEL_FILE.
    """
    try:
        safe_vat = secure_filename(str(vat)) if vat else None
    except Exception:
        safe_vat = str(vat) if vat else None

    # determine fiscal year
    fy = None
    getter = globals().get("get_active_fiscal_year")
    try:
        if callable(getter):
            fy = getter()
    except Exception:
        fy = None
    if not fy:
        from datetime import datetime
        fy = datetime.now().year

    # directory to store excels (same as create_empty_excel_for_vat)
    excel_dir = os.path.join(DATA_DIR, "excel")
    os.makedirs(excel_dir, exist_ok=True)

    if safe_vat:
        # 1) prefer vat + fiscal year
        candidate1 = os.path.join(excel_dir, f"{safe_vat}_{fy}_invoices.xlsx")
        if os.path.exists(candidate1):
            return candidate1
        # 2) fallback to vat only (older pattern)
        candidate2 = os.path.join(excel_dir, f"{safe_vat}_invoices.xlsx")
        if os.path.exists(candidate2):
            return candidate2

    # 3) fallback to DEFAULT_EXCEL_FILE if present
    if "DEFAULT_EXCEL_FILE" in globals() and globals().get("DEFAULT_EXCEL_FILE"):
        return globals()["DEFAULT_EXCEL_FILE"]

    # 4) last-resort: return candidate1 path (where we would create the fiscal-year file)
    if safe_vat:
        return os.path.join(excel_dir, f"{safe_vat}_{fy}_invoices.xlsx")
    # if nothing else, return some default in DATA_DIR
    return os.path.join(DATA_DIR, f"unknown_{fy}_invoices.xlsx")

def _atomic_write(path, data_text):
    dirn = os.path.dirname(path)
    os.makedirs(dirn, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=dirn, prefix=".tmp_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(data_text)
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            try: os.remove(tmp_path)
            except Exception: pass

def _load_json(path):
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def _save_json(path, obj):
    txt = json.dumps(obj, ensure_ascii=False, indent=2)
    _atomic_write(path, txt)

def _match_row_by_mark(df, mark):
    """
    Προσπαθεί να βρει γραμμή στο dataframe df όπου κάποια από τις πιθανές στήλες που
    αντιστοιχούν σε 'mark' ταιριάζει με την τιμή mark.
    Επιστρέφει (found_bool, row_dict_or_None, column_name_used_or_None)
    """
    possible_cols = [
        "mark", "MARK", "Mark",
        "invoice_id", "invoiceId", "id",
        "Αριθμός", "Αριθμός Μητρώου", "Αριθμός Μητρώου Παρ", "Α/Α",
        "αριθμος", "α/α"
    ]
    for col in possible_cols:
        if col in df.columns:
            # ανάγνωση ως string για ασφαλή σύγκριση
            matches = df[df[col].astype(str).str.strip() == str(mark).strip()]
            if not matches.empty:
                # επιστρέφουμε την πρώτη αντιστοιχία ως dict
                return True, matches.iloc[0].to_dict(), col
    # Γενικός fallback: ψάξε σε όλες τις στήλες που είναι string-like
    str_cols = [c for c in df.columns if df[c].dtype == 'object' or df[c].dtype == 'string']
    for c in str_cols:
        matches = df[df[c].astype(str).str.strip() == str(mark).strip()]
        if not matches.empty:
            return True, matches.iloc[0].to_dict(), c
    return False, None, None

def get_active_credential_from_session() -> Optional[Dict]:
    name = session.get("active_credential")
    return get_cred_by_name(name) if name else None

# NEW helper: epsilon per-vat path
def epsilon_file_path_for(vat: str) -> str:
    epsilon_dir = os.path.join(DATA_DIR, "epsilon")
    os.makedirs(epsilon_dir, exist_ok=True)
    return os.path.join(epsilon_dir, secure_filename(f"{vat}_epsilon_invoices.json"))

# New function: build epsilon from invoices.json (used when epsilon file missing)
def build_epsilon_from_invoices(vat: str) -> List[Dict]:
    """
    Δημιουργεί αρχική λίστα εγγραφών για το epsilon file (per-VAT) βασισμένη
    στο data/{vat}_invoices.json. Κάθε εγγραφή έχει:
      { "mark": "...", "AA": ..., "AFM": ..., "lines": [ {id, description, amount, vat, category:''}, ... ] }
    """
    invoices_file = get_customer_docs_file(vat)
    invoices = json_read(invoices_file) if os.path.exists(invoices_file) else []
    epsilon_list: List[Dict] = []

    def pick(src: dict, *keys, default=""):
        for k in keys:
            if k in src and src.get(k) not in (None, ""):
                return src.get(k)
        return default

    for doc in invoices:
        mark = str(pick(doc, "mark", "MARK", "Mark", default="")).strip()
        if not mark:
            mark = str(pick(doc, "identifier", "id", default="")).strip()
        if not mark:
            continue
        vat_doc = pick(doc, "AFM", "AFM_issuer", default="")
        aa = pick(doc, "AA", "aa", default="")
        raw_lines = doc.get("lines") or doc.get("Lines") or doc.get("Positions") or []
        prepared = []
        for idx, raw in enumerate(raw_lines):
            line_id = raw.get("id") or raw.get("line_id") or raw.get("LineId") or f"{mark}_l{idx}"
            description = pick(raw, "description", "desc", "Description", "name", "Name") or ""
            amount = pick(raw, "amount", "lineTotal", "net", "value", default="")
            vat_rate = pick(raw, "vat", "vatRate", "vatPercent", "vatAmount", default="")
            prepared.append({
                "id": line_id,
                "description": description,
                "amount": amount,
                "vat": vat_rate,
                "category": ""   # αρχικά κενό, user θα το συμπληρώσει
            })
        epsilon_list.append({
            "mark": mark,
            "AA": aa,
            "AFM": vat_doc,
            "lines": prepared
        })
    return epsilon_list

def load_epsilon_cache_for_vat(vat: str) -> List[Dict]:
    """
    Αν υπάρχει το per-vat epsilon αρχείο το διαβάζει, αλλιώς το χτίζει
    από το {vat}_invoices.json (με build_epsilon_from_invoices) και το αποθηκεύει.
    """
    path = epsilon_file_path_for(vat)
    if os.path.exists(path):
        try:
            return json_read(path)
        except Exception:
            log.exception("Could not read epsilon cache for %s", vat)
            return []
    # build from invoices if possible
    try:
        epsilon_list = build_epsilon_from_invoices(vat)
        if epsilon_list:
            try:
                json_write(path, epsilon_list)
                log.info("Built epsilon cache for %s from %s_invoices.json (%d entries)", vat, vat, len(epsilon_list))
            except Exception:
                log.exception("Could not write newly built epsilon cache for %s", vat)
        return epsilon_list
    except Exception:
        log.exception("Failed to build epsilon cache from invoices for %s", vat)
        return []

def save_epsilon_cache_for_vat(vat: str, data: List[Dict]):
    path = epsilon_file_path_for(vat)
    try:
        json_write(path, data)
    except Exception:
        log.exception("Could not write epsilon cache for %s", vat)

# στο app.py — κάτω από get_active_credential_from_session()
@app.context_processor
def inject_active_credential():
    """
    Εισάγει αυτόματα στα templates:
      - active_credential: όνομα credential ή None
      - active_credential_vat: ΑΦΜ του active credential (ή empty string)
      - app_settings: γενικές ρυθμίσεις εφαρμογής (φορτώνονται από SETTINGS_FILE)
    """
    active = get_active_credential_from_session()
    name = active.get("name") if active else None
    vat = active.get("vat") if active else ""
    # Load settings (fall back to empty dict)
    try:
        settings = load_settings() or {}
    except Exception:
        log.exception("Could not load settings for context processor")
        settings = {}
    return dict(active_credential=name, active_credential_vat=vat, app_settings=settings)


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


@app.route('/get_fiscal_year', methods=['GET'])
def route_get_fiscal_year():
    """
    GET -> return current fiscal year if present:
    { exists: bool, fiscal_year: int|null }
    """
    y = get_active_fiscal_year()
    return jsonify(exists=(y is not None), fiscal_year=y), 200

@app.route('/set_fiscal_year', methods=['POST'])
def route_set_fiscal_year():
    """
    POST JSON or form: { fiscal_year: 2025 } or { year: 2025 }
    Returns JSON { success: bool, fiscal_year: int|null, message: str }
    """
    try:
        # accept JSON or form
        data = request.get_json(silent=True) or request.form or {}
        fy = data.get('fiscal_year') or data.get('year') or None
        if fy is None:
            return jsonify(success=False, message='Missing fiscal_year'), 400
        try:
            fy_int = int(fy)
        except Exception:
            return jsonify(success=False, message='Invalid fiscal_year'), 400

        ok = set_active_fiscal_year(fy_int)
        if not ok:
            return jsonify(success=False, message='Could not persist fiscal year'), 500
        return jsonify(success=True, fiscal_year=fy_int, message='Fiscal year updated'), 200
    except Exception:
        try:
            log.exception("Failed in set_fiscal_year")
        except Exception:
            pass
        return jsonify(success=False, message='Server error'), 500

# --- helpers για upsert / merge epsilon invoices -------------------------------
import uuid
from collections import OrderedDict

def _normalize_val(v):
    try:
        return "" if v is None else str(v).strip()
    except Exception:
        return ""

def _make_id_inv():
    return uuid.uuid4().hex

def _write_json_atomic(path, obj):
    """Atomic write (utf-8, indent=2)."""
    import tempfile
    dirn = os.path.dirname(path)
    os.makedirs(dirn, exist_ok=True)
    text = json.dumps(obj, ensure_ascii=False, indent=2)
    fd, tmp = tempfile.mkstemp(prefix=".tmp_json_", dir=dirn)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except Exception:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass
        raise

def _upsert_epsilon_invoice(new_doc: dict):
    """
    Insert or update a detailed invoice record into the proper data/epsilon/*_epsilon_invoices.json.
    - Matches by mark (preferred) or AA.
    - If it finds an existing placeholder it replaces/merges it and preserves id_inv (or creates one).
    - If not found, it creates a per-vat file using AFM_issuer/AFM (if available) or 'unknown'.
    Returns (path_written, id_inv).
    """
    epsilon_dir = os.path.join(DATA_DIR, "epsilon")
    os.makedirs(epsilon_dir, exist_ok=True)

    mark = _normalize_val(new_doc.get("mark") or new_doc.get("MARK"))
    aa = _normalize_val(new_doc.get("AA") or new_doc.get("aa"))
    target_vat = _normalize_val(new_doc.get("AFM_issuer") or new_doc.get("AFM") or new_doc.get("issuer_vat"))

    # build candidate list: prefer per-vat file if target_vat present, then all others
    candidates = []
    if target_vat:
        candidates.append(os.path.join(epsilon_dir, f"{secure_filename(target_vat)}_epsilon_invoices.json"))
    for fname in sorted(os.listdir(epsilon_dir)):
        if not fname.endswith("_epsilon_invoices.json"):
            continue
        full = os.path.join(epsilon_dir, fname)
        if full not in candidates:
            candidates.append(full)

    # helper to extract list container & container_key info
    def _extract_items_and_container(raw):
        if isinstance(raw, list):
            return raw, True, None, raw  # items, is_root_list, key, root_container
        if isinstance(raw, dict):
            for k in ("items", "invoices", "data", "records"):
                if k in raw and isinstance(raw[k], list):
                    return raw[k], False, k, raw
            # maybe single invoice dict
            if any(k in raw for k in ("mark", "AA", "AFM", "AFM_issuer")):
                return [raw], False, None, raw
        return [], False, None, raw

    # try to find & replace/merge
    for path in candidates:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
        except Exception:
            # ignore unreadable files
            continue

        items, is_list, container_key, root_container = _extract_items_and_container(raw)
        if not items:
            continue

        changed = False
        for idx, it in enumerate(items):
            try:
                it_mark = _normalize_val(it.get("mark") or it.get("MARK"))
                it_aa = _normalize_val(it.get("AA") or it.get("aa"))
                # match exact or substring (covers small formatting diffs)
                matched = False
                if mark and it_mark and (mark == it_mark or mark in it_mark or it_mark in mark):
                    matched = True
                elif aa and it_aa and aa == it_aa:
                    matched = True

                if not matched:
                    continue

                # found matching existing item -> merge/replace
                existing = dict(it) if isinstance(it, dict) else {}
                # preserve existing id_inv if present, else take from new_doc, else create one
                id_inv = _normalize_val(existing.get("id_inv") or new_doc.get("id_inv") or new_doc.get("id") or "")
                if not id_inv:
                    id_inv = _make_id_inv()

                # merge: new_doc fields override existing ones; keep any remaining existing keys if not present in new_doc
                merged = dict(existing)
                merged.update(new_doc)  # new_doc wins
                merged["id_inv"] = id_inv

                # ensure id_inv appears BEFORE 'lines' key in JSON order
                new_ordered = OrderedDict()
                inserted = False
                for k, v in list(merged.items()):
                    if k == "lines" and not inserted:
                        new_ordered["id_inv"] = id_inv
                        inserted = True
                    new_ordered[k] = v
                if not inserted:
                    # append id_inv at start (or end - we put at start to be "before lines")
                    od = OrderedDict()
                    od["id_inv"] = id_inv
                    for k,v in new_ordered.items():
                        od[k] = v
                    new_ordered = od

                # replace the item in the list
                items[idx] = dict(new_ordered)
                changed = True
                # write back updated container
                if changed:
                    if is_list:
                        to_write = items
                    else:
                        if container_key:
                            root_container[container_key] = items
                            to_write = root_container
                        else:
                            # single dict root replaced by this new item
                            to_write = items[0]
                    _write_json_atomic(path, to_write)
                    try:
                        log.info("_upsert_epsilon_invoice: updated %s (mark=%s AA=%s id_inv=%s)", path, mark, aa, id_inv)
                    except Exception:
                        pass
                    return path, id_inv

            except Exception:
                continue

    # not found anywhere -> create per-vat file (prefer AFM_issuer/AFM), else 'unknown'
    safe_vat = secure_filename(target_vat) if target_vat else "unknown"
    new_path = os.path.join(epsilon_dir, f"{safe_vat}_epsilon_invoices.json")
    id_inv = _normalize_val(new_doc.get("id_inv") or new_doc.get("id") or "")
    if not id_inv:
        id_inv = _make_id_inv()

    # ensure id_inv before lines
    merged = dict(new_doc)
    merged["id_inv"] = id_inv
    new_ordered = OrderedDict()
    inserted = False
    for k, v in list(merged.items()):
        if k == "lines" and not inserted:
            new_ordered["id_inv"] = id_inv
            inserted = True
        new_ordered[k] = v
    if not inserted:
        od = OrderedDict()
        od["id_inv"] = id_inv
        for k,v in new_ordered.items():
            od[k] = v
        new_ordered = od

    # write single-element list to new_path (or append if file exists and is a list)
    try:
        if os.path.exists(new_path):
            # if file exists and is a list, load & append
            with open(new_path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
            if isinstance(raw, list):
                raw.append(dict(new_ordered))
                _write_json_atomic(new_path, raw)
            elif isinstance(raw, dict):
                # try to append into detected container key if possible, else rewrite as list
                appended = False
                for k in ("items","invoices","data","records"):
                    if k in raw and isinstance(raw[k], list):
                        raw[k].append(dict(new_ordered))
                        _write_json_atomic(new_path, raw)
                        appended = True
                        break
                if not appended:
                    # convert to list form
                    _write_json_atomic(new_path, [dict(new_ordered)])
            else:
                _write_json_atomic(new_path, [dict(new_ordered)])
        else:
            _write_json_atomic(new_path, [dict(new_ordered)])
        try:
            log.info("_upsert_epsilon_invoice: created %s (mark=%s AA=%s id_inv=%s)", new_path, mark, aa, id_inv)
        except Exception:
            pass
        return new_path, id_inv
    except Exception:
        try:
            log.exception("_upsert_epsilon_invoice: write failed for %s", new_path)
        except Exception:
            pass
        return "", ""
# -------------------------------------------------------------------------------

# ---------- validation helpers ----------
def parse_date_str_to_utc(date_str):
    """
    Try parse a date string (ISO-ish or dd/mm/yyyy or yyyy-mm-dd).
    Returns a datetime in UTC (naive or tz aware converted to UTC) or None.
    """
    if not date_str:
        return None
    # try ISO first
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            dt = _dt.strptime(date_str, fmt)
            # naive -> assume local? we'll treat naive as UTC to be strict
            if dt.tzinfo is None:
                # treat as UTC for server-side canonicalization
                dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = dt.astimezone(timezone.utc)
            return dt
        except Exception:
            continue
    # last resort: try dateutil if available
    try:
        from dateutil import parser as _parser
        dt = _parser.parse(date_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt
    except Exception:
        return None

def is_date_within_fiscal_year(dt_utc, fiscal_year):
    """
    dt_utc: datetime with tzinfo=UTC
    fiscal_year: int (e.g. 2025)
    Assumes fiscal year = calendar year (Jan 1 - Dec 31).
    If your fiscal year differs, adapt start/end calculation here.
    """
    if not dt_utc or fiscal_year is None:
        return False
    start = _dt(fiscal_year, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    end = _dt(fiscal_year, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
    return start <= dt_utc <= end

def validate_date_field_against_active_fiscal(date_str, field_name='date'):
    """
    Centralized server-side check. Returns (ok:bool, message:str).
    Use this in any route that receives date strings from user.
    """
    fiscal_year = get_active_fiscal_year()
    if fiscal_year is None:
        return True, "No active fiscal year set"  # if no selection, don't block
    dt = parse_date_str_to_utc(date_str)
    if dt is None:
        return False, f"Δεν αναγνώστηκε σωστά η ημερομηνία στο πεδίο {field_name}."
    if not is_date_within_fiscal_year(dt, fiscal_year):
        # produce message with allowed year info
        return False, f"Η επιλεγμένη χρήση είναι {fiscal_year}. Η ημερομηνία στο πεδίο {field_name} ({date_str}) δεν ανήκει στη χρήση αυτή."
    return True, "OK"

@app.route('/api/repeat_entry/get', methods=['GET'])
def api_repeat_entry_get():
    creds = read_credentials_list()
    if not creds:
        return jsonify({"ok": True, "repeat_entry": {"enabled": False, "mapping": {}}, "expense_tags": []})
    vat = request.args.get('vat') or (get_active_credential_from_session() or {}).get('vat')
    idx = find_active_client_index(creds, vat=vat)
    if idx is None:
        return jsonify({"ok": True, "repeat_entry": {"enabled": False, "mapping": {}}, "expense_tags": []})
    repeat = creds[idx].get('repeat_entry', {"enabled": False, "mapping": {}})
    # ensure expense_tags is a list of strings
    raw_tags = creds[idx].get('expense_tags') or []
    if isinstance(raw_tags, str):
        expense_tags = [t.strip() for t in raw_tags.split(',') if t.strip()]
    elif isinstance(raw_tags, list):
        expense_tags = [str(t) for t in raw_tags]
    else:
        expense_tags = []
    return jsonify({"ok": True, "repeat_entry": repeat, "expense_tags": expense_tags})


@app.route('/api/repeat_entry/save', methods=['POST'])
def api_repeat_entry_save():
    payload = request.get_json(silent=True) or {}
    enabled = bool(payload.get('enabled', False))
    mapping = payload.get('mapping', {}) or {}

    # sanitize + normalize mapping keys and values
    normalized_mapping = {}
    for k, v in mapping.items():
        nk = normalize_vat_key(k)
        if not nk:
            # allow storing __default specially (leave as-is)
            if str(k).strip() == '__default' and v:
                normalized_mapping['__default'] = str(v).strip()
            continue
        normalized_mapping[nk] = str(v).strip()

    creds = read_credentials_list()
    vat = payload.get('vat') or (get_active_credential_from_session() or {}).get('vat')
    idx = find_active_client_index(creds, vat=vat)
    if idx is None:
        return jsonify({"ok": False, "error": "No credentials found"}), 400

    creds[idx].setdefault('repeat_entry', {})
    creds[idx]['repeat_entry']['enabled'] = enabled
    creds[idx]['repeat_entry']['mapping'] = normalized_mapping
    creds[idx]['repeat_entry']['updated_at'] = datetime.datetime.utcnow().isoformat() + 'Z'
    creds[idx]['repeat_entry']['user'] = (get_active_credential_from_session() or {}).get('user') or 'unknown'

    try:
        write_credentials_list(creds)
        # optionally: return expense_tags too, if you earlier wanted that
        return jsonify({"ok": True, "repeat_entry": creds[idx]['repeat_entry']})
    except Exception as e:
        log.exception("Failed saving repeat_entry")
        return jsonify({"ok": False, "error": str(e)}), 500



@app.route('/credentials/add', methods=['POST'])
def credentials_add():
    credentials = load_credentials()
    name = request.form.get('name')
    vat = request.form.get('vat')
    user = request.form.get('user')
    key = request.form.get('key')
    book_category = request.form.get('book_category','Β')
    fpa_applicable = bool(request.form.get('fpa_applicable'))
    expense_tags = request.form.getlist('expense_tags')
    apodeixakia_type = request.form.get('apodeixakia_type', '').strip()
    apodeixakia_supplier = request.form.get('apodeixakia_supplier', '').strip()
    new_cred = {
        'name': name,
        'vat': vat,
        'user': user,
        'key': key,
        'book_category': book_category,
        'fpa_applicable': fpa_applicable,
        'expense_tags': expense_tags,
        'apodeixakia_type': apodeixakia_type,
        'apodeixakia_supplier': apodeixakia_supplier,
        'active': False
    }
    credentials.append(new_cred)
    save_credentials(credentials)
    # <-- added flash to ensure message appears if this route is used
    flash("Saved", "success")
    return redirect(url_for('credentials'))




@app.route('/credentials/delete/<name>', methods=['POST'])
def credentials_delete_post(name):
    credentials = load_credentials()
    credentials = [c for c in credentials if c['name'] != name]
    save_credentials(credentials)
    # <-- added flash to ensure message appears if this route is used
    flash(f"Credential {name} διαγράφηκε.", "success")
    return redirect(url_for('credentials'))

@app.route('/credentials/set_active', methods=['POST'])
def credentials_set_active():
    active_name = request.form.get('active_name')
    credentials = load_credentials()
    for c in credentials:
        c['active'] = (c['name'] == active_name)
    save_credentials(credentials)
    # <-- added flash in case this route is used
    flash(f"Active credential set to {active_name}", "success")
    return redirect(url_for('credentials'))

@app.route('/credentials/save_settings', methods=['POST'])
def credentials_save_settings():
    data = request.get_json()
    if data:
        save_settings(data)
        return jsonify({'status':'ok'})
    return jsonify({'status':'error'}), 400

@app.route('/api/save_receipt', methods=['POST'])
def api_save_receipt():
    """
    Expects JSON { "summary": {...} }
    Writes ONLY to epsilon_invoices.json and to Excel.
    Returns JSON { ok: True, duplicate: Bool, message: str }
    """
    try:
        payload = request.get_json(silent=True) or {}
        summary = payload.get('summary') or {}
        if not summary:
            return jsonify(ok=False, error='no summary provided'), 400

        rec = _normalize_receipt_summary(summary)

        # Acquire JSON lock and check duplicates & append
        json_lock = FileLock(EPSILON_JSON_LOCK, timeout=10)
        with json_lock:
            epsilon_list = _read_epsilon_json()
            if _is_duplicate_in_epsilon(epsilon_list, rec):
                return jsonify(ok=True, duplicate=True, message='duplicate entry'), 200
            # append and write
            epsilon_list.append(rec)
            try:
                _write_epsilon_json(epsilon_list)
            except Exception as e:
                current_app.logger.exception("failed writing epsilon json: %s", e)
                return jsonify(ok=False, error='write epsilon json failed'), 500

        # Append to Excel with separate lock
        excel_lock = FileLock(EXCEL_FILE_LOCK, timeout=10)
        with excel_lock:
            ok_excel = _append_to_excel(rec)
            if not ok_excel:
                current_app.logger.warning("Excel append failed for record: %s", rec)
                # we proceed since epsilon json already saved - but inform client
                return jsonify(ok=True, duplicate=False, warning='excel_append_failed', message='saved to epsilon json but excel append failed'), 200

        return jsonify(ok=True, duplicate=False, message='saved'), 200

    except Exception as e:
        current_app.logger.exception("api_save_receipt error: %s", e)
        return jsonify(ok=False, error=str(e)), 500

@app.route('/upload_client_db', methods=['POST'])
def upload_client_db():
    """
    Accept multipart/form-data with field 'client_file' and save it into DATA_DIR
    as client_db{.ext}. Existing client_db* files are moved to backups with a UTC timestamp.
    Also writes client_db.meta.json with original filename + uploaded_at.
    Returns JSON { success: bool, message: str }.
    """
    try:
        os.makedirs(DATA_DIR, exist_ok=True)

        if 'client_file' not in request.files:
            return jsonify(success=False, message='Δεν βρέθηκε το πεδίο client_file στο αίτημα.'), 400

        f = request.files['client_file']
        if not f or not getattr(f, 'filename', '').strip():
            return jsonify(success=False, message='Δεν επιλέχθηκε αρχείο.'), 400

        filename = secure_filename(f.filename)
        base, ext = os.path.splitext(filename)
        ext = ext.lower()
        if ext not in ALLOWED_CLIENT_EXT:
            return jsonify(success=False, message='Μη επιτρεπτή επέκταση. Χρήση .xlsx, .xls ή .csv'), 400

        dest_name = f'client_db{ext}'
        dest_path = os.path.join(DATA_DIR, dest_name)

        # Backup existing client_db.* files (if any)
        try:
            for existing in os.listdir(DATA_DIR):
                if existing.startswith('client_db') and os.path.splitext(existing)[1].lower() in ALLOWED_CLIENT_EXT:
                    existing_path = os.path.join(DATA_DIR, existing)
                    ts = _dt.utcnow().strftime('%Y%m%dT%H%M%SZ')
                    backup_name = f"{existing}.bak.{ts}"
                    backup_path = os.path.join(DATA_DIR, backup_name)
                    os.rename(existing_path, backup_path)
                    log.info("Backed up previous client_db: %s -> %s", existing, backup_name)
        except Exception:
            log.exception("Failed to backup existing client_db files (continuing)")

        # Save uploaded file
        try:
            f.save(dest_path)
        except Exception:
            log.exception("Failed to save uploaded client_db to %s", dest_path)
            return jsonify(success=False, message='Σφάλμα κατά την αποθήκευση του αρχείου.'), 500

        # write meta with original filename + uploaded timestamp (UTC ISO)
        try:
            uploaded_at_iso = _dt.utcnow().replace(microsecond=0).isoformat() + 'Z'
            write_client_meta(filename, uploaded_at_iso)
        except Exception:
            log.exception("Failed to write client_db metadata (continuing)")

        return jsonify(success=True, message=f'Αποθηκεύτηκε: {dest_name}', filename=filename, uploaded_at=uploaded_at_iso), 200

    except Exception:
        log.exception("Unhandled exception in upload_client_db")
        return jsonify(success=False, message='Εσωτερικό σφάλμα server.'), 500


@app.route('/client_db_info', methods=['GET'])
def client_db_info():
    """
    Return JSON with metadata about current client_db (if exists).
    { exists: bool, filename: str|null, uploaded_at: str|null }
    """
    try:
        meta = read_client_meta()
        if meta:
            return jsonify(exists=True, filename=meta.get('filename'), uploaded_at=meta.get('uploaded_at')), 200

        # fallback: if any client_db.* exists but no meta file, infer using file mtime
        for existing in os.listdir(DATA_DIR):
            if existing.startswith('client_db') and os.path.splitext(existing)[1].lower() in ALLOWED_CLIENT_EXT:
                p = os.path.join(DATA_DIR, existing)
                try:
                    mtime = _dt.utcfromtimestamp(os.path.getmtime(p)).replace(microsecond=0).isoformat() + 'Z'
                    return jsonify(exists=True, filename=existing, uploaded_at=mtime), 200
                except Exception:
                    continue

        return jsonify(exists=False, filename=None, uploaded_at=None), 200
    except Exception:
        log.exception("Failed to read client_db info")
        return jsonify(exists=False, filename=None, uploaded_at=None), 500
# ---------- end client_db helpers + routes ----------

# credentials CRUD (unchanged behaviour) but pass active credential to template
@app.route("/credentials", methods=["GET", "POST"])
def credentials():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        user = request.form.get("user", "").strip()
        key = request.form.get("key", "").strip()
        env = MYDATA_ENV
        vat = request.form.get("vat", "").strip()

        # Νέα πεδία
        book_category = request.form.get("book_category", "Β").strip() or "Β"
        fpa_applicable = True if request.form.get("fpa_applicable") in ("on", "true", "1") else False
        expense_tags = request.form.getlist("expense_tags") or []
        apodeixakia_type = request.form.get("apodeixakia_type", "").strip()   # "afm" or "supplier"
        apodeixakia_supplier = request.form.get("apodeixakia_supplier", "").strip()

        if not name:
            flash("Name required", "error")
        else:
            entry = {
                "name": name,
                "user": user,
                "key": key,
                "env": env,
                "vat": vat,
                # προσθήκη νέων πεδίων
                "book_category": book_category,
                "fpa_applicable": fpa_applicable,
                "expense_tags": expense_tags,
                "apodeixakia_type": apodeixakia_type,
                "apodeixakia_supplier": apodeixakia_supplier
            }
            ok, err = add_credential(entry)
            if ok:
                flash("Saved", "success")
            else:
                flash(err or "Could not save", "error")
        return redirect(url_for("credentials"))

    # GET: φορτώνουμε τα credentials και αφήνουμε το context_processor να περάσει το active credential/ΑΦΜ
    creds = load_credentials()
    return safe_render("credentials_list.html", credentials=creds, active_page="credentials")


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

        # Νέα πεδία από τη φόρμα επεξεργασίας
        book_category = request.form.get("book_category", "Β").strip() or "Β"
        fpa_applicable = True if request.form.get("fpa_applicable") in ("on", "true", "1") else False
        expense_tags = request.form.getlist("expense_tags") or []

        # Νέα πεδία (apodeixakia) - fallback στις υπάρχουσες τιμές αν δεν παρέχονται
        apodeixakia_type = request.form.get("apodeixakia_type")
        if apodeixakia_type is None:
            apodeixakia_type = credential.get("apodeixakia_type", "")
        else:
            apodeixakia_type = apodeixakia_type.strip()

        apodeixakia_supplier = request.form.get("apodeixakia_supplier")
        if apodeixakia_supplier is None:
            apodeixakia_supplier = credential.get("apodeixakia_supplier", "")
        else:
            apodeixakia_supplier = apodeixakia_supplier.strip()

        if not new_name:
            flash("Name required", "error")
            return redirect(url_for("credentials_edit", name=name))

        if new_name != name and any(c.get("name") == new_name for c in creds):
            flash("Another credential with that name already exists", "error")
            return redirect(url_for("credentials_edit", name=name))

        new_entry = {
            "name": new_name,
            "user": user,
            "key": key,
            "env": env,
            "vat": vat,
            # Αποθηκεύουμε επίσης τα νέα πεδία
            "book_category": book_category,
            "fpa_applicable": fpa_applicable,
            "expense_tags": expense_tags,
            # Αποθηκεύουμε και τα apodeixakia πεδία
            "apodeixakia_type": apodeixakia_type,
            "apodeixakia_supplier": apodeixakia_supplier
        }

        updated = False
        for i, c in enumerate(creds):
            if c.get("name") == name:
                creds[i] = new_entry
                updated = True
                break
        if not updated:
            creds.append(new_entry)

        save_credentials(creds)

        # Αν το credential που επεξεργάστηκε ήταν ενεργό — ενημέρωσε session
        if session.get("active_credential") == name:
            session["active_credential"] = new_name
            flash(f"Active credential updated to '{new_name}'", "success")
        else:
            flash(f"Credential '{new_name}' updated successfully", "success")

        return redirect(url_for("credentials"))

    # GET -> εμφανίζουμε τη φόρμα επεξεργασίας
    # Προσθέτουμε flash πληροφορία (παραμένει ως έχει)
    flash(f"Editing credential: {credential.get('name')}", "info")
    return safe_render(
        "credentials_edit.html",
        credential=credential,
        active_page="credentials"
    )


@app.route("/credentials/delete/<name>", methods=["POST"])
def credentials_delete(name):
    creds = load_credentials()
    credential = next((c for c in creds if c.get("name") == name), None)

    if not credential:
        # Αν είναι AJAX, επιστρέφουμε JSON
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'status': 'error', 'error': 'not found'}), 404
        flash(f"Credential '{name}' not found", "error")
        return redirect(url_for("credentials"))

    # Αφαίρεση credential
    creds = [c for c in creds if c.get("name") != name]
    save_credentials(creds)

    # Αν ήταν ενεργό, καθαρίζουμε session
    was_active = False
    if session.get("active_credential") == name:
        session.pop("active_credential", None)
        was_active = True

    # Αν request από AJAX, επιστρέφουμε JSON ώστε το frontend fetch να το χειριστεί
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'status': 'ok', 'deleted': name, 'was_active': was_active})

    # Διαφορετικά κάνουμε τα flash + redirect όπως παλιά
    if was_active:
        flash(f"Active credential '{name}' διαγράφηκε και αφαιρέθηκε από τα ενεργά.", "success")
    else:
        flash(f"Credential '{name}' διαγράφηκε.", "success")

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
    preview = []
    creds = load_credentials()
    active_cred = get_active_credential_from_session()
    active_name = active_cred.get("name") if active_cred else None

    if request.method == "POST":
        date_from_raw = request.form.get("date_from", "").strip()
        date_to_raw = request.form.get("date_to", "").strip()
        date_from_iso = normalize_input_date_to_iso(date_from_raw)
        date_to_iso = normalize_input_date_to_iso(date_to_raw)

        if not date_from_iso or not date_to_iso:
            error = "Παρακαλώ συμπλήρωσε έγκυρες ημερομηνίες (dd/mm/YYYY)."
            return safe_render("fetch.html", credentials=creds, message=message,
                               error=error, preview=preview, active_page="fetch",
                               active_credential=active_name)

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
            return safe_render("fetch.html", credentials=creds, message=message,
                               error=error, preview=preview, active_page="fetch",
                               active_credential=active_name)

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

            added_docs = 0
            added_summaries = 0
            for d in all_rows:
                if vat:
                    d["AFM"] = vat  # προσθέτουμε AFM
                if append_doc_to_customer_file(d, vat):
                    added_docs += 1

            for s in summary_list:
                if append_summary_to_customer_file(s, vat):
                    added_summaries += 1

            message = (f"Fetched {len(all_rows)} items, newly saved for VAT {vat}: "
                       f"{added_docs} docs, {added_summaries} summaries.")

            preview = all_rows[:40]

        except Exception as e:
            log.exception("Fetch error")
            error = f"Σφάλμα λήψης: {str(e)[:400]}"

    return safe_render("fetch.html", credentials=creds, message=message,
                       error=error, preview=preview, active_page="fetch",
                       active_credential=active_name)


@app.route("/credentials/get_settings", methods=["GET"])
def credentials_get_settings():
    """
    Επιστρέφει τα stored general settings σε JSON — βολικό για AJAX αν το cog τα φορτώνει δυναμικά.
    """
    try:
        settings = load_settings() or {}
        return jsonify({"status": "ok", "settings": settings})
    except Exception as e:
        log.exception("Could not return settings")
        return jsonify({"status":"error","error":str(e)}), 500


@app.route("/api/check_mark", methods=["POST"])
def api_check_mark():
    """
    Payload JSON: { vat: str, mark: str }
    Επιστρέφει: { found: bool, source: "excel"/"none", characteristic: str|null, row: {...} }
    """
    try:
        payload = request.get_json(force=True)
        vat = payload.get("vat")
        mark = payload.get("mark")
        if not vat or not mark:
            return jsonify({"ok": False, "error": "missing vat or mark"}), 400

        safe_vat = secure_filename(vat)
        excel_path = os.path.join("uploads", f"{safe_vat}_invoices.xlsx")
        if not os.path.exists(excel_path):
            return jsonify({"ok": True, "found": False}), 200

        # διαβάζουμε το excel (single sheet)
        try:
            df = pd.read_excel(excel_path, dtype=str)  # read everything as str for safe compare
        except Exception as e:
            current_app.logger.exception("Failed to read excel for check_mark")
            return jsonify({"ok": False, "error": "cannot_read_excel", "detail": str(e)}), 500

        found, row, col = _match_row_by_mark(df, mark)
        if not found:
            return jsonify({"ok": True, "found": False}), 200

        # προσπαθούμε να βρούμε χαρακτηρισμό:
        # 1) πρώτα ψάχνουμε στο epsilon cache αν υπάρχει (καλύτερο για authoritative value)
        epsilon_path = os.path.join("data", "epsilon", f"{safe_vat}_epsilon_invoices.json")
        epsilon_list = _load_json(epsilon_path) or []
        # αναζητάμε στην epsilon λίστα για το ίδιο mark
        def _match_in_epsilon(item):
            for candidate_key in ("mark", "MARK", "invoice_id", "id", "Αριθμός Μητρώου", "Αριθμός"):
                if candidate_key in item and str(item[candidate_key]).strip() == str(mark).strip():
                    return True
            return False
        matched_eps = None
        for it in epsilon_list:
            if _match_in_epsilon(it):
                matched_eps = it
                break

        characteristic = None
        if matched_eps:
            # Έχουμε authoritative χαρακτηρισμό στον epsilon cache (προτεραιότητα)
            characteristic = matched_eps.get("χαρακτηρισμός") or matched_eps.get("characteristic") or matched_eps.get("flag")
        else:
            # αλλιώς ελέγχουμε αν υπάρχει στήλη χαρακτηρισμός στο excel row
            for candidate in ("χαρακτηρισμός", "χαρακτηρισμος", "characteristic", "flag", "Χαρακτηρισμός"):
                if candidate in row and row[candidate] not in (None, "", "nan"):
                    characteristic = row[candidate]
                    break

        return jsonify({
            "ok": True,
            "found": True,
            "source": "excel",
            "excel_column_used": col,
            "row": row,
            "characteristic": characteristic
        }), 200

    except Exception as e:
        current_app.logger.exception("api_check_mark failed")
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/api/update_epsilon_characteristic", methods=["POST"])
def api_update_epsilon_characteristic():
    """
    Payload JSON: { vat: str, mark: str, characteristic: str }
    Ενημερώνει ΜΟΝΟ το data/epsilon/{vat}_epsilon_invoices.json το πεδίο χαρακτηρισμός
    (δημιουργεί εγγραφή αν δεν υπάρχει).
    """
    try:
        payload = request.get_json(force=True)
        vat = payload.get("vat")
        mark = payload.get("mark")
        new_char = payload.get("characteristic")
        if not vat or not mark:
            return jsonify({"ok": False, "error": "missing vat or mark"}), 400

        safe_vat = secure_filename(vat)
        epsilon_dir = os.path.join("data", "epsilon")
        os.makedirs(epsilon_dir, exist_ok=True)
        epsilon_path = os.path.join(epsilon_dir, f"{safe_vat}_epsilon_invoices.json")
        epsilon_list = _load_json(epsilon_path) or []

        # Try to find existing invoice by common keys
        def _match(item):
            for candidate_key in ("mark", "MARK", "invoice_id", "id", "Αριθμός Μητρώου", "Αριθμός"):
                if candidate_key in item and str(item[candidate_key]).strip() == str(mark).strip():
                    return True
            return False

        found = False
        for i, item in enumerate(epsilon_list):
            if _match(item):
                # update only χαρακτηρισμός-related keys
                epsilon_list[i]["χαρακτηρισμός"] = new_char
                epsilon_list[i]["characteristic"] = new_char  # για συμβατότητα
                epsilon_list[i]["_updated_at"] = datetime.utcnow().isoformat() + "Z"
                found = True
                break

        if not found:
            # Δημιουργούμε ελάχιστη εγγραφή μέσα στην epsilon cache (χωρίς άγγιγμα Excel)
            new_item = {
                "mark": mark,
                "χαρακτηρισμός": new_char,
                "characteristic": new_char,
                "_created_at": datetime.utcnow().isoformat() + "Z"
            }
            epsilon_list.append(new_item)

        _save_json(epsilon_path, epsilon_list)
        return jsonify({"ok": True, "updated": True, "found_existing": found}), 200

    except Exception as e:
        current_app.logger.exception("api_update_epsilon_characteristic failed")
        return jsonify({"ok": False, "error": str(e)}), 500


# ---------------- MARK search ----------------
@app.route("/search", methods=["GET", "POST"])
def search():
    result = None
    error = None
    mark = ""
    modal_summary = None
    invoice_lines = []
    customer_categories = []
    allow_edit_existing = False
    table_html = ""
    file_exists = False
    css_numcols = ""
    modal_warning = None  # νέο flag για προειδοποιητικό modal

    # ---------- helpers ----------
    def _map_invoice_type_local(code):
        INVOICE_TYPE_MAP = {
            "1.1": "Τιμολόγιο Πώλησης",
            "1.2": "Τιμολόγιο Πώλησης / Ενδοκοινοτικές Παραδόσεις",
            "1.3": "Τιμολόγιο Πώλησης / Παραδόσεις Τρίτων Χωρών",
            "1.4": "Τιμολόγιο Πώλησης / Πώληση για Λογαριασμό Τρίτων",
            "1.5": "Τιμολόγιο Πώλησης / Εκκαθάριση Πωλήσεων Τρίτων - Αμοιβή από Πωλήσεις Τρίτων",
            "1.6": "Τιμολόγιο Πώλησης / Συμπληρωματικό Παραστατικό",
            "2.1": "Τιμολόγιο Παροχής Υπηρεσιών",
            "2.2": "Τιμολόγιο Παροχής / Ενδοκοινοτική Παροχή Υπηρεσιών",
            "2.3": "Τιμολόγιο Παροχής / Παροχή Υπηρεσιών σε λήπτη Τρίτης Χώρας",
            "2.4": "Τιμολόγιο Παροχής / Συμπληρωματικό Παραστατικό",
            "3.1": "Τίτλος Κτήσης (μη υπόχρεος Εκδότης)",
            "3.2": "Τίτλος Κτήσης (άρνηση έκδοσης από υπόχρεο Εκδότη)",
            "5.1": "Πιστωτικό Τιμολόγιο / Συσχετιζόμενο",
            "5.2": "Πιστωτικό Τιμολόγιο / Μη Συσχετιζόμενο",
            "6.1": "Στοιχείο Αυτοπαράδοσης",
            "6.2": "Στοιχείο Ιδιοχρησιμοποίησης",
            "7.1": "Συμβόλαιο - Έσοδο",
            "8.1": "Ενοίκια - Έσοδο",
            "8.2": "Τέλος ανθεκτικότητας κλιματικής κρίσης",
            "8.4": "Απόδειξη Είσπραξης POS",
            "8.5": "Απόδειξη Επιστροφής POS",
            "8.6": "Δελτίο Παραγγελίας Εστίασης",
            "9.3": "Δελτίο Αποστολής",
            "11.1": "ΑΛΠ",
            "11.2": "ΑΠΥ",
            "11.3": "Απλοποιημένο Τιμολόγιο",
            "11.4": "Πιστωτικό Στοιχείο Λιανικής",
            "11.5": "Απόδειξη Λιανικής Πώλησης για Λογαριασμό Τρίτων",
            "13.1": "Έξοδα - Αγορές Λιανικών Συναλλαγών ημεδαπής / αλλοδαπής",
            "13.2": "Παροχή Λιανικών Συναλλαγών ημεδαπής / αλλοδαπής",
            "13.3": "Κοινόχρηστα",
            "13.4": "Συνδρομές",
            "13.30": "Παραστατικά Οντότητας ως Αναγράφονται από την ίδια (Δυναμικό)",
            "13.31": "Πιστωτικό Στοιχείο Λιανικής ημεδαπής / αλλοδαπής",
            "14.1": "Τιμολόγιο / Ενδοκοινοτικές Αποκτήσεις",
            "14.2": "Τιμολόγιο / Αποκτήσεις Τρίτων Χωρών",
            "14.3": "Τιμολόγιο / Ενδοκοινοτική Λήψη Υπηρεσιών",
            "14.4": "Τιμολόγιο / Λήψη Υπηρεσιών Τρίτων Χωρών",
            "14.5": "ΕΦΚΑ και λοιποί Ασφαλιστικοί Οργανισμοί",
            "14.30": "Παραστατικά Οντότητας ως Αναγράφονται από την ίδια (Δυναμικό)",
            "14.31": "Πιστωτικό ημεδαπής / αλλοδαπής",
            "15.1": "Συμβόλαιο - Έξοδο",
            "16.1": "Ενοίκιο Έξοδο",
            "17.1": "Μισθοδοσία",
            "17.2": "Αποσβέσεις",
            "17.3": "Λοιπές Εγγραφές Τακτοποίησης Εσόδων - Λογιστική Βάση",
            "17.4": "Λοιπές Εγγραφές Τακτοποίησης Εσόδων - Φορολογική Βάση",
            "17.5": "Λοιπές Εγγραφές Τακτοποίησης Εξόδων - Λογιστική Βάση",
            "17.6": "Λοιπές Εγγραφές Τακτοποίησης Εξόδων - Φορολογική Βάση",
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

    def pick(src: dict, *keys, default=""):
        for k in keys:
            if k in src and src.get(k) not in (None, ""):
                return src.get(k)
        return default

    # ---------- credentials helpers ----------
    def credentials_path():
        return os.path.join(DATA_DIR, "credentials.json")

    def read_credentials_list_local():
        try:
            p = credentials_path()
            if not os.path.exists(p):
                return []
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f) or []
        except Exception:
            log.exception("read_credentials_list_local failed")
            return []

    def write_credentials_list_local(creds_list):
        """
        Persist credentials list and ensure each credential that has a VAT gets an empty excel file.
        Returns True on success, False on failure.
        """
        try:
            p = credentials_path()
            tmp = p + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(creds_list, f, ensure_ascii=False, indent=2)
            os.replace(tmp, p)

            # ensure excel exists for each credential entry that has a VAT
            try:
                for c in (creds_list or []):
                    try:
                        if not isinstance(c, dict):
                            continue
                        vat = c.get("vat") or c.get("AFM") or c.get("tax_number") or None
                        if vat:
                        # safe: create only if missing
                            try:
                                create_empty_excel_for_vat(vat)
                            except Exception:
                                # don't fail the whole write just because excel creation failed
                                log.exception("write_credentials_list_local: failed to create excel for VAT %s", vat)
                    except Exception:
                        log.exception("write_credentials_list_local: error while ensuring excel for one credential")
            except Exception:
                log.exception("write_credentials_list_local: bulk excel ensure failed")

            return True
        except Exception:
            log.exception("write_credentials_list_local failed")
            return False


    def find_active_client_index_local(creds_list, vat_to_match=None):
        if not creds_list:
            return None
        if vat_to_match:
            for i, c in enumerate(creds_list):
                try:
                    if str(c.get("vat", "")).strip() == str(vat_to_match).strip():
                        return i
                except Exception:
                    continue
        for i, c in enumerate(creds_list):
            if c.get("active"):
                return i
        return 0

    # ---------- active credential ----------
    active_cred = get_active_credential_from_session()
    vat = active_cred.get("vat") if active_cred else None

    # --- Handle JSON AJAX request to save repeat mapping ---
    # expects JSON: {"action":"save_repeat_entry", "enabled": true/false, "mapping": {...}}
    if request.method == "POST" and request.is_json:
        data = request.get_json() or {}
        if data.get("action") == "save_repeat_entry":
            enabled = bool(data.get("enabled", False))
            mapping = data.get("mapping", {}) or {}
            # read creds, locate active client, set repeat_entry, write back
            creds = read_credentials_list_local()
            idx = find_active_client_index_local(creds, vat_to_match=vat)
            if idx is None:
                return jsonify({"ok": False, "error": "No credentials found to save."}), 400
            try:
                # ensure structure
                creds[idx]["repeat_entry"] = {"enabled": enabled, "mapping": mapping}
                ok = write_credentials_list_local(creds)
                if not ok:
                    return jsonify({"ok": False, "error": "Failed to write credentials file."}), 500
                # also update session active_cred if needed (so frontend sees the change on reload)
                # (Assuming existence of helper to refresh active credential in session; otherwise next request will read file)
                return jsonify({"ok": True})
            except Exception as e:
                log.exception("Failed saving repeat entry mapping")
                return jsonify({"ok": False, "error": str(e)}), 500

    # emulate POST: GET ?mark=...&force_edit=1
    emulate_post = False
    if request.method == "GET" and request.args.get("mark") and request.args.get("force_edit"):
        mark = request.args.get("mark", "").strip()
        emulate_post = True

    if request.method == "POST" or emulate_post:
        # If this was not JSON-save, normal form handling below
        if request.method == "POST" and not request.is_json:
            mark = request.form.get("mark", "").strip()

        import re
        from urllib.parse import urlparse
        from scraper import scrape_wedoconnect, scrape_mydatapi, scrape_einvoice, scrape_impact, scrape_epsilon

        input_is_url = re.match(r'^https?://', mark)
        if input_is_url:
            domain = urlparse(mark).netloc.lower()
            scraped_afm = None
            scraped_marks = []

            try:
                if "wedoconnect" in domain:
                    scraped_marks, scraped_afm = scrape_wedoconnect(mark)
                elif "mydatapi.aade.gr" in domain:
                    data = scrape_mydatapi(mark)
                    scraped_marks = [data.get("MARK", "N/A")]
                    scraped_afm = data.get("ΑΦΜ Πελάτη")
                elif "einvoice.s1ecos.gr" in domain:
                    scraped_marks, scraped_afm = scrape_einvoice(mark)
                elif "einvoice.impact.gr" in domain or "impact.gr" in domain:
                    scraped_marks = scrape_impact(mark)
                elif "epsilonnet.gr" in domain:
                    mark_val, scraped_afm, _ = scrape_epsilon(mark)
                    if mark_val:
                        scraped_marks = [mark_val]
                else:
                    error = "Άγνωστο URL για scraping."
            except Exception as e:
                log.exception(f"Scraping failed for URL {mark}")
                error = f"Αποτυχία ανάγνωσης URL: {str(e)}"

            # --- Έλεγχος AFM με ενεργό πελάτη ---
            if scraped_afm and vat and str(scraped_afm).strip() != str(vat).strip():
                modal_warning = f"Το URL επιστρέφει ΑΦΜ {scraped_afm}, διαφορετικό από τον ενεργό πελάτη {vat}."

            # εισαγωγή MARK που επιστράφηκε από scraper
            if scraped_marks:
                mark = scraped_marks[0]

        # --- Έλεγχος MARK αν δεν είναι URL ---
        if not input_is_url:
            if not vat:
                error = "Επέλεξε πρώτα έναν πελάτη (ΑΦΜ) για αναζήτηση."
            elif not mark or not mark.isdigit() or len(mark) != 15:
                error = "Πρέπει να δώσεις έγκυρο 15ψήφιο MARK."

        # --- συνέχεια της υπάρχουσας λογικής με cache, Excel, modal_summary ---
        if not error:
            # --- φορτώνουμε cache invoices ---
            customer_file = os.path.join(DATA_DIR, f"{vat}_invoices.json")
            try:
                cache = json_read(customer_file) or []
            except Exception:
                cache = []
            docs_for_mark = [d for d in cache if str(d.get("mark", "")).strip() == mark]

            # flag για ήδη χαρακτηρισμένα docs — δεν κάνουμε return εδώ, μόνο θα εμφανίσουμε μήνυμα
            classified_flag = False
            classified_docs = [
                d for d in docs_for_mark
                if str(d.get("classification", "")).strip().lower() == "χαρακτηρισμενο"
            ]
            if classified_docs:
                error = f"Το MARK {mark} είναι ήδη χαρακτηρισμένο στο invoices.json."
                classified_flag = True
                # δεν χτίζουμε modal_summary ούτε τα invoice_lines — αλλά αφήνουμε να εμφανιστεί ο πίνακας

            # --- Έλεγχος διπλοκαταχώρησης στο Excel για yellow box ---
            try:
                excel_path = excel_path_for(vat=vat)
                if os.path.exists(excel_path):
                    df_check = pd.read_excel(excel_path, engine="openpyxl", dtype=str).fillna("")
                    if "MARK" in df_check.columns:
                        marks_in_excel = df_check["MARK"].astype(str).str.strip().tolist()
                        if mark in marks_in_excel:
                            allow_edit_existing = True
            except Exception:
                log.exception("Could not read Excel to check duplicate MARK")

            # Αν δεν έχουμε docs για το MARK στην cache -> άλλο μήνυμα
            if not docs_for_mark:
                error = f"MARK {mark} όχι στην cache του πελάτη {vat}. Κάνε πρώτα Fetch."
            else:
                # build modal_summary unless classified_flag
                if not classified_flag:
                    invoice_lines = []
                    for idx, inst in enumerate(docs_for_mark):
                        line_id = inst.get("id") or inst.get("line_id") or inst.get("LineId") or f"{mark}_inst{idx}"
                        description = pick(inst, "description", "desc", "Description", "Name", "Name_issuer") or f"Instance #{idx+1}"
                        amount = pick(inst, "amount", "lineTotal", "totalNetValue", "totalValue", "value", default="")
                        vat_rate = pick(inst, "vat", "vatRate", "vatPercent", "totalVatAmount", default="")

                        raw_vatcat = pick(inst, "vatCategory", "vat_category", "vatClass", "vatCategoryCode", "VATCategory", "vatCat", default="")
                        mapped_vatcat = VAT_MAP.get(str(raw_vatcat).strip(), raw_vatcat) if raw_vatcat else ""

                        category = ""

                        invoice_lines.append({
                            "id": line_id,
                            "description": description,
                            "amount": amount,
                            "vat": vat_rate,
                            "category": category,
                            "vatCategory": mapped_vatcat
                        })

                    first = docs_for_mark[0]
                    total_net = sum(float_from_comma(pick(d, "totalNetValue", "totalNet", "lineTotal", default=0)) for d in docs_for_mark)
                    total_vat = sum(float_from_comma(pick(d, "totalVatAmount", "totalVat", default=0)) for d in docs_for_mark)
                    total_value = total_net + total_vat

                    NEGATIVE_TYPES = {"5.1", "5.2", "11.4"}
                    inv_type = str(pick(first, "type", "invoiceType", default="")).strip()
                    is_negative = inv_type in NEGATIVE_TYPES

                    if is_negative:
                        for ml in invoice_lines:
                            try:
                                v = float_from_comma(ml.get("amount", 0))
                                ml["amount"] = f"-{abs(v):.2f}".replace(".", ",")
                            except Exception:
                                ml["amount"] = ml.get("amount", "")
                            try:
                                vv = float_from_comma(ml.get("vat", 0))
                                ml["vat"] = f"-{abs(vv):.2f}".replace(".", ",")
                            except Exception:
                                ml["vat"] = ml.get("vat", "")
                    else:
                        for ml in invoice_lines:
                            try:
                                v = float_from_comma(ml.get("amount", 0))
                                ml["amount"] = f"{v:.2f}".replace(".", ",")
                            except Exception:
                                ml["amount"] = ml.get("amount", "")
                            try:
                                vv = float_from_comma(ml.get("vat", 0))
                                ml["vat"] = f"{vv:.2f}".replace(".", ",")
                            except Exception:
                                ml["vat"] = ml.get("vat", "")

                    if is_negative:
                        modal_summary = {
                            "mark": mark,
                            "AA": pick(first, "AA", "aa", default=""),
                            "AFM": pick(first, "AFM_issuer", "AFM_issuer", default=vat),
                            "Name": pick(first, "Name", "Name_issuer", default=""),
                            "series": pick(first, "series", "Series", "serie", default=""),
                            "number": pick(first, "number", "aa", "AA", default=""),
                            "issueDate": pick(first, "issueDate", "issue_date", default=pick(first,"issueDate","issue_date","")),
                            "totalNetValue": f"-{abs(total_net):.2f}".replace(".", ","),
                            "totalVatAmount": f"-{abs(total_vat):.2f}".replace(".", ","),
                            "totalValue": f"-{abs(total_value):.2f}".replace(".", ","),
                            "type": inv_type,
                            "type_name": mapper(inv_type),
                            "lines": invoice_lines
                        }
                    else:
                        modal_summary = {
                            "mark": mark,
                            "AA": pick(first, "AA", "aa", default=""),
                            "AFM": pick(first, "AFM_issuer", "AFM_issuer", default=vat),
                            "Name": pick(first, "Name", "Name_issuer", default=""),
                            "series": pick(first, "series", "Series", "serie", default=""),
                            "number": pick(first, "number", "aa", "AA", default=""),
                            "issueDate": pick(first, "issueDate", "issue_date", default=pick(first,"issueDate","issue_date","")),
                            "totalNetValue": f"{total_net:.2f}".replace(".", ","),
                            "totalVatAmount": f"{total_vat:.2f}".replace(".", ","),
                            "totalValue": f"{total_value:.2f}".replace(".", ","),
                            "type": inv_type,
                            "type_name": mapper(inv_type),
                            "lines": invoice_lines
                        }

                    # Εισαγωγή προφόρτωσης χαρακτηρισμού από epsilon cache (όπως πριν)
                                        # Εισαγωγή προφόρτωσης χαρακτηρισμού από epsilon cache (όπως πριν)
                    try:
                        epsilon_path = os.path.join(DATA_DIR, "epsilon", f"{vat}_epsilon_invoices.json")
                        # read existing epsilon cache safely
                        eps_list = json_read(epsilon_path, default=[]) or []

                        # If there is no epsilon cache yet, *do not* blindly build full cache from invoices.json.
                        # Instead: build and persist only a per-mark detailed entry (if we have details for this mark).
                        if not eps_list:
                            try:
                                # Only build an epsilon entry for the current mark if modal_summary has meaningful data
                                # modal_summary was created above and invoice_lines contains per-line items
                                has_detail = False
                                # prefer issueDate OR non-empty lines OR AFM issuer info
                                if modal_summary and (modal_summary.get("issueDate") or modal_summary.get("AFM") or modal_summary.get("AFM_issuer")):
                                    has_detail = True
                                if invoice_lines and any((ln.get("description") or ln.get("amount") or ln.get("vat")) for ln in invoice_lines):
                                    has_detail = True

                                if has_detail and modal_summary:
                                    # construct epsilon-format entry from modal_summary + invoice_lines
                                    epsilon_entry = {
                                        "mark": str(modal_summary.get("mark", "")).strip(),
                                        "issueDate": modal_summary.get("issueDate", "") or "",
                                        "series": modal_summary.get("series", "") or "",
                                        "aa": modal_summary.get("number", "") or modal_summary.get("AA", ""),
                                        "AA": modal_summary.get("number", "") or modal_summary.get("AA", ""),
                                        "type": modal_summary.get("type", "") or "",
                                        "vatCategory": modal_summary.get("vatCategory", "") or "",
                                        "totalNetValue": modal_summary.get("totalNetValue", "") or "",
                                        "totalVatAmount": modal_summary.get("totalVatAmount", "") or "",
                                        "totalValue": modal_summary.get("totalValue", "") or "",
                                        "classification": modal_summary.get("classification", "") or "",
                                        "χαρακτηρισμός": modal_summary.get("χαρακτηρισμός", "") or modal_summary.get("characteristic", "") or "",
                                        "characteristic": modal_summary.get("χαρακτηρισμός", "") or modal_summary.get("characteristic", "") or "",
                                        "AFM_issuer": modal_summary.get("AFM_issuer", "") or modal_summary.get("AFM", "") or "",
                                        "Name_issuer": modal_summary.get("Name", "") or modal_summary.get("Name_issuer", "") or "",
                                        "AFM": modal_summary.get("AFM", "") or vat,
                                        "lines": []
                                    }
                                    # normalize lines into epsilon shape (vat_category key)
                                    for ln in invoice_lines:
                                        epsilon_entry["lines"].append({
                                            "id": ln.get("id", ""),
                                            "description": ln.get("description", ""),
                                            "amount": ln.get("amount", ""),
                                            "vat": ln.get("vat", ""),
                                            "category": ln.get("category", "") or "",
                                            "vat_category": ln.get("vatCategory", "") or ""
                                        })
                                    # append to eps_list and persist atomically (use your safe writer)
                                    eps_list.append(epsilon_entry)
                                    try:
                                        _safe_save_epsilon_cache(vat, eps_list)
                                        log.info("Built per-mark epsilon entry for mark %s (vat %s)", epsilon_entry.get("mark"), vat)
                                    except Exception:
                                        log.exception("Failed to save newly built per-mark epsilon entry")
                                else:
                                    # nothing to build: keep eps_list empty (do not create placeholder entries)
                                    pass
                            except Exception:
                                log.exception("Failed building per-mark epsilon entry")
                                # fallthrough: eps_list may still be empty
                        # now attempt to match an existing epsilon entry for the mark (if any)
                        def match_epsilon_item(item, mark_val):
                            for k in ('mark','MARK','invoice_id','Αριθμός Μητρώου','id'):
                                if k in item and str(item[k]).strip() == str(mark_val).strip():
                                    return True
                            return False
                        matched = None
                        for it in (eps_list or []):
                            try:
                                if match_epsilon_item(it, mark):
                                    matched = it
                                    break
                            except Exception:
                                continue
                        if matched:
                            modal_summary['χαρακτηρισμός'] = matched.get('χαρακτηρισμός') or matched.get('characteristic') or modal_summary.get('χαρακτηρισμός','') or ""
                            try:
                                eps_lines = matched.get("lines", []) or []
                                eps_by_id = { str(l.get("id","")): l for l in eps_lines if l.get("id") is not None }
                                for ml in modal_summary.get("lines", []):
                                    lid = str(ml.get("id",""))
                                    if not lid:
                                        continue
                                    eps_line = eps_by_id.get(lid)
                                    if eps_line:
                                        if not ml.get("category") and eps_line.get("category"):
                                            ml["category"] = eps_line.get("category")
                                        if (not ml.get("vatCategory") or ml.get("vatCategory")== "") and eps_line.get("vat_category"):
                                            ml["vatCategory"] = eps_line.get("vat_category")
                            except Exception:
                                log.exception("Failed to merge per-line categories from epsilon")
                    except Exception:
                        log.exception("Could not read epsilon cache for prefill")


                    raw_tags = active_cred.get("expense_tags") or []
                    if isinstance(raw_tags, str):
                        customer_categories = [t.strip() for t in raw_tags.split(",") if t.strip()]
                    elif isinstance(raw_tags, list):
                        customer_categories = raw_tags
                    if not customer_categories:
                        customer_categories = [
                            "αγορες_εμπορευματων",
                            "αγορες_α_υλων",
                            "γενικες_δαπανες",
                            "αμοιβες_τριτων",
                            "δαπανες_χωρις_φπα"
                        ]
                else:
                    modal_summary = None
                    invoice_lines = []
                    customer_categories = []

    # ---------- Read credentials to extract repeat_entry config to pass to template ----------
    repeat_entry_conf = {}
    try:
        creds_list = read_credentials_list_local()
        idx = find_active_client_index_local(creds_list, vat_to_match=vat)
        if idx is not None and idx < len(creds_list):
            repeat_entry_conf = creds_list[idx].get("repeat_entry", {}) or {}
    except Exception:
        log.exception("Could not read repeat_entry config from credentials")

    # --- Build table_html same way as /list ---
    try:
        active = get_active_credential_from_session()
        excel_path = DEFAULT_EXCEL_FILE
        if active and active.get("vat"):
            excel_path = excel_path_for(vat=active.get("vat"))
        elif active and active.get("name"):
            excel_path = excel_path_for(cred_name=active.get("name"))
        if os.path.exists(excel_path):
            file_exists = True
            df = pd.read_excel(excel_path, engine="openpyxl", dtype=str).fillna("")
            df = df.astype(str)
            if "ΦΠΑ_ΑΝΑΛΥΣΗ" in df.columns:
                df = df.drop(columns=["ΦΠΑ_ΑΝΑΛΥΣΗ"])
            # insert checkbox column as first column
            checkbox_html = '<input type="checkbox" name="delete_mark" />'
            df.insert(0, "✓", [checkbox_html] * len(df))
            table_html = df.to_html(classes="summary-table", index=False, escape=False)
        else:
            file_exists = False
            table_html = ""
    except Exception:
        log.exception("Failed building table_html for search page")
        table_html = ""

    # Επιστρέφουμε πάντα το vat και όλα τα context vars, μαζί με repeat_entry_conf
    return safe_render(
        "search.html",
        result=result,
        error=error,
        mark=mark,
        modal_summary=modal_summary,
        invoice_lines=invoice_lines,
        customer_categories=customer_categories,
        allow_edit_existing=allow_edit_existing,
        vat=vat,
        active_page="search",
        table_html=table_html,
        file_exists=file_exists,
        css_numcols=css_numcols,
        modal_warning=modal_warning,
        # για frontend repeat modal
        repeat_entry_conf=repeat_entry_conf
    )


@app.route('/api/scrape_receipt', methods=['POST'])
def api_scrape_receipt():
    """
    POST JSON { "url": "<url>" }
    Καλεί το module scraper_receipt και επιστρέφει standardized JSON.
    Αν το αποτέλεσμα είναι ΑΠΟΔΕΙΞΗ (δηλ. όχι τιμολόγιο) αποθηκεύει και σε epsilon_invoices.json
    και επιστρέφει το JSON προς το frontend.
    """
    try:
        payload = request.get_json(silent=True) or {}
        url = payload.get('url') or request.form.get('url') or ''
        url = (url or '').strip()
        if not url:
            return jsonify(ok=False, error='no url provided'), 400

        # import scraper_receipt
        try:
            mod = importlib.import_module('scraper_receipt')
        except Exception as e:
            return jsonify(ok=False, error=f'cannot import scraper_receipt: {e}'), 500

        # πιθανά ονόματα συνάρτησης που μπορεί να έχει το module
        candidate_fn_names = [
            'scrape_receipt', 'scrape', 'extract_receipt', 'extract', 'scrape_url',
            'scrape_receipt_url', 'detect_and_scrape'
        ]
        fn = None
        for n in candidate_fn_names:
            if hasattr(mod, n):
                fn = getattr(mod, n)
                break

        if fn is None:
            return jsonify(ok=False, error='no scraping function found in scraper_receipt module'), 500

        # προσπάθησε να τρέξεις την συνάρτηση με διάφορα signatures
        result = None
        try:
            result = fn(url)
        except TypeError:
            try:
                result = fn(url, timeout=15)
            except Exception as ee:
                return jsonify(ok=False, error=f'scraper function raised: {ee}'), 500
        except Exception as e:
            return jsonify(ok=False, error=f'scraper function raised: {e}'), 500

        if not isinstance(result, dict):
            return jsonify(ok=False, error='scraper returned non-dict result'), 500

        # normalize fields
        r = result
        is_invoice = bool(r.get('is_invoice') or r.get('invoice', False))
        doc_type_val = str(r.get('doc_type') or r.get('type') or r.get('type_name') or '')
        if not is_invoice and re.search(r"τιμολό?γιο|τιμολογιο|invoice", doc_type_val, flags=re.I):
            is_invoice = True

        out = {
            'ok': True,
            'is_invoice': bool(is_invoice),
            'issuer_vat': r.get('issuer_vat') or r.get('AFM') or r.get('vat') or None,
            'issuer_name': r.get('issuer_name') or r.get('Name') or r.get('company') or None,
            'issue_date': r.get('issue_date') or r.get('issueDate') or r.get('date') or None,
            'progressive_aa': r.get('progressive_aa') or r.get('AA') or r.get('id') or None,
            'total_amount': r.get('total_amount') or r.get('totalValue') or r.get('total') or None,
            'MARK': r.get('MARK') or None,
            'raw': r
        }

        # αν είναι τιμολόγιο -> ενημέρωση frontend και σταματάμε
        if out['is_invoice']:
            return jsonify(ok=True, is_invoice=True, message='Detected invoice'), 200

        # ---------- ΑΠΟΘΗΚΕΥΣΗ ΑΠΟΔΕΙΞΗΣ ----------
        # Αποθήκευση σε epsilon_invoices.json (append)
        try:
            json_path = EPSILON_JSON_PATH
            lock_path = json_path + '.lock'
            lock = FileLock(lock_path, timeout=10)
            with lock:
                # αν δεν υπάρχει αρχείο, φτιάξτο με λίστα
                if not os.path.exists(json_path):
                    with open(json_path, 'w', encoding='utf-8') as f:
                        json.dump([], f, ensure_ascii=False, indent=2)
                # διάβασε, πρόσθεσε και γράψε
                with open(json_path, 'r+', encoding='utf-8') as f:
                    try:
                        data = json.load(f)
                        if not isinstance(data, list):
                            data = []
                    except Exception:
                        data = []
                    # συμπλήρωμα με όσα έχουμε στο out
                    entry = {
                        'url': url,
                        'saved_at': datetime.utcnow().isoformat() + 'Z',
                        'issuer_vat': out['issuer_vat'],
                        'issuer_name': out['issuer_name'],
                        'issue_date': out['issue_date'],
                        'progressive_aa': out['progressive_aa'],
                        'total_amount': out['total_amount'],
                        'MARK': out['MARK'],
                        'raw': out['raw']
                    }
                    data.append(entry)
                    f.seek(0)
                    json.dump(data, f, ensure_ascii=False, indent=2)
                    f.truncate()
        except Exception as e:
            # δεν αποτυγχάνουμε ολόκληρο request λόγω αποτυχίας αποθήκευσης — log μόνο
            try:
                current_app.logger.exception("failed saving receipt to epsilon json: %s", e)
            except Exception:
                pass

        # TODO: αποθήκευση και σε Excel (EXCEL_PATH) — αν θέλεις, μπορώ να σου δώσω snippet με openpyxl/pandas + filelock
        # για να κρατάμε τον ίδιο χώρο αποθήκευσης με τα τιμολόγια. Κάνε μου know αν το θέλεις.

        return jsonify(out), 200

    except Exception as e:
        return jsonify(ok=False, error=str(e)), 500


@app.route("/save_epsilon", methods=["POST"])
def save_epsilon():
    """
    Παρέχεται για απευθείας αποθήκευση epsilon (αν θέλεις ξεχωριστό κουμπί).
    Αναμένει form field "summary_json" (όπως το modal στέλνει) και αποθηκεύει
    το αντικείμενο στο per-vat epsilon file (data/epsilon/{vat}_epsilon_invoices.json).
    """
    active_cred = get_active_credential_from_session()
    if not active_cred:
        flash("Δεν υπάρχει ενεργός πελάτης για αποθήκευση.", "error")
        return redirect(url_for("search"))

    vat = active_cred.get("vat")
    if not vat:
        flash("Δεν βρέθηκε ΑΦΜ πελάτη.", "error")
        return redirect(url_for("search"))

    summary_json = request.form.get("summary_json")
    if not summary_json:
        flash("Δεν στάλθηκε δεδομένο για αποθήκευση.", "error")
        return redirect(url_for("search"))

    try:
        summary_data = json.loads(summary_json)
    except Exception as e:
        flash(f"Σφάλμα κατά την ανάγνωση του JSON: {e}", "error")
        return redirect(url_for("search"))

    # load existing epsilon cache and update per MARK
    epsilon_cache = load_epsilon_cache_for_vat(vat)

    mark = str(summary_data.get("mark", ""))
    existing_index = next((i for i, d in enumerate(epsilon_cache) if str(d.get("mark","")) == mark), None)
    if existing_index is not None:
        epsilon_cache[existing_index] = summary_data
    else:
        epsilon_cache.append(summary_data)

    # Save to disk
    try:
        save_epsilon_cache_for_vat(vat, epsilon_cache)
    except Exception:
        flash("Αποτυχία αποθήκευσης Epsilon αρχείου.", "error")
        return redirect(url_for("search"))

    flash(f"Το παραστατικό MARK {mark} αποθηκεύτηκε για Epsilon Excel.", "success")
    return redirect(url_for("search"))


@app.route("/save_accounts", methods=["POST"])
def save_accounts():
    """
    Αναμένει POST με πεδία:
      - account_<vat>__<expense_tag> = account_code
    Παράδειγμα πεδίου: account_24__γενικες_δαπανες = "70.02"
    Επιπλέον μπορεί να στέλνεται JSON payload.
    """
    try:
        # αν JSON payload
        if request.is_json:
            payload = request.get_json()
            accounts = payload.get("accounts", {})
            save_global_accounts_to_credentials(accounts)
            flash("Global accounts saved", "success")
            return redirect(url_for("credentials"))
        # αλλιώς form fields
        form = request.form
        # Δομή: accounts[vat][expense_tag] = code
        accounts = {}
        # αναζητούμε πεδία που ξεκινούν με "account_"
        for key in form:
            if not key.startswith("account_"):
                continue
            # key format: account_{vat}__{expense_tag}
            rest = key[len("account_"):]
            if "__" not in rest:
                continue
            vat_part, expense_tag = rest.split("__", 1)
            vat_key = vat_part.strip()
            code = form.get(key, "").strip()
            if vat_key not in accounts:
                accounts[vat_key] = {}
            accounts[vat_key][expense_tag] = code
        # αποθηκεύουμε
        save_global_accounts_to_credentials(accounts)
        flash("Global accounts saved", "success")
    except Exception as e:
        log.exception("save_accounts failed")
        flash(f"Could not save accounts: {e}", "error")
    return redirect(url_for("credentials"))

# ---------------- Save summary from modal to Excel & per-customer JSON ----------------
@app.route("/save_summary", methods=["POST"])
def save_summary():
    """
    Save summary and update epsilon:
      - αν υπάρχει ήδη detailed εγγραφή στο epsilon για το mark -> update-only per-line
      - αν υπάρχει μόνο placeholder για το mark -> ΔΙΑΓΡΑΦΟΥΜΕ τα placeholders και ΠΙΕΖΟΥΜΕ δημιουργία Excel + append
      - αλλιώς -> γράφει Excel και προσθέτει πλήρη εγγραφή στο epsilon
    Έχει εκτενή debug logging για να δούμε ακριβώς τι συμβαίνει.
    """
    try:
        log.info("save_summary: start request from %s", request.remote_addr)
        raw = request.form.get("summary_json") or request.get_data(as_text=True)
        if not raw:
            flash("No summary provided", "error")
            log.warning("save_summary: no payload")
            return redirect(url_for("search"))
        try:
            summary = json.loads(raw)
            log.debug("save_summary: parsed JSON summary keys: %s", list(summary.keys()))
        except Exception:
            # fallback: try building minimal summary from form
            log.warning("save_summary: failed json.loads(payload) - building minimal from form")
            summary = {}
            if request.form.get("mark"):
                summary["mark"] = request.form.get("mark")
                summary["AFM"] = request.form.get("vat") or request.form.get("AFM") or ""
    except Exception:
        log.exception("save_summary: cannot parse payload")
        flash("Invalid summary payload", "error")
        return redirect(url_for("search"))

    active = get_active_credential_from_session()
    vat = (active.get("vat") if active else None) or summary.get("AFM") or summary.get("AFM_issuer") or summary.get("AFM")
    if not vat:
        flash("No active customer selected (VAT)", "error")
        log.error("save_summary: missing vat - active=%s summary_afm=%s", bool(active), summary.get("AFM"))
        return redirect(url_for("search"))

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

    # ensure lines
    lines = summary.get("lines", []) or []
    if not lines:
        try:
            mark = str(summary.get("mark", "")).strip()
            docs_file = os.path.join(DATA_DIR, f"{vat}_invoices.json")
            all_docs = json_read(docs_file) or []
            docs_for_mark = [d for d in all_docs if str(d.get("mark","")).strip() == mark]
            reconstructed = []
            for idx, inst in enumerate(docs_for_mark):
                ln_id = inst.get("id") or inst.get("line_id") or inst.get("LineId") or f"{mark}_inst{idx}"
                description = inst.get("description") or inst.get("desc") or inst.get("Description") or inst.get("Name") or inst.get("Name_issuer") or f"Instance #{idx+1}"
                amount = inst.get("amount") or inst.get("lineTotal") or inst.get("totalNetValue") or inst.get("totalValue") or ""
                vat_rate = inst.get("vat") or inst.get("vatRate") or inst.get("vatPercent") or inst.get("totalVatAmount") or ""
                raw_vatcat = inst.get("vatCategory") or inst.get("vat_category") or inst.get("VATCategory") or inst.get("vatCat") or ""
                if not raw_vatcat:
                    raw_vatcat = inst.get("vatCategoryCode") or inst.get("vat_code") or ""
                vat_cat_mapped = VAT_MAP.get(str(raw_vatcat).strip(), raw_vatcat) if raw_vatcat else ""
                reconstructed.append({
                    "id": ln_id,
                    "description": description,
                    "amount": amount,
                    "vat": vat_rate,
                    "category": "",
                    "vatCategory": vat_cat_mapped
                })
            lines = reconstructed
            log.debug("save_summary: reconstructed %d lines from %s", len(lines), docs_file)
        except Exception:
            log.exception("save_summary: failed to reconstruct lines")
            lines = []

    # normalize lines
    normalized_lines = []
    for idx, ln in enumerate(lines):
        if not isinstance(ln, dict):
            continue
        ln_id = ln.get("id") or f"{summary.get('mark','')}_l{idx}"
        raw_vcat = ln.get("vatCategory") or ln.get("vat_category") or ln.get("vatCat") or ln.get("vat_cat") or ""
        vcat_mapped = VAT_MAP.get(str(raw_vcat).strip(), raw_vcat) if raw_vcat else ""
        normalized_lines.append({
            "id": ln_id,
            "description": ln.get("description","") or ln.get("desc","") or "",
            "amount": ln.get("amount","") or ln.get("lineTotal","") or "",
            "vat": ln.get("vat","") or ln.get("vatRate","") or "",
            "category": ln.get("category","") or "",
            "vatCategory": vcat_mapped
        })
    summary["lines"] = normalized_lines

    # append to per-customer summary JSON (best-effort)
    try:
        append_summary_to_customer_file(summary, vat)
    except Exception:
        log.exception("save_summary: append_summary_to_customer_file failed")

    # helper to detect placeholder/detailed epsilon item
    def epsilon_item_has_detail(item):
        try:
            if not item or not isinstance(item, dict):
                return False
            if item.get("issueDate"):
                return True
            if item.get("totalNetValue") or item.get("totalValue"):
                return True
            lines_local = item.get("lines") or []
            if isinstance(lines_local, list):
                for l in lines_local:
                    if l and (l.get("description") or l.get("amount") or l.get("vat")):
                        return True
            if item.get("AFM_issuer") or item.get("AFM"):
                if item.get("aa") or item.get("AA") or item.get("issueDate") or item.get("totalValue"):
                    return True
        except Exception:
            pass
        return False

    # load epsilon cache for vat
    try:
        epsilon_cache = load_epsilon_cache_for_vat(vat)  # returns list or None
        if epsilon_cache is None:
            epsilon_cache = []
        log.debug("save_summary: loaded epsilon_cache len=%d for vat=%s", len(epsilon_cache), vat)
    except Exception:
        log.exception("save_summary: failed loading epsilon cache")
        epsilon_cache = []

    mark = str(summary.get("mark","")).strip()

    # find existing detailed entry, but collect placeholders
    existing_index = None
    placeholder_indices = []
    try:
        for i, d in enumerate(epsilon_cache):
            try:
                d_mark = d.get("mark") or d.get("MARK") or d.get("invoice_id") or d.get("Αριθμός Μητρώου") or d.get("id")
                if d_mark is None or str(d_mark).strip() != mark:
                    continue
                if not epsilon_item_has_detail(d):
                    placeholder_indices.append(i)
                    log.debug("save_summary: found placeholder at idx=%d keys=%s", i, list(d.keys())[:6])
                    continue
                existing_index = i
                log.debug("save_summary: found detailed entry at idx=%d", i)
                break
            except Exception:
                log.exception("save_summary: error scanning epsilon_cache index %s", i)
                continue
    except Exception:
        log.exception("save_summary: scanning epsilon_cache failed unexpectedly")

    # if placeholders exist, remove them (so we will create excel)
    if placeholder_indices:
        try:
            for idx in sorted(placeholder_indices, reverse=True):
                try:
                    removed = epsilon_cache.pop(idx)
                    log.info("save_summary: removed placeholder epsilon entry idx=%d mark=%s vat=%s keys=%s", idx, mark, vat, list(removed.keys())[:6])
                except Exception:
                    log.exception("save_summary: failed to pop placeholder idx=%s", idx)
            # persist truncated cache
            try:
                _safe_save_epsilon_cache(vat, epsilon_cache)
                log.info("save_summary: persisted epsilon cache after removing placeholders for vat=%s", vat)
            except Exception:
                log.exception("save_summary: failed persisting epsilon cache after placeholder removal")
            # ensure existing_index treated as None so we proceed to Excel write
            existing_index = None
        except Exception:
            log.exception("save_summary: error removing placeholders")

    # if existing detailed entry found -> updated-only path
    if existing_index is not None:
        try:
            existing = epsilon_cache[existing_index]
            existing_lines = existing.get("lines", []) or []
            existing_by_id = { str(l.get("id","")): l for l in existing_lines if l.get("id") is not None }
            updated = False
            for ln in normalized_lines:
                lid = str(ln.get("id",""))
                if not lid:
                    continue
                if lid in existing_by_id:
                    el = existing_by_id[lid]
                    new_cat = ln.get("category","") or ""
                    if new_cat and str(el.get("category","")) != new_cat:
                        el["category"] = new_cat
                        el["vat_category"] = ln.get("vatCategory","") or el.get("vat_category","")
                        updated = True
                    elif ln.get("vatCategory") and str(el.get("vat_category","")) != ln.get("vatCategory"):
                        el["vat_category"] = ln.get("vatCategory")
                        updated = True
                else:
                    new_el = {
                        "id": lid,
                        "description": ln.get("description",""),
                        "amount": ln.get("amount",""),
                        "vat": ln.get("vat",""),
                        "category": ln.get("category","") or "",
                        "vat_category": ln.get("vatCategory","") or ""
                    }
                    existing_lines.append(new_el)
                    existing_by_id[lid] = new_el
                    updated = True
            if updated:
                existing["_updated_at"] = _dt.now(timezone.utc).isoformat()
                existing["lines"] = existing_lines
                epsilon_cache[existing_index] = existing
                try:
                    _safe_save_epsilon_cache(vat, epsilon_cache)
                    log.info("save_summary: updated epsilon per-line categories for mark=%s vat=%s", mark, vat)
                    flash("Ενημερώθηκε ο χαρακτηρισμός στο cache (epsilon).", "success")
                except Exception:
                    log.exception("save_summary: failed saving epsilon cache after update")
                    flash("Failed updating epsilon cache (see server logs)", "error")
                return redirect(url_for("search"))
            else:
                log.info("save_summary: no per-line changes for mark=%s vat=%s", mark, vat)
                flash("Δεν υπήρξε αλλαγή στις κατηγορίες.", "info")
                return redirect(url_for("search"))
        except Exception:
            log.exception("save_summary: error processing existing detailed epsilon entry")
            flash("Server error while processing update", "error")
            return redirect(url_for("search"))

    # ELSE -> No existing detailed entry => we must write Excel + append new epsilon entry
    excel_path = excel_path_for(vat=vat)
    try:
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
            "Καθαρή Αξία": f"{total_net:.2f}".replace(".", ","),
            "ΦΠΑ": f"{total_vat:.2f}".replace(".", ","),
            "Σύνολο": f"{total_value:.2f}".replace(".", ",")
        }

        df_new = pd.DataFrame([row]).astype(str).fillna("")
        if os.path.exists(excel_path):
            df_existing = pd.read_excel(excel_path, engine="openpyxl", dtype=str).fillna("")
            df_concat = pd.concat([df_existing, df_new], ignore_index=True, sort=False)
            df_concat.to_excel(excel_path, index=False, engine="openpyxl")
            log.info("save_summary: appended row to existing excel %s", excel_path)
        else:
            os.makedirs(os.path.dirname(excel_path) or ".", exist_ok=True)
            df_new.to_excel(excel_path, index=False, engine="openpyxl")
            log.info("save_summary: created new excel and wrote row %s", excel_path)
        flash("Saved to Excel.", "success")
    except Exception:
        log.exception("save_summary: Excel write failed")
        flash("Excel save failed", "error")

    # build epsilon entry and append
    try:
        epsilon_entry = {
            "mark": mark,
            "issueDate": summary.get("issueDate",""),
            "series": summary.get("series",""),
            "aa": summary.get("number","") or summary.get("AA","") or summary.get("aa",""),
            "AA": summary.get("number","") or summary.get("AA","") or summary.get("aa",""),
            "type": summary.get("type",""),
            "vatCategory": summary.get("vatCategory",""),
            "totalNetValue": summary.get("totalNetValue",""),
            "totalVatAmount": summary.get("totalVatAmount",""),
            "totalValue": summary.get("totalValue",""),
            "classification": summary.get("classification",""),
            "χαρακτηρισμός": summary.get("χαρακτηρισμός") or summary.get("characteristic") or "",
            "characteristic": summary.get("χαρακτηρισμός") or summary.get("characteristic") or "",
            "AFM_issuer": summary.get("AFM_issuer","") or summary.get("AFM",""),
            "Name_issuer": summary.get("Name_issuer","") or summary.get("Name",""),
            "AFM": summary.get("AFM","") or vat,
            "lines": []
        }
        for ln in normalized_lines:
            epsilon_entry["lines"].append({
                "id": ln.get("id",""),
                "description": ln.get("description",""),
                "amount": ln.get("amount",""),
                "vat": ln.get("vat",""),
                "category": ln.get("category","") or "",
                "vat_category": ln.get("vatCategory","") or ""
            })

        epsilon_cache.append(epsilon_entry)
        try:
            _safe_save_epsilon_cache(vat, epsilon_cache)
            log.info("save_summary: appended new epsilon entry for mark=%s vat=%s", mark, vat)
            flash("Saved summary and appended new epsilon entry.", "success")
        except Exception:
            log.exception("save_summary: failed saving new epsilon cache")
            flash("Failed updating epsilon cache (see server logs)", "error")
    except Exception:
        log.exception("save_summary: failed building/appending epsilon entry")
        flash("Failed updating epsilon cache", "error")

    return redirect(url_for("search"))



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
    # collect and normalize marks
    marks_to_delete = request.form.getlist("delete_mark")
    marks_to_delete = [str(m).strip() for m in marks_to_delete if str(m).strip()]

    if not marks_to_delete:
        flash("No marks selected", "error")
        return redirect(url_for("list_invoices"))

    # determine active client's excel file
    active = get_active_credential_from_session()
    excel_path = DEFAULT_EXCEL_FILE
    if active and active.get("vat"):
        excel_path = excel_path_for(vat=active.get("vat"))
    elif active and active.get("name"):
        excel_path = excel_path_for(cred_name=active.get("name"))

    deleted_from_excel = 0
    try:
        if os.path.exists(excel_path):
            df = pd.read_excel(excel_path, engine="openpyxl", dtype=str).fillna("")
            if "MARK" in df.columns:
                marks_series = df["MARK"].astype(str).str.strip()
                mask = marks_series.isin(marks_to_delete)
                num_matches = int(mask.sum())
                if num_matches > 0:
                    df_remaining = df[~mask].copy()
                    # Write back even αν df_remaining είναι κενό
                    df_remaining.to_excel(excel_path, index=False, engine="openpyxl")
                    deleted_from_excel = num_matches
                    log.info("Deleted %d marks from Excel %s: %s", num_matches, excel_path, marks_to_delete)
                else:
                    log.info("No matching MARKs found in Excel %s for deletion: %s", excel_path, marks_to_delete)
            else:
                log.warning("Excel file %s does not contain a MARK column; skipping Excel deletion.", excel_path)
        else:
            log.info("Excel path %s does not exist; skipping Excel deletion.", excel_path)
    except Exception:
        log.exception("Error while deleting from Excel")

    # delete matching entries from per-VAT epsilon cache
    deleted_from_epsilon = 0
    try:
        vat = active.get("vat") if active else None
        if vat:
            epsilon_path = epsilon_file_path_for(vat)
            if os.path.exists(epsilon_path):
                epsilon_cache = json_read(epsilon_path) or []
                before_len = len(epsilon_cache)
                new_cache = [e for e in epsilon_cache if str(e.get("mark", "")).strip() not in marks_to_delete]
                after_len = len(new_cache)
                deleted_from_epsilon = before_len - after_len
                if deleted_from_epsilon > 0:
                    json_write(epsilon_path, new_cache)
                    log.info("Deleted %d marks from epsilon cache %s for VAT %s", deleted_from_epsilon, epsilon_path, vat)
                else:
                    log.info("No matching marks found in epsilon cache %s for deletion.", epsilon_path)
            else:
                log.info("Epsilon cache %s does not exist for VAT %s; skipping epsilon deletion.", epsilon_file_path_for(vat), vat)
        else:
            log.info("No active VAT available; skipped epsilon deletion.")
    except Exception:
        log.exception("Error while deleting from epsilon cache")

    flash(f"Deleted {len(marks_to_delete)} selected mark(s). Removed from Excel: {deleted_from_excel}, from Epsilon cache: {deleted_from_epsilon}", "success")
    return redirect(url_for("search"))







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