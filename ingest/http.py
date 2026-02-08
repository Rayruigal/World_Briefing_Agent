"""Shared HTTP session with retries, backoff, and rate-limit awareness."""

from __future__ import annotations

import logging
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

log = logging.getLogger(__name__)

# ── Defaults ─────────────────────────────────────────────────────────
_TIMEOUT = 20  # seconds
_MAX_RETRIES = 3
_BACKOFF_FACTOR = 1.0  # 1s, 2s, 4s …
_RETRY_STATUS_CODES = (429, 500, 502, 503, 504)
_MIN_REQUEST_INTERVAL = 0.5  # seconds between requests (basic rate limit)

# ── Module-level session (reusable across the run) ───────────────────
_session: requests.Session | None = None
_last_request_ts: float = 0.0


def get_session() -> requests.Session:
    """Return a requests.Session configured with automatic retries."""
    global _session
    if _session is not None:
        return _session

    _session = requests.Session()
    retry = Retry(
        total=_MAX_RETRIES,
        backoff_factor=_BACKOFF_FACTOR,
        status_forcelist=_RETRY_STATUS_CODES,
        allowed_methods=["GET", "HEAD"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    _session.mount("https://", adapter)
    _session.mount("http://", adapter)
    _session.headers.update(
        {"User-Agent": "world_brief/1.0 (+https://github.com/your-org/world_brief)"}
    )
    return _session


def fetch(url: str, params: dict | None = None, timeout: int = _TIMEOUT) -> requests.Response:
    """GET with rate-limiting pause and structured logging."""
    global _last_request_ts

    # Basic rate limiting
    elapsed = time.monotonic() - _last_request_ts
    if elapsed < _MIN_REQUEST_INTERVAL:
        time.sleep(_MIN_REQUEST_INTERVAL - elapsed)

    sess = get_session()
    log.debug("HTTP GET %s", url)
    resp = sess.get(url, params=params, timeout=timeout)
    _last_request_ts = time.monotonic()

    if resp.status_code >= 400:
        log.warning("HTTP %d for %s", resp.status_code, url)

    return resp
