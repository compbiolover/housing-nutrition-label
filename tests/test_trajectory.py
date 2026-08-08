#!/usr/bin/env python3
"""Offline tests for the trajectory channel (no network, no pytest).

The load-bearing ones here are the coverage test and the fetch-invariance test.
Everything else checks shape; those two check the two properties the feature is
actually promising — that no dimension can silently go missing from the view, and
that asking for a timeline costs no extra upstream calls.

Run directly:  python tests/test_trajectory.py
"""

import pandas as pd

from housing_label import confidence as C
from housing_label.data import climate_projections as cp
from housing_label.data import vintages as V
from housing_label.enrich import durability as D
from housing_label.simulate.dimensions import DIMENSIONS
from housing_label.simulate import house as H


# ── The registry contract ────────────────────────────────────────────────────
def test_registry_covers_the_roster_exactly():
    """Every dimension either has a series or has a written reason it has none.

    This is the honest-degradation guard, and it is deliberately a test rather
    than a UI convention: it makes a new dimension UNMERGEABLE until someone
    writes the sentence explaining why it carries no history. Without it, "we
    never got round to backfilling this" renders to a reader as silence, which
    reads as "nothing changed here".

    Same shape as the coverage assertion in tests/test_national_percentile.py,
    and for the same reason.
    """
    roster = {k for k, _ in DIMENSIONS}
    covered = set(V.TRAJECTORY) | set(V.POINT_IN_TIME)
    assert covered == roster, (
        f"uncovered: {roster - covered}; unknown: {covered - roster}")
    overlap = set(V.TRAJECTORY) & set(V.POINT_IN_TIME)
    assert not overlap, f"a dimension cannot be both: {overlap}"


def test_specs_are_well_formed():
    for key, spec in V.TRAJECTORY.items():
        assert spec.basis in V.BASES, f"{key}: bad basis {spec.basis!r}"
        assert spec.source, f"{key}: a series must say where it came from"
        for p in spec.points:
            assert p.kind in V.KINDS, f"{key}: bad point kind {p.kind!r}"
    # At most one point per series may carry a percentile — see the module
    # docstring: a rank only means anything at its calibration vintage.
    for key, spec in V.TRAJECTORY.items():
        n = sum(1 for p in spec.points if p.percentile_ok)
        assert n <= 1, f"{key}: {n} points claim a percentile"


def test_point_in_time_reasons_are_sentences():
    """Not booleans, not TODOs — these are rendered to a reader verbatim."""
    for key, why in V.POINT_IN_TIME.items():
        assert len(why) > 40 and why.endswith("."), f"{key}: {why!r}"
        assert "TODO" not in why and "TBD" not in why, key


# ── Climate: the hist→mid pair ───────────────────────────────────────────────
def test_band_trajectory_is_leg_symmetric_across_every_county():
    """Both endpoints must be averaged over the SAME legs.

    Today the bundled data is symmetric, so this passes trivially — which is the
    point. If a future rebuild populates `hist` for a leg it doesn't populate for
    `low`, `band_trajectory` must keep comparing like with like rather than let
    the delta report a change in methodology as a change in the climate.
    """
    checked = 0
    for row in cp._table().values():
        a, b = cp._band_legs(row, "hist"), cp._band_legs(row, "low")
        if not a or not b:
            continue
        assert set(a) == set(b), f"leg sets differ: {set(a) ^ set(b)}"
        checked += 1
    assert checked > 3000, f"only checked {checked} counties"


def test_resolved_county_carries_a_commensurable_trajectory():
    d = cp.climate_projection_for_county("47157")          # Shelby County, TN
    t = d["trajectory"]
    assert t is not None
    # The projected endpoint IS the row's headline score: a reader comparing the
    # trajectory's last point against the dimension row must not see two numbers.
    assert t["to"] == d["score"] == d["score_low"]
    assert 0 <= t["from"] <= 100
    assert "heat" in t["legs"] and "precip" in t["legs"] and "drought" in t["legs"]


def test_us_fallback_still_carries_a_trajectory():
    # An unresolved place still moves; reporting no trend there would read as
    # "no change" rather than "we don't know where you are".
    d = cp.climate_projection_for_county("99999")
    assert d["resolved"] is False and d["trajectory"] is not None
    assert d["trajectory"]["to"] == d["score"]


def test_the_country_warms_on_balance():
    """A direction check, so a sign flip in the breakpoints can't pass silently."""
    deltas = []
    for row in cp._table().values():
        pair = cp.band_trajectory(row, "hist", "low")
        if pair:
            deltas.append(pair[1] - pair[0])
    assert len(deltas) > 3000
    assert sum(deltas) / len(deltas) < -3.0     # measured ≈ -5.8
    assert sum(1 for d in deltas if d < 0) > 0.9 * len(deltas)


# ── Durability: the aging curve ──────────────────────────────────────────────
def _row(**kw):
    base = {"YRBLT": 1995, "CDU": "AV", "EXTWALL": 7, "GRADE": 40}
    base.update(kw)
    return pd.Series(base)


def test_default_reference_year_is_unchanged():
    """The as-of parameter must be invisible to every existing caller."""
    assert (D.model_parcel_durability(_row())["durability_score"]
            == D.model_parcel_durability(_row(),
                                         reference_year=D.REFERENCE_YEAR)["durability_score"])


def test_durability_declines_with_age():
    scores = [D.model_parcel_durability(_row(), reference_year=y)["durability_score"]
              for y in (2000, 2010, 2026, 2040)]
    assert scores == sorted(scores, reverse=True), scores


