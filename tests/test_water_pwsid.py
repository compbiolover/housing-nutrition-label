#!/usr/bin/env python3
"""Tests for per-system drinking-water scoring.

``data/water.py`` scores a county aggregate — the right answer only while you do
not know which system serves the address. Now that ``enrich/water_system.py``
resolves a parcel to a PWSID, ``data/water_system.py`` scores that system's own
SDWIS record instead, and the county becomes the fallback.

The behaviour worth pinning is the fallback boundary: a system EPA maps a service
area for but SDWIS has no active record of must NOT score as clean.

Runs without network (the parcel→PWSID lookup is injected). Execute directly
(python tests/test_water_pwsid.py) or via pytest.
"""

from __future__ import annotations

import csv
import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parent.parent
for _p in (_ROOT, _ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from housing_label.data.water_system import (                        # noqa: E402
    water_for_pwsid, _SCORE_BY_YEARS, _CSV, RECENT_YEARS)
from housing_label.simulate.location import Location                  # noqa: E402
from housing_label.simulate.house import build_label_parts            # noqa: E402


def _rows():
    with _CSV.open(newline="") as f:
        return list(csv.DictReader(f))


# ── The bundled table and its scoring ────────────────────────────────────────
def test_table_is_well_formed():
    rows = _rows()
    assert len(rows) > 40_000, f"only {len(rows)} systems — did the build truncate?"
    for r in rows[:2000]:
        assert r["pwsid"].strip(), "blank PWSID"
        assert 0 <= int(r["years_in_violation"]) <= RECENT_YEARS
        assert int(r["pop_served"]) >= 0


def test_score_falls_monotonically_with_violating_years():
    """More years out of compliance can never score better."""
    scores = [_SCORE_BY_YEARS[y] for y in range(RECENT_YEARS + 1)]
    assert scores == sorted(scores, reverse=True), scores
    assert scores[0] == 100.0 and scores[-1] == 0.0


def test_every_reachable_year_count_has_a_score():
    """A years value with no entry would raise at scoring time, on real data."""
    for y in range(RECENT_YEARS + 1):
        assert y in _SCORE_BY_YEARS


def test_a_clean_system_scores_100_and_a_violating_one_does_not():
    rows = _rows()
    clean = next(r for r in rows if int(r["years_in_violation"]) == 0)
    dirty = next(r for r in rows if int(r["years_in_violation"]) >= 2)
    assert water_for_pwsid(clean["pwsid"])["score"] == 100.0
    assert water_for_pwsid(dirty["pwsid"])["score"] < 100.0


def test_pwsid_lookup_is_case_insensitive_and_trims():
    row = _rows()[0]
    want = water_for_pwsid(row["pwsid"])
    assert water_for_pwsid(f"  {row['pwsid'].lower()}  ") == want


def test_an_unknown_system_returns_none_not_a_default():
    """None is the honest answer, and it is what routes the caller to the county
    fallback. A default score here would silently rate an unknown system."""
    assert water_for_pwsid("ZZ9999999") is None
    assert water_for_pwsid(None) is None
    assert water_for_pwsid("") is None


# ── End to end ───────────────────────────────────────────────────────────────
def _loc(water_system, county_fips="47157"):
    return Location(lat=35.13, lon=-89.99, state_fips="47", county_fips=county_fips,
                    county_name="Shelby", tract=None, place_label="Shelby",
                    in_urban_area=True, climate_zone="4A", egrid_subregion=None,
                    egrid_factor=None, climate_projection=None, wildfire=None,
                    structure_type="single_family", num_units=1,
                    water_system=water_system, notes=None)


def _served(pwsid, name="TEST WATER"):
    return {"status": "served", "pwsid": pwsid, "name": name,
            "population_served": 1000, "provenance": "State Agency", "source": "EPA"}


def _label(water_system):
    _cfg, _r, lbl = build_label_parts(location=_loc(water_system), allow_network=False,
                                      value=250_000)
    return lbl


def _water(lbl):
    return next(d["score"] for d in lbl["dimensions"] if d["key"] == "water")


def test_a_resolved_system_is_scored_instead_of_the_county():
    rows = _rows()
    dirty = next(r for r in rows if int(r["years_in_violation"]) >= 3)
    lbl = _label(_served(dirty["pwsid"]))
    assert _water(lbl) == water_for_pwsid(dirty["pwsid"])["score"]
    m = lbl["metrics"]
    assert m["water_pwsid"] == dirty["pwsid"].upper()
    assert m["water_years_in_violation"] == int(dirty["years_in_violation"])
    # The county basis is not also reported — one score, one stated basis.
    assert "water_pct_hb_violation" not in m


def test_an_unmapped_system_falls_back_to_the_county():
    """EPA maps a service area, SDWIS has no active record (a merger, a data lag).
    The county aggregate stands in — scoring the unknown system as clean would be a
    guess dressed as a fact — and the note says which of the two this is."""
    lbl = _label(_served("ZZ9999999"))
    assert _water(lbl) is not None
    assert "water_pct_hb_violation" in lbl["metrics"]
    note = lbl["location_notes"]["water"].lower()
    assert "no active record" in note and "county aggregate" in note


def test_the_note_states_the_system_and_its_record():
    rows = _rows()
    clean = next(r for r in rows if int(r["years_in_violation"]) == 0)
    note = _label(_served(clean["pwsid"], "CLEANSVILLE WATER"))["location_notes"]["water"]
    assert "CLEANSVILLE WATER" in note
    assert clean["pwsid"].upper() in note
    assert "no health-based violation" in note.lower()

    dirty = next(r for r in rows if int(r["years_in_violation"]) == 2)
    dnote = _label(_served(dirty["pwsid"]))["location_notes"]["water"].lower()
    assert "2 of the last 5 years" in dnote


def test_a_private_well_still_wins_over_a_resolved_system():
    """Ordering guard: an owner who says "well" is not overridden by a service area
    that happens to cover their point."""
    rows = _rows()
    clean = next(r for r in rows if int(r["years_in_violation"]) == 0)
    _cfg, _r, lbl = build_label_parts(location=_loc(_served(clean["pwsid"])),
                                      allow_network=False, value=250_000,
                                      water_source="well")
    assert _water(lbl) is None


if __name__ == "__main__":
    for _name, _fn in sorted(list(globals().items())):
        if _name.startswith("test_"):
            _fn()
            print(f"  ok  {_name}")
    print("per-system water tests passed")
