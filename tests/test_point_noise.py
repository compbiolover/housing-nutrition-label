#!/usr/bin/env python3
"""Tests for the point-level noise refinement.

The Noise dimension scores the share of a CENSUS TRACT's residents exposed to
>=60 dB transportation noise — a population statistic. In a rural tract containing
one highway corridor, that exposure belongs to the homes beside the corridor and
every other parcel inherits it.

TIGERweb supplies the missing parcel-level fact: distance to the nearest primary
road, secondary road or railroad. What these tests defend is the discipline around
using it — the refinement may only ever IMPROVE a score, only on positive
evidence, and never on the strength of an outage.

Runs without network (the road lookup is stubbed). Execute directly
(python tests/test_point_noise.py) or via pytest.
"""

from __future__ import annotations

import pathlib
import sys
from unittest import mock

_ROOT = pathlib.Path(__file__).resolve().parent.parent
for _p in (_ROOT, _ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from housing_label.enrich import road_noise as rn                     # noqa: E402
from housing_label.data import noise as noise_data                     # noqa: E402
from housing_label.simulate.location import Location                   # noqa: E402
from housing_label.simulate.house import build_label_parts             # noqa: E402

# A quiet rural tract (below the national median) and a noisy one (above it).
QUIET_TRACT = "47123925302"      # 0.87% exposed -> scores 68.1 unrefined


def _sources(primary=None, secondary=None, rail=None):
    """A stubbed lookup result with the given distances in metres."""
    dist = {"primary": primary, "secondary": secondary, "rail": rail}
    within = [k for k, (_l, t) in rn._SOURCES.items()
              if dist[k] is not None and dist[k] <= t]
    return {"distances_m": dist,
            "thresholds_m": {k: t for k, (_l, t) in rn._SOURCES.items()},
            "within_threshold": within, "any_within_threshold": bool(within),
            "source": "test"}


# ── The lookup ───────────────────────────────────────────────────────────────
def test_local_roads_are_not_a_noise_source():
    """Every house in the country is on a local road, so including them would flag
    every parcel and the refinement would never fire. A local street also rarely
    clears 60 dB L_eq beyond its own right-of-way."""
    assert "local" not in rn._SOURCES
    assert set(rn._SOURCES) == {"primary", "secondary", "rail"}


def test_thresholds_are_attenuation_distances_not_hud_screening():
    """HUD's 1,000 ft / 3,000 ft screening distances decide when an assessment is
    required, not where noise is. At those distances almost every rural parcel sits
    near some state highway and nothing would ever resolve."""
    assert rn._SOURCES["primary"][1] == 300.0        # freeway, ~75-80 dBA at 15 m
    assert rn._SOURCES["secondary"][1] == 100.0      # arterial, ~65-70 dBA at 15 m
    assert rn._SOURCES["primary"][1] < 305.0         # below HUD's 1,000 ft
    assert rn._SOURCES["rail"][1] < 914.0            # below HUD's 3,000 ft


def test_search_box_is_wider_than_every_threshold():
    """So "nothing within the threshold" is a measured absence rather than an
    artifact of how far we looked."""
    assert rn._SEARCH_M > max(t for _l, t in rn._SOURCES.values())


def test_off_network_returns_none():
    rn._sources_at.cache_clear()
    assert rn.noise_sources_near(35.5, -84.4, allow_network=False) is None


def test_an_outage_raises_rather_than_reporting_nothing_nearby():
    """"Nothing nearby" is the condition that grants the credit, so an outage that
    produced it would quietly upgrade every address in the country at once."""
    with mock.patch.object(rn, "_query", side_effect=rn.RoadDataUnavailable("boom")):
        rn._sources_at.cache_clear()
        try:
            rn.noise_sources_near(35.5, -84.4)
        except rn.RoadDataUnavailable:
            return
    raise AssertionError("expected RoadDataUnavailable")


def test_distance_is_taken_from_the_nearest_vertex():
    feats = [{"geometry": {"paths": [[[-84.4230, 35.5300], [-84.4230, 35.5400]]]}}]
    d = rn._nearest_m(35.5282, -84.4230, feats)
    assert 190 < d < 210, d              # ~0.0018 deg of latitude
    assert rn._nearest_m(35.5282, -84.4230, []) is None


# ── The refinement ───────────────────────────────────────────────────────────
def _loc(tract=QUIET_TRACT):
    return Location(lat=35.5282, lon=-84.4230, state_fips="47", county_fips="47123",
                    county_name="Monroe", tract=tract, place_label="Monroe",
                    in_urban_area=False, climate_zone="4A", egrid_subregion=None,
                    egrid_factor=None, climate_projection=None, wildfire=None,
                    structure_type="single_family", num_units=1, notes=None)


def _noise(sources_result, tract=QUIET_TRACT):
    """Score with the road lookup stubbed to a given result (or exception)."""
    target = "housing_label.enrich.road_noise.noise_sources_near"
    kw = ({"side_effect": sources_result}
          if isinstance(sources_result, Exception) else {"return_value": sources_result})
    with mock.patch(target, **kw):
        _cfg, _r, lbl = build_label_parts(location=_loc(tract), allow_network=False,
                                          value=250_000)
    dim = next(d for d in lbl["dimensions"] if d["key"] == "noise")
    return dim["score"], lbl["location_notes"].get("noise", "")


def test_a_parcel_clear_of_every_source_is_refined_upward():
    unrefined, _ = _noise(None)
    refined, note = _noise(_sources(secondary=240.0))
    assert refined > unrefined
    assert refined == noise_data.QUIET_FLOOR_SCORE
    assert "refined to this parcel" in note


def test_a_source_within_its_threshold_blocks_the_refinement():
    unrefined, _ = _noise(None)
    for close in (_sources(primary=250.0), _sources(secondary=80.0),
                  _sources(rail=200.0)):
        score, note = _noise(close)
        assert score == unrefined, close["within_threshold"]
        assert "refined" not in note


def test_an_outage_refines_nothing():
    unrefined, _ = _noise(None)
    score, _note = _noise(rn.RoadDataUnavailable("down"))
    assert score == unrefined


def test_the_refinement_only_ever_improves():
    """It is a floor, not a replacement. A tract already quieter than the floor
    must not be dragged down to it."""
    quiet_floor = noise_data.QUIET_FLOOR_SCORE
    with mock.patch("housing_label.data.noise.noise_for_tract",
                    return_value={"score": 97.0, "pct_ge60db": 0.01,
                                  "geo_level": "tract", "label": "test"}):
        score, _ = _noise(_sources(secondary=900.0))
    assert score == 97.0 > quiet_floor


def test_a_noisy_tract_is_not_refined_even_when_no_road_is_near():
    """Above the national median the driver may be aviation, which is in the BTS
    map and invisible to TIGERweb. Declining is the fail-safe direction."""
    noisy = {"score": 30.0, "pct_ge60db": noise_data.MEDIAN_TRACT_PCT + 1.0,
             "geo_level": "tract", "label": "test"}
    with mock.patch("housing_label.data.noise.noise_for_tract", return_value=noisy):
        score, note = _noise(_sources(secondary=900.0))
    assert score == 30.0
    assert "refined" not in note


def test_the_floor_and_gate_track_the_score_curve():
    """Both are read off the curve's own anchors, so they cannot drift from the
    distribution they describe when the noise data is rebuilt."""
    assert noise_data.MEDIAN_TRACT_PCT == noise_data._PCT_XS[3]
    assert noise_data.QUIET_FLOOR_SCORE == noise_data._PCT_YS[1]
    assert noise_data.QUIET_FLOOR_SCORE < 100.0, "must not claim zero exposure"


def test_the_note_admits_what_the_check_cannot_see():
    _score, note = _noise(_sources(secondary=240.0))
    assert "aviation" in note.lower()


if __name__ == "__main__":
    for _name, _fn in sorted(list(globals().items())):
        if _name.startswith("test_"):
            _fn()
            print(f"  ok  {_name}")
    print("point-noise tests passed")
