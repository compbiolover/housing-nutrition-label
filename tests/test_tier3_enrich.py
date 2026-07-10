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

_ROOT = pathlib.Path(__file__).resolve().parent.parent
for _p in (_ROOT, _ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from housing_label.enrich import region_context as RC  # noqa: E402
from housing_label.enrich import seismic as S  # noqa: E402
from housing_label.enrich import tornado as T  # noqa: E402
from housing_label.enrich import noaa_climate as N  # noqa: E402
from housing_label.enrich import seismic_lookup as SL  # noqa: E402
from housing_label.enrich import infrastructure as I  # noqa: E402


def test_as_bool_parses_csv_forms():
    for v in ("True", "true", "1", "yes", "Y", "t", 1, 1.0, True):
        assert I._as_bool(v) is True
    for v in ("False", "false", "0", "no", "n", "f", "", 0, 0.0, False):
        assert I._as_bool(v) is False


# ── region_context ────────────────────────────────────────────────────────────
def test_infra_params_shelby_and_unknown_are_none():
    assert RC.infra_params_for_county(None) is None
    assert RC.infra_params_for_county("47157") is None      # Shelby → Memphis defaults
    assert RC.infra_params_for_county("47157".zfill(5)) is None


def test_normalize_fips():
    assert RC.normalize_fips(None) is None
    assert RC.normalize_fips(float("nan")) is None
    assert RC.normalize_fips("") is None
    assert RC.normalize_fips("nan") is None
    assert RC.normalize_fips(47157.0) == "47157"        # float-parsed CSV
    assert RC.normalize_fips(6037) == "06037"           # lost leading zero
    assert RC.normalize_fips("06037.0") == "06037"      # float-string
    assert RC.normalize_fips(" 6037 ") == "06037"
    assert RC.normalize_fips("47157") == "47157"


def test_infra_params_national_county():
    p = RC.infra_params_for_county("06037", in_urban_area=True)   # Los Angeles County
    assert p is not None
    assert set(p) == {"assess_ratio", "tax_rate", "in_urban_area", "cost_multipliers"}
    assert p["assess_ratio"] == 1.0 and p["in_urban_area"] is True
    assert isinstance(p["tax_rate"], float) and p["tax_rate"] > 0
    # in_urban_area is parcel-level → omitted (not forced) when not supplied
    p2 = RC.infra_params_for_county("06037")
    assert "in_urban_area" not in p2
    assert RC.infra_params_for_county(47157.0) is None            # float Shelby → defaults
    assert RC.infra_params_for_county(float("nan")) is None       # NaN → defaults
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


# ── tornado (FEMA NRI, offline crosswalk) ─────────────────────────────────────
def test_tornado_norm_tract():
    """The join key is normalised to an 11-digit GEOID (mirrors enrich/fire)."""
    assert T._norm_tract("47157006300.0") == "47157006300"   # stringified float
    assert T._norm_tract(6037139000.0) == "06037139000"      # leading zero restored
    assert T._norm_tract(None) is None
    assert T._norm_tract(float("nan")) is None
    assert T._norm_tract("  nan ") is None


def test_tornado_lookup_shelby_county_fallback():
    """No census tract → the Shelby county-level NRI tornado rate (a real, positive
    EAL, resolved at county level for every Shelby parcel)."""
    t = T._lookup(None)
    assert t["geo_level"] == "county"
    assert t["eal_rate"] > 0
    assert t["risk_rating"]                       # Shelby carries a qualitative rating


def test_tornado_lookup_is_location_specific():
    """NRI is honest about location: a Plains 'tornado alley' county reads far higher
    than a low-risk West-coast one — the whole point of retiring the SPC model."""
    from housing_label.data import tornado as TD
    oklahoma = TD.tornado_for_county("40109")     # Oklahoma County, OK
    los_angeles = TD.tornado_for_county("06037")  # Los Angeles County, CA
    assert oklahoma["eal_rate"] > 10 * los_angeles["eal_rate"]


def test_tornado_lookup_unknown_county_national_fallback():
    """An unmapped county falls back to the national average (never None/raises)."""
    t = T._lookup(None, county_fips="99999")
    assert t["geo_level"] == "us"
    assert t["resolved"] is False
    assert t["eal_rate"] >= 0


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


def test_noaa_missing_fips_falls_back_to_shelby():
    """NaN / float Shelby FIPS resolve correctly (not '00nan' / '47157.0')."""
    assert N.climate_row_for_county(float("nan")) == N.MEMPHIS_CLIMATE
    assert N.climate_row_for_county(47157.0)["hdd_annual"] == 3082      # float Shelby
    assert N.climate_row_for_county(6037.0)["climate_zone"] == "3B"     # float LA


def _run_all():
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} tests passed.")


if __name__ == "__main__":
    _run_all()
