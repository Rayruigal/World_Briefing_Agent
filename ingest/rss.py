"""RSS feed ingestion – fetch, parse, normalise."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import feedparser
from dateutil import parser as dateutil_parser

from ingest.http import fetch
from storage.models import NormalizedItem

log = logging.getLogger(__name__)


def _parse_published(entry: dict[str, Any]) -> datetime | None:
    """Best-effort parse of an RSS entry's publication date."""
    for key in ("published", "updated", "created"):
        raw = entry.get(key)
        if raw:
            try:
                return dateutil_parser.parse(raw)
            except (ValueError, OverflowError):
                continue
    return None


def _entry_to_item(entry: dict[str, Any], source_name: str) -> NormalizedItem | None:
    """Convert a feedparser entry to a NormalizedItem, or None on failure."""
    pub_dt = _parse_published(entry)
    if pub_dt is None:
        log.debug("Skipping entry without date: %s", entry.get("title", "?"))
        return None

    # Ensure timezone-aware (assume UTC if naive)
    if pub_dt.tzinfo is None:
        pub_dt = pub_dt.replace(tzinfo=timezone.utc)

    link = entry.get("link", "")
    title = entry.get("title", "").strip()
    # Best-effort body: summary → description → empty
    text = (entry.get("summary") or entry.get("description") or "").strip()
    # Strip HTML tags (basic)
    if "<" in text:
        import re
        text = re.sub(r"<[^>]+>", "", text).strip()

    ext_id = entry.get("id", link)

    return NormalizedItem(
        source_type="rss",
        source_name=source_name,
        title=title,
        text=text,
        url=link,
        published_at=pub_dt.isoformat(),
        external_id=str(ext_id),
    )


def ingest_feed(
    feed_url: str,
    source_name: str,
    since: datetime,
) -> list[NormalizedItem]:
    """Fetch and parse a single RSS feed, returning items published after *since*."""
    items: list[NormalizedItem] = []
    try:
        resp = fetch(feed_url)
        if resp.status_code >= 400:
            log.error("Failed to fetch RSS feed %s (HTTP %d)", feed_url, resp.status_code)
            return items
        feed = feedparser.parse(resp.text)
    except Exception:
        log.exception("Error fetching/parsing RSS feed %s", feed_url)
        return items

    since_aware = since if since.tzinfo else since.replace(tzinfo=timezone.utc)

    for entry in feed.entries:
        item = _entry_to_item(entry, source_name)
        if item is None:
            continue
        try:
            pub_dt = dateutil_parser.parse(item.published_at)
            if pub_dt < since_aware:
                continue
        except (ValueError, OverflowError):
            continue
        items.append(item)

    log.info("RSS %s → %d items (since %s)", source_name, len(items), since.isoformat())
    return items


def ingest_all_feeds(
    feeds: list[dict[str, str]],
    since: datetime | None = None,
) -> list[NormalizedItem]:
    """Ingest all configured RSS feeds.  *feeds* is a list of {name, url} dicts."""
    if since is None:
        since = datetime.now(timezone.utc) - timedelta(hours=24)

    all_items: list[NormalizedItem] = []
    for feed_cfg in feeds:
        name = feed_cfg.get("name", feed_cfg["url"])
        url = feed_cfg["url"]
        try:
            items = ingest_feed(url, name, since)
            all_items.extend(items)
        except Exception:
            log.exception("Unhandled error for feed %s – skipping", name)
    return all_items
