#!/usr/bin/env python3
"""Offline tests for the shared state-code crosswalk (data/states.py).

Runs without network access. This file alone:
  pytest tests/test_states.py
"""

from __future__ import annotations

from housing_label.data.states import (
    CENSUS_DIVISION, SCORED_JURISDICTIONS, STATE_FIPS_TO_USPS, USPS_TO_STATE_FIPS,
    division_for_usps, fips_for_usps, normalize_state_fips, usps_for_fips,
)
from housing_label.data.utility_rates import _STATE_RATES


def test_table_shape():
    """50 states + DC + PR in the mapping; 50 + DC eligible to carry a rule."""
    assert len(STATE_FIPS_TO_USPS) == 52
    assert len(USPS_TO_STATE_FIPS) == 52, "a duplicate USPS code would silently collapse"
    assert len(SCORED_JURISDICTIONS) == 51
    assert "PR" in STATE_FIPS_TO_USPS.values()
    assert "PR" not in SCORED_JURISDICTIONS
    # The four small territories are absent from every fiscal crosswalk in this repo,
    # so including them here would imply coverage that does not exist.
    for absent in ("60", "66", "69", "78"):
        assert absent not in STATE_FIPS_TO_USPS


def test_round_trip():
    for fips, usps in STATE_FIPS_TO_USPS.items():
        assert fips_for_usps(usps) == fips
        assert usps_for_fips(fips) == usps


def test_county_fips_resolves_to_its_state():
    """A 5-digit county code works directly — callers needn't slice it."""
    assert usps_for_fips("47157") == "TN"      # Shelby County, the pilot
    assert usps_for_fips("06037") == "CA"      # Los Angeles County
    assert usps_for_fips("11001") == "DC"      # District of Columbia


def test_messy_input_normalizes():
    """Mirrors region_context.normalize_fips: CSV cells and geocoders are untidy."""
    assert normalize_state_fips(6) == "06"
    assert normalize_state_fips(6.0) == "06"           # float-parsed CSV lost the zero
    assert normalize_state_fips("47.0") == "47"
    assert normalize_state_fips(" 47 ") == "47"
    assert usps_for_fips(6.0) == "CA"
    assert fips_for_usps("tn") == "47"                 # case-insensitive
    for empty in (None, "", "  ", float("nan"), "nan"):
        assert normalize_state_fips(empty) is None
        assert usps_for_fips(empty) is None
    assert fips_for_usps("ZZ") is None
    assert usps_for_fips("99") is None


def test_census_divisions_partition_the_scored_set():
    """Every scored jurisdiction sits in exactly one of the nine divisions.

    This is what makes the regional rollout sequence provably exhaustive: the phases are
    defined by division, so a jurisdiction missing here would be silently skipped.
    """
    assert set(CENSUS_DIVISION) == SCORED_JURISDICTIONS
    assert len(set(CENSUS_DIVISION.values())) == 9
    assert division_for_usps("TN") == "East South Central"
    assert division_for_usps("DC") == "South Atlantic"      # Census groups DC here
    assert division_for_usps("PR") is None                  # territories have no division


def test_utility_rates_postal_codes_agree():
    """data/utility_rates.py embeds the same FIPS→USPS pairs in its value tuples.

    Asserting they agree means a typo in either table is caught for free, which is why
    that one is left as-is rather than refactored to import from here — retyping 51 rows
    of rate data to remove a duplicate mapping would risk more than it saves.
    """
    for fips, (postal, _elec, _gas) in _STATE_RATES.items():
        assert STATE_FIPS_TO_USPS[fips] == postal, f"{fips}: {postal} vs table"
    # EIA publishes the 50 states + DC only, so it is the mapping minus Puerto Rico.
    assert set(_STATE_RATES) == set(STATE_FIPS_TO_USPS) - {"72"}
