# mydata.py
"""
Lightweight myDATA helper module for Firebed_private.

Provides:
  - request_docs(date_from, date_to, dummy_mark=None, counter_vat=None, throttle=0.2,
                 aade_user: Optional[str]=None, subscription_key: Optional[str]=None)
    -> returns List[dict] parsed from the myDATA RequestDocs response (xml -> python dict).

Configuration (env) still supported for defaults (but not required):
  - AADE_USER_ID, AADE_SUBSCRIPTION_KEY, MYDATA_BASE_URL

Notes:
  - Uses requests and xmltodict. Install: pip install requests xmltodict
  - The AADE myDATA API documentation (v1.0.9) defines RequestDocs and required headers.
    See official doc for details (pagination keys: nextPartitionKey / nextRowKey).
"""
from typing import List, Dict, Any, Optional
import os
import time
import logging

import requests
import xmltodict

logger = logging.getLogger(__name__)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(handler)
logger.setLevel(os.getenv("MYDATA_LOG_LEVEL", "INFO"))

# Module-level defaults (kept for backward compatibility)
AADE_USER = os.getenv("AADE_USER_ID", os.getenv("AADE_USER", ""))
SUBSCRIPTION_KEY = os.getenv("AADE_SUBSCRIPTION_KEY", os.getenv("AADE_SUBSCRIPTION", ""))
MYDATA_BASE = os.getenv("MYDATA_BASE_URL", "https://mydataapidev.aade.gr")  # default dev endpoint

# Default header map (used only when explicit creds not passed)
HEADERS = {
    "aade-user-id": AADE_USER,
    "ocp-apim-subscription-key": SUBSCRIPTION_KEY,
    "Accept": "application/xml",
}


def _safe_get(d: dict, *keys) -> Optional[Any]:
    cur = d
    for k in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur


def request_docs(
    date_from: str,
    date_to: str,
    dummy_mark: Optional[str] = None,
    counter_vat: Optional[str] = None,
    throttle: float = 0.2,
    aade_user: Optional[str] = None,
    subscription_key: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Fetch documents from myDATA RequestDocs for [date_from, date_to].

    Args:
      date_from: 'YYYY-MM-DD'
      date_to:   'YYYY-MM-DD'
      dummy_mark: optional 15-digit mark (e.g. '000000000000000')
      counter_vat: optional counterVatNumber (ΑΦΜ) to filter
      throttle: seconds to sleep between paginated requests
      aade_user: optional per-call aade user id (overrides module default)
      subscription_key: optional per-call subscription key (overrides module default)

    Returns:
      list of parsed document dicts (xmltodict -> python dict).
    Raises:
      RuntimeError on non-200 HTTP or other unrecoverable errors (exception includes response text).
    """
    # Prepare headers for this call (prefer explicit credentials passed to function)
    headers = HEADERS.copy()
    if aade_user:
        headers["aade-user-id"] = aade_user
    if subscription_key:
        headers["ocp-apim-subscription-key"] = subscription_key

    if not headers.get("aade-user-id") or not headers.get("ocp-apim-subscription-key"):
        logger.warning("mydata.request_docs called without AADE credentials; the request will likely fail with 401.")

    # Build URL and params
    url = f"{MYDATA_BASE.rstrip('/')}/RequestDocs"
    params = {"dateFrom": date_from, "dateTo": date_to}
    if dummy_mark:
        params["mark"] = dummy_mark
    if counter_vat:
        params["counterVatNumber"] = counter_vat

    results: List[Dict[str, Any]] = []
    attempt = 0

    while True:
        attempt += 1
        logger.debug("RequestDocs attempt %s, url=%s params=%s", attempt, url, params)
        resp = requests.get(url, headers=headers, params=params, timeout=90)
        if resp.status_code != 200:
            logger.error("RequestDocs HTTP %s: %s", resp.status_code, resp.text[:1000])
            raise RuntimeError(f"RequestDocs HTTP {resp.status_code}: {resp.text[:1000]}")

        parsed = xmltodict.parse(resp.text)

        # Try common known paths where docs may be located (based on myDATA doc)
        docs_candidate = None
        possible_paths = [
            ("RequestDocsResponse", "Docs", "Doc"),
            ("RequestDocsResult", "Docs", "Doc"),
            ("RequestDocsResponse", "Documents", "Document"),
            ("Docs", "Doc"),
            ("Documents", "Document"),
            ("RequestDocsResponse",),
        ]
        for path in possible_paths:
            cur = _safe_get(parsed, *path)
            if cur:
                docs_candidate = cur
                break

        # Shallow search fallback for any key that looks like doc(s)/document(s)
        if docs_candidate is None and isinstance(parsed, dict):
            def find_doc_key(d):
                if isinstance(d, dict):
                    for k, v in d.items():
                        if k.lower() in ("doc", "document", "docs", "documents"):
                            return v
                        if isinstance(v, dict):
                            r = find_doc_key(v)
                            if r:
                                return r
                return None
            docs_candidate = find_doc_key(parsed)

        if docs_candidate is None:
            logger.debug("No docs container found in response (attempt %s). Returning collected %d docs.", attempt, len(results))
            break

        # Normalize to list
        if isinstance(docs_candidate, dict):
            docs_list = [docs_candidate]
        elif isinstance(docs_candidate, list):
            docs_list = docs_candidate
        else:
            docs_list = [docs_candidate]

        results.extend(docs_list)

        # Pagination detection: search for nextPartitionKey / nextRowKey anywhere in parsed
        def find_key(d, keys):
            if not isinstance(d, dict):
                return None
            for k, v in d.items():
                if k in keys:
                    return v
                if isinstance(v, dict):
                    res = find_key(v, keys)
                    if res:
                        return res
            return None

        next_partition = find_key(parsed, ("nextPartitionKey", "NextPartitionKey", "nextPartition", "NextPartition"))
        next_row = find_key(parsed, ("nextRowKey", "NextRowKey", "nextRow", "NextRow"))

        if next_partition and next_row:
            params["nextPartitionKey"] = next_partition
            params["nextRowKey"] = next_row
            logger.debug("Pagination keys found; continuing with nextPartitionKey=%s nextRowKey=%s", next_partition, next_row)
            time.sleep(throttle)
            continue
        else:
            break

    return results


def first_doc_preview(date_from: str, date_to: str, **kwargs) -> Optional[Dict[str, Any]]:
    docs = request_docs(date_from, date_to, **kwargs)
    return docs[0] if docs else None


if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) >= 3:
        df = sys.argv[1]
        dt = sys.argv[2]
    else:
        df = "2025-09-01"
        dt = "2025-09-05"

    try:
        docs = request_docs(df, dt, dummy_mark="000000000000000")
        print(f"Fetched {len(docs)} docs")
        if docs:
            print(json.dumps(docs[0], indent=2, ensure_ascii=False))
    except Exception as e:
        print("Error:", str(e))
