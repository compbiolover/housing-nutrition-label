# Housing Nutrition Label: Multi-Hazard Resilience Scoring Research

## Executive Summary

This document synthesizes research on how existing frameworks score disaster resilience for residential properties, with specific recommendations for building a 0–100 composite resilience score from three hazard pillars: flood risk (FEMA zones), tornado risk (historical frequency/proximity), and seismic risk (PGA values, soil amplification).

The dominant approach in the field is **Expected Annual Loss (EAL)** — converting each hazard into a dollar-denominated annual cost, then summing across hazards. This is what FEMA's National Risk Index, Hazus, and the insurance catastrophe modeling industry all use. It solves the "incommensurable risks" problem by putting everything in the same unit (dollars/year). For a consumer-facing label, the EAL can then be mapped to a 0–100 scale.

---

## 1. Landscape of Existing Frameworks

### FEMA National Risk Index (NRI)

The NRI is the most comprehensive public multi-hazard framework, covering 18 natural hazard types at the census-tract level.

**Core formula:**

```
Risk Index = EAL × Social Vulnerability × (1 / Community Resilience)
```

Where EAL for each hazard is:

```
EAL = Exposure × Annualized Frequency × Historic Loss Ratio
```

- **Exposure**: Dollar value of buildings, population (monetized at $13.7M per statistical life), and agriculture
- **Annualized Frequency**: Events per year (e.g., 100-year flood = 0.01/year)
- **Historic Loss Ratio**: Fraction of exposed value lost when event occurs (from SHELDUS database)

Multi-hazard aggregation: **simple summation** of individual hazard EALs, assuming statistical independence. The NRI applies a cube-root transformation to each hazard's EAL before summing to reduce skew from dominant hazards.

### FEMA Hazus

Hazus is a GIS-based loss estimation tool for earthquakes, floods, hurricanes, and tsunamis. Unlike the NRI (which uses simplified historic ratios), Hazus uses engineering-based damage functions.

**Earthquake model:**
- Input: Spectral acceleration or PGA at a site
- Process: Capacity curves (pushover analysis) → building response → fragility curves → damage state probabilities → loss ratios
- Fragility function: `P(DS ≥ ds | IM) = Φ[(1/β) × ln(IM / IM_median)]` (lognormal CDF)
- Four damage states: Slight (2–10% loss), Moderate (10–30%), Extensive (30–60%), Complete (60–100%)
- Building types: 36 model types × 4–5 seismic code eras = ~150+ unique damage functions

**Flood model:**
- Input: Peak water depth relative to first floor
- Process: Depth-damage curves (percentage of replacement cost at each depth from -2 to +16 ft)
- Less sensitive to construction type than seismic — elevation relative to BFE is the primary driver
- Depreciation model: Good/Average/Poor condition

**Multi-hazard combination:**
```
L_combined = L_hazard1 + L_hazard2 - (L_hazard1 × L_hazard2)
```
This treats hazards as independent and prevents double-counting when both affect the same property.

### First Street Foundation (Risk Factor)

Provides property-level 1–10 scores for flood, fire, wind, and heat — but **does not produce a composite score across hazard types**. Each hazard is scored independently.

**Flood Factor scoring basis:** Cumulative probability of ≥1 inch of flooding over 30 years, with depth weighting:
- Factor 1: <1% cumulative probability
- Factor 4: ~6% probability
- Factor 6: ~47% probability
- Factor 10: Near-certain deep flooding

**Key methodological features:**
- Incorporates climate change projections (RCP 4.5 scenario, 30-year forward)
- Uses Monte Carlo simulation (fire model runs millions of scenarios)
- Partners with Arup for building-level fragility curves
- Has faced accuracy criticism (21% agreement with independent UC Irvine model; Zillow removed scores from 1M+ listings in late 2025)

### CoreLogic Hazard Risk Score

- 0.1–100 scale at 10×10 meter grid resolution, covering 154M US properties
- Incorporates both probability/frequency AND loss contribution
- Accounts for property characteristics (construction year, first-floor height, stories, square footage)
- Aggregates across hazard types using proprietary "statistically valid combinations"
- Exact weighting methodology is proprietary

