#!/usr/bin/env python3
"""Offline tests for the Census-of-Governments infrastructure cost calibration:
the per-county multiplier lookup, the infra cost scaling, and the caveat wiring.

Runs without network access and without pytest — execute directly:
  python tests/test_govfinance.py
"""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from housing_label.data import govfinance as gf
from housing_label.data.govfinance import govfinance_for_county
from housing_label.enrich.infrastructure import enrich_row


def _approx(a, b, tol=1e-6):
    return abs(float(a) - float(b)) <= tol


# ── Bundled crosswalk + lookup ──────────────────────────────────────────────────
def test_crosswalk_present_with_shelby_and_national():
    table = gf._table()
    assert table, "govfinance crosswalk is empty/missing"
    assert "47157" in table                     # Shelby County, TN (the pilot)
    assert "00000" in table                     # national-average fallback row
    assert "06037" in table                     # Los Angeles County, CA


def test_shelby_is_unity():
    """Shelby County is 1.0 on every component by construction — the pilot is
    unchanged when the calibration layer is applied."""
    g = govfinance_for_county("47157")
    assert g["resolved"] == "county"
    for c in gf.COMPONENTS:
        assert _approx(g["multipliers"][c], 1.0), f"{c} != 1.0"


def test_la_differs_and_is_in_range():
    g = govfinance_for_county("06037")
    m = g["multipliers"]
    assert g["resolved"] == "county"
    assert m["roads"] > 1.5 and m["water_sewer"] > 2.0      # LA spends more per capita
    for c in gf.COMPONENTS:
        assert 0.25 <= m[c] <= 4.0                          # clamped range


def test_unmapped_and_none_fall_back_to_national():
    nat = govfinance_for_county(None)
    assert nat["resolved"] == "national" and nat["geo_level"] == "us"
    assert govfinance_for_county("99999")["resolved"] == "national"
    # National multipliers are also clamped and populated for all components.
    for c in gf.COMPONENTS:
        assert 0.25 <= nat["multipliers"][c] <= 4.0


def test_school_tax_share_with_dependent_fallback():
    """School-tax share is exposed; independent-district counties carry their real
    share, while dependent-school counties (type-5 ≈ 0) fall back to the national
    average rather than reading 0%."""
    nat = govfinance_for_county(None)["school_tax_share"]
    assert 0.30 <= nat <= 0.50                       # ~41% nationally
    dupage = govfinance_for_county("17043")["school_tax_share"]   # independent districts
    assert dupage > 0.6
    shelby = govfinance_for_county("47157")["school_tax_share"]   # dependent (TN)
    assert abs(shelby - nat) < 1e-6                  # fell back to national, not 0
    for fips in ("17043", "06037", "47157"):
        assert 0.0 <= govfinance_for_county(fips)["school_tax_share"] <= 0.75


# ── Infra cost scaling (enrich/infrastructure.py) ───────────────────────────────
_ROW = pd.Series({"CALC_ACRE": 0.25, "latitude": 35.13, "longitude": -89.99,
                  "RTOTAPR": 200000})


def test_multipliers_scale_components():
    """A county's multipliers scale each cost component by exactly that factor."""
    base = enrich_row(_ROW)                       # Shelby defaults (no multipliers)
    la = govfinance_for_county("06037")["multipliers"]
    scaled = enrich_row(_ROW, assess_ratio=1.0, tax_rate=0.011,
                        in_urban_area=True, cost_multipliers=la)
    # roads & water/sewer have no other multiplier, so the ratio is exactly the mult.
    assert _approx(scaled["infra_cost_roads"] / base["infra_cost_roads"], la["roads"], 1e-3)
    assert _approx(scaled["infra_cost_water_sewer"] / base["infra_cost_water_sewer"],
                   la["water_sewer"], 1e-3)
    assert scaled["est_annual_infra_cost"] != base["est_annual_infra_cost"]


def test_unity_multipliers_are_noop():
    """Shelby's all-1.0 multipliers reproduce the Memphis-default costs exactly."""
    base = enrich_row(_ROW)
    unity = enrich_row(_ROW, cost_multipliers=govfinance_for_county("47157")["multipliers"])
    for c in ("infra_cost_roads", "infra_cost_water_sewer", "infra_cost_fire",
              "infra_cost_police", "infra_cost_sanitation", "infra_cost_parks"):
        assert _approx(unity[c], base[c]), f"{c} changed under unity multipliers"


def test_missing_multiplier_key_defaults_to_one():
    """A partial multiplier dict leaves unspecified components unscaled."""
    base = enrich_row(_ROW)
    partial = enrich_row(_ROW, cost_multipliers={"roads": 2.0})
    # Ratio comparison (the costs are now continuous, not round integers, so
    # round-then-double ≠ double-then-round at the cent level).
    assert _approx(partial["infra_cost_roads"] / base["infra_cost_roads"], 2.0, 1e-3)
    assert _approx(partial["infra_cost_parks"], base["infra_cost_parks"])  # untouched


# ── Caveat wiring (house.py) ────────────────────────────────────────────────────
def test_caveat_reflects_local_calibration():
    from housing_label.simulate.house import _approx_caveats
    # A mapped non-Shelby county → "calibrated to this county's local-government spending".
    la_loc = SimpleNamespace(county_fips="06037", egrid_subregion="CAMX")
    la_caveats = " ".join(_approx_caveats(la_loc))
    assert "local-government spending" in la_caveats
    assert "national-average cost model" not in la_caveats

    # An unmapped county → the national-average caveat.
    loc = SimpleNamespace(county_fips="99999", egrid_subregion="CAMX")
    assert "national-average cost model" in " ".join(_approx_caveats(loc))


def test_caveat_missing_crosswalk_says_pilot_baseline():
    """When the crosswalk isn't bundled (resolved='none'), the caveat names the
    pilot cost-model baseline, not a national-average model."""
    import unittest.mock as mock
    from housing_label.simulate import house
    none_result = {"label": "x", "multipliers": {c: 1.0 for c in gf.COMPONENTS},
                   "resolved": "none", "geo_level": "us"}
    loc = SimpleNamespace(county_fips="06037", egrid_subregion="CAMX")
    with mock.patch("housing_label.data.govfinance.govfinance_for_county",
                    return_value=none_result):
        msg = " ".join(house._approx_caveats(loc))
    assert "pilot cost model" in msg
    assert "national-average cost model" not in msg


def test_multi_unit_caveat_fires_only_above_one_unit():
    """A dense-housing caveat appears when units > 1 and warns that Resilience and
    Durability use single-family assumptions; it stays absent for a single-family home."""
    from housing_label.simulate import house
    loc = SimpleNamespace(county_fips="06037", egrid_subregion="CAMX")

    assert not any("multi-unit" in c.lower() for c in house._approx_caveats(loc, 1))

    msg = " ".join(house._approx_caveats(loc, 4)).lower()
    assert "multi-unit" in msg
    assert "single-family" in msg
    # Still fires when the location can't be resolved.
    assert any("multi-unit" in c.lower() for c in house._approx_caveats(None, 2))


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} tests passed.")


if __name__ == "__main__":
    _run_all()
