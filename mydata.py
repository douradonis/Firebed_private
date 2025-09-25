import requests
import xml.etree.ElementTree as ET
import pandas as pd
from collections import defaultdict
from datetime import datetime
from dateutil.relativedelta import relativedelta

# --- CONFIG ---
DEBUG = True   # θέσε σε False για να απενεργοποιήσεις τα debug prints
MARK = "000000000000000"
DATE_FROM = "12/05/2025"
DATE_TO = "12/05/2025"
USER_ID = "tester97"
SUBS_KEY = "614aa5de28548ac726679355d84b36d4"

URL_REQUEST_DOCS = "https://mydatapi.aade.gr/myDATA/RequestDocs"
URL_REQUEST_TRANSMITTED = "https://mydatapi.aade.gr/myDATA/RequestTransmittedDocs"

headers = {
    "aade-user-id": USER_ID,
    "Ocp-Apim-Subscription-Key": SUBS_KEY
}

# ---------- βοηθητικές συναρτήσεις ----------
def _safe_strip(s):
    if s is None:
        return ""
    return str(s).strip()

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

    # 1) standard issuer element
    issuer = invoice_elem.find("ns:issuer", ns)
    if issuer is not None:
        # direct children
        vat = _safe_strip(issuer.findtext("ns:vatNumber", default="", namespaces=ns))
        if not vat:
            # try any descendant with localname matching vatNumber
            vat = find_in_element_by_localnames(issuer, ["vatNumber", "VATNumber", "vatnumber"])

        # name: try issuer/name, issuer:partyName/name, issuer/party/partyName/name etc.
        name = _safe_strip(issuer.findtext("ns:name", default="", namespaces=ns))
        if not name:
            # try common nested paths and alternatives
            name = find_in_element_by_localnames(issuer, ["name", "Name", "companyName", "partyName", "partyType", "party"])
    else:
        # fallback: try other locations at invoice level (older/other schemas)
        vat = find_in_element_by_localnames(invoice_elem, ["vatNumber", "VATNumber", "vatnumber"])
        name = find_in_element_by_localnames(invoice_elem, ["name", "Name", "companyName", "partyName", "partyType", "party"])

    return _safe_strip(vat), _safe_strip(name)

def to_float_safe(x):
    try:
        return float(x)
    except Exception:
        try:
            s = str(x).strip().replace(",", ".")
            return float(s)
        except Exception:
            return 0.0

# ---------- Step 1: RequestDocs ----------
all_rows = []
params_docs = {"mark": MARK, "dateFrom": DATE_FROM, "dateTo": DATE_TO}

while True:
    response = requests.get(URL_REQUEST_DOCS, params=params_docs, headers=headers)
    if DEBUG:
        print(f"[RequestDocs] Status Code: {response.status_code}")
    if response.status_code != 200:
        if DEBUG:
            print("RequestDocs failed, status:", response.status_code, "body:", response.text[:300])
        break

    try:
        root = ET.fromstring(response.content)
    except Exception as e:
        print("XML parse error RequestDocs:", e)
        break

    ns = {'ns': 'http://www.aade.gr/myDATA/invoice/v1.0'}

    for invoice in root.findall(".//ns:invoice", ns):
        mark = _safe_strip(invoice.findtext("ns:mark", default="", namespaces=ns))
        header = invoice.find("ns:invoiceHeader", ns)
        issueDate = _safe_strip(header.findtext("ns:issueDate", default="", namespaces=ns)) if header is not None else ""
        series = _safe_strip(header.findtext("ns:series", default="", namespaces=ns)) if header is not None else ""
        aa = _safe_strip(header.findtext("ns:aa", default="", namespaces=ns)) if header is not None else ""

        # ---- ΕΞΑΓΩΓΗ ΕΚΔΟΤΗ (vat + name) ----
        vatissuer, Name_issuer = extract_issuer_info(invoice, ns)
        if DEBUG:
            print(f"[DEBUG] Mark: {mark}  AFM_issuer: '{vatissuer}'  Name_issuer: '{Name_issuer}'  issueDate: {issueDate} series:{series} aa:{aa}")

        # ---- Ομαδοποίηση ανά κατηγορία ΦΠΑ ----
        vat_groups = defaultdict(lambda: {"netValue": 0.0, "vatAmount": 0.0})
        # βρες όλα τα invoiceDetails nodes ανεξαρτήτως δομής
        details_nodes = invoice.findall(".//ns:invoiceDetails", ns)
        if not details_nodes:
            details_nodes = invoice.findall(".//ns:invoiceDetail", ns)

        # collect totals from details nodes
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

        # αν δεν βρήκε καθόλου invoiceDetails, fallback στο invoiceSummary
        if not vat_groups:
            summary_node = invoice.find("ns:invoiceSummary", ns)
            if summary_node is not None:
                net = to_float_safe(summary_node.findtext("ns:totalNetValue", default="0", namespaces=ns))
                vat = to_float_safe(summary_node.findtext("ns:totalVatAmount", default="0", namespaces=ns))
                vat_groups["1"]["netValue"] += net
                vat_groups["1"]["vatAmount"] += vat

        if DEBUG:
            # εμφανίζει τα αθροίσματα ανά κατηγορία ΦΠΑ
            print(f"  VAT groups for mark {mark}:")
            for k, v in vat_groups.items():
                print(f"    category {k} -> net={v['netValue']} vat={v['vatAmount']}")

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

    next_token_elem = root.find(".//ns:nextPartitionToken", ns)
    if next_token_elem is not None and next_token_elem.text:
        params_docs["nextPartitionToken"] = next_token_elem.text
        if DEBUG:
            print("[RequestDocs] NextPartitionToken:", params_docs["nextPartitionToken"])
    else:
        break