### FEMA Risk Rating 2.0 (Flood Insurance)

The updated NFIP pricing methodology that moved beyond simple zone-based pricing:
- Uses distance to water source, flood type, first-floor height, replacement cost
- Masonry structures receive lower premiums than wood-frame (~22% discount for elevated structures)
- Essentially prices flood risk as an individualized EAL

---

## 2. The Incommensurability Problem

Flood, tornado, and earthquake are fundamentally different:

| Characteristic | Flood | Tornado | Earthquake |
|---|---|---|---|
| **Frequency** | High (annual in flood zones) | Moderate (regional) | Low (decades–centuries) |
| **Severity per event** | Low–moderate | High (localized) | Very high (widespread) |
| **Spatial footprint** | Follows topography | Narrow path | Regional |
| **Warning time** | Hours–days | Minutes | None |
| **Duration** | Hours–weeks | Seconds–minutes | Seconds |
| **Risk profile** | Chronic/extensive | Acute/intensive | Acute/intensive |
| **Data quality** | Good (FEMA maps) | Moderate (historical) | Good (USGS hazard maps) |

### How the literature handles this

**Approach 1: EAL normalization (recommended).** Convert everything to $/year, then sum. This is the FEMA NRI approach and the insurance industry standard. It naturally handles the frequency–severity tradeoff because EAL = probability × consequence.

**Approach 2: Normalized index with weighting.** Normalize each hazard to 0–1, assign weights (equal, expert-derived via AHP, or data-driven), then compute weighted sum. Simpler but subjective.

**Approach 3: Max-of-hazards.** Final score = maximum individual hazard score. Conservative and transparent, avoids weight selection, but loses information about compound exposure.

**Approach 4: Multiplicative combination.** `L_combined = 1 - (1-L₁)(1-L₂)(1-L₃)`. Used by Hazus for combined wind-flood. Treats hazards as independent survival probabilities.

**Approach 5: Copula-based joint probability.** Models dependencies between hazards using copula functions. Mathematically rigorous but data-intensive; overkill for a consumer label.

**Academic consensus:** No universally agreed method exists. EAL summation with independence assumption is the pragmatic standard. The cube-root transformation (NRI approach) helps prevent one dominant hazard from swamping the composite score.

---

## 3. Expected Annual Loss as the Unifying Metric

### Why EAL works

EAL converts the fundamental risk equation into a common currency:

```
EAL = ∫₀^∞ P(Loss > L) dL
```

Or in discrete form:

```
EAL = Σ [(D_i + D_{i+1}) / 2 × (1/T_{i+1} - 1/T_i)]
```

Where D is damage at annual exceedance probability 1/T (trapezoidal integration under the loss exceedance curve).

Simplified (FEMA NRI approach):

```
EAL = Replacement_Value × Annual_Frequency × Loss_Ratio
```

### EAL by hazard type for Housing Nutrition Label

**Flood:**
```
EAL_flood = Replacement_Value × P(flood) × DamageRatio(depth, construction)
```
- P(flood) from FEMA zone: Zone A/AE ≈ 0.01/yr (1% annual chance); Zone X500 ≈ 0.002/yr; Zone X ≈ 0.001/yr or less
- DamageRatio from Hazus depth-damage curves (typically 10–50% depending on depth)

**Tornado:**
```
EAL_tornado = Replacement_Value × Σ [P(EF_rating) × DamageRatio(EF_rating)]
```
- P(EF_rating) from historical frequency within radius (e.g., EF2+ tornadoes per year per sq mile)
- DamageRatio by EF scale: EF0 ≈ 1–5%, EF1 ≈ 5–15%, EF2 ≈ 15–40%, EF3 ≈ 40–70%, EF4+ ≈ 70–100%

**Seismic:**
```
EAL_seismic = Replacement_Value × Σ [P(PGA_level) × DamageRatio(PGA, soil, construction)]
```
- P(PGA_level) from USGS hazard curves (probability of exceeding given PGA)
- Soil amplification: Multiply PGA by site amplification factor (Fa from NEHRP: 0.8–2.5× depending on soil class)
- DamageRatio from Hazus fragility curves for residential building types

