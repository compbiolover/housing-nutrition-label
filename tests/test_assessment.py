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
    BASIS_DWELLING_UNITS, CLASSIFICATION_MULT_CEIL, CLASSIFICATION_RULES, LAW_AS_OF,
    RULE_ASSESSMENT, RULE_EFFECTIVE, RULE_RATE,
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
    for state in ("CA", "MT", "", None):
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

def _every_rule():
    """(label, rule) for every rule in the table, sub-state rules included.

    Sub-state rules are real rules that score real parcels, so every integrity check
    below has to reach them. Walking only the top level would let New York City's record
    land with no citation and no threshold and still pass the whole schema suite.
    """
    for usps, rule in CLASSIFICATION_RULES.items():
        yield usps, rule
        for county_fips, sub in rule.sub_state.items():
            yield f"{usps}/{county_fips}", sub


def _is_local_option_container(rule):
    """A local-option record carries no legs itself.

    True whether or not ``sub_state`` has entries. Rhode Island and Connecticut have a real
    classification of rental housing that is set per municipality, in states whose counties
    are not governmental units — so there is nothing for a county-keyed ``sub_state`` to
    hold, and requiring one would force them to be mis-recorded as uniform.
    """
    return bool(rule.local_option)


def test_every_rule_carries_provenance():
    """No rule lands without a primary-source citation and a date it was read."""
    import datetime
    today = datetime.date.today()
    for label, rule in _every_rule():
        assert rule.usps == label.split("/")[0], f"{label}: record disagrees with its key"
        assert rule.authority.strip(), f"{label}: no authority cited"
        verified = datetime.date.fromisoformat(rule.verified)
        assert verified <= today, f"{label}: verified in the future"
        assert rule.rule_type in (RULE_ASSESSMENT, RULE_RATE, RULE_EFFECTIVE, RULE_UNIFORM)


def test_rule_types_carry_the_fields_they_need():
    for label, rule in _every_rule():
        if rule.rule_type == RULE_UNIFORM:
            assert rule.multiplier() == 1.0, f"{label}: uniform must not correct"
            continue
        if _is_local_option_container(rule):
            # Routes to sub-rules; those are checked on their own pass through _every_rule.
            assert rule.multiplier() == 1.0, f"{label}: a container must not correct"
            continue
        assert rule.rental_unit_threshold, f"{label}: no threshold"
        assert rule.threshold_basis, f"{label}: no threshold basis"
        if rule.effective_multiplier is None:
            assert rule.residential and rule.commercial, f"{label}: missing a class leg"


def test_local_option_states_route_only_through_sub_state():
    """A local-option state must never correct on its own.

    The container carries no legs, so a caller who omits the county under-corrects instead
    of applying one county's rule statewide — the safe direction, asserted rather than
    assumed. An EMPTY sub_state is allowed and meaningful: Rhode Island and Connecticut
    have a real classification that reaches rental housing but is set per municipality, in
    states whose counties are not governmental units. Recording that as local-option with
    nothing to route to is more honest than RULE_UNIFORM, which would assert there is no
    classification to find.
    """
    for usps, rule in CLASSIFICATION_RULES.items():
        if not rule.local_option:
            continue
        assert rule.residential is None and rule.commercial is None, usps
        assert rule.effective_multiplier is None, usps
        assert classification_multiplier(usps, 157, owner_occupied=False) == 1.0, usps
        # And with a county supplied but no entry for it, still nothing.
        assert classification_multiplier(
            usps, 157, owner_occupied=False, county_fips="99999") == 1.0, usps


def test_multiplier_equals_the_ratio_of_its_legs():
    """Catches a pre-divided number pasted where the two source values belong."""
    for label, rule in _every_rule():
        if rule.rule_type == RULE_UNIFORM or rule.effective_multiplier is not None:
            continue
        if _is_local_option_container(rule):
            continue
        assert abs(rule.multiplier() - rule.commercial / rule.residential) < 1e-9, label


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
    assert active_basis() == (
        "AL:2.00", "MS:1.50", "NY/36005:1.81", "NY/36047:1.81", "NY/36061:1.81",
        "NY/36081:1.81", "NY/36085:1.81", "SC:1.50", "TN:1.60", "WV:2.00")


