#!/usr/bin/env python3
"""Tests for the household-weighted Solar Potential breakpoints.

``national_percentile.py`` says a score maps to a national percentile **"vs US
homes"**. Solar's breakpoints were the UNWEIGHTED distribution of ~3,200 county
yields, in which Loving County TX (64 people) counted as much as Los Angeles County
(10 million) — so the rank was really "vs US counties" wearing the other label.

These tests pin the weighted curve to the bundled data it was derived from, so the
constants in ``data/solar.py`` cannot drift away from the CSVs when either is
rebuilt, and pin the reconciliation that keeps a whole state from being dropped.

Runs without network. Execute directly (python tests/test_solar_percentiles.py) or
via pytest.
"""

from __future__ import annotations

import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parent.parent
for _p in (_ROOT, _ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from housing_label.data import solar as solar_data                       # noqa: E402
from scripts import calibrate_solar_percentiles as cal                   # noqa: E402


def _weights():
    y = cal.load_yields()
    w, _log = cal.household_weights(y, cal.load_housing_units())
    return y, w


# ── The curve matches the data it claims to come from ────────────────────────
def test_the_shipped_breakpoints_are_the_household_weighted_quantiles():
    """The drift guard. Recompute from the bundled CSVs and compare — so a rebuild
    of either table cannot leave data/solar.py quietly describing the old one."""
    y, w = _weights()
    pairs = sorted((v, w.get(k, 0.0)) for k, v in y.items())
    want = ([pairs[0][0]] + [cal.weighted_quantile(pairs, p) for p in cal.PERCENTILES]
            + [pairs[-1][0]])
    assert [round(v, 1) for v in solar_data._YIELD_XS] == [round(v, 1) for v in want]


def test_the_anchors_line_up_with_the_percentiles_they_claim():
    assert solar_data._YIELD_YS == [0.0] + [p * 100 for p in cal.PERCENTILES] + [100.0]
    assert len(solar_data._YIELD_XS) == len(solar_data._YIELD_YS)


def test_the_curve_is_monotonic():
    """A non-monotonic CDF would make a sunnier parcel score lower."""
    xs = solar_data._YIELD_XS
    assert all(a < b for a, b in zip(xs, xs[1:])), xs


# ── What the weighting actually changed ──────────────────────────────────────
def test_weighting_raised_the_upper_half_and_left_the_median_alone():
    """US households sit in sunnier places than US counties do, so it takes more
    yield to beat 75% of homes than 75% of counties. The median barely moves — this
    is a correction to the upper half, not a shift of the whole distribution."""
    y, _w = _weights()
    unw = sorted(y.values())

    def uq(p):
        return unw[min(len(unw) - 1, int(p * (len(unw) - 1)))]

    at = dict(zip(cal.PERCENTILES, solar_data._YIELD_XS[1:-1]))
    assert at[0.75] - uq(0.75) > 30, "p75 should rise materially"
    assert at[0.95] - uq(0.95) > 50, "p95 should rise materially"
    assert abs(at[0.50] - uq(0.50)) < 5, "the median should barely move"


def test_a_sunny_but_not_extreme_parcel_is_no_longer_over_credited():
    """The practical point: the old curve handed out ~7 points too many right where
    the A/B boundary is."""
    score = solar_data.reading_for_yield(1450.0, 1900.0, "point")["score"]
    assert 68.0 < score < 73.0, score           # was 77.0 on the unweighted curve


# ── The geography-vintage reconciliation ─────────────────────────────────────
def test_connecticut_is_not_silently_dropped():
    """solar_yield_county.csv uses 2023 planning regions (09110-09190);
    county_lot_density.csv uses 2020 legacy counties (09001-09015). Nothing joins,
    and dropping it would remove 1.5M households — 1.1% of the country, all in one
    narrow band of the yield axis, which would bias the lower-middle quantiles."""
    _y, w = _weights()
    ct = {k: v for k, v in w.items() if k.startswith("09")}
    assert len(ct) == 9, sorted(ct)
    assert sum(ct.values()) > 1_500_000, sum(ct.values())


def test_state_mass_is_conserved_where_the_vintages_disagree():
    """The redistribution moves mass WITHIN a state, it does not invent or lose
    any: Connecticut's nine planning regions must carry exactly the housing units
    its legacy counties held."""
    units = cal.load_housing_units()
    legacy = sum(v for k, v in units.items() if k.startswith("09"))
    _y, w = _weights()
    assert abs(sum(v for k, v in w.items() if k.startswith("09")) - legacy) < 1.0


def test_places_with_no_solar_score_are_excluded_rather_than_redistributed():
    """Far-north Alaska and the territories are outside PVGIS-NSRDB, so no home
    there is scored on this dimension and none belongs in the reference. Their mass
    must be dropped, NOT spread over the counties that do score."""
    y, w = _weights()
    units = cal.load_housing_units()
    # American Samoa / Guam / N. Mariana / USVI have housing units and no yield.
    for terr in ("60", "66", "69", "78"):
        assert any(k.startswith(terr) for k in units), terr
        assert not any(k.startswith(terr) for k in y), terr
        assert not any(k.startswith(terr) for k in w), terr


def test_every_scored_county_carries_a_weight():
    """A county in the yield table with no weight would silently count as zero
    households and vanish from the reference distribution."""
    y, w = _weights()
    assert set(y) == set(w)
    assert all(w[k] >= 0 for k in w)


def test_the_reference_covers_essentially_every_us_household():
    y, w = _weights()
    covered = sum(w[k] for k in y)
    assert covered > 140_000_000, f"{covered:,.0f}"


if __name__ == "__main__":
    for _name, _fn in sorted(list(globals().items())):
        if _name.startswith("test_"):
            _fn()
            print(f"  ok  {_name}")
    print("solar-percentile tests passed")
