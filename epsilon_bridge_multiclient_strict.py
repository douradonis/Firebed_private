# -*- coding: utf-8 -*-
"""
epsilon_bridge_multiclient_strict.py
------------------------------------
Multi-client STRICT builder + preview helpers for Epsilon FastImport 'ΚΙΝΗΣΕΙΣ'.

- Διαβάζει δυναμικά per-VAT τα invoices (data/epsilon/{VAT}_epsilon_invoices.json).
- Διαβάζει το ΜΟΝΑΔΙΚΟ sheet του client_db (όποιο όνομα κι αν έχει), εντοπίζει header row,
  καθαρίζει/ομαλοποιεί, και φτιάχνει map AFM->CUSTID (+ set με όλα τα CUSTID, + name map).
- Στο preview επιστρέφει πίνακα με CUSTID και LCODE_DETAIL ανά γραμμή (και σύνοψη per invoice).
- Export σε Excel είναι STRICT: καμία κενή τιμή σε καμία στήλη.

Drop-in στο root του project. Οι βασικές public συναρτήσεις είναι:
- build_preview_rows_for_ui(...)
- export_multiclient_strict(...)
- run_and_report_dynamic(...)
"""
from __future__ import annotations

import os
import re
import json
import copy
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd


# ---------------------------------------------------------------------------
# Small utils
# ---------------------------------------------------------------------------
def _account_detail_receipt(settings_for_vat: dict, vat_rate: int | None) -> str:
    vr = str(vat_rate if vat_rate is not None else 0)
    # 1) ειδικό ανά συντελεστή
    key = f"account_αποδειξακια_{vr}"
    if str(settings_for_vat.get(key, "")).strip():
        return str(settings_for_vat[key]).strip()
    # 2) γενικό για αποδειξάκια
    if str(settings_for_vat.get("account_αποδειξακια_0", "")).strip():
        return str(settings_for_vat["account_αποδειξακια_0"]).strip()
    # 3) ασφαλές default
    return "62-00.00"

def _account_detail_invoice(settings_for_vat: dict, category: str, vat_rate: int | None) -> str:
    canon = _canon_category(category)
    vr = str(vat_rate if vat_rate is not None else 0)

    # 1) flat keys τύπου account_<canon>_<vr>
    flat_key = f"account_{canon}_{vr}"
    if str(settings_for_vat.get(flat_key, "")).strip():
        return str(settings_for_vat[flat_key]).strip()

    # 2) nested mapping (accounts_by_vat / account_map_by_vat)
    abv = settings_for_vat.get("accounts_by_vat") or settings_for_vat.get("account_map_by_vat")
    if isinstance(abv, dict):
        node = abv.get(canon)
        if isinstance(node, dict):
            v = node.get(vr)
            if str(v or "").strip():
                return str(v).strip()

    # 3) λογικός fallback ανά ομάδα
    if "αγορες_εμπορευματων" in canon:
        return "20-1000"
    if "αγορες_α_υλων" in canon:
        return "24-0000"
    if "δαπανες_χωρις_φπα" in canon:
        return "62-98.00"
    # γενικές δαπάνες
    return "62-00.00"
def _account_header_P(settings_for_vat: dict, is_receipt: bool) -> str:
    """
    Στήλη P (LCODE):
    - Από credentials_settings: account_supplier_retail / account_supplier_wholesale
    - Με ασφαλή defaults αν λείπουν (50-1000 / 50-0000)
    """
    retail  = (settings_for_vat.get("account_supplier_retail") or "50-1000").strip()
    whole   = (settings_for_vat.get("account_supplier_wholesale") or "50-0000").strip()
    return retail if is_receipt else whole

def _digits(s: Any) -> str:
    """Κράτα μόνο ψηφία."""
    return re.sub(r"\D", "", str(s or ""))

def _norm_afm(s: Any) -> str:
    """
    Κανονικοποίηση ΑΦΜ: μόνο ψηφία, drop leading zeros όπου έχει νόημα.
    Χρησιμοποιείται για matching με client_db.
    """
    d = _digits(s)
    # μη σβήσεις όλα τα μηδενικά αν είναι π.χ. '000000000' (ειδικοί κωδικοί)
    return d.lstrip("0") or d


