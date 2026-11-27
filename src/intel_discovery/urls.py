"""URL resolution, canonicalisation, host allow-lists and robots.txt matching."""
from __future__ import annotations

import hashlib
import re
from typing import Iterable, Optional, Sequence, Tuple
from urllib.parse import (
    quote,
    unquote,
    urljoin,
    urlsplit,
    urlunsplit,
)

DEFAULT_PORTS = {"http": 80, "https": 443}

# Query parameters that never carry content identity; dropped before hashing.
TRACKING_PARAM_PREFIXES = ("utm_", "pk_", "mc_", "ref_")
TRACKING_PARAMS = frozenset({"fbclid", "gclid", "spm", "_openstat", "from"})

_PERCENT = re.compile(r"%[0-9a-fA-F]{2}")
_UNRESERVED = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")


class UrlError(ValueError):
    """Raised when a reference cannot be turned into an absolute http(s) URL."""


def host_of(url: str) -> str:
    """Return the lower-cased hostname of ``url`` (empty string when absent)."""
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def _canonicalise_percent(text: str) -> str:
    def fix(match: "re.Match[str]") -> str:
        return match.group(0).upper()

    return _PERCENT.sub(fix, text)


def _encode_path(path: str) -> str:
    """Percent-encode characters a URL may not contain, keeping existing escapes."""
    out = []
    index = 0
    while index < len(path):
        ch = path[index]
        if ch == "%" and _PERCENT.match(path, index):
            out.append(path[index:index + 3].upper())
            index += 3
            continue
        if ch in _UNRESERVED or ch in "/:@!$&'()*+,;=-._~":
            out.append(ch)
        else:
            out.append(quote(ch, safe=""))
        index += 1
    return "".join(out)


def _remove_dot_segments(path: str) -> str:
    if not path:
        return "/"
    absolute = path.startswith("/")
    segments = path.split("/")
    output = []
    for segment in segments:
        if segment == ".":
            continue
        if segment == "..":
            if output and output[-1] not in ("", ".."):
                output.pop()
            continue
        output.append(segment)
    result = "/".join(output)
    if absolute and not result.startswith("/"):
        result = "/" + result
    return result or "/"


def _clean_query(query: str) -> str:
    if not query:
        return ""
    kept: list = []
    for chunk in query.split("&"):
        if not chunk:
            continue
        name = chunk.split("=", 1)[0]
        lowered = unquote(name).lower()
        if lowered in TRACKING_PARAMS or lowered.startswith(TRACKING_PARAM_PREFIXES):
            continue
        kept.append(chunk)
    kept.sort()
    return "&".join(kept)


def normalize_url(url: str, strip_trailing_slash: bool = False) -> str:
    """Return the canonical form of an absolute http(s) URL.

    The canonical form is what ``url_hash`` is computed over, so it must be
    stable across crawls: lower-cased scheme/host, no default port, no
    fragment, dot-segments resolved, tracking parameters removed and the
    remaining query sorted, percent-escapes upper-cased.
    """
    if not url:
        raise UrlError("empty url")
    parts = urlsplit(url.strip())
    scheme = (parts.scheme or "").lower()
    if scheme not in DEFAULT_PORTS:
        raise UrlError("unsupported scheme: %r" % (scheme or url))
    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        raise UrlError("missing host: %r" % url)
    port = parts.port
    netloc = host
    if port is not None and port != DEFAULT_PORTS[scheme]:
        netloc = "%s:%d" % (host, port)
    path = _encode_path(_remove_dot_segments(parts.path or "/"))
    if strip_trailing_slash and path != "/" and path.endswith("/"):
        path = path.rstrip("/") or "/"
    query = _clean_query(parts.query)
    return urlunsplit((scheme, netloc, path, query, ""))


def url_hash(url: str) -> str:
    """SHA-256 (hex) of the canonical URL - the value stored in intel_raw_pages."""
    return hashlib.sha256(normalize_url(url).encode("utf-8")).hexdigest()


