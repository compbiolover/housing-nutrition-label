#!/usr/bin/env python3
"""Tests for the radon leg's building adjustment.

The EPA radon zone is a map of the GEOLOGY. What a household breathes also depends
on the building, because radon enters through the foundation — and the foundation
was the one thing about the house this dimension ignored while scoring a
lung-cancer risk factor. A full basement and a vented crawlspace over the same
Zone 1 rock are not the same exposure.

Deliberately NOT extended to PM2.5 and ozone: those are outdoor pollutants whose
source model runs at ~12 km, and the building does not move them. That asymmetry
is the point, so it is pinned here.

Runs without network. Execute directly (python tests/test_radon_foundation.py) or
via pytest.
"""

from __future__ import annotations

import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parent.parent
for _p in (_ROOT, _ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from housing_label.data.air_quality import (                            # noqa: E402
    radon_adjusted_reading, _RADON_FOUNDATION_FACTOR, _RADON_SCORE, _reading)
from housing_label.simulate.location import Location                     # noqa: E402
from housing_label.simulate.house import build_label_parts, BONUS_FLAGS  # noqa: E402

# A Zone 1 reading (worst geology), mid-range pollutants.
_Z1 = _reading(8.0, 38.0, 1, "tract")
_Z3 = _reading(8.0, 38.0, 3, "tract")
_NO_ZONE = _reading(8.0, 38.0, None, "tract")


def _radon(reading):
    return reading["radon_score"]


# ── The adjustment itself ────────────────────────────────────────────────────
def test_foundations_order_by_how_much_soil_gas_gets_in():
    """Below-grade rooms draw more soil gas (more contact area, stronger stack
    effect); a vented crawl dilutes it. Slab is the baseline."""
    scores = {f: _radon(radon_adjusted_reading(_Z1, f))
              for f in ("crawl", "slab", "partial-basement", "full-basement")}
    assert scores["crawl"] > scores["slab"] > scores["partial-basement"] > scores["full-basement"]
    assert scores["slab"] == _radon(_Z1), "slab is the unmodified baseline"


def test_the_factor_table_is_anchored_on_slab():
    assert _RADON_FOUNDATION_FACTOR["slab"] == 1.00
    assert _RADON_FOUNDATION_FACTOR["crawl"] < 1.0
    assert _RADON_FOUNDATION_FACTOR["full-basement"] > 1.0


def test_geology_still_dominates_the_building():
    """The modifier must refine the zone, not overrule it: the best foundation on
    the worst rock must still score below the worst foundation on the best rock."""
    best_on_worst = _radon(radon_adjusted_reading(_Z1, "crawl"))
    worst_on_best = _radon(radon_adjusted_reading(_Z3, "full-basement"))
    assert best_on_worst < worst_on_best


def test_mitigation_decouples_the_house_from_its_zone():
    """EPA: sub-slab depressurization cuts indoor radon by up to 99%, and
    mitigation is judged successful below 2 pCi/L — Zone 3 territory by
    definition. So a mitigated home floors at the Zone 3 score whatever its rock."""
    for foundation in ("full-basement", "crawl", "slab", None):
        r = radon_adjusted_reading(_Z1, foundation, mitigated=True)
        assert _radon(r) >= _RADON_SCORE[3], foundation


def test_mitigation_never_lowers_a_score():
    """A floor, not a replacement — a mitigated Zone 3 crawlspace must not be
    dragged DOWN to the Zone 3 value it already beats."""
    unmitigated = _radon(radon_adjusted_reading(_Z3, "crawl"))
    mitigated = _radon(radon_adjusted_reading(_Z3, "crawl", mitigated=True))
    assert mitigated >= unmitigated


def test_outdoor_pollutants_are_untouched():
    """The asymmetry is deliberate: the building moves radon, not PM2.5 or ozone."""
    adj = radon_adjusted_reading(_Z1, "full-basement", mitigated=True)
    assert adj["pm25_score"] == _Z1["pm25_score"]
    assert adj["ozone_score"] == _Z1["ozone_score"]
    assert adj["pm25"] == _Z1["pm25"] and adj["ozone"] == _Z1["ozone"]


def test_the_input_reading_is_not_mutated():
    """The county/tract reading is lru_cached upstream — mutating it would poison
    every later lookup of that tract with one house's foundation."""
    before = dict(_Z1)
    radon_adjusted_reading(_Z1, "full-basement", mitigated=True)
    assert _Z1 == before


def test_a_reading_with_no_radon_zone_passes_through():
    """~0.2% of counties have no EPA zone; there is no risk figure to modify and
    the weights already redistribute without it."""
    assert radon_adjusted_reading(_NO_ZONE, "full-basement") is _NO_ZONE
    assert radon_adjusted_reading(None, "slab") is None


def test_an_unknown_foundation_is_a_no_op():
    assert radon_adjusted_reading(_Z1, None) is _Z1
    assert radon_adjusted_reading(_Z1, "houseboat") is _Z1


# ── End to end ───────────────────────────────────────────────────────────────
def _loc():
    return Location(lat=35.53, lon=-84.42, state_fips="47", county_fips="47123",
                    county_name="Monroe", tract="47123925302", place_label="Monroe",
                    in_urban_area=False, climate_zone="4A", egrid_subregion=None,
                    egrid_factor=None, climate_projection=None, wildfire=None,
                    structure_type="single_family", num_units=1, notes=None)


def _aq(foundation, upgrades=None):
    _cfg, _r, lbl = build_label_parts(location=_loc(), allow_network=False,
                                      foundation=foundation, value=250_000,
                                      upgrades=upgrades)
    return next(d["score"] for d in lbl["dimensions"] if d["key"] == "air_quality")


def test_the_foundation_reaches_the_dimension_score():
    assert _aq("crawl") > _aq("slab") > _aq("full-basement")


def test_the_mitigation_upgrade_is_wired_and_helps():
    assert "radon_mitigation" in BONUS_FLAGS
    assert _aq("full-basement", ["radon_mitigation"]) > _aq("full-basement")


def test_mitigation_does_not_touch_resilience():
    """It is in the shared upgrades vocabulary but is not a resilience measure, so
    it must carry no EAL credit — crediting it would be a category error."""
    from housing_label.simulate.house import BONUS_RADON_MITIGATION
    assert BONUS_RADON_MITIGATION == 1.00

    def resilience(upgrades):
        _cfg, _r, lbl = build_label_parts(location=_loc(), allow_network=False,
                                          foundation="slab", value=250_000,
                                          upgrades=upgrades)
        return next(d["score"] for d in lbl["dimensions"] if d["key"] == "resilience")

    assert resilience(["radon_mitigation"]) == resilience(None)


if __name__ == "__main__":
    for _name, _fn in sorted(list(globals().items())):
        if _name.startswith("test_"):
            _fn()
            print(f"  ok  {_name}")
    print("radon-foundation tests passed")
