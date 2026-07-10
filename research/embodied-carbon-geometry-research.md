# Embodied Carbon — Geometry-Aware Refinement (per-home takeoffs + basement depth)

> **What this backs:** the geometry-aware model in `src/housing_label/data/embodied_carbon.py`,
> consumed by `enrich/environmental.py`. Follow-up to `embodied-carbon-research.md`
> (the per-material EPD factors), implementing that doc's stated upgrade path:
> *"per-home BEAM/Athena takeoffs and actual basement depth."*
> **Date:** 2026-07-10. Constraint unchanged: open / keyless / redistributable only.

---

## What changed

The prior model summed EPD factors × a single fixed per-m²-of-floor takeoff from one
archetype, split into a shell (by wall type) + a foundation (by `BSMT` category). It
ignored home size, shape, and stories, and used categorical foundation constants.

The refinement computes each term from **the home's own geometry**:

```
intensity = ( foundation(footprint slab + perimeter walls × basement depth + footings)
            + roof(roof area)
            + envelope(wall area × wall type)
            + floor(floor area) ) / floor_area
```

Two published findings motivate it:

1. **Foundation is the single largest driver** of residential embodied carbon and its
   biggest source of variance (Jungclaus et al. 2024) — so foundation concrete is now
   computed from actual slab area + perimeter wall volume (× **actual or per-type
   basement depth**) + footings, rather than a flat category constant.
2. **Smaller and single-story homes carry higher embodied intensity per m²** — envelope
   + roof + foundation grow faster than floor area as a home shrinks (Rauf et al. 2025,
   CC-BY: 109 m² → 9.14 GJ/m² vs 525 m² → 6.77, ~35% higher for the small home). So the
   roof scales with roof area and the envelope with wall area, not floor area.

**License note:** the paywalled Jungclaus 2024 per-foundation-type multipliers are **not
used** — the foundation term is derived directly from concrete volumes × the (public
industry-average) NRMCA concrete EPD factor, keeping the whole model redistributable.

---

## Geometry constants (standard code / public relations)

