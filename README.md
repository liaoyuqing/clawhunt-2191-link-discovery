# intel-link-discovery

Article link discovery for the intel briefing module: given one configured source
and its entry URL, produce the list of article links a crawler should fetch next,
skipping what has already been crawled, what robots.txt forbids and what lives
off the allow-list.

```
discover_links(source, entry_url) -> links[]
```

This repository is the deliverable for ticket **2191** (backend, medium). All
domains, titles and article bodies in the fixtures are invented for testing;
no real person, company or client appears anywhere in this repository.

---

## 1. What it does

| # | Requirement | Where |
| --- | --- | --- |
| 1 | `html_list` mode: configured list-link CSS selector first, heuristic extraction as fallback (content region, date or article number in the path, nav/footer/pagination/login excluded), `next page` following, at most 2 pages by default | `src/intel_discovery/discovery.py` (`_article_anchors`, `_heuristic_anchors`, `_content_region`, `_next_page_url`) |
| 2 | `rss` mode: RSS 2.0 and Atom 1.0, reading `link`, `title`, `pubDate` | `src/intel_discovery/feed.py` |
| 3 | Relative links resolved to absolute; hosts outside `allowed_hosts` dropped and counted | `src/intel_discovery/urls.py` (`resolve_url`, `host_allowed`) |
| 4 | Canonical URL hashed and compared against `intel_raw_pages.url_hash`; already-crawled links skipped | `src/intel_discovery/urls.py` (`normalize_url`, `url_hash`), `src/intel_discovery/store.py` (`SqlSeenUrlStore`) |
| 5 | robots.txt-disallowed links skipped and counted | `src/intel_discovery/urls.py` (`RobotsRules`), `discovery.py` (`_accept`) |
| 6 | Attachment links `.pdf` / `Content-Disposition: attachment` flagged `is_attachment` | `discovery.py` (`_anchor_is_attachment`, `_url_is_attachment`, `is_attachment_response`) |
| 7 | Counters `discovered / new / skipped_seen / skipped_robots / skipped_host` returned and written to the batch record | `discovery.py` (`DiscoveryResult`), `store.py` (`BatchDraft`, `SqlBatchRecorder`) |

An extra counter `skipped_invalid` (unresolvable or non-http(s) hrefs) is also
reported and persisted; it is not part of the ticket scope, it keeps the
arithmetic closed:

```
raw_candidates = discovered + skipped_host + skipped_invalid
discovered     = new       + skipped_seen
```

## 2. Dependencies and runtime environment

**The discovery core needs nothing but the Python standard library.** No
PostgreSQL, no Redis, no network access, no external HTTP client, and no
third-party package that could ship data offshore.

| Need | Version | Used by |
| --- | --- | --- |
| Python | 3.11+ (tested on 3.11.9) | everything |
| pytest | >= 8.0 | test suite |
| SQLAlchemy | >= 2.0 (optional) | `store.py` / `models.py` SQL path |
| FastAPI + pydantic | >= 0.110 / >= 2.6 (optional) | `api.py`, skipped when absent |

```bash
python --version                                  # Python 3.11.x
python -m pip install -r requirements.txt         # pytest + SQLAlchemy + FastAPI
python -m pip install -e .                        # installs the intel_discovery package
```

Running only the AC tests needs `pytest` and `SQLAlchemy`; `test_api_optional.py`
is skipped automatically when FastAPI is missing (`pytest.importorskip`).

Nothing reads a database, opens a socket or calls a third-party service during
the tests: every page is served from a fixture file through `StaticFetcher`,
and the SQL path runs on in-memory SQLite.

## 3. Run and test

```bash
python -m pytest -q                                       # whole suite
python -m pytest tests/test_ac1_fixture_extraction.py -q   # AC1
python -m pytest tests/test_ac2_host_allowlist.py -q       # AC2
python -m pytest tests/test_ac3_incremental.py -q          # AC3
python -m pytest tests/test_ac4_feeds.py -q                # AC4
```

Expected tail of the full run:

```
134 passed in 0.96s
```

## 4. How discovery is wired into the service

