"""County typical lot density (keyless + offline).

Supplies the one number ``enrich/infrastructure.py`` needs to stop counting a
county's ruralness twice: the density at which that county's per-capita spending
multiplier was actually observed, expressed on the **same axis as a parcel's lot
density** so the two can be compared through the same cost curve.

Housing units per acre of the land class they occupy — urban units over urban land,
rural units over rural land, blended geometrically by unit count. See
``scripts/build_county_lot_density.py`` for the derivation, the Census source, and
why gross county density (the obvious alternative) is the wrong quantity.

Resolution
----------
``county_lot_density_for_county`` resolves a 5-digit FIPS to its DU/acre
(``resolved="county"``); an unmapped or None county falls back to the national row
(``resolved="national"``). Always returns a dict, never None — a missing county
must degrade to the national average rather than silently disable the correction.
"""

from __future__ import annotations

import csv
import pathlib
from functools import lru_cache

from housing_label.data._util import num as _num

_DIR = pathlib.Path(__file__).resolve().parent
_CSV = _DIR / "county_lot_density.csv"
_NATIONAL_GEOID = "00000"

# The national row's blended density, hard-coded so a stripped install degrades to
# "no county-specific adjustment" rather than raising.
_US_FALLBACK_DU_ACRE = 0.604934


@lru_cache(maxsize=1)
def _table() -> dict[str, dict]:
    """county FIPS (5-digit, zero-padded) -> row."""
    table: dict[str, dict] = {}
    if not _CSV.exists():
        return table
    with _CSV.open(newline="") as f:
        for row in csv.DictReader(f):
            raw = str(row.get("geoid", "")).strip()
            if not raw:            # skip blanks before zero-padding, else zfill
                continue           # would clobber the "00000" national row
            table[raw.zfill(5)] = row
    return table


def _result(row: dict, resolved: str) -> dict:
    du = _num(row.get("du_acre"))
    return {
        "du_acre": du if du and du > 0 else _US_FALLBACK_DU_ACRE,
        "du_acre_urban": _num(row.get("du_acre_urban")),
        "du_acre_rural": _num(row.get("du_acre_rural")),
        "label": (row.get("name") or "").strip() or None,
        "resolved": resolved,
    }


def county_lot_density_for_county(county_fips: str | None) -> dict:
    """Return ``{du_acre, du_acre_urban, du_acre_rural, label, resolved}``."""
    table = _table()
    fips = str(county_fips).strip().zfill(5) if county_fips else ""
    row = table.get(fips) if fips else None
    if row is not None:
        return _result(row, "county")
    national = table.get(_NATIONAL_GEOID)
    if national is not None:
        return _result(national, "national")
    return {"du_acre": _US_FALLBACK_DU_ACRE, "du_acre_urban": None,
            "du_acre_rural": None,
            "label": "US national average (bundled file missing)", "resolved": "none"}
