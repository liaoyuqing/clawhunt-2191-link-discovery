"""``discover_links`` - article link discovery for HTML list pages and feeds.

The public entry point is :func:`discover_links`.  It implements the six
capabilities named by the ticket:

1. ``html_list`` mode - source-configured CSS selector first, heuristic
   extraction second, with ``next page`` following (``max_pages`` default 2);
2. ``rss`` mode - RSS 2.0 and Atom 1.0, reading ``link`` / ``title`` /
   ``pubDate`` (RFC 822 or ISO 8601);
3. relative hrefs resolved against the page URL, hosts outside
   ``allowed_hosts`` dropped and counted as ``skipped_host``;
4. canonical URL hashed (SHA-256) and compared against the ``intel_raw_pages``
   ``url_hash`` column, already-crawled links counted as ``skipped_seen``;
5. robots.txt rules applied, disallowed links counted as ``skipped_robots``;
6. attachment links (``.pdf`` and friends, ``Content-Disposition: attachment``,
   ``<a download>``, ``rel=enclosure``) flagged ``is_attachment`` for the
   attachment extractor instead of the article extractor;
7. counters ``discovered / new / skipped_seen / skipped_robots /
   skipped_host`` are returned and persisted as one batch record.

Counter invariant (asserted by the tests): ``discovered == new + skipped_seen``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable, List, Optional, Sequence
from urllib.parse import urlsplit

from .css import SelectorError, select
from .dom import Node, parse_html
from .feed import FeedEntry, FeedError, looks_like_feed, parse_feed
from .store import BatchDraft, BatchRecorder, SeenLink, SeenUrlStore
from .urls import (
    RobotsRules,
    UrlError,
    host_allowed,
    host_of,
    normalize_url,
    resolve_url,
    url_hash,
)

DEFAULT_MAX_PAGES = 2

ATTACHMENT_EXTENSIONS = (
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".csv",
    ".zip", ".rar", ".7z", ".txt",
)

ATTACHMENT_MIME_HINTS = (
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument",
    "application/octet-stream",
)

# --- list-page heuristics -------------------------------------------------

# Containers that are chrome, never article lists.
CHROME_TAGS = frozenset({"nav", "header", "footer", "aside", "form", "menu", "dialog"})
CHROME_TOKENS = frozenset({
    "nav", "navbar", "navigation", "menu", "menubar", "breadcrumb", "breadcrumbs",
    "footer", "header", "sidebar", "side-bar", "aside", "pagination", "pager",
    "pages", "page-nav", "paging", "login", "signin", "sign-in", "register",
    "signup", "social", "share", "sharing", "toolbar", "copyright", "cookie",
    "advert", "advertisement", "ads", "promo", "related-links", "friendlink",
    "sitemap", "search", "searchbox", "tags", "tagcloud", "subscribe",
})

CONTENT_TOKENS = frozenset({
    "list", "article-list", "news-list", "post-list", "entry-list", "content",
    "main", "main-content", "article", "articles", "news", "posts", "entries",
    "feed", "results", "listing", "indices", "index-list", "archives",
})

CONTENT_TAGS = frozenset({"main", "article"})

# Path shapes that look like an article rather than a section index.
_DATE_PATH = re.compile(r"/(?:19|20)\d{2}[/-](?:0[1-9]|1[0-2])(?:[/-](?:0[1-9]|[12]\d|3[01]))?(?:/|[-])")
_DATE_COMPACT = re.compile(r"/(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])/")
_NUMERIC_ID = re.compile(r"(?:^|[-_/])(\d{3,})(?:[-_.]|$)")
_SLUG_WITH_ID = re.compile(r"[a-z0-9][a-z0-9-]{2,}[-_]\d{2,}(?:\.html?|\.shtml|/)?$")
_ARTICLE_EXT = re.compile(r"\.(?:s?html?|shtml|php|aspx?)$", re.IGNORECASE)

# Anchor text that means "this is navigation", never an article.
NAV_TEXT = frozenset({
    "首页", "home", "上一页", "下一页", "prev", "previous", "next", "more",
    "更多", "返回", "back", "登录", "login", "sign in", "signin", "注册",
    "register", "关于我们", "about", "联系我们", "contact", "友情链接",
    "隐私", "privacy", "条款", "terms", "rss", "订阅", "subscribe",
})

NEXT_PAGE_TEXT = frozenset({"下一页", "next", "next page", "nextpage", "后一页", "下页", ">", ">>", "›", "»"})


class DiscoveryError(RuntimeError):
    """Raised when a page cannot be fetched or a source is misconfigured."""


@dataclass
class FetchResult:
    """One fetched page: body text plus the headers discovery cares about."""

    url: str
    text: str
    status: int = 200
    headers: dict = field(default_factory=dict)
    content_type: str = "text/html"

    def header(self, name: str, default: str = "") -> str:
        lowered = {key.lower(): value for key, value in (self.headers or {}).items()}
        return lowered.get(name.lower(), default)


@dataclass
class SourceConfig:
    """A configured intel source (one row of the source registry)."""

    source_id: str
    entry_url: str
    org_id: str = "00000000-0000-0000-0000-000000000000"
    site_id: str = "00000000-0000-0000-0000-000000000000"
    mode: str = "html_list"
    allowed_hosts: Sequence[str] = field(default_factory=tuple)
    list_selector: Optional[str] = None
    content_selector: Optional[str] = None
    next_page_selector: Optional[str] = None
    max_pages: int = DEFAULT_MAX_PAGES
    robots: Optional[RobotsRules] = None
    attachment_extensions: Sequence[str] = ATTACHMENT_EXTENSIONS
    title_from_anchor: bool = True
    created_by: str = "system"

    def hosts(self) -> Sequence[str]:
        return tuple(self.allowed_hosts) or (host_of(self.entry_url),)


@dataclass
class DiscoveredLink:
    """One link in the ``links[]`` result."""

    url: str
    url_hash: str
    title: str
    anchor_text: str
    pub_date: Optional[datetime]
    is_attachment: bool
    found_on: str
    page_index: int
    position: int

    def to_dict(self):
        return {
            "url": self.url,
            "url_hash": self.url_hash,
            "title": self.title,
            "anchor_text": self.anchor_text,
            "pub_date": self.pub_date.isoformat() if self.pub_date else None,
            "is_attachment": self.is_attachment,
            "found_on": self.found_on,
            "page_index": self.page_index,
            "position": self.position,
        }


@dataclass
class DiscoveryResult:
    """The ``links[]`` plus the counters persisted on the batch record."""

    links: List[DiscoveredLink] = field(default_factory=list)
    mode: str = "html_list"
    pages_fetched: int = 0
    raw_candidates: int = 0
    discovered: int = 0
    new: int = 0
    skipped_seen: int = 0
    skipped_robots: int = 0
    skipped_host: int = 0
    skipped_invalid: int = 0
    batch_id: Optional[str] = None

    def __len__(self):
        return len(self.links)

    def counts(self):
        return {
            "mode": self.mode,
            "pages_fetched": self.pages_fetched,
            "raw_candidates": self.raw_candidates,
            "discovered": self.discovered,
            "new": self.new,
            "skipped_seen": self.skipped_seen,
            "skipped_robots": self.skipped_robots,
            "skipped_host": self.skipped_host,
            "skipped_invalid": self.skipped_invalid,
        }

    def to_dict(self):
        payload = self.counts()
        payload["batch_id"] = self.batch_id
        payload["links"] = [link.to_dict() for link in self.links]
        return payload


class Fetcher:
    """Minimal fetch port; swap for the shared crawler/HTTP client in service."""

    def fetch(self, url: str) -> FetchResult:  # pragma: no cover - interface
        raise NotImplementedError


class StaticFetcher(Fetcher):
    """Serves pages from an in-memory mapping - used by fixtures and tests."""

    def __init__(self, pages: dict, missing_status: int = 404):
        self.pages = dict(pages)
        self.missing_status = missing_status
        self.calls: List[str] = []

    def add(self, url: str, text: str, headers: Optional[dict] = None, content_type: str = "text/html"):
        self.pages[url] = FetchResult(url=url, text=text, headers=headers or {}, content_type=content_type)

    def fetch(self, url: str) -> FetchResult:
        self.calls.append(url)
        page = self.pages.get(url)
        if page is None:
            raise DiscoveryError("fixture not found for %s" % url)
        if isinstance(page, FetchResult):
            return page
        return FetchResult(url=url, text=str(page))


def discover_links(
    source: SourceConfig,
    entry_url: Optional[str] = None,
    fetcher: Optional[Fetcher] = None,
    seen_store: Optional[SeenUrlStore] = None,
    recorder: Optional[BatchRecorder] = None,
    pages: Optional[dict] = None,
) -> DiscoveryResult:
    """Discover article links for ``source`` starting at ``entry_url``.

    ``pages`` is a convenience for callers that already hold the HTML/RSS bytes
    (tests, replays): ``{url: html}``; it builds a :class:`StaticFetcher`.
    """
    if fetcher is None:
        if pages is None:
            raise DiscoveryError("either fetcher= or pages= must be supplied")
        fetcher = StaticFetcher(pages)
    entry = normalize_url(entry_url or source.entry_url)
    max_pages = max(1, int(source.max_pages or DEFAULT_MAX_PAGES))

    started = datetime.now(timezone.utc)
    result = DiscoveryResult(mode=source.mode)
    first = fetcher.fetch(entry)
    mode = _resolve_mode(source.mode, first)
    result.mode = mode

    if mode == "rss":
        _discover_from_feed(source, entry, first, result, seen_store)
        result.pages_fetched = 1
    else:
        _discover_from_html(source, entry, fetcher, result, seen_store, max_pages, first)

    result.new = len(result.links)
    if recorder is not None:
        draft = BatchDraft(
            org_id=source.org_id,
            site_id=source.site_id,
            source_id=source.source_id,
            entry_url=entry,
            mode=result.mode,
            pages_fetched=result.pages_fetched,
            raw_candidates=result.raw_candidates,
            discovered=result.discovered,
            new=result.new,
            skipped_seen=result.skipped_seen,
            skipped_robots=result.skipped_robots,
            skipped_host=result.skipped_host,
            skipped_invalid=result.skipped_invalid,
            created_by=source.created_by,
            started_at=started,
            links=[
                SeenLink(
                    url=link.url,
                    url_hash=link.url_hash,
                    title=link.title,
                    pub_date=link.pub_date,
                    anchor_text=link.anchor_text,
                    found_on=link.found_on,
                    page_index=link.page_index,
                    position=link.position,
                    is_attachment=link.is_attachment,
                )
                for link in result.links
            ],
        )
        result.batch_id = recorder.record(draft)
    return result


def _resolve_mode(mode: str, page: FetchResult) -> str:
    declared = (mode or "auto").strip().lower()
    if declared in ("html", "html_list", "list"):
        return "html_list"
    if declared in ("rss", "atom", "feed"):
        return "rss"
    if declared in ("auto", ""):
        ctype = (page.content_type or "").lower()
        if "html" in ctype and not looks_like_feed(page.text):
            return "html_list"
        if "xml" in ctype or "rss" in ctype or "atom" in ctype or looks_like_feed(page.text):
            return "rss"
        return "html_list"
    raise DiscoveryError("unknown source mode: %r" % mode)


# --- RSS / Atom -----------------------------------------------------------


def _discover_from_feed(
    source: SourceConfig,
    entry: str,
    page: FetchResult,
    result: DiscoveryResult,
    seen_store: Optional[SeenUrlStore],
) -> None:
    try:
        entries = parse_feed(page.text)
    except FeedError as exc:
        raise DiscoveryError(str(exc)) from exc
    seen_hashes: set = set()
    if seen_store is not None and hasattr(seen_store, "seen_hashes"):
        candidates = []
        for item in entries:
            if not item.link:
                continue
            try:
                candidates.append(url_hash(resolve_url(entry, item.link)))
            except (UrlError, ValueError):
                continue
        seen_hashes = seen_store.seen_hashes(candidates)
    batch_keys: set = set()
    for position, item in enumerate(entries):
        result.raw_candidates += 1
        _accept(
            source,
            item.link,
            base=entry,
            title=item.title,
            anchor_text=item.title,
            pub_date=item.pub_date,
            is_attachment=item.is_attachment,
            found_on=entry,
            page_index=0,
            position=position,
            result=result,
            seen_store=seen_store,
            seen_hashes=seen_hashes,
            batch_keys=batch_keys,
        )


# --- HTML list pages -----------------------------------------------------


def _discover_from_html(
    source: SourceConfig,
    entry: str,
    fetcher: Fetcher,
    result: DiscoveryResult,
    seen_store: Optional[SeenUrlStore],
    max_pages: int,
    first_page: FetchResult,
) -> None:
    queue: List[str] = [entry]
    visited: set = {entry}
    page_index = 0
    seen_hashes: set = set()
    batch_keys: set = set()
    while queue and page_index < max_pages:
        page_url = queue.pop(0)
        if page_url == entry:
            # The entry page was already fetched to decide the mode.
            page = first_page
        else:
            try:
                page = fetcher.fetch(page_url)
            except DiscoveryError:
                # A missing "next page" just ends the walk; read pages stand.
                break
        result.pages_fetched += 1
        root = parse_html(page.text)
        base = page.url or page_url
        anchors = _article_anchors(source, root)
        if seen_store is not None and hasattr(seen_store, "seen_hashes"):
            hashes = []
            for anchor in anchors:
                try:
                    hashes.append(url_hash(resolve_url(base, anchor.get("href", ""))))
                except (UrlError, ValueError):
                    continue
            seen_hashes = seen_store.seen_hashes(hashes)
        for position, anchor in enumerate(anchors):
            result.raw_candidates += 1
            _accept(
                source,
                anchor.get("href", ""),
                base=base,
                title=anchor.get("title") or anchor.collapsed_text(),
                anchor_text=anchor.collapsed_text(),
                pub_date=None,
                is_attachment=_anchor_is_attachment(anchor, source),
                found_on=base,
                page_index=page_index,
                position=position,
                result=result,
                seen_store=seen_store,
                seen_hashes=seen_hashes,
                batch_keys=batch_keys,
            )
        next_url = _next_page_url(source, root, base)
        if next_url and next_url not in visited and page_index + 1 < max_pages:
            visited.add(next_url)
            queue.append(next_url)
        page_index += 1


def _article_anchors(source: SourceConfig, root: Node) -> List[Node]:
    """Selector first, heuristic second - both verified to match something."""
    if source.list_selector:
        try:
            matched = select(root, source.list_selector)
        except SelectorError as exc:
            raise DiscoveryError("bad list_selector: %s" % exc) from exc
        anchors = [node for node in matched if node.tag == "a"]
        if not anchors:
            anchors = [node for node in matched if node.tag != "a" for node in select(node, "a")]
        if not anchors:
            raise DiscoveryError(
                "list_selector %r matched no links on %s" % (source.list_selector, source.entry_url)
            )
        return anchors
    return _heuristic_anchors(root, source.content_selector)


def _heuristic_anchors(root: Node, content_selector: Optional[str] = None) -> List[Node]:
    region = None
    if content_selector:
        try:
            region = select(root, content_selector)
        except SelectorError as exc:
            raise DiscoveryError("bad content_selector: %s" % exc) from exc
        region = region[0] if region else None
    if region is None:
        region = _content_region(root)
    anchors: List[Node] = []
    for anchor in select(region, "a"):
        href = (anchor.get("href") or "").strip()
        if not href or href.startswith("#") or href.lower().startswith(("javascript:", "mailto:", "tel:")):
            continue
        if _in_chrome(anchor):
            continue
        if _is_nav_anchor(anchor):
            continue
        if not _looks_like_article(anchor):
            continue
        anchors.append(anchor)
    return anchors


def _content_region(root: Node) -> Node:
    """Pick the container holding the most article-shaped anchors.

    Scoring by *article-shaped* anchors (not raw anchors) keeps a single-article
    page usable while refusing to descend into one card of a ten-card list.
    Ties go to the smallest subtree, so <body> never beats the
    <ul class="article-list"> it contains.
    """
    body = None
    for node in root.iter_elements():
        if node.tag == "body":
            body = node
            break
    scope = body or root
    best = None
    best_count = 0
    best_size = None
    for node in [scope] + list(scope.iter_elements()):
        if node.tag in CHROME_TAGS:
            continue
        if _has_token(_tokens(node), CHROME_TOKENS):
            continue
        count = 0
        for anchor in select(node, "a"):
            if _in_chrome(anchor) or _is_nav_anchor(anchor):
                continue
            if _looks_like_article(anchor):
                count += 1
        if count == 0:
            continue
        size = sum(1 for _ in node.iter_elements())
        if count > best_count or (count == best_count and (best_size is None or size < best_size)):
            best, best_count, best_size = node, count, size
    return best if best is not None else scope


def _tokens(node: Node) -> set:
    tokens = set(node.classes())
    identifier = node.get("id")
    if identifier:
        tokens.add(identifier)
    role = node.get("role")
    if role:
        tokens.add(role)
    return tokens


def _has_token(tokens: set, vocabulary: frozenset) -> bool:
    """Match a token set against a vocabulary, splitting on hyphen/underscore.

    "footer-links" therefore matches the "footer" entry, and "article-list"
    matches both "article" and "list".
    """
    for token in tokens:
        lowered = token.lower()
        if lowered in vocabulary:
            return True
        for piece in lowered.replace("_", "-").split("-"):
            if piece and piece in vocabulary:
                return True
    return False


def _in_chrome(anchor: Node) -> bool:
    for ancestor in anchor.ancestors():
        if ancestor.tag in CHROME_TAGS:
            return True
        if _has_token(_tokens(ancestor), CHROME_TOKENS):
            return True
    return False


def _is_nav_anchor(anchor: Node) -> bool:
    text = anchor.collapsed_text().lower().strip()
    if text in NAV_TEXT:
        return True
    attrs = anchor.attrs
    if (attrs.get("rel") or "").lower() in ("nofollow", "external"):
        pass
    if (attrs.get("target") or "") == "_blank" and "new-window" in (attrs.get("class") or ""):
        return True
    return False


def _looks_like_article(anchor: Node) -> bool:
    """Path-shape test: a date or an article number, plus an article-ish path."""
    href = (anchor.get("href") or "").strip()
    if not href:
        return False
    try:
        path = urlsplit(href).path
    except ValueError:
        return False
    if not path or path in ("/", "/index.html"):
        return False
    if _DATE_PATH.search(path) or _DATE_COMPACT.search(path):
        return True
    if _NUMERIC_ID.search(path):
        return True
    if _ARTICLE_EXT.search(path) and _SLUG_WITH_ID.search(path.rsplit("/", 1)[-1]):
        return True
    return False


def _next_page_url(source: SourceConfig, root: Node, base: str) -> Optional[str]:
    candidates: List[Node] = []
    if source.next_page_selector:
        try:
            candidates = [node for node in select(root, source.next_page_selector)]
        except SelectorError as exc:
            raise DiscoveryError("bad next_page_selector: %s" % exc) from exc
    else:
        for anchor in select(root, "a"):
            rel = (anchor.get("rel") or "").lower()
            text = anchor.collapsed_text().strip().lower()
            classes = " ".join(anchor.classes()).lower()
            if rel == "next" or text in NEXT_PAGE_TEXT or "next" in classes.split("-"):
                candidates.append(anchor)
    for node in candidates:
        if node.tag == "a":
            href = (node.get("href") or "").strip()
        else:
            href = (node.get("href") or "").strip()
        if not href or href.startswith("#"):
            continue
        try:
            return normalize_url(resolve_url(base, href))
        except (UrlError, ValueError):
            continue
    return None


# --- shared acceptance pipeline -----------------------------------------


def _accept(
    source: SourceConfig,
    href: str,
    base: str,
    title: str,
    anchor_text: str,
    pub_date: Optional[datetime],
    is_attachment: bool,
    found_on: str,
    page_index: int,
    position: int,
    result: DiscoveryResult,
    seen_store: Optional[SeenUrlStore],
    seen_hashes: set,
    batch_keys: set,
) -> bool:
    try:
        absolute = resolve_url(base, href)
        canonical = normalize_url(absolute)
    except (UrlError, ValueError):
        result.skipped_invalid += 1
        return False

    if not host_allowed(canonical, source.hosts()):
        result.skipped_host += 1
        return False

    if not _robots_allows(source.robots, canonical):
        result.skipped_robots += 1
        return False

    digest = url_hash(canonical)
    if digest in batch_keys:
        return False

    attachment = bool(is_attachment) or _url_is_attachment(canonical, source)
    link = DiscoveredLink(
        url=canonical,
        url_hash=digest,
        title=title.strip() or anchor_text.strip(),
        anchor_text=anchor_text.strip(),
        pub_date=pub_date,
        is_attachment=attachment,
        found_on=found_on,
        page_index=page_index,
        position=position,
    )

    result.discovered += 1
    batch_keys.add(digest)

    seen = digest in seen_hashes
    if not seen and seen_store is not None:
        seen = seen_store.is_seen(digest)
    if seen:
        result.skipped_seen += 1
        return False

    result.links.append(link)
    return True


def _robots_allows(robots: Optional[RobotsRules], url: str) -> bool:
    if robots is None:
        return True
    return robots.allowed(url)


def _anchor_is_attachment(anchor: Node, source: SourceConfig) -> bool:
    if anchor.has_attr("download"):
        return True
    rel = (anchor.get("rel") or "").lower()
    if "enclosure" in rel.split():
        return True
    declared = (anchor.get("type") or "").lower()
    if declared.startswith(ATTACHMENT_MIME_HINTS):
        return True
    return _url_is_attachment(anchor.get("href") or "", source)


def _url_is_attachment(url: str, source: SourceConfig) -> bool:
    try:
        path = urlsplit(url).path.lower()
    except ValueError:
        return False
    extensions = tuple(ext.lower() for ext in (source.attachment_extensions or ()))
    return bool(path) and path.endswith(extensions)


def is_attachment_response(headers: dict) -> bool:
    """True when a response header block marks the body as an attachment."""
    disposition = ""
    for key, value in (headers or {}).items():
        if key.lower() == "content-disposition":
            disposition = str(value).lower()
            break
    return "attachment" in disposition


__all__ = [
    "discover_links",
    "SourceConfig",
    "DiscoveryResult",
    "DiscoveredLink",
    "DiscoveryError",
    "Fetcher",
    "StaticFetcher",
    "FetchResult",
    "is_attachment_response",
    "DEFAULT_MAX_PAGES",
    "ATTACHMENT_EXTENSIONS",
]
