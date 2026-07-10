"""Bottom-up, geometry-aware embodied-carbon (A1-A3) for US single-family homes.

Estimates cradle-to-gate (A1-A3) embodied carbon, kgCO2e per m2 of gross floor
area, by building each home up from **its own geometry** rather than one fixed
per-m2 archetype ratio:

    intensity = ( foundation(footprint, perimeter, basement depth)
                + roof(roof area)
                + envelope(wall area, wall type)
                + floor(floor area) ) / floor_area

Every material GWP factor is a published industry-average EPD figure (a citable,
redistributable fact); every geometry constant is a standard residential
construction value (IRC / ACI / CMHA) or a public geometric relation. **No value
is from EC3, the CLF report, or any paywalled dataset** — the paywalled Jungclaus
2024 per-foundation multipliers are *not* used; the foundation term is computed
directly from concrete volumes × the NRMCA concrete EPD factor instead.

Why geometry
------------
Two published findings drive the design:

* **Foundation is the single largest driver** of residential embodied carbon and
  its biggest source of variance (Jungclaus et al. 2024): a full basement embodies
  several times the concrete of a slab-on-grade. So the foundation term is computed
  from footprint slab + perimeter walls (× actual/estimated basement depth) +
  footings, not a flat per-m2 constant.
* **Smaller and single-story homes have higher embodied intensity per m2** —
  envelope + roof + foundation grow faster than floor area as a home shrinks
  (Rauf et al. 2025, *Buildings*, CC-BY: 109 m2 -> 9.14 GJ/m2 vs 525 m2 -> 6.77,
  ~35% higher for the small home). So roof scales with roof area and the envelope
  with wall area, not with floor area.

Provenance & boundary
---------------------
Cradle-to-gate **A1-A3**; biogenic carbon nets to zero across A1-A3 (ISO 21930),
so no biogenic credit is taken. Full factor + geometry citation tables are in
``research/embodied-carbon-research.md`` and
``research/embodied-carbon-geometry-research.md``.

The material GWP factors are firm (industry-average EPDs) and the geometry
constants are standard code values; the **assembly allocations** (how the AWC
lumber/panel totals split across floor / wall / roof, and the heavy-masonry wall
factors) are representative estimates, so treat the output as a modeled intensity,
not a per-home measurement. Every wall × foundation × size combination is tested to
land inside the empirical A1-A3 single-family band (~39-210 kgCO2e/m2).
"""

from __future__ import annotations

import math

# ── Material GWP factors (industry-average EPD A1-A3; see research doc) ───────
_CONCRETE_KG_PER_M3 = 320.0    # representative 3000-4000 psi residential (NRMCA v3.2 / GSA)
_REBAR_KG_PER_KG    = 0.854    # US EAF rebar (CRSI)
_REBAR_KG_PER_M3    = 40.0     # modest residential foundation reinforcement (kg steel / m3 concrete)
# Reinforced-concrete GWP per m3 of foundation concrete:
_RC_KG_PER_M3 = _CONCRETE_KG_PER_M3 + _REBAR_KG_PER_M3 * _REBAR_KG_PER_KG   # ~354

# ── Foundation geometry constants (IRC / ACI / CMHA — standard code values) ───
_SLAB_THICK_M   = 0.10    # 4" slab-on-grade / basement slab (IRC R506, de-facto standard)
_WALL_THICK_M   = 0.20    # 8" poured/CMU foundation wall (IRC R404 / CMHA TEK 05-03A)
_FOOTING_W_M    = 0.40    # 16" continuous footing width (IRC R403.1)
_FOOTING_T_M    = 0.15    # 6" footing thickness (IRC R403.1)
_FULL_DEPTH_M   = 2.44    # full-basement wall height ~8 ft (IRC R404 tables)
_PARTIAL_DEPTH_M = 1.5    # partial basement / deep crawl
# Fraction of the footprint perimeter that carries a tall foundation wall, by BSMT
# code (1 = slab/crawl, 2 = partial, 3 = full). Slab/crawl carries only footings +
# a floor slab, no tall wall.
_WALL_FRAC = {1: 0.0, 2: 0.6, 3: 1.0}
_DEPTH_BY_BSMT = {2: _PARTIAL_DEPTH_M, 3: _FULL_DEPTH_M}

# ── Home shape / envelope geometry (public geometric relations + framing norms) ─
_SHAPE_C        = 4.1     # perimeter P = C·sqrt(footprint_area); C≈4.1 for a detached
                          # home of aspect ratio ~1.3-2.0 (P = 2(1+r)/sqrt(r)·sqrt(A))
_STORY_HEIGHT_M = 2.7     # gross wall height per story (8-9 ft framing)
_ROOF_PITCH_FACTOR = 1.12 # 6:12 roof: roof area ≈ 1.12 × footprint (trig fact)
_WINDOW_WALL_RATIO = 0.15 # typical residential window-to-wall ratio

# ── Shell assembly intensities ───────────────────────────────────────────────
# Per m2 of FLOOR area (interior gypsum + floor structure/subfloor). Interior
# partitions + ceilings ≈ 2.5-3× the footprint in board area; largely
# size-independent per unit floor.
_FLOOR_SHELL_KG_PER_M2 = 20.0

