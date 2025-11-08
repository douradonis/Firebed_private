#!/usr/bin/env python3
import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, parse_qs, unquote
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
VAT_RE = re.compile(r"\b\d{9}\b")    # 9-digit AFM


# -------------------- WEDOCONNECT --------------------
# -------------------- WEDOCONNECT --------------------
def _find_erp_qr_target(soup, base_url):
    """
    Βρίσκει τον τελικό target URL του κουμπιού #erpQrBtn (ή παραλλαγές),
    ακόμη κι αν είναι σε onclick, data-href κλπ. Επιστρέφει absolute URL ή None.
    """
    # 1) Άμεσο στοιχείο με id=erpQrBtn
    el = soup.find(id="erpQrBtn")
    href = None
    if el:
        href = el.get("href") or el.get("data-href") or el.get("data-url")
        if not href:
            onclick = el.get("onclick") or ""
            m = re.search(r"(?:window\.open|open|location\.href)\(\s*['\"]([^'\"]+)['\"]", onclick)
            if m:
                href = m.group(1)

    # 2) Εναλλακτικές (anchor/button με class ή id)
    if not href:
        a = soup.select_one("a#erpQrBtn, a.erpQrBtn, button#erpQrBtn, button.erpQrBtn")
        if a and a.get("href"):
            href = a["href"]

    # 3) Οποιοδήποτε <a> που δείχνει ήδη σε mydatapi
    if not href:
        for a in soup.find_all("a", href=True):
            if "mydatapi.aade.gr" in a["href"]:
                href = a["href"]
                break

    # 4) Αναζήτηση μέσα σε <script> (hard fallback)
    if not href:
        for script in soup.find_all("script"):
            sc = (script.string or script.get_text() or "")
            m = re.search(r"https?://mydatapi\.aade\.gr[^\s\"']+", sc)
            if m:
                href = m.group(0)
                break

    if not href:
        return None
    return urljoin(base_url, href)


def _erp_qr_to_mydatapi_from_soup(sess, soup, base_url, timeout=15):
    """
    Από ήδη φορτωμένη σελίδα: βρίσκει το erpQrBtn, κάνει follow, και διαβάζει το mydatapi.
    Επιστρέφει dict από scrape_mydatapi ή None.
    """
    target = _find_erp_qr_target(soup, base_url)
    if not target:
        return None

    r2 = sess.get(target, timeout=timeout, allow_redirects=True)
    r2.raise_for_status()

    final_url = r2.url
    if "mydatapi.aade.gr" not in urlparse(final_url).netloc:
        # Προσπάθησε να εξάγεις mydatapi URL από τη σελίδα (meta refresh / link)
        soup2 = BeautifulSoup(r2.text, "html.parser")
        a2 = soup2.find("a", href=lambda h: h and "mydatapi.aade.gr" in h)
        if a2:
            final_url = urljoin(r2.url, a2["href"])
        else:
            meta = soup2.find("meta", attrs={"http-equiv": lambda v: v and v.lower() == "refresh"})
            if meta and meta.get("content"):
                cm = re.search(r"url=([^;]+)", meta["content"], re.I)
                if cm:
                    final_url = urljoin(r2.url, cm.group(1).strip())

    data = scrape_mydatapi(final_url)
    if data:
        data["__mydatapi_url__"] = final_url
    return data

