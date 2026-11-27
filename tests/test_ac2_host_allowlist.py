"""AC2: links on hosts outside allowed_hosts are dropped and counted."""
from __future__ import annotations

import pytest

from intel_discovery.discovery import SourceConfig, discover_links
from intel_discovery.store import MemoryBatchRecorder, MemorySeenUrlStore
from intel_discovery.urls import host_allowed

from helpers import build_source

PAGE = """
<!DOCTYPE html>
<html><head><title>host filter</title></head><body>
<main><h1>List</h1>
<ul class="article-list">
  <li><a href="/news/2026/03/12/on-site.html">On site</a></li>
  <li><a href="https://mirror.example.net/news/2026/03/11/mirror.html">Mirror</a></li>
  <li><a href="https://partner.example.org/news/2026/03/10/partner.html">Partner</a></li>
  <li><a href="https://sub.example.com/news/2026/03/09/sub.html">Sub domain on the allow-list</a></li>
  <li><a href="//cdn.example.com/news/2026/03/08/cdn.html">Protocol relative on the allow-list</a></li>
  <li><a href="https://evil.example.com.attacker.net/news/2026/03/07/lookalike.html">Lookalike host</a></li>
</ul></main></body></html>
"""


def _source(**overrides):
    base = dict(
        source_id="src-host",
        entry_url="https://www.example.com/list/index.html",
        allowed_hosts=("www.example.com", "cdn.example.com", "sub.example.com"),
        max_pages=1,
    )
    base.update(overrides)
    return SourceConfig(**base)


def _run(source, seen=None, recorder=None):
    pages = {source.entry_url: PAGE}
    return discover_links(
        source,
        pages=pages,
        seen_store=seen if seen is not None else MemorySeenUrlStore(),
        recorder=recorder if recorder is not None else MemoryBatchRecorder(),
    )


def test_offsite_hosts_dropped_and_counted():
    result = _run(_source())
    hosts = {link.url.split("/")[2] for link in result.links}
    assert hosts == {"www.example.com", "cdn.example.com", "sub.example.com"}
    assert result.skipped_host == 3
    assert result.discovered == 3
    assert result.new == 3


def test_no_offsite_url_leaks_into_links():
    result = _run(_source())
    urls = [link.url for link in result.links]
    assert "https://mirror.example.net/news/2026/03/11/mirror.html" not in urls
    assert "https://partner.example.org/news/2026/03/10/partner.html" not in urls
    assert all("attacker.net" not in url for url in urls)


def test_skipped_host_count_persisted_on_batch_record():
    recorder = MemoryBatchRecorder()
    _run(_source(), recorder=recorder)
    draft = recorder.last
    assert draft is not None
    assert draft.skipped_host == 3
    assert draft.discovered == 3
    assert draft.new == 3
    assert draft.new == len(draft.links)


def test_empty_allow_list_denies_everything():
    """An unconfigured allow-list must not turn into "crawl the whole web"."""
    result = _run(_source(allowed_hosts=()))
    # Empty allowed_hosts falls back to the entry URL host, never to "*".
    assert {link.url.split("/")[2] for link in result.links} == {"www.example.com"}
    assert result.skipped_host == 5


def test_wildcard_allow_list_matches_subdomains():
    result = _run(_source(allowed_hosts=("*.example.com",)))
    hosts = {link.url.split("/")[2] for link in result.links}
    assert hosts == {"www.example.com", "cdn.example.com", "sub.example.com"}
    assert result.skipped_host == 3


@pytest.mark.parametrize(
    "url,allowed,expected",
    [
        ("https://www.example.com/a", ["www.example.com"], True),
        ("https://www.example.com/a", ["WWW.Example.COM"], True),
        ("https://www.example.com/a", ["example.com"], False),
        ("https://sub.example.com/a", ["*.example.com"], True),
        ("https://example.com/a", ["*.example.com"], True),
        ("https://notexample.com/a", ["*.example.com"], False),
        ("https://www.example.com/a", [], False),
        ("https://www.example.com/a", ["other.example.com"], False),
    ],
)
def test_host_allowed_matrix(url, allowed, expected):
    assert host_allowed(url, allowed) is expected


def test_host_case_and_trailing_dot_normalised():
    result = _run(_source(allowed_hosts=("WWW.EXAMPLE.COM",)))
    assert {link.url.split("/")[2] for link in result.links} == {"www.example.com"}
