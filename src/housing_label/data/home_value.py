"""Median owner-occupied home value (ACS **B25077**), tract → county → national.

Auto-fills a home value when the user doesn't type one — it feeds the
Infrastructure fiscal ratio and the dollar disaster-loss figures. The neighborhood
(census-tract) median is preferred, falling back to the county median, then the
national median, so an address in an expensive neighborhood no longer reads at the
much-lower county-wide typical.

This is a **median**, so it's a neighborhood typical — *not* a specific property's
value (which only a user entry, or a commercial AVM we deliberately don't use,
would give). Bundled from ``scripts/build_home_value.py`` (keyless ACS Summary
File). A user-entered value always overrides the auto-fill.
"""

from __future__ import annotations

import csv
import gzip
import pathlib
from functools import lru_cache

from housing_label.data._util import num as _num

_DIR = pathlib.Path(__file__).resolve().parent
_CSV_GZ = _DIR / "home_value.csv.gz"
_NATIONAL = "00000"

DATA_VINTAGE = "ACS 2023 5-yr median home value (B25077)"
_LABEL = {"tract": "neighborhood (census-tract) median",
          "county": "county median", "national": "US median"}


@lru_cache(maxsize=1)
def _table() -> dict[str, float]:
    """geoid → median value for every bundled tract / county / national row."""
    out: dict[str, float] = {}
    if not _CSV_GZ.exists():
        return out
    with gzip.open(_CSV_GZ, "rt", newline="") as f:
        for row in csv.DictReader(f):
            geoid = (row.get("geoid") or "").strip()
            v = _num(row.get("median_value"))
            if geoid and v is not None and v > 0:
                out[geoid] = v
    return out


def median_home_value_for(tract_geoid: str | None = None,
                          county_fips: str | None = None) -> dict:
    """Resolve a median home value: tract → county → national.

    Returns ``{value, geo_level, resolved, source}``. ``geo_level`` is
    ``"tract"`` / ``"county"`` / ``"national"`` (or None when nothing is bundled);
    ``resolved`` is True for a real tract/county hit (False for the national
    fallback). ``value`` is None only when even the national row is absent.
    """
    table = _table()
    tract = str(tract_geoid).strip().zfill(11) if tract_geoid else None
    county = (str(county_fips).strip().zfill(5) if county_fips
              else (tract[:5] if tract else None))
    if tract and tract in table:
        return _hit(table[tract], "tract")
    if county and county in table:
        return _hit(table[county], "county")
    # National fallback only when SOME geography was requested — never invent a
    # value from no location at all, so an offline / un-geocoded caller keeps its
    # own default instead of being handed the US median.
    if (tract or county) and _NATIONAL in table:
        return _hit(table[_NATIONAL], "national")
    return {"value": None, "geo_level": None, "resolved": False, "source": None}


def _hit(value: float, level: str) -> dict:
    return {"value": value, "geo_level": level, "resolved": level != "national",
            "source": f"{_LABEL[level]} (ACS)"}
