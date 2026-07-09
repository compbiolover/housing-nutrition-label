#!/usr/bin/env python3
"""Tests for the NATIONAL health reference: the bundled loader (data/health.py)
and the build math (scripts/build_health_ref.weighted_percentile_score).

These lock in the fix for the old within-county ranking: a tract's health_index
is now a national percentile, comparable across locations.
"""

from __future__ import annotations

import pandas as pd

import scripts.build_health_ref as B
from housing_label.data import health as href


# ── Build math: population-weighted percentile → inverted 0-100 score ──────────
def test_weighted_percentile_orientation_and_bounds():
    """Lower prevalence (better health) → higher score; all scores in [0, 100]."""
    vals = pd.Series([5.0, 20.0, 40.0], index=["a", "b", "c"])
    w = pd.Series([1.0, 1.0, 1.0], index=["a", "b", "c"])
    s = B.weighted_percentile_score(vals, w)
    assert s["a"] > s["b"] > s["c"]
    assert 0.0 <= s.min() and s.max() <= 100.0
    # Uniform weights, symmetric values → the middle sits at the median (50).
    assert s["b"] == 50.0


def test_weighted_percentile_respects_weights():
    """A heavily-weighted low-prevalence mass pushes the population percentile so
    the few high-prevalence tracts score near the bottom."""
    vals = pd.Series([5.0, 6.0, 40.0], index=["a", "b", "c"])
    w = pd.Series([100.0, 100.0, 1.0], index=["a", "b", "c"])
    s = B.weighted_percentile_score(vals, w)
    assert s["c"] < 5.0            # almost all population is healthier than c


def test_weighted_percentile_keeps_nan():
    vals = pd.Series([5.0, None, 40.0], index=["a", "b", "c"])
    w = pd.Series([1.0, 1.0, 1.0], index=["a", "b", "c"])
    s = B.weighted_percentile_score(vals, w)
    assert pd.isna(s["b"])


# ── Loader: tract → county → national resolution ──────────────────────────────
def test_national_row_is_centered_at_fifty():
    """The population-weighted national mean percentile is 50 by construction."""
    assert href.health_for_county(None)["health_index"] == 50.0
    assert href.health_for_county(None)["geo_level"] == "us"
    assert href.health_for_county(None)["resolved"] is False


def test_tract_resolution_levels():
    tract = href.health_for_tract("47157000100")     # a real Shelby tract
    assert tract["resolved"] and tract["geo_level"] == "tract"
    assert 0.0 <= tract["health_index"] <= 100.0
    # A tract absent from the crosswalk falls back to its county.
    county = href.health_for_tract("47157999999")
    assert county["geo_level"] == "county" and county["resolved"]


def test_memphis_scores_below_national_median():
    """Shelby County (Memphis) has a high chronic-disease burden, so its national
    health score sits below the median — the signal within-county ranking hid."""
    assert href.health_for_county("47157")["health_index"] < 50.0


def test_measures_present_on_result():
    r = href.health_for_tract("47157000100")
    for m in ("obesity_pct", "diabetes_pct", "high_bp_pct"):
        assert m in r["measures"]


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} tests passed.")
