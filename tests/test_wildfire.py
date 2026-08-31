#!/usr/bin/env python3
"""Offline tests for the FEMA NRI wildfire hazard: lookup, enrichment, resilience
EAL, and the live-path injection into the simulator.

Runs without network access. This file alone:
  pytest tests/test_wildfire.py
"""

from __future__ import annotations

from argparse import Namespace

import pandas as pd

from housing_label.data import wildfire as wf


def _approx(a: float, b: float, tol: float = 1e-9) -> bool:
    return abs(float(a) - float(b)) <= tol


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
    assert _approx(us["eal_rate"], wf._national_average())
    # A non-existent county FIPS also falls back to US.
    assert wf.wildfire_for_county("99999")["geo_level"] == "us"


# ── Resilience scoring (score/resilience.py) ────────────────────────────────────
_BASE_ROW = {
    "flood_risk": "minimal", "tornado_nri_eal_rate": 0.00015,
    "pga_2pct_50yr": 0.48, "pga_10pct_50yr": 0.19,
    "YRBLT": 1998, "EXTWALL": 1, "BSMT": 1, "COND": 3,
    "GRADE": "C", "SFLA": 2000, "RTOTAPR": 200000, "APRBLDG": 150000,
}


def _legs(row: dict) -> dict:
    """The four raw EAL legs, their BRM-adjusted rates and scores, for one row.

    This used to run score/resilience.py's CLI over a temp CSV. That batch scorer
    is gone; the scalar functions it wrapped are the ones the live label path
    uses, so these assertions now exercise those directly.
    """
    from housing_label.score.resilience import (
        calc_brm_row, calc_fire_eal, calc_flood_eal, calc_seismic_eal,
        calc_tornado_eal, eal_rate_to_score,
    )
    brm = calc_brm_row(row)
    raw = {"flood": calc_flood_eal(row), "tornado": calc_tornado_eal(row),
           "seismic": calc_seismic_eal(row), "fire": calc_fire_eal(row)}
    adj = {"flood": raw["flood"] * brm["flood_brm"],
           "tornado": raw["tornado"] * brm["wind_seismic_brm"],
           "seismic": raw["seismic"] * brm["wind_seismic_brm"],
           "fire": raw["fire"] * brm["fire_brm"]}
    out = {f"{k}_eal_rate_raw": v for k, v in raw.items()}
    out |= {f"{k}_eal_rate": v for k, v in adj.items()}
    out |= {f"{k}_score": eal_rate_to_score(v) for k, v in adj.items()}
    out |= brm
    out["total_eal_rate"] = sum(adj.values())
    return out

def test_resilience_includes_fire_term():
    """Fire is a real summed hazard: total = flood+tornado+seismic+fire, and the
    fire columns/score/grade are produced. Higher wildfire → lower fire score."""
    lo = _legs({**_BASE_ROW, "wildfire_eal_rate": 0.000001})   # Memphis-like
    hi = _legs({**_BASE_ROW, "wildfire_eal_rate": 0.0025})     # LA-like

    for legs in (lo, hi):
        recomputed = (legs["flood_eal_rate"] + legs["tornado_eal_rate"]
                      + legs["seismic_eal_rate"] + legs["fire_eal_rate"])
        assert abs(legs["total_eal_rate"] - recomputed) < 1e-12

    assert hi["fire_eal_rate"] > lo["fire_eal_rate"]
    assert hi["fire_score"] < lo["fire_score"]


def test_fire_brm_combustibility():
    """Non-combustible masonry + good condition + modern wiring lowers the fire
    BRM (and fire EAL) vs old combustible frame, at identical wildfire exposure."""
    frame = _legs({**_BASE_ROW, "wildfire_eal_rate": 0.0025,
                   "EXTWALL": 1, "YRBLT": 1945, "COND": 1})   # knob-and-tube, poor
    block = _legs({**_BASE_ROW, "wildfire_eal_rate": 0.0025,
                   "EXTWALL": 2, "YRBLT": 2015, "COND": 5})   # block, modern, excellent
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
    assert _approx(r["fire_raw"], FIRE_EAL_BASE)


def test_simulate_adds_location_wildfire():
    """A supplied wildfire base raises the fire peril and the total EAL."""
    from housing_label.simulate.house import simulate, FIRE_EAL_BASE
    base = simulate(_cfg())
    c = _cfg()
    c["wildfire_eal_base"] = 0.0025
    hot = simulate(c)
    assert _approx(hot["fire_raw"], FIRE_EAL_BASE + 0.0025)
    assert hot["fire_adj"] > base["fire_adj"]
    assert hot["total_eal"] > base["total_eal"]


def test_simulate_coerces_invalid_wildfire_base():
    """A non-numeric wildfire base (e.g. from JSON/CLI) is ignored, not fatal."""
    from housing_label.simulate.house import simulate, FIRE_EAL_BASE
    c = _cfg()
    c["wildfire_eal_base"] = "not-a-number"
    r = simulate(c)
    assert _approx(r["fire_raw"], FIRE_EAL_BASE)
