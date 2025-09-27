# fetch.py
import requests
import xml.etree.ElementTree as ET
import pandas as pd
from collections import defaultdict
from datetime import datetime
from dateutil.relativedelta import relativedelta
from dateutil.parser import parse
from typing import Tuple, List

def _safe_strip(s):
    return str(s).strip() if s else ""

def find_in_element_by_localnames(elem, localnames):
    if elem is None:
        return ""
    for sub in elem.iter():
        tag = sub.tag
        lname = tag.split("}", 1)[1] if "}" in tag else tag
        if lname in localnames:
            txt = _safe_strip(sub.text)
            if txt:
                return txt
    return ""

def extract_issuer_info(invoice_elem, ns):
    vat = ""
    name = ""
    issuer = invoice_elem.find("ns:issuer", ns)
    if issuer is not None:
        vat = _safe_strip(issuer.findtext("ns:vatNumber", default="", namespaces=ns))
        if not vat:
            vat = find_in_element_by_localnames(issuer, ["vatNumber", "VATNumber", "vatnumber"])
        name = _safe_strip(issuer.findtext("ns:name", default="", namespaces=ns))
        if not name:
            name = find_in_element_by_localnames(issuer, ["name", "Name", "companyName", "partyName", "partyType", "party"])
    else:
        vat = find_in_element_by_localnames(invoice_elem, ["vatNumber", "VATNumber", "vatnumber"])
        name = find_in_element_by_localnames(invoice_elem, ["name", "Name", "companyName", "partyName", "partyType", "party"])
    return _safe_strip(vat), _safe_strip(name)

def to_float_safe(x):
    try:
        return float(x)
    except Exception:
        try:
            return float(str(x).strip().replace(",", "."))
        except Exception:
            return 0.0

def format_date_to_ddmmyyyy(value: str) -> str:
    if not value:
        return ""
    v = str(value).strip()
    if "/" in v and len(v.split("/")[0]) <= 2:
        return v
    try:
        dt = parse(v)
        return dt.strftime("%d/%m/%Y")
    except Exception:
        return v

def format_decimal_comma(value) -> str:
    if value is None:
        return ""
    try:
        if isinstance(value, (int, float)):
            s = f"{value:.2f}"
            return s.replace(".", ",")
        vs = str(value).strip()
        num = float(vs.replace(",", "."))
        s = f"{num:.2f}"
        return s.replace(".", ",")
    except Exception:
        return str(value).strip()

