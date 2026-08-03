#!/usr/bin/env python3
"""Tests for the lot_context input and the rural reference-distribution roster.

Lot acreage alone can't say what kind of place a parcel is in — two acres is
exurban outside a city and a large in-town lot inside one, and the two are served
very differently. ``lot_context`` states it, overriding the Census urban-area test
on the geocoded point (a coarse call at a city's fringe).

Also pins the reference distribution's rural roster, since INFRA_XS is anchored to
it: adding or reweighting an archetype without re-running the calibrator would
leave the yardstick measuring a different population than the labels.

Runs without network (a pre-resolved Location is injected). Execute directly
(python tests/test_lot_context.py) or via pytest.
"""

from __future__ import annotations

import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parent.parent
for _p in (_ROOT, _ROOT / "src", _ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from housing_label.simulate.location import Location          # noqa: E402
from housing_label.simulate.house import (                     # noqa: E402
    build_label_parts, LOT_CONTEXTS)
from housing_label.simulate.dimensions import LOT_CONTEXT_URBAN  # noqa: E402


def _loc(in_urban_area):
    # A non-pilot county: Shelby returns None from infra_params_for_county (it keeps
    # the Memphis statutory defaults), which would never see in_urban_area at all.
    return Location(lat=35.53, lon=-84.42, state_fips="47", county_fips="47123",
                    county_name="Monroe", tract=None, place_label="Monroe",
                    in_urban_area=in_urban_area, climate_zone="4A",
                    egrid_subregion=None, egrid_factor=None, climate_projection=None,
                    wildfire=None, structure_type="single_family", num_units=1,
                    notes=None)


def _cost(in_urban_area, lot_context=None, lot_acres=2.0):
    _cfg, _r, lbl = build_label_parts(location=_loc(in_urban_area), allow_network=False,
                                      lot_acres=lot_acres, value=250_000,
                                      lot_context=lot_context)
    return lbl["metrics"]["est_annual_infra_cost"]


def test_vocabulary_and_mapping():
    assert LOT_CONTEXTS == ("rural", "suburban", "urban")
    assert set(LOT_CONTEXT_URBAN) == set(LOT_CONTEXTS)
    assert LOT_CONTEXT_URBAN["rural"] is False
    assert LOT_CONTEXT_URBAN["suburban"] is True and LOT_CONTEXT_URBAN["urban"] is True


def test_unset_keeps_the_detection():
    """The default must not assert anything — an unstated context leaves the Census
    urban-area result in charge, so nothing moves for a caller who never opens the
    panel."""
    assert _cost(True, None) == _cost(True, "urban")
    assert _cost(False, None) == _cost(False, "rural")


def test_stated_context_overrides_the_detection():
    """Stating the opposite of what was detected must actually change the cost, in
    both directions — otherwise the control is decorative."""
    assert _cost(True, "rural") == _cost(False, None)
    assert _cost(False, "urban") == _cost(True, None)
    assert _cost(True, "rural") != _cost(True, "urban")


def test_acreage_and_context_are_independent_inputs():
    """They answer different questions, so neither may swallow the other: acreage
    still moves cost at a fixed context, and context still moves cost at a fixed
    acreage."""
    assert _cost(False, "rural", lot_acres=10.0) > _cost(False, "rural", lot_acres=0.25)
    assert _cost(False, "urban", lot_acres=2.0) != _cost(False, "rural", lot_acres=2.0)


# ── Reference-distribution roster ─────────────────────────────────────────────
def test_archetype_shares_still_sum_to_one():
    from calibrate_infra_breakpoints import DENSITY_ARCHETYPES
    total = sum(a[2] for a in DENSITY_ARCHETYPES)
    assert abs(total - 1.0) < 1e-9, f"household shares sum to {total}"


def test_reference_distribution_contains_genuinely_rural_housing():
    """The sparsest archetype used to be a two-acre lot, so every large-lot home in
    the country was ranked against a population whose biggest lot was two acres.
    Census/CoreLogic put 4.6% of US housing on five acres or more."""
    from calibrate_infra_breakpoints import DENSITY_ARCHETYPES
    big = [a for a in DENSITY_ARCHETYPES if a[1] <= 0.2]      # <= 0.2 DU/acre = 5+ acres
    assert big, "no archetype at five acres or more"
    share = sum(a[2] for a in big)
    assert 0.03 <= share <= 0.06, f"5+ acre share is {share:.3f}, expected ~0.046"
    assert min(a[1] for a in DENSITY_ARCHETYPES) <= 0.05, "nothing reaching a 20-acre lot"


def test_rural_archetypes_are_all_single_family_and_non_urban():
    from calibrate_infra_breakpoints import DENSITY_ARCHETYPES
    for label, du_acre, _share, urban, units, _renter in DENSITY_ARCHETYPES:
        if du_acre <= 0.5:
            assert urban is False, f"{label} flagged urban"
            assert units == 1, f"{label} carries {units} units"


if __name__ == "__main__":
    for _name, _fn in sorted(list(globals().items())):
        if _name.startswith("test_"):
            _fn()
            print(f"  ok  {_name}")
    print("lot-context tests passed")
