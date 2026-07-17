#!/usr/bin/env python3
"""Modeled residential energy-consumption scoring library.

Models a parcel's residential energy use from Shelby County CAMA fields
(YRBLT/SFLA/EXTWALL/HEAT/FUEL/BSMT). Import ``model_parcel_energy`` to score a
single parcel and ``base_eui`` for the underlying ResStock benchmark lookup.

Data source & methodology
--------------------------
  Base site EUI: NREL ResStock 2024 simulation medians by building type × climate
  zone × vintage (~550 k modeled samples), bundled offline as data/resstock_eui.csv
  (built by scripts/build_resstock_eui.py from the OEDI data lake). Keying on
  building type gives Single-Family Attached, Multi-Family (2-4 and 5+ units), and
  Mobile/Manufactured homes their own curves instead of scoring every dwelling off
  the detached one; per-zone-per-vintage medians also capture the A/B/C moisture-
  regime spread (humid 3A vs dry 3B). Zones ResStock doesn't cover (e.g. 8 /
  interior Alaska), or building types it lacks for a zone, fall back — to detached,
  then to the prior 4A-scaled curve.
    https://registry.opendata.aws/nrel-pds-building-stock/

  Within-cell deviations (multiplicative, off the ResStock base): foundation and
  heating-system (HVAC) type are ResStock-derived, climate-controlled factors
  (data/resstock_factors.csv) — a heat-pump home uses less than the cell median;
  size and exterior wall remain engineering factors (wall is not a ResStock axis).

  Multi-Family note: keying the base on the real MF median measures the shared-wall
  effect directly, so the old modeled shared-wall credit (attachment_eui_factor) is
  retired from scoring. Small (2-4 unit) MF stock has *higher* per-sqft EUI than
  detached in ResStock; large (5+) MF lower — the intensity picture a flat credit
  could not represent.

  Upgrade path: extend the within-cell factors / benchmarks with more axes as the
  runtime gains them (heating fuel and HVAC type are not entered today, so they ride
  the heat-pump default); split MF benchmarks by unit-size band.

  Climate zone: from the property's county (data/climate.py, 2021 IECC).

  Utility rates — Memphis Light Gas & Water (MLGW / TVA territory)
    Electricity: $0.105 / kWh  (TVA wholesale + MLGW distribution, ~2024)
    Natural gas : $1.10  / therm  (MLGW residential gas rate, ~2024)
  Sources: TVA residential rate schedule; MLGW rate filings.

CAMA field decoding (Shelby County assessor codes)
---------------------------------------------------
  YRBLT   Year built (float; NaN when unknown)
  SFLA    Square feet living area (float; NaN when unknown)
  EXTWALL Construction/exterior-wall type:
            1 = Brick        3 = Block/Concrete   4 = Stone
            5 = Alum/Vinyl   7 = Frame/Wood        8 = Stucco
            9 = Brick veneer 10 = EIFS
  HEAT    Heating system:
            2 = Electric resistance   3 = Gas furnace   4 = Heat pump
  FUEL    Primary fuel:
            0 = None/all-electric     2 = Natural gas    3 = Other/propane
  BSMT    Foundation / basement:
            1 = Crawlspace or slab    2 = Partial basement   3 = Full basement

Columns added
-------------
  energy_vintage_bin      ResStock-style vintage category
  energy_size_bin         Floor-area bin (small / medium / large / very_large)
  energy_archetype        Composite archetype label (vintage + size + wall + hvac)
  eui_kbtu_sqft_yr        Modeled Energy Use Intensity (kBTU / sqft / yr, site)
  est_annual_kbtu         Total annual site energy (kBTU)
  est_annual_kwh          Estimated annual electricity (kWh)
  est_annual_therms       Estimated annual natural gas (therms)
  est_monthly_energy_cost Estimated monthly energy cost ($)
  energy_data_source      Citation for the EUI benchmark used
"""

from __future__ import annotations

import pandas as pd

# ── Utility rates (MLGW / TVA territory, ~2024) ───────────────────────────────
ELEC_RATE_PER_KWH  = 0.105   # $/kWh
GAS_RATE_PER_THERM = 1.10    # $/therm

# ── Unit conversions ──────────────────────────────────────────────────────────
KBTU_PER_KWH   = 3.412
KBTU_PER_THERM = 100.0

