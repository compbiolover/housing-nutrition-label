#!/usr/bin/env python3
"""Offline tests for the user-fee revenue leg of the fiscal ratio.

The cost side counts water, sewer, and trash in full, but residents pay for those
through utility bills and a monthly fee rather than property tax. The revenue side
therefore counts modeled fee income alongside property tax, using each county's
actual current-charges-to-expenditure ratio from the Census of Governments.

Runs without network access. This file alone:
  pytest tests/test_fee_revenue.py
"""

from __future__ import annotations

import pandas as pd

from housing_label.data.govfinance import COMPONENTS, govfinance_for_county
from housing_label.enrich.infrastructure import SHELBY_FEE_RECOVERY, enrich_row


def _row(units: int = 1, lot_acres: float = 0.25, value: float = 250_000) -> pd.Series:
    return pd.Series({"CALC_ACRE": lot_acres / units, "RTOTAPR": value,
                      "latitude": 35.1450, "longitude": -90.0500})


def test_crosswalk_exposes_fee_recovery_for_every_component():
    for fips in ("47157", "06037", None):
        gov = govfinance_for_county(fips)
        fee = gov["fee_recovery"]
        assert set(fee) == set(COMPONENTS)
        assert all(0.0 <= v <= 1.0 for v in fee.values()), fee


def test_fire_and_police_have_no_user_charge_anywhere():
    """The Census classification has no current-charge code for either function, so
    property tax is genuinely the only thing paying for them. This is the reason the
    typical home still doesn't reach a ratio of 1.0 even with fees counted."""
    for fips in ("47157", "06037", "36119", None):
        fee = govfinance_for_county(fips)["fee_recovery"]
        assert fee["fire"] == 0.0 and fee["police"] == 0.0


def test_utility_surplus_is_capped_at_break_even():
    """Shelby's MLGW recovers more than its own expenditure; crediting >100% would
    let a home generate phantom general-fund revenue on its pipes."""
    assert SHELBY_FEE_RECOVERY["water_sewer"] == 1.0
    assert all(0.0 <= v <= 1.0 for v in SHELBY_FEE_RECOVERY.values())
    assert govfinance_for_county("47157")["fee_recovery"]["water_sewer"] <= 1.0


def test_fee_revenue_is_the_cost_weighted_sum():
    out = enrich_row(_row())
    expected = sum(float(out[f"infra_cost_{c}"]) * SHELBY_FEE_RECOVERY[c]
                   for c in COMPONENTS)
    assert abs(float(out["est_fee_revenue"]) - expected) < 0.01
    assert abs(float(out["est_total_revenue"])
               - (float(out["est_property_tax"]) + float(out["est_fee_revenue"]))) < 0.01


def test_ratio_and_balance_use_total_revenue():
    out = enrich_row(_row())
    cost = float(out["est_annual_infra_cost"])
    total = float(out["est_total_revenue"])
    assert abs(float(out["fiscal_ratio"]) - total / cost) < 1e-4
    assert abs(float(out["fiscal_balance"]) - (total - cost)) < 0.01


def test_zero_fee_recovery_reproduces_tax_only_behavior():
    """The pre-fee model is exactly the fee_recovery={} case, so the new term is a
    clean addition rather than a rewrite of the cost side."""
    zero = enrich_row(_row(), fee_recovery={c: 0.0 for c in COMPONENTS})
    assert zero["est_fee_revenue"] == 0.0
    assert zero["est_total_revenue"] == zero["est_property_tax"]
    assert abs(float(zero["fiscal_ratio"])
               - float(zero["est_property_tax"]) / float(zero["est_annual_infra_cost"])) < 1e-4
    # And counting fees strictly helps, since recovery is never negative.
    assert float(enrich_row(_row())["fiscal_ratio"]) > float(zero["fiscal_ratio"])


def test_malformed_fee_recovery_degrades_instead_of_raising():
    """enrich_row is importable, so fee_recovery can arrive from outside the
    crosswalk that normally sanitizes it. Junk entries must read as "no fee credit"
    rather than raising, and must never over-credit."""
    baseline = float(enrich_row(_row(), fee_recovery={c: 0.0 for c in COMPONENTS})
                     ["est_fee_revenue"])
    for junk in ({}, {c: None for c in COMPONENTS}, {c: "n/a" for c in COMPONENTS},
                 {c: float("nan") for c in COMPONENTS}, {c: -5.0 for c in COMPONENTS}):
        out = enrich_row(_row(), fee_recovery=junk)
        assert float(out["est_fee_revenue"]) == baseline == 0.0
        assert float(out["est_total_revenue"]) == float(out["est_property_tax"])


def test_out_of_range_fee_recovery_is_capped_at_break_even():
    """The documented "never credit a utility surplus" cap holds at the point of
    use, not only in the loader — a caller can't hand in 300% recovery."""
    over = enrich_row(_row(), fee_recovery={c: 3.0 for c in COMPONENTS})
    full = enrich_row(_row(), fee_recovery={c: 1.0 for c in COMPONENTS})
    assert float(over["est_fee_revenue"]) == float(full["est_fee_revenue"])
    # Capped at 1.0 means fee revenue can never exceed the cost it is recovering.
    assert float(over["est_fee_revenue"]) <= float(over["est_annual_infra_cost"]) + 0.01


def test_fee_revenue_amortizes_with_density():
    """Fee revenue rides on modeled cost, so per-unit it falls as density rises —
    unlike property tax, which tracks value per door. A dense parcel therefore gains
    less from this term than a sprawling one, which is the correct direction: its
    pipes and collection stops genuinely cost less to serve."""
    sprawl = enrich_row(_row(units=1, lot_acres=2.0))
    tower = enrich_row(_row(units=157, lot_acres=1.0), units=157)
    assert float(sprawl["est_fee_revenue"]) > float(tower["est_fee_revenue"])