def request_docs(
    date_from: str,
    date_to: str,
    mark: str,
    aade_user: str,
    aade_key: str,
    debug: bool = False,
    save_excel: bool = True,
    out_filename: str = "invoices_vat_summary_classified.xlsx"
) -> Tuple[List[dict], List[dict]]:
    """
    Returns:
        all_rows_json, summary_json  # JSON-ready with comma decimals
    Also saves Excel with numeric columns for Καθαρή Αξία, ΦΠΑ, Σύνολο
    """
    URL_REQUEST_DOCS = "https://mydatapi.aade.gr/myDATA/RequestDocs"
    URL_REQUEST_TRANSMITTED = "https://mydatapi.aade.gr/myDATA/RequestTransmittedDocs"
    headers = {"aade-user-id": aade_user, "Ocp-Apim-Subscription-Key": aade_key}
    all_rows = []
    params_docs = {"mark": mark, "dateFrom": date_from, "dateTo": date_to}

    # --- Step 1: RequestDocs ---
    while True:
        resp = requests.get(URL_REQUEST_DOCS, params=params_docs, headers=headers)
        if debug: print(f"[RequestDocs] Status: {resp.status_code}")
        if resp.status_code != 200:
            raise RuntimeError(f"RequestDocs HTTP {resp.status_code}: {(resp.text or '')[:1000]}")

        root = ET.fromstring(resp.content)
        ns = {'ns': 'http://www.aade.gr/myDATA/invoice/v1.0'}

        for invoice in root.findall(".//ns:invoice", ns):
            mark_val = _safe_strip(invoice.findtext("ns:mark", default="", namespaces=ns))
            header = invoice.find("ns:invoiceHeader", ns)
            issueDate_raw = _safe_strip(header.findtext("ns:issueDate", default="", namespaces=ns)) if header is not None else ""
            issueDate = format_date_to_ddmmyyyy(issueDate_raw)
            series = _safe_strip(header.findtext("ns:series", default="", namespaces=ns)) if header is not None else ""
            aa = _safe_strip(header.findtext("ns:aa", default="", namespaces=ns)) if header is not None else ""

            invoice_type = ""
            if header is not None:
                invoice_type = _safe_strip(header.findtext("ns:invoiceType", default="", namespaces=ns))
                if not invoice_type:
                    invoice_type = find_in_element_by_localnames(header, ["invoiceType", "InvoiceType", "invoiceCategory", "type", "documentType"])
            if not invoice_type:
                invoice_type = find_in_element_by_localnames(invoice, ["invoiceType", "InvoiceType", "invoiceCategory", "type", "documentType"])

            vatissuer, Name_issuer = extract_issuer_info(invoice, ns)

            vat_groups = defaultdict(lambda: {"netValue": 0.0, "vatAmount": 0.0})
            details_nodes = invoice.findall(".//ns:invoiceDetails", ns) or invoice.findall(".//ns:invoiceDetail", ns) or invoice.findall(".//invoiceDetails") or invoice.findall(".//invoiceDetail")
            for detail in details_nodes:
                net = to_float_safe(detail.findtext("ns:netValue", default=None, namespaces=ns) or detail.findtext("netValue") or detail.findtext("NetValue") or 0)
                vat = to_float_safe(detail.findtext("ns:vatAmount", default=None, namespaces=ns) or detail.findtext("vatAmount") or detail.findtext("VatAmount") or 0)
                cat = _safe_strip(detail.findtext("ns:vatCategory", default=None, namespaces=ns) or detail.findtext("vatCategory") or detail.findtext("VatCategory") or "1")
                vat_groups[cat]["netValue"] += net
                vat_groups[cat]["vatAmount"] += vat

            if not vat_groups:
                summary_node = invoice.find("ns:invoiceSummary", ns) or invoice.find("invoiceSummary")
                if summary_node is not None:
                    net = to_float_safe(summary_node.findtext("ns:totalNetValue", default="0", namespaces=ns) or summary_node.findtext("totalNetValue") or "0")
                    vat = to_float_safe(summary_node.findtext("ns:totalVatAmount", default="0", namespaces=ns) or summary_node.findtext("totalVatAmount") or "0")
                    vat_groups["1"]["netValue"] += net
                    vat_groups["1"]["vatAmount"] += vat

            for vat_cat, totals in vat_groups.items():
                total_value = round(totals["netValue"] + totals["vatAmount"], 2)
                row = {
                    "mark": mark_val,
                    "issueDate": issueDate,
                    "series": series,
                    "aa": aa,
                    "AA": aa,
                    "type": invoice_type,
                    "vatCategory": vat_cat,
                    "totalNetValue": round(totals["netValue"], 2),
                    "totalVatAmount": round(totals["vatAmount"], 2),
                    "totalValue": total_value,
                    "classification": "αχαρακτηριστο",
                    "AFM_issuer": vatissuer,
                    "Name_issuer": Name_issuer
                }
                all_rows.append(row)

        next_token_elem = root.find(".//ns:nextPartitionToken", ns)
        if next_token_elem is not None and next_token_elem.text:
            params_docs["nextPartitionToken"] = next_token_elem.text
            if debug: print("[RequestDocs] NextPartitionToken:", params_docs["nextPartitionToken"])
        else:
            break

    # --- Step 2: RequestTransmittedDocs ---
    date_to_docs = datetime.strptime(date_to, "%d/%m/%Y")
    date_to_trans = date_to_docs + relativedelta(months=3)
    DATE_TO_TRANS = date_to_trans.strftime("%d/%m/%Y")
    params_trans = {"mark": mark, "dateFrom": date_from, "dateTo": DATE_TO_TRANS}
    resp_trans = requests.get(URL_REQUEST_TRANSMITTED, params=params_trans, headers=headers)
    transmitted_marks = set()
    if resp_trans.status_code == 200 and resp_trans.content:
        root_trans = ET.fromstring(resp_trans.content)
        for elem in root_trans.iter():
            local = elem.tag.split("}", 1)[-1] if "}" in elem.tag else elem.tag
            if local.lower() == "invoicemark" and elem.text:
                transmitted_marks.add(_safe_strip(elem.text))
            if elem.text and _safe_strip(elem.text).isdigit() and len(_safe_strip(elem.text))==15:
                transmitted_marks.add(_safe_strip(elem.text))

    # --- Step 3: Classification update ---
    for row in all_rows:
        if row["mark"].strip() in transmitted_marks:
            row["classification"] = "χαρακτηρισμενο"

    # --- Step 4: Summary aggregation ---
    summary_rows = {}
    for row in all_rows:
        mark_val = row["mark"]
        if mark_val not in summary_rows:
            summary_rows[mark_val] = dict(row)
        else:
            summary_rows[mark_val]["totalNetValue"] += row.get("totalNetValue", 0)
            summary_rows[mark_val]["totalVatAmount"] += row.get("totalVatAmount", 0)
            summary_rows[mark_val]["totalValue"] += row.get("totalValue", 0)
            if row.get("classification") == "χαρακτηρισμενο":
                summary_rows[mark_val]["classification"] = "χαρακτηρισμενο"

    for s in summary_rows.values():
        s["totalNetValue"] = round(s.get("totalNetValue", 0), 2)
        s["totalVatAmount"] = round(s.get("totalVatAmount", 0), 2)
        s["totalValue"] = round(s.get("totalValue", 0), 2)
        if s.get("issueDate"):
            s["issueDate"] = format_date_to_ddmmyyyy(s["issueDate"])

    summary_list = list(summary_rows.values())

    # --- Step 5: Save Excel with numeric columns and Greek headers ---
    if save_excel:
        all_rows_excel = [{
            "MARK": r["mark"], "Ημερομηνία": r["issueDate"], "Σειρά": r["series"], "ΑΑ": r["aa"],
            "Τύπος": r["type"], "Καθαρή Αξία": r["totalNetValue"], "ΦΠΑ": r["totalVatAmount"],
            "Σύνολο": r["totalValue"], "Κατάσταση": r["classification"],
            "AFM Εκδότη": r["AFM_issuer"], "Όνομα Εκδότη": r["Name_issuer"]
        } for r in all_rows]

        summary_excel = [{
            "MARK": s["mark"], "Ημερομηνία": s["issueDate"], "Σειρά": s["series"], "ΑΑ": s["aa"],
            "Τύπος": s["type"], "Καθαρή Αξία": s["totalNetValue"], "ΦΠΑ": s["totalVatAmount"],
            "Σύνολο": s["totalValue"], "Κατάσταση": s["classification"],
            "AFM Εκδότη": s["AFM_issuer"], "Όνομα Εκδότη": s["Name_issuer"]
        } for s in summary_list]

        with pd.ExcelWriter(out_filename, engine="openpyxl") as writer:
            pd.DataFrame(all_rows_excel).to_excel(writer, sheet_name="detailed", index=False)
            pd.DataFrame(summary_excel).to_excel(writer, sheet_name="summary", index=False)
        if debug:
            print(f"Saved {len(all_rows)} detailed rows and {len(summary_list)} summary rows to '{out_filename}'.")

    # --- Step 6: JSON-ready with comma decimals ---
    all_rows_json = []
    for r in all_rows:
        rr = dict(r)
        rr["totalNetValue"] = format_decimal_comma(rr["totalNetValue"])
        rr["totalVatAmount"] = format_decimal_comma(rr["totalVatAmount"])
        rr["totalValue"] = format_decimal_comma(rr["totalValue"])
        all_rows_json.append(rr)

    summary_json = []
    for s in summary_list:
        ss = dict(s)
        ss["totalNetValue"] = format_decimal_comma(ss["totalNetValue"])
        ss["totalVatAmount"] = format_decimal_comma(ss["totalVatAmount"])
        ss["totalValue"] = format_decimal_comma(ss["totalValue"])
        summary_json.append(ss)

    return all_rows_json, summary_json
