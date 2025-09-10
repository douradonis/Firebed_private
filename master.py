# app.py
import os
import io
import json
import re
from urllib.parse import urlparse, parse_qs
from dotenv import load_dotenv
from flask import Flask, request, render_template_string, url_for, send_file, redirect
import requests
import xmltodict

from PIL import Image
from pyzbar.pyzbar import decode as qr_decode
from pdf2image import convert_from_bytes

# Excel
import pandas as pd
from openpyxl import load_workbook
from bs4 import BeautifulSoup

# Load env
load_dotenv()

AADE_USER = os.getenv("AADE_USER_ID", "")
AADE_KEY = os.getenv("AADE_SUBSCRIPTION_KEY", "")
ENV = (os.getenv("MYDATA_ENV", "sandbox") or "sandbox").lower()

# Endpoints
# REQUESTDOCS_URL: ό,τι είχες για το fetch των συνοψών (παλιά συμπεριφορά)
REQUESTDOCS_URL = (
    "https://mydataapidev.aade.gr/RequestTransmittedDocs"
    if ENV in ("sandbox", "demo", "dev")
    else "https://mydatapi.aade.gr/myDATA/RequestDocs"
)
# TRANSMITTED_URL: ειδικά για τον πρωτοέλεγχο που ζήτησες (RequestTransmittedDocs)
TRANSMITTED_URL = (
    "https://mydataapidev.aade.gr/RequestTransmittedDocs"
    if ENV in ("sandbox", "demo", "dev")
    else "https://mydatapi.aade.gr/myDATA/RequestTransmittedDocs"
)

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = "uploads"
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

# Excel path
EXCEL_FILE = os.path.join(app.config["UPLOAD_FOLDER"], "invoices.xlsx")

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
# Invoice summarization (παραμένει όπως πριν)
INVOICE_TYPE_MAP = {
    "1.1": "Τιμολόγιο Πώλησης",
    "1.2": "Τιμολόγιο Πώλησης / Ενδοκοινοτικές Παραδόσεις",
    "2.1": "Τιμολόγιο Παροχής Υπηρεσιών",
    "17.6": "Λοιπές Εγγραφές Τακτοποίησης Εξόδων - Φορολογική Βάση",
}

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
CLASSIFICATION_PATTERN = re.compile(r'\b(?:E3_[0-9]{3}(?:_[0-9]{3})*|VAT_[0-9]{3}|NOT_VAT_295)\b', flags=re.IGNORECASE)

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

