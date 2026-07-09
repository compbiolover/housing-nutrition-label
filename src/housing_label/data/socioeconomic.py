"""Location-based Socioeconomic score (Census ACS, national — keyless + offline).

Returns a tract's (or county's) **Socioeconomic index**: 0-100 where 100 = least
economic stress. Like Health, the score is a **national** percentile, not a
within-county rank, so it is comparable across locations — the fix for the old
within-county ``rank(pct=True)`` in ``enrich/socioeconomic.py`` that re-baselined
every county to a median of ~50. It also removes the runtime ``CENSUS_API_KEY``
dependency: the value is a bundled offline lookup, not a live ACS API call.

Data
----
Bundled offline by ``scripts/build_socio_ref.py`` from the keyless ACS 5-year
**table-based Summary File** (2023 vintage): poverty rate (B17001), median
household income (B19013), and housing cost burden (B25106). Each metric is a
household-weighted national percentile (poverty & burden inverted, income direct);
``socioeconomic_index`` is their mean. Files: ``socio_tracts.csv.gz`` (tract) and
``socio_county.csv`` (county + a national row centered at ~50 by construction).

Resolution
----------
``socio_for_tract`` resolves a tract -> its parent county -> the national average;
``socio_for_county`` resolves a county -> the national average. Every result
carries a ``geo_level`` (``"tract"`` / ``"county"`` / ``"us"``); ``resolved`` is
False on the national fallback. Always returns a dict, never None.

Caveats
-------
ACS 5-year tract estimates carry margins of error (largest in small tracts); a
tract missing too many metrics is left unscored. The reference distribution is
frozen at the bundled vintage (rebuild to refresh).
"""

from __future__ import annotations

import csv
import gzip
import pathlib
from functools import lru_cache

from housing_label.data._util import num as _num

DATA_VINTAGE = "Census ACS 5-year 2023 (national percentile)"
US_AVG_LABEL = f"US national average ({DATA_VINTAGE})"

_DIR = pathlib.Path(__file__).resolve().parent
_CSV = _DIR / "socio_county.csv"
_TRACT_CSV = _DIR / "socio_tracts.csv"
_TRACT_CSV_GZ = _DIR / "socio_tracts.csv.gz"
_NATIONAL_GEOID = "00000"

METRIC_COLS = ["poverty_rate_pct", "median_household_income", "housing_cost_burden_pct"]


def _load_rows(path: pathlib.Path, width: int) -> dict[str, dict]:
    table: dict[str, dict] = {}
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", newline="") as f:
        for row in csv.DictReader(f):
            raw = str(row.get("geoid", "")).strip()
            if not raw:
                continue
            table[raw.zfill(width)] = row
    return table


@lru_cache(maxsize=1)
def _tract_table() -> dict[str, dict]:
    path = _TRACT_CSV_GZ if _TRACT_CSV_GZ.exists() else _TRACT_CSV
    return _load_rows(path, 11) if path.exists() else {}


@lru_cache(maxsize=1)
def _county_table() -> dict[str, dict]:
    return _load_rows(_CSV, 5) if _CSV.exists() else {}


def _metrics(row: dict) -> dict:
    return {c: _num(row.get(c)) for c in METRIC_COLS}


def _us_result() -> dict:
    row = _county_table().get(_NATIONAL_GEOID, {})
    return {
        "label": US_AVG_LABEL,
        "socioeconomic_index": _num(row.get("socioeconomic_index")),
        "metrics": _metrics(row),
        "resolved": False,
        "geo_level": "us",
    }


def _resolved(row: dict, geo_level: str, geoid: str) -> dict | None:
    si = _num(row.get("socioeconomic_index"))
    if si is None:
        return None
    place = f"Census Tract {geoid}" if geo_level == "tract" else f"County {geoid}"
    return {
        "label": f"{place} ({DATA_VINTAGE})",
        "socioeconomic_index": si,
        "metrics": _metrics(row),
        "resolved": True,
        "geo_level": geo_level,
    }


def socio_for_county(county_fips: str | None) -> dict:
    """Socioeconomic index for a 5-digit county FIPS (county -> national fallback)."""
    fips = str(county_fips).strip().zfill(5) if county_fips else None
    row = _county_table().get(fips) if fips else None
    result = _resolved(row, "county", fips) if row is not None else None
    return result or _us_result()


def socio_for_tract(tract_geoid: str | None) -> dict:
    """Socioeconomic index for an 11-digit tract GEOID (tract -> county -> national)."""
    geoid = str(tract_geoid).strip().zfill(11) if tract_geoid else None
    if geoid:
        row = _tract_table().get(geoid)
        if row is not None:
            result = _resolved(row, "tract", geoid)
            if result is not None:
                return result
        return socio_for_county(geoid[:5])
    return socio_for_county(None)
