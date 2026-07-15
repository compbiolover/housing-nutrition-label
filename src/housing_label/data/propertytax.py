"""Per-county effective property-tax rate (Census ACS, keyless).

Returns the effective property-tax rate (annual property tax as a fraction of
home value) for a U.S. county — the **revenue side** of Infrastructure Burden's
fiscal ratio. It replaces the single national effective rate previously applied
to every non-Shelby location, so the revenue estimate reflects local tax burden
(rates vary ~10x nationally, ~0.3%–3%).

Data
----
Bundled by ``scripts/build_property_tax.py`` as ``property_tax_county.csv`` from
the U.S. Census Bureau **American Community Survey 5-year** table-based summary
file: effective rate = median real estate taxes paid (B25103) / median home value
(B25077), per county, clamped to [0.1%, 5.0%].

Resolution
----------
``property_tax_for_county`` resolves a 5-digit county FIPS → its effective rate
(``resolved="county"``); an unmapped/None county falls back to the national-average
row (``resolved="national"``). Always returns a dict, never None.

Caveats
-------
ACS effective-rate proxies are county-level and noisy (a median-of-medians ratio,
within the ACS margin of error only ~half-to-two-thirds of the time) and reflect
ALL property taxes including the school-district share — while the cost side
(``data/govfinance.py``) excludes school spending — so the fiscal ratio is for
relative comparison, not absolute accounting. Sub-county / per-jurisdiction millage
(state DOR tables) is a future refinement.
"""

from __future__ import annotations

import csv
import pathlib
from functools import lru_cache

DATA_VINTAGE = "Census ACS 2024 5-yr (median taxes / median value)"
US_AVG_LABEL = f"US national average ({DATA_VINTAGE})"
LEGACY_NATIONAL_RATE = 0.011   # ultimate fallback if the crosswalk isn't bundled
RATE_FLOOR, RATE_CEIL = 0.001, 0.05   # 0.1%–5.0% sanity clamp (mirrors the build)

_DIR = pathlib.Path(__file__).resolve().parent
_CSV = _DIR / "property_tax_county.csv"
_NATIONAL_GEOID = "00000"


from housing_label.data._util import num as _num  # shared CSV-cell float coercion


@lru_cache(maxsize=1)
def _table() -> dict[str, dict]:
    """county FIPS (5-digit, zero-padded) → raw crosswalk row."""
    table: dict[str, dict] = {}
    if not _CSV.exists():
        return table
    with _CSV.open(newline="") as f:
        for row in csv.DictReader(f):
            raw = str(row.get("geoid", "")).strip()
            if not raw:
                continue
            table[raw.zfill(5)] = row
    return table


def _rate(row: dict) -> float | None:
    r = _num(row.get("effective_tax_rate"))
    if r is None or r <= 0:
        return None
    return max(RATE_FLOOR, min(RATE_CEIL, r))   # enforce the documented clamp at runtime


def _national_rate() -> float:
    nat = _table().get(_NATIONAL_GEOID)
    return (_rate(nat) if nat else None) or LEGACY_NATIONAL_RATE


def median_home_value_for_county(county_fips: str | None) -> float | None:
    """County median owner-occupied home value (ACS B25077), or None if unmapped.

    Used to auto-fill a realistic home value when the caller doesn't supply one,
    so the fiscal-ratio revenue side reflects the local market.
    """
    fips = str(county_fips).strip().zfill(5) if county_fips else None
    row = _table().get(fips) if fips else None
    v = _num(row.get("median_value")) if row is not None else None
    return v if v is not None and v > 0 else None


def property_tax_for_county(county_fips: str | None) -> dict:
    """Return the effective property-tax rate for a 5-digit county FIPS.

    Always returns a dict: a mapped county carries its ACS effective rate
    (``resolved="county"``); a missing/None county falls back to the national
    average (``resolved="national"``).

    Keys: ``label``, ``effective_tax_rate`` (fraction of value/yr), ``resolved``,
    ``geo_level``.
    """
    fips = str(county_fips).strip().zfill(5) if county_fips else None
    row = _table().get(fips) if fips else None
    rate = _rate(row) if row is not None else None
    if rate is not None and row.get("resolved") == "county":
        return {
            "label": f"County {fips} ({DATA_VINTAGE})",
            "effective_tax_rate": rate,
            "resolved": "county",
            "geo_level": "county",
        }
    return {
        "label": US_AVG_LABEL,
        "effective_tax_rate": _national_rate(),
        "resolved": "national",
        "geo_level": "us",
    }
