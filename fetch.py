#!/usr/bin/env python3
# fetch.py
import os
import argparse
import requests
import xml.etree.ElementTree as ET
import pandas as pd
from collections import defaultdict
from datetime import datetime
from dateutil.relativedelta import relativedelta

MARK_DEFAULT = "000000000000000"

URL_REQUEST_DOCS = "https://mydatapi.aade.gr/myDATA/RequestDocs"
URL_REQUEST_TRANSMITTED = "https://mydatapi.aade.gr/myDATA/RequestTransmittedDocs"

def to_float_safe(x):
    try:
        if x is None:
            return 0.0
        s = str(x).strip()
        if s == "":
            return 0.0
        s2 = s.replace(",", ".")
        return float(s2)
    except Exception:
        return 0.0

def extract_issuer(invoice_elem, ns):
    # try issuer/vatNumber and issuer/name or fallback to any descendant with these names
    vat = invoice_elem.findtext("ns:issuer/ns:vatNumber", default="", namespaces=ns) or ""
    name = invoice_elem.findtext("ns:issuer/ns:name", default="", namespaces=ns) or ""
    if not vat:
        # search any descendant tag ending with vatNumber
        for e in invoice_elem.iter():
            tag = e.tag
            local = tag.split("}", 1)[-1] if "}" in tag else tag
            if local.lower() == "vatnumber" and e.text:
                vat = e.text.strip()
                break
    if not name:
        for e in invoice_elem.iter():
            tag = e.tag
            local = tag.split("}", 1)[-1] if "}" in tag else tag
            if local.lower() in ("name", "companyname", "partyname", "partytype") and e.text:
                name = e.text.strip()
                break
    return vat.strip(), name.strip()

def fetch_request_docs(mark, date_from, date_to, user, key):
    headers = {
        "aade-user-id": user,
        "Ocp-Apim-Subscription-Key": key
    }
    params = {"mark": mark, "dateFrom": date_from, "dateTo": date_to}
    all_rows = []
    while True:
        r = requests.get(URL_REQUEST_DOCS, params=params, headers=headers, timeout=60)
        if r.status_code != 200:
            raise RuntimeError(f"RequestDocs returned {r.status_code}: {r.text[:400]}")
        root = ET.fromstring(r.content)
        ns = {'ns': 'http://www.aade.gr/myDATA/invoice/v1.0'}
        for invoice in root.findall(".//ns:invoice", ns):
            markv = invoice.findtext("ns:mark", default="", namespaces=ns).strip()
            header = invoice.find("ns:invoiceHeader", ns)
            issueDate = header.findtext("ns:issueDate", default="", namespaces=ns) if header is not None else ""
            series = header.findtext("ns:series", default="", namespaces=ns) if header is not None else ""
            aa = header.findtext("ns:aa", default="", namespaces=ns) if header is not None else ""

            # issuer extraction
            vatissuer, nameissuer = extract_issuer(invoice, ns)

            # invoice details grouping
            vat_groups = defaultdict(lambda: {"netValue": 0.0, "vatAmount": 0.0})
            # try both plural and singular nodes
            details = invoice.findall(".//ns:invoiceDetails", ns) or invoice.findall(".//ns:invoiceDetail", ns)
            if not details:
                # fallback: find any node named invoiceDetails or invoiceDetail without ns
                for d in invoice.iter():
                    local = d.tag.split("}",1)[-1] if "}" in d.tag else d.tag
                    if local.lower() in ("invoicedetails","invoicedetail"):
                        # treat this d as a detail
                        net = to_float_safe(d.findtext("ns:netValue", default=None, namespaces=ns) or d.findtext("netValue") or 0)
                        vat = to_float_safe(d.findtext("ns:vatAmount", default=None, namespaces=ns) or d.findtext("vatAmount") or 0)
                        cat = d.findtext("ns:vatCategory", default=None, namespaces=ns) or d.findtext("vatCategory") or "1"
                        vat_groups[cat]["netValue"] += net
                        vat_groups[cat]["vatAmount"] += vat

            else:
                for detail in details:
                    net = detail.findtext("ns:netValue", default=None, namespaces=ns)
                    if net is None:
                        net = detail.findtext("netValue") or "0"
                    vat = detail.findtext("ns:vatAmount", default=None, namespaces=ns)
                    if vat is None:
                        vat = detail.findtext("vatAmount") or "0"
                    cat = detail.findtext("ns:vatCategory", default=None, namespaces=ns)
                    if cat is None:
                        cat = detail.findtext("vatCategory") or "1"
                    netv = to_float_safe(net)
                    vatv = to_float_safe(vat)
                    vat_groups[str(cat).strip() or "1"]["netValue"] += netv
                    vat_groups[str(cat).strip() or "1"]["vatAmount"] += vatv

            # fallback to invoiceSummary if no details recorded
            if not vat_groups:
                summary_node = invoice.find("ns:invoiceSummary", ns)
                if summary_node is not None:
                    net = to_float_safe(summary_node.findtext("ns:totalNetValue", default="0", namespaces=ns))
                    vatv = to_float_safe(summary_node.findtext("ns:totalVatAmount", default="0", namespaces=ns))
                    vat_groups["1"]["netValue"] += net
                    vat_groups["1"]["vatAmount"] += vatv

            for vat_cat, totals in vat_groups.items():
                row = {
                    "mark": markv,
                    "issueDate": issueDate,
                    "series": series,
                    "aa": aa,
                    "vatCategory": vat_cat,
                    "totalNetValue": round(totals["netValue"],2),
                    "totalVatAmount": round(totals["vatAmount"],2),
                    "classification": "αχαρακτηριστο",
                    "AFM_issuer": vatissuer,
                    "Name_issuer": nameissuer
                }
                all_rows.append(row)

        # continuation token support
        next_token_elem = root.find(".//ns:nextPartitionToken", ns)
        if next_token_elem is not None and next_token_elem.text:
            params["nextPartitionToken"] = next_token_elem.text
        else:
            break

    return all_rows

