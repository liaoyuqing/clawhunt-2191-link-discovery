"""SQLAlchemy 2 models for the link-discovery slice of the intel pipeline.

The two tables here are the contract with neighbouring tickets:

* :class:`IntelRawPage` is the ``intel_raw_pages`` table owned by the raw-page
  crawler ticket.  Discovery only *reads* it (``url_hash`` lookups); the
  crawler inserts rows into it.
* :class:`IntelDiscoveryBatch` / :class:`IntelDiscoveredLink` are written by
  discovery: one batch row per ``discover_links`` call plus one row per new
  link, which is what the downstream extractor consumes.

Every business table carries the platform-wide audit columns
``id, org_id, site_id, created_at, created_by, updated_at, deleted_at``.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _uuid() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class AuditMixin:
    """The six audit columns every business table must carry."""

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    site_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    created_by: Mapped[str] = mapped_column(String(64), nullable=False, default="system")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class IntelRawPage(AuditMixin, Base):
    """``intel_raw_pages`` - raw pages already fetched for a source.

    Owned by the raw-page crawler ticket.  ``url_hash`` is the SHA-256 of the
    canonical URL (see :func:`intel_discovery.urls.url_hash`) and is the only
    column discovery reads, through :class:`~intel_discovery.store.SqlSeenUrlStore`.
    """

    __tablename__ = "intel_raw_pages"
    __table_args__ = (
        UniqueConstraint("org_id", "url_hash", name="uq_intel_raw_pages_org_url_hash"),
        Index("ix_intel_raw_pages_org_site", "org_id", "site_id"),
    )

    source_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    url_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    final_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_attachment: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class IntelDiscoveryBatch(AuditMixin, Base):
    """One ``discover_links`` run and its counters (requirement item 7)."""

    __tablename__ = "intel_discovery_batches"

    source_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    entry_url: Mapped[str] = mapped_column(Text, nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False, default="html_list")
    pages_fetched: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    raw_candidates: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    discovered: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    new: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_seen: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_robots: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_host: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_invalid: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    links: Mapped[list["IntelDiscoveredLink"]] = relationship(
        back_populates="batch", cascade="all, delete-orphan", lazy="selectin"
    )


class IntelDiscoveredLink(AuditMixin, Base):
    """A single new link produced by a batch, handed to the extractor."""

    __tablename__ = "intel_discovered_links"
    __table_args__ = (
        UniqueConstraint("batch_id", "url_hash", name="uq_intel_discovered_links_batch_url_hash"),
        Index("ix_intel_discovered_links_org_url_hash", "org_id", "url_hash"),
    )

    batch_id: Mapped[str] = mapped_column(String(36), ForeignKey("intel_discovery_batches.id"), nullable=False)
    source_id: Mapped[str] = mapped_column(String(36), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    url_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False, default="")
    anchor_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    pub_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    found_on: Mapped[str] = mapped_column(Text, nullable=False, default="")
    page_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_attachment: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    batch: Mapped[IntelDiscoveryBatch] = relationship(back_populates="links")


__all__ = [
    "Base",
    "AuditMixin",
    "IntelRawPage",
    "IntelDiscoveryBatch",
    "IntelDiscoveredLink",
    "utcnow",
]
