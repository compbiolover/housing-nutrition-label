"""Tests for the FEMA NRI wildfire hazard: lookup, enrichment, resilience EAL,
and the live-path injection into the simulator."""

from __future__ import annotations

import sys
from argparse import Namespace

import pandas as pd
import pytest

from housing_label.data import wildfire as wf


# ── Bundled data + resolution-aware lookup ──────────────────────────────────────
def test_bundled_crosswalks_present_and_keyed():
    """County + tract crosswalks load and are keyed by zero-padded GEOID."""
    assert wf._table(), "county wildfire crosswalk is empty/missing"
    assert wf._tract_table(), "tract wildfire crosswalk is empty/missing"
    assert "47157" in wf._table()              # Shelby County, TN
    assert "06037" in wf._table()              # Los Angeles County, CA


def test_wildfire_discriminates_by_location():
    """A fire-prone county carries materially higher EAL than a low-risk one."""
    la = wf.wildfire_for_county("06037")
    memphis = wf.wildfire_for_county("47157")
    assert la["resolved"] and memphis["resolved"]
    assert la["eal_rate"] > memphis["eal_rate"] * 10
    assert la["geo_level"] == "county"
    assert "Very High" in (la["risk_rating"] or "")


def test_tract_resolution_and_county_fallback():
    """A known tract resolves at tract level; an unknown tract falls back to county."""
    t = wf.wildfire_for_tract("47157006300")   # a real Shelby tract
    assert t["geo_level"] == "tract" and t["resolved"]

    fallback = wf.wildfire_for_tract("06037999999")   # bogus tract in LA county
    assert fallback["geo_level"] == "county"
    assert fallback["eal_rate"] == wf.wildfire_for_county("06037")["eal_rate"]


def test_unknown_geo_falls_back_to_national_average():
    """An unmapped county / None resolves to the national-average fallback."""
    us = wf.wildfire_for_county(None)
    assert us["geo_level"] == "us" and us["resolved"] is False
    assert us["eal_rate"] == pytest.approx(wf._national_average())
    # A non-existent county FIPS also falls back to US.
    assert wf.wildfire_for_county("99999")["geo_level"] == "us"


# ── Pipeline enrichment (enrich/fire.py) ────────────────────────────────────────
def test_fire_enrichment_attaches_columns(tmp_path, monkeypatch):
    """enrich/fire.py adds the wildfire columns, resolving tract→county fallback."""
    from housing_label.enrich import fire as fire_enrich

    src = tmp_path / "env.csv"
    pd.DataFrame({
        "PARCELID": ["A", "B"],
        "census_tract": ["47157006300", None],   # one resolvable tract, one missing
        "latitude": [35.13, 35.13], "longitude": [-89.99, -89.99],
    }).to_csv(src, index=False)
    out = tmp_path / "fire.csv"

    monkeypatch.setattr(sys, "argv",
                        ["fire", "--input", str(src), "--output", str(out)])
    fire_enrich.main()

    df = pd.read_csv(out)
    for col in ("wildfire_eal_rate", "wildfire_risk_rating", "wildfire_geo_level"):
        assert col in df.columns
    assert df.loc[0, "wildfire_geo_level"] == "tract"      # resolved tract
    assert df.loc[1, "wildfire_geo_level"] == "county"     # county fallback (Shelby)
    assert (df["wildfire_eal_rate"] >= 0).all()


# ── Resilience scoring (score/resilience.py) ────────────────────────────────────
def _score(df: pd.DataFrame, tmp_path) -> pd.DataFrame:
    from housing_label.score import resilience
    src, out = tmp_path / "in.csv", tmp_path / "out.csv"
    df.to_csv(src, index=False)
    monkeypatch_argv = ["resilience", "--input", str(src), "--output", str(out)]
    import unittest.mock as m
    with m.patch.object(sys, "argv", monkeypatch_argv):
        resilience.main()
    return pd.read_csv(out)


_BASE_ROW = {
    "flood_risk": "minimal", "avg_tornadoes_per_yr_25mi": 1.0,
    "pga_2pct_50yr": 0.48, "pga_10pct_50yr": 0.19,
    "YRBLT": 1998, "EXTWALL": 1, "BSMT": 1, "COND": 3,
    "GRADE": "C", "SFLA": 2000, "RTOTAPR": 200000, "APRBLDG": 150000,
}


