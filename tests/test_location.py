#!/usr/bin/env python3
"""Offline tests for national location generalization (no network, no pytest).

Run directly:  python tests/test_location.py
"""

import pandas as pd

from housing_label.simulate.location import resolve_location, Location
from housing_label.data.climate import climate_zone_for_county
from housing_label.data.egrid import egrid_for_county, US_AVG_FACTOR_KG_PER_KWH, US_AVG_LABEL
from housing_label.enrich.energy import climate_zone_factor, model_parcel_energy


def test_climate_zone_lookup():
    assert climate_zone_for_county("47157") == "3A"     # Shelby County, TN
    assert climate_zone_for_county("06037") == "3B"     # Los Angeles County, CA
    assert climate_zone_for_county("17031") == "5A"     # Cook County, IL
    assert climate_zone_for_county("99999") is None     # unknown
    assert climate_zone_for_county(None) is None


def test_egrid_subregion_lookup():
    # Shelby County, TN → SRTV (the pilot's TVA subregion); ≈0.426 kgCO2e/kWh
    # (eGRID2022 SRTV CO2e total-output 938.6 lb/MWh).
    sub, factor = egrid_for_county("47157")
    assert "SRTV" in sub
    assert abs(factor - 0.426) < 0.005
    # Los Angeles County, CA → CAMX, a much cleaner grid than SRTV.
    ca_sub, ca_factor = egrid_for_county("06037")
    assert "CAMX" in ca_sub
    assert ca_factor < factor
    # Cook County, IL (Chicago/ComEd) → RFC West.
    il_sub, _ = egrid_for_county("17031")
    assert "RFCW" in il_sub


def test_egrid_crosswalk_integrity():
    """The bundled county→subregion crosswalk is complete and every subregion it
    references has a factor (guards a regenerated egrid_subregions.csv)."""
    from housing_label.data import egrid as e
    xwalk = e._crosswalk()
    assert len(xwalk) > 3000                       # ~3,200 US counties + territories
    assert all(len(fips) == 5 and fips.isdigit() for fips in xwalk)
    assert set(xwalk.values()) <= set(e._SUBREGION_LB_PER_MWH)   # all map to known subregions
    # Every referenced subregion resolves to a positive kgCO2e/kWh factor.
    for acro in set(xwalk.values()):
        assert e._factor_kg_per_kwh(acro) > 0


def test_egrid_fallback_to_us_average():
    for missing in ("99999", None):
        sub, factor = egrid_for_county(missing)
        assert factor == US_AVG_FACTOR_KG_PER_KWH
        assert sub == US_AVG_LABEL
        assert "average" in sub.lower()


def test_climate_zone_factor_ordering():
    assert climate_zone_factor("4A") == 1.0             # baseline
    assert climate_zone_factor(None) == 1.0             # missing → no scaling
    assert climate_zone_factor("1A") < 1.0              # hot → less site energy
    assert climate_zone_factor("7") > climate_zone_factor("5A") > 1.0   # colder → more


def test_energy_scales_with_climate_zone():
    row = pd.Series({"YRBLT": 2000, "SFLA": 2000})
    hot = model_parcel_energy(row, "1A")["eui_kbtu_sqft_yr"]
    base = model_parcel_energy(row, "4A")["eui_kbtu_sqft_yr"]
    cold = model_parcel_energy(row, "7")["eui_kbtu_sqft_yr"]
    assert hot < base < cold


def test_location_dataclass_helpers():
    loc = Location(lat=34.05, lon=-118.25, county_fips="06037",
                   county_name="Los Angeles County", place_label="Los Angeles city")
    assert loc.county3 == "037"
    assert loc.label == "Los Angeles city"
    bare = Location(lat=1.0, lon=2.0)
    assert "1.0" in bare.label and "2.0" in bare.label   # falls back to coords


def test_resolve_location_offline():
    """Without network, lat/lon is preserved and geographies stay None (noted)."""
    loc = resolve_location(lat=35.13, lon=-89.99, allow_network=False)
    assert loc.lat == 35.13 and loc.lon == -89.99
    assert loc.county_fips is None and loc.tract is None
    assert "geocoder" in loc.notes


def test_get_pga_applies_ratio():
    """get_pga returns (2%/50yr, 10%/50yr, source) with the documented ratio."""
    import housing_label.enrich.seismic_lookup as sl
    sl._usgs_pga.cache_clear()
    orig = sl._usgs_pga
    sl._usgs_pga = lambda lat, lon: 0.80          # stub the live lookup
    try:
        pga2, pga10, source = sl.get_pga(34.0, -118.0)
        assert pga2 == 0.8
        assert abs(pga10 - 0.8 * sl.PGA_10_2_RATIO) < 1e-9
        assert "USGS" in source
    finally:
        sl._usgs_pga = orig
        sl._usgs_pga.cache_clear()


def test_get_pga_offline_no_grid_is_none():
    """With network off and no bundled grid, get_pga returns None (caller then
    falls back), never a fabricated value."""
    import housing_label.enrich.seismic_lookup as sl
    if sl._GRID_CSV.exists():
        return  # a bundled grid is present; offline would interpolate, skip
    assert sl.get_pga(34.0, -118.0, allow_network=False) is None


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} tests passed.")


if __name__ == "__main__":
    _run_all()
