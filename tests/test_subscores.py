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

    from housing_label.data.national_percentile import national_percentile
    vals = [pct[k] for k in CONSTRUCTION_DRIVEN if pct[k] is not None]
    # Plus resilience's BUILDING leg, which is a construction fact living inside a
    # dimension that reports as one number. It joins as a PERCENTILE, like every
    # other member — appending the raw 0-100 leg would put an absolute score back
    # into a mean of percentiles.
    vals.append(national_percentile("resilience", p["resilience_building_score"]))
    assert p["construction_n_scored"] == len(vals)
    assert abs(p["construction_raw_mean"] - round(sum(vals) / len(vals), 1)) < 0.05


def test_both_axes_are_ranked_the_same_way():
    """The symmetry that makes the two headline letters comparable. Before this,
    only the site axis was a rank against US homes — so "Building B / Site C" put
    two different kinds of claim side by side and gave a reader no way to tell.

    Measured over the calibration panels: unranked, the site axis put 0% of
    households in A, 0% in F and 70.7% in C, while the building axis spread but
    skewed (A 14.4% / B 31.4%). Ranked, both sit within a point or two of 20% per
    band — the letters are quintiles on both."""
    from housing_label.data.national_percentile import (
        BUILDING_XS, BUILDING_YS, LOCATION_XS, LOCATION_YS,
        building_percentile, location_percentile)
    for xs, ys in ((BUILDING_XS, BUILDING_YS), (LOCATION_XS, LOCATION_YS)):
        assert xs and ys and len(xs) == len(ys)
        assert all(a < b for a, b in zip(xs, xs[1:])), xs
        assert ys[0] == 1.0 and ys[-1] == 99.0

    p = _payload()
    assert p["construction_score"] == building_percentile(p["construction_raw_mean"])
    assert p["location_score"] == location_percentile(p["location_raw_mean"])


def test_the_building_axis_spread_did_not_make_it_a_percentile():
    """Why this was easy to miss: unlike the site axis, the raw building mean
    already used the whole 0-100 range, so nothing looked broken. It still was not
    a rank — a raw 53.8 is the MEDIAN US home while grading C."""
    from housing_label.data.national_percentile import BUILDING_XS, building_percentile
    assert BUILDING_XS[0] < 20.0 and BUILDING_XS[-1] > 80.0, \
        "the raw building range reaches both thresholds — that is the trap"
    median_home = BUILDING_XS[4]
    assert building_percentile(median_home) == 50.0, median_home


def test_the_location_axis_is_ranked_against_where_households_live():
    """A mean of percentiles cannot reach the ends of a 0-100 ruler: measured over
    6,000 household-weighted tracts the raw mean runs 36.6 (p1) to 73.9 (p99), so
    on absolute thresholds an A and an F were both unreachable."""
    from housing_label.data.national_percentile import (
        LOCATION_XS, location_percentile)
    assert LOCATION_XS[0] > 20.0 and LOCATION_XS[-1] < 80.0, \
        "if the raw range reached the thresholds, no ranking would be needed"
    assert all(a < b for a, b in zip(LOCATION_XS, LOCATION_XS[1:]))

    from housing_label.data.national_percentile import national_percentile
    p = _payload()
    vals = [d["national_percentile"] for d in p["dimensions"]
            if d["key"] in AGGREGATED_LOCATION and d["national_percentile"] is not None]
    # Plus resilience's SITE leg — the hazard with a neutral building, likewise
    # converted to a percentile before it joins the mean.
    vals.append(national_percentile("resilience", p["resilience_site_score"]))
    assert p["location_n_scored"] == len(vals)
    assert abs(p["location_raw_mean"] - round(sum(vals) / len(vals), 1)) < 0.05
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


# ── What the reader actually sees ────────────────────────────────────────────
# The split is only real if the card renders it. It did not: the payload carried
# both axes and the renderer read `composite_score` alone, so three PRs of
# taxonomy, decomposition and calibration shipped behind a UI that still showed
# one number. Nothing in the Python suite could notice — the renderer is JS.
_LABEL_JS = _ROOT / "docs" / "label-core.js"

_AXIS_FIELDS = ("construction_score", "construction_national_grade",
                "location_score", "location_national_grade")


def test_the_renderer_reads_both_axes():
    """A pure-text guard that needs no JS engine, so it runs everywhere. Renaming
    an axis field in the payload without touching the card fails here."""
    js = _LABEL_JS.read_text()
    for field in _AXIS_FIELDS:
        assert f"data.{field}" in js, f"{field} is emitted but never rendered"


def _render(payload):
    """Run the real renderer under node and return its HTML.

    `esc` reaches for `document`, so the shim below is the minimum DOM the card
    touches — enough to exercise the actual shipped code rather than a copy of
    its logic re-implemented in the test.
    """
    import json
    import shutil
    import subprocess

    node = shutil.which("node")
    if not node:                                        # pragma: no cover
        import pytest
        pytest.skip("node not available")
    script = """
      global.document = { createElement: () => ({
        set textContent(v) { this._t = String(v); },
        get innerHTML() { return this._t.replace(/&/g, "&amp;")
          .replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;"); } }) };
      global.window = {};
      eval(require("fs").readFileSync(process.argv[1], "utf8"));
      process.stdout.write(window.LabelCore.renderCard(
        JSON.parse(process.argv[2]), {heading: "x"}));
    """
    out = subprocess.run([node, "-e", script, str(_LABEL_JS), json.dumps(payload)],
                         capture_output=True, text=True, check=True)
    return out.stdout


def test_the_card_shows_both_grades():
    """End to end through the shipped renderer: the two letters and both
    percentiles reach the markup."""
    p = _payload(year_built=2025, condition="excellent")
    html = _render(p)
    assert "axis-pair" in html
    assert f'>{round(p["construction_score"])}<' in html
    assert f'>{round(p["location_score"])}<' in html
    # Two distinct grades, each in its own cell — not the composite twice.
    cells = html.split('class="axis-cell"')[1:]
    assert len(cells) == 2
    assert f'>{p["construction_national_grade"]}<' in cells[0]
    assert f'>{p["location_national_grade"]}<' in cells[1]


def test_the_percentile_suffix_agrees_with_its_number():
    """"51th pct" — the suffix was a fixed string in the markup while the number
    beside it is data. Every ordinal the axes can produce is exercised, including
    the 11/12/13 exception that a naive last-digit rule gets wrong."""
    import re
    expected = {1: "st", 2: "nd", 3: "rd", 11: "th", 12: "th", 13: "th",
                21: "st", 42: "nd", 53: "rd", 80: "th", 99: "th", 0: "th"}
    for n, suffix in expected.items():
        html = _render({"dimensions": [], "construction_score": float(n),
                        "construction_national_grade": "C",
                        "location_score": float(n),
                        "location_national_grade": "C"})
        got = re.findall(r'axis-num">(\d+)<span class="axis-pct">(\w+) pct', html)
        assert got and all(g == (str(n), suffix) for g in got), (n, got)


def test_an_unscorable_axis_does_not_invent_a_percentile():
    """With no axis to show the block is omitted outright, rather than rendering
    "N/A th pct" or a grey chip that reads as a real grade."""
    html = _render({"dimensions": [], "construction_score": None,
                    "construction_national_grade": None,
                    "location_score": None, "location_national_grade": None})
    assert "axis-pair" not in html


if __name__ == "__main__":
    for _name, _fn in sorted(list(globals().items())):
        if _name.startswith("test_"):
            _fn()
            print(f"  ok  {_name}")
    print("subscore tests passed")