# ── Base site EUI (kBTU / sqft / yr) ──────────────────────────────────────────
# The base EUI for a home is looked up from NREL ResStock simulation medians by
# (climate zone × vintage) via data/resstock_eui.py — real per-zone-per-vintage
# values that capture the A/B/C moisture-regime spread (humid 3A vs dry 3B) the
# old single national curve could not. The fallback table below is retained ONLY
# for zones ResStock doesn't cover (e.g. zone 8 / interior Alaska): the prior
# 4A-calibrated curve scaled by a per-zone multiplier.
DEFAULT_CLIMATE_ZONE = "4A"
_FALLBACK_BASE_EUI: dict[str, float] = {
    "pre_1950":  75.0,
    "1950_1979": 60.0,
    "1980_1999": 45.0,
    "2000_2009": 35.0,
    "2010_plus": 28.0,
    "unknown":   50.0,   # mid-range default when YRBLT is missing
}
ZONE_EUI_FACTOR: dict[int, float] = {
    1: 0.85, 2: 0.90, 3: 0.95, 4: 1.00,
    5: 1.10, 6: 1.22, 7: 1.38, 8: 1.55,
}


def climate_zone_factor(climate_zone: str | None) -> float:
    """Map an IECC zone label (e.g. "5B") to a site-EUI multiplier vs. 4A
    (used only by the non-ResStock fallback base EUI)."""
    if not climate_zone:
        return 1.0
    try:
        return ZONE_EUI_FACTOR.get(int(str(climate_zone).strip()[0]), 1.0)
    except (ValueError, IndexError):
        return 1.0


DEFAULT_BUILDING_TYPE = "sf_detached"


def base_eui(climate_zone: str | None, vintage_bin: str,
             building_type: str = DEFAULT_BUILDING_TYPE) -> float:
    """Base site EUI (kBTU/sqft/yr) for a home's building type, climate zone, vintage.

    Prefers the NREL ResStock median for the building type × zone × vintage (a
    Multi-Family or Mobile-Home home gets its own curve, not the detached one);
    where ResStock has no coverage (e.g. zone 8 / interior Alaska) falls back to
    the prior 4A-calibrated curve scaled by the per-zone multiplier.
    """
    from housing_label.data.resstock_eui import resstock_base_eui
    # Fallback chain, most- to least-specific: this building type at the vintage,
    # then this type's all-vintage median (covers a dropped thin cell — e.g. a
    # pre-1950 mobile home — with the right building type), then Single-Family
    # Detached (same order), then the legacy scaled-4A curve for a wholly uncovered
    # zone (e.g. 8 / interior Alaska).
    vbins = (vintage_bin, "unknown") if vintage_bin != "unknown" else ("unknown",)
    for bt in dict.fromkeys((building_type, DEFAULT_BUILDING_TYPE)):
        for vb in vbins:
            eui = resstock_base_eui(climate_zone, vb, bt)
            if eui is not None:
                return eui
    # No ResStock coverage → the "unknown" mid-range fallback (never a KeyError).
    fallback = _FALLBACK_BASE_EUI.get(vintage_bin, _FALLBACK_BASE_EUI["unknown"])
    return fallback * climate_zone_factor(climate_zone)

# ── Vintage bin assignment ─────────────────────────────────────────────────────
def vintage_bin(yrblt) -> str:
    """Map a year-built float to a ResStock-style vintage bin."""
    if pd.isna(yrblt):
        return "unknown"
    yr = int(yrblt)
    if yr < 1950:
        return "pre_1950"
    if yr < 1980:
        return "1950_1979"
    if yr < 2000:
        return "1980_1999"
    if yr < 2010:
        return "2000_2009"
    return "2010_plus"


# ── Size bin assignment ───────────────────────────────────────────────────────
_SFLA_MEDIAN = 2044.0   # empirical median from shelby_parcels_sample.csv

def size_bin(sfla) -> tuple[str, float]:
    """Return (size_bin_label, sfla_to_use) — substitutes median for NaN."""
    area = _SFLA_MEDIAN if pd.isna(sfla) else float(sfla)
    if area < 1000:
        label = "small"
    elif area < 2000:
        label = "medium"
    elif area < 3500:
        label = "large"
    else:
        label = "very_large"
    return label, area


# ── EUI adjustment factors ────────────────────────────────────────────────────
# Each factor is multiplicative. Combined adjustment = product of all factors.
# These represent deviations from a "median" 1960s–1990s frame home.

def _size_factor(size_label: str) -> float:
    """Larger homes have slightly lower EUI (better surface-area-to-volume ratio)."""
    return {
        "small":      1.08,
        "medium":     1.00,
        "large":      0.95,
        "very_large": 0.88,
    }[size_label]


