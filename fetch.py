#!/usr/bin/env python3
# fetch.py
"""
Bulk fetch παραστατικών από myDATA (RequestDocs) και δημιουργία Excel
Χρήση:
  python fetch.py --date-from 01/08/2025 --date-to 31/08/2025 --out out.xlsx [--user AADE_USER] [--key AADE_KEY]
  python fetch.py --dump-creds   # debug: δείχνει credentials που βρέθηκαν
"""

import os
import sys
import json
import argparse
import time
import re
from datetime import datetime
from dateutil.relativedelta import relativedelta
import requests
import xml.etree.ElementTree as ET
from collections import defaultdict
import pandas as pd

# ---------- CONFIG ----------
MARK = "000000000000000"
# default endpoints (sandbox vs prod selection can be done via env MYDATA_ENV)
MYDATA_ENV = (os.getenv("MYDATA_ENV") or "sandbox").lower()
REQUESTDOCS_URL = (
    "https://mydataapidev.aade.gr/RequestDocs"
    if MYDATA_ENV in ("sandbox", "dev", "demo")
    else "https://mydatapi.aade.gr/myDATA/RequestDocs"
)
REQUEST_TRANSMITTED_URL = (
    "https://mydataapidev.aade.gr/RequestTransmittedDocs"
    if MYDATA_ENV in ("sandbox", "dev", "demo")
    else "https://mydatapi.aade.gr/myDATA/RequestTransmittedDocs"
)

# candidate credential locations (checked by load_credentials_for_fetch)
CANDIDATE_CRED_PATHS = [
    os.getenv("CREDENTIALS_FILE", "") or "",
    os.path.join(os.getcwd(), "data", "credentials.json"),
    os.path.join(os.getcwd(), "credentials.json"),
    os.path.join(os.path.dirname(__file__), "data", "credentials.json"),
    os.path.join(os.path.dirname(__file__), "..", "data", "credentials.json"),
    "/app/data/credentials.json",
    "/data/credentials.json",
]

# ---------- helpers ----------
def _safe_strip(x):
    if x is None:
        return ""
    return str(x).strip()

def _read_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        if os.environ.get("DEBUG_FETCH"):
            print(f"[fetch] read_json_file failed for {path}: {e}", file=sys.stderr)
        return None

def load_credentials_for_fetch(pre_user=None, pre_key=None):
    """
    Προσπαθεί να βρει credentials με την εξής προτεραιότητα:
    1) pre_user & pre_key (CLI overrides)
    2) data/credentials.json κ.ά. candidate paths
    3) env vars AADE_USER_ID / AADE_SUBSCRIPTION_KEY
    Επιστρέφει λίστα credential dicts.
    """
    if pre_user and pre_key:
        return [{"name":"cli", "user": pre_user, "key": pre_key, "source": "cli"}]

    creds = None
    found_path = None
    for p in CANDIDATE_CRED_PATHS:
        if not p:
            continue
        if os.path.exists(p):
            maybe = _read_json_file(p)
            if maybe:
                if isinstance(maybe, list):
                    creds = maybe
                elif isinstance(maybe, dict):
                    creds = [maybe]
                if creds:
                    found_path = p
                    break

    if not creds:
        aade_user = os.getenv("AADE_USER_ID") or os.getenv("AADE_USER") or None
        aade_key = os.getenv("AADE_SUBSCRIPTION_KEY") or os.getenv("AADE_KEY") or None
        if aade_user and aade_key:
            creds = [{"name":"env", "user": aade_user, "key": aade_key, "source": "env"}]
            found_path = "env"

    if not creds:
        return []

    # ensure metadata
    for c in creds:
        if "source" not in c:
            c["source"] = found_path or "unknown"
    return creds

def dump_creds(pre_user=None, pre_key=None):
    creds = load_credentials_for_fetch(pre_user, pre_key)
    if not creds:
        print("NO_CREDENTIALS_FOUND")
        return 2
    print("CREDENTIALS_FOUND:", len(creds))
    for i, c in enumerate(creds):
        print(f"--- credential[{i}] (source={c.get('source')}) ---")
        print(json.dumps({k:v for k,v in c.items() if k != "key"}, ensure_ascii=False, indent=2))
    return 0