def resolve_url(base: str, href: str) -> str:
    """Resolve ``href`` against ``base``; raise UrlError for non-http(s) results."""
    href = (href or "").strip()
    if not href:
        raise UrlError("empty href")
    if href.startswith("//"):
        scheme = urlsplit(base).scheme or "https"
        href = scheme + ":" + href
    absolute = urljoin(base, href)
    scheme = urlsplit(absolute).scheme.lower()
    if scheme not in DEFAULT_PORTS:
        raise UrlError("unsupported scheme: %r" % scheme)
    return absolute


def host_allowed(url: str, allowed_hosts: Sequence[str]) -> bool:
    """True when ``url``'s host is in ``allowed_hosts`` (exact or ``*.suffix``).

    An empty allow-list denies everything: crawling without an explicit
    allow-list is never the intended behaviour for an intel source.
    """
    host = host_of(url)
    if not host:
        return False
    for entry in allowed_hosts or ():
        candidate = (entry or "").strip().lower().lstrip(".")
        if not candidate:
            continue
        if candidate.startswith("*."):
            suffix = candidate[2:]
            if host == suffix or host.endswith("." + suffix):
                return True
        elif host == candidate:
            return True
    return False


def matches_prefix(url: str, prefixes: Iterable[str]) -> bool:
    """Prefix helpers kept for ``next_page_prefixes`` style configuration."""
    path = urlsplit(url).path or "/"
    for prefix in prefixes or ():
        if prefix and path.startswith(prefix):
            return True
    return False


class RobotsRules:
    """A parsed robots.txt for one user agent.

    Supports ``Allow``/``Disallow`` with ``*`` wildcards, ``$`` end anchors and
    the standard "longest matching rule wins, Allow wins ties" resolution.
    """

    def __init__(self, groups: Optional[dict] = None, agent: str = ""):
        self.agent = agent
        self.rules: list = []
        if groups:
            self.rules = self._rules_for_agent(groups, agent)

    @staticmethod
    def _rules_for_agent(groups: dict, agent: str) -> list:
        token = (agent or "").strip().lower()
        if token in groups:
            return groups[token]
        for key, rules in groups.items():
            if key and key != "*" and token.startswith(key):
                return rules
        return groups.get("*", [])

    @classmethod
    def parse(cls, text: str, agent: str = "intel-link-discovery") -> "RobotsRules":
        groups: dict = {}
        current: list = []
        current_key: Optional[str] = None
        for raw in (text or "").splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line or ":" not in line:
                continue
            field, value = line.split(":", 1)
            field = field.strip().lower()
            value = value.strip()
            if field == "user-agent":
                key = value.lower()
                if current_key is not None and current:
                    groups.setdefault(current_key, []).extend(current)
                    current = []
                current_key = key
                groups.setdefault(key, [])
            elif field in ("allow", "disallow") and current_key is not None:
                if not value:
                    continue
                current.append((field == "allow", value, _compile_rule(value)))
        if current_key is not None and current:
            groups.setdefault(current_key, []).extend(current)
        return cls(groups, agent)

    def allowed(self, url: str) -> bool:
        if not self.rules:
            return True
        path = urlsplit(url).path or "/"
        if not path.startswith("/"):
            path = "/" + path
        query = urlsplit(url).query
        target = path + (("?" + query) if query else "")
        best_len = -1
        best_allow = True
        for allow, pattern, regex in self.rules:
            if regex.match(target):
                length = len(pattern)
                if length > best_len or (length == best_len and allow):
                    best_len = length
                    best_allow = allow
        return best_allow


def _compile_rule(pattern: str):
    anchored = pattern.endswith("$")
    body = pattern[:-1] if anchored else pattern
    escaped = re.escape(body).replace(r"\*", ".*")
    suffix = "$" if anchored else ""
    return re.compile("^" + escaped + suffix)


def parse_robots(text: str, agent: str = "intel-link-discovery") -> RobotsRules:
    return RobotsRules.parse(text, agent)

ALLOW_ALL = RobotsRules()


def check_robots(url: str, robots: Optional[RobotsRules]) -> bool:
    if robots is None:
        return True
    return robots.allowed(url)

