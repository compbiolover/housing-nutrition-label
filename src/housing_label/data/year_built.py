"""Year-built DISTRIBUTION for a place (ACS **B25034**/**B25035**), tract → county → national.

What this is for
----------------
No public national dataset knows when *this house* was built (see
``research/parcel-level-data-research.md``: the best commercial aggregate carries
year built for 67% of parcels, and no free national source carries it at all). What
is knowable, everywhere, is when the homes *around* it were built — and, crucially,
**how much they vary**.

That second half is the point of this module. The label previously took NSI's
``med_yr_blt`` — itself a census-tract median — and showed it as a bare number. But
across the 84k tracts bundled here the **median interquartile spread is 27 years**,
and 72.8% of tracts spread 20 years or more. A tract typical is a point estimate with
roughly ±14 years of slack, and the label cannot say how much to trust it without
carrying that spread alongside.

So this returns ``p25``/``median``/``p75``, not a scalar. The median remains the best
available stand-in when nobody has told us the real year; the quartiles are what let
the label say *how much of a stand-in it is*, and let a reader see whether confirming
the true year would move anything.

This is still an **area typical, not a measurement of the building** — the same thing
NSI's field was, from a dated and citable source, with its uncertainty attached. A
user entry, or an observed county-assessor record, always outranks it.

Bundled from ``scripts/build_year_built.py`` (keyless ACS Summary File). The shipped
``median`` is the Census's own published B25035; the quartiles are interpolated from
B25034's decade buckets by a rule the build validates against B25035 across ~87k
geographies (median disagreement 0.27 years). The ACS margin of error is read by that
build and spent there, dropping geographies whose unit count is too uncertain to
quantile at all, rather than shipped to a runtime that could not act on it.
"""

from __future__ import annotations

import csv
import pathlib
from functools import lru_cache

from housing_label.data._util import num as _num

_DIR = pathlib.Path(__file__).resolve().parent
_TRACT_CSV = _DIR / "year_built_tracts.csv"          # plain CSV accepted if present
_TRACT_CSV_GZ = _DIR / "year_built_tracts.csv.gz"    # bundled (gzipped) tract table
_COUNTY_CSV = _DIR / "year_built_county.csv"         # county + national fallback
_NATIONAL = "00000"

DATA_VINTAGE = "ACS 2020–2024 5-yr year structure built (B25034/B25035)"

# geo_level vocabulary matches the rest of the bundled loaders (data/home_value,
# data/socioeconomic, data/health): "tract" / "county" / "us".
_LABEL = {
    "tract": "neighborhood typical",
    "county": "county typical",
    "us": "US typical",
}


@lru_cache(maxsize=1)
def _tract_table():
    """tract GEOID (11-digit) → row, via the shared columnar TractStore.

    The ~84k-row table costs 60–190 MB as row dicts and a few MB as typed columns,
    which is the difference between fitting and not fitting on a 512 MB instance.
    """
    path = _TRACT_CSV_GZ if _TRACT_CSV_GZ.exists() else _TRACT_CSV
    if not path.exists():
        return {}
    from housing_label.data._tractstore import load_tract_store
    return load_tract_store(path, 11)


@lru_cache(maxsize=1)
def _county_table() -> dict[str, dict]:
    """county FIPS (5-digit) → row, including the ``00000`` national row.

    Small enough (~3.2k rows) that a plain dict costs nothing.
    """
    table: dict[str, dict] = {}
    if not _COUNTY_CSV.exists():
        return table
    with _COUNTY_CSV.open(newline="") as f:
        for row in csv.DictReader(f):
            geoid = (row.get("geoid") or "").strip()
            if geoid:
                table[geoid.zfill(5)] = row
    return table


def _reading(row, geo_level: str) -> dict | None:
    """Shape one table row into the module's return contract, or None if unusable."""
    p25, median, p75 = (_num(row.get("p25")), _num(row.get("median")),
                        _num(row.get("p75")))
    if median is None or p25 is None or p75 is None:
        return None
    return {
        "year_built": int(round(median)),
        "p25": int(round(p25)),
        "p75": int(round(p75)),
        "spread": int(round(p75)) - int(round(p25)),
        "units": _num(row.get("units")),
        "geo_level": geo_level,
        "resolved": geo_level != "us",
        "label": f"{_LABEL[geo_level]} ({DATA_VINTAGE})",
        "source": f"{_LABEL[geo_level]} year built (ACS) — not this building's",
    }


def year_built_distribution_for(tract_geoid: str | None = None,
                                county_fips: str | None = None) -> dict | None:
    """Resolve a year-built distribution: tract → county → national.

    Returns ``{year_built, p25, p75, spread, units, geo_level, resolved, label,
    source}``, or None when no geography is supplied or nothing resolves.

    ``year_built`` is the area's median — a stand-in for an unknown building, never a
    measurement of one. ``p25``/``p75`` bound the middle half of the homes around it,
    and ``spread`` is how many years wide that is: the number that says whether the
    stand-in is worth trusting here.

    As in ``data/home_value.median_home_value_for``, the national row is only reached
    when *some* geography was requested — an offline or un-geocoded caller keeps its
    own default rather than being handed the US typical.
    """
    tract = str(tract_geoid).strip().zfill(11) if tract_geoid else None
    county = (str(county_fips).strip().zfill(5) if county_fips
              else (tract[:5] if tract else None))
    if not (tract or county):
        return None

    if tract:
        row = _tract_table().get(tract)
        if row is not None:
            hit = _reading(row, "tract")
            if hit is not None:
                return hit
    ctable = _county_table()
    if county:
        row = ctable.get(county)
        if row is not None:
            hit = _reading(row, "county")
            if hit is not None:
                return hit
    row = ctable.get(_NATIONAL)
    return _reading(row, "us") if row is not None else None
