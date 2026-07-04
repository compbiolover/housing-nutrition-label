#!/usr/bin/env python3
"""Offline tests for the dense-housing value-per-door lookup.

Runs without network access and without pytest — execute directly:
  python tests/test_multifamily_value.py
"""

from __future__ import annotations

from housing_label.data import multifamily_value as mv
from housing_label.data.multifamily_value import (
    value_from_rent, value_per_door_for_county, CAP_RATE, OCCUPANCY, OPEX_RATIO,
)


def _approx(a, b, tol=1.0):
    return abs(float(a) - float(b)) <= tol


# ── Bundled rent crosswalk ──────────────────────────────────────────────────────
def test_rent_crosswalk_present():
    table = mv._table()
    assert table, "rent crosswalk is empty/missing"
    assert "00000" in table                      # national fallback row
    assert "47157" in table                      # Shelby County, TN
    assert "06037" in table                      # Los Angeles County, CA


# ── The income / cap-rate formula ───────────────────────────────────────────────
def test_value_from_rent_matches_income_method():
    """value_per_door = annual rent × occupancy × (1 − opex) / cap_rate."""
    rent = 1500.0
    expected = rent * 12 * OCCUPANCY * (1 - OPEX_RATIO) / CAP_RATE
    assert _approx(value_from_rent(rent), expected)


def test_value_rises_with_rent():
    assert value_from_rent(2000) > value_from_rent(1000)


def test_lower_cap_rate_raises_value():
    """A lower cap rate (hotter market) implies a higher value for the same rent."""
    assert value_from_rent(1500, cap_rate=0.045) > value_from_rent(1500, cap_rate=0.065)


def test_value_floor_guards_tiny_rents():
    assert value_from_rent(1.0) == mv.VALUE_FLOOR


def test_nonpositive_cap_rate_does_not_crash():
    """A zero/negative cap rate falls back to the default instead of dividing by zero."""
    assert value_from_rent(1500, cap_rate=0) == value_from_rent(1500)
    assert value_from_rent(1500, cap_rate=-0.05) == value_from_rent(1500)


# ── County resolution ───────────────────────────────────────────────────────────
def test_mapped_county_resolves_local():
    la = value_per_door_for_county("06037")
    assert la["resolved"] == "county"
    assert la["geo_level"] == "county"
    assert la["value_per_door"] > 0
    # LA rents exceed the national median → LA value-per-door exceeds the national.
    assert la["value_per_door"] > value_per_door_for_county(None)["value_per_door"]


def test_unmapped_and_none_fall_back_to_national():
    nat = value_per_door_for_county(None)
    assert nat["resolved"] == "national" and nat["geo_level"] == "us"
    assert value_per_door_for_county("99999")["resolved"] == "national"
    assert nat["value_per_door"] > 0


def test_monthly_rent_override_is_the_hud_seam():
    """An explicit rent (e.g. a HUD FMR) overrides the bundled ACS lookup."""
    base = value_per_door_for_county("47157")
    hi = value_per_door_for_county("47157", monthly_rent=base["monthly_rent"] * 2)
    assert hi["resolved"] == "override"
    assert _approx(hi["value_per_door"], base["value_per_door"] * 2, tol=2.0)
    # The source label names the override, not ACS, so consumers can tell them apart.
    assert hi["source"] == mv.OVERRIDE_SOURCE_LABEL
    assert base["source"] == mv.RENT_SOURCE_LABEL
    # A county-scoped override reports county geo_level; a context-free one is national.
    assert hi["geo_level"] == "county"
    assert value_per_door_for_county(None, monthly_rent=1500)["geo_level"] == "us"


def test_rent_clamp_bounds_outliers():
    """A wildly high override rent is clamped to the sanity ceiling."""
    capped = value_per_door_for_county("47157", monthly_rent=99_999)
    assert _approx(capped["monthly_rent"], mv.RENT_CEIL)


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} tests passed.")


if __name__ == "__main__":
    _run_all()
