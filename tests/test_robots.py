"""Requirement item 5: robots.txt disallowed links are skipped and counted."""
from __future__ import annotations

from pathlib import Path

import pytest

from intel_discovery.discovery import SourceConfig, discover_links
from intel_discovery.store import MemoryBatchRecorder, MemorySeenUrlStore
from intel_discovery.urls import parse_robots

PAGE = """
<!DOCTYPE html><html><head><title>robots</title></head><body>
<main><ul class="article-list">
  <li><a href="/news/2026/03/12/open.html">Public article</a></li>
  <li><a href="/news/2026/03/11/open-two.html">Another public article</a></li>
  <li><a href="/admin/2026/03/10/internal.html">Admin article</a></li>
  <li><a href="/user/2026/03/09/profile.html">User area article</a></li>
  <li><a href="/user/public/2026/03/08/shared.html">Allowed user subarea</a></li>
  <li><a href="/private/2026/03/07/secret.html">Blocked for our agent</a></li>
</ul></main></body></html>
"""

ROBOTS_PATH = Path(__file__).resolve().parent.parent / "fixtures/robots/example.html_robots.txt"


def _robots():
    return parse_robots(ROBOTS_PATH.read_text(encoding="utf-8"), agent="intel-link-discovery")


def _source():
    return SourceConfig(
        source_id="src-robots",
        entry_url="https://www.example.com/list/index.html",
        allowed_hosts=("www.example.com",),
        max_pages=1,
        robots=_robots(),
    )


_DEFAULT = object()


def _run(recorder=None, robots=_DEFAULT):
    source = _source()
    if robots is not _DEFAULT:
        source.robots = robots
    return discover_links(
        source,
        pages={source.entry_url: PAGE},
        seen_store=MemorySeenUrlStore(),
        recorder=recorder if recorder is not None else MemoryBatchRecorder(),
    )


def test_disallowed_paths_skipped_and_counted():
    result = _run()
    urls = [link.url for link in result.links]
    assert "https://www.example.com/news/2026/03/12/open.html" in urls
    assert "https://www.example.com/user/public/2026/03/08/shared.html" in urls
    assert all("/admin/" not in url for url in urls)
    assert all("/private/" not in url for url in urls)
    assert "https://www.example.com/user/2026/03/09/profile.html" not in urls
    assert result.skipped_robots == 3


def test_robots_count_persisted_on_batch():
    recorder = MemoryBatchRecorder()
    _run(recorder=recorder)
    assert recorder.last.skipped_robots == 3
    assert recorder.last.discovered == 3


def test_no_robots_configuration_allows_everything():
    result = _run(robots=None)
    # robots=None means "no robots document configured" -> allow
    assert result.skipped_robots == 0
    assert result.new == 6


def test_allow_beats_disallow_on_prefix_tie():
    """Standard resolution: longest match wins, Allow wins an equal-length tie."""
    rules = parse_robots("User-agent: *\nDisallow: /user/\nAllow: /user/public/", agent="bot")
    assert rules.allowed("https://x.test/user/public/a") is True
    assert rules.allowed("https://x.test/user/private/a") is False


def test_agent_specific_group_overrides_star():
    text = (
        "User-agent: *\n"
        "Disallow: /news/\n"
        "\n"
        "User-agent: intel-link-discovery\n"
        "Disallow: /nothing/\n"
    )
    ours = parse_robots(text, agent="intel-link-discovery")
    other = parse_robots(text, agent="someone-else")
    assert ours.allowed("https://x.test/news/2026/03/12/a.html") is True
    assert other.allowed("https://x.test/news/2026/03/12/a.html") is False


@pytest.mark.parametrize(
    "pattern,target,allowed",
    [
        ("/private/", "https://x.test/private/a", False),
        ("/private/", "https://x.test/public/a", True),
        ("/*.pdf$", "https://x.test/files/report.pdf", False),
        ("/*.pdf$", "https://x.test/files/report.pdf.html", True),
        ("/tmp", "https://x.test/tmp/anything", False),
        ("/a$", "https://x.test/a", False),
        ("/a$", "https://x.test/ab", True),
    ],
)
def test_robots_pattern_matrix(pattern, target, allowed):
    rules = parse_robots("User-agent: *\nDisallow: %s\n" % pattern, agent="bot")
    assert rules.allowed(target) is allowed


def test_robots_skip_happens_before_seen_counting():
    """An already-seen AND disallowed link counts only as skipped_robots."""
    from intel_discovery.urls import url_hash

    source = _source()
    blocked = "https://www.example.com/admin/2026/03/10/internal.html"
    seen = MemorySeenUrlStore({url_hash(blocked)})
    result = discover_links(
        source,
        pages={source.entry_url: PAGE},
        seen_store=seen,
    )
    assert result.skipped_robots == 3
    assert result.skipped_seen == 0
