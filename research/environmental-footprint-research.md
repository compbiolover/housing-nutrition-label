# Environmental Footprint Dimension — Research & Methodology

**Status:** Research complete; ready to implement as `enrich/environmental.py`.
**Scope:** Per-parcel environmental footprint for Shelby County, TN residences across three
components — **embodied carbon**, **operational carbon emissions**, and **water use** —
computed from CAMA building characteristics + location + the existing energy estimates.

This document is grounded in a multi-source, adversarially fact-checked research pass
(25 primary/secondary sources, 113 candidate claims, 19 confirmed and 6 killed by a
3-vote refutation gate). Numbers that **failed** verification are flagged explicitly so we
do not build on them.

---

## 0. Design principle

Match the project's existing pattern: a rigorous-but-simplified, **published-benchmark**
model (like the ResStock-based energy dimension), producing a 0–100 score with national +
local grades. Everything here is computable from data we already have on each parcel.

The cleanest rigorous framing is to express all three legs as an **annual CO₂e flow**
(kg CO₂e/yr), then normalize to 0–100 — but also keep three transparent sub-scores so the
nutrition label can show *where* a home's footprint comes from.

---

## 1. Operational carbon emissions  — STRONGEST leg (best data)

We already compute `est_annual_kwh` and `est_annual_therms` per parcel. Convert to CO₂e
with authoritative emission factors:

```
operational_co2e_kg/yr = est_annual_kwh × EF_grid  +  est_annual_therms × EF_gas
```

| Factor | Value | Source | Verified |
|--------|-------|--------|----------|
| `EF_grid` (electricity) | **933.1 lb CO₂/MWh = 0.423 kg CO₂e/kWh** — eGRID **SRTV** subregion (SERC Tennessee Valley), the correct subregion for Memphis/TVA | EPA eGRID2022 summary tables | ✅ 3–0 |
| `EF_gas` (natural gas) | **5.3 kg CO₂e/therm** (0.0053 t CO₂/therm + minor CH₄/N₂O) | EPA GHG Emission Factors Hub / Equivalencies Calculator | ✅ 3–0 |
| GWP basis | 100-yr GWPs, IPCC AR4/AR5 | EPA methodology | ✅ 2–1 |

**Location-based vs market-based / TVA nuance (verify-flagged).** TVA *self-reports* a
2023 system rate of ~625 lb CO₂/MWh — far below the eGRID SRTV 933.1. The claim that
"TVA's rate is significantly lower than eGRID" was **refuted (1–2)** because the two are
not apples-to-apples: eGRID SRTV is the standard **location-based** subregion factor and
covers all generation in the footprint, not just TVA-owned assets.
→ **Use eGRID SRTV 933.1 lb/MWh as the primary (location-based) factor.** Optionally
report a market-based variant using TVA's self-reported rate. Treat the factor as a
**dated constant** (eGRID is updated ~annually and the grid is decarbonizing) — store the
eGRID vintage in a `*_data_source` column and refresh on each release.

---

## 2. Embodied carbon  — WEAKEST leg (sparse US residential data)

The research's clearest finding: **US single-family residential embodied-carbon data is
genuinely thin**, and published benchmarks vary by an order of magnitude depending on which
LCA stages and assemblies are counted. Treat this leg as *indicative*, not precise.

**Defensible benchmark range:** **~39–121 kgCO₂e/m²** for US single-family detached homes
(Jungclaus et al. 2024, *Sustainable Cities and Society*; verified ✅). This is the band to
calibrate to for a CAMA-driven estimate.

**Refuted — do NOT use:**
- ❌ "Low-rise residential initial embodied carbon < 500 kgCO₂e/m²" — **0–3 refuted**. That
  figure is a *commercial/whole-building* CLF benchmark, not residential; applying it would
  overstate residential embodied carbon ~4–10×.
- ❌ "Embodied carbon outweighs operational for ~120 years on clean grids" — **1–2 refuted**.
  For typical existing homes on the current TVA grid, **operational carbon still dominates**.
  → Operational must remain the heavier-weighted leg; do not let embodied dominate the score.

