#!/usr/bin/env python3
import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, parse_qs, urljoin
import xml.etree.ElementTree as ET

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "el-GR,el;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://mydata.wedoconnect.com/",
    "DNT": "1",
}
MARK_RE = re.compile(r"\b\d{15}\b")  # 15-digit MARK
VAT9_RE = re.compile(r"\b\d{9}\b")   # 9-digit AFM

# -------------------- WEDOCONNECT (attachments-first) --------------------
def scrape_wedoconnect(url, timeout=20):
    """
    Πλέον: πηγαίνουμε πρώτα στα embedded attachments (XML/UBL, PDF, blob links)
    για να βρούμε το ΑΦΜ του πελάτη (counterpart). Επιστρέφει (marks_list, counterpart_vat).
    """
    sess = requests.Session()
    sess.headers.update(HEADERS)

    try:
        r = sess.get(url, timeout=timeout)
        r.raise_for_status()
    except Exception as e:
        print(f"[RequestError] {e}")
        return [], None

    soup = BeautifulSoup(r.text, "html.parser")

    # MARK(s) από το κείμενο της σελίδας (γρήγορο)
    txt = soup.get_text(" ", strip=True)
    marks = MARK_RE.findall(txt)
    marks = sorted(set(marks)) if marks else []

    # Εντοπισμός πιθανών attachments/links (anchor hrefs, iframe file param)
    candidate_urls = []

    # a) anchors
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        full = urljoin(r.url, href)
        lowered = href.lower()
        # προτεραιότητα στο xml/ubl/mydata
        if lowered.endswith(".xml") or ".xml?" in lowered or "ubl" in lowered or "mydata" in lowered:
            candidate_urls.append(full)
        elif lowered.endswith(".pdf") or ".pdf?" in lowered or "blob.core.windows.net" in lowered:
            candidate_urls.append(full)
        else:
            if "blob.core.windows.net" in href or "mydatafilecontainer" in href:
                candidate_urls.append(full)

    # b) iframe (π.χ. pdf viewer με file=)
    iframe = soup.find("iframe", id=lambda x: x and "frmPDF" in x or False)
    if iframe and iframe.get("src"):
        src = iframe["src"]
        # αν υπάρχει file=... decode και πρόσθεσε
        if "file=" in src:
            import urllib.parse as _up
            q = _up.urlparse(src).query
            qs = _up.parse_qs(q)
            if "file" in qs:
                file_url = _up.unquote(qs["file"][0])
                candidate_urls.append(file_url)
        candidate_urls.append(urljoin(r.url, src))

    # dedupe while preserving order
    seen = set()
    candidate_urls = [u for u in candidate_urls if not (u in seen or seen.add(u))]

    # Ψάχνουμε πρώτα για XML / UBL attachments (πιο αξιόπιστο)
    counterpart_vat = None
    for cu in candidate_urls:
        low = cu.lower()
        if low.endswith(".xml") or ".xml?" in low or "ubl" in low or "mydata" in low:
            try:
                r2 = sess.get(cu, timeout=timeout)
                r2.raise_for_status()
            except Exception as e:
                # skip if can't fetch
                continue

            # try parse XML
            try:
                root = ET.fromstring(r2.content)
                # namespace-agnostic search for counterpart -> vatNumber
                cp = root.find(".//{*}counterpart") or root.find(".//counterpart")
                vat_el = None
                if cp is not None:
                    vat_el = cp.find(".//{*}vatNumber") or cp.find(".//vatNumber")
                if vat_el is not None and vat_el.text and VAT9_RE.match(vat_el.text.strip()):
                    counterpart_vat = vat_el.text.strip()
                    # try to extract mark from XML if present
                    mark_xml = root.find(".//{*}mark") or root.find(".//mark")
                    if mark_xml is not None and mark_xml.text:
                        marks.append(mark_xml.text.strip())
                    break
                # fallback: any 9-digit in xml text
                m = VAT9_RE.search(r2.text)
                if m:
                    counterpart_vat = m.group(0)
                    break
            except Exception:
                # not valid XML or parse error -> regex fallback on text
                m = VAT9_RE.search(r2.text)
                if m:
                    counterpart_vat = m.group(0)
                    break

    # Αν δεν βρέθηκε σε XML, δοκιμάζουμε PDF / binary links
    if not counterpart_vat:
        for cu in candidate_urls:
            low = cu.lower()
            if low.endswith(".pdf") or ".pdf?" in low or "blob.core.windows.net" in low:
                try:
                    r3 = sess.get(cu, timeout=timeout)
                    r3.raise_for_status()
                except Exception:
                    continue
                raw = r3.content
                # search for 9-digit vat in binary
                m = re.search(rb"\b\d{9}\b", raw)
                if m:
                    counterpart_vat = m.group(0).decode("ascii")
                    break
                # fallback decode latin1 then regex
                s = raw.decode("latin1", errors="ignore")
                m2 = VAT9_RE.search(s)
                if m2:
                    counterpart_vat = m2.group(0)
                    break

    # normalize marks unique
    marks = list(dict.fromkeys(marks))

    return marks, counterpart_vat

