"""RSS 2.0 / RSS 1.0 / Atom 1.0 feed parsing (stdlib only).

The parser is namespace tolerant because real feeds in the wild mix RDF,
Atom and Dublin Core.  It returns plain ``FeedEntry`` records carrying the raw
strings plus a parsed ``datetime`` (UTC, timezone aware) when the published or
updated timestamp is machine readable.
"""
from __future__ import annotations

import email.utils
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

ATOM_NS = "http://www.w3.org/2005/Atom"
RSS1_NS = "http://purl.org/rss/1.0/"
DC_NS = "http://purl.org/dc/elements/1.1/"
CONTENT_NS = "http://purl.org/rss/1.0/modules/content/"

_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})"
    r"(?:[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d+))?)?)?"
    r"(Z|[+-]\d{2}:?\d{2})?$"
)


class FeedError(ValueError):
    """Raised when the document is not a feed we can parse."""


@dataclass
class FeedEntry:
    """One feed item with its link, title and timestamps."""

    link: str
    title: str = ""
    pub_date: Optional[datetime] = None
    pub_date_raw: str = ""
    updated: Optional[datetime] = None
    entry_id: str = ""
    is_attachment: bool = False
    extra: dict = field(default_factory=dict)

    def to_dict(self):
        return {
            "link": self.link,
            "title": self.title,
            "pub_date": self.pub_date.isoformat() if self.pub_date else None,
            "pub_date_raw": self.pub_date_raw,
            "updated": self.updated.isoformat() if self.updated else None,
            "entry_id": self.entry_id,
            "is_attachment": self.is_attachment,
        }


def parse_date(value: str) -> Optional[datetime]:
    """Parse RFC 822 / RFC 1123 or ISO 8601 into an aware UTC datetime."""
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    parsed = _parse_iso(text)
    if parsed is None:
        parsed = _parse_rfc822(text)
    return parsed


def _parse_iso(text: str) -> Optional[datetime]:
    match = _ISO_RE.match(text)
    if not match:
        return None
    year, month, day, hour, minute, second, fraction, tz = match.groups()
    try:
        micro = int((fraction or "0").ljust(6, "0")[:6])
        dt = datetime(
            int(year), int(month), int(day),
            int(hour or 0), int(minute or 0), int(second or 0), micro,
            tzinfo=timezone.utc,
        )
    except ValueError:
        return None
    if tz and tz not in ("Z", "z"):
        sign = 1 if tz[0] == "+" else -1
        body = tz[1:].replace(":", "")
        offset = sign * (int(body[:2]) * 60 + int(body[2:4]))
        dt = dt.replace(tzinfo=timezone.utc) - _minutes(offset)
    return dt


def _minutes(count: int) -> "timedelta":
    from datetime import timedelta

    return timedelta(minutes=count)


def _parse_rfc822(text: str) -> Optional[datetime]:
    try:
        dt = email.utils.parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError):
        return None
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _strip_ns(tag: str) -> str:
    if "}" in tag:
        ns, local = tag.split("}", 1)
        return local.lower()
    return tag.lower()


def _ns_of(tag: str) -> str:
    if tag.startswith("{"):
        return tag[1:].split("}", 1)[0]
    return ""


def _text(node) -> str:
    if node is None:
        return ""
    return (node.text or "").strip()


def _find(node, names) -> Optional[object]:
    for child in node:
        if _strip_ns(child.tag) in names:
            return child
    return None


def _find_all(node, names) -> List[object]:
    return [child for child in node if _strip_ns(child.tag) in names]


def _pick_link(node):
    """Return (href, came_from_enclosure) for one feed entry.

    Atom: prefer rel="alternate" (or a link without rel); fall back to an
    enclosure only when the entry carries no article link.  RSS: the <link>
    element text, falling back to <enclosure url=...>.
    """
    candidates = [child for child in node if _strip_ns(child.tag) == "link"]
    best = ""
    for child in candidates:
        href = (child.get("href") or "").strip()
        rel = (child.get("rel") or "alternate").strip().lower()
        if not href:
            text = _text(child)
            if text and not best:
                best = text
            continue
        if rel == "alternate":
            return href, False
        if not best and rel not in ("enclosure", "self", "replies"):
            best = href
    if best:
        return best, False
    for child in candidates:
        href = (child.get("href") or "").strip()
        if href:
            return href, (child.get("rel") or "").strip().lower() == "enclosure"
    enclosure = _enclosure_link(node)
    if enclosure:
        return enclosure, True
    return "", False


def _enclosure_link(node) -> str:
    for child in node:
        if _strip_ns(child.tag) == "enclosure":
            url = (child.get("url") or "").strip()
            if url:
                return url
    return ""


def parse_feed(text: str) -> List[FeedEntry]:
    """Parse an RSS 2.0 / RSS 1.0 / Atom 1.0 document into ``FeedEntry`` list."""
    if not text or not text.strip():
        raise FeedError("empty feed document")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise FeedError("malformed feed XML: %s" % exc) from exc

    local = _strip_ns(root.tag)
    if local == "feed":
        return _parse_atom(root)
    if local in ("rss", "rdf"):
        return _parse_rss(root)
    channel = _find(root, {"channel"})
    if channel is not None:
        return _parse_rss(root)
    raise FeedError("unrecognised feed root element: %s" % root.tag)


def _parse_atom(root) -> List[FeedEntry]:
    entries: List[FeedEntry] = []
    for node in _find_all(root, {"entry"}):
        link, from_enclosure = _pick_link(node)
        published = _find(node, {"published"})
        updated = _find(node, {"updated"})
        raw_pub = _text(published) or _text(updated)
        entry_id = _text(_find(node, {"id"}))
        entries.append(
            FeedEntry(
                link=link,
                title=_text(_find(node, {"title"})),
                pub_date=parse_date(raw_pub),
                pub_date_raw=raw_pub,
                updated=parse_date(_text(updated)),
                entry_id=entry_id,
                is_attachment=from_enclosure,
            )
        )
    return entries


def _parse_rss(root) -> List[FeedEntry]:
    channel = _find(root, {"channel"})
    scope = channel if channel is not None else root
    entries: List[FeedEntry] = []
    for node in _find_all(scope, {"item"}):
        if node is None:
            continue
        link, from_enclosure = _pick_link(node)
        raw_pub = _text(_find(node, {"pubdate"}))
        if not raw_pub:
            dc_date = None
            for child in node:
                if _strip_ns(child.tag) == "date" and _ns_of(child.tag) == DC_NS:
                    dc_date = child
                    break
            raw_pub = _text(dc_date)
        entries.append(
            FeedEntry(
                link=link,
                title=_text(_find(node, {"title"})),
                pub_date=parse_date(raw_pub),
                pub_date_raw=raw_pub,
                updated=parse_date(raw_pub),
                entry_id=_text(_find(node, {"guid"})),
                is_attachment=from_enclosure,
            )
        )
    return entries



def looks_like_feed(text: str) -> bool:
    head = (text or "").lstrip()[:400].lower()
    return "<rss" in head or "<feed" in head or ("<rdf" in head and "rss" in head)

