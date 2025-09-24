# fetch.py
"""
Bulk fetch myDATA invoices -> Excel
Usage (CLI):
    python fetch.py --user USER_ID --key SUBS_KEY --date-from 12/05/2025 --date-to 12/05/2025
Environment fallback:
    AADE_USER_ID, AADE_SUBSCRIPTION_KEY
Output:
    invoices_vat_summary_classified.xlsx (two sheets)
    requesttransmitted_raw.xml
"""
import os
import argparse
import requests
import xml.etree.ElementTree as ET
import pandas as pd
from collections import defaultdict
from datetime import datetime
try:
    from dateutil.relativedelta import relativedelta
except Exception:
    # if dateutil not installed, implement a simple month-add fallback (handles day of month poorly)
    def relativedelta(months=0):
        class R:
            def __init__(self, months):
                self.months = months
        return R(months)

    def _add_months(dt, months):
        y = dt.year + (dt.month - 1 + months) // 12
        m = (dt.month - 1 + months) % 12 + 1
        d = min(dt.day, [31,
                         29 if (y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)) else 28,
                         31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1])
        return datetime(y, m, d)
else:
    _add_months = None

DEBUG = True

MARK = "000000000000000"

URL_REQUEST_DOCS = "https://mydatapi.aade.gr/myDATA/RequestDocs"
URL_REQUEST_TRANSMITTED = "https://mydatapi.aade.gr/myDATA/RequestTransmittedDocs"

def _safe_strip(s):
    if s is None:
        return ""
    return str(s).strip()

def to_float_safe(x):
    try:
        if x is None:
            return 0.0
        s = str(x).strip()
        if s == "":
            return 0.0
        s2 = ''.join(ch for ch in s if ch.isdigit() or ch in ",.-")
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

