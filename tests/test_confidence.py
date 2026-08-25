#!/usr/bin/env python3
"""Offline tests for the shared confidence rubric (housing_label.confidence).

No network — exercises the provenance → tier rubric
(research/uncertainty-confidence-research.md §3) and the climate score-band
parser against a mock label dict (the shape produced by
simulate_all_dimensions and consumed by both the API payload and the generator).

Run directly:  python tests/test_confidence.py
"""

import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parent.parent
for _p in (_ROOT, _ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from housing_label.confidence import (  # noqa: E402
    confidence_for_label, bands_for_label, confidence_notes_for_label,
    year_built_display, WIDE_BAND_DIMS, _PROVENANCE_SENSITIVE,
)

_DIM_KEYS = ["resilience", "energy", "durability", "environmental",
             "infrastructure", "health", "air_quality", "noise", "socioeconomic",
             "walkability", "climate", "solar", "water"]


def _mock_label(scores=None, notes=None, metrics=None):
    """A stand-in for simulate_all_dimensions() output."""
    scores = scores or {}
    return {
        "dimensions": [{"key": k, "score": scores.get(k, 70.0)} for k in _DIM_KEYS],
        "location_notes": notes if notes is not None else {
            "health": "CDC PLACES (tract 47157003100)",
            "air_quality": "CDC Tracking PM2.5/ozone (tract 47157003100) + EPA radon zone (county 47157)",
            "noise": "BTS transportation-noise exposure (tract 47157003100)",
            "socioeconomic": "no CENSUS_API_KEY",
            "walkability": "EPA National Walkability Index (tract 47157003100)",
            "climate": "CMIP6-LOCA2 (tract 47157003100, SSP2-4.5 mid-century)",
            "solar": "PVGIS-NSRDB rooftop yield (county 47157)",
            "water": "EPA SDWIS drinking-water compliance (county 47157)",
        },
        "metrics": metrics if metrics is not None else {
            "Climate band (SSP2-4.5–5-8.5, mid-century)": "49.6–47.0",
        },
    }


def test_tiers_match_research_doc_sample():
    """Reproduces the §3.3 worked table for the Cooper-Young sample
    (socioeconomic/walkability null → Low; env/infra/climate → Moderate)."""
    scores = {"socioeconomic": None, "walkability": None}
    tiers = confidence_for_label(_mock_label(scores=scores))
    assert tiers == {
        "resilience": "high", "energy": "high", "durability": "high",
        "environmental": "moderate", "infrastructure": "moderate", "health": "high",
        "air_quality": "high", "noise": "high", "solar": "high", "water": "high",
        "socioeconomic": "low", "walkability": "low", "climate": "moderate",
    }, tiers


def test_unscored_dimension_is_low():
    """A dimension with no score (e.g. vacant-parcel durability) → Low."""
    tiers = confidence_for_label(_mock_label(scores={"durability": None}))
    assert tiers["durability"] == "low", tiers


def test_measured_survey_dims_high_when_scored():
    """With a measured-source note (no 'no …KEY' signal) and a real score, socio/
    walk are measured → High, not Low."""
    tiers = confidence_for_label(_mock_label(notes={
        "socioeconomic": "Census ACS (tract 47157003100)",
        "walkability": "EPA National Walkability Index (tract 47157003100)",
    }))
    assert tiers["socioeconomic"] == "high", tiers
    assert tiers["walkability"] == "high", tiers


def test_wide_band_dims_capped_at_moderate():
    tiers = confidence_for_label(_mock_label())
    for k in ("environmental", "infrastructure", "climate"):
        assert tiers[k] == "moderate", (k, tiers[k])


# --- construction provenance ---------------------------------------------------
#
# Until the accuracy harness ran, a durability grade computed from a census-tract
# median year built was labelled as confidently as one computed from the county's
# record of the building. These pin the retune that measurement forced, including
# the exemption it also forced.


def _with_building(status, **overrides):
    """A label whose construction profile all carries one provenance status."""
    label = _mock_label()
    fields = ("year_built", "sqft", "condition", "foundation", "construction")
    label["building"] = {f: {"status": overrides.get(f, status)} for f in fields}
    return label


def test_an_area_typical_caps_the_dimensions_it_measurably_moves():
    """Measured over 217 addresses: with the construction profile assumed, the
    durability and energy letters differ from the truth 37.3% of the time. A tier
    this module itself calls High cannot mean "wrong one time in three"."""
    tiers = confidence_for_label(_with_building("assumed"))
    assert tiers["durability"] == "moderate"
    assert tiers["energy"] == "moderate"


def test_resilience_is_not_capped_because_the_measurement_says_not_to():
    """The deliberate exemption, and the judgement most worth revisiting.

    Resilience moved on 2.8% of Cook addresses and 8.7% of DC ones — the second
    figure arrived only after a second jurisdiction was measured, and is three times
    the first. It is still four to six times below durability's 37-50%, so the
    exemption stands on magnitude rather than on a bright line. Pinned here so that
    a later tidy-up has to argue with the measurement rather than quietly restore
    symmetry — and so that a third jurisdiction landing nearer durability makes this
    test the place the decision gets reopened.
    """
    assert confidence_for_label(_with_building("assumed"))["resilience"] == "high"


def test_a_record_of_the_building_is_not_capped():
    """estimated (NSI's record of this structure), observed (a county's) and
    confirmed (the reader's) all describe the building rather than the area, so none
    of them trips the cap."""
    for status in ("estimated", "observed", "confirmed"):
        tiers = confidence_for_label(_with_building(status))
        assert tiers["durability"] == "high", status
        assert tiers["energy"] == "high", status


def test_one_assumed_driver_is_enough_to_cap_its_own_dimension():
    """The cap is per dimension, over that dimension's own primary drivers. An
    assumed year built reaches durability and energy; it is not among the drivers
    the environmental model varies on, so it must not be attributed there."""
    label = _with_building("observed", year_built="assumed")
    tiers = confidence_for_label(label)
    assert tiers["durability"] == "moderate", "year_built drives the age basket"
    assert tiers["energy"] == "moderate", "year_built picks the ResStock vintage cell"


def test_a_label_with_no_construction_profile_is_unchanged():
    """Not every caller builds a building block (the trajectory path does not). A
    missing profile is not a stand-in, and must not be read as one."""
    tiers = confidence_for_label(_mock_label())
    assert tiers["durability"] == "high" and tiers["energy"] == "high"


def test_a_capped_dimension_says_why_on_the_dot():
    """A dot that changes colour with no reason is worse than no cap: the reader
    cannot tell whether the source is weak in general or weak for their address —
    and the second is fixable by them, in the panel directly above."""
    notes = confidence_notes_for_label(_with_building("assumed"))
    assert "neighbourhood typical" in notes["durability"]
    assert "Correcting the building details" in notes["durability"]
    # The base description must survive, not be replaced by the caveat.
    assert "Component-lifespan model" in notes["durability"]


def test_the_note_only_goes_where_correcting_the_details_would_actually_help():
    """The note's promise, tested as a promise.

    It tells the reader that correcting the building details resolves the cap. So
    for every dimension carrying it, doing exactly that must lift the tier — and
    this is checked rather than reasoned about, because it was false in the
    shipped version: `environmental` is in both WIDE_BAND_DIMS and
    _PROVENANCE_SENSITIVE, its band capped it first, and the note still claimed
    the stand-in was the cause and offered an action that could not work.
    """
    stood_in = confidence_notes_for_label(_with_building("assumed"))
    before = confidence_for_label(_with_building("assumed"))
    after = confidence_for_label(_with_building("observed"))
    for key, note in stood_in.items():
        if "neighbourhood typical" not in note:
            continue
        assert before[key] == "moderate", key
        assert after[key] == "high", (
            f"{key}'s note promises that correcting the building details resolves "
            f"the cap, but with every driver observed it is still {after[key]}. "
            f"Either the note does not belong on {key} or the tier is wrong.")


def test_a_dimension_capped_for_its_band_does_not_claim_a_standin_caused_it():
    """environmental is wide-band AND provenance-sensitive. The band caps it first,
    so the stand-in explanation would be the wrong cause on a real address."""
    notes = confidence_notes_for_label(_with_building("assumed"))
    assert "environmental" in WIDE_BAND_DIMS and "environmental" in _PROVENANCE_SENSITIVE
    assert "neighbourhood typical" not in notes["environmental"]
    # The base description still has to be there — the dot still needs its note.
    assert "eGRID2023" in notes["environmental"]


def test_an_unscored_dimension_does_not_blame_a_standin():
    """No score means no letter to be wrong about. The dot is Low because nothing
    was computed, and saying otherwise sends the reader to fix the wrong thing."""
    label = _with_building("assumed")
    for d in label["dimensions"]:
        if d["key"] == "durability":
            d["score"] = None
    notes = confidence_notes_for_label(label)
    assert confidence_for_label(label)["durability"] == "low"
    assert "neighbourhood typical" not in notes["durability"]


def test_an_uncapped_dimension_note_is_left_alone():
    notes = confidence_notes_for_label(_with_building("observed"))
    assert "neighbourhood typical" not in notes["durability"]
    assert "neighbourhood typical" not in notes["resilience"]


# --- how a stand-in year is shown ----------------------------------------------


def test_an_area_typical_year_is_shown_as_the_range_it_came_from():
    """A bare number reads as a fact about the building. This is the one field whose
    whole difficulty is that it usually is not one."""
    out = year_built_display({"year_built": {"value": 2002, "status": "assumed",
                                             "typical_range": [1993, 2007]}})
    assert out == "1993\u20132007 (area typical)"


def test_a_stand_in_with_no_range_still_says_it_is_one():
    """The range comes from the ACS distribution and does not always resolve. Losing
    it must not silently turn the value back into a plain assertion."""
    out = year_built_display({"year_built": {"value": 2002, "status": "assumed"}})
    assert out == "~2002 (area typical)"


def test_a_year_about_this_building_is_stated_plainly():
    for status in ("confirmed", "observed", "estimated"):
        assert year_built_display(
            {"year_built": {"value": 2005, "status": status}}) == "2005", status


def test_no_year_produces_no_claim():
    assert year_built_display(None) is None
    assert year_built_display({}) is None
    assert year_built_display({"year_built": {"value": None, "status": "assumed"}}) is None


def test_the_browser_card_uses_the_same_wording_as_the_server():
    """docs/label-core.js reimplements this rule (the card renders without calling
    Python). The logic cannot be shared, so the WORDING is pinned here: a change on
    one side that leaves the other alone would show two different phrasings of the
    same fact on the same page.

    This guards the phrasing, not the branching — the JS is not executed here.
    """
    js = (_ROOT / "docs" / "label-core.js").read_text()
    suffix = year_built_display(
        {"year_built": {"value": 2002, "status": "assumed"}}).split(" ", 1)[1]
    assert suffix in js, f"{suffix!r} not found in label-core.js"
    assert "\\u2013" in js or "\u2013" in js, "the range separator drifted"
    assert '"~"' in js or "'~'" in js or '"~" +' in js, (
        "the no-range form drifted; Python still emits a ~ prefix")


def test_bands_parse_climate_interval():
    """'49.6–47.0' → {low: 47.0, high: 49.6} (ordered by magnitude)."""
    assert bands_for_label(_mock_label()) == {"climate": {"low": 47.0, "high": 49.6}}


def test_bands_absent_without_climate_metric():
    assert bands_for_label(_mock_label(metrics={})) == {}


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} tests passed.")


if __name__ == "__main__":
    _run_all()
