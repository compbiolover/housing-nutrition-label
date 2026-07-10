"""Location-based wildfire hazard (FEMA National Risk Index, keyless + offline).

Returns the **wildfire expected-annual-loss (EAL) rate** for a US tract or county
— the dimensionless fraction of building value lost to wildfire per year — plus
FEMA's qualitative risk rating. The Disaster Resilience model uses this as the
"fire" hazard alongside flood, tornado, and seismic, so a home in a fire-prone
county (e.g. Los Angeles) carries real wildfire EAL while a low-risk one (e.g.
Memphis) carries almost none — unlike the old flat national-average fire constant.

Data
----
Values come from the FEMA **National Risk Index** (NRI), bundled offline by
``scripts/build_nri_wildfire.py`` as ``nri_wildfire.csv`` (county) and
``nri_wildfire_tracts.csv.gz`` (tract, sampled at full census-tract resolution).
NRI defines EAL as ``Exposure × AnnualizedFrequency × HistoricLossRatio``; the
EAL **rate** is therefore ``WFIR_AFREQ × WFIR_HLRB`` (== ``WFIR_EALB / WFIR_EXPB``
where building exposure is non-zero), in the same units as the other hazard
rates in ``score/resilience.py``.

Resolution
----------
Resolution-aware, mirroring ``data/climate_projections.py``:
``wildfire_for_tract`` resolves a tract → its parent county → the national
average, and ``wildfire_for_county`` resolves a county → the national average.
Every result carries a ``geo_level`` (``"tract"`` / ``"county"`` / ``"us"``) so
callers can label the geography that actually answered, and ``resolved`` is False
on the national fallback.

Caveats
-------
NRI is a **present-day baseline**, not a forward climate projection (the ClimRR
Fire Weather Index leg in Climate Projections covers projected fire weather).
It reflects **wildfire** specifically; structural/electrical fire is modeled
separately by the CLI simulator. Tract-level is the finest resolution — a
representative sub-county value, not parcel precision.
"""

from __future__ import annotations

import pathlib
from functools import lru_cache

DATA_VINTAGE = "FEMA National Risk Index (wildfire, present-day baseline)"
US_AVG_LABEL = f"US average ({DATA_VINTAGE})"

_DIR = pathlib.Path(__file__).resolve().parent
_CSV = _DIR / "nri_wildfire.csv"                       # county crosswalk
_TRACT_CSV = _DIR / "nri_wildfire_tracts.csv"          # plain CSV accepted if present
_TRACT_CSV_GZ = _DIR / "nri_wildfire_tracts.csv.gz"    # bundled (gzipped) tract crosswalk


from housing_label.data._util import num as _num  # shared CSV-cell float coercion


def _load_rows(path: pathlib.Path, width: int):
    """geoid (zero-padded to ``width``) → NRI wildfire row, as a compact columnar
    store (memory-efficient drop-in for the old ``{geoid: raw-row}`` dict)."""
    from housing_label.data._tractstore import load_tract_store
    return load_tract_store(path, width)


@lru_cache(maxsize=1)
def _table() -> dict[str, dict]:
    """county FIPS (5-digit) → raw NRI wildfire row."""
    return _load_rows(_CSV, 5) if _CSV.exists() else {}


@lru_cache(maxsize=1)
def _tract_table() -> dict[str, dict]:
    """tract GEOID (11-digit) → raw NRI wildfire row (empty if no tract crosswalk)."""
    path = _TRACT_CSV_GZ if _TRACT_CSV_GZ.exists() else _TRACT_CSV
    return _load_rows(path, 11) if path.exists() else {}


@lru_cache(maxsize=1)
def _national_average() -> float | None:
    """Population-blind national mean wildfire EAL rate (the unmapped fallback)."""
    rates = [r for r in (_num(row.get("wfir_eal_rate")) for row in _table().values())
             if r is not None]
    return round(sum(rates) / len(rates), 9) if rates else None


def _us_result() -> dict:
    """National-average fallback (used when no county/tract row resolves)."""
    return {
        "label": US_AVG_LABEL,
        "eal_rate": _national_average() or 0.0,
        "risk_rating": None,
        "resolved": False,
        "geo_level": "us",
    }


def _resolved_result(row: dict, geo_level: str, geoid: str) -> dict | None:
    """Build a resolved wildfire result from a raw NRI row, or None if it has no rate."""
    rate = _num(row.get("wfir_eal_rate"))
    if rate is None:
        return None
    name = (row.get("county_name") or "").strip()
    state = (row.get("state") or "").strip()
    place = f"{name}, {state}".strip(", ") or geoid
    if geo_level == "tract":
        place = f"Census Tract {geoid} ({place})"
    return {
        "label": f"{place} ({DATA_VINTAGE})",
        "eal_rate": rate,
        "risk_rating": (row.get("wfir_risk_rating") or "").strip() or None,
        "resolved": True,
        "geo_level": geo_level,
    }


def wildfire_for_county(county_fips: str | None) -> dict:
    """Return the wildfire hazard for a 5-digit county FIPS.

    Always returns a dict (never None): a mapped county carries its EAL rate +
    risk rating (``geo_level="county"``); a missing one falls back to the
    national average (``resolved=False``, ``geo_level="us"``).

    Keys: ``label``, ``eal_rate`` (fraction/yr), ``risk_rating``, ``resolved``,
    ``geo_level``.
    """
    fips = str(county_fips).strip().zfill(5) if county_fips else None
    row = _table().get(fips) if fips else None
    result = _resolved_result(row, "county", fips) if row is not None else None
    return result or _us_result()


def wildfire_for_tract(tract_geoid: str | None) -> dict:
    """Return the wildfire hazard for an 11-digit tract GEOID.

    Resolution-aware: a tract in the crosswalk resolves at ``geo_level="tract"``;
    otherwise it falls back to its parent county (first 5 digits), then the
    national average. Same dict shape as ``wildfire_for_county``.
    """
    geoid = str(tract_geoid).strip().zfill(11) if tract_geoid else None
    if geoid:
        row = _tract_table().get(geoid)
        if row is not None:
            result = _resolved_result(row, "tract", geoid)
            if result is not None:
                return result
        return wildfire_for_county(geoid[:5])
    return wildfire_for_county(None)
