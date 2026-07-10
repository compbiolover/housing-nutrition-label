# Embodied-Carbon Data Pack — Bottom-Up, EPD-Grounded (Environmental Footprint)

> **What this backs:** `src/housing_label/data/embodied_carbon.py`, consumed by
> `enrich/environmental.py`. Replaces the earlier hand-set wall band
> (45 / 75 / 115 kgCO2e/m², flagged LOW CONFIDENCE, calibrated only to the
> Jungclaus 2024 39–121 range) with a transparent build-up from published
> industry-average EPD factors × a representative residential material takeoff.
> **Date:** 2026-07-10.

---

## Why the change

The old embodied leg mapped exterior-wall type to one of three guessed whole-house
intensities. It was the environmental dimension's weakest leg, and it baked one
implicit foundation into every home even though **the foundation is the single
largest driver of residential embodied carbon and its biggest source of variance**
(Jungclaus et al. 2024). The new model:

1. Sums **published industry-average EPD GWP factors** (facts, redistributable) ×
   a **representative residential takeoff** from an open-access CC-BY bill of
   materials.
2. Splits the estimate into a **foundation term** (keyed on `BSMT`) and a **shell
   term** (keyed on `EXTWALL`), so a slab home and a full-basement home no longer
   score identically.
3. Lands every wall × foundation combination inside the empirical A1–A3
   single-family band (~39–210 kgCO2e/m²), enforced by a test.

### Constraint compliance

Open, keyless, redistributable only. **No value is from EC3 or the CLF report** —
both are account-gated / non-redistributable and cannot be baked into an open repo
(EC3's Terms forbid redistributing derived data "as a standalone data product" on
*all* tiers; see `research/data-source-strengthening-research.md`). Published EPD
*result numbers* are citable facts (the PDF layouts carry ASTM/UL/NSF copyright, the
numbers do not); US-federal documents (GSA IRA) are public domain.

---

## Boundary & accounting

Cradle-to-gate **A1–A3**, kgCO2e per m² of gross floor area. Under ISO 21930
biogenic carbon nets to zero across A1–A3 (the wood carbon removed in A1 is
re-emitted within the boundary), so **no biogenic credit is taken** — wood is scored
on fossil GWP only, consistent with the wood EPDs.

---

## Layer 1 — Per-material A1–A3 GWP factors

