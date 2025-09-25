# fetch.py
import requests
import xml.etree.ElementTree as ET
import pandas as pd
from collections import defaultdict
from datetime import datetime
from dateutil.relativedelta import relativedelta
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

def request_docs(
    date_from: str,
    date_to: str,
    mark: str,
    user_id: str,
    subs_key: str,
    debug: bool = False,
    save_excel: bool = True,
    out_filename: str = "invoices_vat_summary_classified.xlsx"
) -> Tuple[List[dict], List[dict]]:
    """
    Fetch invoices from myDATA and optionally save Excel.
    Returns: all_rows (detailed) και summary_list (summary)
    """
    URL_REQUEST_DOCS = "https://mydatapi.aade.gr/myDATA/RequestDocs"
    URL_REQUEST_TRANSMITTED = "https://mydatapi.aade.gr/myDATA/RequestTransmittedDocs"

    headers = {"aade-user-id": user_id, "Ocp-Apim-Subscription-Key": subs_key}

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
            issueDate = _safe_strip(header.findtext("ns:issueDate", default="", namespaces=ns)) if header else ""
            series = _safe_strip(header.findtext("ns:series", default="", namespaces=ns)) if header else ""
            aa = _safe_strip(header.findtext("ns:aa", default="", namespaces=ns)) if header else ""

            vatissuer, Name_issuer = extract_issuer_info(invoice, ns)

            vat_groups = defaultdict(lambda: {"netValue": 0.0, "vatAmount": 0.0})
            details_nodes = invoice.findall(".//ns:invoiceDetails", ns)
            if not details_nodes: details_nodes = invoice.findall(".//ns:invoiceDetail", ns)

            for detail in details_nodes:
                net_text = detail.findtext("ns:netValue", default=None, namespaces=ns) or \
                           detail.findtext("netValue") or detail.findtext("NetValue") or "0"
                vat_text = detail.findtext("ns:vatAmount", default=None, namespaces=ns) or \
                           detail.findtext("vatAmount") or detail.findtext("VatAmount") or "0"
                vat_cat = detail.findtext("ns:vatCategory", default=None, namespaces=ns) or \
                          detail.findtext("vatCategory") or detail.findtext("VatCategory") or ""
                net, vat = to_float_safe(net_text), to_float_safe(vat_text)
                cat = _safe_strip(vat_cat) or "1"
                vat_groups[cat]["netValue"] += net
                vat_groups[cat]["vatAmount"] += vat

            if not vat_groups:
                summary_node = invoice.find("ns:invoiceSummary", ns)
                if summary_node:
                    net = to_float_safe(summary_node.findtext("ns:totalNetValue", default="0", namespaces=ns))
                    vat = to_float_safe(summary_node.findtext("ns:totalVatAmount", default="0", namespaces=ns))
                    vat_groups["1"]["netValue"] += net
                    vat_groups["1"]["vatAmount"] += vat

            for vat_cat, totals in vat_groups.items():
                all_rows.append({
                    "mark": mark_val,
                    "issueDate": issueDate,
                    "series": series,
                    "aa": aa,
                    "vatCategory": vat_cat,
                    "totalNetValue": round(totals["netValue"], 2),
                    "totalVatAmount": round(totals["vatAmount"], 2),
                    "classification": "αχαρακτηριστο",
                    "AFM_issuer": vatissuer,
                    "Name_issuer": Name_issuer
                })

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

    # --- Step 4: Summary ---
    summary_rows = {}
    for row in all_rows:
        mark_val = row["mark"]
        if mark_val not in summary_rows:
            summary_rows[mark_val] = {**row}
        else:
            if row["classification"] == "χαρακτηρισμενο":
                summary_rows[mark_val]["classification"] = "χαρακτηρισμενο"
            summary_rows[mark_val]["totalNetValue"] += row["totalNetValue"]
            summary_rows[mark_val]["totalVatAmount"] += row["totalVatAmount"]

    for s in summary_rows.values():
        s["totalValue"] = round(s["totalNetValue"] + s["totalVatAmount"], 2)
    summary_list = list(summary_rows.values())

    # --- Step 5: Save Excel ---
    if save_excel:
        with pd.ExcelWriter(out_filename, engine="openpyxl") as writer:
            pd.DataFrame(all_rows).to_excel(writer, sheet_name="detailed", index=False)
            pd.DataFrame(summary_list).to_excel(writer, sheet_name="summary", index=False)
        if debug: print(f"Saved {len(all_rows)} detailed rows and {len(summary_list)} summary rows to '{out_filename}'.")

    return all_rows, summary_list