def _wall_factor(extwall) -> tuple[str, float]:
    """Exterior-wall construction type → (label, EUI factor)."""
    code = int(extwall) if not pd.isna(extwall) else None
    mapping = {
        1:  ("brick",         0.95),  # solid brick — good thermal mass
        3:  ("concrete_block",0.97),  # CMU — moderate thermal mass
        4:  ("stone",         0.93),  # stone — excellent thermal mass
        5:  ("vinyl_alum",    1.03),  # thin siding, minimal thermal mass
        7:  ("wood_frame",    1.00),  # baseline
        8:  ("stucco",        1.00),  # similar to frame
        9:  ("brick_veneer",  0.97),  # cavity + veneer — slightly better
        10: ("eifs",          0.95),  # exterior insulation — good performance
    }
    return mapping.get(code, ("other", 1.00))


def _resstock_factor(axis: str, label: str, fallback: float) -> float:
    """A ResStock-derived within-cell multiplier for (axis, label), or ``fallback``
    (a bundled copy of the shipped factor) when the factor table has no such row."""
    from housing_label.data.resstock_eui import resstock_factor
    f = resstock_factor(axis, label)
    return f if f is not None else fallback


# Foundation factors used only when the ResStock factor table is unavailable
# (packaging / partial checkout). They are EXACT copies of the shipped
# resstock_factors.csv values, so the degraded path matches the normal one — each
# is the within-cell median-EUI ratio vs. the mixed-stock cell median.
_FOUNDATION_FALLBACK = {
    1: ("crawlspace_slab",  1.003),  # slab / crawl / pier — ~= the cell median
    2: ("partial_basement", 1.033),  # unheated basement
    3: ("full_basement",    0.907),  # heated basement — lower per-sqft EUI
}


def _foundation_factor(bsmt) -> tuple[str, float]:
    """Foundation type → (label, EUI factor). The factor is the ResStock-derived,
    climate-controlled within-cell multiplier, falling back to a bundled exact copy
    of the shipped factor when the ResStock factor table is unavailable."""
    code = int(bsmt) if not pd.isna(bsmt) else None
    label, fallback = _FOUNDATION_FALLBACK.get(code, ("unknown", 1.00))
    if label == "unknown":
        return label, 1.00
    return label, _resstock_factor("foundation", label, fallback)


def _hvac_factor(heat, fuel) -> tuple[str, float]:
    """Heating system → (label, EUI factor).

    Heat pumps deliver ~3× more heat per kWh than resistance heating
    (COP 2.5–4.0 vs COP 1.0), so site EUI is lower for heat-pump homes.
    This is already partially captured in the base EUIs; the adjustment
    accounts for within-vintage variation.
    """
    heat_code = int(heat) if not pd.isna(heat) else None
    # Fallbacks used only when the ResStock factor table is unavailable; EXACT copies
    # of the shipped resstock_factors.csv values (within-cell median-EUI ratios vs.
    # the mixed-stock cell median), so the degraded path matches the normal one.
    fallback = {
        4: ("heat_pump",           0.782),  # efficient — well below the cell median
        2: ("electric_resistance", 0.959),  # COP 1
        3: ("gas_furnace",         1.043),  # gas combustion counted at the site meter
    }
    # Memphis is predominantly heat-pump territory; default to heat pump — using
    # the heat-pump fallback value too, so the degraded (no-table) path matches the
    # normal one for an unknown/blank heat code.
    label, fb = fallback.get(heat_code, fallback[4])
    return label, _resstock_factor("hvac", label, fb)


# ── Fuel split: electricity vs natural gas fraction of total site energy ───────
def _fuel_split(heat_label: str, fuel) -> tuple[float, float]:
    """Return (elec_fraction, gas_fraction) summing to 1.0.

    Split accounts for:
      • Space heating / cooling fuel
      • Water heating (often gas even in heat-pump homes)
      • Plug loads / lighting (always electric)

    Approximate CZ 4A residential end-use split (RECS 2020, DOE BA):
      Heat pump, no gas : elec 95%  gas  5% (mainly cooking if applicable)
      Heat pump + gas   : elec 80%  gas 20% (gas water heater, range)
      Electric resist.  : elec 90%  gas 10%
      Gas furnace       : elec 38%  gas 62%
    """
    fuel_code = int(fuel) if not pd.isna(fuel) else None
    has_gas = fuel_code == 2

    if heat_label == "heat_pump":
        return (0.80, 0.20) if has_gas else (0.95, 0.05)
    if heat_label == "electric_resistance":
        return (0.90, 0.10) if has_gas else (0.90, 0.10)
    if heat_label == "gas_furnace":
        return (0.38, 0.62)
    # Default: heat pump without gas
    return (0.95, 0.05)