def test_active_basis_descends_into_sub_state_rules():
    """A local-option container has no legs of its own, so walking only the top level
    would let New York City enter the reference distribution with the fingerprint
    unchanged — the exact silent mis-scoring INFRA_XS_BASIS exists to catch."""
    ny = CLASSIFICATION_RULES["NY"]
    assert ny.multiplier() == 1.0 and ny.local_option and ny.sub_state
    basis = active_basis()
    assert "NY:1.81" not in basis, "the container must not appear as if statewide"
    for fips in ny.sub_state:
        assert f"NY/{fips}:1.81" in basis, fips


def test_coverage_is_honest_about_the_gap():
    """The unresearched majority is recorded rather than implied by silence.

    Twenty-four of 51 researched after Phase 5 (East North Central). The eighteen uniform
    jurisdictions count as researched despite applying no correction — that distinction
    is the whole point of RULE_UNIFORM.
    """
    remaining = unresearched_jurisdictions()
    assert len(remaining) == 21
    for done in ("AL", "KY", "MS", "TN", "SC", "WV", "FL", "GA", "MD", "NC", "VA", "DE",
                 "AR", "LA", "OK", "TX", "NY", "NJ", "PA", "IL", "IN", "MI", "OH", "WI",
                 "ME", "NH", "VT", "MA", "RI", "CT"):
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


def test_south_carolina_multiplier_is_the_non_school_ratio():
    """1.50 is right, and the tempting re-derivation says otherwise — so pin the reason.

    South Carolina exempts an owner-occupied legal residence from school OPERATING
    millage on top of giving it the 4% ratio. Work the TOTAL tax bill and a rental looks
    like it pays more than 1.5x an owner, which is what an earlier version of this record
    claimed. That reading is wrong for this model.

    The multiplier is applied to the NON-SCHOOL rate: region_context builds
    ``effective_tax_rate * (1 - school_tax_share)`` and enrich_row multiplies that by the
    class multiplier. With m_n the non-school millage, a rental pays 0.06*m_n against an
    owner's 0.04*m_n — exactly 1.5. The observed owner rate is the base for BOTH legs, so
    the exemption shifts that base's level and cancels out of the ratio entirely.

    Michigan is the same structure with no class split to confuse it, and correctly
    carries no correction at all. Asserting the notes name the real residual too, so the
    two findings cannot drift apart again.
    """
    sc = CLASSIFICATION_RULES["SC"]
    assert sc.multiplier() == 1.5

    # Exercised through enrich_row rather than by restating the arithmetic, because the
    # claim is about the MODEL: whatever level the school exemption leaves the observed
    # rate at, the rented and owner-occupied legs are built from that same rate, so the
    # ratio between them stays 1.5. Sweeping the base rate is the whole point — a test
    # that fixed one rate could not distinguish "cancels" from "happens to agree here".
    def _sc_tax(*, owner_occupied, municipal_rate):
        out = enrich_row(_row(1, 0.25, 200_000), units=1,
                         assess_ratio=1.0, tax_rate=municipal_rate,
                         classification_state=None, classification_rate_state="SC",
                         owner_occupied=owner_occupied)
        return float(out["est_property_tax"])

    for municipal_rate in (0.004, 0.010, 0.025):
        owner = _sc_tax(owner_occupied=True, municipal_rate=municipal_rate)
        rented = _sc_tax(owner_occupied=False, municipal_rate=municipal_rate)
        assert owner > 0
        assert abs(rented / owner - 1.5) < 1e-9, (
            f"at municipal_rate={municipal_rate} the ratio was {rented / owner}")

    assert "UNDER-CORRECTS" not in sc.notes, "the retracted claim is back"
    assert "1.50 IS THE RIGHT FIGURE" in sc.notes
    assert "school_tax_share" in sc.notes          # the real residual, named
    # Michigan reaches the same conclusion from the other direction.
    assert "RESOLVED" in CLASSIFICATION_RULES["MI"].notes


def _assert_uniform_is_a_noop(states):
    """A RULE_UNIFORM record must be inert on every path, at every unit count and tenure.

    Shared by every phase from Phase 2 on, because the uniform states are where a
    mis-encoding is hardest to notice: a wrong ratio on a correcting state moves scores
    and shows up in recalibration, but a uniform record that accidentally carries legs
    would start correcting a state the research says to leave alone.
    """
    for state in states:
        rule = CLASSIFICATION_RULES[state]
        assert rule.rule_type == RULE_UNIFORM, state
        for kwargs in _CASES.values():
            assert classification_multiplier(state, **kwargs) == 1.0, f"{state} {kwargs}"
        assert classified_assess_ratio(state, 157, owner_occupied=False) is None, state


