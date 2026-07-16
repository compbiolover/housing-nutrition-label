#!/usr/bin/env python3
"""Tests for the Cambium LRMER marginal grid factor lookup (data/cambium.py).

Offline — reads the bundled cambium_lrmer.csv only. Execute directly
(python tests/test_cambium.py) or via pytest.
"""

from __future__ import annotations

import csv

from housing_label.data import cambium as C


def test_known_counties_resolve():
    # Shelby County, TN (Memphis) → SERTP; Los Angeles County, CA → CAISO.
    shelby = C.cambium_lrmer_for_county("47157")
    la = C.cambium_lrmer_for_county("06037")
    assert shelby is not None and la is not None
    shelby_label, shelby_factor = shelby
    la_label, la_factor = la
    assert "SERTP" in shelby_label and "CAISO" in la_label
    assert C.CAMBIUM_VINTAGE in shelby_label
    # Plausible marginal-rate magnitudes (kgCO2e/kWh).
    assert 0.0 < shelby_factor < 0.6
    assert 0.0 < la_factor < 0.6


def test_fips_is_zero_padded():
    # A caller passing an unpadded integer-ish FIPS still resolves.
    assert C.cambium_lrmer_for_county("6037") == C.cambium_lrmer_for_county("06037")


def test_conus_only_and_missing_return_none():
    # Alaska (02), Hawai'i (15), Puerto Rico (72) are outside Cambium's GEA
    # regions, as is a missing/blank FIPS — all fall back (None) to the average.
    assert C.cambium_lrmer_for_county("02020") is None   # Anchorage, AK
    assert C.cambium_lrmer_for_county("15003") is None   # Honolulu, HI
    assert C.cambium_lrmer_for_county("72127") is None   # San Juan, PR
    assert C.cambium_lrmer_for_county(None) is None
    assert C.cambium_lrmer_for_county("") is None


def test_bundled_csv_is_well_formed():
    """Every row is a 5-digit CONUS FIPS with a positive factor and known region."""
    seen = 0
    with C._CSV.open() as f:
        for row in csv.DictReader(f):
            fips = row["county_fips"]
            assert len(fips) == 5 and fips.isdigit()
            assert fips[:2] not in ("02", "15", "72")   # CONUS only
            assert row["gea_region"] in C._GEA_NAMES
            assert float(row["lrmer_kgco2e_kwh"]) > 0
            seen += 1
    assert seen > 3000   # ~3,100 CONUS counties


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} tests passed.")


if __name__ == "__main__":
    _run_all()
