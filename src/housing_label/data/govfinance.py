"""Per-county local-government finance calibration (Census of Governments, keyless).

Returns per-function **cost multipliers** that scale the Infrastructure Burden
density cost curves from the Memphis (Shelby County) pilot calibration to a
county's actual local spending level. A county that spends 2x the Memphis
per-capita rate on roads gets ``mult_roads = 2.0``; Shelby itself is 1.0 on every
function, so the pilot is unchanged.

Data
----
Bundled by ``scripts/build_govfinance.py`` as ``govfinance_county.csv`` from the
U.S. Census Bureau **2022 Census of Governments — Individual Unit File** (direct
general expenditure by function, per capita, normalized to Shelby) plus Census
**Population Estimates** for the denominator. Multipliers are pre-clamped to
[0.25, 4.0]; a county with zero recorded local spend on a function already carries
the national-average multiplier for it.

Resolution
----------
``govfinance_for_county`` resolves a 5-digit county FIPS → its multipliers
(``resolved="county"``); an unmapped/None county falls back to the national-average
row (``resolved="national"``). Always returns a dict, never None.

Caveats
-------
These are present-day (FY2022 census) per-capita spending ratios, not a forward
projection, and they capture *spending level*, not service quality. County-area
aggregation assigns each local unit to one county (a city or special district
spanning counties is counted in its home county), and special districts that serve
across county lines introduce attribution error. The cost-to-serve density *shape*
still comes from the Halifax/Memphis curves — this layer recalibrates only the
per-function level.
"""

from __future__ import annotations

import csv
import pathlib
from functools import lru_cache

DATA_VINTAGE = "Census of Governments 2022 (per-capita local direct expenditure)"
US_AVG_LABEL = f"US national average ({DATA_VINTAGE})"

_DIR = pathlib.Path(__file__).resolve().parent
_CSV = _DIR / "govfinance_county.csv"
_NATIONAL_GEOID = "00000"

COMPONENTS = ["roads", "water_sewer", "fire", "police", "sanitation", "parks"]


def _num(v) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


@lru_cache(maxsize=1)
def _table() -> dict[str, dict]:
    """county FIPS (5-digit, zero-padded) → raw crosswalk row."""
    table: dict[str, dict] = {}
    if not _CSV.exists():
        return table
    with _CSV.open(newline="") as f:
        for row in csv.DictReader(f):
            raw = str(row.get("geoid", "")).strip()
            if not raw:                 # skip blank GEOIDs before zero-padding
                continue                # (else zfill would clobber the "00000" national row)
            table[raw.zfill(5)] = row
    return table


def _multipliers(row: dict) -> dict[str, float]:
    """Extract the six cost multipliers from a row (missing/invalid → 1.0)."""
    out = {}
    for c in COMPONENTS:
        v = _num(row.get(f"mult_{c}"))
        out[c] = v if v is not None and v > 0 else 1.0
    return out


def _national() -> dict | None:
    return _table().get(_NATIONAL_GEOID)


# Ultimate fallback for the school-tax share when the crosswalk isn't bundled
# (the national figure ≈ 41% of local property tax funds schools).
LEGACY_SCHOOL_SHARE = 0.41


def _school_share(row: dict | None) -> float:
    v = _num(row.get("school_tax_share")) if row is not None else None
    return v if v is not None and 0.0 <= v <= 1.0 else LEGACY_SCHOOL_SHARE


def govfinance_for_county(county_fips: str | None) -> dict:
    """Return the infrastructure cost multipliers for a 5-digit county FIPS.

    Always returns a dict: a mapped county carries its per-function multipliers
    (``resolved="county"``); a missing/None county falls back to the national
    average (``resolved="national"``). If the crosswalk isn't bundled at all,
    returns neutral 1.0 multipliers (``resolved="none"``) so the model degrades to
    the Memphis baseline rather than failing.

    Keys: ``label``, ``multipliers`` (dict of the six components),
    ``school_tax_share`` (fraction of local property tax funding schools, for
    netting the revenue side to a like-for-like non-school basis), ``resolved``,
    ``geo_level``.
    """
    fips = str(county_fips).strip().zfill(5) if county_fips else None
    row = _table().get(fips) if fips else None
    if row is not None:
        name = (row.get("county_name") or "").strip()
        state = (row.get("state") or "").strip()
        place = f"{name}, {state}".strip(", ") or fips
        return {
            "label": f"{place} ({DATA_VINTAGE})",
            "multipliers": _multipliers(row),
            "school_tax_share": _school_share(row),
            "resolved": "county",
            "geo_level": "county",
        }
    nat = _national()
    if nat is not None:
        return {
            "label": US_AVG_LABEL,
            "multipliers": _multipliers(nat),
            "school_tax_share": _school_share(nat),
            "resolved": "national",
            "geo_level": "us",
        }
    # Crosswalk absent entirely — neutral fallback (Memphis baseline).
    return {
        "label": "uncalibrated (Memphis baseline)",
        "multipliers": {c: 1.0 for c in COMPONENTS},
        "school_tax_share": LEGACY_SCHOOL_SHARE,
        "resolved": "none",
        "geo_level": "us",
    }