# ---------- Step 2: RequestTransmittedDocs με dateTo +3 μήνες ----------
date_format = "%d/%m/%Y"
date_to_docs = datetime.strptime(DATE_TO, date_format)
date_to_trans = date_to_docs + relativedelta(months=3)
DATE_TO_TRANS = date_to_trans.strftime(date_format)

params_trans = {"mark": MARK, "dateFrom": DATE_FROM, "dateTo": DATE_TO_TRANS}
response_trans = requests.get(URL_REQUEST_TRANSMITTED, params=params_trans, headers=headers)
if DEBUG:
    print(f"[RequestTransmittedDocs] Status Code: {response_trans.status_code}")

transmitted_marks = set()
if response_trans.status_code == 200 and response_trans.content:
    try:
        root_trans = ET.fromstring(response_trans.content)
        for elem in root_trans.iter():
            tag = elem.tag
            local = tag.split("}", 1)[-1] if "}" in tag else tag
            if local.lower() == "invoicemark" and elem.text:
                transmitted_marks.add(_safe_strip(elem.text))
            if elem.text:
                txt = _safe_strip(elem.text)
                if txt.isdigit() and len(txt) == 15:
                    transmitted_marks.add(txt)
    except Exception as e:
        print("Parse transmitted XML error:", e)

    # save raw XML (για debugging)
    with open("requesttransmitted_raw.xml", "wb") as f:
        f.write(response_trans.content)
    if DEBUG:
        print("[RequestTransmittedDocs] Raw XML saved to requesttransmitted_raw.xml")

if DEBUG:
    print(f"Number of transmitted marks found: {len(transmitted_marks)}")
    if len(transmitted_marks) > 0:
        # δείξε πρώτα 50 για να μην πλημμυρίσει η οθόνη
        sample = list(transmitted_marks)[:50]
        print("Sample transmitted marks:", sample)

# ---------- Step 3: Ενημέρωση classification ----------
updated_count = 0
for row in all_rows:
    mark = row["mark"].strip()
    if mark in transmitted_marks:
        row["classification"] = "χαρακτηρισμενο"
        updated_count += 1

if DEBUG:
    print(f"Total rows updated to 'χαρακτηρισμενο': {updated_count}")

# ---------- Step 4: Δημιουργία summary ανά παραστατικό με συνολικά ποσά ----------
summary_rows = {}
for row in all_rows:
    mark = row["mark"]
    if mark not in summary_rows:
        summary_rows[mark] = {
            "mark": mark,
            "issueDate": row["issueDate"],
            "series": row["series"],
            "aa": row["aa"],
            "classification": row["classification"],
            "totalNetValue": row["totalNetValue"],
            "totalVatAmount": row["totalVatAmount"],
            "AFM_issuer": row.get("AFM_issuer", ""),
            "Name_issuer": row.get("Name_issuer", "")
        }
    else:
        if row["classification"] == "χαρακτηρισμενο":
            summary_rows[mark]["classification"] = "χαρακτηρισμενο"
        summary_rows[mark]["totalNetValue"] += row["totalNetValue"]
        summary_rows[mark]["totalVatAmount"] += row["totalVatAmount"]
        if not summary_rows[mark]["AFM_issuer"] and row.get("AFM_issuer"):
            summary_rows[mark]["AFM_issuer"] = row.get("AFM_issuer")
        if not summary_rows[mark]["Name_issuer"] and row.get("Name_issuer"):
            summary_rows[mark]["Name_issuer"] = row.get("Name_issuer")

# Προσθήκη στήλης totalValue = net + vat
for s in summary_rows.values():
    s["totalValue"] = round(s["totalNetValue"] + s["totalVatAmount"], 2)

summary_list = list(summary_rows.values())

# ---------- Step 5: Αποθήκευση σε Excel με δύο sheets ----------
out_filename = "invoices_vat_summary_classified.xlsx"
with pd.ExcelWriter(out_filename, engine="openpyxl") as writer:
    # αναλυτικό sheet
    df_detail = pd.DataFrame(all_rows)
    if "AFM_issuer" not in df_detail.columns:
        df_detail["AFM_issuer"] = ""
    if "Name_issuer" not in df_detail.columns:
        df_detail["Name_issuer"] = ""
    df_detail.to_excel(writer, sheet_name="invoices_vat_summary_classified", index=False)

    # summary sheet
    df_summary = pd.DataFrame(summary_list)
    if "AFM_issuer" not in df_summary.columns:
        df_summary["AFM_issuer"] = ""
    if "Name_issuer" not in df_summary.columns:
        df_summary["Name_issuer"] = ""
    df_summary.to_excel(writer, sheet_name="invoices_summary", index=False)

if DEBUG:
    print(f"Saved {len(all_rows)} rows (detailed) and {len(summary_list)} rows (summary) to '{out_filename}'.")