def test_resilience_includes_fire_term(tmp_path):
    """Fire is a real summed hazard: total = flood+tornado+seismic+fire, and the
    fire columns/score/grade are produced."""
    rows = [
        {**_BASE_ROW, "PARCELID": "LO", "wildfire_eal_rate": 0.000001},   # Memphis-like
        {**_BASE_ROW, "PARCELID": "HI", "wildfire_eal_rate": 0.0025},     # LA-like
    ]
    df = _score(pd.DataFrame(rows), tmp_path)

    for col in ("fire_eal_rate_raw", "fire_brm", "fire_eal_rate",
                "fire_eal_dollars", "fire_score", "fire_local_grade"):
        assert col in df.columns

    # total EAL is exactly the four-hazard sum.
    recomputed = (df["flood_eal_rate"] + df["tornado_eal_rate"]
                  + df["seismic_eal_rate"] + df["fire_eal_rate"])
    assert (df["total_eal_rate"] - recomputed).abs().max() < 1e-12

    # Higher wildfire → higher fire EAL → lower fire score.
    hi = df[df["PARCELID"] == "HI"].iloc[0]
    lo = df[df["PARCELID"] == "LO"].iloc[0]
    assert hi["fire_eal_rate"] > lo["fire_eal_rate"]
    assert hi["fire_score"] < lo["fire_score"]


def test_fire_brm_combustibility(tmp_path):
    """Non-combustible masonry + good condition + modern wiring lowers the fire
    BRM (and fire EAL) versus old combustible frame, at identical wildfire exposure."""
    rows = [
        {**_BASE_ROW, "PARCELID": "FRAME", "wildfire_eal_rate": 0.0025,
         "EXTWALL": 1, "YRBLT": 1945, "COND": 1},                 # frame, knob-and-tube, poor
        {**_BASE_ROW, "PARCELID": "BLOCK", "wildfire_eal_rate": 0.0025,
         "EXTWALL": 2, "YRBLT": 2015, "COND": 5},                 # block, modern, excellent
    ]
    df = _score(pd.DataFrame(rows), tmp_path)
    frame = df[df["PARCELID"] == "FRAME"].iloc[0]
    block = df[df["PARCELID"] == "BLOCK"].iloc[0]
    assert block["fire_brm"] < frame["fire_brm"]
    assert block["fire_eal_rate"] < frame["fire_eal_rate"]


def test_calc_fire_eal_handles_missing_wildfire_column():
    """A row with no wildfire column still yields the structural baseline (no crash)."""
    from housing_label.score.resilience import calc_fire_eal, STRUCTURAL_FIRE_EAL_BASE
    assert calc_fire_eal(pd.Series({"YRBLT": 1998})) == STRUCTURAL_FIRE_EAL_BASE
    assert calc_fire_eal(pd.Series({"wildfire_eal_rate": "bad"})) == STRUCTURAL_FIRE_EAL_BASE


# ── Live simulator path (house.py) ──────────────────────────────────────────────
_FIELDS = ["flood_zone", "year_built", "construction", "foundation",
           "condition", "value", "units", "sqft", "lot_acres"]


def _cfg(**over):
    from housing_label.simulate.house import resolve_config
    fields = {f: None for f in _FIELDS}
    fields.update(over)
    return resolve_config(Namespace(preset="baseline", lat=34.05, lon=-118.24, **fields))


def test_simulate_offline_default_is_structural_only():
    """Without a wildfire base, the fire peril is the structural baseline alone —
    simulate() stays offline-safe and unchanged for callers that omit it."""
    from housing_label.simulate.house import simulate, FIRE_EAL_BASE
    r = simulate(_cfg())
    assert r["wildfire_eal_base"] == 0.0
    # fire_raw == FIRE_EAL_BASE (structural only); fire_adj = raw × fire_brm.
    assert r["fire_raw"] == pytest.approx(FIRE_EAL_BASE)


def test_simulate_adds_location_wildfire():
    """A supplied wildfire base raises the fire peril and the total EAL."""
    from housing_label.simulate.house import simulate, FIRE_EAL_BASE
    base = simulate(_cfg())
    c = _cfg()
    c["wildfire_eal_base"] = 0.0025
    hot = simulate(c)
    assert hot["fire_raw"] == pytest.approx(FIRE_EAL_BASE + 0.0025)
    assert hot["fire_adj"] > base["fire_adj"]
    assert hot["total_eal"] > base["total_eal"]
