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
    """An unresearched state leaves the caller's own ratio untouched."""
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
    """What score/all_dimensions.INFRA_XS_BASIS must match after a recalibration.

    Sorted by USPS, so the tuple reads as a legible changelog of which jurisdictions
    entered the reference distribution and at what strength.
    """
    assert active_basis() == ("AL:2.00", "MS:1.50", "SC:1.50", "TN:1.60", "WV:2.00")


def test_coverage_is_honest_about_the_gap():
    """The unresearched majority is recorded rather than implied by silence.

    Twelve of 51 researched after Phase 2 (South Atlantic, less DC). The seven uniform
    jurisdictions count as researched despite applying no correction — that distinction
    is the whole point of RULE_UNIFORM.
    """
    remaining = unresearched_jurisdictions()
    assert len(remaining) == 39
    for done in ("AL", "KY", "MS", "TN", "SC", "WV", "FL", "GA", "MD", "NC", "VA", "DE"):
        assert done not in remaining
    # DC is deferred, not done — see test_south_atlantic_coverage_and_the_deferred_jurisdiction.
    assert "DC" in remaining


# ── The CLI tenure contract ──────────────────────────────────────────────────────

def test_tenure_flags_are_tri_state_and_exclusive():
    """Unspecified tenure must reach the config as None, not as a boolean.

    None is not a third cosmetic state: it selects the ACS-backed default in
    rental_unit_count, which differs from an explicit True. For a duplex that is the
    whole ballgame — unknown resolves to rental (reclassified), while True means the
    owner lives in one half (not reclassified). Silently defaulting to a boolean would
    change scores with nothing visibly broken.

    Both flags therefore carry an explicit default=None. argparse seeds a shared dest
    from the first-declared action that supplies a default, so relying on
    --owner-occupied's default alone would make the tri-state depend on declaration
    order. This test pins the behavior rather than the ordering.
    """
    from housing_label.simulate.house import build_parser, resolve_config

    parser = build_parser()
    loc = ["--lat", "36.06", "--lon", "-86.72"]
    for argv, expected in (([], None), (["--owner-occupied"], True), (["--rental"], False)):
        args = parser.parse_args(argv + loc)
        assert args.owner_occupied is expected, f"{argv}: argparse gave {args.owner_occupied!r}"
        assert resolve_config(args).get("owner_occupied") is expected, f"{argv}: lost in cfg"

    # Asserting the two flags cannot both be given, so the dest is never ambiguous.
    try:
        parser.parse_args(["--owner-occupied", "--rental"] + loc)
    except SystemExit:
        pass
    else:
        raise AssertionError("--owner-occupied and --rental must be mutually exclusive")


def test_unknown_tenure_differs_from_explicit_owner_occupied_for_a_duplex():
    """The case that makes the tri-state load-bearing rather than cosmetic."""
    assert classified_assess_ratio("TN", 2) == TN_COMMERCIAL_ASSESS_RATIO      # unknown
    assert classified_assess_ratio("TN", 2, owner_occupied=True) is None       # stated


# ── Phase 1: East South Central (KY, TN, MS, AL) ─────────────────────────────────
#
# Alabama and Mississippi are the first TENURE-based rules: their residential class
# requires single-family AND owner-occupied, so the threshold is 1 rental unit rather
# than Tennessee's 2, and a rented detached house is reclassified. The matrix below is
# the whole behavioral contract for that rule shape.

_TENURE_MATRIX = {
    #                                  AL     MS     TN     KY
    "single-family, owner-occupied": (1.0,   1.0,   1.0,   1.0),
    "single-family, unknown tenure": (1.0,   1.0,   1.0,   1.0),
    "single-family, stated rental":  (2.0,   1.5,   1.0,   1.0),
    "duplex, owner-occupied":        (2.0,   1.5,   1.0,   1.0),
    "duplex, fully rented":          (2.0,   1.5,   1.6,   1.0),
    "8-unit rental":                 (2.0,   1.5,   1.6,   1.0),
    "157-unit condo (parceled)":     (1.0,   1.0,   1.0,   1.0),
}

