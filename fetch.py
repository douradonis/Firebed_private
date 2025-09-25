# --- debug_fetch_patch.py ---
import os
import time
import logging
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup  # in case need to extract CSRF

logging.basicConfig(level=logging.DEBUG, format="%(asctime)s %(levelname)s %(message)s")

AADE_USER = os.getenv("AADE_USER_ID") or "your_user_here"
AADE_PASS = os.getenv("AADE_PASSWORD") or "your_pass_here"

# URLs - προσαρμόζεις στα αληθινά του repo/mydata.py
BASE_URL = "https://example-api.service"            # π.χ. https://www1.gsis.example
LOGIN_URL = urljoin(BASE_URL, "/login")            # όπου γίνεται το login (GET/POST)
REQUEST_DOCS_URL = urljoin(BASE_URL, "/request_docs")  # το endpoint που δίνει 403

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    # "Referer": BASE_URL,   # προσθέστε αν απαιτείται
    # "X-Requested-With": "XMLHttpRequest",  # δοκιμάστε αν απαιτείται
}

def pretty_req_info(resp):
    req = resp.request
    logging.debug("=== REQUEST SENT ===")
    logging.debug("URL: %s", req.url)
    logging.debug("Method: %s", req.method)
    logging.debug("Request headers: %s", dict(req.headers))
    body = req.body
    if body:
        try:
            logging.debug("Request body (truncated): %s", body[:1000])
        except Exception:
            logging.debug("Request body (binary/non-str).")
    logging.debug("=== RESPONSE ===")
    logging.debug("Status code: %s", resp.status_code)
    logging.debug("Response headers: %s", dict(resp.headers))
    logging.debug("Response text (truncated): %s", resp.text[:2000])

def ensure_logged_in(session: requests.Session):
    """
    Κάνει login αν χρειάζεται και προσπαθεί να τραβήξει CSRF token από την σελίδα login.
    Προσαρμόστε τα ονόματα πεδίων του form αν διαφέρουν.
    """
    logging.info("Ensuring logged in (session cookies). GET login page...")
    r = session.get(LOGIN_URL, headers=DEFAULT_HEADERS, timeout=30)
    logging.debug("Login page status: %s", r.status_code)
    # Αν υπάρχει CSRF token στο login form, το παίρνουμε:
    soup = BeautifulSoup(r.text, "html.parser")
    csrf_token = None
    token_input = soup.find("input", {"name": "csrfmiddlewaretoken"}) or soup.find("input", {"name":"__RequestVerificationToken"})
    if token_input:
        csrf_token = token_input.get("value")
        logging.debug("Found CSRF token in login page.")
    # Προσαρμόστε τα ονόματα username/password του form
    payload = {
        "username": AADE_USER,
        "password": AADE_PASS,
    }
    # Αν βρήκαμε token, το προσθέτουμε
    if csrf_token:
        payload["csrfmiddlewaretoken"] = csrf_token

    # Κάνουμε POST login (αν το endpoint απαιτεί POST)
    logging.info("POSTing login credentials...")
    r2 = session.post(LOGIN_URL, data=payload, headers={**DEFAULT_HEADERS, "Referer": LOGIN_URL}, timeout=30)
    logging.debug("Login POST status: %s", r2.status_code)
    pretty_req_info(r2)
    # Έλεγχος επιτυχίας: προσαρμόστε ανάλογα με το API (redirect, 200 + περιεχόμενο κλπ.)
    if r2.status_code not in (200, 302):
        logging.warning("Login did not return 200/302; continuing but maybe unauthorized.")
    return

def request_docs(session: requests.Session, date_from: str, date_to: str, **kwargs):
    """
    Πραγματοποιεί το request που στο fetch.py έδινε 403.
    Προσαρμόστε payload/param names σύμφωνα με το working mydata.py.
    """
    # παράδειγμα payload - προσαρμόστε
    payload = {
        "date_from": date_from,
        "date_to": date_to,
        # + άλλα required πεδία (partition, mark, doc_type κλπ.)
    }

    headers = {**DEFAULT_HEADERS, "Referer": LOGIN_URL, "Content-Type": "application/json"}
    logging.info("Calling request_docs endpoint: %s", REQUEST_DOCS_URL)
    # Αν το endpoint απαιτεί json:
    resp = session.post(REQUEST_DOCS_URL, json=payload, headers=headers, timeout=60)
    pretty_req_info(resp)

    if resp.status_code == 403:
        logging.error("GOT 403 FORBIDDEN from request_docs. Possible causes: invalid session/csrf/headers/permissions.")
        # dump more info for debugging
        logging.debug("Cookies in session: %s", session.cookies.get_dict())
    return resp

def main():
    s = requests.Session()
    s.headers.update(DEFAULT_HEADERS)
    ensure_logged_in(s)
    # δοκιμαστικό μικρό range
    r = request_docs(s, date_from="2025-09-01", date_to="2025-09-02")
    if r.status_code == 200:
        logging.info("Request docs OK; len=%d", len(r.content))
    else:
        logging.error("Request failed with status=%s", r.status_code)
        # αποθηκεύουμε το response για ανάλυση
        open("debug_request_docs_response.html", "w", encoding="utf-8").write(r.text)

if __name__ == "__main__":
    main()
