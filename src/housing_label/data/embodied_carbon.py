"""Bottom-up embodied-carbon (A1-A3) intensities for US single-family homes.

Replaces the earlier hand-set wall-type band (a single 45 / 75 / 115 kgCO2e/m2
guess calibrated only to the Jungclaus et al. 2024 39-121 range, flagged LOW
CONFIDENCE) with a transparent build-up:

    intensity(wall, foundation) = SHELL[wall] + FOUNDATION[foundation]

where every term is a **published industry-average EPD result number x a
representative residential material takeoff**. Published EPD result figures are
citable facts (the PDF *layouts* carry copyright, the numbers do not), and US
federal documents are public domain -- so the resulting table is redistributable.
**No value here is sourced from EC3 or the CLF report** (both are
non-redistributable / account-gated and cannot be baked into an open repo).

Why split foundation from shell
-------------------------------
Across US single-family archetypes the **foundation is the single largest driver
of embodied carbon and its biggest source of variance** (Jungclaus et al. 2024):
a full basement embodies several times the concrete of a slab-on-grade. The old
wall-only band baked one implicit foundation into every home. Keying the
foundation term on the ``BSMT`` code (slab/crawl < partial < full basement) is
the most material accuracy gain available here.

Boundary & accounting
---------------------
Cradle-to-gate **A1-A3**, kgCO2e per m2 of gross floor area. Biogenic carbon nets
to zero across A1-A3 under ISO 21930 (the wood carbon removed in A1 is re-emitted
within the A1-A3 boundary), so **no biogenic credit is taken** -- wood is scored
on its fossil GWP only, consistent with the EPDs cited below.

Provenance
----------
Full factor-by-factor citation table (values, declared units, URLs, licenses) is
in ``research/embodied-carbon-research.md``. Sources in one line each:

  * Ready-mix concrete .... NRMCA member industry-avg EPD v3.2 (2022); GSA IRA
                            Low-Embodied-Carbon Concrete limits (Dec 2023, public domain)
  * Reinforcing steel ..... CRSI industry-wide EPD (2022), US EAF (~98% scrap)
  * Softwood lumber ....... American Wood Council N.A. Softwood Lumber EPD (2020)
  * Wood structural panels  AWC N.A. OSB EPD (2020); plywood proxied to OSB
  * Gypsum board .......... Gypsum Association cradle-to-gate LCA / EPD
  * Insulation ............ NAIMA industry-avg EPDs (fiberglass / mineral wool 2023)
  * Brick (clay) .......... Brick Industry Association industry-avg EPD (NSF EPD11101)
  * Vinyl siding .......... Vinyl Siding Institute industry-avg EPD (2022)
  * Asphalt shingles ...... ARMA asphalt-shingle-system industry-avg EPD (2024)
  * Glazing ............... National Glass Association flat-glass industry-avg EPD (2019)
  * Residential takeoff ... open-access CC-BY single-family bill-of-materials
                            (Frontiers in Built Environment 2024, 265 m2 archetype)
  * Sanity band ........... Jungclaus 2024 (39-121); RMI 2023 / BFCA EMBARC (~150-190),
                            both A1-A3 -- our build-up lands inside this range.

These are ESTIMATES: the material GWP factors are firm (industry-average EPDs),
but the takeoff quantities are representative (one published archetype, scaled),
so treat the output as a modeled intensity, not a per-home measurement. The
heavy-masonry shell values (solid brick / block-concrete-ICF / stone) are anchored
to whole-building masonry benchmarks rather than a per-material takeoff -- no clean
open masonry takeoff is published -- and are the weakest-supported entries here.
"""

from __future__ import annotations

# ── Per-material cradle-to-gate (A1-A3) GWP factors ──────────────────────────
# Each in the unit noted; see the research doc for the source EPD and exact figure.
_CONCRETE_KG_PER_M3   = 320.0    # kgCO2e/m3, representative 3000-4000 psi residential
                                 # mix (NRMCA v3.2 311-384; GSA typical ~318-352)
_REBAR_KG_PER_KG      = 0.854    # kgCO2e/kg, US EAF rebar (CRSI 854 kgCO2e/tonne)
_SOFTWOOD_KG_PER_M3   = 63.12    # kgCO2e/m3, softwood dimensional lumber (AWC)
_WOODPANEL_KG_PER_M3  = 242.58   # kgCO2e/m3, OSB (AWC); plywood proxied to this
_GYPSUM_KG_PER_M2     = 2.51     # kgCO2e/m2 of 1/2" board (Gypsum Assoc, 233 kg/MSF)
_CELLULOSE_KG_PER_KG  = 0.35     # kgCO2e/kg, blown cellulose (low-GWP; conservative)
_MINWOOL_KG_PER_KG    = 2.07     # kgCO2e/kg, mineral wool (NAIMA)
_VINYL_KG_PER_M2      = 4.71     # kgCO2e/m2 installed (Vinyl Siding Institute)
_BRICK_KG_PER_M2WALL  = 31.8     # kgCO2e/m2 of installed veneer wall (BIA)
_SHINGLE_KG_PER_M2    = 4.38     # kgCO2e/m2 of installed roof system (ARMA 2024)
_GLAZING_KG_PER_M2    = 21.0     # kgCO2e/m2 double-glazed IGU, glass only (NGA;
                                 # window frames excluded -> conservative)

