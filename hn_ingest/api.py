"""HN Algolia API client with rate limiting and retry logic."""

import time

import httpx

_BASE = "https://hn.algolia.com/api/v1"
_DELAY = 1.0      # minimum seconds between requests
_RETRIES = 3
_client = httpx.Client(timeout=30.0)


def _get(url: str, params: dict | None = None) -> dict:
    """GET with per-request delay and exponential backoff on 429/5xx/timeout."""
    backoff = 2.0
    for attempt in range(_RETRIES):
        time.sleep(_DELAY)
        try:
            resp = _client.get(url, params=params)
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt < _RETRIES - 1:
                    print(f"  HTTP {resp.status_code}, retrying in {backoff:.0f}s…")
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                resp.raise_for_status()
            resp.raise_for_status()
            return resp.json()
        except httpx.TimeoutException:
            if attempt < _RETRIES - 1:
                print(f"  Timeout, retrying in {backoff:.0f}s…")
                time.sleep(backoff)
                backoff *= 2
                continue
            raise
    raise RuntimeError(f"All {_RETRIES} attempts failed for {url}")


def fetch_whoishiring_threads() -> list[dict]:
    """Return all stories posted by user 'whoishiring', across all pages."""
    results: list[dict] = []
    page = 0
    while True:
        data = _get(
            f"{_BASE}/search_by_date",
            params={"tags": "story,author_whoishiring", "hitsPerPage": 100, "page": page},
        )
        hits: list[dict] = data.get("hits", [])
        results.extend(hits)
        nb_pages: int = data.get("nbPages", 1)
        print(f"  Page {page + 1}/{nb_pages}: {len(hits)} threads (running total: {len(results)})")
        if page >= nb_pages - 1:
            break
        page += 1
    return results


def fetch_thread_items(thread_id: int) -> dict:
    """Return the full item tree for a thread (story + nested comments)."""
    return _get(f"{_BASE}/items/{thread_id}")
