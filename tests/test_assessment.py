#!/usr/bin/env python3
"""Offline tests for property-tax classification (data/assessment.py).

Tennessee classifies residential property containing two or more RENTAL units as
industrial and commercial, assessed at 40% rather than 25% (Tenn. Const. art. II,
§ 28; Tenn. Code Ann. § 67-5-501(11), § 67-5-801). The cases below track the
controlling authority, including Tenn. Att'y Gen. Op. No. 25-016 (Aug. 25, 2025).

Runs without network access and without pytest — execute directly:
  python tests/test_assessment.py
"""

from __future__ import annotations

import pandas as pd

from housing_label.data.assessment import (
    TN_COMMERCIAL_ASSESS_RATIO, TN_RESIDENTIAL_ASSESS_RATIO,
    commercial_assess_ratio, rental_unit_count,
)
from housing_label.enrich.infrastructure import enrich_row


def test_single_family_is_residential_either_tenure():
    """One dwelling unit is at most one rental unit, so tenure can't reclassify it."""
    assert commercial_assess_ratio("TN", 1, owner_occupied=True) is None
    assert commercial_assess_ratio("TN", 1, owner_occupied=False) is None
    # AG Op. 25-016 Q1: a single-family home rented long-term stays residential.
    assert rental_unit_count(1, owner_occupied=False) == 1


def test_owner_occupied_duplex_stays_residential():
    """AG Op. 25-016 Q2: the owner's half is not a rental unit, so a duplex with
    one rented half contains only one rental unit."""
    assert rental_unit_count(2, owner_occupied=True) == 1
    assert commercial_assess_ratio("TN", 2, owner_occupied=True) is None


def test_fully_rented_duplex_is_commercial():
    """Two rental units crosses the constitutional threshold."""
    assert rental_unit_count(2, owner_occupied=False) == 2
    assert commercial_assess_ratio("TN", 2, owner_occupied=False) == TN_COMMERCIAL_ASSESS_RATIO


def test_unknown_tenure_defaults_multiunit_to_rental():
    """ACS 2024 B25032: 86% of units in 2+ unit structures are renter-occupied, so
    unknown tenure resolves to rental for a multi-unit building and owner for a
    single home."""
    assert commercial_assess_ratio("TN", 12) == TN_COMMERCIAL_ASSESS_RATIO
    assert commercial_assess_ratio("TN", 1) is None


def test_unresearched_states_return_none():
    """Only Tennessee is encoded; everywhere else the caller keeps its own ratio."""
    for state in ("CA", "NY", "tx", "", None):
        assert commercial_assess_ratio(state, 157) is None
    # Case-insensitive on the state that IS encoded.
    assert commercial_assess_ratio("tn", 157) == TN_COMMERCIAL_ASSESS_RATIO


def _row(units: int, lot_acres: float, value: float) -> pd.Series:
    return pd.Series({"CALC_ACRE": lot_acres / units, "RTOTAPR": value,
                      "latitude": 35.1450, "longitude": -90.0500})


def test_classification_flows_through_enrich_row():
    """A 157-unit rental building is assessed at 40%, generating 1.6x the tax."""
    tower = enrich_row(_row(157, 1.0, 150_000), units=157)
    assert tower["assess_ratio_applied"] == TN_COMMERCIAL_ASSESS_RATIO
    house = enrich_row(_row(1, 0.25, 150_000), units=1)
    assert house["assess_ratio_applied"] == TN_RESIDENTIAL_ASSESS_RATIO
    # Same value per door, so the tax difference is purely the classification.
    assert abs(tower["est_property_tax"] / house["est_property_tax"] - 1.6) < 1e-6


def test_classification_never_overrides_a_supplied_basis():
    """The national path passes assess_ratio=1.0 against an effective tax rate that
    already embeds classification. Ordinary housing must come back untouched, and
    an explicit opt-out must hold even for a large rental building."""
    for units in (1, 2, 157):
        out = enrich_row(_row(units, 1.0, 200_000), units=units,
                         assess_ratio=1.0, tax_rate=0.01,
                         classification_state=None)
        assert out["assess_ratio_applied"] == 1.0
    # With no opt-out, a single home still keeps a supplied basis untouched,
    # because residential is a no-op rather than an override.
    solo = enrich_row(_row(1, 0.25, 200_000), units=1,
                      assess_ratio=1.0, tax_rate=0.01)
    assert solo["assess_ratio_applied"] == 1.0
    assert abs(solo["est_property_tax"] - 200_000 * 0.01) < 1e-6


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} tests passed.")


if __name__ == "__main__":
    _run_all()