def test_researched_uniform_states_never_correct():
    """Six South Atlantic jurisdictions were researched and found to have no
    classification of rental housing. Each must be a no-op at every unit count and
    tenure — including the exemption/cap states, where a large owner/rental gap exists
    but is not a class ratio and must not be encoded as one."""
    _assert_uniform_is_a_noop(SOUTH_ATLANTIC_UNIFORM)


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


# ── Phase 3: West South Central ──────────────────────────────────────────────────
#
# The first division that adds NO correction: all four jurisdictions were researched and
# found uniform. Every owner/rental gap here runs through an exemption, credit or
# assessment cap, which the documented exclusion rule keeps out of the table.

WEST_SOUTH_CENTRAL_UNIFORM = ("AR", "LA", "OK", "TX")


def test_west_south_central_is_uniform_throughout():
    _assert_uniform_is_a_noop(WEST_SOUTH_CENTRAL_UNIFORM)


def test_louisiana_split_roll_is_use_based_not_tenure_based():
    """Pins the reversal of an earlier prediction, so it cannot quietly regress.

    The rollout memo typed Louisiana as a correcting state on the strength of its real
    10%/15% split. Reading La. Const. art. VII, § 18(B) overturns that: the classes are
    land, 'improvements for residential purposes', electric cooperative, public service
    and 'other property' — a USE test with no tenure or unit-count qualifier anywhere.
    An apartment building is an improvement used for residential purposes, so it sits in
    the 10% class beside a detached house, and the owner/rental gap runs entirely through
    the § 20 homestead exemption instead.

    Without this test the finding is a comment. With it, anyone tempted to re-encode the
    remembered 1.5x has to change an assertion that says why not.
    """
    la = CLASSIFICATION_RULES["LA"]
    assert la.rule_type == RULE_UNIFORM
    assert la.residential is None and la.commercial is None
    assert la.effective_multiplier is None
    assert "18(A), (B), § 20" in la.authority
    assert "§ V-101" in la.authority              # the Tax Commission's own rule agrees
    assert "FOUND AND REJECTED" in la.notes and "homestead" in la.notes
    # A 157-unit rental building in Louisiana is taxed like a house, per the text.
    assert classification_multiplier("LA", 157, owner_occupied=False) == 1.0


def test_texas_records_the_circuit_breaker_that_narrows_the_gap():
    """Texas is the largest jurisdiction encoded so far and it has no classes at all.

    Its § 23.231 circuit breaker caps NON-homestead appraisal growth, so unlike Florida's
    caps it narrows the owner/rental gap. Recording that is the point: it is the clearest
    evidence that a fixed class multiplier cannot stand in for a cap regime, since the
    caps do not even all push the same direction.
    """
    tx = CLASSIFICATION_RULES["TX"]
    assert tx.rule_type == RULE_UNIFORM
    assert "23.231" in tx.authority
    assert "NARROWS" in tx.notes


def test_west_south_central_is_complete_with_no_deferral():
    """Four of four, and the first division to finish without an outstanding jurisdiction.

    Asserted as an empty set rather than by counting, so a future edit that drops a
    record fails here with the missing USPS named.
    """
    from housing_label.data.states import CENSUS_DIVISION

    division = {s for s, d in CENSUS_DIVISION.items() if d == "West South Central"}
    assert division == {"AR", "LA", "OK", "TX"}
    outstanding = division - set(CLASSIFICATION_RULES)
    assert outstanding == set(), f"unencoded: {sorted(outstanding)}"


def test_phase_3_moves_no_anchors():
    """Four uniform records cannot enter the reference distribution.

    active_basis() is what INFRA_XS was calibrated against, so this asserts the phase is
    score-neutral by construction: if any West South Central state ever appears in the
    fingerprint, INFRA_XS is stale and the golden snapshot is wrong.
    """
    basis = active_basis()          # the literal itself lives in test_active_basis_fingerprint
    for state in WEST_SOUTH_CENTRAL_UNIFORM:
        assert not any(entry.startswith(f"{state}:") for entry in basis), state


# ── Phase 4: Middle Atlantic ─────────────────────────────────────────────────────
#
# New York is the hardest jurisdiction in the country and the first to exercise
# local_option + sub_state + BASIS_DWELLING_UNITS + RULE_EFFECTIVE — all four pieces of
# schema that had never been used. New Jersey and Pennsylvania are constitutionally
# uniform, Pennsylvania emphatically so.

