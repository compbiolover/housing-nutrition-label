#!/usr/bin/env python3
"""Tests for the Air Quality lookup + scoring (data/air_quality.py).

Offline — reads the bundled air_quality.csv (county) and air_quality_tracts.csv.gz
(tract) only. Execute directly (python tests/test_air_quality.py) or via pytest.
"""

from __future__ import annotations

import csv
import gzip

from housing_label.data import air_quality as A


def test_known_counties_resolve_and_score():
    la = A.air_quality_for_county("06037")     # Los Angeles, CA — poor air
    shelby = A.air_quality_for_county("47157")  # Shelby, TN (Memphis)
    assert la is not None and shelby is not None
    for rec in (la, shelby):
        assert 0.0 <= rec["score"] <= 100.0
        assert rec["pm25"] is not None and rec["ozone"] is not None
        assert A.AIR_QUALITY_VINTAGE in rec["label"]
    # LA's chronically high PM2.5 + ozone should score worse than Memphis.
    assert la["score"] < shelby["score"]


def test_fips_is_zero_padded():
    assert A.air_quality_for_county("6037") == A.air_quality_for_county("06037")


def test_missing_and_absent_return_none():
    assert A.air_quality_for_county(None) is None
    assert A.air_quality_for_county("") is None
    assert A.air_quality_for_county("99999") is None   # not a real county


def test_radon_weight_redistributes_when_absent():
    """A county with no EPA radon zone is still scored on PM2.5 + ozone alone
    (radon's weight redistributed), never left unscored for that reason."""
    with A._CSV.open() as f:
        no_radon = [r["county_fips"] for r in csv.DictReader(f)
                    if not r["radon_zone"] and r["pm25_ugm3"]]
    assert no_radon, "expected at least one county without an EPA radon zone"
    rec = A.air_quality_for_county(no_radon[0])
    assert rec is not None and rec["radon_zone"] is None
    assert rec["radon_score"] is None
    assert rec["score"] is not None            # scored from PM2.5 + ozone


def test_cleaner_air_scores_higher():
    """The score is monotonic in air quality: a clean-PM2.5/low-radon county
    outscores a high-PM2.5 one."""
    # Cleaner PM2.5 → higher PM sub-score.
    lo = A._interp(5.0, A._PM25_XS, A._PM25_YS)
    hi = A._interp(9.5, A._PM25_XS, A._PM25_YS)
    assert lo > hi
    # Radon Zone 3 (low) beats Zone 1 (high).
    assert A._RADON_SCORE[3] > A._RADON_SCORE[2] > A._RADON_SCORE[1]


def test_tract_resolves_at_tract_level():
    """A real 11-digit tract GEOID scores at tract resolution (geo_level 'tract')
    using tract PM2.5/ozone plus its county's radon zone."""
    geoid = next(iter(A._tract_table()))          # any bundled tract
    rec = A.air_quality_for_tract(geoid)
    assert rec is not None
    assert rec["geo_level"] == "tract"
    assert 0.0 <= rec["score"] <= 100.0
    assert rec["pm25"] is not None and rec["ozone"] is not None


def test_tract_falls_back_to_county():
    """A tract GEOID whose county exists but whose tract row is absent falls back
    to the county reading (geo_level 'county'), never unscored."""
    fake = "06037" + "999999"                     # LA county, non-existent tract
    assert fake not in A._tract_table()
    rec = A.air_quality_for_tract(fake)
    assert rec is not None and rec["geo_level"] == "county"
    assert rec["score"] == A.air_quality_for_county("06037")["score"]


def test_non_conus_tract_and_blank_return_none():
    assert A.air_quality_for_tract("02020000100") is None   # Anchorage, AK — non-CONUS
    assert A.air_quality_for_tract(None) is None
    assert A.air_quality_for_tract("") is None


def test_tract_gz_is_well_formed():
    seen = 0
    with gzip.open(A._TRACT_CSV_GZ, "rt") as f:
        for row in csv.DictReader(f):
            g = row["geoid"]
            assert len(g) == 11 and g.isdigit()
            assert float(row["pm25_ugm3"]) > 0
            assert float(row["ozone_ppb"]) > 0
            seen += 1
    assert seen > 50000   # ~84k CONUS tracts


def test_bundled_csv_is_well_formed():
    seen = 0
    with A._CSV.open() as f:
        for row in csv.DictReader(f):
            fips = row["county_fips"]
            assert len(fips) == 5 and fips.isdigit()
            # PM2.5 and ozone present for every row; radon optional.
            assert float(row["pm25_ugm3"]) > 0
            assert float(row["ozone_ppb"]) > 0
            if row["radon_zone"]:
                assert int(row["radon_zone"]) in (1, 2, 3)
            seen += 1
    assert seen > 3000   # ~3,000 US counties


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} tests passed.")


if __name__ == "__main__":
    _run_all()
