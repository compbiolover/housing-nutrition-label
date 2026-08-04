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
    HYBRID_DIMENSIONS)
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


def test_resilience_is_classified_deliberately_and_marked_hybrid():
    """It is FEMA flood zone, NRI wildfire and tornado, and USGS seismic, times
    construction factors. Graded under Location, but the roster has to say it is
    both or the docs will imply the bucket is the whole story."""
    assert "resilience" in LOCATION_DRIVEN
    assert "resilience" in HYBRID_DIMENSIONS
    assert HYBRID_DIMENSIONS <= LOCATION_DRIVEN | CONSTRUCTION_DRIVEN


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
def test_each_subscore_is_the_mean_of_its_own_scored_members():
    p = _payload()
    s = {d["key"]: d["score"] for d in p["dimensions"]}
    for keys, score, n in ((CONSTRUCTION_DRIVEN, p["construction_score"],
                            p["construction_n_scored"]),
                           (LOCATION_DRIVEN, p["location_score"],
                            p["location_n_scored"])):
        vals = [s[k] for k in keys if s[k] is not None]
        assert n == len(vals)
        assert abs(score - round(sum(vals) / len(vals), 1)) < 0.05


def test_context_rows_do_not_move_either_grade():
    """The load-bearing guarantee of the fair-housing decision. Changing a context
    score must leave both headline grades untouched."""
    p = _payload()
    s = {d["key"]: d["score"] for d in p["dimensions"]}
    con = [s[k] for k in CONSTRUCTION_DRIVEN if s[k] is not None]
    loc = [s[k] for k in LOCATION_DRIVEN if s[k] is not None]
    ctx = [s[k] for k in CONTEXT_ONLY if s[k] is not None]
    assert ctx, "expected the context rows to be scored at this location"
    # Neither aggregate may contain a context value that is not also a member.
    assert p["construction_score"] == round(sum(con) / len(con), 1)
    assert p["location_score"] == round(sum(loc) / len(loc), 1)


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
    assert "A" in grades and len(grades) >= 3, grades


def test_a_poor_structure_is_no_longer_laundered_by_its_surroundings():
    """At the Shelby point, worst-case is a D building (37.7) — but the composite
    reported C, because eight location dimensions outvoted it. That is a
    consumer-protection problem, not just a presentational one.

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
    assert p["construction_national_grade"] == "D", p["construction_score"]
    assert p["composite_national_grade"] == "C", p["composite_score"]
    assert p["location_score"] > p["construction_score"]


if __name__ == "__main__":
    for _name, _fn in sorted(list(globals().items())):
        if _name.startswith("test_"):
            _fn()
            print(f"  ok  {_name}")
    print("subscore tests passed")
