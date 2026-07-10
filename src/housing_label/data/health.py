"""Location-based Health Impact score (CDC PLACES, national — keyless + offline).

Returns a tract's (or county's) **Health Impact index**: a 0-100 score where 100
= lowest chronic-disease burden. Crucially the score is a **national** percentile,
not a within-county rank: each tract is scored against the full national
distribution of US census tracts (population-weighted), so a "70" means the same
thing in Memphis and in Denver. This is the fix for the old within-county
``rank(pct=True)`` in ``enrich/health.py`` that re-baselined every county to a
median of ~50 and made health scores incomparable across locations.

Data
----
Bundled offline by ``scripts/build_health_ref.py`` as ``health_tracts.csv.gz``
(tract) and ``health_county.csv`` (county + a national row). Source: CDC PLACES
census-tract crude prevalence (2023 BRFSS) for 7 measures — physical inactivity,
obesity, diabetes, frequent mental distress, current asthma, high blood pressure,
and coronary heart disease. Each measure is turned into a population-weighted
national percentile (100 = lowest prevalence); ``health_index`` is their mean.

Resolution
----------
Resolution-aware, mirroring ``data/wildfire.py`` / ``data/climate_projections.py``:
``health_for_tract`` resolves a tract -> its parent county -> the national
average; ``health_for_county`` resolves a county -> the national average. Every
result carries a ``geo_level`` (``"tract"`` / ``"county"`` / ``"us"``) and
``resolved`` is False on the national fallback. Always returns a dict, never None.

Caveats
-------
CDC PLACES tract values are **model-based** small-area estimates (MRP), not direct
counts, and reflect adult (18+) crude prevalence. Tract-level is the finest
resolution — a representative neighborhood value, not a per-home measurement.
The reference distribution is frozen at the bundled vintage (rebuild to refresh).
"""

from __future__ import annotations

import pathlib
from functools import lru_cache

from housing_label.data._util import num as _num

DATA_VINTAGE = "CDC PLACES 2023 BRFSS (crude prevalence, adults 18+; national percentile)"
US_AVG_LABEL = f"US national average ({DATA_VINTAGE})"

_DIR = pathlib.Path(__file__).resolve().parent
_CSV = _DIR / "health_county.csv"                 # county crosswalk (+ national row)
_TRACT_CSV = _DIR / "health_tracts.csv"           # plain CSV accepted if present
_TRACT_CSV_GZ = _DIR / "health_tracts.csv.gz"     # bundled (gzipped) tract crosswalk
_NATIONAL_GEOID = "00000"

MEASURE_COLS = [
    "physical_inactivity_pct", "obesity_pct", "diabetes_pct", "mental_distress_pct",
    "asthma_pct", "high_bp_pct", "chd_pct",
]


def _load_rows(path: pathlib.Path, width: int):
    """geoid (zero-padded to ``width``) -> crosswalk row, as a compact columnar
    store (memory-efficient drop-in for the old ``{geoid: raw-row}`` dict)."""
    from housing_label.data._tractstore import load_tract_store
    return load_tract_store(path, width)


@lru_cache(maxsize=1)
def _tract_table() -> dict[str, dict]:
    path = _TRACT_CSV_GZ if _TRACT_CSV_GZ.exists() else _TRACT_CSV
    return _load_rows(path, 11) if path.exists() else {}


@lru_cache(maxsize=1)
def _county_table() -> dict[str, dict]:
    return _load_rows(_CSV, 5) if _CSV.exists() else {}


def _measures(row: dict) -> dict:
    return {c: _num(row.get(c)) for c in MEASURE_COLS}


def _us_result() -> dict:
    row = _county_table().get(_NATIONAL_GEOID, {})
    return {
        "label": US_AVG_LABEL,
        "health_index": _num(row.get("health_index")),
        "measures": _measures(row),
        "resolved": False,
        "geo_level": "us",
    }


def _resolved(row: dict, geo_level: str, geoid: str) -> dict | None:
    hi = _num(row.get("health_index"))
    if hi is None:
        return None
    place = f"Census Tract {geoid}" if geo_level == "tract" else f"County {geoid}"
    return {
        "label": f"{place} ({DATA_VINTAGE})",
        "health_index": hi,
        "measures": _measures(row),
        "resolved": True,
        "geo_level": geo_level,
    }


def health_for_county(county_fips: str | None) -> dict:
    """Health Impact index for a 5-digit county FIPS (county -> national fallback)."""
    fips = str(county_fips).strip().zfill(5) if county_fips else None
    row = _county_table().get(fips) if fips else None
    result = _resolved(row, "county", fips) if row is not None else None
    return result or _us_result()


def health_for_tract(tract_geoid: str | None) -> dict:
    """Health Impact index for an 11-digit tract GEOID (tract -> county -> national)."""
    geoid = str(tract_geoid).strip().zfill(11) if tract_geoid else None
    if geoid:
        row = _tract_table().get(geoid)
        if row is not None:
            result = _resolved(row, "tract", geoid)
            if result is not None:
                return result
        return health_for_county(geoid[:5])
    return health_for_county(None)
