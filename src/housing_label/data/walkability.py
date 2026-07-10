"""Location-based Walkability score (EPA National Walkability Index — offline).

Returns a tract's (or county's) **walkability score** (0-100, higher = more
walkable) from the EPA National Walkability Index (NWI). This replaces the Walk
Score API, which is both quota-capped (~5,000/day) and — critically — whose Terms
of Use PROHIBIT caching/storing returned scores, so it cannot back a stored,
national property-scoring product. The EPA NWI is public-domain, covers every US
census block group, and is freely storable and redistributable.

Because walkability is a property of *location, not parcel*, the score is looked
up by geography (no per-parcel API calls).

Data
----
Bundled offline by ``scripts/build_walkability.py`` from the EPA NWI feature
service (Smart Location Database v3, 2021 vintage). The NWI 1-20 index
(``NatWalkInd`` — intersection density + transit proximity + land-use mix) is
scaled to 0-100 and aggregated from block groups to 2020 census tracts and
counties, household-weighted. Files: ``walkability_tracts.csv.gz`` (tract) and
``walkability_county.csv`` (county + a national row).

Resolution
----------
``walkability_for_tract`` resolves a tract -> its parent county -> the national
average; ``walkability_for_county`` resolves a county -> the national average.
Every result carries a ``geo_level`` (``"tract"`` / ``"county"`` / ``"us"``);
``resolved`` is False on the national fallback. Always returns a dict, never None.

Caveats
-------
NWI is block-group native (aggregated here to tract), 2021 vintage, and
transport-modeling oriented (weighted toward transit proximity and intersection
density) rather than amenity/destination access like Walk Score — so it correlates
with, but is not identical to, Walk Score. It is EPA's official national index; a
finer in-house OpenStreetMap amenity-access score is a documented future upgrade.
"""

from __future__ import annotations

import pathlib
from functools import lru_cache

from housing_label.data._util import num as _num

DATA_VINTAGE = "EPA National Walkability Index (Smart Location Database v3, 2021)"
US_AVG_LABEL = f"US national average ({DATA_VINTAGE})"

_DIR = pathlib.Path(__file__).resolve().parent
_CSV = _DIR / "walkability_county.csv"
_TRACT_CSV = _DIR / "walkability_tracts.csv"
_TRACT_CSV_GZ = _DIR / "walkability_tracts.csv.gz"
_NATIONAL_GEOID = "00000"


def _load_rows(path: pathlib.Path, width: int):
    """geoid (zero-padded to ``width``) → walkability row, as a compact columnar
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


def _us_result() -> dict:
    row = _county_table().get(_NATIONAL_GEOID, {})
    return {
        "label": US_AVG_LABEL,
        "walkability_score": _num(row.get("walkability_score")),
        "nat_walk_ind": _num(row.get("nat_walk_ind")),
        "resolved": False,
        "geo_level": "us",
    }


def _resolved(row: dict, geo_level: str, geoid: str) -> dict | None:
    score = _num(row.get("walkability_score"))
    if score is None:
        return None
    place = f"Census Tract {geoid}" if geo_level == "tract" else f"County {geoid}"
    return {
        "label": f"{place} ({DATA_VINTAGE})",
        "walkability_score": score,
        "nat_walk_ind": _num(row.get("nat_walk_ind")),
        "resolved": True,
        "geo_level": geo_level,
    }


def walkability_for_county(county_fips: str | None) -> dict:
    """Walkability for a 5-digit county FIPS (county -> national fallback)."""
    fips = str(county_fips).strip().zfill(5) if county_fips else None
    row = _county_table().get(fips) if fips else None
    result = _resolved(row, "county", fips) if row is not None else None
    return result or _us_result()


def walkability_for_tract(tract_geoid: str | None) -> dict:
    """Walkability for an 11-digit tract GEOID (tract -> county -> national)."""
    geoid = str(tract_geoid).strip().zfill(11) if tract_geoid else None
    if geoid:
        row = _tract_table().get(geoid)
        if row is not None:
            result = _resolved(row, "tract", geoid)
            if result is not None:
                return result
        return walkability_for_county(geoid[:5])
    return walkability_for_county(None)
