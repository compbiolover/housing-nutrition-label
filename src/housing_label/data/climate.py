"""county FIPS → IECC climate zone lookup (bundled, offline).

Source: DOE / PNNL Building America "Climate Zones by County" table
(https://basc.pnnl.gov/guide-determining-climate-zone-county-data-files),
flattened to `climate_zones.csv` (county_fips, iecc_zone) where iecc_zone is the
IECC number plus moisture regime, e.g. "4A", "5B", "7".
"""

from __future__ import annotations

import csv
import pathlib
from functools import lru_cache

_CSV = pathlib.Path(__file__).resolve().parent / "climate_zones.csv"


@lru_cache(maxsize=1)
def _table() -> dict[str, str]:
    table: dict[str, str] = {}
    if not _CSV.exists():
        return table
    with _CSV.open() as f:
        for row in csv.DictReader(f):
            fips = str(row["county_fips"]).strip().zfill(5)
            zone = str(row["iecc_zone"]).strip()
            if fips and zone:
                table[fips] = zone
    return table


def climate_zone_for_county(county_fips: str | None) -> str | None:
    """Return the IECC climate zone (e.g. "4A") for a 5-digit county FIPS."""
    if not county_fips:
        return None
    return _table().get(str(county_fips).strip().zfill(5))
