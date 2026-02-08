"""Database helpers – SQLite for MVP, easy swap to Postgres."""

from __future__ import annotations

import json
import logging
import os
from contextlib import contextmanager
from datetime import datetime
from typing import Generator, Sequence

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from storage.models import Base, ItemRow, NormalizedItem

log = logging.getLogger(__name__)

# ── Engine / session factory ─────────────────────────────────────────

_engine = None
_SessionFactory: sessionmaker[Session] | None = None


def _get_database_url() -> str:
    """Return the DB URL.  Postgres swap: set DATABASE_URL env var."""
    url = os.getenv("DATABASE_URL")
    if url:
        return url
    db_path = os.getenv("SQLITE_PATH", "world_brief.db")
    return f"sqlite:///{db_path}"


def init_db() -> None:
    """Create engine, session factory, and tables (idempotent)."""
    global _engine, _SessionFactory
    url = _get_database_url()
    connect_args = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    _engine = create_engine(url, echo=False, connect_args=connect_args)
    _SessionFactory = sessionmaker(bind=_engine)
    Base.metadata.create_all(_engine)
    log.info("Database initialised (%s)", url.split("///")[0] + "///…")


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """Provide a transactional session scope."""
    if _SessionFactory is None:
        raise RuntimeError("Call init_db() first")
    session = _SessionFactory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# ── Persistence helpers ──────────────────────────────────────────────


def save_items(items: Sequence[NormalizedItem], run_date: str) -> int:
    """Insert items, skipping duplicates (URL or content_hash).  Returns count saved."""
    from process.dedupe import content_hash  # local import to avoid circular

    saved = 0
    with get_session() as session:
        for item in items:
            ch = content_hash(item.title, item.text)
            existing = (
                session.query(ItemRow)
                .filter((ItemRow.url == item.url) | (ItemRow.content_hash == ch))
                .first()
            )
            if existing:
                log.debug("Skipping duplicate in DB: %s", item.url)
                continue
            row = ItemRow(
                external_id=item.external_id,
                source_type=item.source_type,
                source_name=item.source_name,
                title=item.title,
                text=item.text,
                url=item.url,
                published_at=datetime.fromisoformat(item.published_at),
                content_hash=ch,
                category=item.category,
                confidence=item.confidence,
                tags=json.dumps(item.tags) if item.tags else "[]",
                run_date=run_date,
            )
            session.add(row)
            saved += 1
    log.info("Saved %d new items to DB (run_date=%s)", saved, run_date)
    return saved


def update_classification(
    url: str, category: str, confidence: float, tags: list[str]
) -> None:
    """Update classification fields for an already-persisted item."""
    with get_session() as session:
        row = session.query(ItemRow).filter(ItemRow.url == url).first()
        if row:
            row.category = category
            row.confidence = confidence
            row.tags = json.dumps(tags)
