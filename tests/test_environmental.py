#!/usr/bin/env python3
"""Tests for the Environmental Footprint dimension (enrich/environmental.py).

Pure functions over a synthetic parcel ``pd.Series`` — no network, no CSV.
Execute directly (python tests/test_environmental.py) or via pytest.
"""

from __future__ import annotations

import pandas as pd

from housing_label.enrich import environmental as E


def _row(**kw) -> pd.Series:
    base = {"SFLA": 2000, "est_annual_kwh": 12000, "est_annual_therms": 500,
            "EXTWALL": 7, "GRADE": 40, "RMBED": 3, "FIXBATH": 2,
            "STORIES": 1, "CALC_ACRE": 0.25, "acre_outlier": False}
    base.update(kw)
    return pd.Series(base)


def test_embodied_intensity_wall_and_grade():
    # A higher construction grade raises embodied intensity; a lower grade lowers it.
    mid = E.embodied_intensity(7, E.GRADE_MIDPOINT)
    hi = E.embodied_intensity(7, 70)
    lo = E.embodied_intensity(7, 15)
    assert lo < mid < hi
    # Unknown wall / missing grade fall back to the defaults (no crash).
    assert E.embodied_intensity(None, None) == E.EC_INTENSITY_DEFAULT


def test_service_life_defaults():
    assert E.service_life_years(None) == E.DEFAULT_SERVICE_LIFE_YR
    assert E.service_life_years(9999) == E.DEFAULT_SERVICE_LIFE_YR   # unknown code


def test_water_use_multifamily_drops_outdoor():
    args = (3, 2, 2000, 1, 0.25, False)   # rmbed, fixbath, sfla, stories, acre, outlier
    sf_water, sf_occ = E.water_use_gal_yr(*args, is_multifamily=False)
    mf_water, mf_occ = E.water_use_gal_yr(*args, is_multifamily=True)
    # Same indoor occupancy, but the single-family case adds private-yard irrigation.
    assert sf_occ == mf_occ
    assert sf_water > mf_water


def test_water_use_more_bedrooms_more_indoor():
    small, _ = E.water_use_gal_yr(1, 2, 1200, 1, 0.0, False)   # no lot → indoor only
    large, _ = E.water_use_gal_yr(5, 2, 1200, 1, 0.0, False)
    assert large > small


def test_model_parcel_environment_unscored_without_living_area():
    out = E.model_parcel_environment(_row(SFLA=0))
    assert all(v is None for v in out.values())
    out2 = E.model_parcel_environment(_row(SFLA=None))
    assert all(v is None for v in out2.values())


def test_model_parcel_environment_composite_is_weighted_blend():
    out = E.model_parcel_environment(_row())
    expected = (E.W_OPERATIONAL * out["env_operational_subscore"]
                + E.W_EMBODIED * out["env_embodied_subscore"]
                + E.W_WATER * out["env_water_subscore"])
    assert abs(out["environmental_score"] - round(expected, 1)) <= 0.1
    assert 0.0 <= out["environmental_score"] <= 100.0


def test_model_parcel_environment_cleaner_grid_scores_better():
    """A lower grid-carbon factor lowers operational CO2e and raises the score."""
    dirty = E.model_parcel_environment(_row(), grid_factor=0.7)
    clean = E.model_parcel_environment(_row(), grid_factor=0.1)
    assert clean["env_operational_co2e_kg_yr"] < dirty["env_operational_co2e_kg_yr"]
    assert clean["environmental_score"] >= dirty["environmental_score"]


def test_marginal_reduces_to_average_when_equal_or_absent():
    """The marginal-rate credit must vanish when marginal == average, and when no
    marginal factor is supplied — so the operational leg equals today's
    consumed × average regardless of how many kWh are 'avoided'."""
    today = E.model_parcel_environment(_row(), grid_factor=0.4097)
    # Marginal == average, with a large avoided quantity: credit term is zero.
    equal = E.model_parcel_environment(_row(), grid_factor=0.4097,
                                       grid_marginal_factor=0.4097, avoided_kwh=5000)
    # No marginal factor at all, same avoided quantity: falls back to the average.
    absent = E.model_parcel_environment(_row(), grid_factor=0.4097,
                                        grid_marginal_factor=None, avoided_kwh=5000)
    assert equal["env_operational_co2e_kg_yr"] == today["env_operational_co2e_kg_yr"]
    assert absent["env_operational_co2e_kg_yr"] == today["env_operational_co2e_kg_yr"]
    assert equal["environmental_score"] == today["environmental_score"]
    assert absent["environmental_score"] == today["environmental_score"]
    # A zero credit (marginal == average) must NOT name Cambium in the citation —
    # the credit term is zero, so the number came from the eGRID average alone.
    assert "Cambium" not in equal["env_data_source"]
    assert "Cambium" not in absent["env_data_source"]


def test_marginal_credit_matches_formula():
    """operational == consumed·avg + avoided·(avg − marginal) + therms·EF_GAS."""
    avg, marg, avoided = 0.4097, 0.2362, 3000.0
    out = E.model_parcel_environment(_row(), grid_factor=avg,
                                     grid_marginal_factor=marg, avoided_kwh=avoided)
    expect = 12000 * avg + avoided * (avg - marg) + 500 * E.EF_GAS_KG_PER_THERM
    assert abs(out["env_operational_co2e_kg_yr"] - round(expect, 1)) <= 0.1
    # marginal below average → avoided kWh credited less than an average-rate
    # credit would, so operational is higher than valuing the whole home at avg.
    avg_only = E.model_parcel_environment(_row(), grid_factor=avg)
    assert out["env_operational_co2e_kg_yr"] > avg_only["env_operational_co2e_kg_yr"]
    assert "Cambium" in out["env_data_source"]


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} tests passed.")


if __name__ == "__main__":
    _run_all()
