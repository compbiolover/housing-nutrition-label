#!/usr/bin/env python3
"""Year-built distribution (ACS B25034/B25035) — loader contract + the interpolation rule.

Two things are under test and they fail differently.

The **loader** is ordinary plumbing: tract → county → national, the shared
``resolved``/``geo_level`` vocabulary, and a refusal to invent a US typical for a
caller who supplied no geography at all.

The **interpolation** is the part that could be silently, catastrophically wrong. It
turns ten decade buckets into p25/median/p75, and its one load-bearing property is
direction: ``BUCKETS`` runs oldest → newest, and reversing it would still produce
plausible-looking years while inverting every answer in the file. So the quantile
function is tested against hand-computed cases where a sign error is not survivable —
a distribution entirely inside one bucket, one split across two, and an asymmetric one
whose quartiles sit on opposite sides of its median.

Run standalone: ``python tests/test_year_built.py``
"""

from __future__ import annotations

import sys

import scripts.build_year_built as yb_build
from housing_label.data import year_built as yb

# A tract and county that must exist in any real build of the crosswalk: Shelby
# County, TN (the pilot county) and one of its tracts.
SHELBY_TRACT = "47157000100"
SHELBY_COUNTY = "47157"


# ── the interpolation rule ──────────────────────────────────────────────────────
def _counts(by_decade: dict[int, float]) -> list[float]:
    """Build a BUCKETS-parallel count vector from ``{bucket start year: count}``."""
    return [float(by_decade.get(lo, 0)) for _, lo, _hi in yb_build.BUCKETS]


def test_bucket_order_is_oldest_first():
    """The single assumption the whole file rests on."""
    los = [lo for _, lo, _ in yb_build.BUCKETS]
    assert los == sorted(los), f"BUCKETS must run oldest→newest, got {los}"
    for _, lo, hi in yb_build.BUCKETS:
        assert lo < hi, f"bucket [{lo},{hi}) is not a forward interval"


def test_quantile_all_in_one_bucket():
    """Every home built in the 1990s: all quantiles land inside [1990, 2000)."""
    c = _counts({1990: 100})
    for q in (0.25, 0.5, 0.75):
        got = yb_build.quantile_year(c, q)
        assert 1990 <= got < 2000, f"q={q} gave {got}"
    # Position within the bucket is linear in q.
    assert yb_build.quantile_year(c, 0.25) == 1992.5
    assert yb_build.quantile_year(c, 0.50) == 1995.0
    assert yb_build.quantile_year(c, 0.75) == 1997.5


def test_quantile_split_across_two_buckets():
    """Half in the 1950s, half in the 2000s — the median sits at the seam.

    Walking oldest→newest, the 50% target is reached exactly at the end of the
    1950s bucket, i.e. 1960. A reversed walk would answer 2010 here, so this case
    catches a direction error outright.
    """
    c = _counts({1950: 50, 2000: 50})
    assert yb_build.quantile_year(c, 0.50) == 1960.0
    assert yb_build.quantile_year(c, 0.25) == 1955.0    # midpoint of the 1950s
    assert yb_build.quantile_year(c, 0.75) == 2005.0    # midpoint of the 2000s


def test_quantile_asymmetric_distribution():
    """A mostly-new tract with an old tail: quartiles straddle the median unevenly."""
    c = _counts({1900: 10, 1960: 10, 2000: 80})
    p25, p50, p75 = (yb_build.quantile_year(c, q) for q in (0.25, 0.5, 0.75))
    assert p25 < p50 < p75
    # 20 of 100 homes predate 2000, so every quartile lands inside [2000, 2010) —
    # at 5/80, 30/80 and 55/80 of the way through it. The old tail moves the
    # quartiles without dragging any of them out of the dominant decade, which is
    # exactly the shape that makes a bare median misleading.
    assert p25 == 2000 + 5 / 80 * 10
    assert p50 == 2000 + 30 / 80 * 10
    assert p75 == 2000 + 55 / 80 * 10


def test_quantile_empty_distribution_is_none():
    assert yb_build.quantile_year(_counts({}), 0.5) is None
    assert yb_build.quantile_year([0.0] * len(yb_build.BUCKETS), 0.5) is None


def test_quantile_skips_empty_buckets():
    """A zero-count bucket must not absorb a quantile that lands on its boundary."""
    c = _counts({1950: 50, 1960: 0, 1970: 50})
    assert yb_build.quantile_year(c, 0.50) == 1960.0   # end of the 50s, not inside the 60s
    assert yb_build.quantile_year(c, 0.51) > 1970.0    # jumps the empty decade


