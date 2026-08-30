#!/usr/bin/env python3
"""The distribution actually contains every package in the source tree.

Why this exists
---------------
``pyproject.toml`` lists packages explicitly rather than autodiscovering them, so
a new subpackage is included in a wheel only if someone remembers to add it. Tests
never catch the omission: CI installs the project editable, which imports straight
from ``src/`` and finds the package whether or not it is declared. The failure
appears only for someone who installs a built wheel, as an ImportError at runtime.

That is exactly what happened when ``housing_label.enrich.assessor`` was added, so
the invariant is pinned here rather than left to memory.

Stdlib only, deliberately
-------------------------
The first version of this file imported ``tomllib`` and ``setuptools``. Both are
absent somewhere this suite runs — ``tomllib`` is 3.11+ and the project supports
3.10; ``setuptools`` is not a dependency and modern CI images no longer ship it
— and because an import error at collection time aborts the *entire* run, a test
guarding a packaging detail took the whole suite down on both Python versions.

So the package list is read with a narrow parser and the tree is walked with
pathlib. The parser raises rather than returning empty if it cannot find the
list, so a reformatted pyproject fails loudly instead of turning this into a test
that silently checks nothing.

This file alone: ``pytest tests/test_packaging.py``
"""

from __future__ import annotations

import pathlib
import re

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_SRC = _ROOT / "src"


def _declared_packages() -> set[str]:
    """The `packages` list under `[tool.setuptools]`, without a TOML parser."""
    text = (_ROOT / "pyproject.toml").read_text()
    section = re.search(r"^\[tool\.setuptools\]\s*$(.*?)(?=^\[)", text,
                        re.MULTILINE | re.DOTALL)
    if section is None:
        raise AssertionError(
            "no [tool.setuptools] section in pyproject.toml — this guard can no "
            "longer read the package list, so fix the parser rather than deleting "
            "the test")
    listing = re.search(r"^packages\s*=\s*\[(.*?)\]", section.group(1),
                        re.MULTILINE | re.DOTALL)
    if listing is None:
        raise AssertionError(
            "[tool.setuptools] has no `packages = [...]` list. If the project "
            "switched to autodiscovery this test is obsolete; if it moved, update "
            "the parser.")
    return set(re.findall(r"[\"']([^\"']+)[\"']", listing.group(1)))


def _source_packages() -> set[str]:
    """Every importable package under src/, as a dotted name."""
    return {
        ".".join(init.parent.relative_to(_SRC).parts)
        for init in _SRC.rglob("__init__.py")
    }


def test_the_parser_actually_finds_the_package_list():
    """A guard that silently reads nothing would pass forever. Pin that the
    parser returns a real list containing a package known to be declared."""
    declared = _declared_packages()
    assert len(declared) >= 4, f"suspiciously short package list: {declared}"
    assert "housing_label" in declared


def test_the_source_walk_actually_finds_packages():
    found = _source_packages()
    assert "housing_label" in found
    assert "housing_label.enrich" in found


def test_every_source_package_is_declared_for_distribution():
    missing = sorted(_source_packages() - _declared_packages())
    assert not missing, (
        f"{missing} exist under src/ but are not in pyproject's package list, so a "
        f"wheel would omit them and importing them would fail for anyone who did "
        f"not install editable. Add them to [tool.setuptools] packages.")