def test_as_of_before_construction_is_unscored_not_condition_only():
    """The _valid_year trap.

    An as-of that predates the build year must yield "not scoreable", NOT a score
    computed from the condition rating alone — that would publish a durability
    figure for a house that hadn't been built yet.
    """
    out = D.model_parcel_durability(_row(YRBLT=2010), reference_year=2000)
    assert out["durability_score"] is None
    assert out["durability_condition"] is None
    # And the plausibility check itself is unaffected: a real 2024 build is still
    # a valid record, it simply cannot be scored as of 2000.
    assert D.effective_year(2024, None) == 2024.0
    assert D.model_parcel_durability(_row(YRBLT=2024),
                                     reference_year=2026)["durability_score"] is not None


# ── Confidence ───────────────────────────────────────────────────────────────
def test_trajectory_confidence_never_exceeds_the_snapshot():
    label = {"dimensions": [{"key": "durability", "score": 60.0},
                            {"key": "climate", "score": 50.0}],
             "location_notes": {}}
    snap = C.confidence_for_label(label)
    traj = C.confidence_for_trajectory(label, V.TRAJECTORY)
    order = {"low": 0, "moderate": 1, "high": 2}
    for key, tier in traj.items():
        assert order[tier] <= order[snap[key]], f"{key}: {tier} > {snap[key]}"
    # An unmeasured basis caps a High snapshot at Moderate: durability's snapshot
    # is High (it is a measured CAMA record), but ageing it is arithmetic.
    assert snap["durability"] == "high" and traj["durability"] == "moderate"


def test_boundary_revision_downgrades_a_tier():
    from dataclasses import replace
    label = {"dimensions": [{"key": "durability", "score": 60.0}], "location_notes": {}}
    spec = replace(V.TRAJECTORY["durability"], boundary_basis="2010→2020 crosswalk")
    assert C.confidence_for_trajectory(label, {"durability": spec})["durability"] == "low"


# ── The endpoint's guardrail ─────────────────────────────────────────────────
def test_timeline_runs_exactly_one_scoring_pass():
    """A timeline must cost exactly one label's worth of work, whatever it asks for.

    This is the property that lets /timeline be a separate endpoint at all: every
    trajectory point is read or recomputed from data already resident after the
    single scoring pass, so the only upstream traffic is that pass's own.

    Pinned at ``build_label_parts`` rather than by counting HTTP calls, because
    the upstream fetchers are all ``lru_cache``d — a second pass would make zero
    new requests in a warm process and a call-counting test would pass while the
    thing it guards against was happening. This catches the obvious future
    mistake, which is threading a whole-label as-of through here by re-running
    the pass per year: that re-hits PVGIS and TIGERweb once per year requested,
    on a cold cache, for a label whose composite is computed on a yardstick that
    doesn't apply to it.
    """
    real = H.build_label_parts
    calls = []

    def counting(*a, **kw):
        calls.append(kw)
        return real(*a, **kw)

    H.build_label_parts = counting
    try:
        for years in ([2026], [2000, 2010, 2020, 2026, 2040]):
            calls.clear()
            H.timeline_comparison(lat=35.15, lon=-89.85, preset="baseline",
                                  allow_network=False, years=years)
            assert len(calls) == 1, (
                f"{len(calls)} scoring passes for {len(years)} year(s) — a "
                "trajectory point must never trigger its own pass")
    finally:
        H.build_label_parts = real


# ── The assembled payload ────────────────────────────────────────────────────
def test_timeline_payload_shape():
    out = H.timeline_comparison(lat=35.15, lon=-89.85, preset="baseline",
                                allow_network=False, years=[2000, 2026, 2040])
    assert out["yardstick"] == "fixed"
    assert out["legend"] == V.TRAJECTORY_LEGEND
    # series and point_in_time partition the roster, at request time and not just
    # in the registry — a series that failed to resolve still owes a reason.
    roster = {k for k, _ in DIMENSIONS}
    assert set(out["series"]) | set(out["point_in_time"]) == roster
    assert not (set(out["series"]) & set(out["point_in_time"]))
    for key, s in out["series"].items():
        assert s["basis"] in V.BASES
        assert len(s["points"]) >= 2, f"{key}: a single point is not a trajectory"
        assert s["delta"] == round(s["points"][-1]["score"] - s["points"][0]["score"], 1)


def test_no_percentile_off_the_calibration_vintage():
    """"Beats N% of US homes" renders with no qualifier, so it must not appear on
    a point whose reference distribution was built for a different horizon."""
    out = H.timeline_comparison(lat=35.15, lon=-89.85, preset="baseline",
                                allow_network=False)
    climate = out["series"]["climate"]
    assert "national_percentile" not in climate["points"][0]     # recent past
    assert climate["points"][1]["national_percentile"] is not None
    assert climate["percentile_basis"]


def test_building_axis_sweep_reproduces_the_real_axis():
    """At the present as-of, the swept Building grade must equal the label's own.

    Substituting one member's percentile into the axis mean is exact rather than
    approximate — but only while durability really is the sole member that moves
    with the calendar. If that stops being true this fails, which is the point.
    """
    cfg, r, label = H.build_label_parts(lat=35.15, lon=-89.85, preset="baseline",
                                        allow_network=False)
    full = H.label_payload(cfg, r, label)
    dur = next(d for d in full["dimensions"] if d["key"] == "durability")
    got = H._building_axis_at(label, dur["score"])
    assert got["building_score"] == full["construction_score"]
    assert got["building_national_grade"] == full["construction_national_grade"]


def test_years_are_validated():
    for bad in (["nineteen"], [1500], [3000], [2000.5]):
        try:
            H.timeline_comparison(lat=35.15, lon=-89.85, preset="baseline",
                                  allow_network=False, years=bad)
        except ValueError:
            continue
        raise AssertionError(f"{bad!r} should have been rejected")


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} tests passed.")


if __name__ == "__main__":
    _run_all()
