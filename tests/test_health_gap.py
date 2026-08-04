#!/usr/bin/env python3
"""Tests for the states CDC PLACES does not cover.

Health Impact is built from seven BRFSS-derived outcome measures in CDC PLACES.
Two mainland states carry none of them: Kentucky and Pennsylvania appear in the
PLACES tract dataset only for the 2022 vintage and only for five PREVENTION
measures (colon screening, dental visits, mammography, sleep, teeth lost), and are
absent from the 2023 release entirely. That is ~17.5M people.

The scoring was already right — the dimension is left unscored rather than filled
with the national average. What these tests defend is the EXPLANATION. "no health
data for tract 42101000100" points a Philadelphian at their own neighbourhood for a
gap that is statewide and upstream, and reads as a bad tract id.

They also pin which states are affected, so a later PLACES release that restores
them shows up as a failure here rather than going unnoticed.

Runs without network. Execute directly (python tests/test_health_gap.py) or via
pytest.
"""

from __future__ import annotations

import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parent.parent
for _p in (_ROOT, _ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from housing_label.data import health as health_data                     # noqa: E402
from housing_label.data.states import usps_for_fips                      # noqa: E402
from housing_label.simulate.location import Location                     # noqa: E402
from housing_label.simulate.house import build_label_parts               # noqa: E402

KY, PA, TN = "21", "42", "47"


def _label(state_fips: str, county: str, tract: str):
    loc = Location(lat=39.95, lon=-75.17, state_fips=state_fips, county_fips=county,
                   county_name="test", tract=tract, place_label="test",
                   in_urban_area=True, climate_zone="4A", egrid_subregion=None,
                   egrid_factor=None, climate_projection=None, wildfire=None,
                   structure_type="single_family", num_units=1, notes=None)
    _c, _r, lbl = build_label_parts(location=loc, allow_network=False, value=250_000)
    score = next(d["score"] for d in lbl["dimensions"] if d["key"] == "health")
    return score, lbl["location_notes"].get("health", "")


# ── Which states are missing ─────────────────────────────────────────────────
def test_kentucky_and_pennsylvania_have_no_places_data():
    gap = health_data.states_without_data()
    assert KY in gap and PA in gap, sorted(gap)


def test_the_gap_set_is_derived_from_the_bundle_not_hardcoded():
    """So a later PLACES release that restores these states empties the set and
    stops the caveat being emitted, without anyone editing a literal."""
    covered = {g[:2] for g in health_data._county_table() if g != "00000"}
    assert covered, "expected a bundled county table"
    assert not (health_data.states_without_data() & covered)


def test_no_other_mainland_state_is_missing():
    """If a rebuild drops a state, that is a build regression rather than an
    upstream coverage fact, and it should fail here."""
    gap = health_data.states_without_data()
    mainland = {f for f in gap if f not in {"72"}}     # 72 = Puerto Rico
    assert mainland == {KY, PA}, sorted((f, usps_for_fips(f)) for f in mainland)


def test_puerto_rico_is_missing_too_and_that_is_upstream():
    """PLACES has never covered PR — distinct from KY/PA, which it covered before."""
    assert "72" in health_data.states_without_data()


def test_the_set_is_exactly_what_the_docstring_claims():
    """The answer comes from STATE_FIPS_TO_USPS, so it spans the 50 states, DC and
    PR and can never name AS/GU/MP/VI. Pinned because the docstring said otherwise
    once, and a scope claim nothing enforces is how that happened."""
    gap = health_data.states_without_data()
    assert gap == {KY, PA, "72"}, sorted(gap)
    assert not (gap & {"60", "66", "69", "78"}), \
        "the crosswalk omits these, so they cannot appear here"


# ── What the label says ──────────────────────────────────────────────────────
def test_an_uncovered_state_is_unscored_not_averaged():
    """The national row exists and would resolve; using it would present a home in
    an unmeasured place as an average one."""
    for state, county, tract in ((PA, "42101", "42101000100"),
                                 (KY, "21111", "21111000100")):
        score, _note = _label(state, county, tract)
        assert score is None, (state, score)


def test_the_note_names_the_state_and_the_scope():
    """Not the tract. The gap is statewide and upstream, and the note has to say so
    or it reads as a bad tract id."""
    for state, county, tract in ((PA, "42101", "42101000100"),
                                 (KY, "21111", "21111000100")):
        _score, note = _label(state, county, tract)
        assert usps_for_fips(state) in note, note
        assert "whole state" in note, note
        assert tract not in note, "the tract is not the reason; naming it misleads"


def test_the_note_says_why_it_is_not_filled_in():
    _score, note = _label(PA, "42101", "42101000100")
    assert "national average" in note


def test_a_covered_state_is_unaffected():
    score, note = _label(TN, "47157", "47157000100")
    assert score is not None
    assert "whole state" not in note


def test_a_missing_tract_in_a_covered_state_still_reads_as_a_tract_gap():
    """The statewide caveat must not swallow the ordinary case — an unknown tract
    in a covered state should still fall back to its county."""
    score, note = _label(TN, "47157", "47157999999")
    assert score is not None, "expected the county fallback"
    assert "whole state" not in note


if __name__ == "__main__":
    for _name, _fn in sorted(list(globals().items())):
        if _name.startswith("test_"):
            _fn()
            print(f"  ok  {_name}")
    print("health-gap tests passed")
