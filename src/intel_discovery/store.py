"""Persistence ports for discovery: seen-URL lookups and batch recording.

Two implementations ship here:

* :class:`SqlSeenUrlStore` / :class:`SqlBatchRecorder` - SQLAlchemy 2 against
  the real schema (PostgreSQL in deployment, SQLite in the tests).
* :class:`MemorySeenUrlStore` / :class:`MemoryBatchRecorder` - dependency-free
  doubles so the module can run with no database at all.

The store contract is deliberately tiny so the raw-page crawler ticket can
substitute its own reader without touching discovery logic.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, Protocol

from sqlalchemy import select

from .models import IntelDiscoveredLink, IntelDiscoveryBatch, IntelRawPage


def _now():
    return datetime.now(timezone.utc)


def _uuid():
    return str(uuid.uuid4())


class SeenUrlStore(Protocol):
    """Read side: has this canonical URL already been crawled?"""

    def is_seen(self, url_hash: str) -> bool:
        ...


class BatchRecorder(Protocol):
    """Write side: persist counters and the new links of one batch."""

    def record(self, batch: "BatchDraft") -> str:
        ...


@dataclass
class SeenLink:
    url: str
    url_hash: str
    title: str = ""
    pub_date: Optional[datetime] = None
    anchor_text: str = ""
    found_on: str = ""
    page_index: int = 0
    position: int = 0
    is_attachment: bool = False


@dataclass
class BatchDraft:
    """Everything the recorder needs; mirrors :class:`IntelDiscoveryBatch`."""

    org_id: str
    site_id: str
    source_id: str
    entry_url: str
    mode: str
    pages_fetched: int = 0
    raw_candidates: int = 0
    discovered: int = 0
    new: int = 0
    skipped_seen: int = 0
    skipped_robots: int = 0
    skipped_host: int = 0
    skipped_invalid: int = 0
    created_by: str = "system"
    links: List[SeenLink] = field(default_factory=list)
    started_at: datetime = field(default_factory=_now)
    finished_at: Optional[datetime] = None


class SqlSeenUrlStore:
    """``intel_raw_pages`` reader used for the url_hash incremental check.

    ``SELECT 1 FROM intel_raw_pages WHERE org_id = :org AND url_hash = :hash
    AND deleted_at IS NULL``, batched through :meth:`seen_hashes` so a page with
    200 links costs one round-trip instead of 200.
    """

    def __init__(self, session, org_id: str):
        self.session = session
        self.org_id = org_id

    def is_seen(self, url_hash: str) -> bool:
        stmt = select(IntelRawPage.id).where(
            IntelRawPage.org_id == self.org_id,
            IntelRawPage.url_hash == url_hash,
            IntelRawPage.deleted_at.is_(None),
        ).limit(1)
        return self.session.execute(stmt).first() is not None

    def seen_hashes(self, hashes: Iterable[str]) -> set:
        wanted = [value for value in hashes if value]
        if not wanted:
            return set()
        found = set()
        # Chunk to stay well inside PostgreSQL's bind-parameter limit.
        for start in range(0, len(wanted), 500):
            chunk = wanted[start:start + 500]
            stmt = select(IntelRawPage.url_hash).where(
                IntelRawPage.org_id == self.org_id,
                IntelRawPage.url_hash.in_(chunk),
                IntelRawPage.deleted_at.is_(None),
            )
            found.update(self.session.execute(stmt).scalars().all())
        return found


class SqlBatchRecorder:
    """Writes :class:`IntelDiscoveryBatch` plus its :class:`IntelDiscoveredLink` rows."""

    def __init__(self, session):
        self.session = session

    def record(self, draft: BatchDraft) -> str:
        batch = IntelDiscoveryBatch(
            id=_uuid(),
            org_id=draft.org_id,
            site_id=draft.site_id,
            source_id=draft.source_id,
            entry_url=draft.entry_url,
            mode=draft.mode,
            created_by=draft.created_by,
            pages_fetched=draft.pages_fetched,
            raw_candidates=draft.raw_candidates,
            discovered=draft.discovered,
            new=draft.new,
            skipped_seen=draft.skipped_seen,
            skipped_robots=draft.skipped_robots,
            skipped_host=draft.skipped_host,
            skipped_invalid=draft.skipped_invalid,
            started_at=draft.started_at,
            finished_at=draft.finished_at or _now(),
        )
        self.session.add(batch)
        for link in draft.links:
            self.session.add(
                IntelDiscoveredLink(
                    id=_uuid(),
                    org_id=draft.org_id,
                    site_id=draft.site_id,
                    created_by=draft.created_by,
                    batch_id=batch.id,
                    source_id=draft.source_id,
                    url=link.url,
                    url_hash=link.url_hash,
                    title=link.title,
                    anchor_text=link.anchor_text,
                    pub_date=link.pub_date,
                    found_on=link.found_on,
                    page_index=link.page_index,
                    position=link.position,
                    is_attachment=link.is_attachment,
                )
            )
        self.session.flush()
        return batch.id


class MemorySeenUrlStore:
    """In-process ``intel_raw_pages`` double (tests and dry runs)."""

    def __init__(self, seen: Optional[Iterable[str]] = None):
        self._seen = set(seen or ())

    def is_seen(self, url_hash: str) -> bool:
        return url_hash in self._seen

    def mark(self, url_hash: str) -> None:
        self._seen.add(url_hash)

    def seen_hashes(self, hashes: Iterable[str]) -> set:
        return {value for value in hashes if value in self._seen}

    def __len__(self):
        return len(self._seen)


class MemoryBatchRecorder:
    """Keeps recorded batches in a list so tests can assert on counters."""

    def __init__(self):
        self.batches: List[BatchDraft] = []

    def record(self, draft: BatchDraft) -> str:
        if draft.finished_at is None:
            draft.finished_at = _now()
        self.batches.append(draft)
        return "memory-batch-%d" % len(self.batches)

    @property
    def last(self) -> Optional[BatchDraft]:
        return self.batches[-1] if self.batches else None


__all__ = [
    "SeenUrlStore",
    "BatchRecorder",
    "SeenLink",
    "BatchDraft",
    "SqlSeenUrlStore",
    "SqlBatchRecorder",
    "MemorySeenUrlStore",
    "MemoryBatchRecorder",
]
