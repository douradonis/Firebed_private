# -*- coding: utf-8 -*-
"""
Multi-client STRICT builder for Epsilon FastImport 'ΚΙΝΗΣΕΙΣ' (A..P).

- Dynamic per-VAT: δίνεις οποιοδήποτε VAT και αυτο-λύνει paths.
- STRICT validation: δεν εξάγεται Excel αν υπάρχει κενό κελί σε οποιαδήποτε γραμμή.
- Numeric types στο Excel + πραγματικές ημερομηνίες dd/mm/yyyy.
- Modal warnings: επιστρέφονται ως λίστα dicts (code/message/...).
- Optional per-VAT settings: credentials_settings.json may contain:
    {
      "... global keys ...",
      "by_vat": {
        "123456789": { "... overrides ..." },
        "987654321": { "... overrides ..." }
      }
    }

CLI:
python epsilon_bridge_multiclient_strict.py \
  --vat 802576637 \
  --invoices data/epsilon/802576637_epsilon_invoices.json \
  --credentials data/credentials.json \
  --settings data/credentials_settings.json \
  --clientdb data/epsilon/client_db_802576637.xlsx \
  --out exports/802576637_EPSILON_BRIDGE_KINHSEIS.xlsx
"""
from __future__ import annotations
import os, json, re, argparse
from typing import Any, Dict, List, Tuple, Optional
from datetime import datetime
import copy
import pandas as pd

# ------------------ small helpers ------------------
def _to_date(d: Any) -> Optional[datetime]:
    if not d: return None
    s = str(d)
    for fmt in ("%Y-%m-%d","%d/%m/%Y","%d-%m-%Y","%Y/%m/%d","%d/%m/%y"):
        try: return datetime.strptime(s[:10], fmt)
        except: pass
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", s)
    if m: return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    return None

def _safe_int(x: Any) -> Optional[int]:
    try: return int(float(str(x).strip()))
    except: return None

def _detect_client_cols(df: pd.DataFrame) -> Tuple[str, str]:
    col_afm = col_id = None
    for c in df.columns:
        lc = str(c).lower()
        if col_afm is None and ("αφμ" in lc or lc=="afm" or "vat" in lc): col_afm = c
        if col_id is None and ("συναλλασ" in lc or "κωδ" in lc or lc=="id" or "custid" in lc): col_id = c
    if col_afm is None:
        for c in df.columns:
            if "αφ" in str(c).lower(): col_afm = c; break
    if col_id is None:
        for c in df.columns:
            if "id" in str(c).lower() or "κωδ" in str(c).lower(): col_id = c; break
    if not col_afm or not col_id:
        raise ValueError("Δεν βρέθηκαν στήλες AFM/ID στο client_db.")
    return col_afm, col_id

def _load_client_map(client_db_path: str) -> Dict[str, Any]:
    df = pd.read_excel(client_db_path)  # openpyxl(.xlsx) / xlrd(.xls)
    col_afm, col_id = _detect_client_cols(df)
    by_afm, by_id = {}, set()
    for _, r in df.iterrows():
        afm = str(r.get(col_afm,"")).strip()
        cid = _safe_int(r.get(col_id))
        if afm and cid is not None:
            by_afm[afm] = cid
            by_id.add(cid)
    return {"by_afm": by_afm, "by_id": by_id, "cols": list(df.columns)}

def _vat_rate(label: Any, net: float, vat: float) -> Optional[int]:
    m = re.search(r"(\d+)[\.,]?\d*\s*%", str(label) if label is not None else "")
    if m: return int(m.group(1))
    if net:
        try: return int(round((vat/net)*100))
        except: return None
    return None

