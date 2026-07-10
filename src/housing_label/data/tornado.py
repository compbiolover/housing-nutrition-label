"""Location-based tornado hazard (FEMA National Risk Index, keyless + offline).

Returns the **tornado expected-annual-loss (EAL) rate** for a US tract or county —
the dimensionless fraction of building value lost to tornadoes per year — plus
FEMA's qualitative risk rating. The Disaster Resilience model uses this as the
"tornado" hazard alongside flood, wildfire, and seismic.

This replaces the old NOAA SPC model, which counted historical touchdowns within
25 miles and applied a single **TN/Mid-South EF-magnitude distribution (Ashley
2007) nationally** — so a Great Plains home was scored with Mid-South tornado
intensities. NRI's EAL rate instead reflects the **local** frequency *and* the
**local** historic building-loss ratio, so "tornado alley" (e.g. Oklahoma) carries
a much higher EAL than a low-risk area (e.g. coastal California) — ~30× in the raw
data — where the old model could not tell them apart.

Data
----
Values come from the FEMA **National Risk Index** (NRI), bundled offline by
``scripts/build_nri_tornado.py`` as ``nri_tornado.csv`` (county) and
``nri_tornado_tracts.csv.gz`` (tract). NRI defines EAL as
``Exposure × AnnualizedFrequency × HistoricLossRatio``; the EAL **rate** is
therefore ``TRND_AFREQ × TRND_HLRB`` (== ``TRND_EALB / TRND_EXPB`` where building
exposure is non-zero), in the same units as the other hazard rates in
``score/resilience.py``.

Resolution
----------
Resolution-aware, mirroring ``data/wildfire.py``: ``tornado_for_tract`` resolves a
tract → its parent county → the national average, and ``tornado_for_county``
resolves a county → the national average. Every result carries a ``geo_level``
(``"tract"`` / ``"county"`` / ``"us"``) and ``resolved`` is False on the national
fallback. Always returns a dict, never None.

Caveats
-------
NRI is a **present-day baseline**, not a forward climate projection. Tract-level is
the finest resolution — a representative sub-county value, not parcel precision.
"""

from __future__ import annotations

import pathlib
from functools import lru_cache

from housing_label.data._util import num as _num  # shared CSV-cell float coercion

DATA_VINTAGE = "FEMA National Risk Index (tornado, present-day baseline)"
US_AVG_LABEL = f"US average ({DATA_VINTAGE})"

_DIR = pathlib.Path(__file__).resolve().parent
_CSV = _DIR / "nri_tornado.csv"                       # county crosswalk
_TRACT_CSV = _DIR / "nri_tornado_tracts.csv"          # plain CSV accepted if present
_TRACT_CSV_GZ = _DIR / "nri_tornado_tracts.csv.gz"    # bundled (gzipped) tract crosswalk


def _load_rows(path: pathlib.Path, width: int):
    """geoid (zero-padded to ``width``) → NRI tornado row, as a compact columnar
    store (memory-efficient drop-in for the old ``{geoid: raw-row}`` dict)."""
    from housing_label.data._tractstore import load_tract_store
    return load_tract_store(path, width)


@lru_cache(maxsize=1)
def _table() -> dict[str, dict]:
    """county FIPS (5-digit) → raw NRI tornado row."""
    return _load_rows(_CSV, 5) if _CSV.exists() else {}


@lru_cache(maxsize=1)
def _tract_table() -> dict[str, dict]:
    """tract GEOID (11-digit) → raw NRI tornado row (empty if no tract crosswalk)."""
    path = _TRACT_CSV_GZ if _TRACT_CSV_GZ.exists() else _TRACT_CSV
    return _load_rows(path, 11) if path.exists() else {}


@lru_cache(maxsize=1)
def _national_average() -> float | None:
    """Population-blind national mean tornado EAL rate (the unmapped fallback)."""
    rates = [r for r in (_num(row.get("trnd_eal_rate")) for row in _table().values())
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
    """Build a resolved tornado result from a raw NRI row, or None if it has no rate."""
    rate = _num(row.get("trnd_eal_rate"))
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
        "risk_rating": (row.get("trnd_risk_rating") or "").strip() or None,
        "resolved": True,
        "geo_level": geo_level,
    }


def tornado_for_county(county_fips: str | None) -> dict:
    """Return the tornado hazard for a 5-digit county FIPS.

    Always returns a dict (never None): a mapped county carries its EAL rate + risk
    rating (``geo_level="county"``); a missing one falls back to the national average
    (``resolved=False``, ``geo_level="us"``).

    Keys: ``label``, ``eal_rate`` (fraction/yr), ``risk_rating``, ``resolved``,
    ``geo_level``.
    """
    fips = str(county_fips).strip().zfill(5) if county_fips else None
    row = _table().get(fips) if fips else None
    result = _resolved_result(row, "county", fips) if row is not None else None
    return result or _us_result()


def tornado_for_tract(tract_geoid: str | None) -> dict:
    """Return the tornado hazard for an 11-digit tract GEOID.

    Resolution-aware: a tract in the crosswalk resolves at ``geo_level="tract"``;
    otherwise it falls back to its parent county (first 5 digits), then the national
    average. Same dict shape as ``tornado_for_county``.
    """
    geoid = str(tract_geoid).strip().zfill(11) if tract_geoid else None
    if geoid:
        row = _tract_table().get(geoid)
        if row is not None:
            result = _resolved_result(row, "tract", geoid)
            if result is not None:
                return result
        return tornado_for_county(geoid[:5])
    return tornado_for_county(None)