# -------------------- MYDATAPI --------------------
def scrape_mydatapi(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.encoding = 'utf-8'
        r.raise_for_status()
    except Exception as e:
        print(f"[RequestError] {e}")
        return {}

    soup = BeautifulSoup(r.text, "html.parser")
    mark = soup.find("input", id="tmark")
    doc_type = soup.find("input", id="dtype")
    afm = soup.find("input", id="crvatnumber")
    return {
        "MARK": mark.get("value").strip() if mark else "N/A",
        "Είδος Παραστατικού": doc_type.get("value").strip() if doc_type else "N/A",
        "ΑΦΜ Πελάτη": afm.get("value").strip() if afm else "N/A"
    }

# -------------------- ECOS E-INVOICING --------------------
def scrape_einvoice(url):
    """
    Returns (marks_list, counterpart_vat)
    """
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.encoding = 'utf-8'
        r.raise_for_status()
    except Exception as e:
        print(f"[RequestError] {e}")
        return [], None

    soup = BeautifulSoup(r.text, "html.parser")

    # MARK
    mark = None
    mark_tag = soup.find("span", class_=lambda c: c and "field-Mark" in c)
    if mark_tag:
        val = mark_tag.find("span", class_="value")
        if val and val.get_text(strip=True):
            mark = val.get_text(strip=True)
    if not mark:
        txt = soup.get_text(" ", strip=True)
        m = re.search(r"Μ\.?Αρ\.?Κ\.?\s*[:\u00A0\s-]*\s*(\d{15})", txt, re.I)
        if m:
            mark = m.group(1)

    # counterpart VAT (Στοιχεία Πελάτη)
    counterpart_vat = None
    cp_section = soup.find("div", class_=lambda c: c and "section-counterparties" in c)
    if cp_section:
        left_col = cp_section.find("div", class_=lambda c: c and "section-counterparties-leftcolumn" in c)
        search_block = left_col or cp_section
        if search_block:
            vat_span = search_block.find(lambda tag: tag.name == "span" and tag.get("class") and any("Vat" in cl for cl in tag.get("class")))
            if vat_span:
                val = vat_span.find("span", class_="value")
                if val and val.get_text(strip=True):
                    candidate = val.get_text(strip=True).strip()
                    if VAT9_RE.match(candidate):
                        counterpart_vat = candidate

    # fallback general
    if not counterpart_vat:
        vat_tag = soup.find(lambda tag: tag.name == "span" and tag.get("class") and any("Vat" in cl for cl in tag.get("class")))
        if vat_tag:
            val = vat_tag.find("span", class_="value")
            if val and val.get_text(strip=True):
                candidate = val.get_text(strip=True).strip()
                if VAT9_RE.match(candidate):
                    counterpart_vat = candidate

    return ([mark] if mark else []), counterpart_vat

# -------------------- IMPACT E-INVOICING --------------------
def scrape_impact(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.encoding = 'utf-8'
        r.raise_for_status()
    except Exception as e:
        print(f"[RequestError] {e}")
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    el = soup.select_one("span.field.field-Mark span.value, span.field-Mark span.value")
    if el and el.get_text(strip=True):
        return [el.get_text(strip=True)]

    for lbl in soup.find_all(string=re.compile(r"Μ\.?Αρ\.?Κ\.?", re.I)):
        parent = lbl.parent
        if parent:
            block_text = parent.get_text(" ", strip=True)
            m = MARK_RE.search(block_text)
            if m:
                return [m.group(0)]
            sib_text = " ".join(
                str(sib.get_text(" ", strip=True) if hasattr(sib, "get_text") else sib)
                for sib in parent.next_siblings
            )
            m2 = MARK_RE.search(sib_text)
            if m2:
                return [m2.group(0)]
    full_text = soup.get_text(" ", strip=True)
    m = MARK_RE.search(full_text)
    return [m.group(0)] if m else []

# -------------------- EPSILON --------------------
def scrape_epsilon(url):
    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"

    # documentId
    docid = None
    if "/DocViewer/" in parsed.path:
        docid = parsed.path.split("/DocViewer/")[-1]
    else:
        q = parse_qs(parsed.query)
        if "documentId" in q:
            docid = q["documentId"][0]

    if not docid:
        return None, None, {"error": "documentId not found", "attempt_url": url}

    getfile_url = f"{base}/filedocument/getfile?fileType=3&documentId={docid}"
    sess = requests.Session()
    sess.headers.update(HEADERS)

    try:
        r = sess.get(getfile_url, timeout=20)
        r.raise_for_status()
    except Exception as e:
        return None, None, {"error": f"Request failed: {e}", "attempt_url": getfile_url}

    mark = None
    counterpart_vat = None

    # XML parsing
    if "xml" in r.headers.get("Content-Type", "").lower() or r.text.strip().startswith("<"):
        try:
            ns = {"a": "http://www.aade.gr/myDATA/invoice/v1.0"}
            root = ET.fromstring(r.content)
            mark_el = root.find(".//a:mark", ns)
            if mark_el is not None:
                mark = mark_el.text.strip()
            counterpart_vat_el = root.find(".//a:counterpart/a:vatNumber", ns)
            if counterpart_vat_el is not None:
                counterpart_vat = counterpart_vat_el.text.strip()
        except Exception as e:
            return None, None, {"error": f"XML parse failed: {e}", "attempt_url": getfile_url}
    else:
        # fallback HTML
        soup = BeautifulSoup(r.text, "html.parser")
        sel = soup.select_one("span.field.field-Mark span.value, span.field-Mark span.value")
        if sel:
            mark = sel.get_text(strip=True)
        txt = soup.get_text(" ", strip=True)
        if not mark:
            m = re.search(r"\b\d{15}\b", txt)
            if m:
                mark = m.group(0)
        m2 = re.search(r"(?:AFM|vatNumber|crvatnumber)[\"']?\s*[:=]?\s*[\"']?(\d{9})[\"']?", txt, re.I)
        if m2:
            counterpart_vat = m2.group(1)

    return mark, counterpart_vat, {"attempt_url": getfile_url, "status_code": r.status_code}

# -------------------- MAIN --------------------
def main():
    url = input("Εισάγετε το URL: ").strip()
    domain = urlparse(url).netloc.lower()
    data = {}
    marks = []
    counterpart_vat = None

    if "wedoconnect" in domain:
        source = "Wedoconnect"
        marks, counterpart_vat = scrape_wedoconnect(url)
    elif "mydatapi.aade.gr" in domain:
        source = "MyData"
        data = scrape_mydatapi(url)
        marks = [data.get("MARK", "N/A")]
    elif "einvoice.s1ecos.gr" in domain:
        source = "ECOS E-Invoicing"
        marks, counterpart_vat = scrape_einvoice(url)
    elif "einvoice.impact.gr" in domain or "impact.gr" in domain:
        source = "Impact E-Invoicing"
        marks = scrape_impact(url)
    elif "epsilonnet.gr" in domain:
        source = "Epsilon (myData)"
        mark, counterpart_vat, info = scrape_epsilon(url)
        marks = [mark] if mark else []
    else:
        print("Άγνωστο URL. Δεν μπορεί να γίνει scrape.")
        return

    print(f"\nΠηγή: {source}")
    if marks:
        print("\nΒρέθηκαν MARK(s):")
        for m in marks:
            print(m)
    else:
        print("Δεν βρέθηκε MARK.")

    # ειδική εμφάνιση ΑΦΜ πελάτη για Wedoconnect / ECOS / Epsilon
    if source == "Wedoconnect":
        if counterpart_vat:
            print("\nΑΦΜ Πελάτη (counterpart):", counterpart_vat)
        else:
            print("\nΔεν βρέθηκε ΑΦΜ πελάτη (counterpart) στα attachments.")

    if source == "ECOS E-Invoicing":
        if counterpart_vat:
            print("\nΑΦΜ Πελάτη (counterpart):", counterpart_vat)

    if source == "MyData":
        afm = data.get("ΑΦΜ Πελάτη", "")
        if afm:
            print("\nΑΦΜ Πελάτη:", afm)
        if "απόδειξη" in data.get("Είδος Παραστατικού", "").lower():
            print("\n⚠️ Πρόκειται για απόδειξη!")

    if source == "Epsilon (myData)":
        if marks:
            print("\nMARK:", marks[0])
        if counterpart_vat:
            print("\nCounterpart VAT:", counterpart_vat)

if __name__ == "__main__":
    main()
