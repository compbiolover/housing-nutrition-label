#!/usr/bin/env python3
"""Offline tests for the per-county climate-projection lookup (no network, no pytest).

Run directly:  python tests/test_climate_projections.py
"""

import csv

from housing_label.data import climate_projections as cp
from housing_label.score.all_dimensions import score_climate
import pandas as pd


def test_resolved_county_has_bands_and_drivers():
    d = cp.climate_projection_for_county("47157")   # Shelby County, TN
    assert d["resolved"] is True
    assert "Shelby" in d["label"]
    # A concrete 0–100 headline (low band) plus a low/high band.
    assert 0 <= d["score"] <= 100
    assert d["score"] == d["score_low"]
    # Higher emissions → more hazard → never a higher score than the low band.
    assert d["score_high"] <= d["score_low"]
    # Three hazard legs and five raw drivers, each with hist/low/high.
    assert set(d["hazards"]) == {"heat", "precip", "drought"}
    assert set(d["drivers"]) >= {"heat_days95", "heat_days100", "drought_consecdd"}
    assert set(d["drivers"]["heat_days95"]) == {"hist", "low", "high"}


def test_hotter_county_scores_below_milder_county():
    # Memphis (hot, many >95°F days) should score worse than Boston (mild).
    memphis = cp.climate_projection_for_county("47157")["score"]
    boston = cp.climate_projection_for_county("25025")["score"]
    assert memphis < boston


def test_unmapped_and_none_fall_back_to_national_average():
    nat_low, nat_high = cp._national_average()
    for fips in ("99999", None):
        d = cp.climate_projection_for_county(fips)
        assert d["resolved"] is False
        assert d["label"] == cp.US_AVG_LABEL
        assert d["score"] == nat_low
        assert d["score_high"] == nat_high
        assert d["hazards"] == {} and d["drivers"] == {}


def test_score_monotonic_in_projected_heat():
    # The metric scorer must be non-increasing as projected hazard rises.
    xs = [0, 10, 30, 60, 100, 200]
    scores = [cp._metric_score("heat_days95", x) for x in xs]
    assert scores == sorted(scores, reverse=True)
    assert scores[0] == 100 and scores[-1] == 0


def test_crosswalk_integrity():
    rows = list(csv.DictReader(cp._CSV.open()))
    assert len(rows) >= 3000, "expected ~3233 counties"
    geoids = [r["geoid"] for r in rows]
    assert len(geoids) == len(set(geoids)), "duplicate county FIPS"
    for r in rows:
        assert len(r["geoid"]) == 5 and r["geoid"].isdigit()
        assert r["geo_level"] == "county"


def test_pipeline_scorer_maps_counties():
    # No county column → single-county pilot default (Shelby).
    out = score_climate(pd.DataFrame({"x": [1, 2]}))
    assert out.tolist() == [cp.climate_projection_for_county("47157")["score"]] * 2
    # With a county column → per-row mapping incl. national-average fallback.
    out = score_climate(pd.DataFrame({"county_fips": ["47157", "06037", "99999"]}))
    assert out.tolist() == [
        cp.climate_projection_for_county("47157")["score"],
        cp.climate_projection_for_county("06037")["score"],
        cp.climate_projection_for_county(None)["score"],
    ]


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} tests passed.")


if __name__ == "__main__":
    _run_all()
