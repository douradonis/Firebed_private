#!/usr/bin/env python3
# scraper.py - unified scrapers producing same output schema for multiple sources
import re
import json
import requests
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from datetime import datetime
from urllib.parse import urljoin, urlparse, parse_qs, unquote

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "el-GR,el;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://mydata.wedoconnect.com/",
    "DNT": "1",
}

MARK_RE = re.compile(r"\b\d{15}\b")
VAT_RE = re.compile(r"\b\d{9}\b")
AMOUNT_RE = re.compile(r"(-?\d{1,3}(?:[.,]\d{3})*(?:[.,]\d+)?|\d+(?:[.,]\d+)?)")
DATE_PATTERNS = [r"(\d{4}-\d{2}-\d{2})", r"(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{4})", r"(\d{4}\/\d{2}\/\d{2})"]

# ---------- helpers ----------

def _clean_amount_to_comma(raw):
    """
    Καθαρίζει ποσά: αφαιρεί € και επιστρέφει δεκαδικό με κόμμα.
    Π.χ. "€ 15.17" -> "15,17", "1.234,56" -> "1234,56"
    """
    if raw is None:
        return None
    s = str(raw).strip()
    s = s.replace("€", "").replace("EUR", "").strip()
    # remove non-number except dot/comma and minus
    s = s.replace('\xa0', '').replace(' ', '')
    # handle cases with both separators
    if '.' in s and ',' in s:
        # if last separator is comma treat comma as decimal
        if s.rfind(',') > s.rfind('.'):
            s = s.replace('.', '')
        else:
            s = s.replace(',', '')
            s = s.replace('.', ',')
    else:
        if '.' in s and ',' not in s:
            s = s.replace('.', ',')
    # remove anything but digits, comma, minus
    s = re.sub(r'[^\d,\-]', '', s)
    # if multiple commas keep last as decimal
    if s.count(',') > 1:
        parts = s.split(',')
        decimals = parts[-1]
        integer = ''.join(parts[:-1])
        s = integer + ',' + decimals
    return s or None

