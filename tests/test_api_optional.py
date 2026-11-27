"""Optional HTTP layer: the same discovery run through FastAPI's TestClient."""
from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from intel_discovery.api import app  # noqa: E402

CLIENT = TestClient(app)

PAGE = """
<html><body><main><ul class="article-list">
<li><a href="/news/2026/03/12/a.html">A</a></li>
<li><a href="https://off.example.net/news/2026/03/11/b.html">B off-site</a></li>
<li><a href="/files/2026/03/10/report.pdf">Report</a></li>
</ul></main></body></html>
"""


def _payload(**overrides):
    body = {
        "source": {
            "source_id": "src-http",
            "entry_url": "https://www.example.com/list.html",
            "allowed_hosts": ["www.example.com"],
            "max_pages": 1,
        },
        "pages": [{"url": "https://www.example.com/list.html", "html": PAGE}],
    }
    body.update(overrides)
    return body


def test_healthz():
    assert CLIENT.get("/healthz").json() == {"status": "ok"}


def test_discover_endpoint_returns_counters_and_links():
    response = CLIENT.post("/api/v1/intel/discover-links", json=_payload())
    assert response.status_code == 200
    data = response.json()
    assert data["discovered"] == 2
    assert data["new"] == 2
    assert data["skipped_host"] == 1
    assert [link["url"] for link in data["links"]] == [
        "https://www.example.com/news/2026/03/12/a.html",
        "https://www.example.com/files/2026/03/10/report.pdf",
    ]
    assert data["links"][1]["is_attachment"] is True


def test_seen_hashes_short_circuit_to_zero_new():
    first = CLIENT.post("/api/v1/intel/discover-links", json=_payload()).json()
    hashes = [link["url_hash"] for link in first["links"]]
    second = CLIENT.post(
        "/api/v1/intel/discover-links",
        json=_payload(seen_url_hashes=hashes),
    ).json()
    assert second["new"] == 0
    assert second["skipped_seen"] == len(hashes)


def test_missing_pages_is_422():
    response = CLIENT.post("/api/v1/intel/discover-links", json=_payload(pages=[]))
    assert response.status_code == 422


def test_bad_selector_is_422():
    body = _payload()
    body["source"]["list_selector"] = "a:hover"
    response = CLIENT.post("/api/v1/intel/discover-links", json=body)
    assert response.status_code == 422
    assert "selector" in response.json()["detail"].lower()
