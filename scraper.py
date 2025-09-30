from playwright.sync_api import sync_playwright
import re

MARK_RE = re.compile(r"\b\d{15}\b")  # 15-digit MARK (συνηθισμένο format)

def scrape_epsilon_mark(url):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)  # Μπορείς να βάλεις headless=False για να δεις τον περιηγητή
        page = browser.new_page()
        page.goto(url)
        page.wait_for_load_state("domcontentloaded")

        # Προσπάθεια να βρούμε το MARK μέσω CSS selector
        mark_element = page.query_selector("span.field.field-Mark span.value")
        if mark_element:
            mark = mark_element.inner_text().strip()
            if MARK_RE.match(mark):
                browser.close()
                return {"mark": mark, "method": "playwright_selector"}

        # Προσπάθεια να βρούμε το MARK μέσω αναγνώρισης κειμένου
        labels = page.query_selector_all("span.label")
        for label in labels:
            if "Μ.ΑΡ." in label.inner_text() or "Μ.ΑΡ.Κ" in label.inner_text():
                parent = label.query_selector("..")  # Ανάγνωση του γονέα στοιχείου
                if parent:
                    val_el = parent.query_selector(".value")
                    if val_el:
                        text = val_el.inner_text().strip()
                        if MARK_RE.match(text):
                            browser.close()
                            return {"mark": text, "method": "playwright_label"}

        # Αν δεν βρεθεί τίποτα, επιστρέφουμε None
        browser.close()
        return {"mark": None, "method": "not_found"}

if __name__ == "__main__":
    url = "https://epsilondigital-mcd.epsilonnet.gr/DocViewer/f592d67e-22fa-40aa-8cbe-08ddfae57619"
    print("Scraping:", url)
    res = scrape_epsilon_mark(url)
    print("Result:", res)