def _extract_from_root(root):
    """
    Δομημένη εξαγωγή από ElementTree root (namespace-agnostic).
    Επιστρέφει (marks_list, counterpart_vat or None)
    """
    marks = []
    for adr in root.findall(".//{*}AdditionalDocumentReference"):
        id_el = adr.find(".//{*}ID")
        desc_el = adr.find(".//{*}DocumentDescription")
        if id_el is not None and id_el.text:
            desc_text = (desc_el.text or "").upper() if desc_el is not None else ""
            if "M.AR.K" in desc_text or "MARK" in desc_text:
                marks.append(id_el.text.strip())

    counterpart_vat = None
    candidate_containers = (
        root.findall(".//{*}AccountingCustomerParty") +
        root.findall(".//{*}counterpart") +
        root.findall(".//{*}CounterParty")
    )
    for cont in candidate_containers:
        for el in cont.iter():
            ln = el.tag.split("}")[-1].lower()
            if ln in ("companyid", "vatnumber"):
                txt = (el.text or "").strip()
                m = VAT_RE.search(txt)
                if m:
                    counterpart_vat = m.group(0)
                    break
        if counterpart_vat:
            break

    if not counterpart_vat:
        for el in root.iter():
            txt = (el.text or "").strip()
            if txt:
                m = VAT_RE.search(txt)
                if m:
                    counterpart_vat = m.group(0)
                    break

    seen = set()
    marks = [m for m in marks if not (m in seen or seen.add(m))]
    return marks, counterpart_vat