_CASES = {
    "single-family, owner-occupied": dict(units=1, owner_occupied=True),
    "single-family, unknown tenure": dict(units=1),
    "single-family, stated rental":  dict(units=1, owner_occupied=False),
    "duplex, owner-occupied":        dict(units=2, owner_occupied=True),
    "duplex, fully rented":          dict(units=2, owner_occupied=False),
    "8-unit rental":                 dict(units=8, owner_occupied=False),
    "157-unit condo (parceled)":     dict(units=157, separately_parceled=True),
}


def test_east_south_central_tenure_matrix():
    """One table covering every tenure/unit case in all four states of the division.

    Two rows carry most of the weight. 'single-family, unknown tenure' must stay at 1.0
    everywhere — that is the conservative default, and AL/MS reach a detached house only
    when the caller explicitly says it is a rental. 'duplex, owner-occupied' diverges by
    design: AL and MS test single-family AND owner-occupied, so a duplex fails on the
    first prong whoever lives in it, while Tennessee counts rental units and an
    owner-occupied duplex has only one.
    """
    for case, expected in _TENURE_MATRIX.items():
        kwargs = _CASES[case]
        for state, want in zip(("AL", "MS", "TN", "KY"), expected):
            got = classification_multiplier(state, **kwargs)
            assert got == want, f"{state} / {case}: expected {want}, got {got}"


def test_alabama_and_mississippi_class_ratios():
    """The encoded legs are the statutory percentages, not a pre-divided multiplier."""
    al, ms = CLASSIFICATION_RULES["AL"], CLASSIFICATION_RULES["MS"]
    assert (al.residential, al.commercial) == (0.10, 0.20)   # Class III vs Class II
    assert (ms.residential, ms.commercial) == (0.10, 0.15)   # Class I  vs Class II
    assert al.multiplier() == 2.0 and ms.multiplier() == 1.5
    # Both are tenure rules: threshold 1, unlike Tennessee's 2.
    assert al.rental_unit_threshold == ms.rental_unit_threshold == 1
    assert CLASSIFICATION_RULES["TN"].rental_unit_threshold == 2


def test_kentucky_is_researched_but_uniform():
    """A RULE_UNIFORM record is how 'researched, no correction' is told apart from
    'not researched' — silence would conflate them."""
    ky = CLASSIFICATION_RULES["KY"]
    assert ky.rule_type == RULE_UNIFORM
    assert classified_assess_ratio("KY", 157, owner_occupied=False) is None
    assert "KY" not in unresearched_jurisdictions()
    # The homestead exemption was found and deliberately excluded; the note is the record.
    assert "170" in ky.notes and "exclusion rule" in ky.notes


def test_east_south_central_is_complete():
    """Every jurisdiction in the division now has a record.

    Turns 'we finished the region' into an assertion. Without it a forgotten state would
    silently score as a no-op, which is indistinguishable from a researched uniform state
    at the point of use.
    """
    from housing_label.data.states import CENSUS_DIVISION

    division = {s for s, d in CENSUS_DIVISION.items() if d == "East South Central"}
    assert division == {"AL", "KY", "MS", "TN"}
    missing = division - set(CLASSIFICATION_RULES)
    assert not missing, f"East South Central incomplete: {sorted(missing)}"


# ── Phase 2: South Atlantic ──────────────────────────────────────────────────────
#
# Eight of nine encoded; DC deferred as unverified. South Carolina is a third
# tenure-based assessment-ratio state. West Virginia is the FIRST rule that splits by
# tax RATE rather than assessment ratio — same economic effect, different mechanism,
# and it is what RULE_RATE exists for.

SOUTH_ATLANTIC_UNIFORM = ("DE", "FL", "GA", "MD", "NC", "VA")


def test_south_atlantic_correcting_states():
    """SC and WV, across the same tenure matrix used for East South Central."""
    expected = {  #                                   SC     WV
        "single-family, owner-occupied": (1.0,   1.0),
        "single-family, unknown tenure": (1.0,   1.0),
        "single-family, stated rental":  (1.5,   2.0),
        "duplex, owner-occupied":        (1.5,   2.0),
        "duplex, fully rented":          (1.5,   2.0),
        "8-unit rental":                 (1.5,   2.0),
        "157-unit condo (parceled)":     (1.0,   1.0),
    }
    for case, (sc, wv) in expected.items():
        kwargs = _CASES[case]
        for state, want in (("SC", sc), ("WV", wv)):
            got = classification_multiplier(state, **kwargs)
            assert got == want, f"{state} / {case}: expected {want}, got {got}"


