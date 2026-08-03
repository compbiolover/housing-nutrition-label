"""Drinking-water compliance for a SPECIFIC public water system (keyless + offline).

``data/water.py`` answers "how exposed is the community-water-system-served
population around here" — a county aggregate, which is the right answer only when
you do not know which system serves the address. Now that ``enrich/water_system.py``
resolves a parcel to a PWSID, the better question is answerable: what is the
compliance record of the system that actually serves this home.

The metric
----------
``years_in_violation`` — the number of distinct YEARS in the trailing 5-year window
in which the system began a **health-based** violation (a contaminant exceedance or
treatment-technique failure that can affect health, as opposed to a paperwork or
monitoring lapse). Built by ``scripts/build_water.py`` from EPA SDWIS federal
reporting.

Distinct years rather than a violation count, because a single contamination event
can generate many violation records: counting records would rank one bad quarter
above a system chronically out of compliance, which is backwards for a resident
deciding whether to trust the tap.

Scoring
-------
The same **hurdle (two-part) model** ``data/water.py`` uses for counties, so a
system score and a county score mean the same thing on the same 0-100 axis:

  • **0 years → 100.** A clean record is a real, reachable optimum, not a tie to be
    broken — 38,857 of 49,162 active community systems (86% of the served
    population) have one, and they all deserve the top score.
  • **1+ years → the population-weighted share of the EXPOSED population on a
    system with a worse record.** Ranked only against systems that have any recent
    health-based violation, so the score falls steeply: a single violating year
    already puts a system below 72% of the exposed population.

The drop from 100 to 27.5 at the first violating year is not a calibration
artifact. It is what the distribution says: most systems are clean, so having any
recent health-based violation at all is genuinely unusual, and a score that
softened that would be describing a different country.

Anchors below are printed by ``scripts/build_water.py``; recompute and paste them
whenever the SDWIS snapshot is rebuilt, or the score stops tracking the
distribution it claims to.

Data
----
  water_system.csv — pwsid, pop_served, years_in_violation; one row per active
  community water system in the SDWIS federal-reporting export.
"""

from __future__ import annotations

import csv
import pathlib
from functools import lru_cache

from housing_label.data._util import num as _num

_DIR = pathlib.Path(__file__).resolve().parent
_CSV = _DIR / "water_system.csv"

# Trailing window the years are counted over (mirrors scripts/build_water.py).
RECENT_YEARS = 5

# years_in_violation → score. Population-weighted conditional survival among the
# exposed (see the module docstring); regenerate with scripts/build_water.py.
#   0: clean class                    1: 7,256 systems    2: 1,671 systems
#   3: 677 systems                    4: 404 systems      5: 297 systems
_SCORE_BY_YEARS = {
    0: 100.0,
    1: 27.5,
    2: 10.7,
    3: 6.3,
    4: 3.7,
    5: 0.0,
}


@lru_cache(maxsize=1)
def _table() -> dict[str, dict]:
    """PWSID → row. PWSIDs are alphanumeric (state prefix + digits), so they are
    used verbatim rather than zero-padded like a numeric GEOID."""
    table: dict[str, dict] = {}
    if not _CSV.exists():
        return table
    with _CSV.open(newline="") as f:
        for row in csv.DictReader(f):
            pwsid = str(row.get("pwsid", "")).strip().upper()
            if pwsid:
                table[pwsid] = row
    return table


def water_for_pwsid(pwsid: str | None) -> dict | None:
    """Return ``{score, years_in_violation, pop_served, pwsid}`` for a PWSID, or
    None when it is absent from the bundled SDWIS export.

    None is the honest answer for an unknown system, not a default score: the
    caller falls back to the county aggregate, which is what it had before the
    parcel→system join existed. A system EPA maps a service area for but SDWIS has
    no active record of (a recent merger, a data lag) must not be scored as clean.
    """
    if not pwsid:
        return None
    row = _table().get(str(pwsid).strip().upper())
    if row is None:
        return None
    years = _num(row.get("years_in_violation"))
    if years is None:
        return None
    years = max(0, min(int(years), RECENT_YEARS))
    return {
        "pwsid": str(row.get("pwsid", "")).strip().upper(),
        "years_in_violation": years,
        "pop_served": int(_num(row.get("pop_served")) or 0) or None,
        "score": _SCORE_BY_YEARS[years],
    }