def scrape_wedoconnect(url, timeout=20, debug=False):
    """
    Επιστρέφει (marks_list, counterpart_vat)
    """
    sess = requests.Session()
    sess.headers.update(HEADERS)

    try:
        r = sess.get(url, timeout=timeout)
        r.raise_for_status()
        html = r.text
    except Exception as e:
        if debug: print("[RequestError page]", e)
        return [], None

    soup = BeautifulSoup(html, "html.parser")
    candidate_urls = []

    # anchors
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        full = urljoin(r.url, href)
        low = href.lower()
        txt = (a.get("title") or a.get("download") or a.text or "").lower()
        if any(tok in low for tok in (".xml", "az-ubl", "az_ubl", "ubl", "mydatafilecontainer", "mydata")):
            candidate_urls.append(full)
        elif any(tok in txt for tok in ("az-ubl", "mydata", "ubl", ".xml")):
            candidate_urls.append(full)

    # iframe / embed / inline XML links
    for iframe in soup.find_all("iframe", src=True):
        candidate_urls.append(urljoin(r.url, iframe["src"]))
    for emb in soup.find_all("embed", src=True):
        candidate_urls.append(urljoin(r.url, emb["src"]))
    for m in re.findall(r'https?://[^\s"\'<>]+(?:\.xml|az-ubl|az_ubl|mydatafilecontainer|blob\.core\.windows\.net)[^\s"\'<>]*', html, flags=re.I):
        candidate_urls.append(m)

    seen = set()
    candidate_urls = [u for u in candidate_urls if not (u in seen or seen.add(u))]

    page_marks = MARK_RE.findall(html)
    marks = list(dict.fromkeys(page_marks))
    counterpart_vat = None

    for cu in candidate_urls:
        if debug: print("[debug] trying candidate:", cu)
        try:
            r2 = sess.get(cu, timeout=timeout)
            r2.raise_for_status()
            content = r2.content
            text = r2.text
        except Exception as e:
            if debug: print("[debug] candidate fetch failed:", e)
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
            marks_xml, vat_xml = _extract_from_root(root)
            for m in marks_xml:
                if m not in marks:
                    marks.append(m)
            if vat_xml:
                counterpart_vat = vat_xml
            if marks or counterpart_vat:
                return marks, counterpart_vat
            m_mark = MARK_RE.search(text)
            m_vat = VAT_RE.search(text)
            marks_f = [m_mark.group(0)] if m_mark else []
            vat_f = m_vat.group(0) if m_vat else None
            if marks_f or vat_f:
                return list(dict.fromkeys(marks + marks_f)), vat_f
            continue

        m2 = re.search(rb"\b\d{9}\b", content)
        if m2:
            counterpart_vat = m2.group(0).decode("ascii")
            return marks, counterpart_vat
        m3 = re.search(r"\b\d{9}\b", text)
        if m3:
            counterpart_vat = m3.group(0)
            return marks, counterpart_vat

    if not counterpart_vat:
        page_vat = VAT_RE.search(html)
        if page_vat:
            counterpart_vat = page_vat.group(0)

    marks = list(dict.fromkeys(marks))
    return marks, counterpart_vat

    """
    Επιστρέφει (marks_list, counterpart_vat).
    (existing logic you had previously — kept as-is for this change request)
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
    page_text = soup.get_text(" ", strip=True)
    marks = MARK_RE.findall(page_text)
    marks = list(dict.fromkeys(marks))
    # candidate attachments (simple approach)
    candidate_urls = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        full = urljoin(r.url, href)
        low = href.lower()
        if any(token in low for token in (".xml", "az-ubl", "ubl", "mydata", "mydatafilecontainer", "blob.core.windows.net")):
            candidate_urls.append(full)
        else:
            txt = (a.get("title") or a.get("download") or a.text or "").lower()
            if any(token in txt for token in ("az-ubl", "mydata", "ubl", ".xml")):
                candidate_urls.append(full)
    # try attachments for AFM
    counterpart_vat = None
    for cu in candidate_urls:
        try:
            r2 = sess.get(cu, timeout=timeout)
            r2.raise_for_status()
        except Exception:
            continue
        text = r2.text
        content = r2.content
        # try xml
        if "xml" in (r2.headers.get("Content-Type") or "").lower() or "<?xml" in text[:200]:
            try:
                root = ET.fromstring(content)
                # try common xml paths
                cp = root.find(".//{*}counterpart") or root.find(".//counterpart") or root.find(".//{*}AccountingCustomerParty")
                if cp is not None:
                    vat_el = cp.find(".//{*}vatNumber") or cp.find(".//vatNumber") or cp.find(".//{*}CompanyID")
                    if vat_el is not None and (vat_el.text or "").strip():
                        m = re.search(r"(\d{9})", vat_el.text)
                        if m:
                            counterpart_vat = m.group(1)
                            # also try find MARK inside xml
                            mark_xml = root.find(".//{*}mark") or root.find(".//mark") or root.find(".//{*}cbc:ID")
                            if mark_xml is not None and (mark_xml.text or "").strip():
                                marks.append((mark_xml.text or "").strip())
                            break
            except Exception:
                # regex fallback on text
                m = re.search(r"\b\d{9}\b", text)
                if m:
                    counterpart_vat = m.group(0)
                    break
        else:
            # binary/pd f fallback
            m = re.search(rb"\b\d{9}\b", content)
            if m:
                counterpart_vat = m.group(0).decode("ascii")
                break
            m2 = re.search(r"\b\d{9}\b", text)
            if m2:
                counterpart_vat = m2.group(0)
                break

    marks = list(dict.fromkeys(marks))
    return marks, counterpart_vat


# -------------------- MYDATAPI --------------------
def scrape_mydatapi(url):
    """
    Επιστρέφει dict όπως προηγουμένως: MARK, Είδος Παραστατικού, ΑΦΜ Πελάτη
    """
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
    Επιστρέφει (mark, counterpart_vat)
    - Αν υπάρχει #erpQrBtn που οδηγεί σε mydatapi, παίρνει MARK/ΑΦΜ από scrape_mydatapi (προτιμητέο).
    - Αλλιώς, συνεχίζει με την υπάρχουσα λογική εξαγωγής (πίνακες/attachments).
    """
    sess = requests.Session()
    sess.headers.update(HEADERS)
    try:
        r = sess.get(url, timeout=15)
        r.raise_for_status()
        r.encoding = 'utf-8'
    except Exception as e:
        print(f"[RequestError] {e}")
        return None, None

    soup = BeautifulSoup(r.text, "html.parser")

    # 1) Προσπάθησε μέσω erpQrBtn -> mydatapi
    try:
        data = _erp_qr_to_mydatapi_from_soup(sess, soup, r.url, timeout=15)
    except Exception:
        data = None

    if data:
        mark = (data.get("MARK") or "").strip()
        afm = (data.get("ΑΦΜ Πελάτη") or "").strip()
        afm = re.sub(r"\D", "", afm) if afm else None
        mark_str = mark if mark and mark != "N/A" else None
        return mark_str, afm

    # 2) Fallback στην παλιά λογική
    # 1) MARK extraction
    mark = None
    mark_tag = soup.find("span", class_=lambda c: c and "field-Mark" in c)
    if mark_tag:
        val = mark_tag.find("span", class_="value")
        if val and val.get_text(strip=True):
            mark = val.get_text(strip=True)
    if not mark:
        txt = soup.get_text(" ", strip=True)
        m = re.search(r"\b\d{15}\b", txt)
        if m:
            mark = m.group(0)

    counterpart_vat = None

    # 2) mydatalogo link (παλιό heuristic)
    mydatapi_candidate = None
    for a in soup.find_all("a", href=True):
        img = a.find("img")
        if img and img.get("src"):
            src = img["src"].lower()
            if "mydatalogo" in src or "mydatlogo" in src or ("mydata" in src and "logo" in src):
                mydatapi_candidate = urljoin(r.url, a["href"])
                break
    if not mydatapi_candidate:
        for img in soup.find_all("img", src=True):
            src = img["src"].lower()
            if "mydatalogo" in src or "mydatlogo" in src or ("mydata" in src and "logo" in src):
                parent_a = img.find_parent("a")
                if parent_a and parent_a.get("href"):
                    mydatapi_candidate = urljoin(r.url, parent_a["href"])
                    break
    if mydatapi_candidate:
        try:
            r2 = sess.get(mydatapi_candidate, timeout=15)
            r2.raise_for_status()
            resolved_url = r2.url
            mydata_info = scrape_mydatapi(resolved_url)
            afm = mydata_info.get("ΑΦΜ Πελάτη") or mydata_info.get("ΑΦΜ", "")
            if afm and afm != "N/A":
                counterpart_vat = re.sub(r"\D", "", afm)
        except Exception:
            counterpart_vat = None

    # 3) ...ό,τι είχες ήδη για εύρεση ΑΦΜ (κρατημένο όπως πριν)...
    if not counterpart_vat:
        heading = soup.find(string=re.compile(r"ΣΤΟΙΧΕΙΑ\s+ΑΝΤΙΣΥΜΒΑΛΛΟΜΕΝΟΥ|ΣΤΟΙΧΕΙΑ\s+ΠΕΛΑΤΗ", re.I))
        if heading:
            ancestor = heading.find_parent()
            table = None
            if ancestor:
                table = ancestor.find_parent("table") or ancestor.find_next("table")
            if table:
                for tr in table.find_all("tr"):
                    tr_text = tr.get_text(" ", strip=True)
                    m = re.search(r"Α\.?Φ\.?Μ\.?[:\s]*([0-9]{9})", tr_text, flags=re.I)
                    if m:
                        counterpart_vat = m.group(1)
                        break
                    tds = tr.find_all("td")
                    if tds:
                        last_txt = tds[-1].get_text(" ", strip=True)
                        m2 = re.search(r"([0-9]{9})", last_txt)
                        if m2 and ("ΑΦΜ" in tr_text.upper() or "Α.Φ.Μ." in tr_text.upper()):
                            counterpart_vat = m2.group(1)
                            break

    if not counterpart_vat:
        cp_section = soup.find("div", class_=lambda c: c and "section-counterparties" in c)
        if cp_section:
            for td in cp_section.find_all("td"):
                txt = (td.get_text(" ", strip=True) or "")
                m = re.search(r"Α\.?Φ\.?Μ\.?[:\s]*([0-9]{9})", txt, flags=re.I)
                if m:
                    counterpart_vat = m.group(1)
                    break
            if not counterpart_vat:
                for tr in cp_section.find_all("tr"):
                    tr_text = tr.get_text(" ", strip=True)
                    if "Α.Φ.Μ." in tr_text or "ΑΦΜ" in tr_text.upper():
                        tds = tr.find_all("td")
                        if tds:
                            last_txt = tds[-1].get_text(" ", strip=True)
                            m2 = re.search(r"([0-9]{9})", last_txt)
                            if m2:
                                counterpart_vat = m2.group(1)
                                break

    if not counterpart_vat:
        candidate_urls = []
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            low = href.lower()
            if any(tok in low for tok in (".xml", "az-ubl", "ubl", "mydatafilecontainer", "mydata")) or "blob.core.windows.net" in low:
                candidate_urls.append(urljoin(r.url, href))
        for iframe in soup.find_all("iframe", src=True):
            src = iframe["src"]
            fullsrc = urljoin(r.url, src)
            parsed = urlparse(fullsrc)
            qd = parse_qs(parsed.query)
            if "file" in qd:
                candidate_urls.append(unquote(qd["file"][0]))
            candidate_urls.append(fullsrc)
        seen = set()
        candidate_urls = [u for u in candidate_urls if not (u in seen or seen.add(u))]
        for cu in candidate_urls:
            try:
                r3 = sess.get(cu, timeout=15)
                r3.raise_for_status()
                text = r3.text
                content = r3.content
            except Exception:
                continue
            if "xml" in (r3.headers.get("Content-Type") or "").lower() or "<?xml" in text[:200] or re.search(r"<(Invoice|InvoicesDoc|cbc:Invoice)", text, flags=re.I):
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
                el = root.find(".//{*}AccountingCustomerParty") or root.find(".//{*}counterpart") or root.find(".//counterpart")
                if el is not None:
                    comp = el.find(".//{*}CompanyID") or el.find(".//{*}vatNumber") or el.find(".//vatNumber")
                    if comp is not None and (comp.text or "").strip():
                        m = re.search(r"(\d{9})", comp.text)
                        if m:
                            counterpart_vat = m.group(1)
                            break
                m_any = re.search(r"EL?([0-9]{9})", text)
                if m_any:
                    counterpart_vat = m_any.group(1)
                    break
            else:
                m2 = re.search(rb"\b\d{9}\b", content)
                if m2:
                    counterpart_vat = m2.group(0).decode("ascii")
                    break
                m3 = re.search(r"\b\d{9}\b", text)
                if m3:
                    counterpart_vat = m3.group(0)
                    break

    if not counterpart_vat:
        page_txt = soup.get_text(" ", strip=True)
        m = re.search(r"Α\.?Φ\.?Μ\.?[:\s]*([0-9]{9})", page_txt, flags=re.I)
        if m:
            counterpart_vat = m.group(1)
        else:
            m2 = re.search(r"\b([0-9]{9})\b", page_txt)
            if m2:
                url_match = re.search(r"/v/EL?(\d{9})[-_]", url, flags=re.I)
                if url_match:
                    url_v = url_match.group(1)
                    all9 = re.findall(r"\b([0-9]{9})\b", page_txt)
                    for a9 in all9:
                        if a9 != url_v:
                            counterpart_vat = a9
                            break
                    if not counterpart_vat and all9:
                        counterpart_vat = all9[0]
                else:
                    counterpart_vat = m2.group(1)

    if counterpart_vat:
        counterpart_vat = re.sub(r"\D", "", counterpart_vat)

    # ΕΠΙΣΤΡΟΦΗ: string (ή None), όχι λίστα
    return mark, counterpart_vat