| Material | Factor used | Declared source figure | Source | License |
|----------|-------------|------------------------|--------|---------|
| Ready-mix concrete | **320 kgCO2e/m³** | NRMCA v3.2: 311 (3000 psi) – 384 (4000 psi); GSA IRA typical 318–352 | NRMCA member industry-avg EPD v3.2 (2022); GSA IRA LEC Concrete Limits (Dec 2023) | Industry-avg / **US public domain** |
| Reinforcing steel (rebar) | **0.854 kgCO2e/kg** | 854 kgCO2e/tonne, US EAF (~98% scrap) | CRSI Industry-Wide EPD (2022) | Industry-avg |
| Softwood lumber | **63.12 kgCO2e/m³** | GWP-fossil A1–A3 | AWC/CWC N. American Softwood Lumber EPD (2020) | Industry-avg |
| Wood structural panels (OSB; plywood proxied) | **242.58 kgCO2e/m³** | OSB A1–A3 | AWC N. American OSB EPD (2020) | Industry-avg |
| Gypsum board (½") | **2.51 kgCO2e/m²** | 233 kgCO2e per 1,000 ft² (MSF = 92.9 m²) | Gypsum Association cradle-to-gate LCA / EPD | Industry-avg |
| Cellulose insulation | **0.35 kgCO2e/kg** | low-GWP blown cellulose (conservative) | general LCA literature | — |
| Mineral wool insulation | **2.07 kgCO2e/kg** | heavy-density board industry avg | NAIMA Mineral Wool Industry-Avg EPD (2023) | Industry-avg · *member-use restriction on the document; the number is a citable fact* |
| Vinyl siding | **4.71 kgCO2e/m²** | per m² installed | Vinyl Siding Institute Industry-Avg EPD (2022) | Industry-avg |
| Clay brick (veneer) | **31.8 kgCO2e/m² of wall** | per m² installed wall, A1–A3 baseline | Brick Industry Association Industry-Avg EPD (NSF EPD11101, 2024–25) | Industry-avg |
| Asphalt shingles | **4.38 kgCO2e/m²** | per m² installed roof system (2024 EPD) | ARMA Asphalt Shingle System Industry-Avg EPD (2024) | Industry-avg |
| Glazing | **21.0 kgCO2e/m²** | ~21 kgCO2e/m² double-glazed IGU, **glass only** (frames excluded → conservative) | National Glass Association Flat-Glass Industry-Avg EPD (2019) | Industry-avg |

---

## Layer 2 — Representative residential takeoff (per m² of floor area)

From an **open-access CC-BY** itemized bill of materials for a 265 m² US
single-family home — *Frontiers in Built Environment* (2024),
[DOI 10.3389/fbuil.2024.1384191](https://www.frontiersin.org/journals/built-environment/articles/10.3389/fbuil.2024.1384191/full).
Quantities per m² of floor area (as coded in `_BOM`):

| Material | Quantity /m² | → kgCO2e/m² |
|----------|-------------|-------------|
| Concrete (foundation) | 0.087 m³ | 27.8 *(full-basement case; scaled by `FOUNDATION_KGM2`)* |
| Rebar + misc steel | 5.4 kg | 4.6 |
| Softwood framing lumber | 0.113 m³ | 7.1 |
| Plywood (≈ OSB) | 0.025 m³ | 6.1 |
| OSB | 0.0075 m³ | 1.8 |
| Gypsum board ½" | 6.9 m² | 17.3 |
| Cellulose + mineral-wool insulation | 2.4 + 0.83 kg | 2.6 |
| Vinyl siding | 0.66 m² | 3.1 |
| Asphalt shingles | 0.42 m² | 1.8 |
| Windows (glazing) | 0.13 m² | 2.7 |

**Wood-frame shell** (all non-foundation rows) ≈ **47.2 kgCO2e/m²**.
**Foundation, full basement** ≈ **27.8 kgCO2e/m²**.

### Foundation scaling (`FOUNDATION_KGM2`, keyed on `BSMT`)

A full basement (walls + footings + slab) embodies far more concrete than a
slab-on-grade. Scaled off the archetype's full-basement value by concrete-volume
ratio:

| Foundation (`BSMT`) | Factor | kgCO2e/m² |
|---------------------|--------|-----------|
| slab / crawl (1) | 0.38× | 10.6 |
| partial basement (2) | 0.60× | 16.7 |
| full basement (3) | 1.00× | 27.8 |
| unknown (default) | 0.55× | 15.3 |

### Shell by wall type (`SHELL_KGM2_BY_WALL`, keyed on `EXTWALL`)

Light-frame variants are the frame shell with the cladding swapped (fully sourced).
Heavy-masonry rows are **anchored estimates** (no clean open per-material masonry
takeoff exists) bracketed by the empirical band — the weakest-supported entries here.

| `EXTWALL` | Type | Shell kgCO2e/m² | Basis |
|-----------|------|-----------------|-------|
| 7 | frame / wood | 47.2 | bottom-up BOM |
| 5 | aluminum / vinyl | 47.2 | = frame |
| 9 | brick veneer on frame | 65.1 | frame − vinyl + BIA brick (0.66 m² × 31.8) |
| 8 | stucco | 52.0 | estimate (vinyl < stucco < brick) |
| 10 | EIFS | 49.0 | estimate |
| 1 | solid brick | 82.0 | anchored to upper masonry band |
| 3 | block / concrete / ICF | 72.0 | anchored |
| 4 | stone | 86.0 | anchored |
| — | unknown (default shell) | 52.0 | — |

`intensity = SHELL[extwall] + FOUNDATION[bsmt]`, then `enrich/environmental.py`
applies the ±10% GRADE (finish-quality) nudge and amortizes over material service
life (60–100 yr).

---

## Layer 3 — Sanity band (whole-building A1–A3, single-family)

| Source | kgCO2e/m² | Notes |
|--------|-----------|-------|
| Jungclaus et al. 2024 (RMI/NREL/CU-Boulder) | **39–121** | 64 DOE-prototype homes, structure+enclosure (paywalled; abstract free) |
| RMI 2023 "Hidden Climate Impact of Residential Construction" | ~150–210 (avg ~184) | 921 model homes ([free](https://rmi.org/resources/hidden-climate-impact-of-residential-construction/)) |
| BFCA / PBC EMBARC | 154 (gross) / 189 (heated) | 503 as-built homes ([free PDF](https://www.buildersforclimateaction.org/uploads/1/5/9/3/15931000/bfca_pbc-embarc_report-web.pdf)) |

Theoretical structure+enclosure prototypes sit **~40–120**; empirical as-built homes
(with finishes) cluster **~150–190**. Our build-up (structure+enclosure+drywall+
insulation) spans **~58 (frame, slab) → ~114 (stone, full basement)** — squarely
inside the band, at the lower end as expected for a structure+enclosure boundary.

---

## Score impact (intentional, reviewed via the golden snapshot)

Relative to the old hand-set band, at the golden test's offline cases:

- **Conventional frame homes:** environmental score ↓ ~4–5 pts — the old band
  under-counted (foundation concrete + drywall are now included). Frame embodied
  sub-score ~93 → ~70.
- **ICF / passive homes:** environmental score ↑ ~7 pts — ICF's 100-yr service life
  now properly amortizes its higher upfront carbon, so durable construction is
  rewarded rather than penalized. (`icf_passive` composite 89.0 → 90.4.)
- **Worst-case homes:** ↓ more, as expected for low-grade construction.

This is an accuracy correction, not a re-weighting: the 0.50/0.30/0.20
operational/embodied/water composite weights are unchanged.

---

## Caveats & upgrade path

- The **material GWP factors are firm** (industry-average EPDs); the **takeoff
  quantities are representative** (one published archetype, scaled) — so this is a
  modeled intensity, not a per-home measurement.
- The archetype is a full-basement Midwest home; `FOUNDATION_KGM2` scales it to
  lighter foundations, but a per-home takeoff (BEAM / Athena run against the actual
  house) would be finer.
- **Heavy-masonry shell values (solid brick / block-concrete-ICF / stone) are the
  softest entries** — anchored to whole-building masonry benchmarks, not a
  per-material takeoff, because no clean open masonry takeoff is published.
- No US **industry-average whole-window/IGU** EPD exists; glazing uses NGA flat glass
  (glass only, frames excluded → conservative).

### License notes

- All Layer-1 numbers are industry-average EPD figures (citable facts) or US public
  domain (GSA IRA). The **NAIMA** insulation EPD carries a member-use restriction on
  the *document*; the average GWP number remains a citable fact.
- The Layer-2 takeoff is **CC BY 4.0** (Frontiers) — attribution given here and in
  the module docstring.
- Nothing here is share-alike, non-commercial, or no-derivatives. Nothing is from
  EC3 or CLF.