MIDDLE_ATLANTIC_UNIFORM = ("NJ", "PA")
NYC_COUNTIES = ("36005", "36047", "36061", "36081", "36085")   # the five boroughs
NASSAU_FIPS = "36059"
UPSTATE_FIPS = "36001"                                         # Albany County
# $1.54 (large rentals) over $0.85 (1-3 family), the two published median ETRs. Kept as
# the quotient rather than a pasted 1.81 so both source figures stay visible.
NYC_MULT = round(1.54 / 0.85, 6)


def test_middle_atlantic_uniform_states():
    _assert_uniform_is_a_noop(MIDDLE_ATLANTIC_UNIFORM)


def test_new_york_corrects_only_inside_the_five_boroughs():
    """local_option means the correction is keyed to the county, not the state.

    Upstate New York and Nassau both resolve to no correction, for different documented
    reasons — art. 19 is adopted one assessing unit at a time and cannot be resolved at
    county granularity, and Nassau's multiplier would be a guess. Passing no county at all
    must also be inert, so a caller who forgets to thread it through under-corrects rather
    than applying a Manhattan rule to Buffalo.
    """
    for fips in NYC_COUNTIES:
        assert classification_multiplier(
            "NY", 157, owner_occupied=False, county_fips=fips) == NYC_MULT, fips
    for fips in (UPSTATE_FIPS, NASSAU_FIPS):
        assert classification_multiplier(
            "NY", 157, owner_occupied=False, county_fips=fips) == 1.0, fips
    assert classification_multiplier("NY", 157, owner_occupied=False) == 1.0


def test_new_york_city_threshold_is_the_statutory_eleven_unit_line():
    """11 dwelling units, not a tuned breakpoint.

    RPTL § 1805(2) shields class two parcels with fewer than 11 residential units behind
    the same growth cap class one gets, and the city's own ETR study shows that shield
    working: small rentals pay $0.75 against $0.85 for 1-3 family homes — LESS than a
    house. Correcting a 10-unit building would invent a penalty the data says is absent.

    The basis is dwelling units, not rental units, so tenure does not enter: class one is
    "one, two and three family residential", a physical test.
    """
    nyc = CLASSIFICATION_RULES["NY"].sub_state["36061"]
    assert nyc.threshold_basis == BASIS_DWELLING_UNITS
    assert nyc.rental_unit_threshold == 11
    for units in (1, 3, 4, 8, 10):
        assert classification_multiplier(
            "NY", units, owner_occupied=False, county_fips="36061") == 1.0, units
    for units in (11, 12, 157):
        assert classification_multiplier(
            "NY", units, owner_occupied=False, county_fips="36061") == NYC_MULT, units
    # Dwelling-unit basis: an owner living in one of 20 units does not shrink the count.
    assert classification_multiplier(
        "NY", 20, owner_occupied=True, county_fips="36061") == NYC_MULT


def test_new_york_city_multiplier_is_the_sales_based_etr_ratio_not_the_statutory_one():
    """The naive statutory reading over-corrects by ~2.6x, and the city says why.

    Class one is assessed at 6% of value and taxed at 19.843%; class two at 45% and
    12.439% (FY2026). That is 4.70x. But DOF's published class two "market value" is an
    income-capitalization figure well below sales-based value, so an ETR computed on DOF
    values overstates the disparity — the Advisory Commission recomputed on a common
    sales-based denominator and got $1.54 for large rentals against $0.85 for 1-3 family
    homes. This model's denominator is an ACS self-reported market value, the same
    sales-based concept, so 1.81x is the figure that matches.

    Guarding the gap between the two, because 4.70 is what anyone re-deriving this from
    the statute alone would land on.
    """
    nyc = CLASSIFICATION_RULES["NY"].sub_state["36061"]
    assert nyc.effective_multiplier == 1.54 / 0.85
    assert nyc.multiplier() == NYC_MULT
    assert round(nyc.multiplier(), 2) == 1.81      # how the basis fingerprint prints it
    statutory = (0.45 * 0.12439) / (0.06 * 0.19843)
    assert 4.6 < statutory < 4.8                       # what NOT to encode
    assert nyc.multiplier() < statutory / 2.5
    assert "OVER-CORRECT" in nyc.notes