# Per m2 of ROOF area (footprint × pitch): asphalt shingles (ARMA 4.38) + roof
# framing/sheathing (AWC lumber/OSB) + attic insulation (NAIMA).
_ROOF_SHELL_KG_PER_M2 = 12.4

# Per m2 of gross WALL (envelope) area, by EXTWALL code: framed backup wall or
# structural masonry + cladding + wall insulation + a window allowance
# (0.15 WWR × 21 kgCO2e/m2 glazing ≈ 3.15). Framed light-cladding walls are a
# build-up from cited factors; the heavy-masonry rows (1/3/4) are anchored
# estimates (no clean open masonry takeoff exists) — the softest entries here.
_ENV_DEFAULT_KG_PER_M2WALL = 20.0
_ENV_KG_PER_M2WALL = {
    7:  15.9,   # frame / wood: framed wall ~8 + vinyl 4.71 + window allowance ~3.15
    5:  15.9,   # aluminum / vinyl (light frame)
    9:  38.2,   # brick veneer on frame: framed ~8 + brick 0.85×31.8 + windows ~3.15
    8:  21.4,   # stucco (cement plaster) — estimate
    10: 18.0,   # EIFS (synthetic stucco) — estimate
    1:  57.0,   # solid brick (structural, ~2 wythes) — anchored estimate
    3:  28.0,   # block / concrete / ICF — anchored estimate
    4:  54.0,   # stone — anchored estimate
}

# ── Reference home (used when a home's geometry is unknown) ───────────────────
# A typical ~2,500 sqft two-story home; picked so a geometry-unknown call returns a
# sensible mid-band intensity rather than a hard-coded table.
_FLOOR_REF_M2 = 232.0
_DEFAULT_STORIES = 1.0     # when stories is unknown (conservative: 1-story → more
                           # envelope + roof + foundation per m2 of floor)


def _to_int(code) -> int | None:
    try:
        return int(code)
    except (TypeError, ValueError):
        return None


def _to_float(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and f > 0 else None   # reject NaN / non-positive


def _footprint_and_perimeter(floor_area_m2: float, stories: float) -> tuple[float, float]:
    footprint = floor_area_m2 / max(stories, 1.0)
    perimeter = _SHAPE_C * math.sqrt(footprint)
    return footprint, perimeter


def _foundation_kgm2(floor_area_m2: float, footprint: float, perimeter: float,
                     bsmt_code: int | None, basement_depth_m: float | None) -> float:
    """Foundation embodied carbon per m2 of floor, from concrete volume × geometry.

    Slab-on-grade / basement floor slab + perimeter footings (always) + tall
    perimeter walls whose height is the actual basement depth (or a per-BSMT
    default) and whose extent is the per-BSMT wall fraction."""
    b = bsmt_code if bsmt_code in _WALL_FRAC else 1
    slab = footprint * _SLAB_THICK_M
    footing = perimeter * _FOOTING_W_M * _FOOTING_T_M
    depth = basement_depth_m if basement_depth_m is not None else _DEPTH_BY_BSMT.get(b, 0.0)
    walls = perimeter * depth * _WALL_THICK_M * _WALL_FRAC[b]
    concrete_m3 = slab + footing + walls
    return concrete_m3 * _RC_KG_PER_M3 / floor_area_m2


def embodied_intensity_kgm2(extwall_code=None, bsmt_code=None,
                            floor_area_m2=None, stories=None,
                            basement_depth_m=None) -> float:
    """Bottom-up cradle-to-gate (A1-A3) embodied intensity, kgCO2e per m2 of floor.

    Geometry-aware: foundation is built from the footprint slab + perimeter walls
    (× actual/estimated basement depth) + footings; the roof scales with roof area,
    the envelope with wall area, and interior finishes with floor area. When
    ``floor_area_m2`` is unknown the reference home's geometry is used; when
    ``stories`` is unknown a single story is assumed; when ``basement_depth_m`` is
    unknown a per-``BSMT``-code default depth is used. Grade / finish adjustments are
    applied by the caller (``environmental.embodied_intensity``), not here.
    """
    floor = _to_float(floor_area_m2) or _FLOOR_REF_M2
    st = _to_float(stories) or _DEFAULT_STORIES
    depth = _to_float(basement_depth_m)   # None if unknown → per-BSMT default
    w = _to_int(extwall_code)
    b = _to_int(bsmt_code)

    footprint, perimeter = _footprint_and_perimeter(floor, st)
    roof_area = footprint * _ROOF_PITCH_FACTOR
    wall_area = perimeter * _STORY_HEIGHT_M * st

    env_per_wall = (_ENV_KG_PER_M2WALL.get(w, _ENV_DEFAULT_KG_PER_M2WALL)
                    if w is not None else _ENV_DEFAULT_KG_PER_M2WALL)

    floor_term = _FLOOR_SHELL_KG_PER_M2 * floor
    roof_term = _ROOF_SHELL_KG_PER_M2 * roof_area
    env_term = env_per_wall * wall_area
    fdn_kgm2 = _foundation_kgm2(floor, footprint, perimeter, b, depth)

    shell_kgm2 = (floor_term + roof_term + env_term) / floor
    return round(shell_kgm2 + fdn_kgm2, 1)


# Default whole-home intensity when wall + foundation + geometry are all unknown;
# also the value ``environmental.embodied_intensity(None, None)`` returns.
EC_INTENSITY_DEFAULT = embodied_intensity_kgm2(None, None)
