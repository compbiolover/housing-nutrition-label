#!/usr/bin/env python3
"""Golden-snapshot regression test for the scored label payload.

The rest of the suite asserts *relative* invariants (higher exposure → lower
score, perils summing to the total, structural field presence). None of that
catches a change that uniformly *shifts* absolute scores — a recalibrated
breakpoint, a re-weighted composite, a tweaked EAL constant — which would sail
through while silently moving every published grade.

This test locks the numeric core of ``label_payload`` for a fixed matrix of
``(preset × location)`` cases scored **offline** (``allow_network=False``), so the
output is fully deterministic. Every one of the thirteen dimensions is scored,
because each case supplies its Census geography rather than geocoding for it: the
geocode is the only network call needed to learn a point's county and tract, and
every crosswalk keyed off them is bundled. Offline without it, the county and tract
are unknown and the location dimensions silently score ``null`` — see ``SHELBY_GEO``
below for what that cost.

``allow_network=False`` still matters on top of that, and for a different reason.
It suppresses the enrichers that go out per parcel — NSI structure, building
footprint, EPA water system, TIGERweb road noise, PVGIS solar — each of which
degrades to a bundled or unscored value on its own. Supplying the geography does
not make those live; it only removes the one dependency that had no fallback.

Any intended recalibration must regenerate the snapshot, turning a would-be silent
drift into a reviewable diff:

    UPDATE_GOLDEN=1 python -m pytest tests/test_golden_label.py     # rewrite
    python -m pytest tests/test_golden_label.py                      # verify

Runs directly too:  ``python tests/test_golden_label.py``.
"""

import json
import os
import pathlib

from housing_label.simulate.house import build_label_parts, label_payload
from housing_label.simulate.location import resolve_location

GOLDEN = pathlib.Path(__file__).parent / "golden" / "label_snapshot.json"

# Census geography for the two fixture points, supplied rather than geocoded.
#
# These cases run offline, and offline USED TO mean no geocode, hence no county and
# no tract — which silently left every location dimension unscored. Health, Air
# Quality, Noise, Climate, Solar and Water were all `null` in all seven cases, and
# Shelby and Los Angeles produced IDENTICAL location legs, so the "cross-county
# point" below was pinning nothing about county-resolved scoring. Three
# recalibrations in a row (#255 solar-to-parcel, #257 solar weighting, #258 climate
# weighting) moved published grades and produced no diff here at all.
#
# Supplying the geography closes that: only the geocode step needs network, so the
# bundled crosswalks downstream resolve exactly as they do in production. Captured
# once from the live Census geocoder for these coordinates — real values, not
# invented ones — and frozen so the fixtures stay deterministic.
SHELBY_GEO = {
    "county_fips": "47157", "county_name": "Shelby County", "state_fips": "47",
    "tract": "47157003100", "place_label": "Memphis city", "place_geoid": "4748000",
    "incorporated": True, "in_urban_area": True,
}
LA_GEO = {
    "county_fips": "06037", "county_name": "Los Angeles County", "state_fips": "06",
    "tract": "06037206202", "place_label": "Los Angeles city",
    "place_geoid": "0644000", "incorporated": True, "in_urban_area": True,
}

# (name, preset, lat, lon, geography). Two Shelby profiles spanning the score range
# plus a cross-county (Los Angeles) point, so a change to the county- and
# tract-resolved legs is caught too.
CASES = [
    ("baseline_shelby",       "baseline",       35.13,  -89.99, SHELBY_GEO),
    ("worst_case_shelby",     "worst-case",     35.13,  -89.99, SHELBY_GEO),
    ("icf_passive_shelby",    "icf-passive",    35.13,  -89.99, SHELBY_GEO),
    ("fortified_gold_shelby", "fortified-gold", 35.13,  -89.99, SHELBY_GEO),
    ("baseline_la",           "baseline",       34.05, -118.24, LA_GEO),
    ("icf_passive_la",        "icf-passive",    34.05, -118.24, LA_GEO),
    # A multi-unit case, so property-tax classification actually fires in the snapshot.
    # Every other case is single-family at units=1, where the correction is a no-op by
    # design — without this row the snapshot pins only the yardstick, never the rule.
    ("quadplex_shelby",       "quadplex",       35.13,  -89.99, SHELBY_GEO),
]

# Round every float this many places before comparing/storing, so cross-platform
# / cross-Python floating-point noise can't flake the test. Scores are already
# emitted at 0.1 and dollar flows as ints, so 4 dp is comfortably lossless.
_PLACES = 4


def _round(v):
    return round(v, _PLACES) if isinstance(v, float) else v


