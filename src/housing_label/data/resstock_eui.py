"""Base residential site-EUI benchmark by climate zone × vintage (bundled, offline).

The Energy dimension scores a home against a base site Energy Use Intensity
(kBTU/sqft/yr) for its climate zone and vintage. This table supplies that base
from **NREL ResStock** simulation medians (Single-Family Detached, ~338k modeled
samples), replacing the old single national 4A curve scaled by a crude per-zone
multiplier — which ignored the large A/B/C moisture-regime spread (humid 3A vs
dry 3B) and under-read newer stock. Built by ``scripts/build_resstock_eui.py``
into ``resstock_eui.csv``; see it for the aggregation. Values are weighted medians.

``resstock_base_eui(zone, vintage_bin)`` resolves a full zone string ("4A") first,
then the bare leading digit ("4") as a moisture-weighted fallback (for a bundled
zone that is just a digit, e.g. 7, or a regime ResStock doesn't sample), and
returns None when ResStock has no coverage at all (e.g. zone 8 / interior Alaska)
so the caller can fall back to its prior benchmark. The vintage bins mirror
``enrich/energy.py`` (pre_1950 / 1950_1979 / 1980_1999 / 2000_2009 / 2010_plus,
plus "unknown" for a missing year built).
"""

from __future__ import annotations

import csv
import pathlib
from functools import lru_cache

_CSV = pathlib.Path(__file__).resolve().parent / "resstock_eui.csv"


@lru_cache(maxsize=1)
def _table() -> dict[tuple[str, str], float]:
    table: dict[tuple[str, str], float] = {}
    if not _CSV.exists():
        return table
    with _CSV.open() as f:
        for row in csv.DictReader(f):
            zone = str(row["climate_zone"]).strip()
            vbin = str(row["vintage_bin"]).strip()
            try:
                table[(zone, vbin)] = float(row["eui_kbtu_sqft_yr"])
            except (TypeError, ValueError):
                continue
    return table


def resstock_base_eui(climate_zone: str | None, vintage_bin: str) -> float | None:
    """Base site EUI (kBTU/sqft/yr) for a climate zone + vintage bin, or None.

    Tries the full zone ("4A"), then the leading digit ("4"). Returns None when
    ResStock doesn't cover the zone, so the caller keeps its own fallback.
    """
    if not climate_zone:
        return None
    table = _table()
    zone = str(climate_zone).strip()
    for key in (zone, zone[:1]):
        eui = table.get((key, vintage_bin))
        if eui is not None:
            return eui
    return None
