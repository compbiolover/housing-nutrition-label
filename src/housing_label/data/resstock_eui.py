"""Base residential site-EUI benchmark by building type × climate zone × vintage,
plus ResStock-derived within-cell adjustment factors (bundled, offline).

The Energy dimension scores a home against a base site Energy Use Intensity
(kBTU/sqft/yr) for its **building type**, climate zone, and vintage. These tables
supply that base and the within-cell nudges from **NREL ResStock** simulation
medians (~550k modeled dwellings). Built by ``scripts/build_resstock_eui.py``
into ``resstock_eui.csv`` and ``resstock_factors.csv``; see it for the aggregation.

``resstock_base_eui(zone, vintage_bin, building_type)`` resolves the base EUI:
it tries the requested building type ("mf_5plus", "mobile_home", …), then falls
back to Single-Family Detached; within each it tries the full zone string ("4A")
then the bare leading digit ("4") as a moisture-weighted fallback. It returns None
only when ResStock has no coverage at all (e.g. zone 8 / interior Alaska) so the
caller can fall back to its prior benchmark. Building types: sf_detached,
sf_attached, mf_2_4, mf_5plus, mobile_home. Keying on building type adds real
Multi-Family and Mobile-Home medians (previously every dwelling was scored off the
detached curve). Vintage bins mirror ``enrich/energy.py`` (pre_1950 / 1950_1979 /
1980_1999 / 2000_2009 / 2010_plus, plus "unknown").

``resstock_factor(axis, key)`` returns a within-cell multiplier (or None) for the
"foundation" and "hvac" axes — the ResStock-grounded replacement for the model's
hand-tuned foundation / HVAC nudges, each normalized to the model's baseline value
for that axis (crawl/slab = 1.0, heat pump = 1.0).
"""

from __future__ import annotations

import csv
import logging
import pathlib
from functools import lru_cache

log = logging.getLogger(__name__)

_DIR = pathlib.Path(__file__).resolve().parent
_EUI_CSV = _DIR / "resstock_eui.csv"
_FACTORS_CSV = _DIR / "resstock_factors.csv"

DEFAULT_BUILDING_TYPE = "sf_detached"


@lru_cache(maxsize=1)
def _table() -> dict[tuple[str, str, str], float]:
    table: dict[tuple[str, str, str], float] = {}
    if not _EUI_CSV.exists():
        # Cached, so this warns once: the bundled table is missing (packaging /
        # partial-checkout issue) and the Energy model will silently fall back to
        # its legacy curve — surface it rather than degrade invisibly.
        log.warning("ResStock EUI table not found at %s — Energy falls back to the "
                    "legacy zone-scaled curve.", _EUI_CSV)
        return table
    with _EUI_CSV.open(newline="") as f:
        for row in csv.DictReader(f):
            bt = str(row["building_type"]).strip()
            zone = str(row["climate_zone"]).strip()
            vbin = str(row["vintage_bin"]).strip()
            try:
                table[(bt, zone, vbin)] = float(row["eui_kbtu_sqft_yr"])
            except (TypeError, ValueError):
                continue
    return table


@lru_cache(maxsize=1)
def _factors() -> dict[tuple[str, str], float]:
    table: dict[tuple[str, str], float] = {}
    if not _FACTORS_CSV.exists():
        log.warning("ResStock factor table not found at %s — Energy uses its "
                    "hand-tuned foundation/HVAC factors.", _FACTORS_CSV)
        return table
    with _FACTORS_CSV.open(newline="") as f:
        for row in csv.DictReader(f):
            axis = str(row["axis"]).strip()
            key = str(row["key"]).strip()
            try:
                table[(axis, key)] = float(row["factor"])
            except (TypeError, ValueError):
                continue
    return table


def resstock_base_eui(climate_zone: str | None, vintage_bin: str,
                      building_type: str = DEFAULT_BUILDING_TYPE) -> float | None:
    """Base site EUI (kBTU/sqft/yr) for a building type + climate zone + vintage.

    Falls back building type → Single-Family Detached, then full zone ("4A") →
    leading digit ("4"). Returns None when ResStock doesn't cover the zone, so the
    caller keeps its own fallback.
    """
    if not climate_zone:
        return None
    table = _table()
    bt = str(building_type or DEFAULT_BUILDING_TYPE).strip()
    # Normalize so a lowercase "4a" still matches the "4A" row rather than losing
    # the moisture regime to the digit fallback.
    zone = str(climate_zone).strip().upper()
    # Building-type fallback: the requested type, then detached (dedup keeps order).
    for bt_key in dict.fromkeys((bt, DEFAULT_BUILDING_TYPE)):
        for zone_key in (zone, zone[:1]):
            eui = table.get((bt_key, zone_key, vintage_bin))
            if eui is not None:
                return eui
    return None


def resstock_factor(axis: str, key: str) -> float | None:
    """Within-cell EUI multiplier for a (axis, key), or None if not tabulated.

    Axes: "foundation" (keys crawlspace_slab / partial_basement / full_basement),
    "hvac" (keys heat_pump / electric_resistance / gas_furnace).
    """
    return _factors().get((str(axis).strip(), str(key).strip()))