```python
from intel_discovery import SourceConfig, discover_links
from intel_discovery.store import SqlBatchRecorder, SqlSeenUrlStore

source = SourceConfig(
    source_id="<source uuid>",
    entry_url="https://example.com/news/",
    org_id="<org uuid>",
    site_id="<site uuid>",
    allowed_hosts=("example.com",),
    list_selector="ul.article-list a",       # optional; heuristic used when absent
    max_pages=2,
)

result = discover_links(
    source,
    fetcher=crawler,                          # your Fetcher implementation
    seen_store=SqlSeenUrlStore(session, source.org_id),
    recorder=SqlBatchRecorder(session),
)
session.commit()
print(result.counts())
```

`Fetcher` is a one-method port (`fetch(url) -> FetchResult`); the production
implementation wraps the shared crawler, tests use `StaticFetcher`.

## 5. Interfaces with neighbouring tickets

| Other ticket owns | Table / contract | This repository does |
| --- | --- | --- |
| Raw-page crawler | `intel_raw_pages` (`org_id`, `url_hash`, `deleted_at`) | **reads only**, via `SqlSeenUrlStore`; one batched `IN (...)` query per page (500 hashes per round-trip), so a 200-link page costs one query, not 200. The crawler inserts rows; discovery never writes them. |
| Attachment extractor | `intel_discovered_links.is_attachment` | writes `is_attachment=True` for `.pdf`/`.doc`/`.xlsx`/`zip`/`download`/`rel=enclosure`/`Content-Disposition: attachment` links so the extractor routes them away from article extraction. |
| Article extractor | `intel_discovery_batches` + `intel_discovered_links` | writes one batch row per run with all counters, plus one row per new link (`url`, `url_hash`, `title`, `pub_date`, `found_on`, `page_index`, `position`). |
| Source registry | `SourceConfig` fields | expects `source_id`, `entry_url`, `allowed_hosts`, `list_selector`, `max_pages`, and optionally a parsed `robots.txt`. |
| Scheduler / job runner | `discover_links(...)` | pure function, no globals, no I/O unless a `Fetcher`/`Session` is injected. |

`intel_raw_pages` is **not** created by this repository: its migration belongs to
the crawler ticket. `migrations/versions/0001_intel_discovery.py` creates only
`intel_discovery_batches` and `intel_discovered_links`; the unique index
`intel_raw_pages(org_id, url_hash)` is what makes the incremental check a single
indexed lookup.

## 6. Data model

Both tables carry the platform-wide audit columns `id (UUID), org_id, site_id,
created_at, created_by, updated_at, deleted_at` (soft delete). No monetary column
exists in this ticket.

```
intel_discovery_batches
  id, org_id, site_id, created_at, created_by, updated_at, deleted_at,
  source_id, entry_url, mode, pages_fetched, raw_candidates,
  discovered, new, skipped_seen, skipped_robots, skipped_host,
  skipped_invalid, started_at, finished_at

intel_discovered_links
  id, org_id, site_id, created_at, created_by, updated_at, deleted_at,
  batch_id -> intel_discovery_batches.id, source_id, url, url_hash,
  title, anchor_text, pub_date, found_on, page_index, position, is_attachment
```

```bash
export INTEL_DATABASE_URL="postgresql+psycopg://user:pass@host:5432/intel"   # env only
alembic upgrade head
```

The URL never appears in code: `migrations/env.py` reads
`INTEL_DATABASE_URL` from the environment.

## 7. URL canonicalisation

`normalize_url` is the single definition of "the same page", and
`url_hash = sha256(normalize_url(url))` is the value stored in
`intel_raw_pages.url_hash`. It lower-cases scheme and host, drops the default
port, removes the fragment, resolves dot-segments, drops tracking parameters
(`utm_*`, `fbclid`, `gclid`, `spm`, ...), sorts the remaining query and
upper-cases percent escapes. Tests assert that six spellings of one article URL
collapse to one hash.

## 8. Fixtures

10 fictional HTML list pages and 2 feeds, all invented:

