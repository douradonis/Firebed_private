# -*- coding: utf-8 -*-
"""
epsilon_bridge_g_category.py

Γ Κατηγορία Βιβλίων - FastImport Bridge Export
Επεκτείνει το epsilon_bridge_multiclient_strict.py με υποστήριξη για Γ Κατηγορία.

Κύριες διαφορές από Β Κατηγορία:
1. ΥΠΟΧΡΕΩΤΙΚΟΣ κωδικός κίνησης (MTYPE)
2. Λογαριασμοί μορφής ΧΧ-ΧΧ-ΧΧ-ΧΧΧΧ (αντί ΧΧ-ΧΧΧΧ)
3. NETAMT/VATAMT υποχρεωτικά στα ARTICLE_DETAIL
4. Prefix account_g_ για λογαριασμούς
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

# Import από το υπάρχον module
from epsilon_bridge_multiclient_strict import (
    _safe_json_read,
    _to_date,
    _ddmmyyyy,
    _safe_int,
    _round2,
    _norm_key,
    _settings_norm,
    _merge_custom_accounts,
    _canon_category,
    _infer_vat_rate_for_line,
    _is_receipt,
    _parse_lines,
    _reason_for_rec_enhanced,
    _load_client_map,
    resolve_paths_for_vat,
    load_epsilon_invoices,
    _compose_invoice_value,
    _read_active_fiscal_year,
    characts_from_lines,
)


# ============================================================================
# MTYPE (Κωδικός Κίνησης) - ΥΠΟΧΡΕΩΤΙΚΟ για Γ Κατηγορία
# ============================================================================

DEFAULT_MTYPE_MAPPING = {
    'αγορες_εμπορευματων': '1',
    'αγορες_α_υλων': '2',
    'γενικες_δαπανες_με_φπα': '3',
    'αμοιβες_τριτων': '4',
    'δαπανες_χωρις_φπα': '5',
    'εγγυοδοσια': '3',  # Γενικά έξοδα
    'αποδειξακια': '3',  # Γενικά έξοδα
}


def _get_mtype_for_category(settings: Dict[str, Any], canon_category: str) -> str:
    """
    Βρίσκει τον κωδικό κίνησης (MTYPE) για την κατηγορία.
    Ψάχνει πρώτα στις ρυθμίσεις, μετά στο default mapping.
    """
    setts = _settings_norm(settings)
    
    # Ψάξε στις custom ρυθμίσεις
    key = _norm_key(f"mtype_code_{canon_category}")
    if key in setts and setts[key]:
        return str(setts[key]).strip()
    
    # Fallback στο default mapping
    return DEFAULT_MTYPE_MAPPING.get(canon_category, '3')  # Default: Γενικά έξοδα


# ============================================================================
# Λογαριασμοί Γ Κατηγορίας (ΧΧ-ΧΧ-ΧΧ-ΧΧΧΧ)
# ============================================================================

def _validate_g_account_format(account: str) -> bool:
    """Ελέγχει αν ο λογαριασμός έχει μορφή ΧΧ-ΧΧ-ΧΧ-ΧΧΧΧ"""
    pattern = r'^\d{2}-\d{2}-\d{2}-\d{4}$'
    return bool(re.match(pattern, str(account).strip()))


def _account_key_candidates_g(canon: str, rate: int) -> List[str]:
    """Κλειδιά για Γ Κατηγορία (με prefix account_g_)"""
    r = str(int(rate))
    base = f"account_g_{canon}_"
    return [
        _norm_key(base + f"fpa_kat_{r}%"),
        _norm_key(base + f"fpa_kat_{r}"),
        _norm_key(base + f"{r}%"),
        _norm_key(base + f"{r}"),
    ]


def _get_account_for_g(settings: Dict[str, Any], canon: str, rate: int) -> str:
    """Βρίσκει λογαριασμό Γ Κατηγορίας"""
    setts = _settings_norm(settings)
    for key in _account_key_candidates_g(canon, rate):
        val = setts.get(key)
        if val and isinstance(val, str):
            account = val.strip()
            if account and _validate_g_account_format(account):
                return account
    return ""


def _account_header_P_g(settings: Dict[str, Any], is_receipt: bool) -> str:
    """Λογαριασμός προμηθευτή για Γ Κατηγορία"""
    setts = _settings_norm(settings)
    key = _norm_key("account_g_supplier_retail" if is_receipt else "account_g_supplier_wholesale")
    val = setts.get(key, "")
    if isinstance(val, str) and val.strip() and _validate_g_account_format(val.strip()):
        return val.strip()
    return ""


def _account_detail_for_line_g(
    settings: Dict[str, Any],
    category: str,
    is_receipt: bool,
    vat_rate: Optional[int]
) -> Tuple[str, Dict[str, Any]]:
    """
    Εύρεση λογαριασμού για γραμμή - Γ Κατηγορία.
    Παρόμοιο με το _account_detail_for_line αλλά για account_g_ λογαριασμούς.
    """
    canon = _canon_category(category)
    tried: List[str] = []
    chosen = ""
    used_key = ""

    # Forced rate για receipts/εγγυοδοσία
    forced_rate = 0 if (is_receipt or canon == "εγγυοδοσια") else None
    target_rate = int(forced_rate) if forced_rate is not None else (int(vat_rate) if vat_rate is not None else None)

    if target_rate is None:
        return "", {"error": "no_vat_rate", "category": canon}

    setts = _settings_norm(settings)
    for key in _account_key_candidates_g(canon, target_rate):
        tried.append(key)
        val = setts.get(key)
        if val and isinstance(val, str):
            account = val.strip()
            if account and _validate_g_account_format(account):
                chosen = account
                used_key = key
                break

    dbg = {
        "category": canon,
        "vat_in": vat_rate,
        "forced_zero": bool(forced_rate is not None),
        "used_key": used_key,
        "tried_keys": tried,
        "chosen": chosen,
    }
    return chosen, dbg


# ============================================================================
# Preview/Export για Γ Κατηγορία
# ============================================================================

def build_preview_rows_for_ui_g(
    vat: str,
    credentials_json: str = "data/credentials.json",
    cred_settings_json: str = "data/credentials_settings.json",
    invoices_json: Optional[str] = None,
    client_db: Optional[str] = None,
    base_invoices_dir: str = "data/epsilon",
    fiscal_year: Optional[int] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], bool]:
    """
    Δημιουργεί preview rows για Γ Κατηγορία.
    Παρόμοιο με build_preview_rows_for_ui αλλά με:
    - MTYPE υποχρεωτικό
    - Λογαριασμούς account_g_
    - NETAMT/VATAMT στα details
    """
    paths = resolve_paths_for_vat(vat, invoices_json, client_db, None, base_invoices_dir)
    issues: List[Dict[str, Any]] = []

    try:
        invoices = load_epsilon_invoices(paths["invoices"])
    except Exception as e:
        return [], [{"code": "load_fail", "message": f"Αδυναμία φόρτωσης invoices: {e}"}], False

    # Fiscal year filter
    fy = fiscal_year if fiscal_year is not None else _read_active_fiscal_year(base_invoices_dir)
    if fy is not None:
        orig_count = len(invoices)
        invoices = [
            inv for inv in invoices
            if _to_date(inv.get("issueDate") or inv.get("date")) and
            _to_date(inv.get("issueDate") or inv.get("date")).year == fy
        ]
        filtered = orig_count - len(invoices)
        if filtered > 0:
            issues.append({
                "code": "filtered_out_by_year",
                "message": f"Φιλτραρίστηκαν {filtered} εγγραφές εκτός οικ. έτους {fy}"
            })

    credentials = _safe_json_read(credentials_json, default=[])
    settings_all = _safe_json_read(cred_settings_json, default={})

    cred_list = credentials if isinstance(credentials, list) else [credentials]
    active = next((c for c in cred_list if str(c.get("vat")) == str(vat)), (cred_list[0] if cred_list else {}))
    settings_all = _merge_custom_accounts(settings_all, active)
    
    apod_type = (active or {}).get("apodeixakia_type", "")
    apod_supplier_id = _safe_int((active or {}).get("apodeixakia_supplier", ""))
    other_expenses_flag = 1 if bool((active or {}).get("apodeixakia_other_expenses")) else 0

    # Client map
    client_map = {"by_afm": {}, "ids": set(), "names": {}, "columns": []}
    if paths["client_db"] and os.path.exists(paths["client_db"]):
        try:
            cm = _load_client_map(paths["client_db"])
            client_map["by_afm"] = cm.get("by_afm", {})
            client_map["ids"] = cm.get("ids", set())
            client_map["names"] = cm.get("names", {})
            client_map["columns"] = cm.get("columns", [])
        except Exception as e:
            issues.append({"code": "client_db_fail", "message": f"Αδυναμία φόρτωσης client_db: {e}"})

    rows: List[Dict[str, Any]] = []

    for rec in invoices:
        is_receipt = _is_receipt(rec)
        afm_issuer = str(rec.get("AFM_issuer") or rec.get("counterpart_vat") or "").strip()
        
        # CUSTID
        custid_val = None
        if apod_type.lower() == "afm" and is_receipt and apod_supplier_id:
            custid_val = apod_supplier_id
        elif afm_issuer and client_map["by_afm"]:
            custid_val = client_map["by_afm"].get(afm_issuer)
        
        if custid_val is None:
            issues.append({
                "code": "missing_custid",
                "message": f"Δεν βρέθηκε CUSTID για AFM={afm_issuer}, MARK={rec.get('mark')}"
            })
            continue

        # Reason
        reason = _reason_for_rec_enhanced(rec, is_receipt, client_map.get("names"))
        
        # Date
        date_str = _ddmmyyyy(rec.get("issueDate") or rec.get("date"))
        if not date_str:
            issues.append({"code": "missing_date", "message": f"Λείπει ημερομηνία για MARK={rec.get('mark')}"})
            continue

        # Invoice value
        invoice_val = _compose_invoice_value(rec)

        # Parse lines
        lines = _parse_lines(rec)
        if not lines:
            issues.append({"code": "no_lines", "message": f"Δεν βρέθηκαν γραμμές για MARK={rec.get('mark')}"})
            continue

        # Συγκέντρωση ανά κατηγορία + VAT
        aggregated: Dict[Tuple[str, int], Dict[str, Any]] = {}
        sum_net = 0.0
        sum_vat = 0.0

        for ln in lines:
            cat = ln.get("category", "")
            vr = ln.get("vat_rate")
            net = _round2(ln.get("net", 0))
            vat = _round2(ln.get("vat", 0))

            if vr is None:
                issues.append({
                    "code": "missing_vat_rate",
                    "message": f"Λείπει VAT rate για γραμμή στο MARK={rec.get('mark')}"
                })
                continue

            key = (cat, vr)
            if key not in aggregated:
                aggregated[key] = {"net": 0.0, "vat": 0.0, "category": cat, "vat_rate": vr}
            aggregated[key]["net"] += net
            aggregated[key]["vat"] += vat
            sum_net += net
            sum_vat += vat

        if not aggregated:
            continue

        # Δημιουργία γραμμών με MTYPE
        detail_rows = []
        for (cat, vr), agg in aggregated.items():
            canon = _canon_category(cat)
            
            # ΥΠΟΧΡΕΩΤΙΚΟΣ MTYPE
            mtype = _get_mtype_for_category(settings_all, canon)
            if not mtype:
                issues.append({
                    "code": "missing_mtype",
                    "message": f"Λείπει MTYPE για κατηγορία {canon}"
                })
                continue

            # Λογαριασμός Γ Κατηγορίας
            account, dbg = _account_detail_for_line_g(settings_all, cat, is_receipt, vr)
            if not account:
                issues.append({
                    "code": "missing_account_g",
                    "message": f"Δεν βρέθηκε λογαριασμός Γ για {canon}, VAT={vr}%. Tried: {dbg.get('tried_keys')}"
                })
                continue

            detail_rows.append({
                "MTYPE": mtype,
                "LCODE": account,
                "NETAMT": agg["net"],
                "VATAMT": agg["vat"],
                "category": canon,
                "vat_rate": vr,
            })

        if not detail_rows:
            continue

        # Header λογαριασμός (Προμηθευτής)
        account_p = _account_header_P_g(settings_all, is_receipt)
        if not account_p:
            issues.append({
                "code": "missing_supplier_account_g",
                "message": f"Λείπει λογαριασμός προμηθευτή Γ για MARK={rec.get('mark')}"
            })
            continue

        rows.append({
            "CUSTID": custid_val,
            "MDATE": date_str,
            "REASON": reason,
            "INVOICE": invoice_val,
            "ISKEPYO": 0,
            "ISAGRYP": 0,
            "SUMKEPYOYP": round(sum_net, 2),
            "SUMKEPYONOTYP": 0,
            "SUMKEPYOFPA": round(sum_vat, 2),
            "LCODE_HEADER": account_p,
            "OTHEREXPEND": other_expenses_flag,
            "MSIGN": "",
            "details": detail_rows,
            "characts": characts_from_lines(rec),
            "_source": rec,
        })

    ok = len(rows) > 0
    return rows, issues, ok


def build_preview_strict_g_category(
    vat: str,
    credentials_json: str,
    cred_settings_json: str,
    invoices_json: Optional[str] = None,
    client_db: Optional[str] = None,
    base_invoices_dir: str = "data/epsilon",
    fiscal_year: Optional[int] = None,
) -> Dict[str, Any]:
    """Preview για Γ Κατηγορία"""
    rows, issues, ok = build_preview_rows_for_ui_g(
        vat=vat,
        credentials_json=credentials_json,
        cred_settings_json=cred_settings_json,
        invoices_json=invoices_json,
        client_db=client_db,
        base_invoices_dir=base_invoices_dir,
        fiscal_year=fiscal_year
    )
    paths = resolve_paths_for_vat(vat, invoices_json, client_db, None, base_invoices_dir)
    return {"ok": ok and not issues, "rows": rows, "issues": issues, "paths": paths}


def export_g_category(
    vat: str,
    credentials_json: str,
    cred_settings_json: str,
    invoices_json: Optional[str] = None,
    client_db: Optional[str] = None,
    out_xlsx: Optional[str] = None,
    base_invoices_dir: str = "data/epsilon",
    base_exports_dir: str = "exports",
    fiscal_year: Optional[int] = None
) -> Tuple[bool, Optional[str], List[Dict[str, Any]]]:
    """
    Export γέφυρας για Γ Κατηγορία.
    
    Returns:
        (success, output_path, issues)
    """
    preview = build_preview_strict_g_category(
        vat=vat,
        credentials_json=credentials_json,
        cred_settings_json=cred_settings_json,
        invoices_json=invoices_json,
        client_db=client_db,
        base_invoices_dir=base_invoices_dir,
        fiscal_year=fiscal_year
    )
    
    nonfatal_codes = {"filtered_out_by_year"}
    fatals = [i for i in preview["issues"] if str(i.get("code", "")) not in nonfatal_codes]
    if fatals:
        return False, None, preview["issues"]
    
    nonfatal_issues = [i for i in preview["issues"] if str(i.get("code", "")) in nonfatal_codes]

    paths = resolve_paths_for_vat(vat, invoices_json, client_db, out_xlsx, base_invoices_dir, base_exports_dir)
    rows = preview["rows"]

    # Δημιουργία ΚΙΝΗΣΕΙΣ με MTYPE
    flat: List[Dict[str, Any]] = []
    artid = 1
    
    for rec in rows:
        for detail in rec.get("details", []):
            flat.append({
                "ARTID": artid,
                "MTYPE": detail["MTYPE"],  # ΥΠΟΧΡΕΩΤΙΚΟ για Γ
                "ISKEPYO": rec["ISKEPYO"],
                "ISAGRYP": rec["ISAGRYP"],
                "CUSTID": rec["CUSTID"],
                "MDATE": rec["MDATE"],
                "REASON": rec["REASON"],
                "INVOICE": rec["INVOICE"],
                "SUMKEPYOYP": rec["SUMKEPYOYP"],
                "SUMKEPYONOTYP": rec["SUMKEPYONOTYP"],
                "SUMKEPYOFPA": rec["SUMKEPYOFPA"],
                "LCODE": rec["LCODE_HEADER"],
                "MSIGN": rec.get("MSIGN", ""),
                "OTHEREXPEND": rec.get("OTHEREXPEND", 0),
                # ARTICLE_DETAIL fields
                "LCODE_DETAIL": detail["LCODE"],
                "ISAGRYP_DETAIL": rec["ISAGRYP"],
                "KEPYOPARTY": "",
                "NETAMT_DETAIL": detail["NETAMT"],  # ΥΠΟΧΡΕΩΤΙΚΟ για Γ
                "VATAMT_DETAIL": detail["VATAMT"],  # ΥΠΟΧΡΕΩΤΙΚΟ για Γ
                "CRDB": "Χ",
                "AMOUNT": round(detail["NETAMT"] + detail["VATAMT"], 2),
                "INVOICE_DETAIL": rec["INVOICE"],
                "REASON_DETAIL": rec["REASON"],
            })
            artid += 1

    df_moves = pd.DataFrame(flat, columns=[
        "ARTID", "MTYPE", "ISKEPYO", "ISAGRYP", "CUSTID", "MDATE", "REASON", "INVOICE",
        "SUMKEPYOYP", "SUMKEPYONOTYP", "SUMKEPYOFPA", "MSIGN", "LCODE", "OTHEREXPEND",
        "LCODE_DETAIL", "ISAGRYP_DETAIL", "KEPYOPARTY", "CRDB", "AMOUNT",
        "NETAMT_DETAIL", "VATAMT_DETAIL", "INVOICE_DETAIL", "REASON_DETAIL"
    ])

    # Διάβασμα credentials για supplier mode
    try:
        credentials = _safe_json_read(credentials_json, default=[])
    except Exception:
        credentials = []
    
    cred_list = credentials if isinstance(credentials, list) else [credentials]
    active = next((c for c in cred_list if str(c.get("vat")) == str(vat)), (cred_list[0] if cred_list else {}))
    apod_type = (active or {}).get("apodeixakia_type", "")
    apod_supplier_id = _safe_int((active or {}).get("apodeixakia_supplier", ""))

    # Δημιουργία ΣΥΝΑΛΛΑΣΣΟΜΕΝΩΝ
    used_ids = sorted(set(df_moves["CUSTID"].dropna().unique()))
    used_ids_unique = [int(x) for x in used_ids if _safe_int(x) is not None]

    suppliers_data = []
    
    # Load client_db για πληροφορίες
    client_data_by_id = {}
    if paths["client_db"] and os.path.exists(paths["client_db"]):
        try:
            cm = _load_client_map(paths["client_db"])
            # Reverse mapping: id -> afm/name
            afm_by_id = {cid: afm for afm, cid in cm.get("by_afm", {}).items()}
            names = cm.get("names", {})
            for cid in used_ids_unique:
                afm = afm_by_id.get(cid, "")
                name = names.get(afm, f"Συναλλασσόμενος {cid}")
                client_data_by_id[cid] = {"afm": afm, "name": name}
        except Exception:
            pass

    for cid in used_ids_unique:
        info = client_data_by_id.get(cid, {})
        afm = info.get("afm", "")
        name = info.get("name", f"Συναλλασσόμενος {cid}")
        
        suppliers_data.append({
            "CUSTID": cid,
            "NAME": name,
            "VAT": afm,
            "JOB": "",
            "DOYCODE": "",
            "ISKEPYO": 0,
            "ISAGRYP": 0,
            "ADDRESS": "",
            "ZIP": "",
            "CITY": "",
            "PHONE1": "",
        })

    df_suppliers = pd.DataFrame(suppliers_data, columns=[
        "CUSTID", "NAME", "VAT", "JOB", "DOYCODE", "ISKEPYO", "ISAGRYP",
        "ADDRESS", "ZIP", "CITY", "PHONE1"
    ])

    # Εξαγωγή Excel
    out_path = paths["out"]
    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        df_moves.to_excel(writer, sheet_name="Φύλλο1", index=False)
        df_suppliers.to_excel(writer, sheet_name="Φύλλο2", index=False)

    return True, out_path, nonfatal_issues
