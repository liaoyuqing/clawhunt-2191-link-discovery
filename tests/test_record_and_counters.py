"""Requirement item 7: counters returned and written to the batch record."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from intel_discovery.discovery import SourceConfig, discover_links, is_attachment_response
from intel_discovery.models import Base, IntelDiscoveredLink, IntelDiscoveryBatch
from intel_discovery.store import MemoryBatchRecorder, MemorySeenUrlStore, SqlBatchRecorder, SqlSeenUrlStore

from helpers import build_pages, build_source


def _page():
    return """
<html><body><main><ul class="article-list">
<li><a href="/news/2026/03/12/a.html">A</a></li>
<li><a href="/news/2026/03/11/b.html">B</a></li>
<li><a href="https://off.example.net/news/2026/03/10/c.html">C off-site</a></li>
<li><a href="/files/2026/03/09/report.pdf">Report PDF</a></li>
</ul></main></body></html>
"""


def test_returns_all_six_counters():
    source = SourceConfig(
        source_id="src-counters",
        entry_url="https://www.example.com/list.html",
        allowed_hosts=("www.example.com",),
        max_pages=1,
    )
    result = discover_links(source, pages={source.entry_url: _page()})
    counts = result.counts()
    for key in ("discovered", "new", "skipped_seen", "skipped_robots", "skipped_host"):
        assert key in counts
        assert isinstance(counts[key], int)
    # 4 anchors, 1 off-site dropped -> 3 discovered, all 3 new
    assert counts["discovered"] == 3
    assert counts["new"] == 3
    assert counts["skipped_host"] == 1
    assert result.raw_candidates == 4


def test_batch_record_stores_every_counter_and_link():
    recorder = MemoryBatchRecorder()
    source = SourceConfig(
        source_id="src-counters",
        entry_url="https://www.example.com/list.html",
        org_id="aaaaaaaa-0000-0000-0000-000000000001",
        site_id="bbbbbbbb-0000-0000-0000-000000000002",
        allowed_hosts=("www.example.com",),
        max_pages=1,
    )
    result = discover_links(
        source, pages={source.entry_url: _page()}, recorder=recorder
    )
    draft = recorder.last
    assert result.batch_id == "memory-batch-1"
    assert draft.org_id == source.org_id
    assert draft.site_id == source.site_id
    assert (draft.discovered, draft.new, draft.skipped_host) == (3, 3, 1)
    assert len(draft.links) == 3
    assert draft.finished_at is not None
    assert draft.finished_at >= draft.started_at
    assert draft.links[0].url_hash == result.links[0].url_hash


def test_sql_batch_recorder_persists_audit_columns():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    with Session(engine, future=True) as session:
        source = SourceConfig(
            source_id="src-counters",
            entry_url="https://www.example.com/list.html",
            org_id="aaaaaaaa-0000-0000-0000-000000000001",
            site_id="bbbbbbbb-0000-0000-0000-000000000002",
            allowed_hosts=("www.example.com",),
            max_pages=1,
        )
        result = discover_links(
            source,
            pages={source.entry_url: _page()},
            seen_store=SqlSeenUrlStore(session, source.org_id),
            recorder=SqlBatchRecorder(session),
        )
        session.commit()
        batch = session.query(IntelDiscoveryBatch).one()
        assert batch.id == result.batch_id
        assert batch.new == 3
        assert batch.discovered == 3
        assert batch.skipped_host == 1
        assert batch.raw_candidates == 4
        assert batch.org_id == source.org_id
        assert batch.site_id == source.site_id
        assert batch.created_at is not None
        assert batch.created_by == "system"
        assert batch.deleted_at is None
        links = session.query(IntelDiscoveredLink).all()
        assert len(links) == 3
        assert {link.batch_id for link in links} == {batch.id}
        assert all(link.org_id == source.org_id for link in links)
        assert all(link.site_id == source.site_id for link in links)


def test_attachment_flag_persisted():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    with Session(engine, future=True) as session:
        source = SourceConfig(
            source_id="src-counters",
            entry_url="https://www.example.com/list.html",
            allowed_hosts=("www.example.com",),
            max_pages=1,
        )
        discover_links(
            source,
            pages={source.entry_url: _page()},
            recorder=SqlBatchRecorder(session),
        )
        session.commit()
        pdf = session.query(IntelDiscoveredLink).filter_by(is_attachment=True).all()
        assert len(pdf) == 1
        assert pdf[0].url.endswith("report.pdf")


def test_is_attachment_response_reads_content_disposition():
    assert is_attachment_response({"Content-Disposition": "attachment; filename=a.pdf"}) is True
    assert is_attachment_response({"content-disposition": "inline"}) is False
    assert is_attachment_response({}) is False


def test_pdf_url_flagged_even_without_download_attribute():
    source = SourceConfig(
        source_id="src-counters",
        entry_url="https://www.example.com/list.html",
        allowed_hosts=("www.example.com",),
        max_pages=1,
    )
    result = discover_links(source, pages={source.entry_url: _page()})
    pdf = [link for link in result.links if link.is_attachment]
    assert [link.url.rsplit("/", 1)[-1] for link in pdf] == ["report.pdf"]


def test_custom_attachment_extension_list():
    page = """
<html><body><main><ul class="article-list">
<li><a href="/news/2026/03/12/a.html">A</a></li>
<li><a href="/media/2026/03/11/clip.mp4">Clip</a></li>
</ul></main></body></html>
"""
    source = SourceConfig(
        source_id="src-media",
        entry_url="https://www.example.com/list.html",
        allowed_hosts=("www.example.com",),
        max_pages=1,
        attachment_extensions=(".mp4", ".mov"),
    )
    result = discover_links(source, pages={source.entry_url: page})
    flagged = [link.url for link in result.links if link.is_attachment]
    assert flagged == ["https://www.example.com/media/2026/03/11/clip.mp4"]


def test_table_columns_cover_required_audit_fields():
    """Business tables must carry the six platform audit columns."""
    required = {"id", "org_id", "site_id", "created_at", "created_by", "updated_at", "deleted_at"}
    for table in (IntelDiscoveryBatch.__table__, IntelDiscoveredLink.__table__):
        assert required.issubset(set(table.columns.keys()))
