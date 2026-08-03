#!/usr/bin/env python3
"""Tests for the density-shape vs. spending-level normalization.

``enrich_row`` used to multiply the Halifax density shape straight into the
county's Census-of-Governments per-capita spending multiplier. That charges a
rural county twice for the same sparseness — the multiplier is already elevated
because its households are spread out — and produced figures like $9,137/yr to
serve one rural household, implying ~$178M/yr of local spending for a county of
47,694 people.

The correction expresses the shape relative to the density that county's own
spending was observed at. What these tests defend is the part that made an earlier
attempt unshippable: both densities must be **lot** densities, on the same axis,
so the ratio means something. Gross county density — households over every acre of
dry land — is dominated by how much forest a county contains and is not the same
quantity as a parcel's lot size.

Runs without network. Execute directly (python tests/test_density_normalizer.py)
or via pytest.
"""

from __future__ import annotations

import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parent.parent
for _p in (_ROOT, _ROOT / "src", _ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import pandas as pd                                                    # noqa: E402

from housing_label.enrich.infrastructure import (                       # noqa: E402
    density_normalizer, enrich_row, SHELBY_LOT_DU_ACRE,
    DENSITY_NORM_MIN, DENSITY_NORM_MAX)
from housing_label.data.county_lot_density import (                     # noqa: E402
    county_lot_density_for_county)

SHELBY, MONROE, MANHATTAN = "47157", "47123", "36061"


# ── The crosswalk ────────────────────────────────────────────────────────────
def test_shelby_matches_the_pilot_calibration_it_anchors():
    """The corroboration the whole approach rests on. enrich/infrastructure.py's
    Memphis notes independently put the city at "roughly 1.0-1.5 DU/acre at the
    city average"; this crosswalk, derived from Census urban/rural land and housing
    counts, lands at 1.41. Two separate derivations agreeing is what gross county
    density never had."""
    du = county_lot_density_for_county(SHELBY)["du_acre"]
    assert 1.0 <= du <= 1.5, du
    assert abs(du - SHELBY_LOT_DU_ACRE) < 1e-4


def test_densities_are_lot_densities_not_gross_land():
    """A rural county is sparse but not absurdly so once its forest is excluded.
    Gross density put Monroe at 0.048 DU/acre; over the land its houses actually
    occupy it is 0.08, and its urban core is 0.6 — the axis a parcel's lot size
    lives on."""
    r = county_lot_density_for_county(MONROE)
    assert 0.05 < r["du_acre"] < 0.2, r
    assert r["du_acre_urban"] > r["du_acre_rural"]
    # Manhattan is genuinely dense on this axis; a gross-land measure would agree
    # here and disagree wildly for a county with a big empty hinterland.
    assert county_lot_density_for_county(MANHATTAN)["du_acre"] > 20


def test_unknown_county_falls_back_to_the_national_row():
    for fips in (None, "99999", ""):
        r = county_lot_density_for_county(fips)
        assert r["resolved"] == "national"
        assert r["du_acre"] > 0


# ── The normalizer ───────────────────────────────────────────────────────────
def test_the_pilot_normalizes_to_exactly_one():
    """Shelby's multiplier is 1.0 by construction, so its density must divide out
    to 1.0 or the Memphis calibration this whole model rests on would shift."""
    assert abs(density_normalizer(SHELBY_LOT_DU_ACRE) - 1.0) < 1e-9
    assert abs(density_normalizer(
        county_lot_density_for_county(SHELBY)["du_acre"]) - 1.0) < 1e-6


def test_a_sparser_county_than_the_pilot_is_corrected_downward():
    """The whole point: a rural county's multiplier already carries its ruralness,
    so the shape must not charge for it again."""
    assert density_normalizer(county_lot_density_for_county(MONROE)["du_acre"]) < 1.0


def test_a_denser_county_is_corrected_upward():
    assert density_normalizer(county_lot_density_for_county(MANHATTAN)["du_acre"]) > 1.0


def test_unknown_density_is_a_no_op():
    """A missing crosswalk row must degrade to the OLD model, not a wrong one."""
    for bad in (None, 0, -1.0):
        assert density_normalizer(bad) == 1.0


def test_the_correction_is_bounded():
    """County lot density spans four orders of magnitude. Unclamped, one coarse
    county-level number would dominate every other term in the cost model."""
    assert density_normalizer(1e-6) == DENSITY_NORM_MIN
    assert density_normalizer(1e6) == DENSITY_NORM_MAX
    assert DENSITY_NORM_MIN < 1.0 < DENSITY_NORM_MAX


# ── End to end ───────────────────────────────────────────────────────────────
def _cost(county_du_acre):
    row = pd.Series({"CALC_ACRE": 10.0, "latitude": None, "longitude": None,
                     "RTOTAPR": 250_000.0})
    return enrich_row(row, assess_ratio=1.0, tax_rate=0.008, in_urban_area=False,
                      county_du_acre=county_du_acre)["est_annual_infra_cost"]


def test_a_rural_county_costs_less_to_serve_than_before_the_correction():
    rural = county_lot_density_for_county(MONROE)["du_acre"]
    assert _cost(rural) < _cost(None), "correction did not reach the cost components"


def test_omitting_the_density_reproduces_the_old_model_exactly():
    """The parameter is optional and its absence must be a true no-op, so a caller
    that never learned about it (the batch path, a library user) is unaffected."""
    baseline = _cost(None)
    # 0 and negative are unusable densities, not small ones — they must take the
    # same no-op path as None rather than being fed to the curve.
    for unusable in (0, 0.0, -1.0, -0.0001):
        assert _cost(unusable) == baseline, unusable
    row = pd.Series({"CALC_ACRE": 0.25, "latitude": None, "longitude": None,
                     "RTOTAPR": 250_000.0})
    a = enrich_row(row, assess_ratio=1.0, tax_rate=0.008, in_urban_area=True)
    b = enrich_row(row, assess_ratio=1.0, tax_rate=0.008, in_urban_area=True,
                   county_du_acre=None)
    assert a["est_annual_infra_cost"] == b["est_annual_infra_cost"]


# ── The reference distribution's utility mix ─────────────────────────────────
def test_every_archetype_declares_a_utility_mix():
    """Keyed by label so a new archetype fails loudly rather than silently
    defaulting to all-public — which is the bug this mix exists to fix."""
    from calibrate_infra_breakpoints import DENSITY_ARCHETYPES, UTILITY_MIX
    for label, *_ in DENSITY_ARCHETYPES:
        assert label in UTILITY_MIX, label
        assert abs(sum(s for _w, _s, s in UTILITY_MIX[label]) - 1.0) < 1e-9, label


def test_the_utility_mix_matches_the_national_shares():
    """The yardstick has to contain the connections the housing stock has. EPA puts
    private wells at 14.1% of housing units and septic at ~20% of households;
    Hernandez et al. (2023) put BOTH at 9.1%."""
    from calibrate_infra_breakpoints import DENSITY_ARCHETYPES, UTILITY_MIX
    well = septic = both = 0.0
    for label, _du, share, *_ in DENSITY_ARCHETYPES:
        for pub_water, pub_sewer, s in UTILITY_MIX[label]:
            w = share * s
            if not pub_water:
                well += w
            if not pub_sewer:
                septic += w
            if not pub_water and not pub_sewer:
                both += w
    assert abs(well - 0.141) < 0.01, f"well share {well:.3f}"
    assert abs(septic - 0.200) < 0.01, f"septic share {septic:.3f}"
    assert abs(both - 0.091) < 0.01, f"both share {both:.3f}"


def test_off_network_households_are_concentrated_where_they_actually_are():
    """A well/septic mix spread evenly would be worse than none — it would put
    private wells in high-rise apartments."""
    from calibrate_infra_breakpoints import DENSITY_ARCHETYPES, UTILITY_MIX

    def off_share(label):
        return sum(s for w, sw, s in UTILITY_MIX[label] if not (w and sw))

    by_density = sorted(DENSITY_ARCHETYPES, key=lambda a: a[1])
    sparsest, densest = by_density[0][0], by_density[-1][0]
    assert off_share(sparsest) > 0.8, sparsest
    assert off_share(densest) == 0.0, densest


if __name__ == "__main__":
    for _name, _fn in sorted(list(globals().items())):
        if _name.startswith("test_"):
            _fn()
            print(f"  ok  {_name}")
    print("density-normalizer tests passed")
