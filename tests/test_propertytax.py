#!/usr/bin/env python3
"""Offline tests for the Census-ACS per-county effective-property-tax-rate layer:
the lookup, the revenue-side scaling in the infra model, and the caveat wiring.

Runs without network access and without pytest — execute directly:
  python tests/test_propertytax.py
"""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from housing_label.data import propertytax as pt
from housing_label.data.propertytax import (
    property_tax_for_county, median_home_value_for_county,
)
from housing_label.enrich.infrastructure import enrich_row


def _approx(a, b, tol=1e-9):
    return abs(float(a) - float(b)) <= tol


# ── Bundled crosswalk + lookup ──────────────────────────────────────────────────
def test_crosswalk_present_with_shelby_and_national():
    table = pt._table()
    assert table, "property-tax crosswalk is empty/missing"
    assert "47157" in table                      # Shelby County, TN
    assert "00000" in table                      # national-average row
    assert "06037" in table                      # Los Angeles County, CA


def test_rate_discriminates_by_county():
    """Effective rates vary widely by county (the whole point of localizing)."""
    la = property_tax_for_county("06037")
    westchester = property_tax_for_county("36119")
    assert la["resolved"] == "county" and westchester["resolved"] == "county"
    assert westchester["effective_tax_rate"] > la["effective_tax_rate"] * 1.5


def test_rates_within_clamp_range():
    for fips in ("47157", "06037", "36119", "01001"):
        r = property_tax_for_county(fips)["effective_tax_rate"]
        assert 0.001 <= r <= 0.05, f"{fips} rate {r} out of clamp range"


def test_unmapped_and_none_fall_back_to_national():
    nat = property_tax_for_county(None)
    assert nat["resolved"] == "national" and nat["geo_level"] == "us"
    assert property_tax_for_county("99999")["resolved"] == "national"
    assert 0.001 <= nat["effective_tax_rate"] <= 0.05


def test_median_home_value_lookup():
    """median_home_value_for_county returns sane county medians (for auto-fill),
    and None for an unmapped/None county."""
    shelby = median_home_value_for_county("47157")
    la = median_home_value_for_county("06037")
    assert shelby and 50_000 < shelby < 1_000_000
    assert la and la > shelby                          # LA homes pricier than Memphis
    assert median_home_value_for_county("99999") is None
    assert median_home_value_for_county(None) is None


# ── Revenue scaling in the infra model ──────────────────────────────────────────
_ROW = pd.Series({"CALC_ACRE": 0.25, "latitude": 40.9, "longitude": -73.78,
                  "RTOTAPR": 600000})


def test_tax_rate_drives_revenue_and_ratio():
    """A higher county effective rate yields proportionally more estimated tax
    revenue (and a higher fiscal ratio) at the same home value."""
    lo = property_tax_for_county("06037")["effective_tax_rate"]        # ~0.70%
    hi = property_tax_for_county("36119")["effective_tax_rate"]        # ~1.6%
    out_lo = enrich_row(_ROW, assess_ratio=1.0, tax_rate=lo, in_urban_area=True)
    out_hi = enrich_row(_ROW, assess_ratio=1.0, tax_rate=hi, in_urban_area=True)
    # est_property_tax = appraised * assess_ratio * tax_rate, so it tracks the rate.
    assert _approx(out_lo["est_property_tax"], 600000 * lo, 0.01)
    assert out_hi["est_property_tax"] > out_lo["est_property_tax"]
    assert out_hi["fiscal_ratio"] > out_lo["fiscal_ratio"]


# ── Caveat wiring (house.py) ────────────────────────────────────────────────────
def test_caveat_mentions_acs_revenue_for_mapped_county():
    """For a county in the crosswalks, the caveat names both the Census-of-
    Governments cost calibration and the ACS property-tax (revenue) calibration."""
    from housing_label.simulate.house import _approx_caveats
    loc = SimpleNamespace(county_fips="06037", egrid_subregion="CAMX")
    msg = " ".join(_approx_caveats(loc))
    assert "Census ACS" in msg and "revenue side" in msg


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} tests passed.")


if __name__ == "__main__":
    _run_all()
