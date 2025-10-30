# -*- coding: utf-8 -*-
"""
epsilon_bridge_multiclient_strict.py
------------------------------------
STRICT builder for Epsilon FastImport 'ΚΙΝΗΣΕΙΣ' (multi-client).

- Handles settings keys like: account_{category}_{rate} or account_{category}_{rate}%
- VAT-rate inference per line with multiple sources; snaps to available rates defined in settings.
- Invoices REASON = issuer name (or name from client_db by AFM). Receipts REASON unchanged.
- Case-insensitive settings keys (Greek-safe).
- Adds 'DEBUG' per exported row for server-side inspection (not in Excel).
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
# Utils
# ---------------------------------------------------------------------------
def _digits(s: Any) -> str:
    return "".join(ch for ch in str(s or "") if ch.isdigit())


def _norm_afm(val: Any) -> str:
    d = _digits(val)
    if not d:
        return ""
    if len(d) >= 9:
        d = d[-9:]
    return d.zfill(9)


def _safe_json_read(path: str, default=None):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {} if default is None else default


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


def _round2(x: Any) -> float:
    try:
        return round(float(x), 2)
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# Settings helpers
# ---------------------------------------------------------------------------
def _settings_lc(settings: Dict[str, Any]) -> Dict[str, Any]:
    """Lowercase keys for case-insensitive access (Greek-safe)."""
    return {str(k).lower(): v for k, v in (settings or {}).items()}


def _available_rates_for_category(settings: Dict[str, Any], canon: str) -> List[int]:
    """Find rates from keys account_{canon}_{rate} or account_{canon}_{rate}%."""
    setts = _settings_lc(settings)
    prefix = f"account_{canon}_"
    rates: List[int] = []
    for k in setts.keys():
        if not isinstance(k, str) or not k.startswith(prefix):
            continue
        suf = k.split("_")[-1]
        m = re.match(r"^(\d{1,2})%?$", str(suf))
        if not m:
            continue
        try:
            r = int(m.group(1))
        except Exception:
            continue
        rates.append(r)
    return sorted(list({int(r) for r in rates}))


def _get_account_value_for_key(setts: Dict[str, Any], key_base: str) -> str:
    """
    Try exact key_base; if ends with digits add '%'; if ends with '%', try without.
    Returns non-empty string value or "".
    """
    val = setts.get(key_base, "")
    if isinstance(val, str) and val.strip():
        return val
    m = re.match(r"^(.*?)(\d{1,2})%$", key_base)
    if m:
        alt = (m.group(1) + m.group(2)).lower()
        v = setts.get(alt, "")
        if isinstance(v, str) and v.strip():
            return v
    else:
        m2 = re.match(r"^(.*?)(\d{1,2})$", key_base)
        if m2:
            alt = (m2.group(1) + m2.group(2) + "%").lower()
            v = setts.get(alt, "")
            if isinstance(v, str) and v.strip():
                return v
    return ""


# ---------------------------------------------------------------------------
# Category canon + VAT inference
# ---------------------------------------------------------------------------
def _canon_category(raw: str) -> str:
    """
    Canon keys to match credentials_settings.json:
      αγορες_εμπορευματων, αγορες_α_υλων, γενικες_δαπανες_με_φπα,
      δαπανες_χωρις_φπα, αμοιβες_τριτων, εγγυοδοσια, αποδειξακια
    """
    s = (raw or "").strip().lower().replace(" ", "_")
    if "αποδειξ" in s:
        return "αποδειξακια"
    if "αμοιβ" in s and "τριτ" in s:
        return "αμοιβες_τριτων"
    if "εγγυοδοσι" in s:
        return "εγγυοδοσια"
    if ("εμπορ" in s or "εμπορευ" in s) or ("αγορ" in s and ("εμπ" in s or "εμπορ" in s)):
        return "αγορες_εμπορευματων"
    if ("α_υλων" in s) or ("α'_υλων" in s) or ("α_υλες" in s) or ("πρωτ" in s) or ("υλη" in s):
        return "αγορες_α_υλων"
    without_vat = ("χωρι" in s and "φπα" in s) or "μη_υποκει" in s or "0%" in s
    if without_vat:
        return "δαπανες_χωρις_φπα"
    if "δαπαν" in s or "γενικ" in s or "εξοδ" in s:
        return "γενικες_δαπανες_με_φπα"
    return s


_VAT_PATTERNS = [
    r"(\d+)[\.,]?\d*\s*%",
    r"φπα\s*(\d+)",
    r"vat\s*(\d+)",
    r"tax\s*rate\s*(\d+)",
]


def _extract_rate_from_string(s: Any) -> Optional[int]:
    if s is None:
        return None
    text = str(s).lower()
    for pat in _VAT_PATTERNS:
        m = re.search(pat, text)
        if m:
            try:
                return int(m.group(1))
            except Exception:
                pass
    return None


def _infer_vat_rate_for_line(ln: Dict[str, Any], rec: Dict[str, Any]) -> Tuple[Optional[int], str]:
    # explicit fields
    for fld in ("vat_rate", "vatrate", "vatRate", "ΦΠΑ_rate", "fpa_rate"):
        val = ln.get(fld)
        if val is not None and str(val).strip() != "":
            try:
                return int(float(str(val).replace(",", "."))), f"line.{fld}"
            except Exception:
                pass
    # labels
    rate = _extract_rate_from_string(ln.get("vat_category")) or _extract_rate_from_string(ln.get("vatCategory"))
    if rate is not None:
        return rate, "line.vat_category"
    rate = _extract_rate_from_string(ln.get("category"))
    if rate is not None:
        return rate, "line.category"
    # compute from numbers
    try:
        net = float(str(ln.get("amount", ln.get("net") or ln.get("net_value") or 0)).replace(",", "."))
    except Exception:
        net = 0.0
    try:
        vat = float(str(ln.get("vat", ln.get("vat_amount") or 0)).replace(",", "."))
    except Exception:
        vat = 0.0
    if net and vat:
        try:
            calc = (vat / net) * 100.0
            return int(round(calc)), "calc"
        except Exception:
            pass
    # record-level hints
    rate = _extract_rate_from_string(rec.get("vatCategory")) or _extract_rate_from_string(rec.get("type"))
    if rate is not None:
        return rate, "rec.hint"
    # record totals compute
    try:
        rnet = float(str(rec.get("totalNetValue") or 0).replace(",", "."))
        rvat = float(str(rec.get("totalVatAmount") or 0).replace(",", "."))
        if rnet and rvat:
            return int(round((rvat / rnet) * 100.0)), "rec.calc"
    except Exception:
        pass
    return None, "unknown"


# ---------------------------------------------------------------------------
# Value parsing
# ---------------------------------------------------------------------------
def _split_account_value(val: Any) -> Tuple[str, Optional[int]]:
    s = str(val or "").strip()
    m = re.match(r"^(.*)_(\d{1,2})$", s)
    if m:
        base = m.group(1).strip()
        vr = int(m.group(2))
        return base, vr
    return s, None


# ---------------------------------------------------------------------------
# Reason
# ---------------------------------------------------------------------------
def _reason_for_rec_enhanced(rec: Dict[str, Any], is_receipt: bool, client_names: Optional[Dict[str, str]] = None) -> str:
    name = (rec.get("Name_issuer") or rec.get("issuerName") or
            rec.get("issuer_name") or rec.get("Name") or rec.get("name") or "")
    afm  = (rec.get("AFM_issuer") or rec.get("AFM") or "")
    aa   = (rec.get("AA") or rec.get("aa") or rec.get("mark") or "")
    if is_receipt:
        txt = (f"{name} ({afm})" if (name or afm) else f"Απόδειξη {aa}".strip())
        return txt or "—"
    nm = str(name).strip()
    if not nm and client_names and afm:
        nm = client_names.get(_norm_afm(afm), "").strip()
    if nm:
        return nm
    return (rec.get("ΑΙΤΙΟΛΟΓΙΑ") or rec.get("reason") or f"Τιμολόγιο {aa}").strip() or "—"


# ---------------------------------------------------------------------------
# Client DB
# ---------------------------------------------------------------------------
def _find_header_row(df: pd.DataFrame, scan_rows: int = 30) -> int:
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
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            xl = pd.ExcelFile(path)  # engine auto
        except Exception:
            ext = os.path.splitext(path)[1].lower()
            eng = "xlrd" if ext == ".xls" else "openpyxl"
            xl = pd.ExcelFile(path, engine=eng)
    sheet = xl.sheet_names[0]
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
            cid = int(float(raw_id))
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
# Invoices loading & lines
# ---------------------------------------------------------------------------
def resolve_paths_for_vat(
    vat: str,
    invoices_json: Optional[str] = None,
    client_db: Optional[str] = None,
    out_xlsx: Optional[str] = None,
    base_invoices_dir: str = "data/epsilon",
    base_exports_dir: str = "exports",
) -> Dict[str, str]:
    vat = str(vat).strip()
    inv_candidates = [
        invoices_json,
        os.path.join(base_invoices_dir, f"{vat}_epsilon_invoices.json"),
        os.path.join(base_invoices_dir, "epsilon_invoices.json"),
        f"{vat}_epsilon_invoices.json",
        os.path.join("data", f"{vat}_epsilon_invoices.json"),
        os.path.join("data", "epsilon_invoices.json"),
    ]
    invoices_path = next((p for p in inv_candidates if p and os.path.exists(p)), inv_candidates[1])
    client_candidates = [
        client_db,
        os.path.join("data", f"client_db_{vat}.xlsx"),
        os.path.join("data", f"client_db_{vat}.xls"),
        os.path.join("data", f"{vat}_client_db.xlsx"),
        os.path.join("data", f"{vat}_client_db.xls"),
        os.path.join("data", "client_db.xlsx"),
        os.path.join("data", "client_db.xls"),
        os.path.join(base_invoices_dir, f"client_db_{vat}.xlsx"),
        os.path.join(base_invoices_dir, f"client_db_{vat}.xls"),
        os.path.join(base_invoices_dir, "client_db.xlsx"),
        os.path.join(base_invoices_dir, "client_db.xls"),
        "client_db.xlsx",
        "client_db.xls",
    ]
    client_db_path = next((p for p in client_candidates if p and os.path.exists(p)), client_candidates[4])
    out_path = out_xlsx or os.path.join(base_exports_dir, f"{vat}_EPSILON_BRIDGE_KINHSEIS.xlsx")
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    return {"invoices": invoices_path, "client_db": client_db_path, "out": out_path}


def load_epsilon_invoices(path: str) -> List[Dict[str, Any]]:
    data = json.load(open(path, "r", encoding="utf-8"))
    if isinstance(data, list):
        return data
    for key in ("invoices", "records", "rows", "data", "items"):
        if isinstance(data.get(key), list):
            return data[key]
    return [data]


def _is_receipt(rec: Dict[str, Any]) -> bool:
    t = (rec.get("type") or "").lower()
    return any(k in t for k in ["receipt", "αποδείξ", "αποδειξ", "λιαν"])


def _parse_lines(rec: Dict[str, Any]) -> List[Dict[str, Any]]:
    lines = rec.get("lines") or rec.get("invoice_lines") or rec.get("details") or []
    out: List[Dict[str, Any]] = []
    if isinstance(lines, list) and lines:
        for ln in lines:
            net = float(str(ln.get("amount", "0")).replace(",", ".")) if str(ln.get("amount", "")).strip() else 0.0
            vat = float(str(ln.get("vat", "0")).replace(",", ".")) if str(ln.get("vat", "")).strip() else 0.0
            vr, src = _infer_vat_rate_for_line(ln, rec)
            cat = _canon_category(ln.get("category") or "")
            out.append({"net": net, "vat": vat, "vat_rate": vr, "vat_src": src, "category": cat})
        return out
    net = float(str(rec.get("totalNetValue", "0")).replace(",", ".")) if str(rec.get("totalNetValue", "")).strip() else 0.0
    vat = float(str(rec.get("totalVatAmount", "0")).replace(",", ".")) if str(rec.get("totalVatAmount", "")).strip() else 0.0
    vr, src = _infer_vat_rate_for_line({}, rec)
    cat = _canon_category(rec.get("category", "") or "")
    return [{"net": net, "vat": vat, "vat_rate": vr, "vat_src": src, "category": cat}]


# ---------------------------------------------------------------------------
# Account resolution
# ---------------------------------------------------------------------------
def _account_detail_invoice(settings: Dict[str, Any], category: str, vat_rate: Optional[int]) -> Tuple[str, Dict[str, Any]]:
    setts = _settings_lc(settings)
    canon = _canon_category(category)
    avail = _available_rates_for_category(settings, canon)
    # snap to available
    snapped = None
    why = "none"
    if vat_rate is not None:
        try:
            rv = float(vat_rate)
            if avail:
                snapped = min(avail, key=lambda a: abs(a - rv))
                why = "snap"
            else:
                snapped = int(round(rv))
                why = "no-allowed"
        except Exception:
            snapped = None
            why = "invalid"
    tried = []
    chosen = ""
    used_key = ""
    if snapped is not None:
        for suffix in (f"{snapped}%", f"{snapped}"):
            key = f"account_{canon}_{suffix}".lower()
            tried.append(key)
            raw = _get_account_value_for_key(setts, key)
            if isinstance(raw, str) and raw.strip():
                chosen, _ = _split_account_value(raw)
                used_key = key
                break
        if not chosen:
            for r in avail:
                for suffix in (f"{r}%", f"{r}"):
                    k2 = f"account_{canon}_{suffix}".lower()
                    if k2 in tried:
                        continue
                    raw2 = _get_account_value_for_key(setts, k2)
                    tried.append(k2)
                    if isinstance(raw2, str) and raw2.strip():
                        chosen, _ = _split_account_value(raw2)
                        used_key = k2
                        break
                if chosen:
                    break
    if not chosen:
        generic = setts.get(f"account_{canon}")
        if isinstance(generic, str) and generic.strip():
            chosen, _ = _split_account_value(generic)
    if not chosen:
        if "αγορες_εμπορευματων" in canon:
            chosen = "20-1000"
        elif "αγορες_α_υλων" in canon:
            chosen = "24-0000"
        elif "δαπανες_χωρις_φπα" in canon:
            chosen = "64-1001"
        elif "αμοιβες_τριτων" in canon:
            chosen = "61-0000"
        elif "εγγυοδοσια" in canon:
            chosen = "64-1000"
        else:
            chosen = "62-00.00"
    debug = {
        "category": canon,
        "vat_in": vat_rate,
        "avail_rates": avail,
        "snapped_to": snapped,
        "snap_reason": why,
        "used_key": used_key,
        "tried_keys": tried,
        "chosen": chosen,
    }
    return chosen, debug


def _account_detail_receipt(settings: Dict[str, Any], vat_rate: Optional[int]) -> Tuple[str, Dict[str, Any]]:
    setts = _settings_lc(settings)
    canon = "αποδειξακια"
    avail = _available_rates_for_category(settings, canon)
    snapped = None
    why = "none"
    if vat_rate is not None:
        try:
            rv = float(vat_rate)
            if avail:
                snapped = min(avail, key=lambda a: abs(a - rv))
                why = "snap"
            else:
                snapped = int(round(rv))
                why = "no-allowed"
        except Exception:
            snapped = None
            why = "invalid"
    tried = []
    chosen = ""
    used_key = ""
    if snapped is not None:
        for suffix in (f"{snapped}%", f"{snapped}"):
            key = f"account_{canon}_{suffix}".lower()
            tried.append(key)
            raw = _get_account_value_for_key(setts, key)
            if isinstance(raw, str) and raw.strip():
                chosen, _ = _split_account_value(raw)
                used_key = key
                break
        if not chosen:
            for r in avail:
                for suffix in (f"{r}%", f"{r}"):
                    k2 = f"account_{canon}_{suffix}".lower()
                    if k2 in tried:
                        continue
                    raw2 = _get_account_value_for_key(setts, k2)
                    tried.append(k2)
                    if isinstance(raw2, str) and raw2.strip():
                        chosen, _ = _split_account_value(raw2)
                        used_key = k2
                        break
                if chosen:
                    break
    if not chosen:
        generic = setts.get(f"account_{canon}_0%") or setts.get(f"account_{canon}_0")
        if isinstance(generic, str) and str(generic).strip():
            chosen, _ = _split_account_value(generic)
    if not chosen:
        chosen = "62-00.00"
    debug = {
        "category": canon,
        "vat_in": vat_rate,
        "avail_rates": avail,
        "snapped_to": snapped,
        "snap_reason": why,
        "used_key": used_key,
        "tried_keys": tried,
        "chosen": chosen,
    }
    return chosen, debug


def _account_header_P(settings: Dict[str, Any], is_receipt: bool) -> str:
    setts = _settings_lc(settings)
    key = "account_supplier_retail" if is_receipt else "account_supplier_wholesale"
    val = setts.get(key, "")
    if isinstance(val, str) and val.strip():
        base, _ = _split_account_value(val)
        return base
    return "50-1000" if is_receipt else "50-0000"


# ---------------------------------------------------------------------------
# Preview/export builders
# ---------------------------------------------------------------------------
def characts_from_lines(rec: Dict[str, Any]) -> str:
    cats: List[str] = []
    for ln in (rec.get("lines") or []):
        c = (ln.get("category") or "").strip()
        if c:
            cats.append(_canon_category(c))
    if not cats and rec.get("category"):
        cats = [_canon_category(rec["category"])]
    return ", ".join(sorted({c for c in cats if c}))


def build_preview_rows_for_ui(
    vat: str,
    credentials_json: str = "data/credentials.json",
    cred_settings_json: str = "data/credentials_settings.json",
    invoices_json: Optional[str] = None,
    client_db: Optional[str] = None,
    base_invoices_dir: str = "data/epsilon",
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], bool]:
    vat = str(vat or "").strip()
    paths = resolve_paths_for_vat(vat, invoices_json, client_db, None, base_invoices_dir)

    issues: List[Dict[str, Any]] = []

    try:
        invoices = load_epsilon_invoices(paths["invoices"])
    except Exception as e:
        return [], [{"code": "invoices_read_error", "modal": True, "message": f"Σφάλμα invoices: {e}"}], False

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

    client_map = {"by_afm": {}, "by_id": set(), "names": {}, "cols": []}
    if paths["client_db"] and os.path.exists(paths["client_db"]):
        try:
            cm = _load_client_map(paths["client_db"])
            if isinstance(cm, dict):
                client_map["by_afm"] = cm.get("by_afm", {}) or {}
                client_map["by_id"] = cm.get("ids") or cm.get("by_id") or set()
                client_map["names"] = cm.get("names", {}) or {}
                client_map["cols"] = cm.get("columns") or cm.get("cols") or []
        except Exception as e:
            issues.append({"code": "client_db_read_error", "modal": True, "message": f"client_db κενό/μη αναγνώσιμο. {e}"})
    else:
        issues.append({"code": "client_db_missing", "modal": True, "message": "Δεν βρέθηκε client_db για αντιστοίχιση CUSTID."})

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

        issuer_name = (
            rec.get("Name_issuer")
            or rec.get("issuerName")
            or rec.get("issuer_name")
            or rec.get("Name")
            or rec.get("name")
            or client_map["names"].get(afm_norm, "")
        )
        reason = _reason_for_rec_enhanced(rec, is_receipt, client_map.get("names"))

        pairs = _parse_lines(rec)
        tot_net = sum(p["net"] for p in pairs)
        tot_vat = sum(p["vat"] for p in pairs)
        tot_gross = tot_net + tot_vat

        custid_val: Optional[int] = None
        if is_receipt and apod_type == "supplier":
            if apod_supplier_id is not None and apod_supplier_id in (client_map["by_id"] or set()):
                custid_val = apod_supplier_id
            else:
                issues.append({"code": "apodeixakia_supplier_not_in_client_db", "modal": True, "message": f"apodeixakia_supplier={apod_supplier_id} δεν υπάρχει στο client_db"})
        else:
            custid_val = client_map["by_afm"].get(afm_norm)
            if custid_val is None:
                issues.append({"code": "custid_missing", "modal": True, "message": f"Δεν βρέθηκε CUSTID για ΑΦΜ {afm_norm}"})

        lcode_p = _account_header_P(settings, is_receipt)
        if not lcode_p:
            issues.append({"code":"missing_header_account","modal":True,
                           "message": f"AA={aa} — Δεν έχει οριστεί λογαριασμός προμηθευτή (account_supplier_%s)." % ("retail" if is_receipt else "wholesale")})

        lines_out: List[Dict[str, Any]] = []
        lcodes_summary: List[str] = []

        
        for ln in pairs:
            vr = ln.get("vat_rate")
            src = ln.get("vat_src")
            cat = ln.get("category")
            if is_receipt:
                acc, dbg = _account_detail_receipt(settings, vr)
            else:
                acc, dbg = _account_detail_invoice(settings, cat, vr)

            # strict modal issues
            if (not cat) and (not is_receipt):
                issues.append({"code":"missing_category_line","modal":True,
                               "message": f"AA={aa} — Γραμμή χωρίς κατηγορία. Συμπλήρωσε χαρακτηρισμό."})
            if vr is None:
                issues.append({"code":"missing_vat_rate_line","modal":True,
                               "message": f"AA={aa} — Δεν προέκυψε ποσοστό ΦΠΑ για γραμμή."})
            if not acc:
                exp = f"account_{dbg.get('category')}_<rate>%"
                issues.append({"code":"unresolved_account_line","modal":True,
                               "message": f"AA={aa} — Δεν βρέθηκε λογαριασμός για '{dbg.get('category')}', ΦΠΑ {vr}%. Ρύθμισε {exp} στα settings."})

            lcodes_summary.append(acc or "")
            net_val = abs(float(ln.get("net", 0.0)))
            vat_val = abs(float(ln.get("vat", 0.0)))
            lines_out.append({
                "category": cat,
                "vat_rate_in": vr,
                "vat_rate_source": src,
                "vat_rate_snapped": dbg.get("snapped_to"),
                "lcode_detail": acc,
                "debug": dbg,
                "net": _round2(net_val),
                "vat": _round2(vat_val),
                "gross": _round2(net_val + vat_val),
            })


        characts = characts_from_lines(rec)
        if (len({(l.get("vat_rate_in") or 0) for l in lines_out}) > 1) and not characts:
            characts = "Πολλαπλές κατηγορίες ΦΠΑ"

        rows.append({
            "MARK": str(mark),
            "AA": str(aa),
            "DATE": date,
            "AFM_ISSUER": afm_norm or str(afm_raw),
            "ISSUER_NAME": issuer_name,
            "CUSTID": custid_val,
            "NET": _round2(tot_net),
            "VAT": _round2(tot_vat),
            "GROSS": _round2(tot_gross),
            "DOCTYPE": doc_type,
            "REASON": reason,
            "CHARACTS": characts,
            "LINES": lines_out,
            "LCODE_DETAIL_SUMMARY": ", ".join(sorted({c for c in lcodes_summary if c})),
            "LCODE": (lcode_p or ""),
        })

    ok = (len(issues) == 0) and (len(rows) > 0)
    return rows, issues, ok


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


def build_preview_strict_multiclient(
    vat: str,
    credentials_json: str,
    cred_settings_json: str,
    invoices_json: Optional[str] = None,
    client_db: Optional[str] = None,
    base_invoices_dir: str = "data/epsilon",
) -> Dict[str, Any]:
    vat = str(vat)
    paths = resolve_paths_for_vat(vat, invoices_json, client_db, None, base_invoices_dir)

    invoices = load_epsilon_invoices(paths["invoices"])
    credentials = _safe_json_read(credentials_json, default=[])
    settings_all = _safe_json_read(cred_settings_json, default={})
    settings = _select_settings_for_vat(settings_all, vat)

    cred_list = credentials if isinstance(credentials, list) else [credentials]
    active = next((c for c in cred_list if str(c.get("vat")) == vat), (cred_list[0] if cred_list else {}))
    apod_type = (active or {}).get("apodeixakia_type","")
    apod_supplier_id = _safe_int((active or {}).get("apodeixakia_supplier",""))

    issues: List[Dict[str,Any]] = []
    client_map = {"by_afm": {}, "by_id": set(), "names": {}, "cols": []}
    if paths["client_db"] and os.path.exists(paths["client_db"]):
        try:
            cm = _load_client_map(paths["client_db"])
            client_map["by_afm"] = cm.get("by_afm", {})
            client_map["by_id"]  = cm.get("ids", cm.get("by_id", set()))
            client_map["names"]  = cm.get("names", {})
            client_map["cols"]   = cm.get("columns", cm.get("cols", []))
        except Exception as e:
            issues.append({"code":"client_db_read_error","modal":True,
                           "message":f"Σφάλμα ανάγνωσης client_db: {e}"})
    else:
        issues.append({"code":"client_db_missing","modal":True,
                       "message":"Δεν βρέθηκε client_db για αντιστοίχιση CUSTID."})

    if isinstance(invoices, dict):
        for k in ("invoices","records","rows","data","items"):
            if isinstance(invoices.get(k), list):
                invoices = invoices[k]; break
        else:
            invoices = [invoices]

    rows: List[Dict[str,Any]] = []
    artid = 1

    for rec in invoices:
        is_receipt = _is_receipt(rec)
        aa = str(rec.get("AA") or rec.get("aa") or rec.get("mark",""))
        mdate_dt = _to_date(rec.get("issueDate") or rec.get("ΗΜΕΡΟΜΗΝΙΑ"))
        reason = _reason_for_rec_enhanced(rec, is_receipt, client_names=client_map.get("names"))
        afm_issuer = rec.get("AFM_issuer") or rec.get("AFM") or ""

        pairs = _parse_lines(rec)
        sum_net = sum(p["net"] for p in pairs)
        msign = -1 if sum_net < 0 else 1

        # CUSTID
        custid_val: Optional[int] = None
        if is_receipt and apod_type == "supplier":
            custid_val = apod_supplier_id if apod_supplier_id in (client_map["by_id"] or set()) else None
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

        lcode_P_cfg = _account_header_P(settings, is_receipt)

        
        for p in pairs:

        
            net = abs(float(p["net"]))

        
            vat = abs(float(p["vat"]))

        
            vr  = p.get("vat_rate")

        
            cat = p.get("category") or rec.get("category") or ""

        
        

        
            if is_receipt:

        
                accJ, dbg = _account_detail_receipt(settings, vr)

        
            else:

        
                accJ, dbg = _account_detail_invoice(settings, cat, vr)

        
        

        
            if (not cat) and (not is_receipt):

        
                issues.append({"code":"missing_category_line","modal":True,

        
                               "message": f"AA={aa} — Γραμμή χωρίς κατηγορία. Συμπλήρωσε χαρακτηρισμό."})

        
            if vr is None:

        
                issues.append({"code":"missing_vat_rate_line","modal":True,

        
                               "message": f"AA={aa} — Δεν προέκυψε ποσοστό ΦΠΑ για γραμμή."})

        
            if not accJ:

        
                exp = f"account_{dbg.get('category')}_<rate>%"

        
                issues.append({"code":"unresolved_account_line","modal":True,

        
                               "message": f"AA={aa} — Δεν βρέθηκε λογαριασμός για '{dbg.get('category')}', ΦΠΑ {vr}%. Ρύθμισε {exp} στα settings."})

        
            if not lcode_P_cfg:

        
                issues.append({"code":"missing_header_account","modal":True,

        
                               "message": f"AA={aa} — Δεν έχει οριστεί λογαριασμός προμηθευτή (account_supplier_{'retail' if is_receipt else 'wholesale'})."})

        
        

        
        

        
            final_reason = reason or "—"

        
            final_lcodeJ = accJ or ""

        
            final_lcodeP = str(lcode_P_cfg).strip() or ""

        
        

        
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

        
                "DEBUG": dbg,

        
            })

        
        artid += 1

        
        


    # strict validation
    issues_out = list(issues)
    required = ["ARTID","MTYPE","ISKEPYO","ISAGRYP","CUSTID","MDATE","REASON","INVOICE","SUMKEPYOYP",
                "LCODE_DETAIL","ISAGRYP_DETAIL","KEPYOPARTY_DETAIL","NETAMT_DETAIL","VATAMT_DETAIL","MSIGN","LCODE"]
    for r in rows:
        for c in required:
            v = r.get(c, None)
            if v is None or (isinstance(v, str) and not v.strip()):
                issues_out.append({"code":"blank_cell","modal":True,
                                   "message": f"Γραμμή ARTID={r.get('ARTID')} / πεδίο {c}: κενή τιμή (strict).",
                                   "row_artid": r.get("ARTID"), "field": c})

    return {"ok": len(issues_out)==0, "rows": rows, "issues": issues_out, "paths": paths}


# ---------------------------------------------------------------------------
# Export
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
# Flask helper
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
# CLI
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