def _parse_lines(rec: Dict[str, Any]) -> List[Dict[str, Any]]:
    lines = rec.get("lines") or rec.get("invoice_lines") or rec.get("details") or []
    out: List[Dict[str, Any]] = []
    if isinstance(lines, list) and lines:
        for ln in lines:
            net = float(str(ln.get("amount","0")).replace(",", ".")) if str(ln.get("amount","")).strip()!="" else 0.0
            vat = float(str(ln.get("vat","0")).replace(",", ".")) if str(ln.get("vat","")).strip()!="" else 0.0
            vr  = _vat_rate(ln.get("vat_category") or ln.get("vatRate"), net, vat)
            cat = (ln.get("category") or "").strip().lower().replace(" ","_")
            out.append({"net": net, "vat": vat, "vat_rate": vr, "category": cat})
    if not out:
        net = float(str(rec.get("totalNetValue","0")).replace(",", ".")) if str(rec.get("totalNetValue","")).strip()!="" else 0.0
        vat = float(str(rec.get("totalVatAmount","0")).replace(",", ".")) if str(rec.get("totalVatAmount","")).strip()!="" else 0.0
        vr  = _vat_rate(rec.get("vatCategory"), net, vat)
        cat = (rec.get("category","") or "").lower().replace(" ","_")
        out = [{"net": net, "vat": vat, "vat_rate": vr, "category": cat}]
    return out

def _is_receipt(rec: Dict[str, Any]) -> bool:
    t = (rec.get("type") or "").lower()
    return any(k in t for k in ["receipt","αποδείξ","αποδειξη"])

# ------------------ settings per VAT ------------------
def _deep_merge_dict(base: Dict[str,Any], override: Dict[str,Any]) -> Dict[str,Any]:
    out = copy.deepcopy(base)
    for k,v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge_dict(out[k], v)
        else:
            out[k] = v
    return out

def _select_settings_for_vat(settings: Dict[str,Any], vat: str) -> Dict[str,Any]:
    """
    Αν υπάρχουν overrides υπό 'by_vat' για το συγκεκριμένο VAT,
    τα κάνει merge πάνω στα global settings.
    """
    by_vat = settings.get("by_vat")
    if isinstance(by_vat, dict):
        spec = by_vat.get(str(vat))
        if isinstance(spec, dict):
            # μην επιστρέψεις την 'by_vat' μέσα στο merged:
            base = {k:v for k,v in settings.items() if k != "by_vat"}
            return _deep_merge_dict(base, spec)
    return settings

# ------------------ account resolution (STRICT) ------------------
def _canon_category(raw: str) -> str:
    s = (raw or "").lower().replace(" ", "_")
    if "εμπορ" in s or "εμπορευ" in s or "αγορ" in s: return "αγορες_εμπορευματων"
    if "α_υλων" in s or "πρωτ" in s or "υλη" in s:   return "αγορες_α_υλων"
    if "χωρις_φπα" in s or "0%" in s or "μη_υποκειμ" in s: return "δαπανες_χωρις_φπα"
    if "δαπαν" in s or "γενικ" in s or "εξοδ" in s: return "γενικες_δαπανες"
    return s

def _account_detail_invoice(settings_for_vat: Dict[str,Any], category: str, vat_rate: Optional[int]) -> Optional[str]:
    canon = _canon_category(category)
    vr = str(vat_rate if vat_rate is not None else 0)
    # flat key
    key = f"account_{canon}_{vr}"
    val = settings_for_vat.get(key)
    if isinstance(val, str) and val.strip(): return val.strip()
    # nested
    abv = settings_for_vat.get("accounts_by_vat") or settings_for_vat.get("account_map_by_vat")
    if isinstance(abv, dict):
        node = abv.get(canon)
        if isinstance(node, dict):
            v = node.get(vr)
            if isinstance(v, str) and v.strip(): return v.strip()
    return None

def _account_detail_receipt(settings_for_vat: Dict[str,Any], vat_rate: Optional[int]) -> Optional[str]:
    vr = str(vat_rate if vat_rate is not None else 0)
    key = f"account_αποδειξακια_{vr}"
    if key in settings_for_vat and str(settings_for_vat[key]).strip():
        return str(settings_for_vat[key]).strip()
    if "account_αποδειξακια_0" in settings_for_vat and str(settings_for_vat["account_αποδειξακια_0"]).strip():
        return str(settings_for_vat["account_αποδειξακια_0"]).strip()
    return None

def _account_header_P(settings_for_vat: Dict[str,Any], is_receipt: bool) -> Optional[str]:
    return (settings_for_vat.get("account_supplier_retail") if is_receipt
            else settings_for_vat.get("account_supplier_wholesale"))