| Fixture | Exercises |
| --- | --- |
| `fixtures/html/01_date_path_list.html` | date-shaped paths, tracking params, an off-site mirror, `../` in a path |
| `fixtures/html/02_numeric_id_list.html` | bare article numbers, a relative href without a leading slash, `<dl>` markup |
| `fixtures/html/03_slug_with_id.html` | slug-plus-number paths, a next-page link in a `.pager` |
| `fixtures/html/04_compact_date.html` | `YYYYMMDD` path segments, an allow-listed second host |
| `fixtures/html/05_main_region.html` | `<main>` region, extension-less article paths, an off-site guest post |
| `fixtures/html/06_pagination_page1/2.html` | two-page walk via `rel="next"`, page 3 must never be fetched |
| `fixtures/html/07_selector_configured.html` | opaque classes: only the configured selector finds the list |
| `fixtures/html/08_attachment_list.html` | `.pdf`, `type=application/pdf`, `download`, `rel=enclosure` |
| `fixtures/html/09_heuristic_noise.html` | decoys in nav, sidebar and footer |
| `fixtures/html/10_full_site.html` | full page shell: header/nav/aside/footer must be ignored |
| `fixtures/rss/01_rss20.xml` | RSS 2.0, RFC 822 dates across time zones, a relative link, an enclosure |
| `fixtures/rss/02_atom.xml` | Atom 1.0, `rel=alternate` vs `rel=enclosure`, ISO 8601 dates |

`fixtures/manifest.json` holds the expected link list per fixture, so the tests
compare against declared expectations instead of hard-coded duplicates.
`fixtures/robots/example.html_robots.txt` supplies the robots rules.

## 9. Layout

```
src/intel_discovery/
  discovery.py   discover_links, SourceConfig, heuristics, next-page walk, counters
  feed.py        RSS 2.0 / RSS 1.0 / Atom 1.0 parsing and date parsing
  urls.py        normalisation, url_hash, allow-list, robots.txt matcher
  dom.py         dependency-free HTML tree builder on top of html.parser
  css.py         small CSS selector engine (tag/class/id/attr/descendant/child)
  models.py      SQLAlchemy 2 models (intel_raw_pages read side + two owned tables)
  store.py       SeenUrlStore / BatchRecorder ports and their SQL + memory impls
  api.py         optional FastAPI route (skipped when FastAPI is absent)
fixtures/        10 HTML pages, 2 feeds, robots.txt, expected-lists manifest
tests/           pytest suite covering the four acceptance criteria
migrations/      Alembic migration creating the two owned tables
```

The CSS engine is deliberately a subset: pseudo-classes and sibling combinators
raise `SelectorError` instead of silently matching the wrong nodes, so a bad
source configuration fails loudly during a discovery run.

## 10. Acceptance criteria mapping

| AC | Statement | Test |
| --- | --- | --- |
| 1 | The 10 fictional list-page fixtures extract exactly their expected link list (pytest) | `tests/test_ac1_fixture_extraction.py` (parametrised over all 10 fixtures, compared against `fixtures/manifest.json`) |
| 2 | Links on hosts outside the allow-list are dropped and counted in `skipped_host` | `tests/test_ac2_host_allowlist.py` |
| 3 | A second run over the same fixture reports `new == 0` | `tests/test_ac3_incremental.py` (memory store and the real SQLAlchemy/SQLite `intel_raw_pages` path) |
| 4 | The RSS and Atom fixtures each parse the correct links and publication times | `tests/test_ac4_feeds.py` |

## 11. Notes

* robots.txt: a crawler obeys the group naming it, and falls back to `*`
  otherwise. Longest match wins; `Allow` wins an equal-length tie; `*` and `$`
  wildcards are supported.
* "Content region": the container with the most article-shaped anchors wins,
  ties going to the smallest subtree, so a single-article page still works
  while a ten-card list never collapses to one card.
* Discovery never raises on a bad `href`, a malformed HTML page or a missing
  trailing page: bad hrefs increment `skipped_invalid`, malformed markup is
  tolerated, and a missing "next page" simply ends the walk.
* No client name, no real domain, no real person appears in this repository.

