"""Per-county school millage, for netting schools off the revenue side by measurement.

The Infrastructure Burden fiscal ratio compares *non-school* municipal cost to *non-school*
municipal revenue. Getting the revenue side to a non-school basis has always been an
estimate:

    municipal_rate = effective_tax_rate * (1 - school_tax_share)

where ``effective_tax_rate`` is ACS B25103 / B25077 — **owner-occupied homes only** — and
``school_tax_share`` is Census of Governments — **all property in the county**. Two
populations, multiplied together.

That is fine where owner-occupied homes pay school taxes on the same footing as everything
else. It breaks wherever a state gives owner-occupied homes **school-specific** relief: the
ACS rate has already lost most of its school component, and netting the county-wide share
removes it a second time. The result understates non-school revenue — and so the score — for
every parcel in that state, owner and rental alike.

This module supplies the alternative. Where a county's school rates and the statutory owner
exemption are known, ``owner_school_rate`` computes what the *owner* actually pays in school
tax as a fraction of home value, so the consumer can **subtract** it:

    municipal_rate = max(0.0, effective_tax_rate - owner_school_rate(value))

Both terms are then measured over owner-occupied homes. No county without a row is affected:
``owner_school_rate`` returns ``None`` rather than a guess, and the caller keeps the
multiplicative path.

Coverage
--------
**Texas only** (9.2% of the US population), bundled by ``scripts/build_school_millage.py``
from the Comptroller's *ISD Rates and Levies* file. Michigan, Arizona, South Carolina, South
Dakota and Vermont have the same defect for a combined further 7.4%; each needs a different
state source, and Michigan and South Carolina exempt an entire operating levy rather than a
slice of value, so they need an operating-versus-debt millage split rather than this shape.
See ``research/infrastructure-burden-research.md``.

The Texas exemption reaches both levies
---------------------------------------
Tex. Tax Code § 11.13(b) exempts $100,000 of appraised value from school district taxes.
Secondary sources say confidently that this covers maintenance-and-operations only, not debt
service — the source file shows otherwise, with the two taxable bases equal in 87% of
district-county rows and the I&S base never the smaller of the two. ``is_exempt_weight``
carries the measured share of each county's debt levy that the exemption does reach, so the
carve-out for districts with grandfathered debt is data-derived rather than assumed. The
build script documents the evidence.
"""

from __future__ import annotations

import csv
import pathlib
from functools import lru_cache

from housing_label.data._util import num as _num  # shared CSV-cell float coercion

DATA_VINTAGE = "Texas Comptroller ISD Rates and Levies 2024"

_DIR = pathlib.Path(__file__).resolve().parent
_CSV = _DIR / "school_millage_county.csv"


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


def millage_for_county(county_fips: str | None) -> dict | None:
    """Raw school-millage record for a county, or ``None`` if not covered.

    ``None`` is the honest answer for the ~96% of counties this file does not reach, and
    it is what keeps the change inert outside Texas — there is no national fallback row,
    because a national average school millage would be exactly the invented number this
    module exists to avoid.
    """
    fips = str(county_fips).strip().zfill(5) if county_fips else None
    if not fips:
        return None
    row = _table().get(fips)
    if row is None:
        return None
    mo = _num(row.get("school_mo_rate"))
    isr = _num(row.get("school_is_rate"))
    if mo is None or isr is None:
        return None
    weight = _num(row.get("is_exempt_weight"))
    exempt = _num(row.get("owner_exempt_value"))
    return {
        "state": (row.get("state") or "").strip(),
        "school_mo_rate": mo,
        "school_is_rate": isr,
        # Share of the debt levy the homestead exemption reaches. Defaults to 0.0 — the
        # leg that yields the LARGER owner school rate and so the smaller correction.
        "is_exempt_weight": min(max(weight, 0.0), 1.0) if weight is not None else 0.0,
        "owner_exempt_value": max(exempt, 0.0) if exempt is not None else 0.0,
        "vintage": DATA_VINTAGE,
    }


def owner_school_rate(county_fips: str | None, home_value: float | None) -> float | None:
    """School tax an owner-occupier actually pays, as a fraction of home value.

    ``None`` when the county is not covered or the value is unusable, which the caller
    must treat as "keep the multiplicative path" rather than as zero — a zero here would
    silently claim the owner pays no school tax at all.

    The operating levy applies to value above the exemption. The debt levy applies to that
    same reduced base for the share of the county's debt levy the exemption reaches
    (``is_exempt_weight``) and to full value for the rest — the districts that may still
    tax exempted homestead value for debt authorised before the exemption increases.
    """
    rec = millage_for_county(county_fips)
    if rec is None:
        return None
    try:
        value = float(home_value)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None

    taxable = max(0.0, value - rec["owner_exempt_value"])
    weight = rec["is_exempt_weight"]
    is_base = taxable * weight + value * (1.0 - weight)
    tax = rec["school_mo_rate"] * taxable + rec["school_is_rate"] * is_base
    return tax / value


def covered_states() -> tuple[str, ...]:
    """USPS codes with any school-millage coverage, sorted.

    Exposed so tests and the docs can assert the coverage boundary rather than restate it,
    and so a future state added to the crosswalk does not need a second edit here.
    """
    return tuple(sorted({(r.get("state") or "").strip()
                         for r in _table().values() if (r.get("state") or "").strip()}))