**Standards & tools (named for the upgrade path):** ISO 14040/14044 (LCA framework),
EN 15978 / RICS Whole Life Carbon (building-level method, default 60-yr reference study
period), the ICE database (material factors), EC3 / Building Transparency (product-level
EPDs), **BEAM** (Builders for Climate Action — the most residential-appropriate free
estimator), and the CLF North America Building LCA dataset (verified as the main open US
dataset, but residential coverage is sparse).

**CAMA-driven estimator (what we can actually compute):**

```
embodied_total_kg = EC_intensity(EXTWALL, GRADE) × floor_area_m²
embodied_annualized_kg/yr = embodied_total_kg / RSP        # RSP = 60 yr (EN 15978/RICS default)
```

Map `EXTWALL` to an intensity within the verified 39–121 band (wood frame sequesters carbon
and sits low; masonry/concrete sit high):

| EXTWALL | Class | EC intensity (kgCO₂e/m²) |
|---------|-------|--------------------------|
| 7 frame / 5 vinyl-alum | light frame | ~45 |
| 9 brick veneer / 8 stucco / 10 EIFS | veneer/clad | ~75 |
| 1 brick / 3 block / 4 stone | solid masonry/concrete | ~115 |

`GRADE` (construction quality) adds a small ±10% modifier (higher grade ⇒ more/heavier
finishes ⇒ more embodied). Annualizing over a 60-yr RSP makes embodied directly comparable
to operational CO₂e. **Flag this leg's low confidence in the output and the docs.**

---

## 3. Water use  — moderate data; locally favorable

**Consumption benchmark (EPA WaterSense, verified):**
- Average US household ≈ **300 gal/day** total at home; conventional homes much higher than
  efficient ones. WaterSense-labeled new homes use **≥20–30% less**. ✅ 3–0
- Indoor ≈ ~70% of total; outdoor ≈ ~30% nationally (humid Mid-South ⇒ lower outdoor share).

**Verify-flagged:** the precise REU2016 (Water Research Foundation) figures — "138 gphd
indoor / 58.6 gpcd" and the exact end-use breakdown (toilet 24%, shower 20%, …) — were
**refuted (1–2)** on the specific numbers. Use the **EPA WaterSense** headline figures as the
anchor and cite REU2016 only for the *qualitative* end-use ranking.

**CAMA-driven estimator:**
```
indoor_gal/yr  = occupancy × gpcd_base × fixture_factor(FIXBATH)
                 occupancy ≈ RMBED + 1   (bedroom→occupant proxy)
outdoor_gal/yr = irrigable_area × regional_irrigation_rate
                 irrigable_area ≈ (CALC_ACRE − building_footprint)
total_water_gal/yr = indoor + outdoor
```

**Embedded water-energy → carbon, with a strong LOCAL twist (verified):** Memphis draws
artesian drinking water from the **Memphis Sand aquifer**, which needs minimal treatment —
so the embedded energy (and thus embedded carbon) per gallon is **unusually low** versus
surface-water or desalination regions (CAESER / USGS sources). Compute embedded carbon as
`water_gal × embedded_kWh_per_gal × EF_grid`, using a low Memphis-specific embedded-energy
rate. **Water-stress context:** the aquifer is abundant but faces over-pumping and
contamination-breach concerns (USGS, CAESER) — worth a note in the label, even though
per-gallon carbon is low.

---

## 4. Scoring → 0–100 and composite

Two compatible options; **recommend running both representations**:

**(a) Total annual CO₂e (most LCA-consistent).**
```
total_co2e_kg/yr = operational_co2e + embodied_annualized + water_embedded_co2e
```
Normalize **per m²** (so big and small homes compare fairly) via log-linear breakpoints, in
the same style as the energy/infrastructure dimensions. Anchor breakpoints to a regional
median single-family home (lower kgCO₂e/m²/yr = higher score).

