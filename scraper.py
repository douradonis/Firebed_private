# scraper_utf8.py
import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse

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

# -------------------- WEDOCONNECT --------------------
def scrape_wedoconnect(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.encoding = 'utf-8'
        r.raise_for_status()
    except Exception as e:
        print(f"[RequestError] {e}")
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    txt = soup.get_text(separator=" ", strip=True)
    found = MARK_RE.findall(txt)
    if found:
        return sorted(set(found))
    return []

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

    data = {
        "MARK": mark.get("value").strip() if mark else "N/A",
        "Είδος Παραστατικού": doc_type.get("value").strip() if doc_type else "N/A",
        "ΑΦΜ Πελάτη": afm.get("value").strip() if afm else "N/A"
    }
    return data

# -------------------- ECOS E-INVOICING --------------------
def scrape_einvoice(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.encoding = 'utf-8'
        r.raise_for_status()
    except Exception as e:
        print(f"[RequestError] {e}")
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    # look for typical span structure
    mark_tag = soup.find("span", class_="field field-Mark")
    if mark_tag:
        mark = mark_tag.find("span", class_="value")
        if mark:
            return [mark.get_text(strip=True)]

    # fallback: search text block for Μ.Αρ.Κ. followed by 15 digits
    txt = soup.get_text(" ", strip=True)
    m = re.search(r"Μ\.?Αρ\.?Κ\.?\s*[:\u00A0\s-]*\s*(\d{15})", txt, re.I)
    if m:
        return [m.group(1)]
    return []

# -------------------- IMPACT E-INVOICE --------------------
def scrape_impact(url):
    """
    Scrape pages like https://einvoice.impact.gr/v/...
    Strategy:
      - requests + BS4 (the example page contains the MARK in HTML text)
      - try CSS selector patterns, then label-sibling, then regex on page text
    """
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.encoding = 'utf-8'
        r.raise_for_status()
    except Exception as e:
        print(f"[RequestError] {e}")
        return []

    soup = BeautifulSoup(r.text, "html.parser")

    # 1) try to find a span with class/value pattern
    el = soup.select_one("span.field.field-Mark span.value, span.field-Mark span.value")
    if el and el.get_text(strip=True):
        return [el.get_text(strip=True)]

    # 2) look for label text 'Μ.Αρ.Κ.' and read the number near it
    # we search the whole text around label occurrences
    for lbl in soup.find_all(string=re.compile(r"Μ\.?Αρ\.?Κ\.?", re.I)):
        # work with parent block text
        parent = lbl.parent
        if parent:
            block_text = parent.get_text(" ", strip=True)
            m = MARK_RE.search(block_text)
            if m:
                return [m.group(0)]
            # also search next siblings text
            sib_text = ""
            for sib in parent.next_siblings:
                try:
                    sib_text += " " + (sib.get_text(" ", strip=True) if hasattr(sib, "get_text") else str(sib))
                except Exception:
                    continue
            m2 = MARK_RE.search(sib_text)
            if m2:
                return [m2.group(0)]

    # 3) fallback: search entire page text for pattern "Μ.Αρ.Κ." followed by 15 digits
    full_text = soup.get_text(" ", strip=True)
    m = re.search(r"Μ\.?Αρ\.?Κ\.?\s*[:\u00A0\s-]*\s*(\d{15})", full_text, re.I)
    if m:
        return [m.group(1)]

    # 4) last fallback: any 15-digit number on page
    found = MARK_RE.findall(full_text)
    if found:
        return [found[0]]

    return []


# -------------------- MAIN (updated) --------------------
def main():
    url = input("Εισάγετε το URL: ").strip()

    # Εντοπισμός της πηγής με βάση το domain του URL
    domain = urlparse(url).netloc.lower()
    data = {}
    marks = []

    if "wedoconnect" in domain:
        source = "Wedoconnect"
        marks = scrape_wedoconnect(url)
    elif "mydatapi.aade.gr" in domain:
        source = "MyData"
        data = scrape_mydatapi(url)
        marks = [data.get("MARK", "N/A")]
    elif "einvoice.s1ecos.gr" in domain:
        source = "ECOS E-Invoicing"
        marks = scrape_einvoice(url)
    elif "einvoice.impact.gr" in domain or "impact.gr" in domain:
        source = "Impact E-Invoicing"
        marks = scrape_impact(url)
    else:
        print("Άγνωστο URL. Δεν μπορεί να γίνει scrape.")
        return

    # Εμφάνιση αποτελεσμάτων
    print(f"\nΠηγή: {source}")
    if marks:
        print("\nΒρέθηκαν MARK(s):")
        for m in marks:
            print(m)
    else:
        print("Δεν βρέθηκε MARK.")

    # --- ΝΕΟ: στην περίπτωση MyData να εμφανίζει και το ΑΦΜ πελάτη πάντα ---
    if source == "MyData":
        afm = data.get("ΑΦΜ Πελάτη", data.get("ΑΦΜ", "N/A"))
        print(f"\nΑΦΜ Πελάτη: {afm}")

    # Προειδοποίηση αν πρόκειται για απόδειξη
    if source == "MyData" and "απόδειξη" in data.get("Είδος Παραστατικού", "").lower():
        print("\n⚠️ Προσοχή: Πρόκειται για απόδειξη!")


if __name__ == "__main__":
    main()
