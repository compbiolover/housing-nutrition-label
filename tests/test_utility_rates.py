#!/usr/bin/env python3
"""Tests for the state utility-rate lookup and its effect on energy cost.

Runs without network. Execute directly (python tests/test_utility_rates.py) or
via pytest.
"""

import pandas as pd

from housing_label.data.utility_rates import (
    utility_rates_for_state, US_AVG_ELEC_PER_KWH, US_AVG_GAS_PER_THERM,
)
from housing_label.enrich.energy import model_parcel_energy


def test_state_lookup_returns_local_rates():
    tn = utility_rates_for_state("47")
    ca = utility_rates_for_state("06")
    assert tn["elec_per_kwh"] != ca["elec_per_kwh"]           # rates differ by state
    assert ca["elec_per_kwh"] > tn["elec_per_kwh"]            # CA pricier than TN
    assert "TN" in tn["label"] and "CA" in ca["label"]
    # accepts an unpadded FIPS ("6" → "06")
    assert utility_rates_for_state("6") == ca


def test_unknown_state_falls_back_to_us_average():
    for bad in (None, "", "99"):
        r = utility_rates_for_state(bad)
        assert r["elec_per_kwh"] == US_AVG_ELEC_PER_KWH
        assert r["gas_per_therm"] == US_AVG_GAS_PER_THERM
        assert r["label"] == "US average (EIA)"


def test_energy_cost_scales_with_rate():
    row = pd.Series({"YRBLT": 2000, "SFLA": 2000, "EXTWALL": None,
                     "BSMT": None, "HEAT": None, "FUEL": None})
    tn = utility_rates_for_state("47")
    ca = utility_rates_for_state("06")
    tn_cost = model_parcel_energy(row, elec_rate=tn["elec_per_kwh"],
                                  gas_rate=tn["gas_per_therm"])["est_monthly_energy_cost"]
    ca_cost = model_parcel_energy(row, elec_rate=ca["elec_per_kwh"],
                                  gas_rate=ca["gas_per_therm"])["est_monthly_energy_cost"]
    # Same building, only the rates differ → CA materially pricier than TN.
    assert ca_cost > tn_cost * 1.4


def test_resilience_local_grade_gated_to_shelby():
    """The Shelby-dataset local grade is computed only when local_compare=True,
    so an off-Shelby address never gets a Shelby-relative rank."""
    import tempfile, os, pathlib
    from argparse import Namespace
    from housing_label.simulate import house
    from housing_label.simulate.house import resolve_config, simulate

    fields = ["year_built", "construction", "foundation", "condition",
              "value", "units", "sqft", "lot_acres"]
    args = Namespace(preset="baseline", lat=34.05, lon=-118.24, flood_zone="X",
                     **{f: None for f in fields})
    cfg = resolve_config(args)

    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as fh:
        fh.write("resilience_score\n10\n50\n90\n")
        tmp = fh.name
    orig = house.SCORED_CSV
    try:
        house.SCORED_CSV = pathlib.Path(tmp)
        # Off-Shelby: gate off → N/A even though the dataset exists.
        assert simulate(cfg, local_compare=False)["local_grade"] == "N/A"
        # Gate on → a real percentile grade is produced.
        assert simulate(cfg, local_compare=True)["local_grade"] != "N/A"
    finally:
        house.SCORED_CSV = orig
        os.unlink(tmp)

    # An empty dataset (header only, no scores) must not divide-by-zero → N/A.
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as fh:
        fh.write("resilience_score\n")
        empty = fh.name
    try:
        house.SCORED_CSV = pathlib.Path(empty)
        assert simulate(cfg, local_compare=True)["local_grade"] == "N/A"
    finally:
        house.SCORED_CSV = orig
        os.unlink(empty)


if __name__ == "__main__":
    test_state_lookup_returns_local_rates()
    test_unknown_state_falls_back_to_us_average()
    test_energy_cost_scales_with_rate()
    test_resilience_local_grade_gated_to_shelby()
    print("utility-rate tests passed")
