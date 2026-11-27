"""Intel link discovery: HTML list pages and RSS/Atom feeds -> article links.

Public API:

* :func:`intel_discovery.discovery.discover_links` - the ticket's entry point
* :class:`intel_discovery.discovery.SourceConfig` - one configured source
* :class:`intel_discovery.store.SqlSeenUrlStore` - ``intel_raw_pages`` reader
* :class:`intel_discovery.store.SqlBatchRecorder` - batch record writer
"""
from __future__ import annotations

from .discovery import (
    ATTACHMENT_EXTENSIONS,
    DEFAULT_MAX_PAGES,
    DiscoveredLink,
    DiscoveryError,
    DiscoveryResult,
    Fetcher,
    FetchResult,
    SourceConfig,
    StaticFetcher,
    discover_links,
    is_attachment_response,
)
from .feed import FeedEntry, FeedError, parse_date, parse_feed
from .models import Base, IntelDiscoveredLink, IntelDiscoveryBatch, IntelRawPage
from .store import (
    BatchDraft,
    BatchRecorder,
    MemoryBatchRecorder,
    MemorySeenUrlStore,
    SeenLink,
    SeenUrlStore,
    SqlBatchRecorder,
    SqlSeenUrlStore,
)
from .urls import RobotsRules, UrlError, host_allowed, normalize_url, parse_robots, url_hash

__version__ = "1.0.0"

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
    "parse_feed",
    "parse_date",
    "FeedEntry",
    "FeedError",
    "normalize_url",
    "url_hash",
    "host_allowed",
    "parse_robots",
    "RobotsRules",
    "UrlError",
    "SeenUrlStore",
    "BatchRecorder",
    "SqlSeenUrlStore",
    "SqlBatchRecorder",
    "MemorySeenUrlStore",
    "MemoryBatchRecorder",
    "SeenLink",
    "BatchDraft",
    "Base",
    "IntelRawPage",
    "IntelDiscoveryBatch",
    "IntelDiscoveredLink",
    "__version__",
]