def _core(preset: str, lat: float, lon: float, geography: dict) -> dict:
    """The stable, numeric heart of the offline payload for one case."""
    loc = resolve_location(lat=lat, lon=lon, allow_network=False,
                           geography=geography)
    cfg, r, lbl = build_label_parts(preset=preset, location=loc,
                                    allow_network=False)
    p = label_payload(cfg, r, lbl)
    m = lbl["metrics"]
    return {
        "dimensions": [
            {"key": d.get("key"),
             "score": _round(d.get("score")),
             "national_grade": d.get("national_grade")}
            for d in p["dimensions"]
        ],
        "composite_score": _round(p["composite_score"]),
        "composite_national_grade": p["composite_national_grade"],
        "n_scored": p["n_scored"],
        # The two headline axes. Pinned separately from the composite because that
        # is the whole point of splitting them: a change that moves the building
        # grade and the location grade in opposite directions can leave the
        # composite untouched, and would otherwise sail through this file.
        "construction_score": _round(p["construction_score"]),
        "construction_national_grade": p["construction_national_grade"],
        "construction_n_scored": p["construction_n_scored"],
        "location_score": _round(p["location_score"]),
        "location_national_grade": p["location_national_grade"],
        "location_n_scored": p["location_n_scored"],
        "location_raw_mean": _round(p["location_raw_mean"]),
        "resilience_site_score": _round(p["resilience_site_score"]),
        "resilience_building_score": _round(p["resilience_building_score"]),
        "cost": {k: _round(v) for k, v in (p.get("cost") or {}).items()},
        "total_loss": _round(p["total_loss"]),
        "fire_loss": _round(p["fire_loss"]),
        # The raw fiscal ratio and the two classification outputs, not just the rounded
        # score they feed. A classification bug that left the score inside its percentile
        # band would otherwise slip through unnoticed.
        "fiscal_ratio": _round(m.get("fiscal_ratio")),
        "assess_ratio_applied": _round(m.get("assess_ratio_applied")),
        "classification_multiplier_applied": _round(m.get("classification_multiplier_applied")),
    }


def _build_all() -> dict:
    return {name: _core(preset, lat, lon, geo)
            for name, preset, lat, lon, geo in CASES}


def test_label_payload_matches_golden():
    current = _build_all()

    if os.environ.get("UPDATE_GOLDEN"):
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n")
        print(f"  wrote golden snapshot: {GOLDEN}")
        return

    assert GOLDEN.exists(), (
        f"missing golden snapshot {GOLDEN} — generate it once with "
        "UPDATE_GOLDEN=1 python -m pytest tests/test_golden_label.py")
    expected = json.loads(GOLDEN.read_text())

    # Per-case diff so a failure names exactly what moved, not "big dict != dict".
    assert set(current) == set(expected), (
        f"case set changed: {sorted(set(current) ^ set(expected))}")
    for name in expected:
        assert current[name] == expected[name], (
            f"scoring drift in case {name!r} — if intentional, regenerate with "
            f"UPDATE_GOLDEN=1.\n  expected: {expected[name]}\n  actual:   {current[name]}")


def test_every_dimension_is_scored_in_every_case():
    """The snapshot cannot defend its own coverage.

    When the location dimensions were silently unscored, this file recorded
    ``"score": null`` for six of them and passed — and would have kept passing
    through any recalibration of Health, Air Quality, Noise, Climate, Solar or
    Water. Regenerating with UPDATE_GOLDEN would simply have re-recorded the nulls.

    So coverage is asserted separately from the values. If a change ever unscores a
    dimension in these fixtures, that fails here loudly instead of being absorbed
    into the snapshot as an expected null.
    """
    for name, core in _build_all().items():
        unscored = [d["key"] for d in core["dimensions"] if d["score"] is None]
        assert not unscored, f"{name}: unscored {unscored}"
        assert core["n_scored"] == len(core["dimensions"]), name


def test_the_two_locations_actually_score_differently():
    """The cross-county case has to earn its place. Offline without geography,
    Shelby and Los Angeles produced IDENTICAL location legs, so the second point
    pinned nothing that the first did not."""
    cur = _build_all()
    shelby = {d["key"]: d["score"] for d in cur["baseline_shelby"]["dimensions"]}
    la = {d["key"]: d["score"] for d in cur["baseline_la"]["dimensions"]}
    differing = {k for k in shelby if shelby[k] != la[k]}
    location_driven = {"health", "air_quality", "noise", "socioeconomic",
                       "walkability", "climate", "solar", "water", "infrastructure"}
    assert location_driven <= differing, sorted(location_driven - differing)


def _run_all():
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} tests passed.")


if __name__ == "__main__":
    _run_all()
