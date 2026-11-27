"""AC3: a second run over the same fixture yields new == 0."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from intel_discovery.discovery import SourceConfig, discover_links
from intel_discovery.models import Base, IntelDiscoveredLink, IntelDiscoveryBatch
from intel_discovery.store import (
    MemoryBatchRecorder,
    MemorySeenUrlStore,
    SqlBatchRecorder,
    SqlSeenUrlStore,
)
from intel_discovery.urls import url_hash

from helpers import build_pages, build_source

CASES = ["01_date_path_list", "05_main_region", "09_heuristic_noise"]


def _case(html_cases, case_id):
    for case in html_cases:
        if case["id"] == case_id:
            return case
    raise AssertionError(case_id)


@pytest.mark.parametrize("case_id", CASES)
def test_second_run_reports_zero_new(case_id, html_cases, page_reader):
    case = _case(html_cases, case_id)
    pages = build_pages(case, page_reader)
    seen = MemorySeenUrlStore()
    first = discover_links(build_source(case), pages=pages, seen_store=seen)
    assert first.new > 0
    for link in first.links:
        seen.mark(link.url_hash)
    second = discover_links(build_source(case), pages=pages, seen_store=seen)
    assert second.new == 0
    assert second.links == []
    assert second.skipped_seen == first.new
    assert second.discovered == first.discovered


def test_second_run_keeps_counters_additive(html_cases, page_reader):
    case = _case(html_cases, "01_date_path_list")
    pages = build_pages(case, page_reader)
    seen = MemorySeenUrlStore()
    recorder = MemoryBatchRecorder()
    first = discover_links(build_source(case), pages=pages, seen_store=seen, recorder=recorder)
    for link in first.links:
        seen.mark(link.url_hash)
    second = discover_links(build_source(case), pages=pages, seen_store=seen, recorder=recorder)
    assert recorder.batches[0].new == first.new
    assert recorder.batches[1].new == 0
    assert recorder.batches[1].skipped_seen == first.new
    assert second.new == 0


def test_url_variants_collapse_to_one_hash():
    """Canonicalisation must fold tracking params, case and default ports."""
    base = "https://www.example.com/news/2026/03/12/negotiation-playbook.html"
    variants = [
        base,
        base + "?utm_source=rss&utm_medium=feed",
        base + "#comments",
        "HTTPS://WWW.EXAMPLE.COM/news/2026/03/12/negotiation-playbook.html",
        "https://www.example.com:443/news/2026/03/12/negotiation-playbook.html",
        "https://www.example.com/news/2026/03/05/../12/negotiation-playbook.html",
    ]
    hashes = {url_hash(url) for url in variants}
    assert len(hashes) == 1


@pytest.mark.parametrize("case_id", CASES)
def test_sql_seen_store_makes_second_run_zero(case_id, html_cases, page_reader):
    """The real intel_raw_pages path: SQLAlchemy + SQLite, url_hash lookup."""
    case = _case(html_cases, case_id)
    pages = build_pages(case, page_reader)
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    with Session(engine, future=True) as session:
        seen = SqlSeenUrlStore(session, org_id="11111111-1111-1111-1111-111111111111")
        recorder = SqlBatchRecorder(session)
        source = build_source(case)
        first = discover_links(source, pages=pages, seen_store=seen, recorder=recorder)
        assert first.new > 0
        session.commit()
        # The crawler ticket owns IntelRawPage inserts; discovery only reads it.
        from intel_discovery.models import IntelRawPage

        for link in first.links:
            session.add(
                IntelRawPage(
                    org_id=source.org_id,
                    site_id=source.site_id,
                    source_id=source.source_id,
                    url=link.url,
                    url_hash=link.url_hash,
                    is_attachment=link.is_attachment,
                )
            )
        session.commit()
        second = discover_links(source, pages=pages, seen_store=seen, recorder=recorder)
        session.commit()
        assert second.new == 0
        assert second.skipped_seen == first.new
        batches = session.query(IntelDiscoveryBatch).all()
        assert len(batches) == 2
        assert batches[1].new == 0
        assert batches[1].skipped_seen == first.new
        stored = session.query(IntelDiscoveredLink).count()
        assert stored == first.new


def test_sql_soft_deleted_pages_are_not_seen(html_cases, page_reader):
    """A soft-deleted raw page must be re-discovered (deleted_at IS NULL)."""
    from datetime import datetime, timezone

    from intel_discovery.models import IntelRawPage

    case = _case(html_cases, "01_date_path_list")
    pages = build_pages(case, page_reader)
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    source = build_source(case)
    with Session(engine, future=True) as session:
        seen = SqlSeenUrlStore(session, org_id=source.org_id)
        first = discover_links(source, pages=pages, seen_store=seen)
        for link in first.links:
            session.add(
                IntelRawPage(
                    org_id=source.org_id,
                    site_id=source.site_id,
                    source_id=source.source_id,
                    url=link.url,
                    url_hash=link.url_hash,
                    deleted_at=datetime.now(timezone.utc),
                )
            )
        session.commit()
        second = discover_links(source, pages=pages, seen_store=seen)
        assert second.new == first.new


def test_seen_check_happens_after_host_and_robots_filters(html_cases, page_reader):
    """Counters must not double-count: an off-site link never reaches seen."""
    case = _case(html_cases, "01_date_path_list")
    pages = build_pages(case, page_reader)
    source = build_source(case)
    first = discover_links(source, pages=pages, seen_store=MemorySeenUrlStore())
    all_hashes = {link.url_hash for link in first.links}
    seen = MemorySeenUrlStore(all_hashes)
    second = discover_links(source, pages=pages, seen_store=seen)
    assert second.new == 0
    assert second.skipped_seen == len(all_hashes)
    assert second.skipped_host == first.skipped_host