| Constant | Value | Source |
|----------|-------|--------|
| Slab-on-grade / basement slab thickness | **0.10 m** (4") | IRC R506.2 |
| Foundation wall thickness | **0.20 m** (8") | IRC R404 / CMHA TEK 05-03A |
| Footing (continuous) | **0.40 m W × 0.15 m T** (16"×6") | IRC Table R403.1 |
| Full-basement wall height | **2.44 m** (8 ft) | IRC R404 tables |
| Partial-basement / deep-crawl depth | **1.5 m** | IRC R408 (crawl clearance) + engineering judgment |
| Perimeter from footprint | **P = 4.1·√A** | geometric: P = 2(1+r)/√r·√A, aspect ratio ~1.3–2.0 (public domain; corroborated by RSMeans/Swift area→perimeter estimators) |
| Story height (gross) | **2.7 m** | standard 8–9 ft framing (IRC R305) |
| Roof area factor | **1.12 × footprint** | 6:12 pitch trig factor (public domain) |
| Window-to-wall ratio | **0.15** | typical residential |
| Foundation reinforcement | **40 kg steel/m³ concrete** | modest residential (CRSI rebar EPD for GWP) |

Foundation concrete volume by `BSMT` code (1 = slab/crawl, 2 = partial, 3 = full):
slab (footprint × 0.10) + footings (perimeter × 0.40 × 0.15) always; tall perimeter
walls (perimeter × depth × 0.20) scaled by a wall fraction {slab 0, partial 0.6,
full 1.0}, with **depth taken from an explicit `basement_depth_ft` when supplied**,
else the per-type default. Concrete → GWP via NRMCA 320 kgCO₂e/m³ + 40 kg/m³ rebar
(CRSI 0.854 kgCO₂e/kg) = **354 kgCO₂e/m³ reinforced**.

## Shell assembly intensities

| Term | Value | Scales with | Build-up |
|------|-------|-------------|----------|
| Floor (interior gypsum + floor structure) | 20.0 kgCO₂e/m² floor | floor area | Gypsum Assoc. + AWC |
| Roof (shingles + framing + attic insul.) | 12.4 kgCO₂e/m² roof | footprint × pitch | ARMA + AWC + NAIMA |
| Envelope (framed/masonry wall + cladding + windows) | per m² wall, by wall type | perimeter × height × stories | see below |

Envelope per m² of wall area, by `EXTWALL`: frame/vinyl 15.9 · brick-veneer 38.2 ·
stucco 21.4 · EIFS 18.0 · block/concrete/ICF 28.0 · solid brick 57.0 · stone 54.0.
Frame variants build up from cited factors (framed wall ~8 + cladding + 0.15·21
window allowance); the **heavy-masonry rows (solid brick / block / stone) are anchored
estimates** — no clean open masonry takeoff exists — and are the softest entries.

Per-material scaling bases follow the **BEAM** (Builders for Climate Action, open)
method — quantities derived from plan dimensions — and Athena residential BOMs; only
BEAM/public figures are used for values (Athena's LCI is non-redistributable and was
not embedded).

## Sanity band (whole-building A1–A3, single-family)

Jungclaus 2024 **39–121** (theoretical, structure+enclosure); RMI 2023 / BFCA EMBARC
**~150–210** (as-built, with finishes; individual homes up to 561). The model spans
**~55 (compact 2-story slab wood) → ~210 (small masonry over a full basement)** — inside
the band, at the lower end for a structure+enclosure boundary. A test asserts every
wall × foundation × size × story combination lands in 38–260 kgCO₂e/m².

---

## Companion recalibration (embodied sub-score breakpoints)

Because the geometry model counts the full foundation, intensities are systematically
higher and wider than the prior model. The embodied sub-score breakpoints were
therefore **re-anchored** from `[40, 60, 80, 100, 120]` to `[55, 95, 135, 175, 210]`
kgCO₂e/m² (→ 100…0). Without this, every home would bunch at the low-scoring end and
the refinement would read as a uniform ~11-point drop. With it, a **typical home's score
is essentially unchanged** while the score now **discriminates by geometry**.

## Score impact (intentional; golden snapshot regenerated)

Net change vs the prior merged model is small for typical homes, with new geometry
sensitivity layered in:

| Case | env (prior → now) |
|------|-------------------|
| baseline (frame, slab) | 65.1 → 65.3 |
| icf-passive | 85.9 → 89.1 |
| fortified-gold | 69.1 → 69.3 |
| worst-case | 36.3 → 33.5 |

New per-home sensitivity (2000 sqft frame): 1-story slab 67.2 · 2-story slab 70.7 ·
1-story full basement 57.0 · full basement at 3 m depth 54.6.

New optional inputs (simulator): `--stories` and `--basement-depth-ft`. When unknown,
stories defaults to **1** (conservative — more foundation + roof per m² of floor) and
basement depth to the per-foundation-type default. Providing them improves accuracy.

---

## Caveats & upgrade path

- Material GWP factors are firm; **geometry constants are standard code values**; the
  **assembly allocations and heavy-masonry wall factors are representative estimates** —
  a modeled intensity, not a per-home measurement.
- The **stories default (1)** materially affects a home whose stories are unknown; the
  web/API path can surface a stories input to make this per-home rather than defaulted.
- Perimeter uses a shape factor (C≈4.1); an actual footprint polygon (e.g. from FEMA
  USA Structures) would remove the shape assumption.

### License / provenance
All geometry constants are standard code values (facts) or public geometric relations;
Rauf 2025 is CC-BY (size curve); BEAM is open; RMI/BFCA reports are free to cite. The
Jungclaus 2024 figure data (paywalled) is **not** embedded — only its qualitative
"foundation is dominant" finding, which the geometry model reproduces from first
principles. Nothing from EC3, CLF, Athena LCI, or RSMeans proprietary constants.