def test_new_york_city_is_an_effective_rate_rule_with_no_absolute_ratio():
    """RULE_EFFECTIVE exists because neither leg alone is the datum. The absolute
    accessor must stay silent so the statutory path can never pick up the 45% ratio and
    apply it against an ACS rate that already embeds class one."""
    assert CLASSIFICATION_RULES["NY"].sub_state["36061"].rule_type == RULE_EFFECTIVE
    for fips in NYC_COUNTIES:
        assert classified_assess_ratio(
            "NY", 157, owner_occupied=False, county_fips=fips) is None, fips


def test_new_york_city_condominium_is_not_corrected():
    """Right answer, and worth pinning because the usual reasoning does not apply.

    Elsewhere a separately-parceled condo escapes because each parcel holds at most one
    rental unit. In New York City the statute says the opposite — condos are class two
    regardless of unit count. But the city's ETR study reports class two condos at $0.63
    against $0.85 for 1-3 family homes, i.e. condo owners pay LESS than house owners, so
    no correction is the correct outcome by a different route.
    """
    assert classification_multiplier(
        "NY", 157, separately_parceled=True, county_fips="36061") == 1.0


def test_pennsylvania_uniformity_forecloses_classification():
    """Valley Forge Towers is squarely about apartment buildings: a district appealed
    only apartment-complex assessments and the Supreme Court struck it down, holding all
    property in a taxing district to be a single class. Pennsylvania could not enact the
    kind of rule this table encodes even if it wanted to."""
    pa = CLASSIFICATION_RULES["PA"]
    assert pa.rule_type == RULE_UNIFORM
    assert "Valley Forge Towers" in pa.authority
    assert "single class" in pa.notes


def test_middle_atlantic_is_complete_with_nassau_named_as_the_gap():
    """Three of three encoded. Nassau is a sub-state deferral rather than a missing
    jurisdiction, so it cannot be caught by the division check — assert it separately, the
    way DC is asserted for South Atlantic."""
    from housing_label.data.states import CENSUS_DIVISION

    division = {s for s, d in CENSUS_DIVISION.items() if d == "Middle Atlantic"}
    assert division == {"NJ", "NY", "PA"}
    assert division - set(CLASSIFICATION_RULES) == set()
    ny = CLASSIFICATION_RULES["NY"]
    assert NASSAU_FIPS not in ny.sub_state, "Nassau is deferred, not encoded"
    assert "NASSAU COUNTY (36059) IS DEFERRED" in ny.notes


# ── Phase 5: East North Central ──────────────────────────────────────────────────
#
# All five uniform, so no anchor moves. The value here is in what was rejected: two states
# whose real class splits key on USE rather than tenure (IL, OH), one whose large
# owner/rental gap lives entirely in a levy this dimension already excludes (MI), and one
# cap regime that is structurally unlike Florida's (IN).

EAST_NORTH_CENTRAL_UNIFORM = ("IL", "IN", "MI", "OH", "WI")


def test_east_north_central_is_uniform_throughout():
    _assert_uniform_is_a_noop(EAST_NORTH_CENTRAL_UNIFORM)


def test_illinois_cook_ordinance_does_not_split_houses_from_apartments():
    """Pins the second predicted correction to dissolve, after Louisiana.

    The rollout memo typed Illinois as the second local_option case on the strength of
    Cook County's classification ordinance. Cook's own class-code schedule groups major
    classes 1, 2 and 3 under one heading — "RESIDENTIAL ASSESSMENT CLASSES (10% level of
    assessment)" — so a seven-or-more-unit rental building (class 3) is assessed at the
    same 10% as a house (class 2). The split that matters there is residential against
    commercial, and rental housing is on the residential side of it.

    Asserting local_option is False specifically: encoding Illinois as local_option with
    an empty sub_state would ALSO yield 1.0, so the no-op test above cannot tell the two
    apart. This is what says the memo's prediction was wrong rather than unimplemented.
    """
    il = CLASSIFICATION_RULES["IL"]
    assert il.rule_type == RULE_UNIFORM
    assert il.local_option is False and not il.sub_state
    assert il.residential is None and il.commercial is None
    assert "9-145" in il.authority                       # uniform 33-1/3% downstate
    assert "IT IS NOT" in il.notes                       # the reversal, stated
    for units in (1, 2, 6, 7, 157):
        assert classification_multiplier(
            "IL", units, owner_occupied=False) == 1.0, units


