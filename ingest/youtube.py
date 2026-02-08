"""YouTube Data API v3 ingestion – fetch recent uploads per channel."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from ingest.http import fetch
from storage.models import NormalizedItem

log = logging.getLogger(__name__)

_YT_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
_YT_VIDEO_URL = "https://www.youtube.com/watch?v="


def _get_api_key() -> str | None:
    return os.getenv("YOUTUBE_API_KEY")


def _fetch_channel_uploads(
    channel_id: str,
    api_key: str,
    since: datetime,
) -> list[dict[str, Any]]:
    """Return raw search-result items for a channel's recent uploads."""
    params = {
        "part": "snippet",
        "channelId": channel_id,
        "type": "video",
        "order": "date",
        "publishedAfter": since.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "maxResults": 15,
        "key": api_key,
    }
    resp = fetch(_YT_SEARCH_URL, params=params)
    if resp.status_code != 200:
        log.error(
            "YouTube API error for channel %s: HTTP %d – %s",
            channel_id,
            resp.status_code,
            resp.text[:300],
        )
        return []
    data = resp.json()
    return data.get("items", [])


def _yt_item_to_normalized(raw: dict[str, Any], channel_name: str) -> NormalizedItem | None:
    """Convert a YouTube search-result item to a NormalizedItem."""
    snippet = raw.get("snippet", {})
    video_id_info = raw.get("id", {})
    video_id = video_id_info.get("videoId")
    if not video_id:
        return None

    title = snippet.get("title", "").strip()
    description = snippet.get("description", "").strip()
    published = snippet.get("publishedAt", "")

    return NormalizedItem(
        source_type="youtube",
        source_name=channel_name,
        title=title,
        text=description,
        url=f"{_YT_VIDEO_URL}{video_id}",
        published_at=published,
        external_id=video_id,
    )


def ingest_channel(
    channel_id: str,
    channel_name: str,
    api_key: str,
    since: datetime,
) -> list[NormalizedItem]:
    """Fetch recent uploads for a single YouTube channel."""
    items: list[NormalizedItem] = []
    try:
        raw_items = _fetch_channel_uploads(channel_id, api_key, since)
    except Exception:
        log.exception("Error fetching YouTube channel %s", channel_name)
        return items

    for raw in raw_items:
        item = _yt_item_to_normalized(raw, channel_name)
        if item:
            items.append(item)

    log.info("YouTube %s → %d items (since %s)", channel_name, len(items), since.isoformat())
    return items


def ingest_all_channels(
    channels: list[dict[str, str]],
    since: datetime | None = None,
) -> list[NormalizedItem]:
    """Ingest all configured YouTube channels.

    Each element of *channels* is ``{"channel_id": "...", "name": "..."}``.
    If YOUTUBE_API_KEY is not set, this step is silently skipped.
    """
    api_key = _get_api_key()
    if not api_key:
        log.warning("YOUTUBE_API_KEY not set – skipping YouTube ingestion")
        return []

    if since is None:
        since = datetime.now(timezone.utc) - timedelta(hours=24)

    all_items: list[NormalizedItem] = []
    for ch in channels:
        cid = ch["channel_id"]
        name = ch.get("name", cid)
        try:
            items = ingest_channel(cid, name, api_key, since)
            all_items.extend(items)
        except Exception:
            log.exception("Unhandled error for YouTube channel %s – skipping", name)
    return all_items