# XML helpers to robustly find elements by localname
def find_in_element_by_localnames(elem, localnames):
    """Ψάχνει μέσα στο elem (και σε όλο το δέντρο του) για υπο-στοιχεία με localname στη λίστα."""
    if elem is None:
        return ""
    for sub in elem.iter():
        tag = sub.tag
        if isinstance(tag, str) and "}" in tag:
            lname = tag.split("}", 1)[1]
        else:
            lname = tag
        if lname in localnames:
            txt = _safe_strip(sub.text)
            if txt:
                return txt
    return ""

def extract_issuer_info(invoice_elem, ns):
    """
    Επιστρέφει (vatissuer, issuer_name) προσπαθώντας πολλές πιθανές θέσεις.
    - τυπική: invoice/issuer/vatNumber , invoice/issuer/name
    - αλλιώς: ψάχνει οποιοδήποτε descendant με localname vatNumber/name/companyName/partyName/partyType
    """
    vat = ""
    name = ""
    issuer = invoice_elem.find("ns:issuer", ns)
    if issuer is not None:
        vat = _safe_strip(issuer.findtext("ns:vatNumber", default="", namespaces=ns))
        if not vat:
            vat = find_in_element_by_localnames(issuer, ["vatNumber", "VATNumber", "vatnumber"])
        # try issuer/name or descendants
        name = _safe_strip(issuer.findtext("ns:name", default="", namespaces=ns))
        if not name:
            # sometimes the structure uses party/partyName/name or partyType/name etc.
            name = find_in_element_by_localnames(issuer, ["name", "Name", "companyName", "partyName", "partyType"])
    else:
        # fallback searching whole invoice
        vat = find_in_element_by_localnames(invoice_elem, ["vatNumber", "VATNumber", "vatnumber"])
        name = find_in_element_by_localnames(invoice_elem, ["name", "Name", "companyName", "partyName", "partyType"])
    return _safe_strip(vat), _safe_strip(name)

def to_float_safe(x):
    try:
        if x is None:
            return 0.0
        s = str(x).strip()
        if s == "":
            return 0.0
        # remove currency characters, keep digits , . and -
        s2 = re.sub(r"[^\d\-,\.]", "", s)
        if "," in s2 and "." not in s2:
            s2 = s2.replace(".", "").replace(",", ".")
        else:
            s2 = s2.replace(",", "")
        return float(s2)
    except Exception:
        try:
            return float(re.sub(r"[^\d\.]", "", str(x)))
        except Exception:
            return 0.0

# ---------- main fetch logic ----------
def request_docs_loop(aade_user, subscription_key, date_from_ddmmyyyy, date_to_ddmmyyyy, mark=MARK, debug=False):
    """
    Καλεί RequestDocs με σελιδοποίηση (nextPartitionToken). Επιστρέφει λίστα xml invoice elements (as ET.Element)
    """
    headers = {
        "aade-user-id": aade_user,
        "Ocp-Apim-Subscription-Key": subscription_key,
        "Accept": "application/xml",
    }
    params = {"mark": mark, "dateFrom": date_from_ddmmyyyy, "dateTo": date_to_ddmmyyyy}
    invoices = []
    attempt = 0
    while True:
        attempt += 1
        if debug: print(f"[RequestDocs] GET {REQUESTDOCS_URL} params={params}", file=sys.stderr)
        r = requests.get(REQUESTDOCS_URL, params=params, headers=headers, timeout=60)
        if debug: print(f"[RequestDocs] status {r.status_code}", file=sys.stderr)
        if r.status_code != 200:
            raise RuntimeError(f"RequestDocs failed status={r.status_code} body={r.text[:500]}")
        try:
            root = ET.fromstring(r.content)
        except Exception as e:
            raise RuntimeError(f"Failed parse RequestDocs XML: {e}")
        ns = {'ns': 'http://www.aade.gr/myDATA/invoice/v1.0'}
        found = root.findall(".//ns:invoice", ns)
        if debug: print(f"[RequestDocs] found {len(found)} invoices on page {attempt}", file=sys.stderr)
        invoices.extend(found)
        # next token?
        next_token_elem = root.find(".//ns:nextPartitionToken", ns)
        if next_token_elem is not None and _safe_strip(next_token_elem.text):
            params["nextPartitionToken"] = _safe_strip(next_token_elem.text)
            # continue loop
            time.sleep(0.15)
            continue
        break
    return invoices

