#!/usr/bin/env python3
"""Offline tests for the infrastructure cost curve (continuous, density-extended).

Runs without network access and without pytest — execute directly:
  python tests/test_infrastructure.py
"""

import pandas as pd

from housing_label.enrich.infrastructure import (
    interp_cost, enrich_row,
    ROAD_COST_BY_DENSITY, WATER_SEWER_COST_BY_DENSITY,
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


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} tests passed.")


if __name__ == "__main__":
    _run_all()