def fetch_transmitted_marks(mark, date_from, date_to, user, key):
    headers = {
        "aade-user-id": user,
        "Ocp-Apim-Subscription-Key": key
    }
    params = {"mark": mark, "dateFrom": date_from, "dateTo": date_to}
    r = requests.get(URL_REQUEST_TRANSMITTED, params=params, headers=headers, timeout=60)
    trans = set()
    if r.status_code == 200 and r.content:
        try:
            root = ET.fromstring(r.content)
            for elem in root.iter():
                tag = elem.tag
                local = tag.split("}",1)[-1] if "}" in tag else tag
                if local.lower() == "invoicemark" and elem.text:
                    trans.add(elem.text.strip())
                else:
                    # capture direct 15-digit numbers anywhere in the returned xml text
                    if elem.text:
                        t = elem.text.strip()
                        if t.isdigit() and len(t) == 15:
                            trans.add(t)
        except Exception:
            pass
    # save raw xml for debugging
    try:
        with open("requesttransmitted_raw.xml", "wb") as f:
            f.write(r.content)
    except Exception:
        pass
    return trans

def main():
    parser = argparse.ArgumentParser(description="Bulk fetch myDATA RequestDocs and write Excel")
    parser.add_argument("--date-from", required=True, help="dd/mm/YYYY")
    parser.add_argument("--date-to", required=True, help="dd/mm/YYYY")
    parser.add_argument("--user", required=False, help="AADE user id (or use env)")
    parser.add_argument("--key", required=False, help="AADE subscription key (or use env)")
    parser.add_argument("--out", required=True, help="output Excel path")
    parser.add_argument("--mark", required=False, default=MARK_DEFAULT, help="MARK to query (default 000000000000000)")
    args = parser.parse_args()

    user = args.user or os.getenv("AADE_USER_ID") or os.getenv("AADE_USER") or ""
    key = args.key or os.getenv("AADE_SUBSCRIPTION_KEY") or os.getenv("AADE_KEY") or ""
    if not user or not key:
        print("ERROR: AADE credentials missing (either pass --user/--key or set env vars).", file=sys.stderr)
        sys.exit(2)

    # request docs
    try:
        print(f"Fetching RequestDocs mark={args.mark} from={args.date_from} to={args.date_to} ...")
        all_rows = fetch_request_docs(args.mark, args.date_from, args.date_to, user, key)
        print(f"Rows extracted: {len(all_rows)}")
    except Exception as e:
        print("ERROR fetching RequestDocs:", e, file=sys.stderr)
        sys.exit(3)

    # fetch transmitted marks with dateTo + 3 months
    try:
        df_to = datetime.strptime(args.date_to, "%d/%m/%Y")
        to_plus_3 = (df_to + relativedelta(months=3)).strftime("%d/%m/%Y")
    except Exception:
        to_plus_3 = args.date_to

    try:
        transmitted = fetch_transmitted_marks(args.mark, args.date_from, to_plus_3, user, key)
        print(f"Transmitted marks found: {len(transmitted)}")
    except Exception as e:
        print("Warning: fetch transmitted failed:", e)

    # update classifications
    updated = 0
    for r in all_rows:
        if r["mark"] in transmitted:
            r["classification"] = "χαρακτηρισμενο"
            updated += 1
    print(f"Updated classification to 'χαρακτηρισμενο' for {updated} rows")

    # create summary per invoice
    summary_rows = {}
    for r in all_rows:
        mk = r["mark"]
        if mk not in summary_rows:
            summary_rows[mk] = {
                "mark": mk,
                "issueDate": r.get("issueDate",""),
                "series": r.get("series",""),
                "aa": r.get("aa",""),
                "classification": r.get("classification",""),
                "totalNetValue": r.get("totalNetValue",0.0),
                "totalVatAmount": r.get("totalVatAmount",0.0),
                "AFM_issuer": r.get("AFM_issuer",""),
                "Name_issuer": r.get("Name_issuer","")
            }
        else:
            # sum amounts
            summary_rows[mk]["totalNetValue"] += r.get("totalNetValue",0.0)
            summary_rows[mk]["totalVatAmount"] += r.get("totalVatAmount",0.0)
            if r.get("classification") == "χαρακτηρισμενο":
                summary_rows[mk]["classification"] = "χαρακτηρισμενο"
            if not summary_rows[mk]["AFM_issuer"] and r.get("AFM_issuer"):
                summary_rows[mk]["AFM_issuer"] = r.get("AFM_issuer")
            if not summary_rows[mk]["Name_issuer"] and r.get("Name_issuer"):
                summary_rows[mk]["Name_issuer"] = r.get("Name_issuer")

    # add totalValue
    for v in summary_rows.values():
        v["totalValue"] = round(v.get("totalNetValue",0.0) + v.get("totalVatAmount",0.0), 2)

    # write Excel with two sheets
    out_path = args.out
    try:
        with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
            df_detail = pd.DataFrame(all_rows)
            # ensure issuer columns exist
            if "AFM_issuer" not in df_detail.columns:
                df_detail["AFM_issuer"] = ""
            if "Name_issuer" not in df_detail.columns:
                df_detail["Name_issuer"] = ""
            df_detail.to_excel(writer, sheet_name="invoices_vat_summary_classified", index=False)

            df_summary = pd.DataFrame(list(summary_rows.values()))
            if "AFM_issuer" not in df_summary.columns:
                df_summary["AFM_issuer"] = ""
            if "Name_issuer" not in df_summary.columns:
                df_summary["Name_issuer"] = ""
            df_summary.to_excel(writer, sheet_name="invoices_summary", index=False)
        print("Excel written to", out_path)
    except Exception as e:
        print("ERROR writing Excel:", e, file=sys.stderr)
        sys.exit(4)

if __name__ == "__main__":
    import sys
    main()
