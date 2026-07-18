#!/usr/bin/env python3
"""Tests for the Air Quality lookup + scoring (data/air_quality.py).

Offline — reads the bundled air_quality.csv only. Execute directly
(python tests/test_air_quality.py) or via pytest.
"""

from __future__ import annotations

import csv

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
    no_radon = [r["county_fips"] for r in csv.DictReader(A._CSV.open())
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
