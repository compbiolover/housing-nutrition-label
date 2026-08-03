#!/usr/bin/env python3
"""Offline tests for the infrastructure cost curve (continuous, density-extended).

Runs without network access and without pytest — execute directly:
  python tests/test_infrastructure.py
"""

import pandas as pd

from housing_label.enrich.infrastructure import (
    interp_cost, enrich_row,
    ROAD_COST_BY_DENSITY, WATER_SEWER_COST_BY_DENSITY,
    WATER_LEG_SHARE, SEWER_LEG_SHARE,
)


def test_interp_cost_anchors_and_clamp():
    """interp_cost returns anchor values at anchor densities and clamps outside."""
    for d, c in ROAD_COST_BY_DENSITY:
        assert abs(interp_cost(d, ROAD_COST_BY_DENSITY) - c) < 1e-6
    lo_d, lo_c = ROAD_COST_BY_DENSITY[0]
    hi_d, hi_c = ROAD_COST_BY_DENSITY[-1]
    assert interp_cost(lo_d / 10, ROAD_COST_BY_DENSITY) == lo_c   # clamp low
    assert interp_cost(hi_d * 10, ROAD_COST_BY_DENSITY) == hi_c   # clamp high


def test_interp_cost_monotonic_decreasing():
    """Per-household linear-infra cost falls monotonically with density."""
    for anchors in (ROAD_COST_BY_DENSITY, WATER_SEWER_COST_BY_DENSITY):
        prev = float("inf")
        for du in (1, 2, 4, 8, 12, 16, 24, 32, 48, 64):
            c = interp_cost(du, anchors)
            assert c <= prev + 1e-9, f"cost rose at {du} DU/acre"
            prev = c


def test_cost_curve_does_not_floor_at_12():
    """Regression: the curve keeps declining past 12 DU/acre (it used to floor),
    so a quadplex-density parcel costs less to serve than a triplex-density one."""
    assert interp_cost(16, ROAD_COST_BY_DENSITY) < interp_cost(12, ROAD_COST_BY_DENSITY)
    assert interp_cost(48, ROAD_COST_BY_DENSITY) < interp_cost(16, ROAD_COST_BY_DENSITY)


def test_enrich_row_per_unit_cost_falls_with_density():
    """At a fixed lot, the modeled per-unit infra cost falls as units increase,
    with no flooring between a triplex and a quadplex."""
    lot, value, rate = 0.25, 250_000.0, 0.0319 * 0.25
    costs = []
    for units in (1, 2, 3, 4, 8):
        row = pd.Series({"CALC_ACRE": lot / units, "latitude": None,
                         "longitude": None, "RTOTAPR": value})
        out = enrich_row(row, assess_ratio=1.0, tax_rate=rate, in_urban_area=True)
        costs.append(out["est_annual_infra_cost"])
    assert all(b < a for a, b in zip(costs, costs[1:])), f"not strictly falling: {costs}"


def _total(units, lot=0.25, value=150_000.0):
    row = pd.Series({"CALC_ACRE": lot / units, "latitude": None,
                     "longitude": None, "RTOTAPR": value})
    return enrich_row(row, in_urban_area=True)


def test_density_credit_extends_past_16_du_acre():
    """Regression: a high-rise-density parcel costs less to serve per unit than a
    mid-rise one. The credit used to saturate ~16 DU/acre, so a 157-unit tower was
    billed like a quadplex; now it keeps falling to the per-capita floor."""
    c4 = _total(4)["est_annual_infra_cost"]      # 16 DU/acre
    c16 = _total(16)["est_annual_infra_cost"]    # 64 DU/acre
    c48 = _total(48)["est_annual_infra_cost"]    # 192 DU/acre
    c157 = _total(157)["est_annual_infra_cost"]  # 628 DU/acre
    assert c16 < c4 and c48 < c16                # keeps declining past a quadplex
    assert c157 <= c48 + 1e-9                    # flattens at the per-capita floor
    assert c157 < c4 * 0.85                      # a tower is materially cheaper than a fourplex


def test_fire_and_sanitation_amortize_with_density():
    """Fire and sanitation — once flat per household — now share across a dense
    building, flooring at their per-capita residual. Parks stays flat (per-capita)."""
    assert _total(157)["infra_cost_fire"] < _total(1)["infra_cost_fire"]
    assert _total(157)["infra_cost_sanitation"] < _total(1)["infra_cost_sanitation"]
    assert _total(157)["infra_cost_parks"] == _total(1)["infra_cost_parks"]


# ── On-site water / sewer (private well, septic field) ────────────────────────
def _connections(**kw):
    """One rural parcel scored with the given public_water/public_sewer flags."""
    row = pd.Series({"CALC_ACRE": 10.0, "latitude": None, "longitude": None,
                     "RTOTAPR": 250_000.0})
    return enrich_row(row, assess_ratio=1.0, tax_rate=0.008, in_urban_area=False, **kw)


def test_leg_shares_sum_to_one():
    """The two legs partition the water/sewer component — a fully connected parcel
    must be charged exactly what it was before the split existed."""
    assert abs((WATER_LEG_SHARE + SEWER_LEG_SHARE) - 1.0) < 1e-9


def test_public_connections_are_the_default():
    """Omitting the flags must score identically to stating both are public, so an
    unknown water source never quietly discounts a parcel's cost to serve."""
    a, b = _connections(), _connections(public_water=True, public_sewer=True)
    assert a["est_annual_infra_cost"] == b["est_annual_infra_cost"]
    assert a["infra_cost_water_sewer"] > 0


def test_well_and_septic_drop_the_whole_public_leg():
    """A parcel on a private well and a septic field receives no public water or
    sewer service, so it is charged none of that cost."""
    off = _connections(public_water=False, public_sewer=False)
    assert off["infra_cost_water_sewer"] == 0.0
    on = _connections()
    assert off["est_annual_infra_cost"] < on["est_annual_infra_cost"]


def test_one_leg_off_charges_the_other():
    """The legs are independent: a private well with a public sewer connection is
    still charged the sewer half (and vice versa)."""
    full = _connections()["infra_cost_water_sewer"]
    well_only = _connections(public_water=False)["infra_cost_water_sewer"]
    septic_only = _connections(public_sewer=False)["infra_cost_water_sewer"]
    assert abs(well_only - full * SEWER_LEG_SHARE) < 0.01
    assert abs(septic_only - full * WATER_LEG_SHARE) < 0.01


def test_dropping_a_leg_drops_its_fee_revenue_too():
    """Water/sewer is ~100% fee-recovered, so a leg the parcel isn't connected to
    must leave the REVENUE side as well. Crediting a rural home with utility fees it
    never pays would inflate its fiscal ratio on the strength of a service it does
    not receive — so the ratio is expected to FALL, not rise."""
    on, off = _connections(), _connections(public_water=False, public_sewer=False)
    assert off["est_fee_revenue"] < on["est_fee_revenue"]
    assert off["est_property_tax"] == on["est_property_tax"]   # tax side untouched
    assert off["fiscal_ratio"] < on["fiscal_ratio"]


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} tests passed.")


if __name__ == "__main__":
    _run_all()
