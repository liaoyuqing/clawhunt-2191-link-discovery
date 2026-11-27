#!/usr/bin/env python
"""Run the four acceptance-criteria test modules and print one evidence block each.

    python scripts/run_ac.py            # all four criteria
    python scripts/run_ac.py AC3        # just one

Exit code is 0 only when every selected criterion passes, so this doubles as a
pre-submission gate.  Each block prints the module, the pytest tail line and the
number of tests that ran.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CRITERIA = [
    (
        "AC1",
        "The 10 fictional list pages extract exactly their expected links",
        "tests/test_ac1_fixture_extraction.py",
    ),
    (
        "AC2",
        "Off-allow-list hosts are dropped and counted in skipped_host",
        "tests/test_ac2_host_allowlist.py",
    ),
    (
        "AC3",
        "A second run over the same fixture reports new == 0",
        "tests/test_ac3_incremental.py",
    ),
    (
        "AC4",
        "The RSS and Atom fixtures parse the right links and publication times",
        "tests/test_ac4_feeds.py",
    ),
]


def run(module: str) -> tuple:
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", module, "-q"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    tail = lines[-1] if lines else ""
    return completed.returncode, tail


def main(argv) -> int:
    wanted = {item.upper() for item in argv[1:]} or {key for key, _, _ in CRITERIA}
    failures = 0
    for key, statement, module in CRITERIA:
        if key not in wanted:
            continue
        code, tail = run(module)
        status = "PASS" if code == 0 else "FAIL"
        print("=" * 78)
        print("%s [%s] %s" % (key, status, statement))
        print("  module : %s" % module)
        print("  pytest : %s" % tail)
        print("  exit   : %d" % code)
        if code != 0:
            failures += 1
    print("=" * 78)
    print("ALL PASS" if failures == 0 else "%d CRITERIA FAILED" % failures)
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