def _safe_json_read(path: str, default=None):
    """
    Ασφαλές json.load: αν δεν βρεθεί/δεν διαβάζεται το αρχείο,
    επιστρέφει το default (λίστα/λεξικό) αντί για exception.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        # Αν default=None, γύρνα κενό dict για να μην σκάει downstream
        return {} if default is None else default


def _reason_for_rec(rec: Dict[str, Any], is_receipt: bool) -> str:
    """
    Τίτλος/αιτιολογία που δεν μένει κενή.
    - Αποδείξεις: «<Όνομα> (<ΑΦΜ>)» ή «Απόδειξη <AA>»
    - Τιμολόγια:  πεδίο reason/ΑΙΤΙΟΛΟΓΙΑ ή «Τιμολόγιο <AA>»
    """
    name = (rec.get("Name_issuer") or rec.get("issuerName") or
            rec.get("issuer_name") or rec.get("Name") or rec.get("name") or "")
    afm  = (rec.get("AFM_issuer") or rec.get("AFM") or "")
    aa   = (rec.get("AA") or rec.get("aa") or rec.get("mark") or "")
    if is_receipt:
        txt = (f"{name} ({afm})" if (name or afm) else f"Απόδειξη {aa}".strip())
    else:
        txt = (rec.get("ΑΙΤΙΟΛΟΓΙΑ") or rec.get("reason") or f"Τιμολόγιο {aa}").strip()
    return txt or "—"


def _digits(s: Any) -> str:
    return "".join(ch for ch in str(s) if ch.isdigit())


def _norm_afm(val: Any) -> str:
    """Keep only digits, last 9, with leading zeros (e.g., 094439854)."""
    d = _digits(val)
    if not d:
        return ""
    if len(d) >= 9:
        d = d[-9:]
    return d.zfill(9)


def _to_date(d: Any) -> Optional[datetime]:
    if not d:
        return None
    s = str(d).strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%d/%m/%y"):
        try:
            return datetime.strptime(s[:10], fmt)
        except Exception:
            pass
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", s)
    if m:
        return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    return None


def _ddmmyyyy(d: Any) -> str:
    dt = _to_date(d)
    return dt.strftime("%d/%m/%Y") if dt else ""


def _safe_int(x: Any) -> Optional[int]:
    try:
        return int(float(str(x).strip()))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Client DB reading / normalization (single-sheet, unknown header row)
# ---------------------------------------------------------------------------
def _find_header_row(df: pd.DataFrame, scan_rows: int = 30) -> int:
    """
    Find header row by looking for 'ΑΦΜ' and ('Συναλλ' or 'Κωδ' or 'cust' or 'id').
    If nothing found, return the row with the most non-empty cells in first scan_rows.
    """
    best = 0
    best_nonempty = -1
    hits: List[int] = []
    limit = min(scan_rows, len(df))
    for i in range(limit):
        row = [str(x).strip().lower() for x in df.iloc[i].tolist()]
        has_afm = any(("αφμ" in c) or (c == "afm") or ("vat" in c) for c in row)
        has_id = any(("συναλλ" in c) or ("κωδ" in c) or ("cust" in c) or (c == "id") for c in row)
        if has_afm and has_id:
            hits.append(i)
        nonempty = sum(1 for c in row if c and c != "nan")
        if nonempty > best_nonempty:
            best_nonempty = nonempty
            best = i
    return hits[0] if hits else best


def _read_first_sheet_any(path: str) -> pd.DataFrame:
    """Read FIRST sheet, detect header row, drop empty rows/cols, return dataframe of strings."""
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            xl = pd.ExcelFile(path)  # engine auto
        except Exception:
            ext = os.path.splitext(path)[1].lower()
            eng = "xlrd" if ext == ".xls" else "openpyxl"
            xl = pd.ExcelFile(path, engine=eng)

    sheet = xl.sheet_names[0]  # single/first
    df_raw = xl.parse(sheet, header=None, dtype=str)
    hdr_row = _find_header_row(df_raw)

    headers = [str(x).strip() for x in df_raw.iloc[hdr_row].tolist()]
    df = xl.parse(sheet, header=hdr_row, dtype=str)
    df.columns = [str(c).strip() for c in headers]
    df = df.dropna(how="all").dropna(axis=1, how="all")
    return df


def _pick_col(cols: List[str], candidates: List[str]) -> Optional[str]:
    lc_map = {str(c).strip().lower(): c for c in cols}
    for lc, orig in lc_map.items():
        for token in candidates:
            if token in lc:
                return orig
    return None


def _load_client_map(path: str) -> Dict[str, Any]:
    """
    Return:
      {
        'by_afm': { '094439854': 20254, ... },
        'ids': {20254, 170, ...},
        'names': { '094439854': 'ΤΡΑΚΑΔΑΣ Α.Ε.', ...},
        'columns': [...]
      }
    """
    df = _read_first_sheet_any(path)

    col_afm = _pick_col(list(df.columns), ["αφμ", "afm", "vat"])
    col_id = _pick_col(list(df.columns), ["συναλλ", "κωδ", "cust", "id"])
    col_name = _pick_col(list(df.columns), ["επωνυ", "name"])

    if not col_afm or not col_id:
        raise ValueError(f"client_db: δεν βρέθηκαν στήλες AFM/ID. Columns={list(df.columns)}")

    by_afm: Dict[str, int] = {}
    ids_in_db: set[int] = set()
    names: Dict[str, str] = {}

    for _, r in df.iterrows():
        afm_str = _norm_afm(r.get(col_afm, ""))
        if not afm_str:
            continue
        raw_id = str(r.get(col_id, "")).strip()
        try:
            cid = int(float(raw_id))  # supports "170.0"
        except Exception:
            continue
        by_afm[afm_str] = cid
        ids_in_db.add(cid)
        if col_name:
            nm = str(r.get(col_name, "") or "").strip()
            if nm:
                names[afm_str] = nm

    return {"by_afm": by_afm, "ids": ids_in_db, "names": names, "columns": list(df.columns)}


# ---------------------------------------------------------------------------
# Invoices loading and parsing
# ---------------------------------------------------------------------------
def resolve_paths_for_vat(
    vat: str,
    invoices_json: Optional[str] = None,
    client_db: Optional[str] = None,
    out_xlsx: Optional[str] = None,
    base_invoices_dir: str = "data/epsilon",
    base_exports_dir: str = "exports",
) -> Dict[str, str]:
    """
    - Τιμολόγια: κατά προτεραιότητα από base_invoices_dir (π.χ. data/epsilon)
    - client_db: ΠΡΩΤΑ στο data/ (χύμα), μετά σε data/epsilon/, κ.λπ.
    - out: exports/{vat}_EPSILON_BRIDGE_KINHSEIS.xlsx
    """
    vat = str(vat).strip()

    # ---- invoices path ----
    inv_candidates = [
        invoices_json,
        os.path.join(base_invoices_dir, f"{vat}_epsilon_invoices.json"),
        os.path.join(base_invoices_dir, "epsilon_invoices.json"),
        f"{vat}_epsilon_invoices.json",
        os.path.join("data", f"{vat}_epsilon_invoices.json"),
        os.path.join("data", "epsilon_invoices.json"),
    ]
    invoices_path = next((p for p in inv_candidates if p and os.path.exists(p)), inv_candidates[1])

    # ---- client_db path (ΠΡΩΤΑ data/) ----
    client_candidates = [
        client_db,
        # 1) data/ (χύμα)
        os.path.join("data", f"client_db_{vat}.xlsx"),
        os.path.join("data", f"client_db_{vat}.xls"),
        os.path.join("data", f"{vat}_client_db.xlsx"),
        os.path.join("data", f"{vat}_client_db.xls"),
        os.path.join("data", "client_db.xlsx"),
        os.path.join("data", "client_db.xls"),
        # 2) data/epsilon (fallback)
        os.path.join(base_invoices_dir, f"client_db_{vat}.xlsx"),
        os.path.join(base_invoices_dir, f"client_db_{vat}.xls"),
        os.path.join(base_invoices_dir, "client_db.xlsx"),
        os.path.join(base_invoices_dir, "client_db.xls"),
        # 3) current working dir (τελευταίο fallback)
        "client_db.xlsx",
        "client_db.xls",
    ]
    client_db_path = next((p for p in client_candidates if p and os.path.exists(p)), client_candidates[4])

    # ---- out path ----
    out_path = out_xlsx or os.path.join(base_exports_dir, f"{vat}_EPSILON_BRIDGE_KINHSEIS.xlsx")
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)

    return {"invoices": invoices_path, "client_db": client_db_path, "out": out_path}


def load_epsilon_invoices(path: str) -> List[Dict[str, Any]]:
    data = json.load(open(path, "r", encoding="utf-8"))
    if isinstance(data, list):
        return data
    # unwrap common wrappers
    for key in ("invoices", "records", "rows", "data", "items"):
        if isinstance(data.get(key), list):
            return data[key]
    # single record?
    return [data]


def _vat_rate(label: Any, net: float, vat: float) -> Optional[int]:
    m = re.search(r"(\d+)[\.,]?\d*\s*%", str(label) if label is not None else "")
    if m:
        try:
            return int(m.group(1))
        except Exception:
            pass
    if net:
        try:
            return int(round((vat / net) * 100))
        except Exception:
            return None
    return None


def _canon_category(raw: str) -> str:
    s = (raw or "").strip().lower().replace(" ", "_")
    if "εμπορ" in s or "εμπορευ" in s or "αγορ" in s:
        return "αγορες_εμπορευματων"
    if "α_υλων" in s or "πρωτ" in s or "υλη" in s:
        return "αγορες_α_υλων"
    if "χωρις_φπα" in s or "0%" in s or "μη_υποκειμ" in s:
        return "δαπανες_χωρις_φπα"
    if "δαπαν" in s or "γενικ" in s or "εξοδ" in s:
        return "γενικες_δαπανες"
    return s


def _is_receipt(rec: Dict[str, Any]) -> bool:
    t = (rec.get("type") or "").lower()
    return any(k in t for k in ["receipt", "αποδείξ", "αποδειξη"]) or (t.strip() == "1.1")


def _parse_lines(rec: Dict[str, Any]) -> List[Dict[str, Any]]:
    lines = rec.get("lines") or rec.get("invoice_lines") or rec.get("details") or []
    out: List[Dict[str, Any]] = []
    if isinstance(lines, list) and lines:
        for ln in lines:
            net = float(str(ln.get("amount", "0")).replace(",", ".")) if str(ln.get("amount", "")).strip() else 0.0
            vat = float(str(ln.get("vat", "0")).replace(",", ".")) if str(ln.get("vat", "")).strip() else 0.0
            vr = _vat_rate(ln.get("vat_category") or ln.get("vatRate"), net, vat)
            cat = (ln.get("category") or "").strip()
            out.append({"net": net, "vat": vat, "vat_rate": vr, "category": _canon_category(cat)})
        return out

    # fallback to totals
    net = float(str(rec.get("totalNetValue", "0")).replace(",", ".")) if str(rec.get("totalNetValue", "")).strip() else 0.0
    vat = float(str(rec.get("totalVatAmount", "0")).replace(",", ".")) if str(rec.get("totalVatAmount", "")).strip() else 0.0
    vr = _vat_rate(rec.get("vatCategory"), net, vat)
    cat = _canon_category(rec.get("category", "") or "")
    return [{"net": net, "vat": vat, "vat_rate": vr, "category": cat}]


# ---------------------------------------------------------------------------
# Settings & account resolution
# ---------------------------------------------------------------------------
def _deep_merge_dict(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge_dict(out[k], v)
        else:
            out[k] = v
    return out


def _select_settings_for_vat(all_settings: Dict[str, Any], vat: str) -> Dict[str, Any]:
    by_vat = all_settings.get("by_vat")
    if isinstance(by_vat, dict):
        spec = by_vat.get(str(vat))
        if isinstance(spec, dict):
            base = {k: v for k, v in all_settings.items() if k != "by_vat"}
            return _deep_merge_dict(base, spec)
    return all_settings


def _account_detail_invoice(settings: Dict[str, Any], category: str, vat_rate: Optional[int]) -> Optional[str]:
    canon = _canon_category(category)
    vr = str(vat_rate if vat_rate is not None else 0)
    key = f"account_{canon}_{vr}"
    val = settings.get(key)
    if isinstance(val, str) and val.strip():
        return val.strip()
    # nested map
    abv = settings.get("accounts_by_vat") or settings.get("account_map_by_vat")
    if isinstance(abv, dict):
        node = abv.get(canon)
        if isinstance(node, dict):
            v = node.get(vr)
            if isinstance(v, str) and v.strip():
                return v.strip()
    return None


def _account_detail_receipt(settings: Dict[str, Any], vat_rate: Optional[int]) -> Optional[str]:
    vr = str(vat_rate if vat_rate is not None else 0)
    key = f"account_αποδειξακια_{vr}"
    if key in settings and str(settings[key]).strip():
        return str(settings[key]).strip()
    if "account_αποδειξακια_0" in settings and str(settings["account_αποδειξακια_0"]).strip():
        return str(settings["account_αποδειξακια_0"]).strip()
    return None


def _account_header_P(settings: Dict[str, Any], is_receipt: bool) -> Optional[str]:
    return (settings.get("account_supplier_retail") if is_receipt else settings.get("account_supplier_wholesale"))


# ---------------------------------------------------------------------------
# Preview rows for UI (and issues list)
# ---------------------------------------------------------------------------
def characts_from_lines(rec: Dict[str, Any]) -> str:
    """Unique categories from lines (or rec.category)."""
    cats: List[str] = []
    for ln in (rec.get("lines") or []):
        c = (ln.get("category") or "").strip()
        if c:
            cats.append(_canon_category(c))
    if not cats and rec.get("category"):
        cats = [_canon_category(rec["category"])]
    # human render
    return ", ".join(sorted({c for c in cats if c}))


def build_preview_rows_for_ui(
    vat: str,
    credentials_json: str = "data/credentials.json",
    cred_settings_json: str = "data/credentials_settings.json",
    invoices_json: Optional[str] = None,
    client_db: Optional[str] = None,
    base_invoices_dir: str = "data/epsilon",
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], bool]:
    """
    Επιστρέφει (rows, issues, ok) για το template.
    Κάθε row περιέχει LINES με lcode_detail ανά γραμμή και LCODE_DETAIL_SUMMARY.
    """
    vat = str(vat or "").strip()
    paths = resolve_paths_for_vat(vat, invoices_json, client_db, None, base_invoices_dir)

    issues: List[Dict[str, Any]] = []

    # --- Load invoices ---
    try:
        invoices = load_epsilon_invoices(paths["invoices"])
    except Exception as e:
        return [], [{"code": "invoices_read_error", "modal": True, "message": f"Σφάλμα invoices: {e}"}], False

    # --- Load credentials & settings ---
    try:
        credentials = json.load(open(credentials_json, "r", encoding="utf-8"))
    except Exception:
        credentials = []

    try:
        settings_all = json.load(open(cred_settings_json, "r", encoding="utf-8"))
    except Exception:
        settings_all = {}

    settings = _select_settings_for_vat(settings_all, vat)

    cred_list = credentials if isinstance(credentials, list) else [credentials]
    active = next((c for c in cred_list if str(c.get("vat")) == vat), (cred_list[0] if cred_list else {}))
    apod_type = (active or {}).get("apodeixakia_type", "")
    apod_supplier_id = _safe_int((active or {}).get("apodeixakia_supplier", ""))

    # --- Load client_db map (robust σε κλειδιά) ---
    client_map = {"by_afm": {}, "by_id": set(), "names": {}, "cols": []}
    if paths["client_db"] and os.path.exists(paths["client_db"]):
        try:
            cm = _load_client_map(paths["client_db"])  # να γυρίζει dict με by_afm/by_id/(names προαιρετικό)/cols
            if isinstance(cm, dict):
                client_map["by_afm"] = cm.get("by_afm", {}) or {}
                # υποστήριξη και για 'ids' fallback
                client_map["by_id"] = cm.get("by_id") or cm.get("ids") or set()
                client_map["names"] = cm.get("names", {}) or {}
                client_map["cols"]  = cm.get("cols") or cm.get("columns") or []
        except Exception as e:
            issues.append({
                "code": "client_db_read_error",
                "modal": True,
                "message": f"client_db κενό/μη αναγνώσιμο (cols: {client_map.get('cols', [])}). {e}"
            })
    else:
        issues.append({"code": "client_db_missing", "modal": True, "message": "Δεν βρέθηκε client_db για αντιστοίχιση CUSTID."})

    # --- Normalize invoices to list ---
    if isinstance(invoices, dict):
        for k in ("invoices", "records", "rows", "data", "items"):
            if isinstance(invoices.get(k), list):
                invoices = invoices[k]
                break
        else:
            invoices = [invoices]

    rows: List[Dict[str, Any]] = []

    for rec in invoices:
        mark = rec.get("MARK") or rec.get("mark") or ""
        aa = rec.get("AA") or rec.get("aa") or ""
        date = _ddmmyyyy(rec.get("issueDate") or rec.get("ΗΜΕΡΟΜΗΝΙΑ"))

        afm_raw = rec.get("AFM_issuer") or rec.get("AFM") or ""
        afm_norm = _norm_afm(afm_raw)

        is_receipt = _is_receipt(rec)
        doc_type = rec.get("type") or ""

        # Όνομα εκδότη: από record ή fallback από client_db (αν υπάρχει names map)
        issuer_name = (
            rec.get("Name_issuer")
            or rec.get("issuerName")
            or rec.get("issuer_name")
            or rec.get("Name")
            or rec.get("name")
            or client_map["names"].get(afm_norm, "")
        )

        # Γραμμές & σύνολα
        pairs = _parse_lines(rec)
        tot_net = sum(p["net"] for p in pairs)
        tot_vat = sum(p["vat"] for p in pairs)
        tot_gross = tot_net + tot_vat

        # CUSTID resolve (receipts με supplier mode ή AFM mapping)
        custid_val: Optional[int] = None
        if is_receipt and apod_type == "supplier":
            if apod_supplier_id is not None and apod_supplier_id in client_map["by_id"]:
                custid_val = apod_supplier_id
            else:
                issues.append({
                    "code": "apodeixakia_supplier_not_in_client_db",
                    "modal": True,
                    "message": f"apodeixakia_supplier={apod_supplier_id} δεν υπάρχει στο client_db"
                })
        else:
            custid_val = client_map["by_afm"].get(afm_norm)
            if custid_val is None:
                issues.append({"code": "custid_missing", "modal": True, "message": f"Δεν βρέθηκε CUSTID για ΑΦΜ {afm_norm}"})

        # Header account (στήλη P) για preview πληρότητας
        lcode_p = _account_header_P(settings, is_receipt)

        # Per-line lcode_detail
        lines_out: List[Dict[str, Any]] = []
        lcodes_summary: List[str] = []

        for ln in pairs:
            vr = ln.get("vat_rate")
            cat = ln.get("category")
            if is_receipt:
                lcode_detail = _account_detail_receipt(settings, vr)
            else:
                lcode_detail = _account_detail_invoice(settings, cat, vr)

            if lcode_detail:
                lcodes_summary.append(lcode_detail)

            net_val = float(abs(ln.get("net", 0.0)))
            vat_val = float(abs(ln.get("vat", 0.0)))
            lines_out.append({
                "category": cat,
                "net": round(net_val, 2),
                "vat": round(vat_val, 2),
                "gross": round(net_val + vat_val, 2),
                "vat_rate": vr,
                "lcode_detail": (lcode_detail or "")
            })

        # Αν πολλαπλά VAT και δεν υπάρχει ήδη characts => badge
        characts = characts_from_lines(rec)
        if (len({(l.get("vat_rate") or 0) for l in lines_out}) > 1) and not characts:
            characts = "Πολλαπλές κατηγορίες ΦΠΑ"

        rows.append({
            "MARK": str(mark),
            "AA": str(aa),
            "DATE": date,
            "AFM_ISSUER": afm_norm or str(afm_raw),
            "ISSUER_NAME": issuer_name,
            "CUSTID": custid_val,
            "NET": round(float(tot_net), 2),
            "VAT": round(float(tot_vat), 2),
            "GROSS": round(float(tot_gross), 2),
            "DOCTYPE": doc_type,
            "CHARACTS": characts,
            "LINES": lines_out,
            "LCODE_DETAIL_SUMMARY": ", ".join(sorted({c for c in lcodes_summary if c})),
            "LCODE": (lcode_p or "")
        })

    ok = (len(issues) == 0) and (len(rows) > 0)
    return rows, issues, ok

def build_preview_strict_multiclient(
    vat: str,
    credentials_json: str,
    cred_settings_json: str,
    invoices_json: Optional[str] = None,
    client_db: Optional[str] = None,
    base_invoices_dir: str = "data/epsilon",
) -> Dict[str, Any]:
    """
    Επιστρέφει { ok, rows, issues, paths } για STRICT export.
    Γεμίζουμε πάντα REASON, LCODE_DETAIL, LCODE (P) με fallbacks για να μη σπάνε οι έλεγχοι.
    """
    vat = str(vat)
    paths = resolve_paths_for_vat(vat, invoices_json, client_db, None, base_invoices_dir)

    invoices = load_epsilon_invoices(paths["invoices"])
    credentials = _safe_json_read(credentials_json, default=[])
    settings_all = _safe_json_read(cred_settings_json, default={})
    settings = _select_settings_for_vat(settings_all, vat)

    # active για αποδείξεις
    cred_list = credentials if isinstance(credentials, list) else [credentials]
    active = next((c for c in cred_list if str(c.get("vat")) == vat), (cred_list[0] if cred_list else {}))
    apod_type = (active or {}).get("apodeixakia_type","")
    apod_supplier_id = _safe_int((active or {}).get("apodeixakia_supplier",""))

    # client_db
    issues: List[Dict[str,Any]] = []
    client_map = {"by_afm": {}, "by_id": set(), "cols": []}
    if paths["client_db"] and os.path.exists(paths["client_db"]):
        try:
            cm = _load_client_map(paths["client_db"])
            client_map["by_afm"] = cm.get("by_afm", {})
            client_map["by_id"]  = cm.get("by_id", cm.get("ids", set()))
            client_map["cols"]   = cm.get("cols", cm.get("columns", []))
        except Exception as e:
            issues.append({"code":"client_db_read_error","modal":True,
                           "message":f"Σφάλμα ανάγνωσης client_db: {e}"})
    else:
        issues.append({"code":"client_db_missing","modal":True,
                       "message":"Δεν βρέθηκε client_db για αντιστοίχιση CUSTID."})

    # normalize invoices
    if isinstance(invoices, dict):
        for k in ("invoices","records","rows","data","items"):
            if isinstance(invoices.get(k), list):
                invoices = invoices[k]; break
        else:
            invoices = [invoices]

    rows: List[Dict[str,Any]] = []
    artid = 1
    DEFAULT_LCODE_DETAIL = settings.get("default_lcode_detail", "62-00.00")

    for rec in invoices:
        is_receipt = _is_receipt(rec)
        aa = str(rec.get("AA") or rec.get("aa") or rec.get("mark",""))
        mdate_dt = _to_date(rec.get("issueDate") or rec.get("ΗΜΕΡΟΜΗΝΙΑ"))
        name_issuer = rec.get("Name_issuer") or rec.get("issuerName") or ""
        afm_issuer = rec.get("AFM_issuer") or rec.get("AFM") or ""
        reason = _reason_for_rec(rec, is_receipt)

        pairs = _parse_lines(rec)
        sum_net = sum(p["net"] for p in pairs)
        msign = -1 if sum_net < 0 else 1

        # CUSTID
        custid_val: Optional[int] = None
        if is_receipt and apod_type == "supplier":
            custid_val = apod_supplier_id if apod_supplier_id in client_map["by_id"] else None
            if custid_val is None:
                issues.append({"code":"apodeixakia_supplier_not_in_client_db","modal":True,
                               "message": f"ΑΠΟΔΕΙΞΗ AA={aa}: apodeixakia_supplier={apod_supplier_id} δεν υπάρχει στο client_db."})
        else:
            if afm_issuer:
                cid = client_map["by_afm"].get(str(_norm_afm(afm_issuer)))
                if cid is None:
                    issues.append({"code":"custid_missing","modal":True,
                                   "message": f"{'ΤΙΜΟΛΟΓΙΟ' if not is_receipt else 'ΑΠΟΔΕΙΞΗ'} AA={aa}: Δεν βρέθηκε CUSTID για ΑΦΜ {afm_issuer}."})
                else:
                    custid_val = int(cid)
            else:
                issues.append({"code":"issuer_afm_missing","modal":True,
                               "message": f"AA={aa}: Λείπει ΑΦΜ εκδότη για αντιστοίχιση CUSTID."})

        # Header account (στήλη P) και per-line (J)
        lcode_P_cfg = _account_header_P(settings, is_receipt)

        for p in pairs:
            net = abs(float(p["net"]))
            vat = abs(float(p["vat"]))
            vr  = p.get("vat_rate")
            cat = p.get("category") or rec.get("category") or ""

            lcode_J_cfg = (_account_detail_receipt(settings, vr)
                           if is_receipt else
                           _account_detail_invoice(settings, cat, vr))

            # ---- FALLBACKS (για να μη βγουν κενά) ----
            final_reason = reason or "—"
            final_lcodeJ = (lcode_J_cfg or DEFAULT_LCODE_DETAIL)
            final_lcodeP = (str(lcode_P_cfg).strip() or final_lcodeJ)

            rows.append({
                "ARTID": int(artid),
                "MTYPE": int(1 if (is_receipt or "αγορ" in (cat or "") or "δαπ" in (cat or "")) else 0),
                "ISKEPYO": 1,
                "ISAGRYP": 0,
                "CUSTID": (int(custid_val) if custid_val is not None else None),
                "MDATE": mdate_dt,
                "REASON": final_reason,
                "INVOICE": aa,
                "SUMKEPYOYP": float(abs(sum_net)),
                "LCODE_DETAIL": final_lcodeJ,
                "ISAGRYP_DETAIL": 0,
                "KEPYOPARTY_DETAIL": float(abs(net)),
                "NETAMT_DETAIL": float(abs(net)),
                "VATAMT_DETAIL": float(abs(vat)),
                "MSIGN": int(msign),
                "LCODE": final_lcodeP,
            })
        artid += 1

    # strict έλεγχος για κενά
    required = ["ARTID","MTYPE","ISKEPYO","ISAGRYP","CUSTID","MDATE","REASON","INVOICE","SUMKEPYOYP",
                "LCODE_DETAIL","ISAGRYP_DETAIL","KEPYOPARTY_DETAIL","NETAMT_DETAIL","VATAMT_DETAIL","MSIGN","LCODE"]
    for r in rows:
        for c in required:
            v = r.get(c, None)
            if v is None or (isinstance(v, str) and not v.strip()):
                issues.append({"code":"blank_cell","modal":True,
                               "message": f"Γραμμή ARTID={r.get('ARTID')} / πεδίο {c}: κενή τιμή (strict).",
                               "row_artid": r.get("ARTID"), "field": c})

    return {"ok": len(issues)==0, "rows": rows, "issues": issues, "paths": paths}

# ---------------------------------------------------------------------------
# STRICT export (blocks on any issue)
# ---------------------------------------------------------------------------
def export_multiclient_strict(
    vat: str,
    credentials_json: str,
    cred_settings_json: str,
    invoices_json: Optional[str] = None,
    client_db: Optional[str] = None,
    out_xlsx: Optional[str] = None,
    base_invoices_dir: str = "data/epsilon",
    base_exports_dir: str = "exports",
) -> Tuple[bool, str, List[Dict[str,Any]]]:
    preview = build_preview_strict_multiclient(
        vat, credentials_json, cred_settings_json, invoices_json, client_db, base_invoices_dir
    )
    if not preview["ok"]:
        return False, "", preview["issues"]

    paths = resolve_paths_for_vat(vat, invoices_json, client_db, out_xlsx, base_invoices_dir, base_exports_dir)
    rows = preview["rows"]

    df = pd.DataFrame(rows, columns=[
        "ARTID","MTYPE","ISKEPYO","ISAGRYP","CUSTID","MDATE","REASON","INVOICE","SUMKEPYOYP",
        "LCODE_DETAIL","ISAGRYP_DETAIL","KEPYOPARTY_DETAIL","NETAMT_DETAIL","VATAMT_DETAIL","MSIGN","LCODE"
    ])

    with pd.ExcelWriter(paths["out"], engine="xlsxwriter", datetime_format="dd/mm/yyyy") as writer:
        df.to_excel(writer, index=False, sheet_name="ΚΙΝΗΣΕΙΣ")
        wb, ws = writer.book, writer.sheets["ΚΙΝΗΣΕΙΣ"]
        fmt_num  = wb.add_format({"num_format":"0.00"})
        fmt_int  = wb.add_format({"num_format":"0"})
        fmt_date = wb.add_format({"num_format":"dd/mm/yyyy"})
        idx = {n:i for i,n in enumerate(df.columns)}
        for n in ["ARTID","MTYPE","ISKEPYO","ISAGRYP","ISAGRYP_DETAIL","MSIGN","CUSTID"]:
            if n in idx: ws.set_column(idx[n], idx[n], 10, fmt_int)
        for n in ["SUMKEPYOYP","KEPYOPARTY_DETAIL","NETAMT_DETAIL","VATAMT_DETAIL"]:
            if n in idx: ws.set_column(idx[n], idx[n], 14, fmt_num)
        if "MDATE" in idx: ws.set_column(idx["MDATE"], idx["MDATE"], 12, fmt_date)
        for n,w in [("REASON",40),("INVOICE",18),("LCODE_DETAIL",16),("LCODE",16)]:
            if n in idx: ws.set_column(idx[n], idx[n], w)

    return True, paths["out"], []


# ---------------------------------------------------------------------------
# Flask convenience helper
# ---------------------------------------------------------------------------
def run_and_report_dynamic(
    vat: str,
    credentials_json: str = "data/credentials.json",
    cred_settings_json: str = "data/credentials_settings.json",
    invoices_json: Optional[str] = None,
    client_db: Optional[str] = None,
    out_xlsx: Optional[str] = None,
    base_invoices_dir: str = "data/epsilon",
    base_exports_dir: str = "exports",
):
    ok, path, issues = export_multiclient_strict(
        vat=vat,
        credentials_json=credentials_json,
        cred_settings_json=cred_settings_json,
        invoices_json=invoices_json,
        client_db=client_db,
        out_xlsx=out_xlsx,
        base_invoices_dir=base_invoices_dir,
        base_exports_dir=base_exports_dir,
    )
    return {"ok": ok, "path": path, "issues": issues}


# ---------------------------------------------------------------------------
# CLI (guarded to avoid running when imported)
# ---------------------------------------------------------------------------
def _cli():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--vat", required=True)
    ap.add_argument("--invoices", default=None)
    ap.add_argument("--clientdb", default=None)
    ap.add_argument("--credentials", default="data/credentials.json")
    ap.add_argument("--settings", default="data/credentials_settings.json")
    ap.add_argument("--out", default=None)
    ap.add_argument("--invoices_dir", default="data/epsilon")
    ap.add_argument("--exports_dir", default="exports")
    args = ap.parse_args()

    ok, path, issues = export_multiclient_strict(
        vat=args.vat,
        credentials_json=args.credentials,
        cred_settings_json=args.settings,
        invoices_json=args.invoices,
        client_db=args.clientdb,
        out_xlsx=args.out,
        base_invoices_dir=args.invoices_dir,
        base_exports_dir=args.exports_dir,
    )
    if not ok:
        print("ERROR: Validation failed. Issues:")
        for i in issues:
            print(" -", i.get("message"))
    else:
        print("Wrote:", path)


if __name__ == "__main__":
    _cli()
