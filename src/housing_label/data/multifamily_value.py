"""Per-unit ("value-per-door") value for a multi-family building (keyless).

The single-family owner-occupied median (ACS B25077, ``data/propertytax.py``) is
wrong for an apartment or condo: for a rental building it carries no value at all,
and dividing a single-home median across units understates each unit badly. This
module estimates a per-unit value the way apartments are actually valued — the
**income / cap-rate method** — from local market rent:

    value_per_door = (annual_rent × occupancy × (1 − opex_ratio)) / cap_rate
                   =  NOI_per_door / cap_rate

Rent input (the HUD-FMR seam)
-----------------------------
Rent comes from the bundled ``rent_county.csv`` (ACS B25064 median gross rent,
built by ``scripts/build_rent.py``). ACS gross rent is what *current* tenants pay,
so it slightly understates market rent for new construction. HUD **Fair Market
Rents** (40th-percentile, market-rent-targeted, per-bedroom) are the preferred
input; they can be dropped in later without touching the value formula by either
(a) building a ``fmr_county.csv`` with the same schema and pointing
``_gross_rent_for_county`` at it, or (b) passing ``monthly_rent=`` into
``value_per_door_for_county`` from a HUD lookup. The formula and constants below
are source-agnostic.

Valuation constants (bundled, documented, sourced)
--------------------------------------------------
- ``OCCUPANCY`` 0.93 — national rental occupancy ~93–94% (Census HVS).
- ``OPEX_RATIO`` 0.40 — apartment operating-expense ratio, ~35–45% of effective
  gross income (industry consensus).
- ``CAP_RATE`` 0.055 — national multi-family cap rate, ~5.0–5.7% in 2024–25
  (CBRE / Statista); ±100 bps ≈ ±20% value, so this is the dominant assumption.

Caveats
-------
County-level and neighborhood-average, not building-specific; blends unit sizes
and subsidy; NSI's "multifamily" doesn't distinguish rental from condo, so one
income-based per-door value serves both (a condo's for-sale value can differ from
its rental-cap-rate value). This is a relative-scoring estimate, not an appraisal.
"""

from __future__ import annotations

import csv
import pathlib
from functools import lru_cache

DATA_VINTAGE = "Census ACS 2022 5-yr median gross rent (B25064)"
RENT_SOURCE_LABEL = "value-per-door (income method, ACS rent)"
OVERRIDE_SOURCE_LABEL = "value-per-door (income method, rent override)"

# Income-method valuation constants (see module docstring for sources).
OCCUPANCY = 0.93
OPEX_RATIO = 0.40
CAP_RATE = 0.055

RENT_FLOOR, RENT_CEIL = 200.0, 5000.0     # $/mo clamp (mirrors the build script)
NATIONAL_RENT = 1300.0                     # ultimate fallback if the crosswalk isn't bundled
VALUE_FLOOR = 20_000.0                     # per-door sanity floor

_DIR = pathlib.Path(__file__).resolve().parent
_CSV = _DIR / "rent_county.csv"
_NATIONAL_GEOID = "00000"


from housing_label.data._util import num as _num  # shared CSV-cell float coercion


@lru_cache(maxsize=1)
def _table() -> dict[str, dict]:
    """county FIPS (5-digit, zero-padded) → raw rent-crosswalk row."""
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


def _clamp_rent(v: float | None) -> float | None:
    if v is None or v <= 0:
        return None
    return max(RENT_FLOOR, min(RENT_CEIL, v))


def _national_rent() -> float:
    nat = _table().get(_NATIONAL_GEOID)
    return (_clamp_rent(_num(nat.get("median_gross_rent"))) if nat else None) or NATIONAL_RENT


def _gross_rent_for_county(county_fips: str | None) -> tuple[float, str]:
    """Return (monthly gross rent, resolved) for a county FIPS, national fallback.

    This is the single point a HUD FMR source would replace: swap the bundled ACS
    ``rent_county.csv`` for an ``fmr_county.csv`` of the same schema and every
    downstream value estimate follows, no formula change.
    """
    fips = str(county_fips).strip().zfill(5) if county_fips else None
    row = _table().get(fips) if fips else None
    rent = _clamp_rent(_num(row.get("median_gross_rent"))) if row is not None else None
    if rent is not None and row.get("resolved") == "county":
        return rent, "county"
    return _national_rent(), "national"


def value_from_rent(monthly_rent: float, *, occupancy: float = OCCUPANCY,
                    opex_ratio: float = OPEX_RATIO, cap_rate: float = CAP_RATE) -> float:
    """Per-door value from monthly market rent via the income / cap-rate method.

    A non-positive ``cap_rate`` is nonsensical (and would divide by zero), so it
    falls back to the module default rather than crashing the caller."""
    if cap_rate <= 0:
        cap_rate = CAP_RATE
    annual_noi = monthly_rent * 12.0 * occupancy * (1.0 - opex_ratio)
    return max(VALUE_FLOOR, annual_noi / cap_rate)


def value_per_door_for_county(county_fips: str | None,
                              monthly_rent: float | None = None) -> dict:
    """Estimate the per-unit value of a multi-family building in a county.

    ``monthly_rent`` overrides the bundled rent lookup (the HUD-FMR seam — pass a
    Fair Market Rent here to prefer it). Otherwise the county's ACS median gross
    rent is used, with the national row as fallback.

    Always returns a dict: ``value_per_door``, ``monthly_rent``, ``cap_rate``,
    ``resolved`` (``"county"`` | ``"national"`` | ``"override"``), ``source``
    (label — names the rent origin, ACS vs. an override), ``geo_level``.
    """
    if monthly_rent is not None and monthly_rent > 0:
        rent = _clamp_rent(monthly_rent) or _national_rent()
        resolved = "override"
    else:
        rent, resolved = _gross_rent_for_county(county_fips)

    # geo_level tracks the geography of the estimate: a county lookup is county-
    # scoped; an override is county-scoped when the caller supplied a county context
    # (the common HUD-FMR-per-county seam), else national.
    is_county_scoped = resolved == "county" or (resolved == "override" and bool(county_fips))
    return {
        "value_per_door": round(value_from_rent(rent), 2),
        "monthly_rent": round(rent, 2),
        "cap_rate": CAP_RATE,
        "resolved": resolved,
        "source": OVERRIDE_SOURCE_LABEL if resolved == "override" else RENT_SOURCE_LABEL,
        "geo_level": "county" if is_county_scoped else "us",
    }
