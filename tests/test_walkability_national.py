#!/usr/bin/env python3
"""Tests for the EPA National Walkability Index dimension: the bundled loader
(data/walkability.py) and the build scaling (scripts/build_walkability).

Pure computation over the bundled crosswalk — no network. Runs without pytest
(``python tests/test_walkability_national.py``) or via pytest, matching the
convention of the other test modules in this repo.
"""

from __future__ import annotations

import pandas as pd

import scripts.build_walkability as B
from housing_label.data import walkability as wref


def _close(a: float, b: float, tol: float = 1e-3) -> bool:
    return abs(a - b) <= tol


# ── Build scaling: NWI 1-20 → 0-100 ───────────────────────────────────────────
def test_scale_endpoints_and_clamp():
    assert B._scale(1.0) == 0.0
    assert B._scale(20.0) == 100.0
    assert _close(B._scale(10.5), 50.0)
    assert B._scale(0.0) == 0.0        # clamps below 1
    assert B._scale(25.0) == 100.0     # clamps above 20


def test_wmean_household_weighted():
    v = pd.Series([2.0, 18.0])
    w = pd.Series([9.0, 1.0])          # heavily weight the low-walk block group
    assert _close(B._wmean(v, w), (2 * 9 + 18 * 1) / 10)
    # all-zero weights → simple mean fallback
    assert _close(B._wmean(pd.Series([4.0, 8.0]), pd.Series([0.0, 0.0])), 6.0)


# ── Loader: tract → county → national resolution ──────────────────────────────
def test_national_row_present_and_bounded():
    r = wref.walkability_for_county(None)
    assert r["geo_level"] == "us" and r["resolved"] is False
    assert 0.0 <= r["walkability_score"] <= 100.0


def test_resolution_levels():
    ny = wref.walkability_for_county("36061")               # Manhattan
    assert ny["resolved"] and ny["geo_level"] == "county"
    assert 0.0 <= ny["walkability_score"] <= 100.0
    absent = wref.walkability_for_tract("36061999999")      # absent tract → county
    assert absent["geo_level"] == "county" and absent["resolved"]


def test_manhattan_more_walkable_than_national_median():
    assert wref.walkability_for_county("36061")["walkability_score"] > \
        wref.walkability_for_county(None)["walkability_score"]


def _run_all():
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} tests passed.")


if __name__ == "__main__":
    _run_all()