def test_west_virginia_is_a_rate_rule_not_a_ratio_rule():
    """WV assesses every class at 60% of value; only the levy RATE differs.

    So the absolute accessor must stay silent at every unit count — there is no
    different assessment ratio to hand back — while the multiplier still applies. This
    is the first jurisdiction to exercise that distinction; before it,
    test_rate_rules_never_yield_an_absolute_ratio looped over an empty set.
    """
    wv = CLASSIFICATION_RULES["WV"]
    assert wv.rule_type == RULE_RATE
    for units in (1, 2, 8, 157):
        assert classified_assess_ratio("WV", units, owner_occupied=False) is None
    assert classification_multiplier("WV", 8, owner_occupied=False) == 2.0
    # The legs are the county maximum regular levy rates, 28.60 -> 57.20 cents.
    assert abs(wv.commercial / wv.residential - 2.0) < 1e-9


def test_south_carolina_class_ratios():
    sc = CLASSIFICATION_RULES["SC"]
    assert (sc.residential, sc.commercial) == (0.04, 0.06)   # legal residence vs other
    assert sc.multiplier() == 1.5 and sc.rental_unit_threshold == 1


def test_researched_uniform_states_never_correct():
    """Six South Atlantic jurisdictions were researched and found to have no
    classification of rental housing. Each must be a no-op at every unit count and
    tenure — including the exemption/cap states, where a large owner/rental gap exists
    but is not a class ratio and must not be encoded as one."""
    for state in SOUTH_ATLANTIC_UNIFORM:
        rule = CLASSIFICATION_RULES[state]
        assert rule.rule_type == RULE_UNIFORM, state
        for kwargs in _CASES.values():
            assert classification_multiplier(state, **kwargs) == 1.0, f"{state} {kwargs}"
        assert classified_assess_ratio(state, 157, owner_occupied=False) is None, state


def test_cap_and_credit_states_record_what_was_rejected():
    """FL, GA and MD each have a real owner/rental gap driven by an exemption, credit or
    assessment cap. The notes are the only thing distinguishing 'researched, rejected'
    from 'not researched', since both yield a 1.0 multiplier."""
    for state, marker in (("FL", "196.031"), ("GA", "48-5-44"), ("MD", "9-105")):
        notes = CLASSIFICATION_RULES[state].notes
        assert "REJECTED" in notes, f"{state}: no rejection recorded"
        assert marker in CLASSIFICATION_RULES[state].authority + notes, state


def test_virginia_is_uniform_not_local_option():
    """Virginia permits some locality-level classification, but the only one with rate
    consequences expressly excludes rental housing — so it is uniform, and must NOT be
    flagged local_option, which would imply an unresolvable sub-state rule."""
    va = CLASSIFICATION_RULES["VA"]
    assert va.rule_type == RULE_UNIFORM and va.local_option is False
    assert "58.1-3221.3" in va.authority
    assert "EXCLUDES" in va.notes


def test_south_atlantic_coverage_and_the_deferred_jurisdiction():
    """Eight of nine encoded, with DC named as the outstanding one.

    Asserting the gap rather than implying it: an unencoded jurisdiction and a
    researched-uniform one both score 1.0, so without this the deferral would be
    indistinguishable from an oversight.
    """
    from housing_label.data.states import CENSUS_DIVISION

    division = {s for s, d in CENSUS_DIVISION.items() if d == "South Atlantic"}
    assert len(division) == 9
    outstanding = division - set(CLASSIFICATION_RULES)
    assert outstanding == {"DC"}, f"expected only DC outstanding, got {sorted(outstanding)}"
    assert "DC" in unresearched_jurisdictions()
    assert classification_multiplier("DC", 157, owner_occupied=False) == 1.0


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} tests passed.")


if __name__ == "__main__":
    _run_all()
