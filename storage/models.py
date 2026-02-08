"""SQLAlchemy models and shared data classes for world_brief."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase


# ── ORM base ────────────────────────────────────────────────────────
class Base(DeclarativeBase):
    pass


class ItemRow(Base):
    """Persisted news item (one row per unique item)."""

    __tablename__ = "items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    external_id = Column(String(512), nullable=False)
    source_type = Column(String(32), nullable=False)  # "rss" | "youtube"
    source_name = Column(String(256), nullable=False)
    title = Column(Text, nullable=False)
    text = Column(Text, nullable=False, default="")
    url = Column(String(2048), nullable=False)
    published_at = Column(DateTime, nullable=False)
    content_hash = Column(String(64), nullable=False)
    category = Column(String(128), nullable=True)
    confidence = Column(Float, nullable=True)
    tags = Column(Text, nullable=True)  # JSON-encoded list
    ingested_at = Column(DateTime, nullable=False, default=dt.datetime.utcnow)
    run_date = Column(String(10), nullable=False)  # "YYYY-MM-DD"

    __table_args__ = (
        UniqueConstraint("url", name="uq_items_url"),
        UniqueConstraint("content_hash", name="uq_items_content_hash"),
    )

    def __repr__(self) -> str:
        return f"<ItemRow id={self.id} title={self.title!r:.40}>"


# ── Plain data class used throughout the pipeline ────────────────────
@dataclass
class NormalizedItem:
    source_type: str  # "rss" | "youtube"
    source_name: str
    title: str
    text: str
    url: str
    published_at: str  # ISO-8601 string
    external_id: str

    # Populated after classification
    category: Optional[str] = None
    confidence: Optional[float] = None
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "source_type": self.source_type,
            "source_name": self.source_name,
            "title": self.title,
            "text": self.text,
            "url": self.url,
            "published_at": self.published_at,
            "external_id": self.external_id,
            "category": self.category,
            "confidence": self.confidence,
            "tags": self.tags,
        }
