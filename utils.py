# utils.py
import os
import io
import json
import re
from urllib.parse import urlparse, parse_qs
import requests
import xmltodict
from PIL import Image
from pyzbar.pyzbar import decode as qr_decode
from pdf2image import convert_from_bytes
import pandas as pd
from openpyxl import load_workbook
from bs4 import BeautifulSoup

# Excel path
UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
EXCEL_FILE = os.path.join(UPLOAD_FOLDER, "invoices.xlsx")

# Invoice type mapping
INVOICE_TYPE_MAP = {
    "1.1": "Τιμολόγιο Πώλησης",
    "1.2": "Τιμολόγιο Πώλησης / Ενδοκοινοτικές Παραδόσεις",
    "2.1": "Τιμολόγιο Παροχής Υπηρεσιών",
    "17.6": "Λοιπές Εγγραφές Τακτοποίησης Εξόδων - Φορολογική Βάση",
}

# Classification pattern
CLASSIFICATION_PATTERN = re.compile(r'\b(?:E3_[0-9]{3}(?:_[0-9]{3})*|VAT_[0-9]{3}|NOT_VAT_295)\b', flags=re.IGNORECASE)

# ----------------------
# Utilities for extracting MARK from URL pages (web scraping)
def extract_marks_from_url(url: str):
    """
    Δέχεται ένα URL, κατεβάζει τη σελίδα και επιστρέφει όλα τα ΜΑΡΚ (15-ψήφια).
    Γίνονται δεκτές παραλλαγές 'ΜΑΡΚ', 'mark', 'Κωδικός ΜΑΡΚ' κλπ.
    """
    try:
        resp = requests.get(url, timeout=12)
        resp.raise_for_status()
    except Exception as e:
        print(f"Σφάλμα κατά το κατέβασμα της σελίδας: {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    text = soup.get_text(" ", strip=True)

    mark_patterns = [
        r"(?:ΜΑΡΚ|Mark|MARK|κωδικός[\s\-]*ΜΑΡΚ|ΚΩΔΙΚΟΣ[\s\-]*ΜΑΡΚ)\s*[:\-]?\s*(\d{15})",
        r"κωδικος\s*μαρκ\s*[:\-]?\s*(\d{15})",
        r"(\d{15})"  # fallback: οποιοδήποτε 15ψήφιο
    ]

    found_marks = set()
    for pat in mark_patterns:
        matches = re.findall(pat, text, flags=re.IGNORECASE)
        for m in matches:
            if isinstance(m, str) and m.isdigit() and len(m) == 15:
                found_marks.add(m)

    # Επιστροφή ως λίστα
    return sorted(found_marks)

# ----------------------
# Helpers (MARK extraction from text/url fragments & QR decoding)
def extract_mark(text: str):
    """Προσπαθεί να εντοπίσει MARK μέσα σε απλό string ή URL query params."""
    if not text:
        return None
    txt = text.strip()
    # αν είναι ακριβώς 15 ψηφία -> MARK
    if txt.isdigit() and len(txt) == 15:
        return txt
    # προσπάθησε query params
    try:
        u = urlparse(txt)
        qs = parse_qs(u.query or "")
        keys = ("mark", "MARK", "invoiceMark", "invMark", "ΜΑΡΚ", "κωδικοςΜΑΡΚ", "ΚΩΔΙΚΟΣΜΑΡΚ")
        for key in keys:
            if key in qs and qs[key]:
                val = qs[key][0]
                if isinstance(val, str) and val.isdigit() and len(val) == 15:
                    return val
    except Exception:
        pass
    return None

def decode_qr_from_file(file_bytes: bytes, filename: str):
    """Διαβάζει QR από PDF/εικόνα και επιστρέφει πρώτο έγκυρο MARK (ή None)."""
    try:
        if filename.lower().endswith(".pdf"):
            images = convert_from_bytes(file_bytes)
            for img in images:
                codes = qr_decode(img)
                for c in codes:
                    try:
                        val = c.data.decode("utf-8")
                    except Exception:
                        val = str(c.data)
                    m = extract_mark(val)
                    if m:
                        return m
        else:
            img = Image.open(io.BytesIO(file_bytes))
            codes = qr_decode(img)
            for c in codes:
                try:
                    val = c.data.decode("utf-8")
                except Exception:
                    val = str(c.data)
                m = extract_mark(val)
                if m:
                    return m
    except Exception as e:
        print("decode_qr_from_file error:", e)
    return None

# ----------------------
# VAT extraction utilities (from parsed XML dict)
def _to_number_any(x):
    """Προσπαθεί να μετατρέψει διάφορα string σε float (υποστηρίζει 1.234,56 και 1234.56 κλπ)."""
    try:
        if x is None:
            return 0.0
        s = str(x).strip()
        if s == "":
            return 0.0
        # remove currency symbols/spaces
        s2 = re.sub(r"[^\d\-,\.]", "", s)
        # if comma present and dot not -> comma decimal
        if "," in s2 and "." not in s2:
            s2 = s2.replace(".", "").replace(",", ".")
        else:
            # remove thousand commas
            s2 = s2.replace(",", "")
        return float(s2)
    except Exception:
        try:
            return float(re.sub(r"[^\d\.]", "", str(x)))
        except Exception:
            return 0.0

def extract_vat_categories(parsed: dict) -> list:
    """
    Αναζήτηση πρώτα στα invoiceDetails (που περιέχουν vatCategory, netValue, vatAmount),
    group by vatCategory. Fallback στο invoiceSummary για συνολικά.
    Επιστρέφει λίστα dict: { 'category': '1', 'net': 123.45, 'vat': 24.56, 'gross': 147.01 }
    """
    try:
        # Normalize to the invoice dict as in summarize_invoice
        invoices_doc = parsed
        if isinstance(parsed, dict) and parsed.get("RequestedDoc"):
            invoices_doc = parsed.get("RequestedDoc")
        if isinstance(invoices_doc, dict) and invoices_doc.get("invoicesDoc"):
            invoices_doc = invoices_doc.get("invoicesDoc")

        invoice = None
        if isinstance(invoices_doc, dict):
            invoice = invoices_doc.get("invoice") or next(iter(invoices_doc.values()), None)
        else:
            invoice = invoices_doc

        if isinstance(invoice, list):
            invoice = invoice[0]

        if isinstance(invoice, dict):
            # try invoiceDetails
            details = invoice.get("invoiceDetails")
            lines = []
            if isinstance(details, list):
                lines = details
            elif isinstance(details, dict):
                lines = [details]
            else:
                # search deeper for invoiceDetails
                def find_details(o):
                    if isinstance(o, dict):
                        for k, v in o.items():
                            if k == "invoiceDetails":
                                if isinstance(v, list):
                                    return v
                                if isinstance(v, dict):
                                    return [v]
                            res = find_details(v)
                            if res:
                                return res
                    elif isinstance(o, list):
                        for i in o:
                            res = find_details(i)
                            if res:
                                return res
                    return None
                found = find_details(invoice)
                if found:
                    lines = found

            if lines:
                grouped = {}
                for ln in lines:
                    if not isinstance(ln, dict):
                        continue
                    # identify category
                    cat = str(ln.get("vatCategory") or ln.get("vatCategoryCode") or ln.get("vatCategoryId") or "").strip()
                    if not cat:
                        # attempt to extract digits from any field
                        txt = json.dumps(ln, ensure_ascii=False)
                        m = re.search(r"\b([0-9]{1,2})\b", txt)
                        cat = m.group(1) if m else "1"
                    net = _to_number_any(ln.get("netValue") or ln.get("net") or ln.get("baseAmount") or ln.get("netAmount"))
                    vat = _to_number_any(ln.get("vatAmount") or ln.get("vat") or ln.get("vatAmountValue"))
                    gross = round(net + vat, 2)
                    g = grouped.setdefault(cat, {"category": cat, "net": 0.0, "vat": 0.0, "gross": 0.0})
                    g["net"] += net
                    g["vat"] += vat
                    g["gross"] += gross

                res = [ {"category": k, "net": round(v["net"],2), "vat": round(v["vat"],2), "gross": round(v["gross"],2)} for k,v in sorted(grouped.items(), key=lambda t: t[0]) ]
                return res

        # fallback: invoiceSummary totals (single-row)
        if isinstance(invoice, dict):
            totals = invoice.get("invoiceSummary") or {}
            net = _to_number_any(totals.get("totalNetValue") or totals.get("TotalNetValue") or totals.get("netValue") or 0.0)
            vat = _to_number_any(totals.get("totalVatAmount") or totals.get("TotalVatAmount") or totals.get("vatAmount") or 0.0)
            gross = _to_number_any(totals.get("totalGrossValue") or totals.get("TotalGrossValue") or totals.get("grossValue") or 0.0)
            return [{"category": "1", "net": round(net,2), "vat": round(vat,2), "gross": round(gross,2)}]
    except Exception as e:
        print("extract_vat_categories error:", e)

    return []

# ----------------------
# Invoice summarization
def summarize_invoice(parsed: dict) -> dict:
    """Εξάγει ασφαλή περίληψη από το parsed xml->dict."""
    summary = {
        "Εκδότης": {"ΑΦΜ": "", "Επωνυμία": ""},
        "Στοιχεία Παραστατικού": {"Σειρά": "", "Αριθμός": "", "Ημερομηνία": "", "Είδος": ""},
        "Σύνολα": {"Καθαρή Αξία": "0", "ΦΠΑ": "0", "Σύνολο": "0"}
    }

    def safe_get(d, k):
        if isinstance(d, dict):
            return d.get(k) or d.get(k.lower()) or ""
        return ""

    try:
        invoices_doc = parsed
        if isinstance(parsed, dict) and parsed.get("RequestedDoc"):
            invoices_doc = parsed.get("RequestedDoc")
        if isinstance(invoices_doc, dict) and invoices_doc.get("invoicesDoc"):
            invoices_doc = invoices_doc.get("invoicesDoc")

        invoice = None
        if isinstance(invoices_doc, dict):
            invoice = invoices_doc.get("invoice") or next(iter(invoices_doc.values()), None)
        else:
            invoice = invoices_doc

        if isinstance(invoice, list):
            invoice = invoice[0]
        if not isinstance(invoice, dict):
            return summary

        issuer = invoice.get("issuer") or {}
        header = invoice.get("invoiceHeader") or {}
        totals = invoice.get("invoiceSummary") or {}

        summary["Εκδότης"]["ΑΦΜ"] = safe_get(issuer, "vatNumber") or safe_get(issuer, "VATNumber")
        summary["Εκδότης"]["Επωνυμία"] = safe_get(issuer, "name") or safe_get(issuer, "Name") or safe_get(issuer, "companyName")

        summary["Στοιχεία Παραστατικού"]["Σειρά"] = safe_get(header, "series") or safe_get(header, "Series")
        summary["Στοιχεία Παραστατικού"]["Αριθμός"] = safe_get(header, "aa") or safe_get(header, "AA") or safe_get(header, "Number")

        date_val = safe_get(header, "issueDate") or safe_get(header, "IssueDate")
        if date_val:
            try:
                from datetime import datetime
                dt = datetime.strptime(date_val, "%Y-%m-%d")
                summary["Στοιχεία Παραστατικού"]["Ημερομηνία"] = dt.strftime("%d/%m/%Y")
            except Exception:
                summary["Στοιχεία Παραστατικού"]["Ημερομηνία"] = date_val

        etype = safe_get(header, "invoiceType") or safe_get(header, "InvoiceType") or ""
        summary["Στοιχεία Παραστατικού"]["Είδος"] = INVOICE_TYPE_MAP.get(str(etype).strip(), str(etype).strip())

        summary["Σύνολα"]["Καθαρή Αξία"] = safe_get(totals, "totalNetValue") or safe_get(totals, "TotalNetValue") or summary["Σύνολα"]["Καθαρή Αξία"]
        summary["Σύνολα"]["ΦΠΑ"] = safe_get(totals, "totalVatAmount") or safe_get(totals, "TotalVatAmount") or summary["Σύνολα"]["ΦΠΑ"]
        summary["Σύνολα"]["Σύνολο"] = safe_get(totals, "totalGrossValue") or safe_get(totals, "TotalGrossValue") or summary["Σύνολα"]["Σύνολο"]

    except Exception as e:
        print("Σφάλμα στην περίληψη:", e)

    return summary

# ----------------------
# Formatting euro string
def format_euro_str(val):
    """Μετατρέπει αριθμό/string σε ευρωπαϊκή μορφή "1.234,56" ως string. Αν αποτύχει επιστρέφει ""."""
    try:
        if val is None or val == "":
            return ""
        s = str(val).strip()
        cleaned = re.sub(r"[^\d\-,\.]", "", s)
        if "," in cleaned and "." not in cleaned:
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
        v = float(cleaned)
        out = "{:,.2f}".format(v)
        out = out.replace(",", "X").replace(".", ",").replace("X", ".")
        return out
    except Exception:
        return ""

# ----------------------
# Classification regex (E3_xxx, VAT_xxx, NOT_VAT_295 etc.)
def _scan_for_classifications_and_marks_in_raw(raw_text: str, mark: str) -> bool:
    """
    Επιστρέφει True αν στο raw_text βρεθεί classification token ή αν βρεθεί field με invoiceMark == mark.
    """
    if not raw_text:
        return False

    # quick classification regex search
    if CLASSIFICATION_PATTERN.search(raw_text):
        return True

    # try parse xml and inspect keys/values for invoiceMark or classification tokens
    try:
        outer = xmltodict.parse(raw_text)
        inner_xml = outer.get("string", {}).get("#text") if isinstance(outer.get("string"), dict) else None
        parsed = xmltodict.parse(inner_xml) if inner_xml else outer
    except Exception:
        parsed = None

    if parsed is None:
        # as fallback, search raw text for invoiceMark=mark or the mark itself
        if re.search(re.escape(str(mark)), raw_text):
            # presence of the mark alone isn't necessarily "characterized", but since RequestTransmittedDocs is specific, treat presence as indicator
            return True
        return False

    # Walk parsed structure
    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                # check key name for classification tokens
                if CLASSIFICATION_PATTERN.search(str(k)):
                    return True
                # check value strings
                if isinstance(v, (str, int, float)):
                    s = str(v)
                    if CLASSIFICATION_PATTERN.search(s):
                        return True
                    if s.strip() == str(mark).strip():
                        # exact match of mark in some field (invoiceMark)
                        return True
                # recurse
                res = walk(v)
                if res:
                    return True
        elif isinstance(o, list):
            for item in o:
                res = walk(item)
                if res:
                    return True
        else:
            try:
                s = str(o)
                if CLASSIFICATION_PATTERN.search(s):
                    return True
                if s.strip() == str(mark).strip():
                    return True
            except Exception:
                pass
        return False

    return walk(parsed)

def is_mark_transmitted(mark: str, aade_user: str, aade_key: str, transmitted_url: str) -> bool:
    """
    Καλούμε το TRANSMITTED_URL (RequestTransmittedDocs).
    Ελέγχουμε αν το αποτέλεσμα περιέχει classification tokens ή το ίδιο το mark.
    Επιστρέφει True/False.
    Προσπαθούμε πρώτα με mark-1 (όπως κάνει και το fetch), μετά με mark.
    """
    headers = {
        "aade-user-id": aade_user,
        "ocp-apim-subscription-key": aade_key,
        "Accept": "application/xml",
    }

    candidates = []
    try:
        mi = int(str(mark).strip())
        if mi > 0:
            candidates.append(str(mi - 1))
    except Exception:
        pass
    candidates.append(str(mark))

    for q in candidates:
        try:
            r = requests.get(transmitted_url, headers=headers, params={"mark": q}, timeout=30)
        except Exception as e:
            print("is_mark_transmitted: request failed:", e)
            continue

        if r.status_code >= 400:
            # skip, try next candidate
            print("is_mark_transmitted: status", r.status_code, r.text[:200])
            continue

        raw_text = r.text or ""
        try:
            if _scan_for_classifications_and_marks_in_raw(raw_text, mark):
                return True
        except Exception as e:
            print("is_mark_transmitted: scan error:", e)
            # continue to next candidate

    return False

# ----------------------
# API call / parse
def fetch_by_mark(mark: str, aade_user: str, aade_key: str, requestdocs_url: str):
    """Καλεί το API (δοκιμάζει mark-1 πρώτα, fallback στο mark) και επιστρέφει (err, parsed, raw, summary)"""
    headers = {
        "aade-user-id": aade_user,
        "ocp-apim-subscription-key": aade_key,
        "Accept": "application/xml",
    }

    def call_mark(m_to_call):
        try:
            r = requests.get(requestdocs_url, headers=headers, params={"mark": m_to_call}, timeout=30)
        except Exception as e:
            return (f"Αποτυχία κλήσης στο API: {e}", None, None, None)
        if r.status_code >= 400:
            return (f"{r.status_code} Σφάλμα από το API: {r.text}", None, r.text, None)
        raw_xml = r.text
        try:
            outer = xmltodict.parse(raw_xml)
            inner_xml = outer.get("string", {}).get("#text") if isinstance(outer.get("string"), dict) else None
            parsed = xmltodict.parse(inner_xml) if inner_xml else outer
            summary = summarize_invoice(parsed)
            return ("", parsed, raw_xml, summary)
        except Exception as e:
            return (f"Σφάλμα parse XML: {e}", None, raw_xml, None)

    try:
        mi = int(str(mark).strip())
        if mi > 0:
            err, parsed, raw, summary = call_mark(str(mi - 1))
            if not err:
                return (err, parsed, raw, summary)
    except Exception:
        pass
    return call_mark(mark)

# ----------------------
# Save summary to excel (modified to split per VAT category if needed)
def save_summary_to_excel(summary: dict, mark: str, vat_categories: list = None, filepath: str = EXCEL_FILE) -> bool:
    """
    Προσθέτει μία ή πολλές γραμμές στο invoices.xlsx.
    - Αν vat_categories περιέχει πολλαπλές κατηγορίες και κάποια != '1', τότε
      δημιουργούμε μία γραμμή ανά κατηγορία με συνολικά ποσά κάθε κατηγορίας.
    - Διαχείριση διπλοεγγραφών:
      * Single-row: αν υπάρχει MARK -> θεωρείται duplicate και επιστρέφει False
      * Multi-row: ελέγχουμε για κάθε νέα γραμμή αν υπάρχει ακριβές ταίριασμα (MARK + ΦΠΑ_ΚΑΤΗΓΟΡΙΑ + Καθαρή Αξία + ΦΠΑ + Σύνολο)
        και εισάγουμε μόνο τις νέες γραμμές. Αν δεν εισαχθεί καμία γραμμή -> επιστρέφουμε False.
    """
    os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)

    existing = None
    if os.path.exists(filepath):
        try:
            existing = pd.read_excel(filepath, engine="openpyxl", dtype=str).fillna("")
        except Exception:
            existing = None

    rows_to_add = []

    if vat_categories and any(str(vc.get("category")) != "1" for vc in vat_categories):
        # create a row per category (use MARK same for all)
        for vc in vat_categories:
            cat = str(vc.get("category") or "").strip()
            net = vc.get("net", 0.0)
            vat = vc.get("vat", 0.0)
            gross = vc.get("gross", 0.0)
            row = {
                "MARK": str(mark),
                "ΑΦΜ": summary.get("Εκδότης", {}).get("ΑΦΜ", ""),
                "Επωνυμία": summary.get("Εκδότης", {}).get("Επωνυμία", ""),
                "Σειρά": summary.get("Στοιχεία Παραστατικού", {}).get("Σειρά", ""),
                "Αριθμός": summary.get("Στοιχεία Παραστατικού", {}).get("Αριθμός", ""),
                "Ημερομηνία": summary.get("Στοιχεία Παραστατικού", {}).get("Ημερομηνία", ""),
                "Είδος": summary.get("Στοιχεία Παραστατικού", {}).get("Είδος", ""),
                "ΦΠΑ_ΚΑΤΗΓΟΡΙΑ": cat,
                "Καθαρή Αξία": net,
                "ΦΠΑ": vat,
                "Σύνολο": gross
            }
            rows_to_add.append(row)
    else:
        # Single summary row
        row = {
            "MARK": str(mark),
            "ΑΦΜ": summary.get("Εκδότης", {}).get("ΑΦΜ", ""),
            "Επωνυμία": summary.get("Εκδότης", {}).get("Επωνυμία", ""),
            "Σειρά": summary.get("Στοιχεία Παραστατικού", {}).get("Σειρά", ""),
            "Αριθμός": summary.get("Στοιχεία Παραστατικού", {}).get("Αριθμός", ""),
            "Ημερομηνία": summary.get("Στοιχεία Παραστατικού", {}).get("Ημερομηνία", ""),
            "Είδος": summary.get("Στοιχεία Παραστατικού", {}).get("Είδος", ""),
            "ΦΠΑ_ΚΑΤΗΓΟΡΙΑ": "",  # κενό όταν δεν σπάει
            "Καθαρή Αξία": summary.get("Σύνολα", {}).get("Καθαρή Αξία", ""),
            "ΦΠΑ": summary.get("Σύνολα", {}).get("ΦΠΑ", ""),
            "Σύνολο": summary.get("Σύνολα", {}).get("Σύνολο", ""),
        }
        rows_to_add.append(row)

    df_new = pd.DataFrame(rows_to_add)

    # Format numeric columns (apply euro formatting so comparisons with existing are consistent)
    for col in ("Καθαρή Αξία", "ΦΠΑ", "Σύνολο"):
        if col in df_new.columns:
            df_new[col] = df_new[col].apply(format_euro_str)

    # If existing present, avoid exact duplicates
    if existing is not None:
        try:
            # Single-row duplicate check (MARK present)
            if len(df_new) == 1 and "MARK" in existing.columns:
                if str(df_new.at[0, "MARK"]).strip() in existing["MARK"].astype(str).str.strip().tolist():
                    # Already present: don't add
                    return False

            # For multi-row: add only rows that do not exist exactly
            if len(df_new) > 1 and existing is not None:
                # normalize existing to strings
                ex = existing.astype(str).fillna("")
                to_append = []
                for _, newr in df_new.iterrows():
                    # Compare on MARK, ΦΠΑ_ΚΑΤΗΓΟΡΙΑ, Καθαρή Αξία, ΦΠΑ, Σύνολο
                    cols_check = ["MARK", "ΦΠΑ_ΚΑΤΗΓΟΡΙΑ", "Καθαρή Αξία", "ΦΠΑ", "Σύνολο"]
                    bool_series = pd.Series([True] * len(ex))
                    for c in cols_check:
                        val_new = str(newr.get(c, "") or "").strip()
                        if c in ex.columns:
                            bool_series = bool_series & (ex[c].astype(str).str.strip() == val_new)
                        else:
                            bool_series = bool_series & pd.Series([False] * len(ex))
                    if not bool_series.any():
                        to_append.append(newr.to_dict())

                if not to_append:
                    return False  # nothing to add (duplicates)
                df_to_write = pd.concat([ex, pd.DataFrame(to_append)], ignore_index=True, sort=False)
                if "ΦΠΑ_ΑΝΑΛΥΣΗ" in df_to_write.columns:
                    df_to_write = df_to_write.drop(columns=["ΦΠΑ_ΑΝΑΛΥΣΗ"])
                df_to_write.to_excel(filepath, index=False, engine="openpyxl")
                return True

            # default concat for other cases
            df_concat = pd.concat([existing, df_new], ignore_index=True, sort=False)
            if "ΦΠΑ_ΑΝΑΛΥΣΗ" in df_concat.columns:
                df_concat = df_concat.drop(columns=["ΦΠΑ_ΑΝΑΛΥΣΗ"])
            df_concat.to_excel(filepath, index=False, engine="openpyxl")
            return True
        except Exception as e:
            print("Σφάλμα append Excel, θα δημιουργήσω νέο αρχείο:", e)

    # create new file
    if "ΦΠΑ_ΑΝΑΛΥΣΗ" in df_new.columns:
        df_new = df_new.drop(columns=["ΦΠΑ_ΑΝΑΛΥΣΗ"])
    df_new.to_excel(filepath, index=False, engine="openpyxl")
    return True

# ----------------------
# extract marks from plain text (used when user pastes URL or MARK string)
def extract_marks_from_text(text: str):
    """Βρίσκει όλα τα πιθανά MARKs μέσα σε ένα text (URL, query params ή digit sequences 15)."""
    marks = set()
    if not text:
        return []
    try:
        m = extract_mark(text)
        if m:
            marks.add(m)
    except Exception:
        pass

    # if URL, check query params
    try:
        u = urlparse(text)
        qs = parse_qs(u.query or "")
        keys = ("mark", "MARK", "invoiceMark", "invMark", "ΜΑΡΚ", "Μ.Α.Ρ.Κ.", "Μ.Αρ.Κ.")
        for k in keys:
            if k in qs:
                for v in qs[k]:
                    if isinstance(v, str) and re.fullmatch(r"\d{15}", v.strip()):
                        marks.add(v.strip())
    except Exception:
        pass

    # find any digit sequences exactly 15
    for match in re.findall(r"\d{15}", text):
        marks.add(match)

    return sorted(marks)