def request_transmitted_marks(aade_user, subscription_key, date_from_ddmmyyyy, date_to_ddmmyyyy_plus3, mark=MARK, debug=False):
    """
    Καλεί RequestTransmittedDocs για περίοδο date_from..date_to_plus3 και επιστρέφει set of marks που είναι χαρακτηρισμένα.
    Χρησιμοποιεί απλή αναζήτηση invoiceMark tags και όλα τα 15-digit numbers στο XML.
    """
    headers = {
        "aade-user-id": aade_user,
        "Ocp-Apim-Subscription-Key": subscription_key,
        "Accept": "application/xml",
    }
    params = {"mark": mark, "dateFrom": date_from_ddmmyyyy, "dateTo": date_to_ddmmyyyy_plus3}
    if debug: print(f"[RequestTransmittedDocs] GET {REQUEST_TRANSMITTED_URL} params={params}", file=sys.stderr)
    r = requests.get(REQUEST_TRANSMITTED_URL, params=params, headers=headers, timeout=60)
    if r.status_code != 200:
        if debug:
            print(f"[RequestTransmittedDocs] status {r.status_code} body: {r.text[:400]}", file=sys.stderr)
        # return empty set on non-200 (so we don't fail everything)
        return set()
    txt = r.text or ""
    marks = set()
    # try parse XML
    try:
        root = ET.fromstring(r.content)
        for elem in root.iter():
            tag = elem.tag
            local = tag.split("}", 1)[-1] if "}" in tag else tag
            if local.lower() in ("invoicemark", "invoiceMark".lower()) and (elem.text or "").strip():
                marks.add(_safe_strip(elem.text))
            # also if any element text looks like 15-digit number
            if elem.text:
                t = _safe_strip(elem.text)
                if t.isdigit() and len(t) == 15:
                    marks.add(t)
    except Exception:
        # fallback: regex find 15-digit numbers in raw text
        for m in re.findall(r"\b(\d{15})\b", txt):
            marks.add(m)
    # save raw xml for debugging
    try:
        with open("requesttransmitted_raw.xml", "wb") as f:
            f.write(r.content)
    except Exception:
        pass
    if debug:
        print(f"[RequestTransmittedDocs] found {len(marks)} marks", file=sys.stderr)
    return marks

def build_rows_from_invoices(invoice_elements, transmitted_marks_set, debug=False):
    """
    Δεχόμαστε λίστα ET invoice elements. Επιστρέφουμε all_rows (list of dicts) με πεδία:
      mark, issueDate, series, aa, vatCategory, totalNetValue, totalVatAmount, classification, AFM_issuer, Name_issuer
    """
    ns = {'ns': 'http://www.aade.gr/myDATA/invoice/v1.0'}
    all_rows = []
    for inv in invoice_elements:
        mark = _safe_strip(inv.findtext("ns:mark", default="", namespaces=ns))
        header = inv.find("ns:invoiceHeader", ns)
        issueDate = _safe_strip(header.findtext("ns:issueDate", default="", namespaces=ns)) if header is not None else ""
        series = _safe_strip(header.findtext("ns:series", default="", namespaces=ns)) if header is not None else ""
        aa = _safe_strip(header.findtext("ns:aa", default="", namespaces=ns)) if header is not None else ""

        # issuer info
        afm_issuer, name_issuer = extract_issuer_info(inv, ns)

        # collect invoiceDetails - attempt several tag names
        vat_groups = defaultdict(lambda: {"netValue": 0.0, "vatAmount": 0.0})
        details_nodes = inv.findall(".//ns:invoiceDetails", ns)
        if not details_nodes:
            # sometimes invoiceDetails appears multiple times as individual nodes
            # find all nodes whose localname is invoiceDetails or invoiceDetail
            details_nodes = []
            for e in inv.iter():
                tag = e.tag
                local = tag.split("}", 1)[-1] if "}" in tag else tag
                if local.lower() in ("invoicedetails", "invoicedetail", "invoiceDetails".lower(), "invoiceDetail".lower()):
                    details_nodes.append(e)
        # parse details
        if details_nodes:
            for detail in details_nodes:
                # try namespaced first
                net_text = detail.findtext("ns:netValue", default=None, namespaces=ns)
                if net_text is None:
                    net_text = detail.findtext("netValue") or detail.findtext("NetValue") or "0"
                vat_text = detail.findtext("ns:vatAmount", default=None, namespaces=ns)
                if vat_text is None:
                    vat_text = detail.findtext("vatAmount") or detail.findtext("VatAmount") or "0"
                vat_cat = detail.findtext("ns:vatCategory", default=None, namespaces=ns)
                if vat_cat is None:
                    vat_cat = detail.findtext("vatCategory") or detail.findtext("VatCategory") or ""
                net = to_float_safe(net_text)
                vat = to_float_safe(vat_text)
                cat = _safe_strip(vat_cat) or "1"
                vat_groups[cat]["netValue"] += net
                vat_groups[cat]["vatAmount"] += vat
        else:
            # fallback to invoiceSummary totals
            summary_node = inv.find("ns:invoiceSummary", ns)
            if summary_node is not None:
                net = to_float_safe(summary_node.findtext("ns:totalNetValue", default="0", namespaces=ns))
                vat = to_float_safe(summary_node.findtext("ns:totalVatAmount", default="0", namespaces=ns))
                vat_groups["1"]["netValue"] += net
                vat_groups["1"]["vatAmount"] += vat

        # if still empty, ensure at least one group
        if not vat_groups:
            vat_groups["1"]["netValue"] += 0.0
            vat_groups["1"]["vatAmount"] += 0.0

        classification = "αχαρακτηριστο"
        if mark and mark in transmitted_marks_set:
            classification = "χαρακτηρισμενο"

        for vat_cat, totals in vat_groups.items():
            row = {
                "mark": mark,
                "issueDate": issueDate,
                "series": series,
                "aa": aa,
                "vatCategory": vat_cat,
                "totalNetValue": round(totals["netValue"], 2),
                "totalVatAmount": round(totals["vatAmount"], 2),
                "classification": classification,
                "AFM_issuer": afm_issuer,
                "Name_issuer": name_issuer
            }
            all_rows.append(row)
    return all_rows

