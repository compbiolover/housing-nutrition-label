#!/usr/bin/env python3
"""Offline tests for the FEMA NRI tornado hazard: lookup, enrichment, resilience
EAL, and the live-path injection into the simulator.

These cover the consolidation that retires the NOAA SPC touchdown-count model in
favour of the FEMA National Risk Index tornado EAL rate (mirroring the wildfire
consolidation). Runs without network access. This file alone:
  pytest tests/test_tornado.py
"""

from __future__ import annotations

from argparse import Namespace

import pandas as pd

from housing_label.data import tornado as td


def _approx(a: float, b: float, tol: float = 1e-9) -> bool:
    return abs(float(a) - float(b)) <= tol


# ── Bundled data + resolution-aware lookup ──────────────────────────────────────
def test_bundled_crosswalks_present_and_keyed():
    """County + tract crosswalks load and are keyed by zero-padded GEOID."""
    assert td._table(), "county tornado crosswalk is empty/missing"
    assert td._tract_table(), "tract tornado crosswalk is empty/missing"
    assert "47157" in td._table()              # Shelby County, TN
    assert "40109" in td._table()              # Oklahoma County, OK


def test_tornado_discriminates_by_location():
    """A Plains 'tornado alley' county carries materially higher EAL than a
    low-risk West-coast one — the whole reason for retiring the SPC model, which
    applied one TN/Mid-South EF distribution nationally."""
    oklahoma = td.tornado_for_county("40109")   # Oklahoma County, OK
    los_angeles = td.tornado_for_county("06037")  # Los Angeles County, CA
    assert oklahoma["resolved"] and los_angeles["resolved"]
    assert oklahoma["eal_rate"] > los_angeles["eal_rate"] * 10
    assert oklahoma["geo_level"] == "county"


def test_shelby_resolves_and_is_rated():
    """Shelby County resolves at county level with a positive EAL + qualitative rating."""
    memphis = td.tornado_for_county("47157")
    assert memphis["resolved"] and memphis["geo_level"] == "county"
    assert memphis["eal_rate"] > 0
    assert memphis["risk_rating"]


def test_tract_resolution_and_county_fallback():
    """A known tract resolves at tract level; an unknown tract falls back to county."""
    t = td.tornado_for_tract("47157006300")   # a real Shelby tract
    assert t["geo_level"] == "tract" and t["resolved"]

    fallback = td.tornado_for_tract("47157999999")   # bogus tract in Shelby county
    assert fallback["geo_level"] == "county"
    assert fallback["eal_rate"] == td.tornado_for_county("47157")["eal_rate"]


def test_unknown_geo_falls_back_to_national_average():
    """An unmapped county / None resolves to the national-average fallback."""
    us = td.tornado_for_county(None)
    assert us["geo_level"] == "us" and us["resolved"] is False
    assert _approx(us["eal_rate"], td._national_average())
    # A non-existent county FIPS also falls back to US.
    assert td.tornado_for_county("99999")["geo_level"] == "us"



# ── Resilience scoring (score/resilience.py) ────────────────────────────────────
def test_calc_tornado_eal_reads_nri_rate():
    """calc_tornado_eal returns the clean NRI rate, 0.0 for missing/garbage/negative."""
    from housing_label.score.resilience import calc_tornado_eal
    assert calc_tornado_eal(pd.Series({"tornado_nri_eal_rate": 0.00015})) == 0.00015
    assert calc_tornado_eal(pd.Series({"YRBLT": 1998})) == 0.0            # column absent
    assert calc_tornado_eal(pd.Series({"tornado_nri_eal_rate": "bad"})) == 0.0
    assert calc_tornado_eal(pd.Series({"tornado_nri_eal_rate": -1.0})) == 0.0


_BASE_ROW = {
    "flood_risk": "minimal", "pga_2pct_50yr": 0.48, "pga_10pct_50yr": 0.19,
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

def test_resilience_tornado_term_tracks_nri_rate():
    """Higher NRI tornado rate → higher tornado EAL and lower tornado score; the
    total EAL is still the exact sum of the four perils."""
    lo = _legs({**_BASE_ROW, "tornado_nri_eal_rate": 7.6e-6})   # LA-like
    hi = _legs({**_BASE_ROW, "tornado_nri_eal_rate": 2.4e-4})   # Plains-like

    for legs in (lo, hi):
        recomputed = (legs["flood_eal_rate"] + legs["tornado_eal_rate"]
                      + legs["seismic_eal_rate"] + legs["fire_eal_rate"])
        assert abs(legs["total_eal_rate"] - recomputed) < 1e-12

    assert hi["tornado_eal_rate"] > lo["tornado_eal_rate"]
    assert hi["tornado_score"] <= lo["tornado_score"]


# ── Live simulator path (house.py) ──────────────────────────────────────────────
_FIELDS = ["flood_zone", "year_built", "construction", "foundation",
           "condition", "value", "units", "sqft", "lot_acres"]


def _cfg(**over):
    from housing_label.simulate.house import resolve_config
    fields = {f: None for f in _FIELDS}
    fields.update(over)
    return resolve_config(Namespace(preset="baseline", lat=35.15, lon=-89.98, **fields))


def test_simulate_offline_default_has_no_tornado_base():
    """Without a tornado base, the tornado peril is zero — simulate() stays
    offline-safe and unchanged for callers that omit it."""
    from housing_label.simulate.house import simulate
    r = simulate(_cfg())
    assert r["tornado_eal_base"] == 0.0
    assert _approx(r["tornado_raw"], 0.0)


def test_simulate_adds_location_tornado():
    """A supplied tornado base raises the tornado peril and the total EAL."""
    from housing_label.simulate.house import simulate
    base = simulate(_cfg())
    c = _cfg()
    c["tornado_eal_base"] = 2.4e-4
    windy = simulate(c)
    assert _approx(windy["tornado_raw"], 2.4e-4)
    assert windy["tornado_adj"] > base["tornado_adj"]
    assert windy["total_eal"] > base["total_eal"]


def test_simulate_coerces_invalid_tornado_base():
    """A non-numeric tornado base (e.g. from JSON/CLI) is ignored, not fatal."""
    from housing_label.simulate.house import simulate
    c = _cfg()
    c["tornado_eal_base"] = "not-a-number"
    r = simulate(c)
    assert _approx(r["tornado_raw"], 0.0)
