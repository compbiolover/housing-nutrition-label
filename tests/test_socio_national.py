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
    """Least-stress tract (low poverty, high income, low burden, high education,
    low unemployment) scores highest across all five blended metrics."""
    tracts = pd.DataFrame(
        {
            "poverty_rate_pct": [3.0, 15.0, 35.0],
            "median_household_income": [140000, 70000, 28000],
            "housing_cost_burden_pct": [15.0, 30.0, 55.0],
            "education_bachelors_plus_pct": [70.0, 30.0, 8.0],   # direct: more → higher
            "unemployment_rate_pct": [2.0, 5.0, 14.0],           # inverted: less → higher
            "households": [1000, 1000, 1000],
        },
        index=["good", "mid", "bad"],
    )
    out = B.score_tracts(tracts)
    si = out["socioeconomic_index"]
    assert si["good"] > si["mid"] > si["bad"]
    assert (si >= 0).all() and (si <= 100).all()


def test_score_tracts_education_and_jobs_move_the_score():
    """The two new metrics genuinely affect the index: flipping education and
    unemployment on an otherwise-identical tract changes its score."""
    base = dict(poverty_rate_pct=12.0, median_household_income=70000,
                housing_cost_burden_pct=28.0, households=1000)
    tracts = pd.DataFrame(
        {**{k: [v, v] for k, v in base.items()},
         "education_bachelors_plus_pct": [65.0, 10.0],
         "unemployment_rate_pct": [2.0, 15.0]},
        index=["educated_employed", "less_so"],
    )
    si = B.score_tracts(tracts)["socioeconomic_index"]
    assert si["educated_employed"] > si["less_so"]


def test_derive_metrics_formulas():
    """The ACS table cells map to the five headline metrics via the documented
    ratios — covers education (B15003) and unemployment (B23025) without a rebuild."""
    g = B.TRACT_PREFIX + "47157000100"
    b17001 = {g: {"B17001_E001": 1000.0, "B17001_E002": 100.0}}          # 10.0% poverty
    b19013 = {g: {"B19013_E001": 65000.0}}
    b25106 = {g: {"B25106_E001": 500.0, "B25106_E023": 0.0,
                  "B25106_E045": 0.0, "B25106_E046": 0.0,
                  "B25106_E006": 50.0, "B25106_E010": 0.0, "B25106_E014": 0.0,
                  "B25106_E018": 0.0, "B25106_E022": 0.0,
                  "B25106_E028": 50.0, "B25106_E032": 0.0, "B25106_E036": 0.0,
                  "B25106_E040": 0.0, "B25106_E044": 0.0}}               # (50+50)/500 = 20.0%
    b15003 = {g: {"B15003_E001": 200.0, "B15003_E022": 40.0, "B15003_E023": 10.0,
                  "B15003_E024": 0.0, "B15003_E025": 0.0}}               # 50/200 = 25.0%
    b23025 = {g: {"B23025_E003": 400.0, "B23025_E005": 20.0}}            # 20/400 = 5.0%

    r = B.derive_metrics(b17001, b19013, b25106, b15003, b23025).loc["47157000100"]
    assert r["poverty_rate_pct"] == 10.0
    assert r["median_household_income"] == 65000
    assert r["housing_cost_burden_pct"] == 20.0
    assert r["education_bachelors_plus_pct"] == 25.0
    assert r["unemployment_rate_pct"] == 5.0


def test_derive_metrics_suppressed_education_cell_unscored():
    """A suppressed bachelor's+ cell leaves education unscored (not understated to 0)."""
    import numpy as np
    g = B.TRACT_PREFIX + "47157000200"
    b15003 = {g: {"B15003_E001": 200.0, "B15003_E022": None, "B15003_E023": 10.0,
                  "B15003_E024": 0.0, "B15003_E025": 0.0}}
    r = B.derive_metrics({}, {}, {}, b15003, {}).loc["47157000200"]
    assert np.isnan(r["education_bachelors_plus_pct"])


def test_min_metrics_needs_three_of_five():
    """A tract with only two available metrics is left unscored (MIN_METRICS=3)."""
    import numpy as np
    tracts = pd.DataFrame(
        {
            "poverty_rate_pct": [10.0, 10.0],
            "median_household_income": [70000, 70000],
            "housing_cost_burden_pct": [np.nan, 25.0],
            "education_bachelors_plus_pct": [np.nan, 40.0],
            "unemployment_rate_pct": [np.nan, 5.0],
            "households": [1000, 1000],
        },
        index=["two_metrics", "five_metrics"],
    )
    si = B.score_tracts(tracts)["socioeconomic_index"]
    assert pd.isna(si["two_metrics"]) and pd.notna(si["five_metrics"])


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
    for m in ("poverty_rate_pct", "median_household_income", "housing_cost_burden_pct",
              "education_bachelors_plus_pct", "unemployment_rate_pct"):
        assert m in r["metrics"]


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} tests passed.")