# ── Representative residential takeoff (per m2 of gross floor area) ───────────
# From an open-access CC-BY itemized bill-of-materials for a 265 m2 US
# single-family home (Frontiers in Built Environment 2024). Foundation concrete
# below is the *full-basement* case; FOUNDATION_KGM2 scales it down for lighter
# foundations. All other rows are the shell (they don't vary with foundation).
_BOM_CONCRETE_M3_PER_M2 = 0.087   # -> full-basement foundation concrete
_BOM = {                          # shell materials: (quantity per m2, GWP factor)
    "rebar_kg":      (5.4,    _REBAR_KG_PER_KG),      # kg/m2
    "softwood_m3":   (0.113,  _SOFTWOOD_KG_PER_M3),   # m3/m2
    "plywood_m3":    (0.025,  _WOODPANEL_KG_PER_M3),  # m3/m2 (plywood ~ OSB)
    "osb_m3":        (0.0075, _WOODPANEL_KG_PER_M3),  # m3/m2
    "gypsum_m2":     (6.9,    _GYPSUM_KG_PER_M2),     # m2/m2
    "cellulose_kg":  (2.4,    _CELLULOSE_KG_PER_KG),  # kg/m2
    "minwool_kg":    (0.83,   _MINWOOL_KG_PER_KG),    # kg/m2
    "vinyl_m2":      (0.66,   _VINYL_KG_PER_M2),      # m2/m2 (cladding area)
    "shingle_m2":    (0.42,   _SHINGLE_KG_PER_M2),    # m2/m2
    "glazing_m2":    (0.13,   _GLAZING_KG_PER_M2),    # m2/m2
}
_CLADDING_AREA_M2_PER_M2 = 0.66   # exterior wall/cladding area per m2 floor (= vinyl row)

# Shell of a wood-frame, vinyl-clad home = sum of every non-foundation BOM row.
_FRAME_SHELL = round(sum(q * f for q, f in _BOM.values()), 2)          # ~47.2
_VINYL_CONTRIB = _BOM["vinyl_m2"][0] * _BOM["vinyl_m2"][1]             # cladding to swap out


def _reclad(delta_per_m2wall: float) -> float:
    """Frame shell with the vinyl cladding swapped for a different cladding of the
    given GWP per m2 of *wall* area."""
    return round(_FRAME_SHELL - _VINYL_CONTRIB
                 + _CLADDING_AREA_M2_PER_M2 * delta_per_m2wall, 1)


# ── Shell intensity (kgCO2e/m2 floor) by EXTWALL code ────────────────────────
# Light-frame variants are the bottom-up frame shell with the cladding swapped
# (fully sourced). The heavy-masonry rows (1/3/4) are anchored to whole-building
# masonry embodied benchmarks (upper Jungclaus / empirical band) because no clean
# open per-material masonry takeoff exists -- these are the softest entries.
DEFAULT_SHELL = 52.0
SHELL_KGM2_BY_WALL = {
    7:  _FRAME_SHELL,              # frame / wood (vinyl-clad) ~47.2
    5:  _FRAME_SHELL,              # aluminum / vinyl (light frame)
    9:  _reclad(_BRICK_KG_PER_M2WALL),   # brick veneer on frame ~65.1
    8:  52.0,                      # stucco (cement plaster) -- estimate, brackets vinyl<..<brick
    10: 49.0,                      # EIFS (synthetic stucco) -- estimate
    1:  82.0,                      # solid brick (structural + veneer) -- anchored estimate
    3:  72.0,                      # block / concrete / ICF -- anchored estimate
    4:  86.0,                      # stone -- anchored estimate
}

# ── Foundation intensity (kgCO2e/m2 floor) by BSMT code ──────────────────────
# Full basement = the archetype's concrete; lighter foundations scale down by the
# ratio of their concrete volume (a slab-on-grade uses far less concrete than a
# full basement's walls + footings + slab). Foundation is the dominant driver, so
# this split is where most of the home-to-home variance now lives.
_FULL_BASEMENT_FDN = round(_BOM_CONCRETE_M3_PER_M2 * _CONCRETE_KG_PER_M3, 1)   # ~27.8
DEFAULT_FOUNDATION = round(0.55 * _FULL_BASEMENT_FDN, 1)   # representative US mix ~15.3
FOUNDATION_KGM2 = {
    1: round(0.38 * _FULL_BASEMENT_FDN, 1),   # slab / crawl ~10.6
    2: round(0.60 * _FULL_BASEMENT_FDN, 1),   # partial basement ~16.7
    3: _FULL_BASEMENT_FDN,                     # full basement ~27.8
}

# Default whole-home intensity when both wall and foundation are unknown; also the
# value ``environmental.embodied_intensity(None, None)`` returns.
EC_INTENSITY_DEFAULT = round(DEFAULT_SHELL + DEFAULT_FOUNDATION, 1)


def _to_int(code) -> int | None:
    try:
        return int(code)
    except (TypeError, ValueError):
        return None


def embodied_intensity_kgm2(extwall_code=None, bsmt_code=None) -> float:
    """Bottom-up cradle-to-gate (A1-A3) embodied intensity, kgCO2e per m2 floor.

    ``extwall_code`` selects the shell (exterior-wall/structure) term; ``bsmt_code``
    selects the foundation term. Either may be ``None`` / unknown, in which case the
    representative default is used. Grade / finish adjustments are applied by the
    caller (``environmental.embodied_intensity``), not here.
    """
    w = _to_int(extwall_code)
    shell = SHELL_KGM2_BY_WALL.get(w, DEFAULT_SHELL) if w is not None else DEFAULT_SHELL
    b = _to_int(bsmt_code)
    fdn = FOUNDATION_KGM2.get(b, DEFAULT_FOUNDATION) if b is not None else DEFAULT_FOUNDATION
    return round(shell + fdn, 1)
