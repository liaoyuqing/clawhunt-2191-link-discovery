"""Shared fixtures: load the manifest, build sources, run discovery off disk."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

FIXTURES = ROOT / "fixtures"


@pytest.fixture(scope="session")
def manifest():
    return json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def html_cases(manifest):
    return manifest["fixtures"]


@pytest.fixture(scope="session")
def feed_cases(manifest):
    return manifest["feeds"]


def read_fixture(relpath: str) -> str:
    return (FIXTURES / relpath).read_text(encoding="utf-8")


@pytest.fixture()
def page_reader():
    cache: dict = {}

    def load(relpath: str) -> str:
        if relpath not in cache:
            cache[relpath] = read_fixture(relpath)
        return cache[relpath]

    return load
