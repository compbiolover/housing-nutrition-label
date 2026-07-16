"""Marginal grid CO2e emission factor by location (NREL Cambium 2023 LRMER,
keyless + offline).

Returns the **long-run marginal** grid CO2e emission rate for a county — the
emissions of the generation that actually ramps up/down in response to a
sustained change in load. This is the correct rate for valuing *avoided* kWh
(rooftop solar + envelope/passive efficiency): a kWh a home no longer draws
turns off marginal generation, not the average mix. The environmental model
differences it against the eGRID **average** (data/egrid.py) — consumed kWh at
the average, avoided kWh credited at the marginal — so the two must be on the
same combustion/stack-emissions basis (both exclude precombustion), which is why
the *combustion* CO2e Cambium metric is used.

Data
----
  • Marginal factors + county crosswalk — cambium_lrmer.csv, built by
    scripts/build_cambium_crosswalk.py from NREL's Cambium 2023 LRMER
    (GEA-regions) workbook: Mid-case scenario, levelized over 20 years from a
    2025 start at a 3% real discount rate, 100-year AR6 GWP, end-use basis.
    Long-Run Marginal Emission Rate, Combustion CO2e, kg/MWh → kg/kWh.

Scope: Cambium's 18 GEA regions cover CONUS only. Alaska, Hawai'i, and Puerto
Rico counties are not in the crosswalk; ``cambium_lrmer_for_county`` returns
None for them (and any unresolved county), so the caller falls back to the
eGRID average — i.e. no marginal adjustment there.

Cambium is reissued ~annually and the grid is decarbonizing — treat these as
dated constants and refresh (re-run the build script on the new workbook) on
each Cambium release. The function signature is stable, so callers never change.

Source (CC BY 4.0): Gagnon, Pieter, et al. "Cambium 2023 Data." NREL, 2024.
https://data.nrel.gov/submissions/230
"""

from __future__ import annotations

import csv
import pathlib
from functools import lru_cache

CAMBIUM_VINTAGE = "NREL Cambium 2023 LRMER (Mid-case, 20-yr levelized)"

_CSV = pathlib.Path(__file__).resolve().parent / "cambium_lrmer.csv"

# Cambium GEA region code → readable name (the 18 CONUS regions).
_GEA_NAMES: dict[str, str] = {
    "CAISO":              "California ISO",
    "ERCOT":              "ERCOT (Texas)",
    "FRCC":               "Florida (FRCC)",
    "ISONE":              "ISO New England",
    "MISO_Central":       "MISO Central",
    "MISO_North":         "MISO North",
    "MISO_South":         "MISO South",
    "NorthernGrid_East":  "NorthernGrid East",
    "NorthernGrid_South": "NorthernGrid South",
    "NorthernGrid_West":  "NorthernGrid West",
    "NYISO":              "New York ISO",
    "PJM_East":           "PJM East",
    "PJM_West":           "PJM West",
    "SERTP":              "Southeast (SERTP)",
    "SPP_North":          "SPP North",
    "SPP_South":          "SPP South",
    "WestConnect_North":  "WestConnect North",
    "WestConnect_South":  "WestConnect South",
}


def _label(gea: str) -> str:
    name = _GEA_NAMES.get(gea, gea)
    return f"{gea} — {name} ({CAMBIUM_VINTAGE})"


@lru_cache(maxsize=1)
def _table() -> dict[str, tuple[str, float]]:
    """county FIPS (5-digit) → (GEA region, marginal kgCO2e/kWh)."""
    table: dict[str, tuple[str, float]] = {}
    if not _CSV.exists():
        return table
    with _CSV.open() as f:
        for row in csv.DictReader(f):
            fips = str(row["county_fips"]).strip().zfill(5)
            gea = str(row["gea_region"]).strip()
            try:
                factor = float(row["lrmer_kgco2e_kwh"])
            except (TypeError, ValueError):
                continue
            if fips and gea:
                table[fips] = (gea, factor)
    return table


def cambium_lrmer_for_county(county_fips: str | None) -> tuple[str, float] | None:
    """Return (region_label, marginal kgCO2e/kWh) for a 5-digit county FIPS.

    Looks the county up in the bundled Cambium crosswalk. Returns None for a
    missing/blank FIPS or any county outside the CONUS GEA regions (Alaska,
    Hawai'i, Puerto Rico, or otherwise unmapped) — the caller then falls back to
    the eGRID average, applying no marginal adjustment.
    """
    if county_fips:
        row = _table().get(str(county_fips).strip().zfill(5))
        if row is not None:
            gea, factor = row
            return (_label(gea), factor)
    return None
