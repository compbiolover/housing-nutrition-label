#!/usr/bin/env python3
"""Tests for the NATIONAL socioeconomic reference: the bundled loader
(data/socioeconomic.py) and the build math (scripts/build_socio_ref).

These lock in the fix for the old within-county ranking: a tract's
socioeconomic_index is now a national percentile, comparable across locations.
"""

from __future__ import annotations

import pandas as pd

import scripts.build_socio_ref as B
from housing_label.data import socioeconomic as sref


# ── Build math: household-weighted percentile ─────────────────────────────────
def test_weighted_percentile_below_and_bounds():
    vals = pd.Series([10.0, 20.0, 30.0], index=["a", "b", "c"])
    w = pd.Series([1.0, 1.0, 1.0], index=["a", "b", "c"])
    pct = B._wpct(vals, w)
    assert pct["a"] < pct["b"] < pct["c"]
    assert 0.0 <= pct.min() and pct.max() <= 1.0
    assert pct["b"] == 0.5              # uniform weights, symmetric → middle at 0.5


def test_score_tracts_orientation():
    """Least-stress tract (low poverty, high income, low burden) scores highest."""
    tracts = pd.DataFrame(
        {
            "poverty_rate_pct": [3.0, 15.0, 35.0],
            "median_household_income": [140000, 70000, 28000],
            "housing_cost_burden_pct": [15.0, 30.0, 55.0],
            "households": [1000, 1000, 1000],
        },
        index=["good", "mid", "bad"],
    )
    out = B.score_tracts(tracts)
    si = out["socioeconomic_index"]
    assert si["good"] > si["mid"] > si["bad"]
    assert (si >= 0).all() and (si <= 100).all()


# ── Loader: tract → county → national resolution ──────────────────────────────
def test_national_row_centered():
    r = sref.socio_for_county(None)
    assert r["geo_level"] == "us" and r["resolved"] is False
    assert abs(r["socioeconomic_index"] - 50.0) <= 1.0     # centered by construction


def test_tract_resolution_levels():
    tract = sref.socio_for_tract("47157000100")
    assert tract["resolved"] and tract["geo_level"] == "tract"
    assert 0.0 <= tract["socioeconomic_index"] <= 100.0
    county = sref.socio_for_tract("47157999999")           # absent tract → county
    assert county["geo_level"] == "county" and county["resolved"]


def test_metrics_present_on_result():
    r = sref.socio_for_tract("47157000100")
    for m in ("poverty_rate_pct", "median_household_income", "housing_cost_burden_pct"):
        assert m in r["metrics"]


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} tests passed.")