# -------------------- IMPACT E-INVOICING --------------------
def scrape_impact(url):
    """
    Επιστρέφει (mark, counterpart_vat) — όπου mark είναι str ή None.
    1) Αν υπάρχει #erpQrBtn που οδηγεί σε mydatapi → διαβάζει MARK/ΑΦΜ από scrape_mydatapi.
    2) Αλλιώς, fallback στην παλιά εξαγωγή του MARK μόνο.
    """
    sess = requests.Session()
    sess.headers.update(HEADERS)
    try:
        r = sess.get(url, headers=HEADERS, timeout=15)
        r.encoding = 'utf-8'
        r.raise_for_status()
    except Exception as e:
        print(f"[RequestError] {e}")
        return None, None

    soup = BeautifulSoup(r.text, "html.parser")

    # 1) Προσπάθησε μέσω erpQrBtn -> mydatapi
    try:
        data = _erp_qr_to_mydatapi_from_soup(sess, soup, r.url, timeout=15)
    except Exception:
        data = None

    if data:
        mark = (data.get("MARK") or "").strip()
        afm = (data.get("ΑΦΜ Πελάτη") or "").strip()
        afm = re.sub(r"\D", "", afm) if afm else None
        mark_str = mark if mark and mark != "N/A" else None
        return mark_str, afm

    # 2) Fallback: παλιά λογική εύρεσης MARK από τη σελίδα
    el = soup.select_one("span.field.field-Mark span.value, span.field-Mark span.value")
    if el and el.get_text(strip=True):
        return el.get_text(strip=True), None

    for lbl in soup.find_all(string=re.compile(r"Μ\.?Αρ\.?Κ\.?", re.I)):
        parent = lbl.parent
        if parent:
            block_text = parent.get_text(" ", strip=True)
            m = MARK_RE.search(block_text)
            if m:
                return m.group(0), None
            sib_text = " ".join(
                str(sib.get_text(" ", strip=True) if hasattr(sib, "get_text") else sib)
                for sib in parent.next_siblings
            )
            m2 = MARK_RE.search(sib_text)
            if m2:
                return m2.group(0), None

    full_text = soup.get_text(" ", strip=True)
    m = MARK_RE.search(full_text)
    return (m.group(0) if m else None), None

