# Test results (measured, ticket 2191)

Every number below was produced by running the suite in this working tree;
nothing is estimated.

## Command

```powershell
python -m pytest -q --junitxml=logs/pytest-junit.xml
```

## Output

```
........................................................................ [ 53%]
..............................................................           [100%]
134 passed in 0.82s
```

Exit code: **0**. Collected: **134**, passed: **134**, failed: **0**, skipped: **0**.

## Per test module

| Module | Tests | Acceptance criterion |
| --- | --- | --- |
| `tests/test_ac1_fixture_extraction.py` | 27 | AC1 - 10 fixtures extract exactly their expected links |
| `tests/test_ac2_host_allowlist.py` | 14 | AC2 - off-allow-list hosts dropped and counted |
| `tests/test_ac3_incremental.py` | 10 | AC3 - second run over the same fixture reports `new == 0` |
| `tests/test_ac4_feeds.py` | 19 | AC4 - RSS 2.0 and Atom 1.0 links and publication times |
| `tests/test_record_and_counters.py` | 8 | requirement 6 and 7 - attachment flag, counters, batch record |
| `tests/test_robots.py` | 13 | requirement 5 - robots.txt skipping and counting |
| `tests/test_urls_and_selectors.py` | 38 | requirement 3 - canonicalisation, resolution, selector engine |
| `tests/test_api_optional.py` | 5 | optional FastAPI route (skipped when FastAPI absent) |
| **total** | **134** | |

## Fixtures

| Kind | Count | Files |
| --- | --- | --- |
| HTML list pages | 10 (11 files: fixture 06 ships two pages) | `fixtures/html/*.html` |
| RSS 2.0 | 1 | `fixtures/rss/01_rss20.xml` |
| Atom 1.0 | 1 | `fixtures/rss/02_atom.xml` |
| robots.txt | 1 | `fixtures/robots/example.html_robots.txt` |
| Expected-link manifest | 1 | `fixtures/manifest.json` |

## Size

| Area | Lines |
| --- | --- |
| `src/intel_discovery/` | 1838 |
| `tests/` | 907 |
| test modules | 8 |

## Per-criterion commands

```powershell
python -m pytest tests/test_ac1_fixture_extraction.py -q   # 27 passed
python -m pytest tests/test_ac2_host_allowlist.py -q       # 14 passed
python -m pytest tests/test_ac3_incremental.py -q          # 10 passed
python -m pytest tests/test_ac4_feeds.py -q                # 19 passed
```

## Environment

| Item | Value |
| --- | --- |
| Python | 3.11.9 |
| pytest | 9.2.0 |
| SQLAlchemy | 2.0.49 |
| FastAPI | 0.136.1 |
| Database used by the tests | in-memory SQLite (no PostgreSQL, no Redis, no network) |