### Composite:
```
EAL_total = EAL_flood + EAL_tornado + EAL_seismic
```

(Assuming independence — reasonable since flood, tornado, and earthquake are driven by different physical processes and rarely co-occur.)

---

## 4. Building Construction as a Modifier

### How frameworks handle it

Every major framework modifies hazard risk by construction type. The effect is substantial:

**Seismic vulnerability by construction and code era (Mean Damage Ratio at moderate PGA):**

| Construction Type | Pre-Code | Low Code | Moderate Code | High Code |
|---|---|---|---|---|
| Wood frame | 25–40% | 15–25% | 10–20% | 5–12% |
| Unreinforced masonry | 30–50% | 20–35% | — | — |
| Reinforced masonry | 15–30% | 10–20% | 8–15% | 4–10% |
| Reinforced concrete | 15–30% | 10–20% | 5–15% | 3–8% |
| Steel frame | 10–25% | 8–18% | 5–12% | 3–8% |

**Flood vulnerability modifiers:**
- Elevated foundation (≥BFE): 0.3–0.5× baseline damage
- Slab-on-grade: 1.0× (baseline)
- Basement: 1.3–1.5× baseline damage
- Masonry vs. wood: ~0.8× modifier

**Tornado/wind vulnerability modifiers:**
- Roof shape (hip vs. gable): Hip roof ≈ 0.7–0.8× damage
- Garage door (reinforced vs. standard): Significant for wind infiltration
- Window protection (shutters/impact glass): 0.7–0.8× modifier
- Roof-to-wall connection (hurricane straps): 0.6–0.8× modifier

### Practical construction modifier for Housing Nutrition Label

A simplified **Building Resilience Modifier (BRM)** on a 0.5–1.5 scale:

```
BRM = Base_Construction × Code_Era × Mitigation_Measures
```

| Factor | Value | Description |
|---|---|---|
| **Base construction** | | |
| Reinforced concrete/steel | 0.7 | Most resilient |
| Reinforced masonry | 0.8 | Good resilience |
| Wood frame (modern) | 1.0 | Baseline |
| Manufactured/mobile home | 1.4 | Most vulnerable |
| **Code era** | | |
| Post-2000 (modern code) | 0.8 | Best standards |
| 1975–2000 | 1.0 | Baseline |
| Pre-1975 | 1.2 | Older standards |
| Pre-1940 | 1.4 | No seismic/wind code |
| **Mitigation** | | |
| Elevated above BFE | 0.5 (flood only) | Major flood reduction |
| Hurricane straps | 0.8 (wind only) | Wind connection |
| Seismic retrofit | 0.6 (seismic only) | Soft-story fix |
| None | 1.0 | No mitigation |

Applied as: `Adjusted_EAL = EAL_raw × BRM`

---

## 5. Recommended Scoring Approach for Housing Nutrition Label

### Architecture: EAL-Based 0–100 Resilience Score

The score should represent resilience (higher = safer), making it intuitive for consumers.

#### Step 1: Calculate hazard-specific EAL

For a property with replacement value V:

**Flood EAL:**
```
EAL_flood = V × ZoneFrequency × DepthDamageRatio × FloodBRM
```

| FEMA Zone | Annual Frequency | Typical Depth-Damage Ratio |
|---|---|---|
| V/VE (coastal high hazard) | 0.01 | 0.30–0.50 |
| A/AE (100-year floodplain) | 0.01 | 0.15–0.30 |
| A (no BFE determined) | 0.01 | 0.15–0.30 |
| X (shaded/500-year) | 0.002 | 0.10–0.20 |
| X (unshaded/minimal) | 0.0005 | 0.05–0.10 |

**Tornado EAL:**
```
EAL_tornado = V × Σ [AnnualRate(EF_i) × DamageRatio(EF_i)] × WindBRM
```

Using historical tornado counts within specified radii:
- Convert count of EF0–EF5 tornadoes within radius over N years to annual rates
- Weight by damage ratio for each EF rating

