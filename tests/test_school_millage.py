#!/usr/bin/env python3
"""Tests for the measured school-netting path.

The Infrastructure Burden revenue side nets school taxes off an ACS effective rate so it is
like-for-like with the non-school cost model. That netting used to be a single
multiplicative estimate — an owner-occupied-derived rate times an all-property school share
— which over-nets in states giving owners school-specific relief.

``data/school_millage.py`` supplies the alternative for counties where school rates are
bundled: compute what the owner actually pays in school tax and subtract it. These tests
pin three things a future reader could easily break —

  1. the measured path fires ONLY where millage exists, and is byte-identical to the old
     behaviour everywhere else (the guarantee that makes shipping one state safe);
  2. the arithmetic matches a hand computation from the encoded legs;
  3. the Texas homestead exemption reaches the DEBT levy as well as operating, which
     secondary sources deny and the source data establishes.

Pure logic, no network. Runs standalone (``python tests/test_school_millage.py``) or via
pytest.
"""

from __future__ import annotations

import csv
import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parent.parent
for _p in (_ROOT, _ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from housing_label.data.govfinance import govfinance_for_county  # noqa: E402
from housing_label.data.propertytax import (  # noqa: E402
    median_home_value_for_county, property_tax_for_county,
)
from housing_label.data.school_millage import (  # noqa: E402
    covered_states, millage_for_county, owner_school_rate,
)
from housing_label.enrich.region_context import (  # noqa: E402
    BASIS_MEASURED, BASIS_SHARE, municipal_tax_rate,
)

_CSV = _ROOT / "src" / "housing_label" / "data" / "school_millage_county.csv"

TX_COUNTY_COUNT = 254
HARRIS, DALLAS = "48201", "48113"


def _rows() -> list[dict]:
    with _CSV.open(newline="") as f:
        return list(csv.DictReader(f))


# ── The crosswalk itself ─────────────────────────────────────────────────────────


def test_crosswalk_covers_every_texas_county_and_only_texas():
    """254 of 254, and no accidental second state.

    The coverage boundary is the whole safety argument for this change, so it is asserted
    rather than implied. A partial Texas would silently mix two netting bases within one
    state — neighbouring counties scored on different definitions.
    """
    rows = _rows()
    assert len(rows) == TX_COUNTY_COUNT, f"expected {TX_COUNTY_COUNT} counties, got {len(rows)}"
    assert covered_states() == ("TX",)
    assert {r["geoid"][:2] for r in rows} == {"48"}
    assert len({r["geoid"] for r in rows}) == len(rows), "duplicate county"


def test_rates_are_plausible_school_rates():
    """A column-mapping slip is the likeliest build failure, and it looks like this.

    Texas school M&O is compressed toward ~0.75 per $100 statewide; reading the wrong
    column (total rate, or a taxable value) would land orders of magnitude off. The band is
    deliberately loose — this catches a parse error, not a policy change.
    """
    for r in _rows():
        mo, isr = float(r["school_mo_rate"]), float(r["school_is_rate"])
        assert 0.004 <= mo <= 0.015, f"{r['geoid']} M&O {mo}"
        assert 0.0 <= isr <= 0.008, f"{r['geoid']} I&S {isr}"
        assert 0.0 <= float(r["is_exempt_weight"]) <= 1.0
        assert float(r["owner_exempt_value"]) == 100_000


def test_the_homestead_exemption_reaches_the_debt_levy():
    """The finding that sizes the whole correction, and it contradicts secondary sources.

    Whether Tex. Tax Code § 11.13(b)'s $100,000 exemption applies to the I&S levy as well
    as M&O is worth 10-13 percentage points of the correction. Search results say
    confidently that it does not. The Comptroller's own file says otherwise: the two
    taxable bases are EQUAL in the large majority of district-county rows, which could not
    happen if the exemption skipped the debt levy, since every district has homesteads.

    ``is_exempt_weight`` carries the measured per-county share, so the carve-out for
    districts with grandfathered debt is derived rather than assumed. If a future rebuild
    inverted the comparison, this median would collapse to 0 and the correction would
    quietly shrink toward the answer the secondary sources gave.
    """
    weights = sorted(float(r["is_exempt_weight"]) for r in _rows())
    median = weights[len(weights) // 2]
    assert median == 1.0, f"median I&S exemption weight {median} — the evidence says 1.0"
    # Stated as a mean rather than a count, because the county-level count is much weaker
    # than the row-level evidence it rests on: 132 of 254 counties are FULLY exempt, but
    # the mean weight is ~0.70 and the population-weighted mean ~0.88, since the districts
    # that may still tax exempted value for debt are small and rural. Asserting the mean
    # keeps the claim at the strength the data actually supports.
    mean = sum(weights) / len(weights)
    assert mean > 0.6, (
        f"mean I&S exemption weight {mean:.3f} — re-read the TAXABLE VALUE M&O vs I&S "
        "comparison in scripts/build_school_millage.py; if it inverted, this collapses "
        "toward 0 and the correction quietly shrinks to the secondary-source answer")
    assert sum(w == 0.0 for w in weights) < len(weights) * 0.2


# ── The rate computation ─────────────────────────────────────────────────────────


def test_owner_school_rate_matches_a_hand_computation():
    """The arithmetic, spelled out against the encoded legs rather than a magic number.

    Same discipline as ``test_multiplier_equals_the_ratio_of_its_legs`` in
    tests/test_assessment.py: assert the relationship, so the test survives a data refresh
    and still fails on a formula change.
    """
    rec = millage_for_county(HARRIS)
    assert rec is not None
    value = median_home_value_for_county(HARRIS)
    taxable = value - rec["owner_exempt_value"]
    w = rec["is_exempt_weight"]
    expected = (rec["school_mo_rate"] * taxable
                + rec["school_is_rate"] * (taxable * w + value * (1.0 - w))) / value
    assert abs(owner_school_rate(HARRIS, value) - expected) < 1e-12


def test_the_exemption_actually_reduces_the_rate():
    """A home at exactly the exemption owes no school operating tax, and the code says so.

    Texas has counties whose ACS median home value sits BELOW $100,000 — there the median
    owner genuinely pays no school M&O, and a near-zero owner school rate is the correct
    answer rather than a bug. Pinned because it looks wrong at a glance.
    """
    rec = millage_for_county(HARRIS)
    at_exemption = owner_school_rate(HARRIS, rec["owner_exempt_value"])
    # Only the un-exempted slice of the debt levy can survive.
    assert abs(at_exemption
               - rec["school_is_rate"] * (1.0 - rec["is_exempt_weight"])) < 1e-15
    below = owner_school_rate(HARRIS, rec["owner_exempt_value"] / 2)
    assert below <= at_exemption + 1e-12
    # And the rate rises with value, asymptotically toward the full school rate.
    assert (owner_school_rate(HARRIS, 1_000_000)
            > owner_school_rate(HARRIS, 300_000)
            > owner_school_rate(HARRIS, 150_000))


def test_uncovered_county_returns_none_not_zero():
    """None and 0.0 mean opposite things here, and confusing them would be catastrophic.

    0.0 would claim the owner pays NO school tax — netting nothing off the revenue side
    and inflating the score everywhere the crosswalk is absent. None means "no measurement,
    keep the multiplicative estimate", which is what every non-Texas county must get.
    """
    for fips in ("45045", "06037", "47157", "36061", "00000", "", None):
        assert owner_school_rate(fips, 300_000) is None, fips
        assert millage_for_county(fips) is None, fips
    # A covered county with an unusable value is also None, not zero.
    for bad in (None, 0, -1, "abc"):
        assert owner_school_rate(HARRIS, bad) is None, bad


# ── The wiring ───────────────────────────────────────────────────────────────────


def _legacy_rate(fips: str) -> float:
    """The pre-change computation, restated here on purpose.

    Duplicating the old formula is what makes the inertness test meaningful: if
    ``_municipal_rate``'s fallback branch is ever "simplified" into something subtly
    different, this catches it. A shared helper could not.
    """
    return (property_tax_for_county(fips)["effective_tax_rate"]
            * (1.0 - govfinance_for_county(fips)["school_tax_share"]))


def test_measured_path_fires_in_texas_and_only_there():
    for fips in (HARRIS, DALLAS, "48003", "48453"):
        rate, basis = municipal_tax_rate(fips)
        assert basis == BASIS_MEASURED, fips
        assert rate is not None and rate >= 0.0
    for fips in ("45045", "06037", "36061", "26163", "04013"):
        _, basis = municipal_tax_rate(fips)
        assert basis == BASIS_SHARE, fips


def test_every_county_outside_texas_is_bit_for_bit_unchanged():
    """The guarantee that makes shipping one state safe.

    Sampled across the states that carry the SAME defect (MI, AZ, SC) plus a few that do
    not, because those are exactly the counties a reader might assume this change already
    fixed. Equality is exact, not approximate — the fallback must be the identical
    expression, not an equivalent one.
    """
    for fips in ("45045", "45079", "26163", "26125", "04013", "04019",
                 "06037", "36061", "17031", "48000"[:5]):
        if fips.startswith("48"):
            continue
        rate, basis = municipal_tax_rate(fips)
        assert basis == BASIS_SHARE, fips
        assert rate == _legacy_rate(fips), fips


def test_texas_moves_both_ways_and_mostly_up():
    """Be honest about direction: the DEFECT is one-directional, the FIX is not.

    The old path always over-nets, so the correction is upward on balance — but it replaces
    an estimate with a measurement, so an individual county can land either side. Asserting
    the population-weighted direction rather than a per-county floor, because a per-county
    floor would be a false claim.
    """
    ups = downs = 0
    for r in _rows():
        fips = r["geoid"]
        new, _ = municipal_tax_rate(fips)
        old = _legacy_rate(fips)
        if old <= 0:
            continue
        ups += new > old
        downs += new < old
    assert ups + downs > 200, "the measured path barely moved anything — check the wiring"
    assert ups > downs * 4, f"expected a mostly-upward correction, got {ups} up / {downs} down"


def test_municipal_rate_never_goes_negative():
    """A county whose measured school rate exceeds its ACS bill is a vintage mismatch.

    ACS 5-year medians and a single-year millage file do not describe the same moment, so
    the subtraction can overshoot in a small, noisy county. Clamping at zero keeps that
    from becoming negative municipal revenue, which would invert the fiscal ratio.
    """
    for r in _rows():
        rate, _ = municipal_tax_rate(r["geoid"])
        assert rate >= 0.0, r["geoid"]


def test_counties_with_a_suppressed_acs_median_keep_the_estimate():
    """Having millage is not enough — the subtraction needs a median value too.

    ACS suppresses B25077 for a handful of very small counties. Those already fall back to
    the NATIONAL effective rate, so subtracting a measured Texas school rate from it would
    mix two geographies in one expression and overstate the correction badly. The code
    declines instead, and this pins that: they must stay on the share path.
    """
    stranded = [r["geoid"] for r in _rows()
                if median_home_value_for_county(r["geoid"]) is None]
    assert stranded, "no suppressed counties left — has the ACS vintage changed?"
    for fips in stranded:
        assert property_tax_for_county(fips)["resolved"] == "national", fips
        rate, basis = municipal_tax_rate(fips)
        assert basis == BASIS_SHARE, fips
        assert rate == _legacy_rate(fips), fips
    measured = [r["geoid"] for r in _rows()
                if municipal_tax_rate(r["geoid"])[1] == BASIS_MEASURED]
    assert len(measured) + len(stranded) == TX_COUNTY_COUNT


def test_shelby_still_opts_out():
    """The pilot county keeps its statutory Memphis basis on both accessors."""
    assert municipal_tax_rate("47157") == (None, None)
    assert municipal_tax_rate(None) == (None, None)


def _run_all():
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} tests passed.")


if __name__ == "__main__":
    _run_all()
