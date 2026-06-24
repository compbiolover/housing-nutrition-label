"""Grid CO2 emission factor by location (eGRID2022, keyless + offline).

Returns the EPA eGRID **subregion** total-output CO2-equivalent emission rate for
a county, so the environmental dimension's operational-carbon leg reflects the
real regional grid instead of a single national average. Where a county can't be
resolved to a subregion, the US-average factor is returned (label flags it).

Data
----
  • Subregion factors — EPA eGRID2022 Summary Tables, Table 1 "Subregion Output
    Emission Rates", the CO2e *total output* rate (lb/MWh), converted to kg/kWh.
    (Same vintage as the pilot pipeline's SRTV constant in enrich/environmental.py.)
    https://www.epa.gov/system/files/documents/2024-01/egrid2022_summary_tables.pdf
  • County→subregion crosswalk — egrid_subregions.csv, built by
    scripts/build_egrid_crosswalk.py from EPA's Power Profiler ZIP→subregion
    mapping aggregated to counties via the Census 2020 ZCTA↔county file.

The grid is decarbonizing and eGRID is reissued ~annually — treat these as dated
constants and refresh (factor table + crosswalk) on each eGRID release. The
function signature is stable, so callers never change.
"""

from __future__ import annotations

import csv
import pathlib
from functools import lru_cache

EGRID_VINTAGE = "eGRID2022"
LB_PER_MWH_TO_KG_PER_KWH = 0.45359237 / 1000.0   # lb/MWh → kg/kWh

_CSV = pathlib.Path(__file__).resolve().parent / "egrid_subregions.csv"

# eGRID2022 subregion acronym → (full name, CO2e total-output rate in lb/MWh).
# Values transcribed verbatim from the eGRID2022 Summary Tables (Table 1, CO2e
# column). Converted to kg/kWh on load.
_SUBREGION_LB_PER_MWH: dict[str, tuple[str, float]] = {
    "AKGD": ("ASCC Alaska Grid",          1057.8),
    "AKMS": ("ASCC Miscellaneous",         497.6),
    "AZNM": ("WECC Southwest",             779.4),
    "CAMX": ("WECC California",            499.3),
    "ERCT": ("ERCOT All",                  774.3),
    "FRCC": ("FRCC All",                   816.9),
    "HIMS": ("HICC Miscellaneous",        1163.1),
    "HIOA": ("HICC Oahu",                 1586.9),
    "MROE": ("MRO East",                  1488.7),
    "MROW": ("MRO West",                   943.4),
    "NEWE": ("NPCC New England",           540.5),
    "NWPP": ("WECC Northwest",             605.9),
    "NYCW": ("NPCC NYC/Westchester",       886.6),
    "NYLI": ("NPCC Long Island",          1209.3),
    "NYUP": ("NPCC Upstate NY",            275.4),
    "PRMS": ("Puerto Rico Miscellaneous", 1599.9),
    "RFCE": ("RFC East",                   660.3),
    "RFCM": ("RFC Michigan",              1224.2),
    "RFCW": ("RFC West",                  1005.9),
    "RMPA": ("WECC Rockies",              1131.7),
    "SPNO": ("SPP North",                  959.4),
    "SPSO": ("SPP South",                  975.3),
    "SRMV": ("SERC Mississippi Valley",    803.7),
    "SRMW": ("SERC Midwest",              1380.2),
    "SRSO": ("SERC South",                 897.7),
    "SRTV": ("SERC Tennessee Valley",      938.6),
    "SRVC": ("SERC Virginia/Carolina",     625.9),
}

# EPA eGRID2022 US-average total-output CO2e rate (827.5 lb/MWh) — the fallback
# for counties with no subregion mapping.
US_AVG_FACTOR_KG_PER_KWH = round(827.5 * LB_PER_MWH_TO_KG_PER_KWH, 4)   # ≈ 0.3754
US_AVG_LABEL = f"US average ({EGRID_VINTAGE})"


def _factor_kg_per_kwh(acronym: str) -> float | None:
    entry = _SUBREGION_LB_PER_MWH.get(acronym)
    if entry is None:
        return None
    return round(entry[1] * LB_PER_MWH_TO_KG_PER_KWH, 4)


def _label(acronym: str) -> str:
    name = _SUBREGION_LB_PER_MWH.get(acronym, (acronym,))[0]
    return f"{acronym} — {name} ({EGRID_VINTAGE})"


@lru_cache(maxsize=1)
def _crosswalk() -> dict[str, str]:
    """county FIPS (5-digit) → eGRID subregion acronym."""
    table: dict[str, str] = {}
    if not _CSV.exists():
        return table
    with _CSV.open() as f:
        for row in csv.DictReader(f):
            fips = str(row["county_fips"]).strip().zfill(5)
            sub = str(row["egrid_subregion"]).strip()
            if fips and sub:
                table[fips] = sub
    return table


def egrid_for_county(county_fips: str | None) -> tuple[str | None, float | None]:
    """Return (subregion_label, kgCO2e/kWh) for a 5-digit county FIPS.

    Looks the county up in the bundled crosswalk and returns its eGRID2022
    subregion factor. Counties not in the crosswalk (or a missing/blank FIPS)
    fall back to the US-average factor, with the label flagging it as such.
    """
    if county_fips:
        acro = _crosswalk().get(str(county_fips).strip().zfill(5))
        factor = _factor_kg_per_kwh(acro) if acro else None
        if factor is not None:
            return (_label(acro), factor)
    return (US_AVG_LABEL, US_AVG_FACTOR_KG_PER_KWH)