**(b) Three sub-scores + weighted composite (nutrition-label-friendly).**
Each leg → 0–100 against its benchmark, then:
```
environmental_score = 0.50·operational + 0.30·embodied + 0.20·water
```
Weighting rationale (supported by the verification results): operational is the dominant,
best-measured leg ⇒ heaviest; embodied is real but data-weak ⇒ moderate; water is
locally low-carbon ⇒ lightest (but still reported). **Do not** life-cycle-weight embodied
above operational — the "embodied dominates" claim was refuted for this grid.

Reference methodologies for normalization: **LBNL Home Energy Score** (asset-rating
0–10/0–100 against a reference distribution; verified), RIBA 2030 Climate Challenge and One
Click LCA carbon benchmarking (benchmark-band approach).

Emit, per parcel: `env_operational_co2e`, `env_embodied_co2e_annual`, `env_water_gal`,
`env_water_co2e`, `env_total_co2e`, three sub-scores, `environmental_score`, and
`environmental_data_source` (carrying the eGRID vintage + low-confidence embodied flag).

---

## 5. Data gaps & upgrade path

**Cannot be known from CAMA alone:** actual metered kWh/therms/gallons; real appliance/HVAC
efficiencies; insulation/air-tightness; actual materials & quantities (the embodied driver);
irrigation behavior; PV/green-power participation (market-based emissions).

**Main uncertainty:** embodied carbon (sparse US residential benchmarks, assembly-level
unknowns) >> water (behavioral variance) > operational (already modeled, factors solid).

**Rigorous upgrade path:**
1. **Operational:** replace modeled kWh/therms with metered MLGW utility data; refresh eGRID
   annually; add a market-based factor from TVA green-power / Green Invest.
2. **Embodied:** run a real LCA — **BEAM** (residential-first, free) or Athena Impact
   Estimator / One Click LCA — keyed on assembly takeoffs; or join the CLF North America LCA
   dataset by archetype. Replace the EXTWALL band with EC3 EPD-backed material factors.
3. **Water:** parcel-level irrigation from remote sensing (NDVI / impervious-surface change);
   MLGW water-billing data; local embedded-energy from MLGW pumping/treatment records.

---

## Sources (verified primary unless noted)

- EPA eGRID2022 summary tables — grid emission factors (SRTV). `epa.gov/system/files/documents/2024-01/egrid2022_summary_tables.pdf`
- EPA GHG Emission Factors Hub / Equivalencies Calculator — natural gas factor, GWPs. `epa.gov/.../ghg_emission_factors_hub.pdf`
- Jungclaus et al. 2024, *Sustainable Cities and Society* — US single-family embodied carbon 39–121 kgCO₂e/m². `sciencedirect.com/science/article/abs/pii/S2210670724007996`
- Carbon Leadership Forum — Embodied Carbon Benchmark; EC3 tool; CLF NA LCA dataset. `carbonleadershipforum.org`
- Builders for Climate Action — BEAM / embodied-vs-operational ("120-yr" claim refuted). `buildersforclimateaction.org`
- Nature *Scientific Data* 2025 — US residential building LCA dataset. `nature.com/articles/s41597-025-05216-0`
- EPA WaterSense — statistics & how-we-use-water (300 gal/day, ≥20% savings). `epa.gov/watersense`
- Water Research Foundation REU2016 — end-use ranking (specific gphd numbers refuted). `waterrf.org/.../residential-end-uses-water-version-2`
- AWWA Residential End Uses of Water. `awwa.org`
- Water Energy Innovations — embedded energy in water. `waterenergyinnovations.com`
- CAESER (U. Memphis) & USGS — Memphis Sand aquifer, low treatment energy, water-stress. `caeser.memphis.edu/resources/memphis-aquifer/`, `usgs.gov/.../aquifers-memphis-area-tennessee`
- LBNL Home Energy Score methodology; RIBA 2030 Climate Challenge; One Click LCA benchmarking — scoring/normalization. `hes-documentation.lbl.gov`, `riba.org`, `oneclicklca.com`