# ------------------ path resolver per VAT ------------------
def resolve_paths_for_vat(
    vat: str,
    invoices_json: Optional[str] = None,
    client_db: Optional[str] = None,
    out_xlsx: Optional[str] = None,
    base_invoices_dir: str = "data/epsilon",
    base_exports_dir: str = "exports",
) -> Dict[str,str]:
    vat = str(vat)
    # invoices
    candidates_inv = [
        invoices_json,
        os.path.join(base_invoices_dir, f"{vat}_epsilon_invoices.json"),
        os.path.join(base_invoices_dir, "epsilon_invoices.json"),
        f"{vat}_epsilon_invoices.json",
    ]
    invoices_path = next((p for p in candidates_inv if p and os.path.exists(p)), candidates_inv[1])

    # client_db
    candidates_db = [
        client_db,
        os.path.join(base_invoices_dir, f"client_db_{vat}.xlsx"),
        os.path.join(base_invoices_dir, f"client_db_{vat}.xls"),
        os.path.join(base_invoices_dir, "client_db.xlsx"),
        os.path.join(base_invoices_dir, "client_db.xls"),
        "client_db.xlsx",
        "client_db.xls",
    ]
    client_db_path = next((p for p in candidates_db if p and os.path.exists(p)), candidates_db[1])

    # out
    out_path = out_xlsx or os.path.join(base_exports_dir, f"{vat}_EPSILON_BRIDGE_KINHSEIS.xlsx")
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    return {"invoices": invoices_path, "client_db": client_db_path, "out": out_path}