def build_summary_from_rows(all_rows):
    """
    Δημιουργεί μία γραμμή ανά MARK με συνολικά ποσά και κρατάει AFM/Name εκδότη.
    """
    summary_rows = {}
    for row in all_rows:
        mark = row.get("mark", "")
        if mark not in summary_rows:
            summary_rows[mark] = {
                "mark": mark,
                "issueDate": row.get("issueDate", ""),
                "series": row.get("series", ""),
                "aa": row.get("aa", ""),
                "classification": row.get("classification", ""),
                "totalNetValue": row.get("totalNetValue", 0.0),
                "totalVatAmount": row.get("totalVatAmount", 0.0),
                "AFM_issuer": row.get("AFM_issuer", ""),
                "Name_issuer": row.get("Name_issuer", "")
            }
        else:
            if row.get("classification") == "χαρακτηρισμενο":
                summary_rows[mark]["classification"] = "χαρακτηρισμενο"
            summary_rows[mark]["totalNetValue"] += row.get("totalNetValue", 0.0)
            summary_rows[mark]["totalVatAmount"] += row.get("totalVatAmount", 0.0)
            if not summary_rows[mark]["AFM_issuer"] and row.get("AFM_issuer"):
                summary_rows[mark]["AFM_issuer"] = row.get("AFM_issuer")
            if not summary_rows[mark]["Name_issuer"] and row.get("Name_issuer"):
                summary_rows[mark]["Name_issuer"] = row.get("Name_issuer")
    # add totalValue
    for s in summary_rows.values():
        s["totalValue"] = round(s["totalNetValue"] + s["totalVatAmount"], 2)
    return list(summary_rows.values())

def write_excel(out_path, all_rows, summary_list, debug=False):
    # convert to dataframes and write two sheets
    df_detail = pd.DataFrame(all_rows)
    df_summary = pd.DataFrame(summary_list)

    # ensure columns present
    for col in ("AFM_issuer", "Name_issuer"):
        if col not in df_detail.columns:
            df_detail[col] = ""
        if col not in df_summary.columns:
            df_summary[col] = ""

    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        df_detail.to_excel(writer, sheet_name="invoices_vat_summary_classified", index=False)
        df_summary.to_excel(writer, sheet_name="invoices_summary", index=False)
    if debug:
        print(f"[fetch] Wrote Excel: {out_path}", file=sys.stderr)

