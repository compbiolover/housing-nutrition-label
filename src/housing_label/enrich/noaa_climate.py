#!/usr/bin/env python3
"""NOAA climate-normals model library.

Provides the Memphis/Shelby climate normals and a per-county climate-row
resolver for the climate dimension. Importable functions only; no batch runner.

Data source
-----------
  NOAA 1991–2020 U.S. Climate Normals
  Station : Memphis International Airport  (USW00013893)
  Location: 35.0584° N, 89.9787° W  (Shelby County, TN)

  All 1,000 parcels are in the same IECC climate zone (4A, Mixed-Humid),
  so a single county-wide set of normals is applied to every parcel.
  These are published reference values and will not change between runs.

  Full CDO API: https://www.ncei.noaa.gov/cdo-web/api/v2/
  Free token  : https://www.ncdc.noaa.gov/cdo-web/token
  (API-based lookup is the upgrade path when this expands beyond Shelby County.)

Climate columns added
---------------------
  climate_zone            IECC energy-code zone (e.g. "4A")
  climate_zone_desc       Human-readable zone label
  hdd_annual              Heating Degree Days, base 65°F (annual normal)
  cdd_annual              Cooling Degree Days, base 65°F (annual normal)
  avg_jan_low_f           Average January daily low (°F)
  avg_jul_high_f          Average July daily high (°F)
  precip_annual_in        Normal annual precipitation (inches)
  extreme_heat_days       Days/yr with max temp > 95°F
  freeze_days             Days/yr with min temp < 32°F
  climate_station         NOAA station ID used as reference
  climate_normals_period  Normals period (e.g. "1991-2020")
"""

# ── NOAA 1991-2020 Climate Normals: Memphis International Airport ─────────────
#    Source: NOAA Climate Normals for the U.S. (1991–2020), NCEI station USW00013893
MEMPHIS_CLIMATE = {
    "climate_zone":           "4A",
    "climate_zone_desc":      "Mixed-Humid",
    "hdd_annual":             3082,    # Heating Degree Days (base 65°F)
    "cdd_annual":             2191,    # Cooling Degree Days (base 65°F)
    "avg_jan_low_f":          31.1,    # Average January daily low (°F)
    "avg_jul_high_f":         92.5,    # Average July daily high (°F)
    "precip_annual_in":       53.7,    # Normal annual precipitation (in)
    "extreme_heat_days":      45,      # Days/yr with max temp > 95°F
    "freeze_days":            50,      # Days/yr with min temp < 32°F
    "climate_station":        "USW00013893",
    "climate_normals_period": "1991-2020",
}

CLIMATE_COLS = list(MEMPHIS_CLIMATE.keys())


def climate_row_for_county(county_fips: str | None) -> dict:
    """Return the climate-normals column dict for a county.

    Shelby (or None) keeps the full Memphis normals unchanged. For any other
    county, the IECC ``climate_zone`` + ``climate_zone_desc`` come from the
    bundled DOE/PNNL crosswalk (the one field with a national bundle); the
    degree-day / temperature / precip normals have no bundled national source
    (the NOAA CDO API is the documented upgrade path), so they are left null
    rather than stamped with Memphis values that don't apply elsewhere.
    """
    from housing_label.enrich.region_context import (
        SHELBY_COUNTY_FIPS, climate_zone_for_county_fips, normalize_fips,
    )

    fips = normalize_fips(county_fips)
    if not fips or fips == SHELBY_COUNTY_FIPS:
        return dict(MEMPHIS_CLIMATE)

    zone, desc = climate_zone_for_county_fips(fips)
    row = {c: None for c in CLIMATE_COLS}
    row["climate_zone"] = zone
    row["climate_zone_desc"] = desc
    row["climate_station"] = "IECC crosswalk (per-location normals: NOAA CDO API)"
    return row