# ── Per-parcel energy model ────────────────────────────────────────────────────
ENERGY_COLS = [
    "energy_vintage_bin",
    "energy_size_bin",
    "energy_archetype",
    "eui_kbtu_sqft_yr",
    "est_annual_kbtu",
    "est_annual_kwh",
    "est_annual_therms",
    "est_monthly_energy_cost",
    "energy_data_source",
]


def model_parcel_energy(
    row: pd.Series,
    climate_zone: str | None = DEFAULT_CLIMATE_ZONE,
    elec_rate: float = ELEC_RATE_PER_KWH,
    gas_rate: float = GAS_RATE_PER_THERM,
    building_type: str = DEFAULT_BUILDING_TYPE,
) -> dict:
    """Compute energy metrics for a single parcel.

    Steps
    -----
    1. Look up the base EUI (kBTU/sqft/yr) from ResStock by (building type × climate
       zone × vintage); zones ResStock doesn't cover fall back to the scaled 4A curve.
    2. Apply within-cell multiplicative adjustments: size, wall type, foundation, HVAC.
    3. Convert adjusted EUI × floor area → total annual kBTU.
    4. Split kBTU into electricity (kWh) and gas (therms) by fuel split.
    5. Compute estimated monthly cost at utility rates.

    `climate_zone` is an IECC zone label (e.g. "5B"); defaults to 4A (the pilot).
    `building_type` selects the ResStock benchmark (sf_detached / sf_attached /
    mf_2_4 / mf_5plus / mobile_home); defaults to detached.
    `elec_rate` ($/kWh) and `gas_rate` ($/therm) default to the Memphis/TVA pilot
    constants; the live path passes the property's state rates (data/utility_rates).
    """
    # --- Base EUI: ResStock building-type × zone × vintage median (fallback: 4A) ---
    vbin = vintage_bin(row.get("YRBLT"))
    base = base_eui(climate_zone, vbin, building_type)

    # --- Size ---
    sbin, area = size_bin(row.get("SFLA"))

    # --- Adjustment factors ---
    sf  = _size_factor(sbin)
    wall_label, wf  = _wall_factor(row.get("EXTWALL"))
    fnd_label, ff   = _foundation_factor(row.get("BSMT"))
    hvac_label, hf  = _hvac_factor(row.get("HEAT"), row.get("FUEL"))

    # --- Adjusted EUI (ResStock base × within-cell deviations) ---
    adj_eui = round(base * sf * wf * ff * hf, 2)

    # --- Annual totals ---
    annual_kbtu = round(adj_eui * area, 1)
    elec_frac, gas_frac = _fuel_split(hvac_label, row.get("FUEL"))
    annual_kwh    = round(annual_kbtu * elec_frac / KBTU_PER_KWH, 1)
    annual_therms = round(annual_kbtu * gas_frac  / KBTU_PER_THERM, 1)

    # --- Monthly cost (at the property's local utility rates) ---
    annual_cost   = annual_kwh * elec_rate + annual_therms * gas_rate
    monthly_cost  = round(annual_cost / 12, 2)

    # --- Archetype label (building type + climate zone + vintage + size + wall + hvac) ---
    zone_tok = "cz" + str(climate_zone or DEFAULT_CLIMATE_ZONE).strip().lower()
    bt_tok = str(building_type or DEFAULT_BUILDING_TYPE).strip().lower()
    archetype = f"{bt_tok}_{zone_tok}_{vbin}_{sbin}_{wall_label}_{hvac_label}"

    return {
        "energy_vintage_bin":      vbin,
        "energy_size_bin":         sbin,
        "energy_archetype":        archetype,
        "eui_kbtu_sqft_yr":        adj_eui,
        "est_annual_kbtu":         annual_kbtu,
        "est_annual_kwh":          annual_kwh,
        "est_annual_therms":       annual_therms,
        "est_monthly_energy_cost": monthly_cost,
        "energy_data_source":      (
            "NREL ResStock 2024 building-type×zone×vintage site-EUI medians; "
            "ResStock-derived within-cell foundation/HVAC (+ size/wall) deviations; "
            "local utility rates"
        ),
    }