def test_a_suppressed_bucket_refuses_the_row_rather_than_reading_as_zero():
    """A missing decade must not be coerced to "nobody built then".

    Never fires on the 2024 vintage — all 88,605 geographies carry all ten buckets —
    so this pins the guard itself. Zeroing a suppressed cell would move every
    quantile, and the B25035 cross-check could not catch it, because the Census's
    own median is computed from cells we never saw.
    """
    counts = _counts({1950: 50, 2000: 50})
    complete = {c: v for (c, _, _), v in zip(yb_build.BUCKETS, counts)}
    complete[yb_build.TOTAL_COL] = 100.0
    complete[yb_build.TOTAL_MOE_COL] = 10.0

    ok = yb_build.derive({"1400000US99999999999": complete}, {})
    assert len(ok) == 1, "a complete distribution must be kept"

    suppressed = dict(complete)
    suppressed["B25034_E009"] = None            # the 1950s bucket goes missing
    got = yb_build.derive({"1400000US99999999999": suppressed}, {})
    assert len(got) == 0, "a suppressed bucket must refuse the row, not read as zero"


# ── the loader contract ─────────────────────────────────────────────────────────
def test_tract_resolves_with_ordered_quartiles():
    got = yb.year_built_distribution_for(SHELBY_TRACT)
    assert got is not None, "the pilot tract must be in the bundled crosswalk"
    assert got["geo_level"] == "tract"
    assert got["resolved"] is True
    assert got["p25"] <= got["year_built"] <= got["p75"]
    assert got["spread"] == got["p75"] - got["p25"]
    assert 1800 <= got["p25"] and got["p75"] <= 2100


def test_county_fallback_for_unknown_tract():
    """An 11-digit geoid that isn't in the table falls back to its parent county."""
    unknown_in_shelby = SHELBY_COUNTY + "999999"
    got = yb.year_built_distribution_for(unknown_in_shelby)
    assert got is not None
    assert got["geo_level"] == "county"
    assert got["resolved"] is True


def test_national_fallback_is_unresolved():
    """Nothing matches, but a geography WAS asked for — US typical, flagged."""
    got = yb.year_built_distribution_for("99999999999")
    assert got is not None
    assert got["geo_level"] == "us"
    assert got["resolved"] is False, "the national row must never read as resolved"


def test_no_geography_returns_none():
    """No location at all must not be handed the US typical.

    Mirrors data/home_value.median_home_value_for: an offline or un-geocoded caller
    keeps its own default rather than silently inheriting a national number.
    """
    assert yb.year_built_distribution_for() is None
    assert yb.year_built_distribution_for(None, None) is None
    assert yb.year_built_distribution_for("", "") is None


def test_county_lookup_by_fips():
    got = yb.year_built_distribution_for(None, SHELBY_COUNTY)
    assert got is not None
    assert got["geo_level"] == "county"


def test_geoid_is_zero_padded():
    """A caller passing an int-ish geoid that lost its leading zero still resolves."""
    padded = yb.year_built_distribution_for(None, "01001")
    unpadded = yb.year_built_distribution_for(None, "1001")
    assert padded is not None
    assert unpadded == padded


def test_reading_carries_the_sample_size():
    """How many homes the typical was drawn from — context the median alone lacks."""
    got = yb.year_built_distribution_for(SHELBY_TRACT)
    assert got["units"] is not None and got["units"] > 0


def test_the_reliability_gate_is_spent_at_build_time():
    """The ACS margin does not ride along to the runtime.

    It is read by scripts/build_year_built.py and used there to drop geographies
    whose unit count is too uncertain to quantile (CV > MAX_CV). A request handed the
    margin could not do anything the filter has not already done, so its absence from
    the contract is the design, not an oversight.
    """
    assert "units_moe" not in yb.year_built_distribution_for(SHELBY_TRACT)
    assert 0 < yb_build.MAX_CV < 1


def test_source_string_denies_it_is_this_building():
    """The label must never read as a measurement of the addressed structure."""
    got = yb.year_built_distribution_for(SHELBY_TRACT)
    assert "not this building" in got["source"]
    assert yb.DATA_VINTAGE in got["label"]


def test_national_spread_is_wide_enough_to_matter():
    """The premise of the whole feature, asserted rather than assumed.

    If the US typical range ever collapses to a handful of years, the interval is no
    longer worth rendering and the honest move would be to drop it — so a rebuild
    that produces a narrow national spread should fail here and be looked at.
    """
    got = yb.year_built_distribution_for("99999999999")
    assert got["spread"] >= 20, f"national interquartile spread is only {got['spread']} yr"


def _run_all() -> int:
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"  ok    {fn.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL  {fn.__name__}: {exc}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_run_all())
