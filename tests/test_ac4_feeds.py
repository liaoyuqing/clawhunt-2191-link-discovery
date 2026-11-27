"""AC4: the RSS 2.0 and Atom fixtures parse the right links and timestamps."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from intel_discovery.feed import FeedError, parse_date, parse_feed
from intel_discovery.discovery import discover_links, SourceConfig
from intel_discovery.store import MemoryBatchRecorder, MemorySeenUrlStore

from helpers import build_source


def _feed_case(feed_cases, case_id):
    for case in feed_cases:
        if case["id"] == case_id:
            return case
    raise AssertionError(case_id)


def _run_feed(case, page_reader, seen=None, recorder=None):
    source = SourceConfig(
        source_id="src-" + case["id"],
        entry_url=case["entry_url"],
        mode="rss",
        allowed_hosts=tuple(case["allowed_hosts"]),
    )
    pages = {case["entry_url"]: page_reader(case["path"])}
    return discover_links(
        source,
        pages=pages,
        seen_store=seen if seen is not None else MemorySeenUrlStore(),
        recorder=recorder if recorder is not None else MemoryBatchRecorder(),
    )


@pytest.mark.parametrize("case_id", ["01_rss20", "02_atom"])
def test_feed_links_and_pubdates_match_expected(case_id, feed_cases, page_reader):
    case = _feed_case(feed_cases, case_id)
    result = _run_feed(case, page_reader)
    assert [(link.url, link.title) for link in result.links] == [
        (item["url"], item["title"]) for item in case["expected"]
    ]
    assert [link.pub_date.isoformat() for link in result.links] == [
        item["pub_date"] for item in case["expected"]
    ]


@pytest.mark.parametrize("case_id", ["01_rss20", "02_atom"])
def test_feed_mode_detected_and_offsites_counted(case_id, feed_cases, page_reader):
    case = _feed_case(feed_cases, case_id)
    result = _run_feed(case, page_reader)
    assert result.mode == "rss"
    assert result.pages_fetched == 1
    assert result.skipped_host == case["skipped_host"]
    assert result.discovered == len(case["expected"])
    assert result.new == len(case["expected"])


def test_rss_parse_reads_link_title_pubdate():
    """Direct parser check: RSS 2.0 item order and RFC 822 timestamps."""
    from pathlib import Path

    text = Path(__file__).resolve().parent.parent.joinpath("fixtures/rss/01_rss20.xml").read_text(encoding="utf-8")
    entries = parse_feed(text)
    assert [entry.title for entry in entries][:2] == [
        "会员空间需求侧的三条主线",
        "区域资金流向月报",
    ]
    assert entries[0].pub_date == datetime(2026, 3, 12, 1, 4, tzinfo=timezone.utc)
    assert entries[0].pub_date_raw == "Thu, 12 Mar 2026 09:04:00 +0800"
    # +0800 wall clock 09:04 == 01:04 UTC
    assert entries[0].pub_date.tzinfo == timezone.utc


def test_atom_parse_reads_alternate_link_not_enclosure():
    from pathlib import Path

    text = Path(__file__).resolve().parent.parent.joinpath("fixtures/rss/02_atom.xml").read_text(encoding="utf-8")
    entries = parse_feed(text)
    third = entries[2]
    assert third.link == "https://atom.example.org/posts/2026/03/10/layout.html"
    assert third.title == "联合办公的动线设计"
    assert third.pub_date == datetime(2026, 3, 10, 0, 45, tzinfo=timezone.utc)
    # rel=enclosure is an attachment, never the article URL
    assert third.is_attachment is False
    assert all(not entry.link.endswith(".png") for entry in entries)


def test_rss_relative_link_resolved_against_entry_url(feed_cases, page_reader):
    case = _feed_case(feed_cases, "01_rss20")
    result = _run_feed(case, page_reader)
    assert "https://feed.example.com/brief/2026/03/10/policy.html" in [link.url for link in result.links]


def test_rss_second_run_is_incremental(feed_cases, page_reader):
    case = _feed_case(feed_cases, "01_rss20")
    seen = MemorySeenUrlStore()
    first = _run_feed(case, page_reader, seen=seen)
    for link in first.links:
        seen.mark(link.url_hash)
    second = _run_feed(case, page_reader, seen=seen)
    assert second.new == 0
    assert second.skipped_seen == first.new


def test_rss_attachment_marked_and_pdf_detected(feed_cases, page_reader):
    """Requirement item 6 also applies to feed enclosures."""
    case = _feed_case(feed_cases, "01_rss20")
    result = _run_feed(case, page_reader)
    pdfs = [link for link in result.links if link.is_attachment]
    assert [link.url for link in pdfs] == [
        "https://feed.example.com/brief/2026/03/08/visit-form.pdf"
    ]


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Thu, 12 Mar 2026 09:04:00 +0800", datetime(2026, 3, 12, 1, 4, tzinfo=timezone.utc)),
        ("Tue, 10 Mar 2026 08:00:00 GMT", datetime(2026, 3, 10, 8, 0, tzinfo=timezone.utc)),
        ("2026-03-12T09:00:00+08:00", datetime(2026, 3, 12, 1, 0, tzinfo=timezone.utc)),
        ("2026-03-11T14:20:00Z", datetime(2026, 3, 11, 14, 20, tzinfo=timezone.utc)),
        ("2026-03-12", datetime(2026, 3, 12, 0, 0, tzinfo=timezone.utc)),
    ],
)
def test_parse_date_formats(raw, expected):
    assert parse_date(raw) == expected


@pytest.mark.parametrize("raw", ["", "not a date", "2026-13-45T99:99:99Z"])
def test_parse_date_rejects_garbage(raw):
    assert parse_date(raw) is None


def test_malformed_feed_raises_feed_error():
    with pytest.raises(FeedError):
        parse_feed("<rss><channel><item>")
    with pytest.raises(FeedError):
        parse_feed("")
    with pytest.raises(FeedError):
        parse_feed("<html><body>not a feed</body></html>")


def test_auto_mode_detects_feed_without_viewing_headers(feed_cases, page_reader):
    case = _feed_case(feed_cases, "02_atom")
    source = SourceConfig(
        source_id="src-auto",
        entry_url=case["entry_url"],
        mode="auto",
        allowed_hosts=tuple(case["allowed_hosts"]),
    )
    result = discover_links(source, pages={case["entry_url"]: page_reader(case["path"])})
    assert result.mode == "rss"
    assert len(result.links) == len(case["expected"])