# -------------------- EPSILON --------------------
def scrape_epsilon(url):
    # --- ΝΕΟ: κανονικοποίηση fd → DocViewer/UUID ---
    def _normalize_fd_to_docviewer(u: str) -> str:
        p = urlparse(u)
        # Αν είναι ήδη DocViewer, μην το πειράξεις
        if "/DocViewer/" in p.path:
            return u
        # Πιάσε το κομμάτι μετά το /fd/
        m = re.search(r"/fd/([^/?#]+)", p.path, flags=re.I)
        if not m:
            return u
        token = m.group(1)
        # Κόψε ό,τι υπάρχει μετά το ':'
        token = token.split(":")[0]
        # Κράτα μόνο hex και βεβαιώσου ότι είναι 32 ψηφία
        hexonly = re.sub(r"[^0-9a-fA-F]", "", token)
        if len(hexonly) != 32:
            return u
        # Μετατροπή 32-hex σε UUID (8-4-4-4-12)
        docid = f"{hexonly[0:8]}-{hexonly[8:12]}-{hexonly[12:16]}-{hexonly[16:20]}-{hexonly[20:32]}"
        return f"{p.scheme}://{p.netloc}/DocViewer/{docid}"

    # Εφάρμοσε κανονικοποίηση στην είσοδο
    url = _normalize_fd_to_docviewer(url)

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
    source = None

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
        marks, counterpart_vat = scrape_impact(url)

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

    # Εκτύπωση ΑΦΜ / counterpart VAT για κάθε πηγή
    if source == "Wedoconnect":
        if counterpart_vat:
            print("counterpart VAT:", counterpart_vat)
        else:
            print("Δεν βρέθηκε ΑΦΜ πελάτη.")

    if source == "MyData":
        afm = data.get("ΑΦΜ Πελάτη", "")
        if afm:
            print("ΑΦΜ Πελάτη:", afm)
        if "απόδειξη" in data.get("Είδος Παραστατικού", "").lower():
            print("⚠️ Πρόκειται για απόδειξη!")

    if source == "ECOS E-Invoicing":
        if counterpart_vat:
            print("counterpart VAT:", counterpart_vat)

    if source == "Epsilon (myData)":
        if counterpart_vat:
            print("counterpart VAT:", counterpart_vat)


if __name__ == "__main__":
    main()
