#!/usr/bin/env python3
"""Tests for the Tier-3 de-Shelbyfication of the batch enrich stages.

Covers the shared region-context helper and the national paths of the seismic,
tornado, and noaa_climate enrichers — plus that Shelby/default behavior is
preserved. Pure logic, no network. Runs standalone (``python
tests/test_tier3_enrich.py``) or via pytest.
"""

from __future__ import annotations

import pathlib
import sys

import pandas as pd

_ROOT = pathlib.Path(__file__).resolve().parent.parent
for _p in (_ROOT, _ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from housing_label.enrich import region_context as RC  # noqa: E402
from housing_label.enrich import seismic as S  # noqa: E402
from housing_label.enrich import tornado as T  # noqa: E402
from housing_label.enrich import noaa_climate as N  # noqa: E402
from housing_label.enrich import seismic_lookup as SL  # noqa: E402


# ── region_context ────────────────────────────────────────────────────────────
def test_infra_params_shelby_and_unknown_are_none():
    assert RC.infra_params_for_county(None) is None
    assert RC.infra_params_for_county("47157") is None      # Shelby → Memphis defaults
    assert RC.infra_params_for_county("47157".zfill(5)) is None


def test_infra_params_national_county():
    p = RC.infra_params_for_county("06037", in_urban_area=True)   # Los Angeles County
    assert p is not None
    assert set(p) == {"assess_ratio", "tax_rate", "in_urban_area", "cost_multipliers"}
    assert p["assess_ratio"] == 1.0 and p["in_urban_area"] is True
    assert isinstance(p["tax_rate"], float) and p["tax_rate"] > 0
    # municipal_rate = ACS effective rate × (1 − school share)
    from housing_label.data.govfinance import govfinance_for_county
    from housing_label.data.propertytax import property_tax_for_county
    gov = govfinance_for_county("06037")
    tax = property_tax_for_county("06037")
    assert abs(p["tax_rate"] - tax["effective_tax_rate"] * (1 - gov["school_tax_share"])) < 1e-12
    assert set(p["cost_multipliers"]) >= {"roads", "water_sewer", "fire", "police"}


def test_climate_zone_for_county_fips():
    assert RC.climate_zone_for_county_fips(None) == (None, None)
    zone, desc = RC.climate_zone_for_county_fips("06037")       # LA
    assert zone == "3B" and desc == "Warm-Dry"


# ── seismic ───────────────────────────────────────────────────────────────────
def test_seismic_national_bands_monotonic():
    order = ["very low", "low", "moderate", "high", "very high"]
    ranks = [order.index(S._national_risk(p)) for p in (0.04, 0.10, 0.20, 0.35, 0.70)]
    assert ranks == sorted(ranks) and ranks[0] == 0 and ranks[-1] == 4
    assert [S._national_sdc(p) for p in (0.05, 0.10, 0.20, 0.40, 0.60)] == ["A", "B", "C", "D", "E"]


def test_seismic_uses_national_pga(monkeypatch=None):
    """enrich_parcel writes the national mapped PGA + derived labels."""
    orig = SL.get_pga
    SL.get_pga = lambda lat, lon, allow_network=True: (0.50, 0.20, "USGS ASCE7 (2%/50yr)")
    try:
        r = S.enrich_parcel(34.05, -118.24)      # LA
    finally:
        SL.get_pga = orig
    assert r["pga_2pct_50yr"] == 0.50 and r["pga_10pct_50yr"] == 0.20
    assert r["seismic_design_category"] == "E" and r["seismic_risk"] == "high"
    assert "USGS" in r["soil_amplification_note"]


def test_seismic_offline_falls_back_to_legacy():
    orig = SL.get_pga
    SL.get_pga = lambda lat, lon, allow_network=True: None   # no USGS, no grid
    try:
        r = S.enrich_parcel(35.05, -90.0)        # Memphis
    finally:
        SL.get_pga = orig
    # Legacy New-Madrid model: Memphis is county-wide SDC "D", high PGA.
    assert r["seismic_design_category"] == "D"
    assert 0.3 < r["pga_2pct_50yr"] < 0.7
    assert r["seismic_risk"] in ("very high", "high")


# ── tornado ───────────────────────────────────────────────────────────────────
def test_tornado_national_bands():
    assert T._national_risk(0.1, -1) == "low"
    assert T._national_risk(0.3, -1) == "moderate"
    assert T._national_risk(0.8, -1) == "high"
    assert T._national_risk(0.1, 4) == "high"        # a violent tornado nearby


def _tornado_df(points):
    return pd.DataFrame([{"slat": la, "slon": lo, "mag": m} for la, lo, m in points])


def test_tornado_point_centered_no_bleed():
    """A parcel counts only tornadoes near IT, not a far-away cluster."""
    near = [(35.15, -89.98, 2)] * 3 + [(35.20, -89.98, 1)] * 2   # ~all within 10 mi of Shelby
    far = [(40.00, -100.00, 3)] * 5                               # ~700 mi away
    df = _tornado_df(near + far)

    shelby = T.enrich_parcel(35.15, -89.98, df)
    assert shelby["tornado_count_25mi"] == 5      # only the near cluster
    assert shelby["tornado_count_10mi"] == 5
    assert shelby["max_ef_25mi"] == 2

    plains = T.enrich_parcel(40.00, -100.00, df)
    assert plains["tornado_count_25mi"] == 5      # only the far cluster
    assert plains["max_ef_25mi"] == 3
    # avg/yr = count / 74 years
    assert plains["avg_tornadoes_per_yr_25mi"] == round(5 / T.DATA_YEARS, 3)


def test_tornado_dateline_wraparound():
    """A parcel just west of +180° counts tornadoes just east of −180° (same place)."""
    # Two records ~3 mi apart straddling the antimeridian near 52°N.
    df = _tornado_df([(52.00, 179.98, 1), (52.00, -179.99, 2)])
    r = T.enrich_parcel(52.00, 179.99, df)
    assert r["tornado_count_25mi"] == 2           # both counted despite the ±180° seam
    assert r["max_ef_25mi"] == 2


# ── noaa_climate ──────────────────────────────────────────────────────────────
def test_noaa_shelby_unchanged():
    row = N.climate_row_for_county(None)
    assert row == N.MEMPHIS_CLIMATE                # None → full Memphis normals
    assert N.climate_row_for_county("47157")["hdd_annual"] == 3082


def test_noaa_national_zone_nulls_degree_days():
    row = N.climate_row_for_county("06037")        # LA
    assert row["climate_zone"] == "3B" and row["climate_zone_desc"] == "Warm-Dry"
    assert row["hdd_annual"] is None and row["cdd_annual"] is None
    assert row["avg_jul_high_f"] is None
    assert set(row) == set(N.CLIMATE_COLS)         # same column set, just nulled
    assert "NOAA CDO API" in row["climate_station"]


def _run_all():
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} tests passed.")


if __name__ == "__main__":
    _run_all()
