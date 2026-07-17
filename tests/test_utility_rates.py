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


def test_resolved_location_without_state_uses_us_average():
    """A Location that resolves but has no state_fips must use the US-average
    rates, not silently fall back to the Memphis/TVA pilot constants."""
    from argparse import Namespace
    from housing_label.simulate.house import resolve_config
    from housing_label.simulate.dimensions import (
        simulate_all_dimensions, build_parcel_row, _adjusted_energy,
    )
    from housing_label.simulate.location import Location
    from housing_label.data.utility_rates import US_AVG_ELEC_PER_KWH, US_AVG_GAS_PER_THERM

    fields = ["year_built", "construction", "foundation", "condition",
              "value", "units", "sqft", "lot_acres"]
    cfg = resolve_config(Namespace(preset="baseline", lat=34.0, lon=-118.0,
                                   flood_zone="X", **{f: None for f in fields}))
    loc = Location(lat=34.0, lon=-118.0)          # resolved but state_fips is None
    assert loc.state_fips is None

    label = simulate_all_dimensions(cfg, 50.0, location=loc, allow_network=False)
    got = label["metrics"]["est_monthly_energy_cost"]

    row = build_parcel_row(cfg)
    us_avg = _adjusted_energy(cfg, row, None, elec_rate=US_AVG_ELEC_PER_KWH,
                              gas_rate=US_AVG_GAS_PER_THERM)["est_monthly_energy_cost"]
    memphis = _adjusted_energy(cfg, row, None)["est_monthly_energy_cost"]
    assert got == us_avg              # used the US-average rates
    assert got != memphis             # not the pilot constants


if __name__ == "__main__":
    test_state_lookup_returns_local_rates()
    test_unknown_state_falls_back_to_us_average()
    test_energy_cost_scales_with_rate()
    test_resolved_location_without_state_uses_us_average()
    print("utility-rate tests passed")