# ---------- CLI ----------
def parse_args():
    p = argparse.ArgumentParser(description="Bulk fetch myDATA RequestDocs -> Excel")
    p.add_argument("--date-from", required=False, help="dateFrom dd/mm/YYYY (required unless --dump-creds)")
    p.add_argument("--date-to", required=False, help="dateTo dd/mm/YYYY (required unless --dump-creds)")
    p.add_argument("--out", required=False, help="output xlsx path (required unless --dump-creds)")
    p.add_argument("--user", required=False, help="AADE user id (optional override)")
    p.add_argument("--key", required=False, help="AADE subscription key (optional override)")
    p.add_argument("--dump-creds", action="store_true", help="print credentials found and exit (debug)")
    p.add_argument("--debug", action="store_true", help="enable debug prints")
    return p.parse_args()

def validate_ddmmyyyy(s):
    try:
        return datetime.strptime(s, "%d/%m/%Y")
    except Exception:
        return None

def main():
    args = parse_args()
    debug = bool(args.debug) or bool(os.environ.get("DEBUG_FETCH"))

    if args.dump_creds:
        rc = dump_creds(pre_user=args.user, pre_key=args.key)
        sys.exit(rc)

    if not args.date_from or not args.date_to or not args.out:
        print("Error: --date-from, --date-to and --out are required (or use --dump-creds).", file=sys.stderr)
        sys.exit(4)

    d1 = validate_ddmmyyyy(args.date_from)
    d2 = validate_ddmmyyyy(args.date_to)
    if not d1 or not d2:
        print("Error: Dates must be in dd/mm/YYYY format.", file=sys.stderr)
        sys.exit(5)
    if d1 > d2:
        print("Error: date-from must be <= date-to.", file=sys.stderr)
        sys.exit(6)

    out_path = args.out
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)

    # load credentials
    creds = load_credentials_for_fetch(pre_user=args.user, pre_key=args.key)
    if not creds:
        print("ERROR: No credentials found. Provide --user/--key or create data/credentials.json or set env vars.", file=sys.stderr)
        sys.exit(7)
    cred = creds[0]
    aade_user = cred.get("user")
    aade_key = cred.get("key")
    if debug:
        print(f"[fetch] Using credential source={cred.get('source')} user={aade_user}", file=sys.stderr)

    # Step1: RequestDocs loop
    try:
        invoice_elems = request_docs_loop(aade_user, aade_key, args.date_from, args.date_to, mark=MARK, debug=debug)
    except Exception as e:
        print(f"Error fetching RequestDocs: {e}", file=sys.stderr)
        sys.exit(8)

    if debug:
        print(f"[fetch] Total invoices fetched: {len(invoice_elems)}", file=sys.stderr)

    # Step2: RequestTransmittedDocs with dateTo + 3 months (API expects dd/mm/YYYY strings)
    try:
        date_to_dt = validate_ddmmyyyy(args.date_to)
        date_to_plus3 = (date_to_dt + relativedelta(months=3)).strftime("%d/%m/%Y")
        transmitted_marks = request_transmitted_marks(aade_user, aade_key, args.date_from, date_to_plus3, mark=MARK, debug=debug)
    except Exception as e:
        print(f"Error fetching RequestTransmittedDocs: {e}", file=sys.stderr)
        transmitted_marks = set()

    if debug:
        print(f"[fetch] Transmitted marks count: {len(transmitted_marks)}", file=sys.stderr)

    # Step3: build rows
    try:
        all_rows = build_rows_from_invoices(invoice_elems, transmitted_marks, debug=debug)
    except Exception as e:
        print(f"Error building rows: {e}", file=sys.stderr)
        sys.exit(9)

    # Step4: summary per invoice
    try:
        summary_list = build_summary_from_rows(all_rows)
    except Exception as e:
        print(f"Error building summary: {e}", file=sys.stderr)
        sys.exit(10)

    # Step5: write excel
    try:
        write_excel(out_path, all_rows, summary_list, debug=debug)
    except Exception as e:
        print(f"Error writing Excel: {e}", file=sys.stderr)
        sys.exit(11)

    # success
    print(f"OK: wrote {len(all_rows)} detailed rows and {len(summary_list)} summary rows to {out_path}")
    sys.exit(0)

if __name__ == "__main__":
    main()
