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
    CLASSIFICATION_MULT_CEIL, CLASSIFICATION_RULES, RULE_ASSESSMENT, RULE_RATE,
    RULE_UNIFORM, TN_COMMERCIAL_ASSESS_RATIO, TN_RESIDENTIAL_ASSESS_RATIO,
    active_basis, classification_for, classification_multiplier,
    classified_assess_ratio, rental_unit_count, unresearched_jurisdictions,
)
from housing_label.enrich.infrastructure import enrich_row


def test_single_family_is_residential_either_tenure():
    """One dwelling unit is at most one rental unit, so tenure can't reclassify it."""
    assert classified_assess_ratio("TN", 1, owner_occupied=True) is None
    assert classified_assess_ratio("TN", 1, owner_occupied=False) is None
    # AG Op. 25-016 Q1: a single-family home rented long-term stays residential.
    assert rental_unit_count(1, owner_occupied=False) == 1


def test_owner_occupied_duplex_stays_residential():
    """AG Op. 25-016 Q2: the owner's half is not a rental unit, so a duplex with
    one rented half contains only one rental unit."""
    assert rental_unit_count(2, owner_occupied=True) == 1
    assert classified_assess_ratio("TN", 2, owner_occupied=True) is None


def test_fully_rented_duplex_is_commercial():
    """Two rental units crosses the constitutional threshold."""
    assert rental_unit_count(2, owner_occupied=False) == 2
    assert classified_assess_ratio("TN", 2, owner_occupied=False) == TN_COMMERCIAL_ASSESS_RATIO


def test_unknown_tenure_defaults_multiunit_to_rental():
    """ACS 2024 B25032: 86% of units in 2+ unit structures are renter-occupied, so
    unknown tenure resolves to rental for a multi-unit building and owner for a
    single home."""
    assert classified_assess_ratio("TN", 12) == TN_COMMERCIAL_ASSESS_RATIO
    assert classified_assess_ratio("TN", 1) is None


def test_unresearched_states_return_none():
    """Only Tennessee is encoded; everywhere else the caller keeps its own ratio."""
    for state in ("CA", "NY", "tx", "", None):
        assert classified_assess_ratio(state, 157) is None
    # Case-insensitive on the state that IS encoded.
    assert classified_assess_ratio("tn", 157) == TN_COMMERCIAL_ASSESS_RATIO


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


# ── Schema integrity: the guard rail that makes the per-state rollout safe ────────

def test_every_rule_carries_provenance():
    """No rule lands without a primary-source citation and a date it was read."""
    import datetime
    today = datetime.date.today()
    for usps, rule in CLASSIFICATION_RULES.items():
        assert rule.usps == usps, f"{usps}: record disagrees with its key"
        assert rule.authority.strip(), f"{usps}: no authority cited"
        verified = datetime.date.fromisoformat(rule.verified)
        assert verified <= today, f"{usps}: verified in the future"
        assert rule.rule_type in (RULE_ASSESSMENT, RULE_RATE, RULE_UNIFORM)


def test_rule_types_carry_the_fields_they_need():
    for usps, rule in CLASSIFICATION_RULES.items():
        if rule.rule_type == RULE_UNIFORM:
            assert rule.multiplier() == 1.0, f"{usps}: uniform must not correct"
            continue
        assert rule.rental_unit_threshold, f"{usps}: no threshold"
        assert rule.threshold_basis, f"{usps}: no threshold basis"
        if rule.effective_multiplier is None:
            assert rule.residential and rule.commercial, f"{usps}: missing a class leg"


def test_multiplier_equals_the_ratio_of_its_legs():
    """Catches a pre-divided number pasted where the two source values belong."""
    for usps, rule in CLASSIFICATION_RULES.items():
        if rule.rule_type == RULE_UNIFORM or rule.effective_multiplier is not None:
            continue
        assert abs(rule.multiplier() - rule.commercial / rule.residential) < 1e-9, usps


def test_multipliers_are_within_the_sanity_ceiling():
    """A split roll that more than triples the tax is a research error, not a statute."""
    for usps, rule in CLASSIFICATION_RULES.items():
        assert 1.0 <= rule.multiplier() <= CLASSIFICATION_MULT_CEIL, usps


def test_rate_rules_never_yield_an_absolute_ratio():
    """RULE_RATE states differ by millage, not by assessment ratio — the absolute
    accessor must stay silent there however many units the parcel has."""
    for usps, rule in CLASSIFICATION_RULES.items():
        if rule.rule_type != RULE_RATE:
            continue
        for units in (1, 2, 4, 157):
            assert classified_assess_ratio(usps, units, owner_occupied=False) is None, usps


# ── The multiplier accessor (the national path) ──────────────────────────────────

def test_tn_multiplier_is_the_class_ratio():
    assert classification_multiplier("TN", 157) == TN_COMMERCIAL_ASSESS_RATIO / TN_RESIDENTIAL_ASSESS_RATIO
    assert classification_multiplier("TN", 157) == 1.6


def test_multiplier_is_exactly_one_where_nothing_applies():
    """Unresearched states, ordinary housing, and no state at all are all no-ops —
    the correction can only ever move parcels a statute actually reclassifies."""
    for state in ("CA", "NY", "XX", "", None):
        assert classification_multiplier(state, 157) == 1.0
    assert classification_multiplier("TN", 1) == 1.0
    assert classification_multiplier("TN", 2, owner_occupied=True) == 1.0
    for usps in unresearched_jurisdictions():
        assert classification_multiplier(usps, 157) == 1.0


def test_separately_parceled_suppresses_reclassification_everywhere():
    """A condominium tower is N parcels of one unit, not one parcel of N."""
    for units in (2, 4, 157):
        assert classified_assess_ratio("TN", units, separately_parceled=True) is None
        assert classification_multiplier("TN", units, separately_parceled=True) == 1.0


def test_both_classification_paths_at_once_raises():
    """The two paths are alternatives; wiring up both would square the correction
    (1.6 x 1.6 = 2.56 in Tennessee). enrich_row must refuse rather than pick one."""
    try:
        enrich_row(_row(157, 1.0, 150_000), units=157,
                   classification_state="TN", classification_rate_state="TN")
    except ValueError as exc:
        assert "alternatives" in str(exc)
    else:
        raise AssertionError("expected ValueError when both classification paths are set")


def test_reporting_view_is_always_a_dict():
    applied = classification_for("TN", 157)
    assert applied["applied"] is True and applied["researched"] is True
    assert applied["multiplier"] == 1.6 and applied["assess_ratio"] == 0.40
    assert "67-5-501" in applied["authority"]
    missing = classification_for("CA", 157)
    assert missing["applied"] is False and missing["researched"] is False
    assert missing["multiplier"] == 1.0 and missing["authority"] is None


def test_active_basis_fingerprint():
    """What score/all_dimensions.INFRA_XS_BASIS must match after a recalibration."""
    assert active_basis() == ("TN:1.60",)


def test_coverage_is_honest_about_the_gap():
    """50 of 51 jurisdictions are unresearched, and that is recorded rather than
    implied by silence."""
    assert len(unresearched_jurisdictions()) == 50
    assert "TN" not in unresearched_jurisdictions()


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} tests passed.")


if __name__ == "__main__":
    _run_all()