def is_mark_transmitted(mark: str) -> bool:
    """
    Καλούμε το TRANSMITTED_URL (RequestTransmittedDocs).
    Ελέγχουμε αν το αποτέλεσμα περιέχει classification tokens ή το ίδιο το mark.
    Επιστρέφει True/False.
    Προσπαθούμε πρώτα με mark-1 (όπως κάνει και το fetch), μετά με mark.
    """
    headers = {
        "aade-user-id": AADE_USER,
        "ocp-apim-subscription-key": AADE_KEY,
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
            r = requests.get(TRANSMITTED_URL, headers=headers, params={"mark": q}, timeout=30)
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
# API call / parse (παραμένει όπως πριν)
def fetch_by_mark(mark: str):
    """Καλεί το API (δοκιμάζει mark-1 πρώτα, fallback στο mark) και επιστρέφει (err, parsed, raw, summary)"""
    headers = {
        "aade-user-id": AADE_USER,
        "ocp-apim-subscription-key": AADE_KEY,
        "Accept": "application/xml",
    }

    def call_mark(m_to_call):
        try:
            r = requests.get(REQUESTDOCS_URL, headers=headers, params={"mark": m_to_call}, timeout=30)
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

# ----------------------
# API call / parse (παραμένει όπως πριν)
# (fetch_by_mark implemented above)

# ----------------------
# HTML templates (παραμένουν ως έχει — χρησιμοποίησα τα templates από το αρχικό σου αρχείο)
NAV_HTML = """<!doctype html>
<html lang="el">
<head><meta charset="utf-8"><title>myDATA - Μενού</title>
<style>
body {font-family:Arial,sans-serif;max-width:900px;margin:20px auto;background:#fafafa;}
.card {background:white;padding:16px;margin:16px 0;border-radius:12px;box-shadow:0 2px 6px rgba(0,0,0,0.05);}
.menu {display:flex;gap:12px;flex-wrap:wrap;}
.menu a {display:block;padding:12px 18px;background:#0d6efd;color:#fff;border-radius:10px;text-decoration:none;}
.menu a.secondary {background:#6c757d;}
</style>
</head><body>
<div class="card"><h1>myDATA - Κεντρικό Μενού</h1>
<p>Επέλεξε λειτουργία:</p>
<div class="menu">
<a href="{{ url_for('viewer') }}">Εισαγωγή Παραστατικού</a>
<a href="{{ url_for('options') }}" class="secondary">Επιλογές</a>
<a href="{{ url_for('list_invoices') }}">Λίστα Παραστατικών</a>
</div>
</div>
</body></html>
"""

VIEWER_HTML = """<!doctype html>
<html lang="el">
<head>
<meta charset="UTF-8">
<title>myDATA QR Viewer</title>
<style>
body {font-family:Arial,sans-serif;max-width:900px;margin:20px auto;background:#fafafa;}
.card {background:white;padding:16px;margin:16px 0;border-radius:12px;box-shadow:0 2px 6px rgba(0,0,0,0.05);}
input, button {width:100%;padding:8px;margin:6px 0;border-radius:8px;}
button {background:#0d6efd;color:white;border:none;cursor:pointer;}
button:hover {background:#0b5ed7;}
pre {white-space:pre-wrap;word-wrap:break-word;background:#f7f7f7;padding:10px;border-radius:8px;}
.summary-table {width:100%;border-collapse:collapse;}
.summary-table th {background:#0d6efd;color:white;padding:8px;text-align:left;}
.summary-table td {border:1px solid #ddd;padding:8px;}
.summary-table tr:nth-child(even) td{background:#f9f9f9;}
.modal{display:none;position:fixed;z-index:1000;left:0;top:0;width:100%;height:100%;overflow:auto;background:rgba(0,0,0,0.5);}
.modal-content{background:#fff;margin:8% auto;padding:20px;border-radius:12px;width:80%;max-width:600px;}
.close{float:right;font-size:24px;font-weight:bold;cursor:pointer;}
.close:hover{color:#000;}
</style>
<script src="https://unpkg.com/html5-qrcode" defer></script>
</head>
<body>
<h1>myDATA QR Viewer</h1>
<p>Σκάναρε QR, ανέβασε εικόνα/PDF ή γράψε ΜΑΡΚ / URL.</p>

<p><a href="{{ url_for('home') }}">⬅ Επιστροφή στο μενού</a></p>

<div class="card">
<h3>1) Σάρωση QR</h3>
<div id="reader"></div>
<p>Περιβάλλον: {{ env|e }}, Endpoint: {{ endpoint|e }}</p>
</div>

<div class="card">
<h3>2) Εισαγωγή ΜΑΡΚ χειροκίνητα (ή URL)</h3>
<form method="post">
<input type="text" name="mark" placeholder="π.χ. 123456789012345  - ή -  https://... (URL με mark)" />
<button type="submit">Ανάκτηση</button>
</form>
</div>

<div class="card">
<h3>3) Upload εικόνας ή PDF</h3>
<form method="post" enctype="multipart/form-data">
<input type="file" name="file" />
<button type="submit">Ανέβασμα & Ανάκτηση</button>
</form>
</div>

{% if message %}
<div class="card" style="background:#e6ffed;border-color:#b7f5c6;">
<h3>OK</h3><pre>{{ message }}</pre>
</div>
{% endif %}

{% if error %}
<div class="card" style="background:#fff5f5;border-color:#f5c2c7;">
<h3>Σφάλμα</h3><pre>{{ error }}</pre>
</div>
{% endif %}

{% if summary %}
<div id="summaryModal" class="modal">
<div class="modal-content">
<span class="close" onclick="document.getElementById('summaryModal').style.display='none';">&times;</span>
<h3>Περίληψη Παραστατικού</h3>
<table class="summary-table">
<tr><th colspan="2">Εκδότης</th></tr>
<tr><td>ΑΦΜ</td><td>{{ summary['Εκδότης']['ΑΦΜ'] }}</td></tr>
<tr><td>Επωνυμία</td><td style="white-space:normal;word-break:break-word;">{{ summary['Εκδότης']['Επωνυμία'] }}</td></tr>
<tr><th colspan="2">Στοιχεία Παραστατικού</th></tr>
<tr><td>Σειρά</td><td>{{ summary['Στοιχεία Παραστατικού']['Σειρά'] }}</td></tr>
<tr><td>Αριθμός</td><td>{{ summary['Στοιχεία Παραστατικού']['Αριθμός'] }}</td></tr>
<tr><td>Ημερομηνία</td><td>{{ summary['Στοιχεία Παραστατικού']['Ημερομηνία'] }}</td></tr>
<tr><td>Είδος</td><td>{{ summary['Στοιχεία Παραστατικού']['Είδος'] }}</td></tr>
<tr><th colspan="2">Σύνολα</th></tr>
<tr><td>Καθαρή Αξία</td><td>{{ summary['Σύνολα']['Καθαρή Αξία'] }}</td></tr>
<tr><td>ΦΠΑ</td>
<td style="color: {% if summary['Σύνολα']['ΦΠΑ']|float > 100 %}red{% else %}green{% endif %};">
{{ summary['Σύνολα']['ΦΠΑ'] }}
</td></tr>
<tr><td>Σύνολο</td>
<td style="color: {% if summary['Σύνολα']['Σύνολο']|float > 500 %}red{% else %}black{% endif %};">
{{ summary['Σύνολα']['Σύνολο'] }}
</td></tr>

</table>
</div>
</div>
{% endif %}

{% if payload %}
<div class="card">
<h3>JSON (ολόκληρο)</h3>
<pre>{{ payload }}</pre>
</div>
{% endif %}

{% if raw %}
<div class="card">
<h3>XML Απόκριση</h3>
<pre>{{ raw }}</pre>
</div>
{% endif %}

<script>
document.addEventListener("DOMContentLoaded", function(){
  if (window.Html5Qrcode) {
    const html5QrcodeScanner = new Html5QrcodeScanner("reader", { fps:10, qrbox:240 });
    html5QrcodeScanner.render((decodedText)=>{
      const mark = (function(text){
        try{
          if(/^\d{15}$/.test(text.trim())) return text.trim();
          const url=new URL(text);
          const params=new URLSearchParams(url.search||"");
          const keys=["mark","MARK","invoiceMark","invMark","ΜΑΡΚ","Μ.Α.Ρ.Κ.","Μ.Αρ.Κ."];
          for(const k of keys){
            const v=params.get(k);
            if(v && /^\d{15}$/.test(v)) return v;
          }
        }catch(e){}
        return null;
      })(decodedText);
      if(mark){
        const form=document.createElement("form");
        form.method="POST";
        const input=document.createElement("input");
        input.type="hidden"; input.name="mark"; input.value=mark;
        form.appendChild(input); document.body.appendChild(form); form.submit();
      } else { alert("Το QR διαβάστηκε αλλά δεν βρέθηκε έγκυρος ΜΑΡΚ."); }
    });
  }

  {% if summary %}
    document.getElementById('summaryModal').style.display = 'block';
  {% endif %}
});
</script>

</body>
</html>
"""

PLACEHOLDER_HTML = """<!doctype html><html lang="el"><head><meta charset="utf-8"><title>{{ title }}</title>
<style>body{font-family:Arial,sans-serif;max-width:900px;margin:20px auto;background:#fafafa}.card{background:#fff;padding:16px;border-radius:12px;box-shadow:0 2px 6px rgba(0,0,0,0.05)}</style></head>
<body><div class="card"><h1>{{ title }}</h1><p>{{ message }}</p><p><a href='{{ url_for("home") }}'>⬅ Επιστροφή</a></p></div></body></html>
"""

LIST_HTML = """<!doctype html>
<html lang="el">
<head>
<meta charset="UTF-8">
<title>Λίστα Παραστατικών</title>
<style>
body {font-family:Arial,sans-serif;max-width:1100px;margin:20px auto;background:#fafafa;}
.card {background:white;padding:16px;margin:16px 0;border-radius:12px;box-shadow:0 2px 6px rgba(0,0,0,0.05);}
.summary-table {width:100%;border-collapse:collapse;table-layout:fixed;}
.summary-table th, .summary-table td {border:1px solid #ddd;padding:8px;vertical-align:top;position:relative;}
.summary-table th {background:#0d6efd;color:white;user-select:none; cursor:grab;}
.summary-table th:active {cursor:grabbing;}
.summary-table tr:nth-child(even) td{background:#f9f9f9;}
nav {display:flex;gap:10px;margin-bottom:10px;}
nav a, nav span {text-decoration:none;padding:8px 12px;border-radius:8px;background:#0d6efd;color:#fff;}
nav a:hover {background:#0b5ed7;}
.small-btn {display:inline-block;padding:8px 12px;border-radius:8px;background:#198754;color:#fff;text-decoration:none;}
.cell-wrap {white-space:pre-wrap; word-break:break-word; max-width:360px; overflow:hidden;}
.controls {display:flex; gap:10px; align-items:center; flex-wrap:wrap; margin-top:8px;}
.controls input[type="text"] {padding:8px; border-radius:8px; border:1px solid #ddd; min-width:260px;}
.controls .danger {background:#dc3545;}
.controls .primary {background:#0d6efd;}
.controls .secondary {background:#6c757d;}
/* arrows */
th.sorted-asc::after { content: " \\2191"; }
th.sorted-desc::after { content: " \\2193"; }
/* resize handle */
th .resize-handle{
  position:absolute; right:0; top:0; width:6px; height:100%;
  cursor:col-resize; user-select:none;
}
th.drag-over-left { box-shadow: inset 3px 0 0 rgba(0,0,0,0.25); }
th.drag-over-right{ box-shadow: inset -3px 0 0 rgba(0,0,0,0.25); }
{{ css_numcols | safe }}
</style>
</head>
<body>
<nav>
  <a href="{{ url_for('home') }}">Αρχική</a>
  <a href="{{ url_for('viewer') }}">Εισαγωγή Παραστατικού</a>
  <a href="{{ url_for('options') }}">Επιλογές</a>
  <span style="background:#6c757d">Λίστα Παραστατικών</span>
</nav>

<div class="card">
  <h1>Λίστα Παραστατικών</h1>

  <div class="controls">
    <input type="text" id="globalSearch" placeholder="🔎 Αναζήτηση σε όλες τις στήλες...">
    {% if file_exists %}
      <a class="small-btn primary" href="{{ url_for('download_excel') }}">⬇️ Κατέβασμα .xlsx</a>
    {% endif %}
    <a class="small-btn secondary" href="{{ url_for('viewer') }}">➕ Εισαγωγή Παραστατικού</a>
  </div>

  {% if error %}
    <div style="background:#fff5f5;padding:12px;border-radius:8px;margin-top:12px;">{{ error }}</div>
  {% endif %}

  {% if table_html %}
    <form method="POST" action="{{ url_for('delete_invoices') }}">
      <div style="overflow:auto;margin-top:12px;">
        {{ table_html | safe }}
      </div>

      <div class="controls" style="margin-top:12px;">
        <button type="submit" class="small-btn danger">🗑️ Διαγραφή Επιλεγμένων</button>
      </div>
    </form>
  {% else %}
    <div style="color:#666;margin-top:12px;">Δεν υπάρχουν εγγραφές προς εμφάνιση.</div>
  {% endif %}
</div>

<script>
document.addEventListener("DOMContentLoaded", function(){
  const table = document.querySelector(".summary-table");
  if (!table) return;

  const thead = table.querySelector("thead");
  const tbody = table.querySelector("tbody");

  // ===== Global search (μόνο αυτό — αφαιρέθηκε το οριζόντιο φίλτρο) =====
  const search = document.getElementById("globalSearch");
  if (search){
    search.addEventListener("input", function(){
      const q = (search.value || "").toLowerCase();
      Array.from(tbody.rows).forEach(row=>{
        row.style.display = row.innerText.toLowerCase().includes(q) ? "" : "none";
      });
    });
  }

  // ===== Sorting (click-to-sort με ↑/↓) =====
  let lastSortedIndex = -1;
  let lastAsc = true;

  function normalizeValue(txt){
    const t = txt.trim();
    const euro = t.replace(/\./g,"").replace(",",".").replace(/[^\d\.\-]/g,"");
    if (!isNaN(parseFloat(euro)) && /[\d]/.test(euro)) return {num:parseFloat(euro), raw:t, isNum:true};
    const eng = t.replace(/,/g,"").replace(/[^\d\.\-]/g,"");
    if (!isNaN(parseFloat(eng)) && /[\d]/.test(eng)) return {num:parseFloat(eng), raw:t, isNum:true};
    return {num:0, raw:t.toLowerCase(), isNum:false};
  }

  function sortByColumn(colIndex, asc){
    const rows = Array.from(tbody.rows);
    rows.sort((a,b)=>{
      const A = a.cells[colIndex]?.innerText || "";
      const B = b.cells[colIndex]?.innerText || "";
      const nA = normalizeValue(A);
      const nB = normalizeValue(B);
      if (nA.isNum && nB.isNum) return asc ? (nA.num - nB.num) : (nB.num - nA.num);
      return asc ? nA.raw.localeCompare(nB.raw, "el", {numeric:true}) : nB.raw.localeCompare(nA.raw, "el", {numeric:true});
    });
    rows.forEach(r=>tbody.appendChild(r));
    thead.querySelectorAll("th").forEach(th=>th.classList.remove("sorted-asc","sorted-desc"));
    const th = thead.querySelectorAll("th")[colIndex];
    if (th) th.classList.add(asc ? "sorted-asc" : "sorted-desc");
    lastSortedIndex = colIndex; lastAsc = asc;
  }

  // ===== Resize handles & reorder =====
  thead.querySelectorAll("th").forEach((th, idx) => {
    // click-to-sort (exclude clicks on resize handle)
    th.addEventListener("click", function(e){
      if (e.target.classList.contains("resize-handle")) return;
      const colIndex = Array.from(thead.rows[0].cells).indexOf(th);
      const asc = (lastSortedIndex !== colIndex) ? true : !lastAsc;
      sortByColumn(colIndex, asc);
    });

    const handle = document.createElement("div");
    handle.className = "resize-handle";
    th.appendChild(handle);

    let startX = 0, startW = 0;
    function mmove(e){
      const dx = e.pageX - startX;
      const newW = Math.max(40, startW + dx);
      th.style.width = newW + "px";
    }
    function mup(){
      document.removeEventListener("mousemove", mmove);
      document.removeEventListener("mouseup", mup);
    }
    handle.addEventListener("mousedown", (e)=>{
      startX = e.pageX; startW = th.offsetWidth;
      document.addEventListener("mousemove", mmove);
      document.addEventListener("mouseup", mup);
      e.preventDefault(); e.stopPropagation();
    });

    // Reorder
    th.setAttribute("draggable","true");
    th.addEventListener("dragstart", (e)=>{
      e.dataTransfer.setData("text/plain", idx.toString());
    });
    th.addEventListener("dragover", (e)=>{
      e.preventDefault();
      const rect = th.getBoundingClientRect();
      const halfway = rect.left + rect.width / 2;
      th.classList.toggle("drag-over-left", e.clientX < halfway);
      th.classList.toggle("drag-over-right", e.clientX >= halfway);
    });
    th.addEventListener("dragleave", ()=>{
      th.classList.remove("drag-over-left","drag-over-right");
    });
    th.addEventListener("drop", (e)=>{
      e.preventDefault();
      const fromIndex = parseInt(e.dataTransfer.getData("text/plain"), 10);
      const headers = Array.from(thead.rows[0].cells);
      const toIndex = headers.indexOf(th);
      if (fromIndex === -1 || toIndex === -1 || fromIndex === toIndex) {
        th.classList.remove("drag-over-left","drag-over-right");
        return;
      }
      const dropOnRightHalf = th.classList.contains("drag-over-right");
      th.classList.remove("drag-over-left","drag-over-right");

      const fromTh = headers[fromIndex];
      const toTh = headers[toIndex];
      if (dropOnRightHalf) {
        toTh.after(fromTh);
      } else {
        toTh.before(fromTh);
      }

      // reorder cells
      const newHeaders = Array.from(thead.rows[0].cells);
      const newOrderMap = {};
      newHeaders.forEach((h, newPos) => {
        const origPos = headers.indexOf(h);
        newOrderMap[newPos] = origPos;
      });

      Array.from(tbody.rows).forEach(tr => {
        const cells = Array.from(tr.cells);
        const newCells = new Array(cells.length);
        for (let newPos=0; newPos<newCells.length; newPos++){
          const origPos = newOrderMap[newPos];
          newCells[newPos] = cells[origPos];
        }
        newCells.forEach((c, i)=>{
          if (i === 0) tr.appendChild(c); else newCells[i-1].after(c);
        });
      });

      thead.querySelectorAll("th").forEach(h=>h.classList.remove("sorted-asc","sorted-desc"));
      lastSortedIndex = -1;
    });
  });

  // ===== Select all / none (checkbox in header if any) =====
  const headerCheckbox = document.getElementById("selectAll");
  if (headerCheckbox){
    headerCheckbox.addEventListener("change", function(){
      const chks = table.querySelectorAll('input[type="checkbox"][name="delete_mark"]');
      chks.forEach(c => { c.checked = headerCheckbox.checked; });
    });
  }
});
</script>
</body>
</html>
"""

# ----------------------
# Routes
@app.route("/")
def home():
    return render_template_string(NAV_HTML)

@app.route("/options")
def options():
    return render_template_string(PLACEHOLDER_HTML, title="Επιλογές", message="Εδώ θα μπουν μελλοντικές ρυθμίσεις.")

@app.route("/viewer", methods=["GET", "POST"])
def viewer():
    error = ""
    payload = None
    raw = None
    summary = None
    message = None

    if request.method == "POST":
        input_text = request.form.get("mark", "") if "mark" in request.form else ""
        marks = []

        # 1) αν ανέβηκε αρχείο, προτεραιότητα στο αρχείο
        if "file" in request.files:
            f = request.files["file"]
            if f and f.filename:
                data = f.read()
                mark_from_file = decode_qr_from_file(data, f.filename)
                if mark_from_file:
                    marks = [mark_from_file]
                else:
                    error = "Δεν βρέθηκε ΜΑΡΚ στο αρχείο."

        # 2) αλλιώς αν υπάρχει input_text (MARK ή URL)
        if not marks and input_text:
            # αν είναι URL -> κάνουμε webscrape για όλα τα 15-ψήφια MARKs
            try:
                parsed_url = urlparse(input_text)
                if parsed_url.scheme in ("http", "https") and parsed_url.netloc:
                    marks_from_page = extract_marks_from_url(input_text)
                    if marks_from_page:
                        marks = marks_from_page
                    else:
                        # αν δεν βρέθηκε, ενημέρωση error (θα δείξουμε popup)
                        error = "Δεν βρέθηκε ΜΑΡΚ στη σελίδα."
                else:
                    # απλό text/mark
                    marks = extract_marks_from_text(input_text)
            except Exception:
                marks = extract_marks_from_text(input_text)

        if not marks:
            if not error:
                error = "Δεν βρέθηκε ΜΑΡΚ."
        else:
            successes = []
            duplicates = []
            api_errors = []
            last_summary = None
            last_payload = None
            last_raw = None

            for m in marks:
                # ΠΡΩΤΑ: έλεγχος στο RequestTransmittedDocs
                try:
                    if is_mark_transmitted(m):
                        api_errors.append((m, "το παραστατικο ειναι ηδη καταχωρημενο-χαρακτηρισμενο"))
                        continue
                except Exception as e:
                    # σε περίπτωση σφάλματος στο check, προχωράμε κανονικά (θα καταγραφεί)
                    print("is_mark_transmitted error:", e)

                try:
                    err, parsed, raw_xml, summ = fetch_by_mark(m)
                except Exception as e:
                    api_errors.append((m, f"Exception: {e}"))
                    continue

                if err:
                    api_errors.append((m, err))
                    continue
                if not parsed or not summ:
                    api_errors.append((m, "Αποτυχία parse ή κενά δεδομένα."))
                    continue

                try:
                    vat_cats = extract_vat_categories(parsed)
                    saved = save_summary_to_excel(summ, m, vat_categories=vat_cats)
                    if saved:
                        successes.append(m)
                    else:
                        duplicates.append(m)
                except Exception as e:
                    api_errors.append((m, f"Σφάλμα αποθήκευσης: {e}"))
                    continue

                last_summary = summ
                last_payload = json.dumps(parsed, ensure_ascii=False, indent=2)
                last_raw = raw_xml

            parts = []
            if successes:
                parts.append(f"Αποθηκεύτηκαν: {len(successes)} ({', '.join(successes)})")
            if duplicates:
                parts.append(f"Διπλοεγγραφές (παραλήφθηκαν): {len(duplicates)} ({', '.join(duplicates)})")
            if api_errors:
                parts.append(f"Σφάλματα/Μηνύματα: {len(api_errors)}")
                parts += [f"- {m}: {e}" for m, e in api_errors[:20]]
            message = "\n".join(parts) if parts else None

            if last_summary:
                summary = last_summary
                payload = last_payload
                raw = last_raw

            if not successes and not duplicates and api_errors and not summary:
                error = "Απέτυχαν όλες οι προσπάθειες. Δες λεπτομέρειες στο μήνυμα."

    return render_template_string(
        VIEWER_HTML,
        error=error,
        payload=payload,
        raw=raw,
        summary=summary,
        env=ENV,
        endpoint=REQUESTDOCS_URL,
        message=message
    )

@app.route("/list", methods=["GET"])
def list_invoices():
    filepath = EXCEL_FILE
    table_html = ""
    error = ""
    css_numcols = ""

    if os.path.exists(filepath):
        try:
            df = pd.read_excel(filepath, engine="openpyxl", dtype=str).fillna("")
            df = df.astype(str)

            # Απόκρυψη στήλης ΦΠΑ_ΑΝΑΛΥΣΗ από τη λίστα αν υπάρχει
            if "ΦΠΑ_ΑΝΑΛΥΣΗ" in df.columns:
                df = df.drop(columns=["ΦΠΑ_ΑΝΑΛΥΣΗ"])

            # Προσθήκη checkbox για διαγραφή (χρησιμοποιούμε το MARK ως id)
            if "MARK" in df.columns:
                checkboxes = df["MARK"].apply(lambda v: f'<input type="checkbox" name="delete_mark" value="{str(v)}">')
                df.insert(0, "✓", checkboxes)

            table_html = df.to_html(classes="summary-table", index=False, escape=False)

            # Βάλε checkbox "select all" στον header της πρώτης στήλης
            table_html = table_html.replace(
                "<th>✓</th>", '<th><input type="checkbox" id="selectAll" title="Επιλογή όλων"></th>'
            )

            table_html = table_html.replace("<td>", '<td><div class="cell-wrap">').replace("</td>", "</div></td>")

            # Δεξιά στοίχιση για αριθμητικές στήλες
            headers = re.findall(r'<th[^>]*>(.*?)</th>', table_html, flags=re.S)
            num_indices = []
            for i, h in enumerate(headers):
                text = re.sub(r'<.*?>', '', h).strip()
                if text in ("Καθαρή Αξία", "ΦΠΑ", "Σύνολο", "Total", "Net", "VAT") or "ΦΠΑ" in text or "ΠΟΣΟ" in text:
                    num_indices.append(i+1)  # nth-child 1-based
            css_rules = []
            for idx in num_indices:
                css_rules.append(f".summary-table td:nth-child({idx}), .summary-table th:nth-child({idx}) {{ text-align: right; }}")
            css_numcols = "\n".join(css_rules)

        except Exception as e:
            error = f"Σφάλμα ανάγνωσης Excel: {e}"
    else:
        error = "Δεν βρέθηκε το αρχείο invoices.xlsx."

    return render_template_string(
        LIST_HTML,
        table_html=table_html,
        error=error,
        file_exists=os.path.exists(filepath),
        css_numcols=css_numcols
    )

@app.route("/delete", methods=["POST"])
def delete_invoices():
    """
    Διαγράφει εγγραφές βάσει MARK από το invoices.xlsx και επιστρέφει στη λίστα.
    """
    marks_to_delete = request.form.getlist("delete_mark")
    if not marks_to_delete:
        return redirect(url_for("list_invoices"))

    if os.path.exists(EXCEL_FILE):
        try:
            df = pd.read_excel(EXCEL_FILE, engine="openpyxl", dtype=str).fillna("")
            if "MARK" in df.columns:
                before = len(df)
                df = df[~df["MARK"].astype(str).isin([str(m).strip() for m in marks_to_delete])]
                after = len(df)
                if after != before:
                    df.to_excel(EXCEL_FILE, index=False, engine="openpyxl")
        except Exception as e:
            print("Σφάλμα διαγραφής:", e)

    return redirect(url_for("list_invoices"))

@app.route("/download", methods=["GET"])
def download_excel():
    if not os.path.exists(EXCEL_FILE):
        return ("Το αρχείο .xlsx δεν υπάρχει.", 404)
    return send_file(
        EXCEL_FILE,
        as_attachment=True,
        download_name="invoices.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

# ----------------------
if __name__ == "__main__":
    # debug=True μόνο σε development
    app.run(host="0.0.0.0", port=5001, debug=True)
