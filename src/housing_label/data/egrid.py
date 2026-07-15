"""Grid CO2 emission factor by location (eGRID2023, keyless + offline).

Returns the EPA eGRID **subregion** total-output CO2-equivalent emission rate for
a county, so the environmental dimension's operational-carbon leg reflects the
real regional grid instead of a single national average. Where a county can't be
resolved to a subregion, the US-average factor is returned (label flags it).

Data
----
  • Subregion factors — EPA eGRID2023 Summary Tables (Revision 2, 12 Jun 2025),
    Table 1 "Subregion Output Emission Rates", the CO2e *total output* rate
    (lb/MWh), converted to kg/kWh.
    (Same vintage as the pilot pipeline's SRTV constant in enrich/environmental.py.)
    https://www.epa.gov/system/files/documents/2025-06/summary_tables_rev2.xlsx
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

EGRID_VINTAGE = "eGRID2023"
LB_PER_MWH_TO_KG_PER_KWH = 0.45359237 / 1000.0   # lb/MWh → kg/kWh

_CSV = pathlib.Path(__file__).resolve().parent / "egrid_subregions.csv"

# eGRID2023 subregion acronym → (full name, CO2e total-output rate in lb/MWh).
# Values transcribed verbatim from the eGRID2023 Summary Tables Rev 2 (Table 1,
# CO2e total-output column). Converted to kg/kWh on load.
_SUBREGION_LB_PER_MWH: dict[str, tuple[str, float]] = {
    "AKGD": ("ASCC Alaska Grid",           905.109),
    "AKMS": ("ASCC Miscellaneous",         522.4),
    "AZNM": ("WECC Southwest",             706.189),
    "CAMX": ("WECC California",            429.983),
    "ERCT": ("ERCOT All",                  736.629),
    "FRCC": ("FRCC All",                   784.785),
    "HIMS": ("HICC Miscellaneous",        1133.294),
    "HIOA": ("HICC Oahu",                 1498.947),
    "MROE": ("MRO East",                  1404.963),
    "MROW": ("MRO West",                   926.552),
    "NEWE": ("NPCC New England",           543.178),
    "NWPP": ("WECC Northwest",             635.267),
    "NYCW": ("NPCC NYC/Westchester",       865.744),
    "NYLI": ("NPCC Long Island",          1189.333),
    "NYUP": ("NPCC Upstate NY",            242.776),
    "PRMS": ("Puerto Rico Miscellaneous", 1548.53),
    "RFCE": ("RFC East",                   599.17),
    "RFCM": ("RFC Michigan",               975.978),
    "RFCW": ("RFC West",                   916.054),
    "RMPA": ("WECC Rockies",              1042.539),
    "SPNO": ("SPP North",                  867.74),
    "SPSO": ("SPP South",                  875.567),
    "SRMV": ("SERC Mississippi Valley",    741.741),
    "SRMW": ("SERC Midwest",              1248.582),
    "SRSO": ("SERC South",                 846.007),
    "SRTV": ("SERC Tennessee Valley",      903.306),
    "SRVC": ("SERC Virginia/Carolina",     596.326),
}

# EPA eGRID2023 US-average total-output CO2e rate (770.884 lb/MWh) — the fallback
# for counties with no subregion mapping.
US_AVG_FACTOR_KG_PER_KWH = round(770.884 * LB_PER_MWH_TO_KG_PER_KWH, 4)   # ≈ 0.3497
US_AVG_LABEL = f"US average ({EGRID_VINTAGE})"


# Convert each subregion's lb/MWh to kg/kWh once at import (the source table
# above stays verbatim for provenance); egrid_for_county is not itself cached, so
# this avoids a multiply+round on every lookup.
_SUBREGION_FACTOR_KG_PER_KWH: dict[str, float] = {
    acro: round(lb * LB_PER_MWH_TO_KG_PER_KWH, 4)
    for acro, (_name, lb) in _SUBREGION_LB_PER_MWH.items()
}


def _factor_kg_per_kwh(acronym: str) -> float | None:
    return _SUBREGION_FACTOR_KG_PER_KWH.get(acronym)


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


def egrid_for_county(county_fips: str | None) -> tuple[str, float]:
    """Return (subregion_label, kgCO2e/kWh) for a 5-digit county FIPS.

    Looks the county up in the bundled crosswalk and returns its eGRID2023
    subregion factor. Counties not in the crosswalk (or a missing/blank FIPS)
    fall back to the US-average factor, with the label flagging it as such — so
    a concrete (label, factor) pair is always returned, never None.
    """
    if county_fips:
        acro = _crosswalk().get(str(county_fips).strip().zfill(5))
        factor = _factor_kg_per_kwh(acro) if acro else None
        if factor is not None:
            return (_label(acro), factor)
    return (US_AVG_LABEL, US_AVG_FACTOR_KG_PER_KWH)
