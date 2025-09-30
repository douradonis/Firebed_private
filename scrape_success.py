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
    mark_tag = soup.find("span", class_="field field-Mark")
    if mark_tag:
        mark = mark_tag.find("span", class_="value")
        if mark:
            return [mark.get_text(strip=True)]
    return []

# -------------------- MAIN --------------------
def main():
    url = input("Εισάγετε το URL: ").strip()

    # Εντοπισμός της πηγής με βάση το domain του URL
    domain = urlparse(url).netloc
    if "wedoconnect" in domain:
        source = "Wedoconnect"
        marks = scrape_wedoconnect(url)
    elif "mydatapi.aade.gr" in domain:
        source = "MyData"
        data = scrape_mydatapi(url)
        marks = [data["MARK"]]
    elif "einvoice.s1ecos.gr" in domain:
        source = "ECOS E-Invoicing"
        marks = scrape_einvoice(url)
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

    # Προειδοποίηση αν πρόκειται για απόδειξη
    if source == "MyData" and "απόδειξη" in data.get("Είδος Παραστατικού", "").lower():
        print("\n⚠️ Προσοχή: Πρόκειται για απόδειξη!")

if __name__ == "__main__":
    main()
