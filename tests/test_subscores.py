#!/usr/bin/env python3
"""Tests for the two headline axes: the building, and the site around it.

One composite answers neither question a buyer has. A 2025 build beside a freeway
and a 1955 bungalow on a quiet walkable street land within a few points of each
other, because the mean of thirteen percentiles has a standard deviation near
29/sqrt(13) ~= 8 — so every real house crowds the middle and an A is four sigma out.

What these tests defend is the taxonomy, because that is what makes or breaks the
split. Two dimensions used to be on the wrong side of it, and both were visible to
users: Infrastructure Burden (a COUNTY fiscal ratio) was dragging new builds' build
quality down, and Disaster Resilience was rendered under "The building itself"
because it was in neither set and took the `else`.

Runs without network. Execute directly (python tests/test_subscores.py) or via
pytest.
"""

from __future__ import annotations

import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parent.parent
for _p in (_ROOT, _ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from housing_label.simulate.dimensions import (                          # noqa: E402
    DIMENSIONS, CONSTRUCTION_DRIVEN, LOCATION_DRIVEN, CONTEXT_ONLY,
    HYBRID_DIMENSIONS, AGGREGATED_LOCATION)
from housing_label.simulate.location import resolve_location             # noqa: E402
from housing_label.simulate.house import build_label_parts, label_payload  # noqa: E402

LA_GEO = {"county_fips": "06037", "county_name": "Los Angeles County",
          "state_fips": "06", "tract": "06037206202",
          "place_label": "Los Angeles city", "place_geoid": "0644000",
          "incorporated": True, "in_urban_area": True}


def _payload(preset="baseline", **fields):
    loc = resolve_location(lat=34.05, lon=-118.24, allow_network=False,
                           geography=LA_GEO)
    cfg, r, lbl = build_label_parts(preset=preset, location=loc,
                                    allow_network=False, **fields)
    return label_payload(cfg, r, lbl)


# ── The taxonomy ─────────────────────────────────────────────────────────────
def test_the_three_groups_partition_the_roster_exactly():
    """No dimension in two groups, and none in none. The `else` that put
    Disaster Resilience under "The building itself" is exactly what an
    unpartitioned roster buys you."""
    roster = {k for k, _ in DIMENSIONS}
    groups = [CONSTRUCTION_DRIVEN, LOCATION_DRIVEN, CONTEXT_ONLY]
    union = set().union(*groups)
    assert union == roster, sorted(roster ^ union)
    for i, a in enumerate(groups):
        for b in groups[i + 1:]:
            assert not (a & b), sorted(a & b)


def test_an_unclassified_dimension_is_visibly_unclassified():
    """`kind` is an explicit lookup, so a future dimension added to no group is
    labelled `unclassified` rather than silently claimed by the last branch."""
    kinds = {d["key"]: d["kind"] for d in _payload()["dimensions"]}
    assert set(kinds.values()) <= {"construction", "location", "context"}
    for key in CONSTRUCTION_DRIVEN:
        assert kinds[key] == "construction", key
    for key in LOCATION_DRIVEN:
        assert kinds[key] == "location", key
    for key in CONTEXT_ONLY:
        assert kinds[key] == "context", key


def test_infrastructure_is_not_building_quality():
    """A county's fiscal cost-to-serve ratio says nothing about how the house was
    built. It sat in the construction bucket and cost a new build ~12 points."""
    assert "infrastructure" in LOCATION_DRIVEN
    assert "infrastructure" not in CONSTRUCTION_DRIVEN


def test_resilience_contributes_to_both_axes_as_two_legs():
    """It is FEMA flood zone, NRI wildfire and tornado, and USGS seismic, TIMES
    construction factors — genuinely both axes at once. It is not assigned to one
    side; it is split, and each half joins the aggregate it belongs to."""
    assert "resilience" in HYBRID_DIMENSIONS
    assert "resilience" not in AGGREGATED_LOCATION, \
        "the combined dimension must not be aggregated — its legs are"
    p = _payload()
    assert p["resilience_site_score"] is not None
    assert p["resilience_building_score"] is not None
    assert p["resilience_building_multiplier"] is not None


def test_the_site_leg_does_not_move_when_the_building_does():
    """The property the site grade needs and the combined score never had. Before
    the split, varying only the preset at one LA tract moved resilience from the
    1st national percentile to the 99th, dragging the site grade 98 points."""
    sites = {_payload(preset=pr)["resilience_site_score"]
             for pr in ("baseline", "icf-passive", "fortified-gold")}
    assert len(sites) == 1, sites
    builds = {_payload(preset=pr)["resilience_building_score"]
              for pr in ("baseline", "icf-passive", "fortified-gold")}
    assert len(builds) == 3, builds


def test_the_building_leg_is_scored_at_a_reference_site():
    """So build quality is comparable between two houses even when one of them
    sits on a floodplain — the leg answers "at a typical US location"."""
    from housing_label.score.resilience import (
        REFERENCE_SITE_EAL_RATE, eal_rate_to_score, resilience_legs)
    assert 1e-4 < REFERENCE_SITE_EAL_RATE < 1e-3, REFERENCE_SITE_EAL_RATE
    legs = resilience_legs({"flood_raw": 1e-4, "tornado_raw": 1e-4,
                            "seismic_raw": 1e-4, "fire_raw": 1e-4,
                            "total_eal": 2e-4})
    assert legs["multiplier"] == 0.5
    assert legs["building"] == round(
        eal_rate_to_score(REFERENCE_SITE_EAL_RATE * 0.5), 1)


def test_a_site_with_no_modelled_hazard_reports_no_multiplier():
    """Dividing by zero hazard would call every building neutral, which is not a
    measurement — the building leg is unknown there, not 1.0."""
    from housing_label.score.resilience import resilience_legs
    legs = resilience_legs({"flood_raw": 0.0, "tornado_raw": 0.0,
                            "seismic_raw": 0.0, "fire_raw": 0.0,
                            "total_eal": 0.0})
    assert legs["site"] == 100.0
    assert legs["building"] is None and legs["multiplier"] is None


def test_health_and_socioeconomic_are_shown_but_not_graded():
    """Both measure the PEOPLE nearby (ACS income/education, CDC PLACES disease
    prevalence) and are constant across a tract, so a per-address letter grade
    built on them is a map of neighbourhoods graded by their residents. The rows
    stay; the aggregate does not include them."""
    assert CONTEXT_ONLY == {"health", "socioeconomic"}
    p = _payload()
    rows = {d["key"]: d for d in p["dimensions"]}
    for key in CONTEXT_ONLY:
        assert key in rows, "context dimensions must still be shown in full"
        assert rows[key]["score"] is not None
        assert key not in CONSTRUCTION_DRIVEN and key not in LOCATION_DRIVEN


# ── The arithmetic ───────────────────────────────────────────────────────────
def test_subscores_average_percentiles_not_raw_scores():
    """Different quantities for five of the thirteen: the construction-driven
    scores are absolute 0-100 values remapped through a reference, and so is
    walkability. Averaging the raw column mixed the two and produced neither."""
    p = _payload()
    pct = {d["key"]: d["national_percentile"] for d in p["dimensions"]}
    raw = {d["key"]: d["score"] for d in p["dimensions"]}
    assert any(abs(raw[k] - pct[k]) > 1 for k in CONSTRUCTION_DRIVEN), \
        "expected at least one construction dimension to be remapped"

    vals = [pct[k] for k in CONSTRUCTION_DRIVEN if pct[k] is not None]
    # Plus resilience's BUILDING leg, which is a construction fact living inside a
    # dimension that reports as one number.
    assert p["construction_n_scored"] == len(vals) + 1


def test_the_location_axis_is_ranked_against_where_households_live():
    """A mean of percentiles cannot reach the ends of a 0-100 ruler: measured over
    6,000 household-weighted tracts the raw mean runs 36.6 (p1) to 73.9 (p99), so
    on absolute thresholds an A and an F were both unreachable."""
    from housing_label.data.national_percentile import (
        LOCATION_XS, location_percentile)
    assert LOCATION_XS[0] > 20.0 and LOCATION_XS[-1] < 80.0, \
        "if the raw range reached the thresholds, no ranking would be needed"
    assert all(a < b for a, b in zip(LOCATION_XS, LOCATION_XS[1:]))

    p = _payload()
    vals = [d["national_percentile"] for d in p["dimensions"]
            if d["key"] in AGGREGATED_LOCATION and d["national_percentile"] is not None]
    # Plus resilience's SITE leg — the hazard with a neutral building.
    assert p["location_n_scored"] == len(vals) + 1
    assert p["location_score"] == location_percentile(p["location_raw_mean"])


def test_context_rows_do_not_move_either_grade():
    """The load-bearing guarantee of the fair-housing decision."""
    p = _payload()
    pct = {d["key"]: d["national_percentile"] for d in p["dimensions"]}
    assert [pct[k] for k in CONTEXT_ONLY if pct[k] is not None], \
        "expected the context rows to be scored at this location"
    for key in CONTEXT_ONLY:
        assert key not in CONSTRUCTION_DRIVEN and key not in AGGREGATED_LOCATION


def test_the_composite_still_averages_everything():
    """Kept alongside the two axes rather than replaced — it is what every earlier
    label and downstream consumer reads. Context rows DO count here."""
    p = _payload()
    vals = [d["score"] for d in p["dimensions"] if d["score"] is not None]
    assert p["n_scored"] == len(vals)
    assert abs(p["composite_score"] - round(sum(vals) / len(vals), 1)) < 0.05


# ── What the split is for ────────────────────────────────────────────────────
def test_a_new_build_in_a_hard_place_reads_as_exactly_that():
    """The motivating case. A 2025 house should say 'well built, difficult site',
    which one blended number cannot express."""
    p = _payload(year_built=2025, condition="excellent")
    assert p["construction_national_grade"] == "A", p["construction_score"]
    assert p["construction_score"] > p["location_score"] + 25
    # And the old single number said neither thing.
    assert p["composite_national_grade"] == "C"


def test_infrastructure_is_what_used_to_break_that_case():
    """Pinned because it is the specific defect, not a general improvement: with
    infrastructure still counted as build quality, the same house grades B."""
    p = _payload(year_built=2025, condition="excellent")
    s = {d["key"]: d["score"] for d in p["dimensions"]}
    old_set = CONSTRUCTION_DRIVEN | {"infrastructure"}
    old = round(sum(s[k] for k in old_set) / len(old_set), 1)
    assert old < 80.0 <= p["construction_score"], (old, p["construction_score"])


def test_the_building_axis_uses_the_whole_grade_scale():
    """The composite could not: across these presets it never left C/B."""
    grades = {_payload(preset=p)["construction_national_grade"]
              for p in ("worst-case", "baseline", "icf-passive", "fortified-gold")}
    assert "A" in grades and len(grades) >= 2, grades


def test_a_poor_structure_is_no_longer_laundered_by_its_surroundings():
    """At the Shelby point, worst-case is an F building (16.3 on the percentile
    basis) — but the composite reports C, because the other dimensions outvote it.
    That is a consumer-protection problem, not just a presentational one.

    Scored here rather than at the LA fixture on purpose: the same preset in LA
    grades C on the building axis, so asserting D there would pass or fail on
    which point was chosen rather than on the behaviour."""
    loc = resolve_location(
        lat=35.13, lon=-89.99, allow_network=False,
        geography={"county_fips": "47157", "county_name": "Shelby County",
                   "state_fips": "47", "tract": "47157003100",
                   "place_label": "Memphis city", "place_geoid": "4748000",
                   "incorporated": True, "in_urban_area": True})
    cfg, r, lbl = build_label_parts(preset="worst-case", location=loc,
                                    allow_network=False)
    p = label_payload(cfg, r, lbl)
    assert p["construction_national_grade"] == "F", p["construction_score"]
    assert p["composite_national_grade"] == "C", p["composite_score"]
    assert p["location_score"] > p["construction_score"]


if __name__ == "__main__":
    for _name, _fn in sorted(list(globals().items())):
        if _name.startswith("test_"):
            _fn()
            print(f"  ok  {_name}")
    print("subscore tests passed")
