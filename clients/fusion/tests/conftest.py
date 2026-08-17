# MIT License
# Copyright (c) 2026 sliptonic
# SPDX-License-Identifier: MIT
"""Test path setup: the package under test, and the `loobric` client library
from the sibling loobric-cli checkout when it isn't pip-installed."""
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
try:
    import loobric  # noqa: F401
except ImportError:
    # Sibling checkout fallbacks: monorepo layout (clients/fusion under
    # loobric-clients, loobric-cli next to it) first, then the old flat layout.
    for candidate in (HERE.parents[3] / "loobric-cli",
                      HERE.parents[1] / "loobric-cli"):
        if candidate.is_dir():
            sys.path.insert(0, str(candidate))
            break

FIXTURES = HERE / "fixtures"


@pytest.fixture()
def sample_doc():
    """A real Fusion export: 6 tools — Sandvik ball end mill (mm), probe,
    HSS 'mysterybit' with live preset numbers (mm), Tormach flat end mill
    with holder (in), drill, bull nose end mill."""
    with open(FIXTURES / "sample.json", encoding="utf-8") as fh:
        return json.load(fh)


def tool_named(doc, fragment):
    for tool in doc["data"]:
        if fragment in (tool.get("description") or ""):
            return tool
    raise AssertionError("no sample tool matching %r" % fragment)
