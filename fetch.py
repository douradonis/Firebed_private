#!/usr/bin/env python3
# fetch.py
"""
CLI wrapper that calls mydata.request_docs and writes results to an Excel file.

Usage:
  python fetch.py --date-from 01/09/2025 --date-to 30/09/2025 --out out.xlsx --user tester97 --key SUBS_KEY

The frontend can call this script (subprocess) and then serve the produced XLSX.
"""
from typing import Any, Dict, List, Optional
import argparse
import sys
import os
import json
import logging
from datetime import datetime
import pandas as pd

# import the mydata module (must be in project root)
import mydata

logging.basicConfig(stream=sys.stdout, level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
log = logging.getLogger("fetch")

def parse_date_input(s: str) -> Optional[str]:
    """Accept dd/mm/YYYY or ISO (YYYY-MM-DD or full iso) and return YYYY-MM-DD or None."""
    if not s:
        return None
    s = s.strip()
    # try dd/mm/YYYY
    try:
        if "/" in s:
            d = datetime.strptime(s, "%d/%m/%Y")
            return d.date().isoformat()
        # try ISO date (YYYY-MM-DD)
        d = datetime.fromisoformat(s)
        return d.date().isoformat()
    except Exception:
        return None

def extract_mark_from_obj(o: Any) -> Optional[str]:
    """Recursively search object (dict/list/str) for a 15-digit MARK and return first found."""
    import re
    if o is None:
        return None
    if isinstance(o, str):
        m = re.search(r"\b(\d{15})\b", o)
        if m:
            return m.group(1)
        return None
    if isinstance(o, (int, float)):
        s = str(int(o)) if isinstance(o, int) else str(o)
        if len(s) == 15 and s.isdigit():
            return s
        return None
    if isinstance(o, dict):
        for k, v in o.items():
            mm = extract_mark_from_obj(v)
            if mm:
                return mm
    if isinstance(o, list):
        for v in o:
            mm = extract_mark_from_obj(v)
            if mm:
                return mm
    return None

def find_issuer_fields(doc: Dict[str, Any]) -> (str, str):
    """
    Try to extract AFM (vatNumber) and issuer name from parsed xml->dict.
    Search common keys under invoice/issuer and recursively for vatNumber/name/partyType/name etc.
    """
    afm = ""
    name = ""

    def walk(o):
        nonlocal afm, name
        if isinstance(o, dict):
            for k, v in o.items():
                kl = str(k).lower()
                if not afm and kl.endswith("vatnumber") or kl == "vatnumber" or kl == "vat_number" or "vat" in kl and "number" in kl:
                    afm_try = _to_str(v)
                    if afm_try and len(''.join(filter(str.isdigit, afm_try))) >= 7:
                        afm = afm_try.strip()
                if not name and (kl in ("name", "companyname", "partyname", "partytype", "issuername")):
                    name_try = _to_str(v)
                    if name_try:
                        name = name_try.strip()
                # recurse
                if isinstance(v, (dict, list)):
                    walk(v)
        elif isinstance(o, list):
            for i in o:
                walk(i)

    def _to_str(x):
        if x is None:
            return ""
        if isinstance(x, str):
            return x
        try:
            return str(x)
        except Exception:
            return ""

    # Common entrypoints
    candidates = []
    if isinstance(doc, dict):
        # sometimes response root is RequestedDoc -> invoicesDoc -> invoice (single or list)
        # collect potential invoice nodes
        def collect_invoices(obj):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if k.lower() in ("invoice", "invoices", "invoicesdoc", "invoicesdoc"):
                        if isinstance(v, list):
                            candidates.extend(v)
                        else:
                            candidates.append(v)
                    else:
                        collect_invoices(v)
            elif isinstance(obj, list):
                for it in obj:
                    collect_invoices(it)
        collect_invoices(doc)

    # If none found, just walk whole doc
    if not candidates:
        walk(doc)
    else:
        # examine first candidate invoice node (most responses are per-invoice)
        for inv in candidates:
            walk(inv)
            if afm or name:
                break

    # last resort: walk entire doc
    if not afm and not name:
        walk(doc)

    return (afm or "", name or "")

def main(argv=None):
    parser = argparse.ArgumentParser(prog="fetch.py", description="Bulk fetch myDATA docs and write to XLSX")
    parser.add_argument("--date-from", required=True, help="dateFrom (dd/mm/YYYY or ISO)")
    parser.add_argument("--date-to", required=True, help="dateTo (dd/mm/YYYY or ISO)")
    parser.add_argument("--user", required=False, help="AADE user id (overrides env)")
    parser.add_argument("--key", required=False, help="AADE subscription key (overrides env)")
    parser.add_argument("--out", required=True, help="Output xlsx path")
    parser.add_argument("--dummy-mark", required=False, default="000000000000000", help="dummy MARK to pass")
    parser.add_argument("--throttle", type=float, default=0.2, help="throttle between paginated requests")
    args = parser.parse_args(argv)

    d1_iso = parse_date_input(args.date_from)
    d2_iso = parse_date_input(args.date_to)
    if not d1_iso or not d2_iso:
        log.error("Invalid dates. Provide dd/mm/YYYY or ISO. Got: %s / %s", args.date_from, args.date_to)
        return 2

    # mydata.request_docs expects YYYY-MM-DD strings
    date_from_arg = d1_iso
    date_to_arg = d2_iso

    log.info("RequestDocs dateFrom=%s dateTo=%s (dummy_mark=%s)", date_from_arg, date_to_arg, args.dummy_mark)

    try:
        docs = mydata.request_docs(
            date_from=date_from_arg,
            date_to=date_to_arg,
            dummy_mark=args.dummy_mark,
            throttle=args.throttle,
            aade_user=args.user,
            subscription_key=args.key,
        )
    except Exception as e:
        log.exception("RequestDocs failed: %s", e)
        print(f"ERROR RequestDocs failed: {e}", file=sys.stderr)
        return 3

    log.info("Fetched %d documents", len(docs) if docs else 0)

    rows = []
    summary_rows = []
    for doc in docs:
        # doc is already a Python dict from xmltodict
        mark = extract_mark_from_obj(doc) or ""
        afm, issuer_name = find_issuer_fields(doc)
        raw_json = json.dumps(doc, ensure_ascii=False)
        rows.append({
            "MARK": mark,
            "AFM_issuer": afm,
            "Name_issuer": issuer_name,
            "raw_json": raw_json
        })
        summary_rows.append({
            "MARK": mark,
            "AFM_issuer": afm,
            "Name_issuer": issuer_name
        })

    # Ensure out dir exists
    out_path = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)

    # Write Excel with two sheets
    try:
        df_raw = pd.DataFrame(rows)
        df_summary = pd.DataFrame(summary_rows)
        with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
            df_raw.to_excel(writer, sheet_name="raw_docs", index=False)
            df_summary.to_excel(writer, sheet_name="summary_marks", index=False)
        log.info("Wrote %s (rows: %d)", out_path, len(rows))
        print(f"OK: wrote {out_path} with {len(rows)} docs")
        return 0
    except Exception as e:
        log.exception("Failed to write excel: %s", e)
        print(f"ERROR: failed to write excel: {e}", file=sys.stderr)
        return 4

if __name__ == "__main__":
    sys.exit(main())