def test_michigan_rejects_on_the_school_levy_not_the_generic_rule():
    """Michigan's gap is real and large — 18 mills — and still correctly uncorrected.

    Every other uniform record rejects an exemption because exemptions are value- and
    tenure-length-dependent. Michigan's rejection is stronger and different: the
    Principal Residence Exemption relieves 18 mills of SCHOOL OPERATING tax, and this
    dimension already nets school taxes out of both the cost and the revenue side. So the
    differential is outside what the fiscal ratio measures at all, rather than merely hard
    to model. Asserting the reason, because the reason is the finding.
    """
    mi = CLASSIFICATION_RULES["MI"]
    assert mi.rule_type == RULE_UNIFORM
    assert "211.7cc" in mi.authority
    assert "SCHOOL OPERATING" in mi.notes and "school_tax_share" in mi.notes


def test_indiana_records_why_its_caps_are_not_floridas():
    """Indiana is the least comfortable uniform record, so the distinction is asserted.

    Florida and Texas cap the GROWTH of assessed value, so their owner/rental gap depends
    on holding period and appreciation — genuinely not a class ratio. Indiana caps tax as
    a share of CURRENT assessed value by class, which has no time dependence and is a rate
    ceiling in all but name. It stays uniform because the multiplier needs county gross
    rates the bundled data does not carry, not because the two regimes are alike.
    """
    ind = CLASSIFICATION_RULES["IN"]
    assert ind.rule_type == RULE_UNIFORM
    assert "art. 10, § 1(f)" in ind.authority
    assert "STRUCTURALLY DIFFERENT" in ind.notes


def test_use_based_splits_are_recorded_as_such():
    """Louisiana and Ohio both have a real class split that keys on use, not tenure.

    Grouping them in one assertion because it is now a recurring failure mode rather than
    a one-off: a state can have two assessment classes and still owe no correction, and
    the notes are the only thing that says why.
    """
    for usps in ("LA", "OH"):
        rule = CLASSIFICATION_RULES[usps]
        assert rule.rule_type == RULE_UNIFORM, usps
        assert "USE" in rule.notes, f"{usps}: the use-vs-tenure finding is not recorded"


def test_east_north_central_is_complete_with_no_deferral():
    from housing_label.data.states import CENSUS_DIVISION

    division = {s for s, d in CENSUS_DIVISION.items() if d == "East North Central"}
    assert division == {"IL", "IN", "MI", "OH", "WI"}
    outstanding = division - set(CLASSIFICATION_RULES)
    assert outstanding == set(), f"unencoded: {sorted(outstanding)}"


def test_phase_5_moves_no_anchors():
    """Five uniform records cannot enter the reference distribution."""
    basis = active_basis()          # the literal itself lives in test_active_basis_fingerprint
    for state in EAST_NORTH_CENTRAL_UNIFORM:
        assert not any(entry.startswith(f"{state}:") for entry in basis), state
        assert not any(entry.startswith(f"{state}/") for entry in basis), state


# ── Phase 6: New England ─────────────────────────────────────────────────────────
#
# The smallest division by population and the most legally varied. Vermont is the sharpest
# test of the rule that a tenure split confined to a SCHOOL levy owes no correction.
# Rhode Island and Connecticut are the first records for a third state of knowledge: a
# classification that is real, reaches rental housing, and cannot be resolved by county.

NEW_ENGLAND_UNIFORM = ("MA", "ME", "NH", "VT")
UNRESOLVABLE_LOCAL_OPTION = ("CT", "RI")


def test_new_england_uniform_states():
    _assert_uniform_is_a_noop(NEW_ENGLAND_UNIFORM)


def test_vermont_education_split_owes_no_correction():
    """The hardest "no" in the table, and the one most likely to be undone by mistake.

    32 V.S.A. § 5402 taxes homestead and nonhomestead property at different statewide
    rates — about 1.6x — with no local option. On its face it is the cleanest RULE_RATE
    candidate in the country, and anyone reading the statute alone would encode it.

    It owes no correction because the split sits entirely inside an EDUCATION levy, which
    this dimension nets out of both the cost and the revenue side. That is the rule
    established when South Carolina's note was retracted and Michigan's was written; this
    asserts Vermont applies it, and that the record says WHY rather than just yielding 1.0
    like an unresearched state would.
    """
    vt = CLASSIFICATION_RULES["VT"]
    assert vt.rule_type == RULE_UNIFORM
    assert vt.residential is None and vt.commercial is None
    assert "5402" in vt.authority
    assert "EDUCATION" in vt.notes            # the reason, not just the verdict
    assert "UNDER-CORRECTS" in vt.notes       # honest about the direction
    for units in (1, 2, 11, 157):
        assert classification_multiplier("VT", units, owner_occupied=False) == 1.0, units


