"""Deduplication – by URL and by content hash (title + text)."""

from __future__ import annotations

import hashlib
import logging
from typing import Sequence

from storage.models import NormalizedItem

log = logging.getLogger(__name__)


def content_hash(title: str, text: str) -> str:
    """SHA-256 of the normalised concatenation of title and text."""
    blob = (title.strip().lower() + "|" + text.strip().lower()).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def deduplicate(items: Sequence[NormalizedItem]) -> list[NormalizedItem]:
    """Remove duplicates by URL and by content hash.  First occurrence wins."""
    seen_urls: set[str] = set()
    seen_hashes: set[str] = set()
    unique: list[NormalizedItem] = []

    for item in items:
        url_norm = item.url.strip().rstrip("/")
        if url_norm in seen_urls:
            log.debug("Dedup (URL): %s", item.title)
            continue
        ch = content_hash(item.title, item.text)
        if ch in seen_hashes:
            log.debug("Dedup (hash): %s", item.title)
            continue
        seen_urls.add(url_norm)
        seen_hashes.add(ch)
        unique.append(item)

    dropped = len(items) - len(unique)
    if dropped:
        log.info("Deduplication removed %d items (%d → %d)", dropped, len(items), len(unique))
    return unique
