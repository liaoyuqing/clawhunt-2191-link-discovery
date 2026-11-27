"""AC1: the 10 fictional list-page fixtures extract exactly their expected links."""
from __future__ import annotations

import pytest

from intel_discovery.discovery import DiscoveryResult

from helpers import build_pages, build_source, run

EXPECTED_IDS = [
    "01_date_path_list",
    "02_numeric_id_list",
    "03_slug_with_id",
    "04_compact_date",
    "05_main_region",
    "06_pagination",
    "07_selector_configured",
    "08_attachment_list",
    "09_heuristic_noise",
    "10_full_site",
]


def _case(html_cases, case_id):
    for case in html_cases:
        if case["id"] == case_id:
            return case
    raise AssertionError("fixture case not found: " + case_id)


def test_manifest_lists_ten_html_fixtures(html_cases):
    assert [case["id"] for case in html_cases] == EXPECTED_IDS
    assert len(html_cases) == 10
    for case in html_cases:
        assert case["expected"], "fixture %s has no expected links" % case["id"]


@pytest.mark.parametrize("case_id", EXPECTED_IDS)
def test_fixture_extracts_expected_links(case_id, html_cases, page_reader):
    case = _case(html_cases, case_id)
    result = run(case, page_reader)
    assert isinstance(result, DiscoveryResult)
    actual = [link.url for link in result.links]
    assert actual == case["expected"]


@pytest.mark.parametrize("case_id", EXPECTED_IDS)
def test_fixture_counters_are_consistent(case_id, html_cases, page_reader):
    case = _case(html_cases, case_id)
    result = run(case, page_reader)
    assert result.discovered == result.new + result.skipped_seen
    assert result.new == len(case["expected"])
    assert result.discovered == result.raw_candidates - result.skipped_host - result.skipped_invalid


def test_noise_fixture_drops_navigation_and_footer(html_cases, page_reader):
    """Fixture 09 hides decoy links inside nav, sidebar and footer."""
    case = _case(html_cases, "09_heuristic_noise")
    result = run(case, page_reader)
    urls = " ".join(link.url for link in result.links)
    assert "menu-item" not in urls
    assert "pinned" not in urls
    assert "top-1" not in urls
    assert "footer-trap" not in urls
    assert len(result.links) == 3


def test_selector_fixture_uses_configured_selector_only(html_cases, page_reader):
    """Fixture 07 hides its list behind opaque classes and id-less slugs, so
    only the configured list_selector can produce these five links."""
    case = _case(html_cases, "07_selector_configured")
    heuristic = run(dict(case, list_selector=None), page_reader)
    configured = run(case, page_reader)
    assert heuristic.links == []
    assert [link.url for link in configured.links] == case["expected"]


def test_attachment_fixture_flags_every_attachment(html_cases, page_reader):
    """Requirement item 6: .pdf paths, download attr, rel=enclosure."""
    case = _case(html_cases, "08_attachment_list")
    result = run(case, page_reader)
    flagged = [link.url for link in result.links if link.is_attachment]
    assert flagged == case["expected_attachments"]
    assert [link.url for link in result.links] == case["expected"]


def test_pagination_follows_next_page_up_to_max_pages(html_cases, page_reader):
    """Requirement item 1: follow the next-page link, default at most 2 pages.

    page-3 is linked from page 2 but must never be requested.
    """
    from intel_discovery.discovery import StaticFetcher, discover_links

    from helpers import build_pages, build_source

    case = _case(html_cases, "06_pagination")
    pages = build_pages(case, page_reader)
    fetcher = StaticFetcher(pages)
    result = discover_links(build_source(case), fetcher=fetcher)
    assert result.pages_fetched == 2
    assert fetcher.calls == [
        "https://brief.example.cn/brief/list/index.html",
        "https://brief.example.cn/brief/list/page-2.html",
    ]
    assert not any("page-3" in url for url in fetcher.calls)


def test_pagination_respects_single_page_setting(html_cases, page_reader):
    case = dict(_case(html_cases, "06_pagination"), max_pages=1)
    pages = build_pages(case, page_reader)
    result = run(case, page_reader, pages=pages)
    assert result.pages_fetched == 1
    assert len(result.links) == 3


def test_full_site_fixture_skips_main_nav_and_sidebar(html_cases, page_reader):
    case = _case(html_cases, "10_full_site")
    result = run(case, page_reader)
    urls = [link.url for link in result.links]
    assert "https://portal.example.cn/news/2026/03/12/hot-topic.html" not in urls
    assert "https://portal.example.cn/news/2026/03/08/footer-note.html" not in urls
    assert urls == case["expected"]
