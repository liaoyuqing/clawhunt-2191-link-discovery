"""Thin FastAPI surface for the link-discovery service (optional runtime).

The HTTP layer exists so the ticket fits the platform-wide FastAPI convention;
the discovery logic itself is transport agnostic and fully exercised without a
server (see ``tests/``).  Nothing here performs network I/O: pages are supplied
by the shared crawler, injected through :class:`PageFetcher` implementations.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from .discovery import (
    DiscoveryError,
    DiscoveryResult,
    SourceConfig,
    StaticFetcher,
    discover_links,
)
from .store import BatchRecorder, MemoryBatchRecorder, MemorySeenUrlStore, SeenUrlStore
from .urls import UrlError, parse_robots

router = APIRouter(prefix="/api/v1/intel", tags=["intel-discovery"])


class SourceIn(BaseModel):
    source_id: str
    entry_url: str
    org_id: str = "00000000-0000-0000-0000-000000000000"
    site_id: str = "00000000-0000-0000-0000-000000000000"
    mode: str = "html_list"
    allowed_hosts: List[str] = Field(default_factory=list)
    list_selector: Optional[str] = None
    content_selector: Optional[str] = None
    next_page_selector: Optional[str] = None
    max_pages: int = 2
    robots_txt: Optional[str] = None


class PageIn(BaseModel):
    url: str
    html: str
    content_type: str = "text/html"


class DiscoverIn(BaseModel):
    """``pages`` replaces the crawler: pass the HTML the crawler already holds."""

    source: SourceIn
    pages: List[PageIn] = Field(default_factory=list)
    entry_url: Optional[str] = None
    seen_url_hashes: List[str] = Field(default_factory=list)


class LinkOut(BaseModel):
    url: str
    url_hash: str
    title: str
    anchor_text: str
    pub_date: Optional[str]
    is_attachment: bool
    found_on: str
    page_index: int
    position: int


class DiscoverOut(BaseModel):
    mode: str
    pages_fetched: int
    raw_candidates: int
    discovered: int
    new: int
    skipped_seen: int
    skipped_robots: int
    skipped_host: int
    skipped_invalid: int
    batch_id: Optional[str]
    links: List[LinkOut]


def get_seen_store() -> SeenUrlStore:
    """Override in deployment with SqlSeenUrlStore(session, org_id)."""
    return MemorySeenUrlStore()


def get_recorder() -> BatchRecorder:
    """Override in deployment with SqlBatchRecorder(session)."""
    return MemoryBatchRecorder()


@router.post("/discover-links", response_model=DiscoverOut)
def discover_links_endpoint(
    payload: DiscoverIn,
    recorder: BatchRecorder = Depends(get_recorder),
) -> DiscoverOut:
    incoming = {page.url: page.html for page in payload.pages}
    if not incoming:
        raise HTTPException(status_code=422, detail="pages must contain the entry page")
    fetcher = StaticFetcher(incoming)
    robots = None
    if payload.source.robots_txt:
        robots = parse_robots(payload.source.robots_txt)
    source = SourceConfig(
        source_id=payload.source.source_id,
        entry_url=payload.source.entry_url,
        org_id=payload.source.org_id,
        site_id=payload.source.site_id,
        mode=payload.source.mode,
        allowed_hosts=tuple(payload.source.allowed_hosts),
        list_selector=payload.source.list_selector,
        content_selector=payload.source.content_selector,
        next_page_selector=payload.source.next_page_selector,
        max_pages=payload.source.max_pages,
        robots=robots,
    )
    seen = MemorySeenUrlStore(payload.seen_url_hashes)
    try:
        result: DiscoveryResult = discover_links(
            source,
            entry_url=payload.entry_url,
            fetcher=fetcher,
            seen_store=seen,
            recorder=recorder,
        )
    except (DiscoveryError, UrlError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    payload_out = result.to_dict()
    return DiscoverOut(**payload_out)


def create_app() -> FastAPI:
    app = FastAPI(title="Intel link discovery", version="1.0.0")
    app.include_router(router)

    @app.get("/healthz")
    def healthz() -> Dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()

__all__ = ["app", "create_app", "router"]
