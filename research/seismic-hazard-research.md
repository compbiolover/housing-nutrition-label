# Seismic Hazard — True Return-Period PGA (USGS 2023 NSHM)

> **What this backs:** `src/housing_label/enrich/seismic_lookup.py`. Implements the
> strategy memo's seismic fix: replace the constant `0.43` 10%/50yr ÷ 2%/50yr ratio
> with true return-period ground motions read directly off the USGS 2023 National
> Seismic Hazard Model. **Date:** 2026-07-10. Constraint: open / keyless.

---

## The problem

The seismic leg of Disaster Resilience integrates a **two-point hazard curve** — the
PGA at 2%-in-50-yr (~2475-yr return) and 10%-in-50-yr (~475-yr return) — mapped to
damage ratios (HAZUS fragility) to get an expected annual loss. The lookup fetched
the 2%/50yr value from the USGS **ASCE7 design-maps** service and then **faked the
10%/50yr as `0.43 × the 2%/50yr`** — a single national constant.

That constant is materially wrong. The true 10%/2% ratio varies strongly by region
(the hazard curves have different shapes in the stable interior vs. the active West):

| Site | true 2%/50yr | true 10%/50yr | true ratio | old `×0.43` 10%/50yr |
|------|-------------|---------------|-----------|----------------------|
| Boston | 0.248 g | 0.075 g | **0.30** | 0.107 g |
| Memphis | 0.753 g | 0.273 g | **0.36** | 0.324 g |
| Los Angeles | 0.879 g | 0.446 g | **0.51** | 0.378 g |
| San Francisco | 0.790 g | 0.465 g | **0.59** | 0.340 g |

The constant over-stated the 10%/50yr in the stable interior and understated it on
the West Coast — directly biasing the seismic EAL.

## The fix

Read **both** return-period ground motions off the actual PGA hazard curve for the
point, from the **USGS 2023 NSHM hazard-curve web service** (keyless):

```
GET https://earthquake.usgs.gov/ws/nshmp/conus-2023/dynamic/hazard/{lon}/{lat}/760
```

- **Keyless**, path form (longitude first), `vs30=760` m/s = the BC-boundary reference
  site condition used by the national hazard maps. `conus-2023` 302-redirects to the
  versioned release (requests follows it).
- Response: `response.hazardCurves[i]` where `imt.value == "PGA"`, component `"Total"`,
  giving `values.xs` (ground motion, g, ascending) and `values.ys` (annual frequency
  of exceedance, per year, descending).
- Interpolate the ground motion at each return period's **annual rate** in log-log
  space:
  * 2%/50yr → λ = −ln(1−0.02)/50 ≈ **4.04e-4 /yr**
  * 10%/50yr → λ = −ln(1−0.10)/50 ≈ **2.11e-3 /yr**

Both targets always fall inside the curve's rate range (`ys[0]≈0.9` down to `ys[-1]≈1e-8`),
so interpolation always brackets; the helper clamps to the curve ends as a guard.

### Fallbacks (the `0.43` ratio survives only here)

1. **USGS ASCE7 design-maps** (2%/50yr MCEG) × `0.43` — for Alaska / Hawaii /
   territories (outside the CONUS NSHM bounds) or an NSHM outage.
2. **Bundled PGA grid** × `0.43` — offline (the grid CSV isn't currently shipped, so
   this is a no-op; offline the CLI simulator falls back to its legacy New Madrid
   model instead).

CONUS bounds are checked locally because the service does **not** cleanly reject
offshore/out-of-region points.

## Coverage, models, reliability

- Models: `conus-2023` (used), plus `conus-2018`, `alaska-2023`, `hawaii-2021`,
  `prvi-2025`. This PR uses CONUS; non-CONUS points take the design-maps fallback.
- Keyless, ~0.7–1.5 s latency, ~750 KB payload (all 23 IMTs; we extract PGA/Total).
  Results are `@lru_cache`d per rounded lat/lon.
- USGS is public domain. `nshmp-haz` v2 service, current as of 2026.

## Score impact (live path only)

**Offline is unchanged** — offline `get_pga` returns None and the simulator uses its
New Madrid model, so the golden snapshot is unaffected (verified).

On the **live** path, seismic-active addresses now carry a more accurate (and
generally higher) seismic EAL, for two reasons: (a) the true 10%/50yr replaces the
`0.43` approximation, and (b) the true **uniform-hazard** 2%/50yr replaces the
risk-targeted design MCEG — which is the correct input for a loss integration (design
MCE_R is deterministically capped and risk-targeted for code design, not EAL). For a
live Memphis address, e.g., 2%/50yr moves 0.48 → ~0.75 g and 10%/50yr 0.21 → 0.27 g.
This is an accuracy correction; the HAZUS fragility (PGA→damage) is a physical
relationship, so feeding it the true hazard gives the true loss — no re-calibration.

## Caveats & further work

- `vs30=760` is the national-map reference; it is not the site's actual Vs30 (unknown
  without a soil map). In the stable interior the choice barely matters (Memphis 760
  vs 1080 differ by <0.3%); in the West it matters more (LA 0.879 vs 0.754).
- Non-CONUS (AK/HI/PR) still uses the design-maps + ratio fallback — those NSHM models
  (`alaska-2023`, `hawaii-2021`, `prvi-2025`) could be wired in later.
- A bundled 2-value PGA grid built from the NSHM data release would let the **offline**
  path use true return periods too (today offline uses the New Madrid model).