def find_in_element_by_localnames(elem, localnames):
    """
    Ψάχνει μέσα στο elem (και σε όλο το δέντρο του) για οποιοδήποτε υπο-στοιχείο
    whose localname (tag without namespace) ανήκει στη λίστα localnames.
    Επιστρέφει το πρώτο non-empty text.
    """
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
    Επιστρέφει tuple (vatissuer, issuer_name).
    Προσπαθεί πολλές πιθανές διαδρομές:
    - invoice/issuer/vatNumber
    - invoice/issuer/party/.../vatNumber
    - invoice/issuer/name  κ.λπ.
    """
    vat = ""
    name = ""

    issuer = invoice_elem.find("ns:issuer", ns)
    if issuer is not None:
        vat = _safe_strip(issuer.findtext("ns:vatNumber", default="", namespaces=ns))
        if not vat:
            vat = find_in_element_by_localnames(issuer, ["vatNumber", "VATNumber", "vatnumber"])
        # try issuer/name
        name = _safe_strip(issuer.findtext("ns:name", default="", namespaces=ns))
        if not name:
            # try partyType/name, partyName, companyName etc.
            name = find_in_element_by_localnames(issuer, ["name", "Name", "companyName", "partyName", "partyType", "party"])
    else:
        # fallback search at invoice level
        vat = find_in_element_by_localnames(invoice_elem, ["vatNumber", "VATNumber", "vatnumber"])
        name = find_in_element_by_localnames(invoice_elem, ["name", "Name", "companyName", "partyName", "partyType", "party"])

    return _safe_strip(vat), _safe_strip(name)

def parse_request_docs(response_content):
    """
    Parse RequestDocs XML content and return list of invoice elements
    using ElementTree root.
    """
    try:
        root = ET.fromstring(response_content)
    except Exception as e:
        raise ValueError(f"XML parse error RequestDocs: {e}")
    return root

def collect_invoice_rows(root, ns):
    all_rows = []
    for invoice in root.findall(".//ns:invoice", ns):
        mark = _safe_strip(invoice.findtext("ns:mark", default="", namespaces=ns))
        header = invoice.find("ns:invoiceHeader", ns)
        issueDate = _safe_strip(header.findtext("ns:issueDate", default="", namespaces=ns)) if header is not None else ""
        series = _safe_strip(header.findtext("ns:series", default="", namespaces=ns)) if header is not None else ""
        aa = _safe_strip(header.findtext("ns:aa", default="", namespaces=ns)) if header is not None else ""

        vatissuer, Name_issuer = extract_issuer_info(invoice, ns)
        # collect vat groups
        vat_groups = defaultdict(lambda: {"netValue": 0.0, "vatAmount": 0.0})
        # find detail nodes robustly
        details_nodes = invoice.findall(".//ns:invoiceDetails", ns)
        if not details_nodes:
            details_nodes = invoice.findall(".//ns:invoiceDetail", ns)
        # If invoiceDetails is a container and inside there are many invoiceDetails (same name),
        # ET will return each matching; to be safe iterate through any descendant that has netValue.
        if not details_nodes:
            # try to find any element that contains netValue child
            for elem in invoice.iter():
                if elem.find("ns:netValue", ns) is not None or elem.find("netValue") is not None:
                    details_nodes.append(elem)

        for detail in details_nodes:
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

        # fallback to invoiceSummary if nothing found
        if not vat_groups or all(v["netValue"] == 0 and v["vatAmount"] == 0 for v in vat_groups.values()):
            summary_node = invoice.find("ns:invoiceSummary", ns)
            if summary_node is not None:
                net = to_float_safe(summary_node.findtext("ns:totalNetValue", default="0", namespaces=ns))
                vat = to_float_safe(summary_node.findtext("ns:totalVatAmount", default="0", namespaces=ns))
                vat_groups = defaultdict(lambda: {"netValue": 0.0, "vatAmount": 0.0})
                vat_groups["1"]["netValue"] += net
                vat_groups["1"]["vatAmount"] += vat

        for vat_cat, totals in vat_groups.items():
            row = {
                "mark": mark,
                "issueDate": issueDate,
                "series": series,
                "aa": aa,
                "vatCategory": vat_cat,
                "totalNetValue": round(totals["netValue"], 2),
                "totalVatAmount": round(totals["vatAmount"], 2),
                "classification": "αχαρακτηριστο",
                "AFM_issuer": vatissuer,
                "Name_issuer": Name_issuer
            }
            all_rows.append(row)
    return all_rows

def fetch_transmitted_marks(url, headers, params, debug=False):
    """
    Καλεί RequestTransmittedDocs με params και επιστρέφει set από invoiceMark που βρέθηκαν.
    """
    try:
        r = requests.get(url, params=params, headers=headers, timeout=60)
    except Exception as e:
        if debug:
            print("RequestTransmittedDocs request error:", e)
        return set(), None

    if r.status_code != 200:
        if debug:
            print("[RequestTransmittedDocs] non-200:", r.status_code, r.text[:300])
        return set(), r.text

    transmitted = set()
    try:
        root_trans = ET.fromstring(r.content)
        for elem in root_trans.iter():
            tag = elem.tag
            local = tag.split("}", 1)[-1] if "}" in tag else tag
            if local.lower() == "invoicemark" and elem.text:
                transmitted.add(_safe_strip(elem.text))
            else:
                # also consider any 15-digit numeric text inside response
                if elem.text:
                    txt = _safe_strip(elem.text)
                    if txt.isdigit() and len(txt) == 15:
                        transmitted.add(txt)
    except Exception as e:
        if debug:
            print("Parse transmitted XML error:", e)
        # fallback: try text scan for 15-digit sequences
        try:
            txt_all = r.text or ""
            import re
            for m in re.findall(r"\b(\d{15})\b", txt_all):
                transmitted.add(m)
        except Exception:
            pass

    return transmitted, r.content

def main(user_id, subs_key, date_from, date_to, out_filename="invoices_vat_summary_classified.xlsx"):
    headers = {
        "aade-user-id": user_id,
        "Ocp-Apim-Subscription-Key": subs_key
    }

    # Step 1: RequestDocs (single call using MARK constant + date range)
    params_docs = {"mark": MARK, "dateFrom": date_from, "dateTo": date_to}
    try:
        resp = requests.get(URL_REQUEST_DOCS, params=params_docs, headers=headers, timeout=60)
    except Exception as e:
        print("RequestDocs request error:", e)
        return

    if DEBUG:
        print("[RequestDocs] Status Code:", resp.status_code)

    if resp.status_code != 200:
        print("RequestDocs non-200:", resp.status_code)
        print(resp.text[:500])
        return

    try:
        root = parse_request_docs(resp.content)
    except Exception as e:
        print(e)
        return

    ns = {'ns': 'http://www.aade.gr/myDATA/invoice/v1.0'}
    all_rows = collect_invoice_rows(root, ns)

    if DEBUG:
        print(f"Collected {len(all_rows)} VAT-detail rows from RequestDocs.")

    # Step 2: RequestTransmittedDocs with dateTo + 3 months
    date_format = "%d/%m/%Y"
    try:
        dt_to = datetime.strptime(date_to, date_format)
        if _add_months:
            dt_to_trans = _add_months(dt_to, 3)
        else:
            dt_to_trans = dt_to + relativedelta(months=3)
        date_to_trans = dt_to_trans.strftime(date_format)
    except Exception:
        # if parse fail, default to same date
        date_to_trans = date_to

    params_trans = {"mark": MARK, "dateFrom": date_from, "dateTo": date_to_trans}
    transmitted_marks, raw_trans_content = fetch_transmitted_marks(URL_REQUEST_TRANSMITTED, headers, params_trans, debug=DEBUG)
    if raw_trans_content:
        try:
            with open("requesttransmitted_raw.xml", "wb") as f:
                if isinstance(raw_trans_content, bytes):
                    f.write(raw_trans_content)
                else:
                    f.write(raw_trans_content.encode("utf-8"))
            if DEBUG:
                print("Saved requesttransmitted_raw.xml")
        except Exception as e:
            if DEBUG:
                print("Could not save requesttransmitted_raw.xml:", e)

    if DEBUG:
        print("Transmitted marks found:", len(transmitted_marks))

    # Step 3: Update classification
    updated_count = 0
    for row in all_rows:
        m = _safe_strip(row.get("mark", ""))
        if m in transmitted_marks:
            row["classification"] = "χαρακτηρισμενο"
            updated_count += 1
    if DEBUG:
        print("Updated classified rows:", updated_count)

    # Step 4: Create summary per invoice (aggregate)
    summary_rows = {}
    for row in all_rows:
        mark = row["mark"]
        if mark not in summary_rows:
            summary_rows[mark] = {
                "mark": mark,
                "issueDate": row.get("issueDate", ""),
                "series": row.get("series", ""),
                "aa": row.get("aa", ""),
                "classification": row.get("classification", "αχαρακτηριστο"),
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

    summary_list = list(summary_rows.values())

    # Step 5: Save Excel with two sheets
    with pd.ExcelWriter(out_filename, engine="openpyxl") as writer:
        df_detail = pd.DataFrame(all_rows)
        # ensure issuer columns exist
        if "AFM_issuer" not in df_detail.columns:
            df_detail["AFM_issuer"] = ""
        if "Name_issuer" not in df_detail.columns:
            df_detail["Name_issuer"] = ""
        df_detail.to_excel(writer, sheet_name="invoices_vat_summary_classified", index=False)

        df_summary = pd.DataFrame(summary_list)
        if "AFM_issuer" not in df_summary.columns:
            df_summary["AFM_issuer"] = ""
        if "Name_issuer" not in df_summary.columns:
            df_summary["Name_issuer"] = ""
        df_summary.to_excel(writer, sheet_name="invoices_summary", index=False)

    if DEBUG:
        print(f"Saved {len(all_rows)} detail rows and {len(summary_list)} summary rows into '{out_filename}'.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch myDATA invoices and create Excel summary.")
    parser.add_argument("--user", help="AADE user id (or set AADE_USER_ID env var)")
    parser.add_argument("--key", help="AADE subscription key (or set AADE_SUBSCRIPTION_KEY env var)")
    parser.add_argument("--date-from", required=True, help="dateFrom in format DD/MM/YYYY")
    parser.add_argument("--date-to", required=True, help="dateTo in format DD/MM/YYYY")
    parser.add_argument("--out", default="invoices_vat_summary_classified.xlsx", help="output excel filename")
    args = parser.parse_args()

    user_id = args.user or os.getenv("AADE_USER_ID") or os.getenv("AADE_USER")
    subs_key = args.key or os.getenv("AADE_SUBSCRIPTION_KEY") or os.getenv("AADE_KEY")

    if not user_id or not subs_key:
        print("Error: Missing credentials. Provide --user and --key or set environment variables AADE_USER_ID and AADE_SUBSCRIPTION_KEY.")
        raise SystemExit(1)

    # Validate date format
    try:
        datetime.strptime(args.date_from, "%d/%m/%Y")
        datetime.strptime(args.date_to, "%d/%m/%Y")
    except Exception:
        print("Error: Dates must be in DD/MM/YYYY format.")
        raise SystemExit(1)

    main(user_id, subs_key, args.date_from, args.date_to, out_filename=args.out)
