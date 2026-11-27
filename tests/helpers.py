"""Helpers shared by the test modules."""
from __future__ import annotations

from intel_discovery.discovery import SourceConfig, discover_links
from intel_discovery.store import MemoryBatchRecorder, MemorySeenUrlStore


def build_source(case: dict, robots=None) -> SourceConfig:
    return SourceConfig(
        source_id="src-" + case["id"],
        entry_url=case["entry_url"],
        org_id="11111111-1111-1111-1111-111111111111",
        site_id="22222222-2222-2222-2222-222222222222",
        mode=case.get("mode", "html_list"),
        allowed_hosts=tuple(case["allowed_hosts"]),
        list_selector=case.get("list_selector"),
        content_selector=case.get("content_selector"),
        next_page_selector=case.get("next_page_selector"),
        max_pages=case.get("max_pages", 2),
        robots=robots,
    )


def build_pages(case: dict, load) -> dict:
    """Map each fixture document onto the URL discovery will request it by."""
    urls = case.get("page_urls") or [case["entry_url"]]
    pages = {}
    for relpath, url in zip(case["pages"], urls):
        pages[url] = load(relpath)
    return pages


def run(case: dict, load, seen_store=None, recorder=None, robots=None, pages=None):
    source = build_source(case, robots=robots)
    if pages is None:
        pages = build_pages(case, load)
    seen = seen_store if seen_store is not None else MemorySeenUrlStore()
    rec = recorder if recorder is not None else MemoryBatchRecorder()
    return discover_links(source, pages=pages, seen_store=seen, recorder=rec)