def test_massachusetts_shift_cannot_reach_apartments():
    """Massachusetts permits a classification shift, so the record must say why it is
    still uniform rather than leaving that to be re-derived.

    ch. 40, § 56 lets a municipality move burden toward commercial and industrial
    property, but Massachusetts counts every property with one or more units for human
    habitation as residential — apartment buildings included — so the shift moves burden
    between residential and commercial and rental housing is on the residential side.
    Same shape as Virginia, and local_option must stay False so the record reads "the
    option does not reach rental housing" rather than "not yet resolved".
    """
    ma = CLASSIFICATION_RULES["MA"]
    assert ma.rule_type == RULE_UNIFORM and ma.local_option is False
    assert "§ 56" in ma.authority
    assert "RESIDENTIAL INCLUDES ALL PROPERTY" in ma.notes


def test_unresolvable_local_option_is_recorded_not_flattened():
    """Rhode Island and Connecticut classify rental housing, and we cannot resolve it.

    RI § 44-5-11.8 leaves a six-unit building in the commercial class unless the city says
    otherwise; CT § 12-62n names 'apartment property' as its own category. Both are set
    per municipality, and neither state's counties are governmental units — RI's five
    counties have no government, CT abolished county government in 1960 — so no county
    FIPS can carry the rule.

    Recording them as local_option with an EMPTY sub_state keeps the distinction from
    RULE_UNIFORM, which would assert there is no classification to find. Both yield 1.0
    either way, so only the record tells them apart — the same argument that makes
    RULE_UNIFORM worth having at all.
    """
    for usps in UNRESOLVABLE_LOCAL_OPTION:
        rule = CLASSIFICATION_RULES[usps]
        assert rule.local_option is True, usps
        assert rule.sub_state == {}, f"{usps}: expected no resolvable county"
        assert rule.rule_type != RULE_UNIFORM, (
            f"{usps}: RULE_UNIFORM would deny the classification exists")
        assert "per municipality" in rule.notes or "municipality" in rule.notes, usps
        for kwargs in _CASES.values():
            assert classification_multiplier(usps, **kwargs) == 1.0, f"{usps} {kwargs}"
        # The absolute path must stay silent too, even for the RULE_ASSESSMENT one.
        assert classified_assess_ratio(usps, 157, owner_occupied=False) is None, usps


def test_new_england_is_complete_with_no_deferral():
    from housing_label.data.states import CENSUS_DIVISION

    division = {s for s, d in CENSUS_DIVISION.items() if d == "New England"}
    assert division == {"CT", "MA", "ME", "NH", "RI", "VT"}
    outstanding = division - set(CLASSIFICATION_RULES)
    assert outstanding == set(), f"unencoded: {sorted(outstanding)}"


def test_phase_6_moves_no_anchors():
    """No New England record carries a correction, resolvable or otherwise."""
    basis = active_basis()          # the literal itself lives in test_active_basis_fingerprint
    for state in NEW_ENGLAND_UNIFORM + UNRESOLVABLE_LOCAL_OPTION:
        assert not any(entry.startswith(f"{state}:") for entry in basis), state
        assert not any(entry.startswith(f"{state}/") for entry in basis), state


def test_law_as_of_is_at_least_the_newest_verified_date():
    """The table-level vintage must not lag the records it describes.

    LAW_AS_OF plays the DATA_VINTAGE role for this table, so a reader treats it as "the
    law was checked as of this date". Adding a jurisdiction verified later than
    LAW_AS_OF silently makes that claim false, and nothing else would catch it.
    """
    import datetime

    as_of = datetime.date.fromisoformat(LAW_AS_OF)
    newest = max(datetime.date.fromisoformat(r.verified)
                 for r in CLASSIFICATION_RULES.values())
    assert as_of >= newest, (
        f"LAW_AS_OF is {LAW_AS_OF} but the newest record was verified {newest} — "
        "bump LAW_AS_OF when adding jurisdictions")


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} tests passed.")


if __name__ == "__main__":
    _run_all()