# ------------------ PREVIEW (validate-only) ------------------
def build_preview_strict_multiclient(
    vat: str,
    credentials_json: str,
    cred_settings_json: str,
    invoices_json: Optional[str] = None,
    client_db: Optional[str] = None,
    base_invoices_dir: str = "data/epsilon",
) -> Dict[str, Any]:
    """Επιστρέφει { ok, rows, issues, paths } — δεν γράφει Excel."""
    vat = str(vat)
    paths = resolve_paths_for_vat(vat, invoices_json, client_db, None, base_invoices_dir)

    invoices = json.load(open(paths["invoices"], "r", encoding="utf-8"))
    credentials = json.load(open(credentials_json, "r", encoding="utf-8"))
    settings_all = json.load(open(cred_settings_json, "r", encoding="utf-8"))
    settings = _select_settings_for_vat(settings_all, vat)

    # active cred (για apodeixakia)
    cred_list = credentials if isinstance(credentials, list) else [credentials]
    active = next((c for c in cred_list if str(c.get("vat")) == vat), (cred_list[0] if cred_list else {}))
    apod_type = (active or {}).get("apodeixakia_type","")
    apod_supplier_id = _safe_int((active or {}).get("apodeixakia_supplier",""))

    issues: List[Dict[str,Any]] = []
    client_map = {"by_afm": {}, "by_id": set(), "cols": []}
    if paths["client_db"] and os.path.exists(paths["client_db"]):
        try:
            client_map = _load_client_map(paths["client_db"])
        except Exception as e:
            issues.append({"code":"client_db_read_error","modal":True,"message":f"Σφάλμα ανάγνωσης client_db: {e}"})
    else:
        issues.append({"code":"client_db_missing","modal":True,"message":"Δεν βρέθηκε client_db για αντιστοίχιση CUSTID."})

    # normalize invoices
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
        if not aa:
            issues.append({"code":"missing_invoice_no","modal":True,"message":"Λείπει αριθμός παραστατικού (AA/mark)."})
        mdate_dt = _to_date(rec.get("issueDate") or rec.get("ΗΜΕΡΟΜΗΝΙΑ"))
        if not mdate_dt:
            issues.append({"code":"missing_date","modal":True,"message":f"AA={aa}: Λείπει/μη έγκυρη ημερομηνία."})
        name_issuer = rec.get("Name_issuer") or rec.get("issuerName") or ""
        afm_issuer = rec.get("AFM_issuer") or rec.get("AFM") or ""
        reason = (f"{name_issuer} ({afm_issuer})" if is_receipt
                  else (rec.get("ΑΙΤΙΟΛΟΓΙΑ") or rec.get("reason") or name_issuer))

        pairs = _parse_lines(rec)
        sum_net = sum(p["net"] for p in pairs)
        msign = -1 if sum_net < 0 else 1

        # CUSTID
        custid_val: Optional[int] = None
        if is_receipt and apod_type == "supplier":
            custid_val = apod_supplier_id
            if (custid_val is None) or (custid_val not in client_map["by_id"]):
                issues.append({"code":"apodeixakia_supplier_not_in_client_db","modal":True,
                               "message": f"ΑΠΟΔΕΙΞΗ AA={aa}: apodeixakia_supplier={apod_supplier_id} δεν υπάρχει στο client_db."})
        else:
            if afm_issuer:
                cid = client_map["by_afm"].get(str(afm_issuer))
                if cid is None:
                    issues.append({"code":"custid_missing","modal":True,
                                   "message": f"{'ΤΙΜΟΛΟΓΙΟ' if not is_receipt else 'ΑΠΟΔΕΙΞΗ'} AA={aa}: Δεν βρέθηκε CUSTID για ΑΦΜ {afm_issuer}."})
                else:
                    custid_val = int(cid)
            else:
                issues.append({"code":"issuer_afm_missing","modal":True,
                               "message": f"AA={aa}: Λείπει ΑΦΜ εκδότη για αντιστοίχιση CUSTID."})

        # Accounts
        lcode_P = _account_header_P(settings, is_receipt)
        if not lcode_P or not str(lcode_P).strip():
            issues.append({"code":"header_lcode_missing","modal":True,
                           "message": f"{'ΤΙΜΟΛΟΓΙΟ' if not is_receipt else 'ΑΠΟΔΕΙΞΗ'} AA={aa}: Λείπει account_supplier_{'retail' if is_receipt else 'wholesale'} στο credentials_settings.json."})
            lcode_P = None

        for p in pairs:
            net = abs(float(p["net"])); vat = abs(float(p["vat"])); vr = p["vat_rate"]; cat = p["category"]
            if is_receipt:
                lcode_J = _account_detail_receipt(settings, vr)
                if not lcode_J:
                    issues.append({"code":"receipt_lcode_detail_missing","modal":True,
                                   "message": f"ΑΠΟΔΕΙΞΗ AA={aa}: Λείπει account_αποδειξακια_{vr if vr is not None else 0}."})
            else:
                lcode_J = _account_detail_invoice(settings, cat, vr)
                if not lcode_J:
                    issues.append({"code":"invoice_lcode_detail_missing","modal":True,
                                   "message": f"ΤΙΜΟΛΟΓΙΟ AA={aa}: Λείπει λογαριασμός για κατηγορία '{_canon_category(cat)}' και ΦΠΑ {vr}%."})

            rows.append({
                "ARTID": int(artid),
                "MTYPE": int(1 if (is_receipt or "αγορ" in (cat or "") or "δαπ" in (cat or "")) else 0),
                "ISKEPYO": 1,
                "ISAGRYP": 0,
                "CUSTID": (int(custid_val) if custid_val is not None else None),
                "MDATE": mdate_dt,
                "REASON": reason,
                "INVOICE": aa,
                "SUMKEPYOYP": float(abs(sum_net)),
                "LCODE_DETAIL": (lcode_J or None),
                "ISAGRYP_DETAIL": 0,
                "KEPYOPARTY_DETAIL": float(abs(net)),
                "NETAMT_DETAIL": float(abs(net)),
                "VATAMT_DETAIL": float(abs(vat)),
                "MSIGN": int(msign),
                "LCODE": (str(lcode_P).strip() if lcode_P else None),
            })
        artid += 1

    # strict: no blanks in any cell
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

# ------------------ EXPORT (blocks if issues exist) ------------------
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

# ------------------ Flask convenience ------------------
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

# ------------------ CLI ------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vat", required=True)
    ap.add_argument("--invoices", default=None)
    ap.add_argument("--clientdb", default=None)
    ap.add_argument("--credentials", default="data/credentials.json")
    ap.add_argument("--settings",    default="data/credentials_settings.json")
    ap.add_argument("--out",         default=None)
    ap.add_argument("--invoices_dir", default="data/epsilon")
    ap.add_argument("--exports_dir",  default="exports")
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
            print(" -", i["message"])
        return
    print("Wrote:", path)

if __name__ == "__main__":
    main()