| EF Rating | Damage Ratio | Typical Annual Rate (per sq mi, Tornado Alley) |
|---|---|---|
| EF0 | 0.03 | 0.001–0.01 |
| EF1 | 0.10 | 0.0005–0.005 |
| EF2 | 0.30 | 0.0001–0.001 |
| EF3 | 0.60 | 0.00005–0.0005 |
| EF4 | 0.85 | 0.00001–0.0001 |
| EF5 | 0.95 | 0.000001–0.00001 |

**Seismic EAL:**
```
EAL_seismic = V × Σ [P(PGA_i) × DamageRatio(PGA_i × SoilAmp)] × SeismicBRM
```

Using USGS hazard curves (probability of exceeding PGA levels):

| PGA (g) | Damage Ratio (wood frame, moderate code) | Return Period |
|---|---|---|
| 0.05 | 0.01 | ~100 yr |
| 0.10 | 0.03 | ~200 yr |
| 0.20 | 0.08 | ~500 yr |
| 0.40 | 0.20 | ~1000 yr |
| 0.60 | 0.35 | ~2500 yr |
| 0.80 | 0.50 | ~5000 yr |

Soil amplification factors (NEHRP):

| Site Class | Description | Amplification Factor (Fa) |
|---|---|---|
| A | Hard rock | 0.8 |
| B | Rock | 1.0 |
| C | Dense soil | 1.1–1.2 |
| D | Stiff soil | 1.2–1.6 |
| E | Soft soil | 1.5–2.5 |

#### Step 2: Sum to total EAL

```
EAL_total = EAL_flood + EAL_tornado + EAL_seismic
```

#### Step 3: Normalize to EAL Rate

```
EAL_Rate = EAL_total / V
```

This gives the annual expected loss as a fraction of property value (e.g., 0.002 = 0.2% of value per year).

#### Step 4: Map to 0–100 Resilience Score

Use a logarithmic mapping (because EAL spans orders of magnitude):

```
Score = 100 - (ln(EAL_Rate / EAL_min) / ln(EAL_max / EAL_min)) × 100
```

Or more practically, use percentile-based breakpoints calibrated against the national distribution:

| EAL Rate (% of value/year) | Resilience Score | Label |
|---|---|---|
| < 0.01% | 95–100 | Excellent |
| 0.01–0.05% | 80–94 | Very Good |
| 0.05–0.15% | 60–79 | Good |
| 0.15–0.40% | 40–59 | Moderate |
| 0.40–1.0% | 20–39 | Elevated Risk |
| 1.0–3.0% | 5–19 | High Risk |
| > 3.0% | 0–4 | Severe Risk |

**Why these thresholds:** A 0.1% EAL rate means losing 0.1% of property value per year to natural hazards — over a 30-year mortgage, that's ~3% of value in expected losses. At 1.0%/year, you'd expect to lose 30% of property value over a mortgage term. The breakpoints are calibrated so that the median US property scores around 75–85.

#### Step 5: Present pillar-level scores alongside composite

Following the "nutrition label" metaphor, show both:

```
OVERALL RESILIENCE SCORE: 72 / 100 (Good)

  Flood Risk:    82 / 100  (Very Good — Zone X, not in floodplain)
  Tornado Risk:  58 / 100  (Moderate — 12 historical tornadoes within 25mi)
  Seismic Risk:  91 / 100  (Excellent — low PGA, firm soil)

  Building Modifier: +5 pts (modern construction, post-2000 code)
```

### Alternative Simplified Approach (Without Full EAL)

If full EAL calculation is too complex for initial implementation, use a **normalized additive index**:

#### Per-hazard scoring (each 0–100):

**Flood sub-score:**

| FEMA Zone | Base Score |
|---|---|
| X (unshaded) | 95 |
| X (shaded/500-yr) | 75 |
| A/AE (100-yr, no BFE) | 40 |
| A/AE (100-yr, with BFE) | 35 |
| V/VE (coastal high hazard) | 15 |
| Floodway | 5 |

**Tornado sub-score:**

Based on annual tornado density (events per 1000 sq mi per year within radius):

| Annual Density | Base Score |
|---|---|
| 0–0.5 | 95 |
| 0.5–1.5 | 80 |
| 1.5–3.0 | 65 |
| 3.0–5.0 | 50 |
| 5.0–8.0 | 35 |
| 8.0+ | 20 |

