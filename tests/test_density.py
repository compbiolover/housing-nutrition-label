#!/usr/bin/env python3
"""Offline tests for the per-parcel density comparison (fixed lot, vary units).

Runs without network access and without pytest — execute directly:
  python tests/test_density.py
(pytest will also collect the test_* functions if it is installed.)
"""

from housing_label.simulate.house import density_comparison, DENSITY_UNIT_COUNTS

# A fixed Shelby-area point with an explicit value so the per-unit baseline is
# deterministic offline (no county auto-fill needed).
_COMMON = dict(lat=35.15, lon=-89.85, allow_network=False, value=250_000)


def test_default_sweep_shape():
    """The default comparison returns one scenario per default unit count, named."""
    comp = density_comparison(**_COMMON)
    units = [s["units"] for s in comp["scenarios"]]
    assert units == list(DENSITY_UNIT_COUNTS)
    names = {s["units"]: s["name"] for s in comp["scenarios"]}
    assert names[1] == "Single-family"
    assert names[2] == "Duplex"
    assert names[4] == "Quadplex"
    assert comp["model"] == "fixed-lot-vary-units"


def test_per_unit_value_constant_total_scales():
    """Per-unit value is held constant; total value scales with the unit count."""
    comp = density_comparison(**_COMMON)
    assert comp["per_unit_value"] == 250_000
    for s in comp["scenarios"]:
        assert abs(s["per_unit_value"] - 250_000) < 1e-6
        assert abs(s["value"] - 250_000 * s["units"]) < 1e-6


def test_lot_fixed_per_unit_acres_split():
    """Lot size is fixed across scenarios; per-unit acreage is lot / units."""
    comp = density_comparison(lot_acres=0.20, **_COMMON)
    lot = comp["lot_acres"]
    assert abs(lot - 0.20) < 1e-9
    for s in comp["scenarios"]:
        assert abs(s["lot_acres"] - 0.20) < 1e-9
        # per_unit_acres is rounded to 4 dp in the summary.
        assert abs(s["per_unit_acres"] - 0.20 / s["units"]) < 1e-4


def test_density_dividend_improves_infrastructure():
    """The density dividend: more units on the same lot don't worsen — and here
    improve — the Infrastructure fiscal ratio and score (cost shared across homes)."""
    comp = density_comparison(**_COMMON)
    scn = comp["scenarios"]
    first, last = scn[0], scn[-1]
    # Fiscal ratio and infra score are monotonic non-decreasing with density.
    fr = [s["fiscal_ratio"] for s in scn]
    inf = [s["infrastructure_score"] for s in scn]
    assert all(b >= a - 1e-9 for a, b in zip(fr, fr[1:]))
    assert all(b >= a - 1e-9 for a, b in zip(inf, inf[1:]))
    # And the headline dividend strictly improves from single-family to quadplex.
    assert last["fiscal_ratio"] > first["fiscal_ratio"]
    assert last["infrastructure_score"] > first["infrastructure_score"]
    dd = comp["density_dividend"]
    assert dd["from_units"] == 1 and dd["to_units"] == 4
    assert dd["fiscal_ratio_to"] == last["fiscal_ratio"]
    assert dd["infrastructure_grade_from"] == first["infrastructure_grade"]


def test_explicit_value_treated_as_per_unit():
    """An explicit value is the per-unit value; total scales from it."""
    comp = density_comparison(lat=35.15, lon=-89.85, allow_network=False,
                              value=180_000, unit_counts=[1, 2])
    assert comp["per_unit_value"] == 180_000
    assert comp["value_source"] is None          # explicit, not auto-filled
    by_units = {s["units"]: s for s in comp["scenarios"]}
    assert set(by_units) == {1, 2}
    assert abs(by_units[2]["value"] - 360_000) < 1e-6


def test_per_unit_value_overrides_value():
    """per_unit_value wins over an explicit value as the held-constant baseline."""
    comp = density_comparison(lat=35.15, lon=-89.85, allow_network=False,
                              value=999_999, per_unit_value=200_000, unit_counts=[1, 3])
    assert comp["per_unit_value"] == 200_000
    by_units = {s["units"]: s for s in comp["scenarios"]}
    assert abs(by_units[3]["value"] - 600_000) < 1e-6


def test_unit_counts_deduped_and_sorted():
    """Unit counts are de-duplicated and ascending; sub-1 counts are dropped."""
    comp = density_comparison(unit_counts=[4, 2, 2, 0, 1], **_COMMON)
    assert [s["units"] for s in comp["scenarios"]] == [1, 2, 4]


def test_empty_unit_counts_raises():
    """No valid unit counts is a clean validation error."""
    try:
        density_comparison(unit_counts=[0, -1], **_COMMON)
    except ValueError:
        return
    raise AssertionError("expected ValueError for empty unit_counts")


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} tests passed.")


if __name__ == "__main__":
    _run_all()
