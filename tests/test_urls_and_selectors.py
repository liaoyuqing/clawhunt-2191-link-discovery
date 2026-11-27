"""URL canonicalisation, resolution and selector engine tests."""
from __future__ import annotations

import pytest

from intel_discovery.css import SelectorError, select, select_first
from intel_discovery.dom import parse_html
from intel_discovery.urls import (
    UrlError,
    host_of,
    normalize_url,
    resolve_url,
    url_hash,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("https://Example.COM/a/b", "https://example.com/a/b"),
        ("HTTPS://example.com:443/a", "https://example.com/a"),
        ("http://example.com:80/a", "http://example.com/a"),
        ("https://example.com/a#frag", "https://example.com/a"),
        ("https://example.com/a/./b/../c", "https://example.com/a/c"),
        ("https://example.com", "https://example.com/"),
        ("https://example.com/a?b=2&a=1", "https://example.com/a?a=1&b=2"),
        ("https://example.com/a?utm_source=x&id=7", "https://example.com/a?id=7"),
        ("https://example.com/a?fbclid=abc", "https://example.com/a"),
        ("https://example.com/a b.html", "https://example.com/a%20b.html"),
        ("https://example.com/中文.html", "https://example.com/%E4%B8%AD%E6%96%87.html"),
        ("https://example.com/%e4%b8%ad", "https://example.com/%E4%B8%AD"),
    ],
)
def test_normalize_url(raw, expected):
    assert normalize_url(raw) == expected


def test_default_port_kept_unless_standard():
    """443 on https is the default port, so the canonical form has no port."""
    assert normalize_url("https://example.com:443/a") == "https://example.com/a"
    assert normalize_url("https://example.com:8443/a") == "https://example.com:8443/a"


@pytest.mark.parametrize("bad", ["", "not a url", "ftp://example.com/a", "/relative/path", "mailto:a@b.c"])
def test_normalize_url_rejects(bad):
    with pytest.raises(UrlError):
        normalize_url(bad)


@pytest.mark.parametrize(
    "base,href,expected",
    [
        ("https://example.com/a/b.html", "c.html", "https://example.com/a/c.html"),
        ("https://example.com/a/b.html", "/c.html", "https://example.com/c.html"),
        ("https://example.com/a/b.html", "../c.html", "https://example.com/c.html"),
        ("https://example.com/a/b.html", "//cdn.example.com/c.js", "https://cdn.example.com/c.js"),
        ("http://example.com/a/b.html", "//cdn.example.com/c.js", "http://cdn.example.com/c.js"),
        ("https://example.com/a/b.html", "https://other.example/a", "https://other.example/a"),
    ],
)
def test_resolve_url(base, href, expected):
    assert resolve_url(base, href) == expected


def test_host_of():
    assert host_of("https://WWW.Example.COM/a") == "www.example.com"
    assert host_of("nonsense") == ""


def test_url_hash_is_stable_and_canonical():
    assert url_hash("https://example.com/a") == url_hash("https://EXAMPLE.com/a#x")
    assert len(url_hash("https://example.com/a")) == 64
    assert url_hash("https://example.com/a") != url_hash("https://example.com/b")


def test_default_port_variant_shares_hash():
    assert url_hash("https://example.com:443/a") == url_hash("https://example.com/a")


def test_selector_tag_class_id():
    root = parse_html('<div id="x"><a class="l" href="/1">1</a><a class="l m" href="/2">2</a></div>')
    assert [n.get("href") for n in select(root, "a")] == ["/1", "/2"]
    assert [n.get("href") for n in select(root, "a.l")] == ["/1", "/2"]
    assert [n.get("href") for n in select(root, "a.m")] == ["/2"]
    assert len(select(root, "#x")) == 1
    assert [n.get("href") for n in select(root, "div#x a.l")] == ["/1", "/2"]


def test_selector_descendant_and_child_combinators():
    html = '<div class="a"><p><a href="/1">1</a></p></div><div class="a"><a href="/2">2</a></div>'
    root = parse_html(html)
    assert [n.get("href") for n in select(root, "div.a a")] == ["/1", "/2"]
    assert [n.get("href") for n in select(root, "div.a > a")] == ["/2"]


def test_selector_attribute_operators():
    html = '<a href="/a" rel="next" type="application/pdf" title="t">a</a><a href="/b">b</a>'
    root = parse_html(html)
    assert len(select(root, 'a[rel="next"]')) == 1
    assert len(select(root, 'a[type^="application"]')) == 1
    assert len(select(root, 'a[href$=".pdf"]')) == 0
    assert len(select(root, "a[title]")) == 1
    assert len(select(root, 'a[href*="b"]')) == 1


def test_selector_groups():
    root = parse_html('<h1>t</h1><a href="/1">1</a><p>p</p>')
    assert len(select(root, "h1, p")) == 2


@pytest.mark.parametrize("bad", ["a:hover", "a + b", "a ~ b", "a[", "", "[="])
def test_selector_rejects_unsupported(bad):
    with pytest.raises(SelectorError):
        select(parse_html("<a>a</a>"), bad)


def test_select_first():
    root = parse_html('<a href="/1">1</a><a href="/2">2</a>')
    assert select_first(root, "a").get("href") == "/1"
    assert select_first(root, "img") is None