Adjust by maximum EF rating observed: EF3+ within 10mi → subtract 10 pts; EF4+ → subtract 20 pts.

**Seismic sub-score:**

| PGA (g, 2% in 50yr) × Soil Amp | Base Score |
|---|---|
| 0–0.05 | 98 |
| 0.05–0.10 | 90 |
| 0.10–0.20 | 75 |
| 0.20–0.40 | 55 |
| 0.40–0.60 | 35 |
| 0.60+ | 15 |

#### Composite:

```
Composite = w_flood × Flood_Score + w_tornado × Tornado_Score + w_seismic × Seismic_Score
```

**Recommended weights** (based on national average loss contribution from NRI data):
- Flood: 0.40 (largest contributor to US residential losses)
- Seismic: 0.35 (high-consequence, even if low-frequency)
- Tornado: 0.25 (significant but more localized damage paths)

Then apply building modifier as ±5–15 points.

---

## 6. Defensibility and Transparency Recommendations

1. **Use EAL as the foundation.** It's what FEMA, the insurance industry, and academic literature converge on. It's defensible in peer review and regulatory contexts.

2. **Show your work.** The "nutrition label" metaphor demands transparency. Display each pillar's contribution and the building modifier separately, not just a single number.

3. **Cube-root transformation** (NRI approach) before summing prevents a single dominant hazard from overwhelming the composite. Consider this if one hazard type consistently dominates.

4. **Calibrate against known benchmarks.** Validate scores against FEMA NRI tract-level ratings, First Street scores (where available), and NFIP premium data. Properties in FEMA Zone V should score low; properties in low-seismicity Zone X areas should score high.

5. **Acknowledge limitations.** Tornado risk is inherently harder to quantify at the property level (path width is narrow, historical data is spatially sparse). Be transparent that tornado scoring has higher uncertainty.

6. **Building modifier should be optional/secondary.** Not all users will know their construction type. Make the score work without it (assume "typical" construction) and let the modifier refine it.

7. **Avoid false precision.** Report scores in 5-point increments or letter grades (A–F) rather than implying single-point accuracy. The underlying data doesn't support distinguishing a "67" from a "69."

8. **Time horizon matters.** First Street uses 30-year projections. For a housing label, current risk is most defensible; forward projections add value but also uncertainty. Consider showing both.

---

## 7. Key Sources

### Federal frameworks
- FEMA National Risk Index: https://hazards.fema.gov/nri
- FEMA NRI Expected Annual Loss methodology: https://hazards.fema.gov/nri/expected-annual-loss
- Hazus Earthquake Technical Manual: https://www.fema.gov/sites/default/files/2020-09/fema_hazus_earthquake-model_technical-manual_2.1.pdf
- Hazus Flood Technical Manual: https://www.fema.gov/sites/default/files/2020-09/fema_hazus_flood-model_technical-manual_2.1.pdf
- FEMA Risk Rating 2.0: https://www.fema.gov/sites/default/files/documents/FEMA_Risk-Rating-2.0_Methodology-and-Data-Appendix__01-22.pdf

### Industry
- First Street Foundation methodology: https://firststreet.org/methodology/flood
- CoreLogic Hazard Risk Solutions: https://www.corelogic.com/insurance/hazard-risk-solutions/
- RiskFootprint: https://riskfootprint.com/

### Academic
- "Towards multi-hazard and multi-risk indicators" (NHESS 2025): https://nhess.copernicus.org/articles/25/4263/2025/
- "The national risk index: establishing a nationwide baseline" (Natural Hazards 2022): https://link.springer.com/article/10.1007/s11069-022-05474-w
- "Global multi-hazard risk assessment in a changing climate" (Scientific Reports 2024): https://www.nature.com/articles/s41598-024-55775-2
- "A Building Classification System for Multi-hazard Risk Assessment": https://link.springer.com/article/10.1007/s13753-022-00400-x
- Multi-hazard risk assessment comparative evaluation: https://eprints.whiterose.ac.uk/id/eprint/86059/1/multi-hazard%20risk%20assessment-symplectic.pdf