def _fmt_date_to_ddmmyyyy(s):
    """
    Επιστρέφει ημερομηνία σε dd/mm/YYYY αν μπορεί να την παρσει.
    Δέχεται ISO, dd/mm/yyyy, yyyy-mm-dd, κτλ.
    """
    if not s:
        return None
    s = str(s).strip()
    # try iso-like
    try:
        # only date part
        dpart = s.split()[0]
        dt = datetime.fromisoformat(dpart)
        return dt.strftime("%d/%m/%Y")
    except Exception:
        pass
    # try several formats
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%Y/%m/%d", "%d.%m.%Y"):
        try:
            dpart = s.split()[0]
            dt = datetime.strptime(dpart, fmt)
            return dt.strftime("%d/%m/%Y")
        except Exception:
            continue
    # regex fallback dd/mm/yyyy
    m = re.search(r"(\d{1,2})[\/\-\.\s](\d{1,2})[\/\-\.\s](\d{4})", s)
    if m:
        d, mo, y = m.groups()
        return f"{int(d):02d}/{int(mo):02d}/{int(y)}"
    # yyyy-mm-dd fallback
    m2 = re.search(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m2:
        y, mo, d = m2.groups()
        return f"{int(d):02d}/{int(mo):02d}/{int(y)}"
    return None

def _extract_from_ubl_root(root):
    """
    Best-effort εξαγωγή από XML (UBL-like).
    Επιστρέφει dict με τα επιθυμητά πεδία (όπου βρεθούν).
    """
    out = {
        "issuer_vat": None,
        "issue_date": None,
        "issuer_name": None,
        "progressive_aa": None,
        "doc_type": None,
        "total_amount": None,
        "MARK": None
    }

    def find_text_by_localname(elem, localname):
        for el in elem.iter():
            if el.tag is None:
                continue
            ln = el.tag.split('}')[-1].lower()
            if ln == localname.lower() and el.text and el.text.strip():
                return el.text.strip()
        return None

    # issuer VAT: common locations
    for tagname in ("AccountingSupplierParty", "SupplierParty", "AccountingCustomerParty", "Supplier", "AccountingSupplier"):
        for candidate in root.findall(".//{*}" + tagname):
            v = find_text_by_localname(candidate, "vatNumber") or find_text_by_localname(candidate, "CompanyID") or find_text_by_localname(candidate, "ID")
            if v:
                m = VAT_RE.search(v)
                if m:
                    out["issuer_vat"] = m.group(0)
                    break
        if out["issuer_vat"]:
            break

    # fallback scan full xml text for VAT
    if not out["issuer_vat"]:
        all_text = ET.tostring(root, encoding="utf-8", method="text").decode("utf-8")
        m = VAT_RE.search(all_text)
        if m:
            out["issuer_vat"] = m.group(0)

    # issue date
    for el in root.iter():
        ln = el.tag.split("}")[-1].lower()
        if ln in ("issuedate", "issue_date", "date", "documentdate"):
            if el.text and el.text.strip():
                out["issue_date"] = _fmt_date_to_ddmmyyyy(el.text.strip())
                break

    # issuer name
    for el in root.iter():
        ln = el.tag.split("}")[-1].lower()
        if ln in ("partyname", "name", "companyname", "suppliername"):
            if el.text and el.text.strip():
                out["issuer_name"] = el.text.strip()
                break

    # progressive a/a (look for sequence-like tags)
    for el in root.iter():
        ln = el.tag.split("}")[-1].lower()
        if any(k in ln for k in ("sequential", "sequence", "progres", "saa", "serial", "progress")):
            txt = (el.text or "").strip()
            if txt and re.search(r"\d{2,}", txt):
                out["progressive_aa"] = re.sub(r"\D", "", txt)
                break

    # doc type
    for el in root.iter():
        ln = el.tag.split("}")[-1].lower()
        if ln in ("invoicetypecode", "documenttype", "documenttypecode", "typedocument", "doctype"):
            if el.text and el.text.strip():
                out["doc_type"] = el.text.strip()
                break

    # total amount
    for el in root.iter():
        ln = el.tag.split("}")[-1].lower()
        if ln in ("payableamount", "legalmonetarytotal", "grandtotal", "totalamount", "amount"):
            txt = (el.text or "").strip()
            if txt and re.search(r"[0-9]", txt):
                out["total_amount"] = _clean_amount_to_comma(txt)
                break
    # fallback numeric search
    if not out["total_amount"]:
        root_text = ET.tostring(root, encoding="utf-8", method="text").decode("utf-8")
        m = re.search(r"([0-9]{1,3}(?:[.,][0-9]{3})*[.,][0-9]{1,2})", root_text)
        if m:
            out["total_amount"] = _clean_amount_to_comma(m.group(1))

    # MARK
    mark = find_text_by_localname(root, "mark") or find_text_by_localname(root, "tmark") or find_text_by_localname(root, "markid")
    if mark:
        mm = MARK_RE.search(mark)
        if mm:
            out["MARK"] = mm.group(0)

    return out

def _norm_date_to_ddmmyyyy(s):
    if not s:
        return None
    s = str(s).strip()
    # try iso-ish
    try:
        tok = s.split()[0]
        dt = datetime.fromisoformat(tok)
        return dt.strftime("%d/%m/%Y")
    except Exception:
        pass
    for p in DATE_PATTERNS:
        m = re.search(p, s)
        if m:
            tok = m.group(1)
            tok2 = tok.replace("-", "/")
            parts = tok2.split("/")
            if len(parts) == 3:
                if len(parts[0]) == 4:  # yyyy/mm/dd
                    y, mo, d = parts
                else:
                    d, mo, y = parts
                try:
                    dt = datetime(int(y), int(mo), int(d))
                    return dt.strftime("%d/%m/%Y")
                except Exception:
                    continue
    # final fallback: try parsing common datetime formats
    for fmt in ("%d/%m/%Y %H:%M", "%Y-%m-%d %H:%M", "%d-%m-%Y %H:%M", "%Y/%m/%d"):
        try:
            dt = datetime.strptime(s.split()[0], fmt.split()[0])
            return dt.strftime("%d/%m/%Y")
        except Exception:
            pass
    return None

def _clean_amount_to_comma(s):
    if s is None:
        return None
    raw = str(s).strip()
    raw = re.sub(r"[^\d\.,\-]", "", raw)
    if raw == "":
        return None
    # both separators present: last marks decimal
    if raw.count(",") and raw.count("."):
        if raw.rfind(",") > raw.rfind("."):
            raw = raw.replace(".", "")
            raw = raw.replace(",", ".")
        else:
            raw = raw.replace(",", "")
    if raw.count(",") and not raw.count("."):
        raw = raw.replace(",", ".")
    try:
        val = float(raw)
    except Exception:
        m = AMOUNT_RE.search(str(s))
        if not m:
            return None
        tok = m.group(1).replace(",", ".")
        try:
            val = float(tok)
        except Exception:
            return None
    formatted = f"{val:,.2f}"  # '1,234.56'
    formatted = formatted.replace(",", "TMP").replace(".", ",").replace("TMP", ".")
    # remove leading thousands separator if it starts with '.': keep as-is
    # ensure no currency symbol
    return formatted

def _text_of(el):
    if not el:
        return ""
    if hasattr(el, "get_text"):
        return el.get_text(" ", strip=True)
    return str(el).strip()

def _extract_input_or_text(soup, *ids_or_names):
    for key in ids_or_names:
        if not key:
            continue
        el = soup.find(id=key)
        if el:
            val = el.get("value") or el.get_text(" ", strip=True)
            if val and str(val).strip():
                return str(val).strip()
        el2 = soup.find(attrs={"name": key})
        if el2:
            val = el2.get("value") or el2.get_text(" ", strip=True)
            if val and str(val).strip():
                return str(val).strip()
        sel = soup.select_one(f"#{key}")
        if sel:
            t = sel.get_text(" ", strip=True)
            if t:
                return t
    return None

def _extract_from_jsonld(soup):
    for s in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(s.string)
        except Exception:
            continue
        if isinstance(data, dict):
            yield data
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    yield item

def _xml_text(root, xpath):
    el = root.find(xpath)
    return el.text.strip() if el is not None and el.text else None

def _ns_strip(tag):
    return tag.split("}")[-1] if "}" in tag else tag

def _extract_from_ubl_root(root):
    """Extract seller (issuer) info from UBL-like XML (namespace-agnostic)."""
    out = {"issuer_vat": None, "issuer_name": None, "issue_date": None,
           "progressive_aa": None, "doc_type": None, "total_amount": None, "MARK": None}
    # find supplier / issuer
    supplier = None
    for candidate in ("AccountingSupplierParty","SellerSupplierParty","SupplierParty","AccountingCustomerParty"):
        el = root.find(".//{*}" + candidate)
        if el is not None:
            supplier = el
            break
    if supplier is None:
        # fallback look for Party with VAT tags
        for el in root.findall(".//"):
            tagname = _ns_strip(el.tag).lower()
            if tagname in ("accountingsupplierparty","supplierparty","sellerparty"):
                supplier = el
                break
    if supplier is not None:
        # vat search inside supplier
        for sub in supplier.iter():
            tag = _ns_strip(sub.tag).lower()
            txt = (sub.text or "").strip()
            if tag in ("companyid","vatnumber","vat_number","vat"):
                m = re.search(r"(\d{9,})", txt)
                if m:
                    out["issuer_vat"] = m.group(1)
                    break
        # name
        name_el = supplier.find(".//{*}Name") or supplier.find(".//{*}CompanyName") or supplier.find(".//{*}RegistrationName")
        if name_el is not None and (name_el.text or "").strip():
            out["issuer_name"] = name_el.text.strip()
    # issue date
    for tag in ("IssueDate","IssueTime","DocumentDate"):
        d = root.find(".//{*}" + tag)
        if d is not None and (d.text or "").strip():
            out["issue_date"] = _norm_date_to_ddmmyyyy(d.text.strip())
            break
    # total amount
    for tag in ("LegalMonetaryTotal","LegalTotal","MonetaryTotal","TotalAmount"):
        el = root.find(".//{*}" + tag)
        if el is not None:
            # try PayableAmount or Payable
            pa = el.find(".//{*}PayableAmount") or el.find(".//{*}Payable") or el.find(".//{*}Amount") or el.find(".//{*}PayableAmount")
            if pa is not None and (pa.text or "").strip():
                out["total_amount"] = _clean_amount_to_comma(pa.text.strip())
                break
    if not out["total_amount"]:
        # try any element named PayableAmount
        el = root.find(".//{*}PayableAmount")
        if el is not None and (el.text or "").strip():
            out["total_amount"] = _clean_amount_to_comma(el.text.strip())
    # doc type / invoice type
    itc = root.find(".//{*}InvoiceTypeCode") or root.find(".//{*}DocumentType")
    if itc is not None and (itc.text or "").strip():
        out["doc_type"] = itc.text.strip()
    # ID / progressive no
    id_el = root.find(".//{*}ID") or root.find(".//{*}InvoiceNumber")
    if id_el is not None and (id_el.text or "").strip():
        out["progressive_aa"] = id_el.text.strip()
    # MARK in xml if any
    for el in root.findall(".//{*}mark") + root.findall(".//{*}Mark") + root.findall(".//{*}DocumentReference"):
        t = (el.text or "").strip()
        if t and MARK_RE.search(t):
            out["MARK"] = MARK_RE.search(t).group(0)
            break
    return out

# ---------- specialized scrapers (return unified dict) ----------

def scrape_www1_aade(url, timeout=15, debug=False):
    """
    Scrape pages like:
    https://www1.aade.gr/tameiakes/myweb/q1.php?SIG=...
    Return unified dict.
    """
    res = {"issuer_vat": None, "issue_date": None, "issuer_name": None,
           "progressive_aa": None, "doc_type": None, "total_amount": None,
           "is_invoice": False, "MARK": None, "source": "AADE_www1"}
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        r.raise_for_status()
        r.encoding = r.apparent_encoding or "utf-8"
        html = r.text
    except Exception as e:
        if debug: print("www1 fetch error:", e)
        return res

    soup = BeautifulSoup(html, "html.parser")
    # parse table rows where first td is label, second td is value
    for tr in soup.select("table.info tr"):
        tds = tr.find_all(["td","th"])
        if len(tds) < 2:
            continue
        label = tds[0].get_text(" ", strip=True)
        val = tds[1].get_text(" ", strip=True)
        if re.search(r"Συνολική αξία|Συνολικό ποσό|Συνολικού ποσού", label, re.I):
            res["total_amount"] = _clean_amount_to_comma(val)
        elif re.search(r"Ημερομηνία", label, re.I):
            # sample "2023-07-31 16:28" -> dd/mm/yyyy
            res["issue_date"] = _norm_date_to_ddmmyyyy(val)
        elif re.search(r"ΑΦΜ εκδότη|ΑΦΜ.*εκδότη", label, re.I):
            m = re.search(r"(\d{9,})", val)
            if m: res["issuer_vat"] = m.group(1)
        elif re.search(r"Επωνυμία", label, re.I):
            res["issuer_name"] = val.strip()
        elif re.search(r"Προοδευτικός α\/α|Προοδευτικ", label, re.I):
            res["progressive_aa"] = val.strip()
        elif re.search(r"Είδος παραστατικού", label, re.I):
            res["doc_type"] = val.strip()
            if re.search(r"τιμολόγι", val, re.I):
                res["is_invoice"] = True
        # MARK could be absent; try rows or paragraphs earlier
        if not res["MARK"]:
            m_mark = MARK_RE.search(val)
            if m_mark:
                res["MARK"] = m_mark.group(0)
    # fallback searches across page if some fields missing
    if not res["issuer_vat"]:
        m = VAT_RE.search(html)
        if m: res["issuer_vat"] = m.group(0)
    if not res["total_amount"]:
        # text near euro symbol
        m = re.search(r"€\s*([0-9\.,]+)", html)
        if m:
            res["total_amount"] = _clean_amount_to_comma(m.group(1))
    return res

def scrape_mydatapi(url, timeout=12, debug=False):
    """
    Robust extractor for mydatapi pages (id attributes, json-ld, etc.)
    """
    out = {"issuer_vat": None, "issue_date": None, "issuer_name": None,
           "progressive_aa": None, "doc_type": None, "total_amount": None,
           "is_invoice": False, "MARK": None, "source": "MyData"}
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        r.raise_for_status()
        r.encoding = r.apparent_encoding or "utf-8"
        html = r.text
    except Exception as e:
        if debug: print("mydatapi fetch error:", e)
        return out

    soup = BeautifulSoup(html, "html.parser")
    # MARK
    mark = _extract_input_or_text(soup, "tmark", "mark", "mark_id", "markNumber")
    if mark: out["MARK"] = mark.strip()
    # doc type
    doc_type = _extract_input_or_text(soup, "dtype", "doc_type", "documentType", "document_type")
    if doc_type:
        out["doc_type"] = doc_type.strip()
        if re.search(r"τιμολό?γιο|τιμολογιο|τιμολόγιο", doc_type, re.I):
            out["is_invoice"] = True
    # total
    total = _extract_input_or_text(soup, "tamount", "t_amount", "tamount_total", "tamount")
    if not total:
        label = soup.find(string=re.compile(r"Συνολικού ποσού|Συνολική αξία|Συνολικό ποσό", re.I))
        if label:
            parent = label.find_parent()
            if parent:
                nxt = parent.find_next(["input","strong","td","span"])
                if nxt: total = nxt.get("value") or nxt.get_text(" ", strip=True)
    if total:
        out["total_amount"] = _clean_amount_to_comma(total)
    # issue date
    date_raw = _extract_input_or_text(soup, "tdate", "t_date", "issueDate", "tdate")
    if not date_raw:
        lab = soup.find(string=re.compile(r"Ημερομηνία.*Έκδοσης|Ημερομηνία, ώρα", re.I))
        if lab:
            p = lab.find_parent()
            if p:
                nxt = p.find_next(["input","td","span","div"])
                if nxt:
                    date_raw = nxt.get("value") or nxt.get_text(" ", strip=True)
    out["issue_date"] = _norm_date_to_ddmmyyyy(date_raw) if date_raw else None
    # issuer vat
    vat_raw = _extract_input_or_text(soup, "vatnumber", "vat_number", "issuer_vat", "crvatnumber", "companyid", "vat")
    if not vat_raw:
        label = soup.find(string=re.compile(r"Α\.?Φ\.?Μ.*εκδότη|ΑΦΜ εκδότη|ΑΦΜ", re.I))
        if label:
            p = label.find_parent()
            if p:
                nxt = p.find_next(["input","td","span"])
                if nxt:
                    vat_raw = nxt.get("value") or nxt.get_text(" ", strip=True)
    if vat_raw:
        m = re.search(r"(\d{9,})", str(vat_raw))
        if m: out["issuer_vat"] = m.group(1)
        else: out["issuer_vat"] = re.sub(r"\D", "", str(vat_raw)) or None
    # issuer name
    iname = _extract_input_or_text(soup, "bname", "issuer_name", "issuer", "companyName", "businessName")
    if not iname:
        label = soup.find(string=re.compile(r"Επωνυμία\s*(εκδότη)?|Επωνυμία εκδότη", re.I))
        if label:
            p = label.find_parent()
            if p:
                nxt = p.find_next(["input","td","span"])
                if nxt:
                    iname = nxt.get("value") or nxt.get_text(" ", strip=True)
    out["issuer_name"] = (iname.strip() if iname else None)
    # progressive aa
    paa = _extract_input_or_text(soup, "saa", "s_aa", "saa", "saa_input", "s_aa")
    if not paa:
        lab = soup.find(string=re.compile(r"Προοδευτικ(ός|ο)\s*α\/α|Προοδευτικός", re.I))
        if lab:
            p = lab.find_parent()
            if p:
                nxt = p.find_next(["input","td","span"])
                if nxt:
                    paa = nxt.get("value") or nxt.get_text(" ", strip=True)
    out["progressive_aa"] = (str(paa).strip() if paa else None)
    # try JSON-LD fallback
    if not (out["issuer_vat"] and out["issue_date"] and out["total_amount"]):
        for obj in _extract_from_jsonld(soup):
            try:
                if not out["issuer_vat"]:
                    comp = obj.get("seller") or obj.get("provider") or obj.get("sellerOrganization")
                    if comp and isinstance(comp, dict):
                        vatc = comp.get("vatNumber") or comp.get("taxID") or comp.get("vat")
                        if vatc:
                            mm = re.search(r"(\d{9,})", str(vatc))
                            if mm: out["issuer_vat"] = mm.group(1)
                if not out["issue_date"]:
                    idate = obj.get("dateIssued") or obj.get("issueDate")
                    if idate: out["issue_date"] = _norm_date_to_ddmmyyyy(idate)
                if not out["total_amount"]:
                    tam = obj.get("totalPaymentDue") or obj.get("totalPrice") or obj.get("total")
                    if isinstance(tam, dict):
                        tamv = tam.get("amount")
                    else:
                        tamv = tam
                    if tamv: out["total_amount"] = _clean_amount_to_comma(tamv)
                if not out["issuer_name"]:
                    comp = obj.get("seller") or obj.get("provider") or obj.get("sellerOrganization")
                    if isinstance(comp, dict):
                        iname_c = comp.get("name") or comp.get("legalName")
                        if iname_c: out["issuer_name"] = iname_c
            except Exception:
                continue
    if out["doc_type"] and re.search(r"τιμολό?γιο|τιμολογιο|τιμολόγιο", out["doc_type"], re.I):
        out["is_invoice"] = True
    return out

def scrape_wedoconnect(url, timeout=20, debug=False):
    """
    Modified wedoconnect scraper:
    - Προσπαθεί να βρει XML attachments/UBL και να εξάγει πεδία.
    - Εάν το XML περιέχει <cbc:ID> (ή άλλο ID) με pipe-separated segments
      (π.χ. "094222211|18/08/2025|51|1.1|ΤΔ147|000580206"), θα:
        - πάρει πιθανό ΑΦΜ από το πρώτο segment (αν είναι 9-digit),
        - πάρει ημερομηνία από δεύτερο segment (αν μοιάζει με ημερομηνία),
        - πάρει doc_type από segment που μοιάζει σε μορφή X.Y (π.χ. "1.1" ή "13.1"),
        - πάρει progressive_aa από το τελευταίο segment αν είναι αριθμητικό.
    - Διατηρεί τα υπάρχοντα fallbacks (xml parsing μέσω _extract_from_ubl_root, HTML scanning).
    """
    out = {"issuer_vat": None, "issue_date": None, "issuer_name": None,
           "progressive_aa": None, "doc_type": None, "total_amount": None,
           "is_invoice": False, "MARK": None, "source": "Wedoconnect"}
    sess = requests.Session()
    sess.headers.update(HEADERS)
    try:
        r = sess.get(url, timeout=timeout)
        r.raise_for_status()
        html = r.text
    except Exception as e:
        if debug: print("wedoconnect fetch error:", e)
        return out

    soup = BeautifulSoup(html, "html.parser")
    # quick MARK from page
    m_mark = MARK_RE.search(html)
    if m_mark: out["MARK"] = m_mark.group(0)

    # find candidate xml/ubl links as before
    candidate_urls = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        full = urljoin(r.url, href)
        low = href.lower()
        txt = (a.get("title") or a.get("download") or a.text or "").lower()
        if any(tok in low for tok in (".xml", "az-ubl", "az_ubl", "ubl", "mydatafilecontainer", "mydata")):
            candidate_urls.append(full)
        elif any(tok in txt for tok in ("az-ubl", "mydata", "ubl", ".xml")):
            candidate_urls.append(full)
    # iframe/embed
    for iframe in soup.find_all("iframe", src=True):
        candidate_urls.append(urljoin(r.url, iframe["src"]))
    for emb in soup.find_all("embed", src=True):
        candidate_urls.append(urljoin(r.url, emb["src"]))
    seen = set()
    candidate_urls = [u for u in candidate_urls if not (u in seen or seen.add(u))]

    # helper to try parse pipe-separated cbc:ID inside an XML root
    def _try_parse_pipe_id_from_root(root):
        # search all ID elements and prefer ones containing '|'
        for id_el in root.findall(".//{*}ID") + root.findall(".//ID"):
            txt = (id_el.text or "").strip()
            if '|' in txt:
                parts = [p.strip() for p in txt.split('|')]
                # attempt mappings: first segment AFM, second date, any \d+\.\d+ as doc_type, last numeric as progressive_aa
                found = {}
                # AFM candidate (first)
                if parts and re.match(r"^\d{9}$", parts[0]):
                    found["issuer_vat"] = parts[0]
                # date candidate (try second)
                if len(parts) > 1:
                    dt = _fmt_date_to_ddmmyyyy(parts[1])
                    if dt:
                        found["issue_date"] = dt
                # doc_type candidate: look for first segment matching \d+\.\d+ or containing '13.' etc.
                doc_candidate = None
                for p in parts:
                    if re.search(r"\d+\.\d+", p):
                        doc_candidate = p
                        break
                if doc_candidate:
                    found["doc_type"] = doc_candidate
                # progressive aa: prefer last segment if numeric
                last = parts[-1]
                if re.search(r"\d{2,}", last):
                    found["progressive_aa"] = re.sub(r"\D", "", last)
                # also try to detect issuer_vat inside any segment if not found
                if "issuer_vat" not in found:
                    for p in parts:
                        m = re.search(r"(\d{9})", p)
                        if m:
                            found["issuer_vat"] = m.group(1)
                            break
                return found
        return None

    # try attachments first (prefer XML attachments)
    parsed_xml_found = False
    for cu in candidate_urls:
        try:
            r2 = sess.get(cu, timeout=timeout)
            r2.raise_for_status()
            content = r2.content
            text = r2.text
        except Exception:
            continue
        ctype = (r2.headers.get("Content-Type") or "").lower()
        if "xml" in ctype or b"<?xml" in content[:200].lower() or re.search(r"<(Invoice|InvoicesDoc|cbc:Invoice)\b", text, flags=re.I):
            try:
                root = ET.fromstring(content)
            except Exception:
                try:
                    txt = content.decode("utf-8", errors="replace")
                    idx = txt.find("<?xml")
                    if idx != -1:
                        root = ET.fromstring(txt[idx:].encode("utf-8"))
                    else:
                        continue
                except Exception:
                    continue
            # 1) try the special pipe-ID parsing
            parsed = _try_parse_pipe_id_from_root(root)
            if parsed:
                # apply parsed values
                if parsed.get("issuer_vat") and not out.get("issuer_vat"):
                    out["issuer_vat"] = parsed.get("issuer_vat")
                if parsed.get("issue_date") and not out.get("issue_date"):
                    out["issue_date"] = parsed.get("issue_date")
                if parsed.get("doc_type") and not out.get("doc_type"):
                    out["doc_type"] = parsed.get("doc_type")
                if parsed.get("progressive_aa") and not out.get("progressive_aa"):
                    out["progressive_aa"] = parsed.get("progressive_aa")
            # 2) then fallback to generic UBL extraction
            extracted = _extract_from_ubl_root(root)
            for k, v in extracted.items():
                if v and not out.get(k):
                    out[k] = v
            if out.get("MARK") is None and extracted.get("MARK"):
                out["MARK"] = extracted["MARK"]
            parsed_xml_found = True
            # if we have essential fields stop
            if out.get("issuer_vat") and out.get("total_amount"):
                break

    # If no attachments or fields remain missing, try inline XML fragments in HTML
    if not parsed_xml_found:
        # try to find inline xml in page text
        for m in re.finditer(r'(<\?xml[\s\S]{0,20000}?</(?:Invoice|InvoicesDoc|UBLInvoice)>)', html, flags=re.I):
            snippet = m.group(1)
            try:
                root = ET.fromstring(snippet.encode("utf-8"))
                parsed = _try_parse_pipe_id_from_root(root)
                if parsed:
                    if parsed.get("issuer_vat") and not out.get("issuer_vat"):
                        out["issuer_vat"] = parsed.get("issuer_vat")
                    if parsed.get("issue_date") and not out.get("issue_date"):
                        out["issue_date"] = parsed.get("issue_date")
                    if parsed.get("doc_type") and not out.get("doc_type"):
                        out["doc_type"] = parsed.get("doc_type")
                    if parsed.get("progressive_aa") and not out.get("progressive_aa"):
                        out["progressive_aa"] = parsed.get("progressive_aa")
                extracted = _extract_from_ubl_root(root)
                for k, v in extracted.items():
                    if v and not out.get(k):
                        out[k] = v
                parsed_xml_found = True
                break
            except Exception:
                continue

    # fallback HTML parsing: try to find blocks/tables with labels
    if not out["total_amount"]:
        # try common labels
        lbl = soup.find(string=re.compile(r"Συνολική αξία|Συνολικό ποσό|Συνολικού ποσού", re.I))
        if lbl:
            parent = lbl.find_parent()
            if parent:
                nxt = parent.find_next(["strong","span","td","input"])
                if nxt:
                    out["total_amount"] = _clean_amount_to_comma(nxt.get("value") or nxt.get_text(" ", strip=True))
    if not out["issuer_vat"]:
        m_v = VAT_RE.search(html)
        if m_v: out["issuer_vat"] = m_v.group(0)
    if not out["issue_date"]:
        # look for ISO date in page text
        m = re.search(r"(\d{4}-\d{2}-\d{2})", html)
        if m:
            out["issue_date"] = _norm_date_to_ddmmyyyy(m.group(1))

    # If doc_type still missing, try to find in page text or extracted doc_type
    if not out.get("doc_type"):
        # try to find "Είδος παραστατικού" label nearby
        lbl2 = soup.find(string=re.compile(r"Είδος παραστατικού", re.I))
        if lbl2:
            p = lbl2.find_parent()
            if p:
                nxt = p.find_next(["td","span","strong","input"])
                if nxt:
                    dt = (nxt.get("value") or nxt.get_text(" ", strip=True)).strip()
                    if dt:
                        out["doc_type"] = dt
    # mark is possibly already set

    # detect invoice wording in doc_type or anywhere in page
    if out.get("doc_type") and re.search(r"τιμολό?γιο|τιμολογιο", out["doc_type"], re.I):
        out["is_invoice"] = True
    else:
        # also detect numeric doc_type codes in doc_type (like 13.1 etc.) and treat according to rule:
        if out.get("doc_type"):
            mcode = re.search(r"(\d{1,2}\.\d{1,2})", str(out["doc_type"]))
            if mcode:
                code = mcode.group(1)
                # treat codes 13.1,13.2,13.31 as special (not-invoice) elsewhere — here we mark invoice if NOT those
                if code not in ("13.1", "13.2", "13.31"):
                    out["is_invoice"] = True
        # fallback page-wide detection of word 'τιμολόγ'
        page_txt = soup.get_text(" ", strip=True)
        if re.search(r"τιμολόγ", page_txt, flags=re.I):
            out["is_invoice"] = True

    # Normalize outputs
    if out["issuer_vat"]:
        m = VAT_RE.search(str(out["issuer_vat"]))
        out["issuer_vat"] = m.group(0) if m else re.sub(r"\D", "", str(out["issuer_vat"]))
    if out["issue_date"]:
        out["issue_date"] = _fmt_date_to_ddmmyyyy(out["issue_date"])
    if out["total_amount"]:
        out["total_amount"] = _clean_amount_to_comma(out["total_amount"])

    return out

def scrape_einvoice(url, timeout=15, debug=False):
    """
    ECOS e-invoicing pages: try to follow mydatalogo links or parse html, then attachments xml.
    Returns unified dict.
    """
    out = {"issuer_vat": None, "issue_date": None, "issuer_name": None,
           "progressive_aa": None, "doc_type": None, "total_amount": None,
           "is_invoice": False, "MARK": None, "source": "ECOS"}
    sess = requests.Session()
    sess.headers.update(HEADERS)
    try:
        r = sess.get(url, timeout=timeout)
        r.raise_for_status()
        html = r.text
    except Exception as e:
        if debug: print("einvoice fetch error:", e)
        return out
    soup = BeautifulSoup(html, "html.parser")
    # try mydatapi button detection
    mydatapi_candidate = None
    for a in soup.find_all("a", href=True):
        img = a.find("img")
        if img and img.get("src") and ("mydatlogo" in img["src"].lower() or "mydata" in img["src"].lower()):
            mydatapi_candidate = urljoin(r.url, a["href"])
            break
    if mydatapi_candidate:
        try:
            r2 = sess.get(mydatapi_candidate, timeout=timeout)
            r2.raise_for_status()
            resolved_url = r2.url
            # reuse mydatapi
            sub = scrape_mydatapi(resolved_url, timeout=timeout, debug=debug)
            sub["source"] = "ECOS->MyData"
            return sub
        except Exception:
            pass
    # else try attachments xml similar to wedoconnect
    candidate_urls = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        full = urljoin(r.url, href)
        low = href.lower()
        if any(tok in low for tok in (".xml", "az-ubl", "ubl", "mydatafilecontainer", "mydata")):
            candidate_urls.append(full)
    seen=set()
    candidate_urls=[u for u in candidate_urls if not (u in seen or seen.add(u))]
    for cu in candidate_urls:
        try:
            r3 = sess.get(cu, timeout=timeout)
            r3.raise_for_status()
            content = r3.content
            text = r3.text
        except Exception:
            continue
        if "xml" in (r3.headers.get("Content-Type") or "").lower() or b"<?xml" in content[:200].lower() or re.search(r"<(Invoice|InvoicesDoc|cbc:Invoice)", text, flags=re.I):
            try:
                root = ET.fromstring(content)
            except Exception:
                try:
                    txt = content.decode("utf-8", errors="replace")
                    idx = txt.find("<?xml")
                    if idx != -1:
                        root = ET.fromstring(txt[idx:].encode("utf-8"))
                    else:
                        continue
                except Exception:
                    continue
            extracted = _extract_from_ubl_root(root)
            for k,v in extracted.items():
                if v and not out.get(k):
                    out[k]=v
            if out.get("total_amount") and out.get("issuer_vat"):
                break
    # fallback: HTML search
    if not out["issuer_vat"]:
        m = VAT_RE.search(html)
        if m: out["issuer_vat"]=m.group(0)
    if not out["total_amount"]:
        m = re.search(r"€\s*([0-9\.,]+)", html)
        if m: out["total_amount"]=_clean_amount_to_comma(m.group(1))
    if out.get("doc_type") and re.search(r"τιμολό?γιο|τιμολογιο", out["doc_type"], re.I):
        out["is_invoice"]=True
    return out

def scrape_impact(url, timeout=15, debug=False):
    """
    Impact (ECOS) view pages: 
    1) Αν υπάρχει #erpQrBtn, ακολούθησε το redirect (href / data-url / onclick / script).
    2) Αν ο τελικός προορισμός είναι mydatapi/mydata, τρέξε scrape_mydatapi και γύρνα το αποτέλεσμα.
    3) Fallback: παλιό HTML parsing των πεδίων μέσα στη σελίδα impact.
    """
    out = {
        "issuer_vat": None, "issue_date": None, "issuer_name": None,
        "progressive_aa": None, "doc_type": None, "total_amount": None,
        "is_invoice": False, "MARK": None, "source": "Impact"
    }

    sess = requests.Session()
    sess.headers.update(HEADERS)
    try:
        r = sess.get(url, timeout=timeout)
        r.raise_for_status()
        html = r.text
    except Exception as e:
        if debug: print("impact fetch error:", e)
        return out

    soup = BeautifulSoup(html, "html.parser")

    # --- 1) Βρες URL του erpQrBtn (href, data-url, onclick, scripts) ---
    def _extract_erp_redirect(soup_obj, base_url):
        # άμεσο element
        btn = soup_obj.select_one("#erpQrBtn")
        cand = None
        if btn:
            # <a id="erpQrBtn" href="...">
            cand = btn.get("href")
            if not cand:
                # <button id="erpQrBtn" data-url="...">
                cand = btn.get("data-url") or btn.get("data-href")
            if not cand:
                # onclick="window.location.href='...';" / window.open("...")
                onclick = btn.get("onclick") or ""
                m = re.search(r"(?:location\.href|window\.location(?:\.href)?|document\.location(?:\.href)?|window\.open)\s*\(\s*['\"]([^'\"]+)['\"]\s*\)", onclick, flags=re.I)
                if m:
                    cand = m.group(1)
        # αν δεν βρέθηκε, δοκίμασε scripts που αναφέρουν το id
        if not cand:
            for s in soup_obj.find_all("script"):
                txt = s.string or s.get_text() or ""
                if "erpQrBtn" in txt.lower():
                    # πιάσε πρώτο URL μέσα στο script
                    m2 = re.search(r"https?://[^\s'\"<>]+", txt)
                    if m2:
                        cand = m2.group(0)
                        break
                    # ή ρυθμίσεις τύπου location.href='...'
                    m3 = re.search(r"(?:location\.href|window\.location(?:\.href)?|document\.location(?:\.href)?|window\.open)\s*\(\s*['\"]([^'\"]+)['\"]\s*\)", txt, flags=re.I)
                    if m3:
                        cand = m3.group(1)
                        break
        if cand:
            return urljoin(base_url, cand)
        return None

    erp_url = _extract_erp_redirect(soup, r.url)

    # Αν έχουμε erp_url, ακολούθησέ το και, αν πάει σε mydata, τρέξε scrape_mydatapi
    if erp_url:
        try:
            r2 = sess.get(erp_url, timeout=timeout, allow_redirects=True)
            r2.raise_for_status()
            final_u = r2.url.lower()
            if debug: print("erpQrBtn resolved to:", r2.url)

            if ("mydatapi.aade.gr" in final_u) or ("mydata.aade.gr" in final_u):
                sub = scrape_mydatapi(r2.url, timeout=timeout, debug=debug)
                sub["source"] = "Impact->MyData"
                return sub
            else:
                # μερικές φορές το intermediate redirect ξαναστέλνει σύνδεσμο για mydatapi στη σελίδα
                sub_try = scrape_mydatapi(r2.url, timeout=timeout, debug=debug)
                if any(sub_try.get(k) for k in ("issuer_vat", "issue_date", "total_amount", "MARK")):
                    sub_try["source"] = "Impact->MyData(?)"
                    return sub_try
        except Exception as e:
            if debug: print("erpQrBtn follow error:", e)
            # συνέχισε σε fallback

    # --- 2) Fallback: παλιό HTML parsing μέσα στην impact σελίδα ---
    # MARK (συνηθισμένο DOM για Impact)
    el = soup.select_one("span.field.field-Mark span.value, span.field-Mark span.value")
    if el and el.get_text(strip=True):
        out["MARK"] = el.get_text(strip=True)

    # Πίνακες με labels (ΑΦΜ, Ημερομηνία, Συνολική αξία, Είδος παραστατικού, Α/Α)
    for lbl in soup.find_all(string=re.compile(r"Α\.?Φ\.?Μ|Ημερομηνία|Συνολική αξία|Συνολικό ποσό|Είδος παραστατικού|Α/Α", re.I)):
        parent = lbl.find_parent()
        if not parent: continue
        nxt = parent.find_next(["input","td","span","strong"])
        if not nxt: continue
        val = nxt.get("value") or nxt.get_text(" ", strip=True)

        if re.search(r"Α\.?Φ\.?Μ", lbl, re.I) and val:
            m = re.search(r"(\d{9,})", val); 
            if m: out["issuer_vat"] = m.group(1)
        if re.search(r"Ημερομηνία", lbl, re.I) and val:
            out["issue_date"] = _norm_date_to_ddmmyyyy(val)
        if re.search(r"Συνολική αξία|Συνολικό ποσό", lbl, re.I) and val:
            out["total_amount"] = _clean_amount_to_comma(val)
        if re.search(r"Είδος παραστατικού", lbl, re.I) and val:
            out["doc_type"] = val
            if re.search(r"τιμολό?γιο|τιμολογιο", val, re.I):
                out["is_invoice"] = True

    # regex fallbacks
    if not out["issuer_vat"]:
        m = VAT_RE.search(html)
        if m: out["issuer_vat"] = m.group(0)
    if not out["total_amount"]:
        m = re.search(r"€\s*([0-9\.,]+)", html)
        if m: out["total_amount"] = _clean_amount_to_comma(m.group(1))

    return out


def scrape_epsilon(url, timeout=20, debug=False):
    """
    Getfile-only approach for Epsilon DocViewer links.
    Returns dict with:
      issuer_vat, issue_date (dd/mm/YYYY), issuer_name,
      progressive_aa (from aa / saa / s_aa / snumber), doc_type (invoiceType if present),
      total_amount (comma decimal), MARK, is_invoice (bool), tried_url
      --- NOTE: if invoiceType exists and is NOT one of 13.1,13.2,13.31 => treat as invoice
    """
    from urllib.parse import urlparse, parse_qs
    import re, requests
    from bs4 import BeautifulSoup
    import xml.etree.ElementTree as ET
    from datetime import datetime

    VAT_RE = re.compile(r"\b\d{9}\b")
    MARK_RE = re.compile(r"\b\d{15}\b")
    NON_INVOICE_CODES = {"11.1", "11.2", "13.31"}  # these codes are NOT invoices; anything else (if present) => invoice

    def _clean_amount_to_comma(raw):
        if raw is None: return None
        s = str(raw).strip()
        s = s.replace("€", "").replace("EUR", "").replace("\xa0", "").replace(" ", "")
        # handle separators: prefer comma as decimal separator
        if '.' in s and ',' in s:
            if s.rfind(',') > s.rfind('.'):
                s = s.replace('.', '')
            else:
                s = s.replace(',', '')
                s = s.replace('.', ',')
        else:
            if '.' in s and ',' not in s:
                s = s.replace('.', ',')
        s = re.sub(r'[^\d,\-]', '', s)
        if s.count(',') > 1:
            parts = s.split(',')
            decimals = parts[-1]
            integer = ''.join(parts[:-1])
            s = integer + ',' + decimals
        return s or None

    def _fmt_date_to_ddmmyyyy(s):
        if not s: return None
        s = str(s).strip()
        # try iso first
        try:
            dt = datetime.fromisoformat(s.split()[0])
            return dt.strftime("%d/%m/%Y")
        except Exception:
            pass
        for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%Y/%m/%d", "%d.%m.%Y"):
            try:
                dt = datetime.strptime(s.split()[0], fmt)
                return dt.strftime("%d/%m/%Y")
            except Exception:
                continue
        m = re.search(r"(\d{1,2})[\/\-\.\s](\d{1,2})[\/\-\.\s](\d{4})", s)
        if m:
            d, mo, y = m.groups()
            return f"{int(d):02d}/{int(mo):02d}/{int(y)}"
        m2 = re.search(r"(\d{4})-(\d{2})-(\d{2})", s)
        if m2:
            y, mo, d = m2.groups()
            return f"{int(d):02d}/{int(mo):02d}/{int(y)}"
        return None

    def _extract_from_ubl_root(root):
        out = {
            "issuer_vat": None,
            "issue_date": None,
            "issuer_name": None,
            "progressive_aa": None,
            "doc_type": None,
            "total_amount": None,
            "MARK": None,
        }
        # issuer VAT (supplier)
        for candidate_tag in ("AccountingSupplierParty", "SupplierParty", "Supplier", "AccountingSupplier"):
            for cand in root.findall(".//{*}" + candidate_tag):
                for el in cand.iter():
                    ln = el.tag.split("}")[-1].lower()
                    if ln in ("vatnumber", "companyid", "id"):
                        text = (el.text or "").strip()
                        m = VAT_RE.search(text)
                        if m:
                            out["issuer_vat"] = m.group(0)
                            break
                if out["issuer_vat"]:
                    break
            if out["issuer_vat"]:
                break
        # xml-wide vat fallback
        if not out["issuer_vat"]:
            txt = ET.tostring(root, encoding="utf-8", method="text").decode("utf-8")
            m = VAT_RE.search(txt)
            if m: out["issuer_vat"] = m.group(0)

        # issue date - prefer invoiceIssueDate / IssueDate etc.
        for el in root.iter():
            ln = el.tag.split("}")[-1].lower()
            if ln in ("invoiceissuedate", "issuedate", "issue_date", "date", "documentdate", "issue", "invoice_date"):
                if el.text and el.text.strip():
                    out["issue_date"] = _fmt_date_to_ddmmyyyy(el.text.strip())
                    break

        # issuer name
        for el in root.iter():
            ln = el.tag.split("}")[-1].lower()
            if ln in ("partyname", "name", "companyname", "suppliername", "legalname"):
                if el.text and el.text.strip():
                    out["issuer_name"] = el.text.strip()
                    break

        # progressive aa (look for aa or sequence)
        for el in root.iter():
            ln = el.tag.split("}")[-1].lower()
            if ln in ("aa", "a_a", "saa", "sequence", "sequentialid", "sequentialidnumeric"):
                txt = (el.text or "").strip()
                if txt and re.search(r"\d{1,}", txt):
                    out["progressive_aa"] = re.sub(r"\D", "", txt)
                    break

        # invoiceType -> doc_type
        for el in root.iter():
            ln = el.tag.split("}")[-1].lower()
            if ln in ("invoicetype", "invoicetypecode", "invoicetypeid", "invoicetypecode"):
                if el.text and el.text.strip():
                    out["doc_type"] = el.text.strip()
                    break

        # total amount
        for el in root.iter():
            ln = el.tag.split("}")[-1].lower()
            if ln in ("payableamount", "legalmonetarytotal", "grandtotal", "totalamount", "amount", "payableamount"):
                txt = (el.text or "").strip()
                if txt and re.search(r"[0-9]", txt):
                    out["total_amount"] = _clean_amount_to_comma(txt)
                    break
        if not out["total_amount"]:
            txt = ET.tostring(root, encoding="utf-8", method="text").decode("utf-8")
            m = re.search(r"([0-9]{1,3}(?:[.,][0-9]{3})*[.,][0-9]{1,2})", txt)
            if m: out["total_amount"] = _clean_amount_to_comma(m.group(1))

        # MARK
        for el in root.iter():
            ln = el.tag.split("}")[-1].lower()
            if "mark" in ln or "tmark" in ln:
                txt = (el.text or "").strip()
                mm = MARK_RE.search(txt)
                if mm:
                    out["MARK"] = mm.group(0)
                    break

        return out

    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    docid = None
    if "/DocViewer/" in parsed.path:
        docid = parsed.path.split("/DocViewer/")[-1]
    else:
        q = parse_qs(parsed.query)
        if "documentId" in q:
            docid = q["documentId"][0]

    out = {
        "issuer_vat": None,
        "issue_date": None,
        "issuer_name": None,
        "progressive_aa": None,
        "doc_type": None,
        "total_amount": None,
        "MARK": None,
        "is_invoice": False,
        "tried_url": None,
        "source": "Epsilon-getfile-only"
    }

    if not docid:
        if debug: print("No documentId found in DocViewer URL.")
        return out

    getfile_url = f"{base}/filedocument/getfile?fileType=3&documentId={docid}"
    out["tried_url"] = getfile_url
    sess = requests.Session()
    sess.headers.update({"User-Agent": "Mozilla/5.0", "Accept": "*/*", "Referer": url})
    try:
        r = sess.get(getfile_url, timeout=timeout)
        r.raise_for_status()
    except Exception as e:
        if debug: print("getfile request failed:", e)
        return out

    content = r.content
    text = r.text or ""
    ctype = (r.headers.get("Content-Type") or "").lower()

    # Try XML first
    if "xml" in ctype or text.lstrip().startswith("<?xml") or re.search(r"<(Invoice|InvoicesDoc|cbc:Invoice|InvoiceLine)", text, flags=re.I):
        try:
            root = ET.fromstring(content)
            extracted = _extract_from_ubl_root(root)
            for k, v in extracted.items():
                if v:
                    out[k] = v
            # NEW LOGIC: if doc_type exists and is NOT one of NON_INVOICE_CODES => it's an invoice
            itype = out.get("doc_type")
            if itype:
                itype_s = str(itype).strip()
                if itype_s not in NON_INVOICE_CODES:
                    out["is_invoice"] = True
            # fallback detect word 'τιμολόγ'
            txt_all = ET.tostring(root, encoding="utf-8", method="text").decode("utf-8")
            if re.search(r"τιμολόγ", txt_all, flags=re.I):
                out["is_invoice"] = True
        except Exception as e:
            if debug: print("XML parse error:", e)

    else:
        # HTML parse fallbacks
        try:
            soup = BeautifulSoup(text, "html.parser")
            # map of ids/names we expect
            id_map = {
                "vatnumber": "issuer_vat",
                "tdate": "issue_date",
                "tamount": "total_amount",
                "t_amount": "total_amount",
                "bname": "issuer_name",
                "saa": "progressive_aa",
                "aa": "progressive_aa",
                "s_aa": "progressive_aa",
                "snumber": "progressive_aa",
                "tmark": "MARK",
                "dtype": "doc_type",
                "invoiceType": "doc_type",
                "t_date": "issue_date",
            }
            for idn, field in id_map.items():
                el = soup.find(id=idn) or soup.find(attrs={"name": idn})
                if not el: continue
                val = None
                if el.name in ("input", "textarea"):
                    val = (el.get("value") or "").strip()
                else:
                    val = el.get_text(" ", strip=True).strip()
                if not val: continue
                if field == "total_amount":
                    out[field] = out[field] or _clean_amount_to_comma(val)
                elif field == "issue_date":
                    out[field] = out[field] or _fmt_date_to_ddmmyyyy(val)
                elif field == "issuer_vat":
                    m = VAT_RE.search(val)
                    if m: out[field] = out[field] or m.group(0)
                elif field == "MARK":
                    m = MARK_RE.search(val)
                    if m: out[field] = out[field] or m.group(0)
                else:
                    out[field] = out[field] or val

            # wide page fallbacks
            page_txt = soup.get_text(" ", strip=True)
            if not out["total_amount"]:
                m = re.search(r"(?:Συνολική αξία|Συνολικού ποσού|Συνολική αξία)[^\d\w\n\r]*([0-9\.,\s€]+)", page_txt, flags=re.I)
                if not m:
                    m = re.search(r"€\s*([0-9\.,]+)", page_txt)
                if m: out["total_amount"] = _clean_amount_to_comma(m.group(1))
            if not out["issuer_vat"]:
                mv = VAT_RE.search(page_txt)
                if mv: out["issuer_vat"] = mv.group(0)
            if not out["issue_date"]:
                md = re.search(r"(\d{2}\/\d{2}\/\d{4})", page_txt)
                if md: out["issue_date"] = _fmt_date_to_ddmmyyyy(md.group(1))

            # NEW LOGIC: if doc_type exists and is NOT one of NON_INVOICE_CODES => it's an invoice
            if out.get("doc_type"):
                dval = str(out["doc_type"]).strip()
                if dval not in NON_INVOICE_CODES:
                    out["is_invoice"] = True

            # fallback text detection
            if re.search(r"τιμολόγ", page_txt, flags=re.I):
                out["is_invoice"] = True

        except Exception as e:
            if debug: print("HTML parse error on getfile response:", e)

    # Normalize outputs
    if out["issuer_vat"]:
        m = VAT_RE.search(str(out["issuer_vat"]))
        out["issuer_vat"] = m.group(0) if m else re.sub(r"\D", "", str(out["issuer_vat"]))
    if out["issue_date"]:
        out["issue_date"] = _fmt_date_to_ddmmyyyy(out["issue_date"])
    if out["total_amount"]:
        out["total_amount"] = _clean_amount_to_comma(out["total_amount"])

    # final invoiceType numeric check (if doc_type has numeric code like '13.1' embedded)
    if not out["is_invoice"] and out.get("doc_type"):
        mcode = re.search(r"(\d{1,2}\.\d{1,2})", str(out["doc_type"]))
        if mcode:
            if mcode.group(1) not in NON_INVOICE_CODES:
                out["is_invoice"] = True

    if debug:
        print("scrape_epsilon (getfile-only) result:", out)

    return out

def scrape_s1ecos(url, timeout=15, debug=False):
    """
    ECOS/S1 einvoice pages, π.χ. https://einvoice.s1ecos.gr/v/...
    1) Βρίσκουμε το #erpQrBtn και ακολουθούμε το redirect.
    2) Αν καταλήξει σε mydatapi/mydata → τρέχουμε scrape_mydatapi.
    3) Fallback: απλό parsing από τη σελίδα (αν υπάρχει).
    """
    out = {
        "issuer_vat": None, "issue_date": None, "issuer_name": None,
        "progressive_aa": None, "doc_type": None, "total_amount": None,
        "is_invoice": False, "MARK": None, "source": "S1ECOS"
    }

    sess = requests.Session()
    sess.headers.update(HEADERS)
    try:
        r = sess.get(url, timeout=timeout, allow_redirects=True)
        r.raise_for_status()
        html = r.text
    except Exception as e:
        if debug: print("s1ecos fetch error:", e)
        return out

    soup = BeautifulSoup(html, "html.parser")

    # --- εντοπισμός redirect από το κουμπί/σκριπτάκια του viewer ---
    def _extract_erp_redirect(soup_obj, base_url):
        btn = soup_obj.select_one("#erpQrBtn")
        cand = None
        if btn:
            cand = btn.get("href") or btn.get("data-url") or btn.get("data-href")
            if not cand:
                onclick = btn.get("onclick") or ""
                m = re.search(
                    r"(?:location\.href|window\.location(?:\.href)?|document\.location(?:\.href)?|window\.open)\s*\(\s*['\"]([^'\"]+)['\"]\s*\)",
                    onclick, flags=re.I
                )
                if m: cand = m.group(1)

        if not cand:
            for s in soup_obj.find_all("script"):
                txt = s.string or s.get_text() or ""
                if "erpQrBtn" in txt.lower():
                    m2 = re.search(r"https?://[^\s'\"<>]+", txt)
                    if m2:
                        cand = m2.group(0); break
                    m3 = re.search(
                        r"(?:location\.href|window\.location(?:\.href)?|document\.location(?:\.href)?|window\.open)\s*\(\s*['\"]([^'\"]+)['\"]\s*\)",
                        txt, flags=re.I
                    )
                    if m3:
                        cand = m3.group(1); break
        return urljoin(base_url, cand) if cand else None

    erp_url = _extract_erp_redirect(soup, r.url)

    if erp_url:
        try:
            r2 = sess.get(erp_url, timeout=timeout, allow_redirects=True)
            r2.raise_for_status()
            final_u = r2.url.lower()
            if debug: print("s1ecos erpQrBtn resolved to:", r2.url)

            if ("mydatapi.aade.gr" in final_u) or ("mydata.aade.gr" in final_u):
                sub = scrape_mydatapi(r2.url, timeout=timeout, debug=debug)
                sub["source"] = "S1ECOS->MyData"
                return sub
            else:
                # δοκίμασε απευθείας μήπως είναι ενδιάμεση σελίδα με embedded mydatapi στοιχεία
                sub_try = scrape_mydatapi(r2.url, timeout=timeout, debug=debug)
                if any(sub_try.get(k) for k in ("issuer_vat", "issue_date", "total_amount", "MARK")):
                    sub_try["source"] = "S1ECOS->MyData(?)"
                    return sub_try
        except Exception as e:
            if debug: print("s1ecos follow error:", e)
            # συνέχισε στο fallback

    # --- Fallback: ελαφρύ parsing στη σελίδα S1ECOS (αν έχει ευδιάκριτα labels/τιμές) ---
    el = soup.select_one("span.field.field-Mark span.value, span.field-Mark span.value")
    if el and el.get_text(strip=True):
        out["MARK"] = el.get_text(strip=True)

    for lbl in soup.find_all(string=re.compile(r"Α\.?Φ\.?Μ|Ημερομηνία|Συνολική αξία|Συνολικό ποσό|Είδος παραστατικού|Α/Α", re.I)):
        parent = lbl.find_parent()
        if not parent: continue
        nxt = parent.find_next(["input","td","span","strong"])
        if not nxt: continue
        val = nxt.get("value") or nxt.get_text(" ", strip=True)

        if re.search(r"Α\.?Φ\.?Μ", lbl, re.I) and val:
            m = re.search(r"(\d{9,})", val)
            if m: out["issuer_vat"] = m.group(1)
        if re.search(r"Ημερομηνία", lbl, re.I) and val:
            out["issue_date"] = _norm_date_to_ddmmyyyy(val)
        if re.search(r"Συνολική αξία|Συνολικό ποσό", lbl, re.I) and val:
            out["total_amount"] = _clean_amount_to_comma(val)
        if re.search(r"Είδος παραστατικού", lbl, re.I) and val:
            out["doc_type"] = val
            if re.search(r"τιμολό?γιο|τιμολογιο", val, re.I):
                out["is_invoice"] = True

    if not out["issuer_vat"]:
        m = VAT_RE.search(html)
        if m: out["issuer_vat"] = m.group(0)
    if not out["total_amount"]:
        m = re.search(r"€\s*([0-9\.,]+)", html)
        if m: out["total_amount"] = _clean_amount_to_comma(m.group(1))

    return out

# ---------- entry point demonstration ----------
def detect_and_scrape(url, timeout=20, debug=False):
    """
    Convenience wrapper: detect source from URL and call appropriate scraper.
    """
    domain = urlparse(url).netloc.lower()
    if "www1.aade.gr" in domain:
        return scrape_www1_aade(url, timeout=timeout, debug=debug)
    if "mydatapi.aade.gr" in domain or "mydata.aade.gr" in domain:
        return scrape_mydatapi(url, timeout=timeout, debug=debug)
    if "wedoconnect" in domain:
        return scrape_wedoconnect(url, timeout=timeout, debug=debug)
    if "einvoice.s1ecos.gr" in domain:
        return scrape_s1ecos(url, timeout=timeout, debug=debug)
    if "impact.gr" in domain or "einvoice.impact" in domain:
        return scrape_impact(url, timeout=timeout, debug=debug)
    if "epsilonnet.gr" in domain or "epsilon" in domain:
        return scrape_epsilon(url, timeout=timeout, debug=debug)
    # fallback: attempt generic wedoconnect-like scraping then page scanning
    return scrape_wedoconnect(url, timeout=timeout, debug=debug)

# if run as script, quick demo input
if __name__ == "__main__":
    u = input("URL: ").strip()
    res = detect_and_scrape(u, debug=True)
    import pprint
    pprint.pprint(res)
