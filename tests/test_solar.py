#!/usr/bin/env python3
"""Tests for the Solar Potential lookup + scoring (data/solar.py).

Offline — reads the bundled solar_yield_county.csv only. Execute directly
(python tests/test_solar.py) or via pytest.
"""

from __future__ import annotations

import csv

from housing_label.data import solar as S


def test_known_counties_resolve_and_rank():
    phoenix = S.solar_for_county("04013")     # Maricopa, AZ — desert, best-in-class
    seattle = S.solar_for_county("53033")     # King, WA — cloudy Pacific NW
    memphis = S.solar_for_county("47157")     # Shelby, TN — middle of the pack
    for rec in (phoenix, seattle, memphis):
        assert rec is not None
        assert 0.0 <= rec["score"] <= 100.0
        assert rec["yield_kwh_kwp"] > 0
        assert S.SOLAR_VINTAGE in rec["label"]
    # Sunnier location → higher yield → higher score.
    assert phoenix["yield_kwh_kwp"] > memphis["yield_kwh_kwp"] > seattle["yield_kwh_kwp"]
    assert phoenix["score"] > memphis["score"] > seattle["score"]


def test_fips_is_zero_padded():
    assert S.solar_for_county("4013") == S.solar_for_county("04013")


def test_missing_and_absent_return_none():
    assert S.solar_for_county(None) is None
    assert S.solar_for_county("") is None
    assert S.solar_for_county("99999") is None   # not a real county


def test_score_is_monotonic_in_yield():
    lo = S._interp(1100.0, S._YIELD_XS, S._YIELD_YS)
    mid = S._interp(1370.0, S._YIELD_XS, S._YIELD_YS)
    hi = S._interp(1700.0, S._YIELD_XS, S._YIELD_YS)
    assert lo < mid < hi          # higher yield ⇒ higher score


def test_bundled_csv_is_well_formed():
    seen = 0
    with S._CSV.open() as f:
        for row in csv.DictReader(f):
            fips = row["county_fips"]
            assert len(fips) == 5 and fips.isdigit()
            assert float(row["specific_yield_kwh_kwp"]) > 0
            assert float(row["irradiation_kwh_m2"]) > 0
            seen += 1
    assert seen > 3000   # ~3,200 US counties within PVGIS coverage


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} tests passed.")


if __name__ == "__main__":
    _run_all()
