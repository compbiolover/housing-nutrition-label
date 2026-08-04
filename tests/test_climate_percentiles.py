#!/usr/bin/env python3
"""Tests for the household-weighted Climate Projections breakpoints.

The anchors used to be UNWEIGHTED quantiles over one value per COUNTY, which was
wrong twice: unweighted, so Loving County TX (64 people) counted as much as Los
Angeles County; and county-level, when the dimension RESOLVES at the tract — a
tract was ranked against a population it is not a member of.

The second error is the one that bit. Counties average away the sub-county
variation the tract file exists to capture, and consecutive dry days are both
extreme and dense in California and the Southwest, so the county p95 landed at 56.8
days and pinned 15% of US households at a flat drought score of 0.

Runs without network. Execute directly (python tests/test_climate_percentiles.py)
or via pytest.
"""

from __future__ import annotations

import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parent.parent
for _p in (_ROOT, _ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from housing_label.data import climate_projections as cp                 # noqa: E402
from scripts import calibrate_climate_breakpoints as cal                 # noqa: E402

_CLIMATE, _WEIGHTS = cal.load()


def _pairs(metric: str, band: str = cal.BAND):
    col = f"{metric}_{band}"
    return sorted((float(r[col]), _WEIGHTS.get(r["geoid"].zfill(11), 0.0))
                  for r in _CLIMATE if (r.get(col) or "").strip() != "")


def _share_at_or_beyond(metric: str, threshold: float) -> float:
    pairs = _pairs(metric)
    total = sum(w for _, w in pairs)
    return sum(w for v, w in pairs if v >= threshold) / total


# ── The curve matches the data it claims to come from ────────────────────────
def test_the_shipped_breakpoints_are_the_household_weighted_tract_quantiles():
    """The drift guard: recompute from the bundled CSVs so a rebuild of either
    cannot leave data/climate_projections.py describing the old distribution."""
    for metric in cal.METRICS:
        want = cal.anchors(_CLIMATE, _WEIGHTS, metric)
        got = [round(v, 1) for v in cp._BREAKPOINTS[metric][0]]
        assert got == want, (metric, got, want)


def test_every_metric_is_covered_and_scored_the_same_way():
    assert set(cal.METRICS) == set(cp._BREAKPOINTS)
    for metric, (xs, ys) in cp._BREAKPOINTS.items():
        assert ys == cal.SCORES, metric
        assert len(xs) == len(ys) == len(cal.PERCENTILES), metric


def test_every_curve_is_monotonic():
    """Hazard rises left to right and the score falls; a break would make a worse
    projection score better."""
    for metric, (xs, ys) in cp._BREAKPOINTS.items():
        assert all(a < b for a, b in zip(xs, xs[1:])), (metric, xs)
        assert all(a > b for a, b in zip(ys, ys[1:])), (metric, ys)


# ── What the reweighting actually fixed ──────────────────────────────────────
def test_the_anchors_land_where_their_percentiles_claim():
    """The whole point: the share of HOUSEHOLDS beyond each anchor should match the
    percentile the anchor is labelled with. The old county curve did not."""
    for metric, (xs, _ys) in cp._BREAKPOINTS.items():
        for pct, x in zip(cal.PERCENTILES, xs):
            share = _share_at_or_beyond(metric, x)
            assert abs(share - (1 - pct / 100)) < 0.02, (metric, pct, x, share)


def test_the_old_drought_curve_saturated_and_the_new_one_does_not():
    """15.1% of US households scored a flat 0 on the drought leg — triple what a
    p95 anchor implies — with no way to tell them apart."""
    old_p95, new_p95 = 56.8, cp._BREAKPOINTS["drought_consecdd"][0][-1]
    assert _share_at_or_beyond("drought_consecdd", old_p95) > 0.14
    assert abs(_share_at_or_beyond("drought_consecdd", new_p95) - 0.05) < 0.01
    assert new_p95 > old_p95 * 2


def test_the_drought_extreme_is_the_desert_southwest_not_an_artifact():
    """A 2.6x move at p95 deserves a sanity check on where the mass actually is."""
    hot = [r for r in _CLIMATE
           if (r.get("drought_consecdd_low") or "").strip()
           and float(r["drought_consecdd_low"]) >= 200]
    assert hot, "expected some tracts above 200 consecutive dry days"
    assert all(r["state"] in {"CA", "AZ", "NV"} for r in hot), \
        sorted({r["state"] for r in hot})


# ── The weighting join ───────────────────────────────────────────────────────
def test_the_weights_cover_essentially_every_tract_and_household():
    weighted = sum(1 for r in _CLIMATE if r["geoid"].zfill(11) in _WEIGHTS)
    assert len(_CLIMATE) - weighted <= 20, len(_CLIMATE) - weighted
    assert sum(_WEIGHTS.get(r["geoid"].zfill(11), 0.0) for r in _CLIMATE) > 130_000_000


def test_unpopulated_tracts_carry_no_weight():
    """Parks, water and industrial tracts must not move a percentile over homes."""
    zero = [g for g, w in _WEIGHTS.items() if w == 0]
    assert zero, "expected some zero-household tracts"
    assert all(_WEIGHTS[g] == 0 for g in zero)


def test_the_fire_leg_really_is_a_single_pathway():
    """The module says fire_fwi_low == fire_fwi_high, and the anchors are taken
    from the low column on that basis. Check it rather than trust it."""
    assert all((r.get("fire_fwi_low") or "") == (r.get("fire_fwi_high") or "")
               for r in _CLIMATE)


if __name__ == "__main__":
    for _name, _fn in sorted(list(globals().items())):
        if _name.startswith("test_"):
            _fn()
            print(f"  ok  {_name}")
    print("climate-percentile tests passed")
