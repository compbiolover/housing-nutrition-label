# Housing Nutrition Label: Above-Code Feature Modifiers

## Evidence-Based Damage Reduction Research

*Compiled from IBHS, FEMA, USACE, PEER-CEA, and insurance loss studies*
*Date: April 2, 2026*

---

## How to Read This Document

Each feature includes:
- **Damage reduction %** from best available source
- **Recommended modifier** (multiplier where 1.0 = code minimum, lower = less damage)
- **Hazard scope** (wind, seismic, flood, or multi-hazard)
- **Evidence quality** (Strong / Moderate / Expert Estimate)
- **Source citation**

Modifiers are designed for multiplicative stacking within a hazard category. A house with hip roof (0.55), sealed roof deck (0.70), and hurricane straps (0.75) would have a combined wind modifier of 0.55 x 0.70 x 0.75 = 0.29 (71% reduction) before capping.

---

## IBHS FORTIFIED Home Program (Benchmark Reference)

The FORTIFIED program is the best-researched tiered above-code system. Your Housing Nutrition Label tiers should map roughly to these.

### Tier Definitions

| Tier | Focus | Key Requirements |
|------|-------|------------------|
| **FORTIFIED Roof** | Roof system only | Sealed roof deck, 8d ring-shank nails at 6" OC (4" at gable ends), Class F/H shingles (110/150 mph), enhanced edge/soffit details |
| **FORTIFIED Silver** | Roof + openings + walls | All Roof requirements + impact-rated windows/doors, wind-rated garage doors, reinforced gable ends, chimney anchoring |
| **FORTIFIED Gold** | Full continuous load path | All Silver requirements + engineer-stamped continuous load path from roof to foundation |

### Actuarial Loss Data (Hurricane Sally 2020, n=40,000+ homes in coastal Alabama)

| Metric | FORTIFIED Roof | FORTIFIED Gold |
|--------|---------------|----------------|
| Claim frequency reduction | 73% | 76% |
| Claim severity reduction (avg claim $) | 15% | 24% |
| Loss ratio reduction | 72% | 67% |
| Water intrusion reduction | Up to 95% | Up to 95% |

### Insurance Premium Discounts (Proxy for Actuarial Risk Assessment)

| State | FORTIFIED Roof | FORTIFIED Silver | FORTIFIED Gold |
|-------|---------------|-----------------|----------------|
| Alabama | 25-35% | 35-45% | 45-55% |
| Mississippi | Up to 35% | Up to 45% | Up to 55% |
| Louisiana | ~22% average | — | — |
| Oklahoma | Up to 42% (wind+hail) | — | — |
| South Carolina | Up to 50%+ (wind) | — | — |

### Recommended FORTIFIED-Equivalent Composite Modifiers

```
FORTIFIED_ROOF_MODIFIER  = 0.35  // 65% combined loss reduction
FORTIFIED_SILVER_MODIFIER = 0.25  // 75% combined loss reduction (estimated)
FORTIFIED_GOLD_MODIFIER  = 0.20  // 80% combined loss reduction
```

**Sources:**
- IBHS, "Study Shows IBHS's FORTIFIED Program Reduced Hurricane Sally Damage" (2021)
- Alabama Department of Insurance, "Performance of IBHS FORTIFIED Home Construction in Hurricane Sally" (2021)
- FORTIFIED Home Program (fortifiedhome.org)

---

## WIND/TORNADO FEATURES

### 1. Hurricane Straps/Clips (Continuous Load Path)

| Attribute | Value |
|-----------|-------|
| **Damage reduction** | 25-35% (insurance premium proxy); prevents catastrophic roof-to-wall separation |
| **Recommended modifier** | **0.75** |
| **Hazard scope** | Wind only |
| **Evidence quality** | Moderate |

**Evidence:** IBHS wind tunnel testing showed a conventionally-built house failed at just over 100 mph (EF-0 to EF-1 equivalent), while a house with continuous load path (FORTIFIED Gold) withstood significantly higher speeds. FEMA MAT reports consistently document roof-to-wall connection failure as a primary wind damage mechanism. Simpson Strong-Tie connections create a continuous load path from roof to foundation.

**Key distinction:** Toe-nailed connections (code minimum in many jurisdictions) fail at much lower loads than engineered metal connectors. Hurricane clips provide moderate uplift resistance; full continuous load path (clips + hold-downs + anchor bolts) provides the maximum benefit.

```
HURRICANE_CLIPS_MODIFIER = 0.75   // clips only
CONTINUOUS_LOAD_PATH_MODIFIER = 0.60  // full engineered system
```

**Sources:** IBHS Continuous Load Path Research; FEMA P-804 Wind Retrofit Guide; Building America Solution Center

### 2. Reduced Truss/Rafter Spacing (16" OC vs 24" OC)

| Attribute | Value |
|-----------|-------|
| **Damage reduction** | Not directly quantified in published studies |
| **Recommended modifier** | **0.92** (expert estimate) |
| **Hazard scope** | Wind + general structural |
| **Evidence quality** | Expert Estimate |

**Evidence:** No published studies directly compare 16" vs 24" OC spacing for wind damage outcomes. Engineering principles confirm that closer spacing distributes loads over more members, reducing per-member stress. FORTIFIED Gold requires roof framing at 24" OC or less with 7/16" OSB minimum, treating 24" as the acceptable maximum rather than the target. The benefit is primarily in preventing localized sheathing failures between supports.

```
TRUSS_16OC_MODIFIER = 0.92  // modest benefit, well-established engineering principle
```

**Sources:** APA Engineered Wood Guidelines; IBHS FORTIFIED Gold standards

### 3. Ring-Shank/Deformed-Shank Nails vs Smooth Shank

| Attribute | Value |
|-----------|-------|
| **Damage reduction** | 2x withdrawal resistance (approximately 50% reduction in nail pull-through failures) |
| **Recommended modifier** | **0.70** |
| **Hazard scope** | Wind only |
| **Evidence quality** | Strong |

**Evidence:** Ring-shank nails have approximately double the withdrawal resistance of smooth-shank nails in mechanical testing. IBHS states ring-shank nails "almost double the strength of a roof against winds." FEMA requires ring-shank nails in areas with design wind speeds over 110 mph. The FORTIFIED Roof standard mandates 8d ring-shank nails (0.113" diameter, 2-3/8" long) at 6" OC in field and 4" OC at gable ends.

**Combined with spacing:** The interaction of ring-shank nails + tighter spacing is greater than either alone. FORTIFIED's 6"/4" OC ring-shank specification represents the combined best practice.

```
RING_SHANK_NAILS_MODIFIER = 0.70   // ring-shank at code spacing
RING_SHANK_PLUS_TIGHT_SPACING_MODIFIER = 0.55  // ring-shank at 6"/4" OC (FORTIFIED spec)
```

**Sources:** IBHS FORTIFIED Roof Standards; FEMA P-2181 Fact Sheet 3.3.1; Florida Building Code

### 4. Hip Roof vs Gable Roof

| Attribute | Value |
|-----------|-------|
| **Damage reduction** | 45-50% reduction in peak wind pressure loads |
| **Recommended modifier** | **0.55** |
| **Hazard scope** | Wind only |
| **Evidence quality** | Strong |

**Evidence:** IBHS wind tunnel testing demonstrates that hip roofs experience 45-50% lower wind pressures than gable roofs under identical conditions. The aerodynamic advantage is dramatic: gable ends present large flat surfaces perpendicular to wind, creating high suction pressures. Hip geometry eliminates this vulnerability. Insurance companies offer up to 32% premium discount for hip roof configuration alone.

This is one of the single highest-leverage design decisions for wind resistance.

```
HIP_ROOF_MODIFIER = 0.55       // vs gable as baseline (1.0)
GABLE_ROOF_MODIFIER = 1.00     // baseline
GABLE_BRACED_MODIFIER = 0.80   // gable with proper bracing (see #6)
```

**Sources:** IBHS Research Center wind tunnel testing; U.S. DOE Building America Program; Insurance industry rating data

### 5. Impact-Rated Garage Doors

| Attribute | Value |
|-----------|-------|
| **Damage reduction** | 30% insurance premium reduction; garage door failure initiates 80% of residential wind damage |
| **Recommended modifier** | **0.70** |
| **Hazard scope** | Wind only |
| **Evidence quality** | Strong |

**Evidence:** FEMA documents that 80% of residential hurricane wind damage initiates through garage door failure. When garage doors survive, 90% of homes had no structural roof damage (FEMA data). Failure mechanism: garage door breach allows internal pressurization, doubling effective wind loads on roof and walls, causing blowout. FORTIFIED Silver requires wind-rated garage doors meeting ASCE 7 design pressures (Vasd=110 mph or Vult=140 mph).

This is the single highest-leverage retrofit for homes with attached garages.

```
IMPACT_GARAGE_DOOR_MODIFIER = 0.70
STANDARD_GARAGE_DOOR_MODIFIER = 1.00  // major vulnerability point
```

**Sources:** FEMA "Against the Wind" guidance; IBHS FORTIFIED Silver standards; Florida Alliance for Safe Homes

### 6. Reinforced Gable Ends

| Attribute | Value |
|-----------|-------|
| **Damage reduction** | Not directly quantified in published studies |
| **Recommended modifier** | **0.80** (for gable roofs only; N/A for hip roofs) |
| **Hazard scope** | Wind only |
| **Evidence quality** | Moderate |

**Evidence:** FEMA extensively documents gable-end wall collapse as a major failure mode in hurricanes. Bracing transfers wind forces to the roof/ceiling system, distributing loads over a larger area. FORTIFIED Silver requires structural sheathing with bracing for out-of-plane wind loads on gable ends >4 feet tall. No published percentage reduction, but the feature is a mandatory FORTIFIED Silver requirement, suggesting substantial actuarial benefit.

```
GABLE_BRACING_MODIFIER = 0.80  // applies only to gable roofs
```

**Sources:** FEMA P-804 Wind Retrofit Guide; FEMA P-2181 Fact Sheet 3.3.1; IBHS FORTIFIED Silver standards

### 7. Sealed Roof Deck (Secondary Water Barrier)

| Attribute | Value |
|-----------|-------|
| **Damage reduction** | Up to 95% water intrusion prevention after shingle loss |
| **Recommended modifier** | **0.70** |
| **Hazard scope** | Wind (water intrusion component) |
| **Evidence quality** | Strong |

**Evidence:** IBHS duplex testing showed the sealed side prevented water entry entirely, while the unsealed side had water streaming from light fixtures, saturated drywall/insulation, ruined furniture, and ceiling collapse. This is a mandatory FORTIFIED Roof requirement. The sealed roof deck does not prevent shingle loss but prevents the catastrophic secondary water damage that accounts for a large portion of total hurricane losses. Peel-and-stick underlayment seals joints and self-seals around fastener penetrations.

```
SEALED_ROOF_DECK_MODIFIER = 0.70  // massive reduction in water-intrusion losses
```

**Sources:** IBHS "A Brief History of IBHS Sealed Roof Deck Research" (2020); IBHS FORTIFIED Roof standards

### 8. Roof Covering Type

| Attribute | Value |
|-----------|-------|
| **Damage reduction** | Metal roof: 20-30 mph wind rating advantage over asphalt; Architectural shingles: 10 mph advantage over 3-tab |
| **Recommended modifiers** | See below |
| **Hazard scope** | Wind only |
| **Evidence quality** | Strong |

**Evidence:**

| Covering Type | Wind Rating | Post-Hurricane Damage Rate | Modifier |
|--------------|-------------|---------------------------|----------|
| 3-tab shingles | 130 mph (Class F) | >80% damaged (Hurricane Michael) | 1.00 |
| Architectural shingles | 140 mph (Class H) | ~50% damaged (Hurricane Harvey) | 0.85 |
| Metal roof (standing seam) | 140-160 mph | Significantly lower damage rates | 0.65 |

Note: Installation quality matters enormously. IBHS found north-facing winter installations of 3-tab shingles failed at 110 mph or lower.

```
THREE_TAB_MODIFIER = 1.00
ARCHITECTURAL_SHINGLE_MODIFIER = 0.85
METAL_ROOF_MODIFIER = 0.65
```

**Sources:** IBHS "Wind Uplift of Asphalt Shingles" (2017); IBHS Post-Hurricane Harvey/Michael investigations

### 9. (See General section - Roof Pitch)

---

## SEISMIC FEATURES

### 10. Anchor Bolt Spacing (Tighter Than Code)

| Attribute | Value |
|-----------|-------|
| **Damage reduction** | Qualitative benefit; prevents house sliding off foundation |
| **Recommended modifier** | **0.90** (expert estimate) |
| **Hazard scope** | Seismic only |
| **Evidence quality** | Moderate |

**Evidence:** Code requires maximum 6' spacing (4' for high seismic/multi-story). Tighter spacing prevents sill plate splitting observed extensively in the 1994 Northridge earthquake. PEER research indicates retrofitted homes save $10,000-$200,000 in repair costs from proper bolting. No published percentage reduction for spacing alone (typically studied as part of complete retrofit package). The California Earthquake Brace+Bolt program treats bolting as one component of a combined retrofit.

```
TIGHT_ANCHOR_BOLT_MODIFIER = 0.90  // seismic damage component only
```

**Sources:** FEMA sill plate documentation; NACHI Foundation Anchor Bolt guidance; PEER research

### 11. Cripple Wall Bracing

| Attribute | Value |
|-----------|-------|
| **Damage reduction** | 40-70% reduction in average annual earthquake losses (varies by exterior finish) |
| **Recommended modifier** | **0.45** |
| **Hazard scope** | Seismic only (raised foundation homes) |
| **Evidence quality** | Strong |

**Evidence:** PEER-CEA (Pacific Earthquake Engineering Research Center / California Earthquake Authority) multi-year research project quantified effectiveness:
- Wood siding homes: up to 70% reduction in average annual losses
- Stucco-finished homes: less than 40% reduction

FEMA P-1024 and P-1100 provide prescriptive retrofit solutions. Caltech researchers established 50% loss reduction as the cost-effectiveness threshold. Cripple wall collapse is the dominant failure mode for pre-1980 raised-foundation houses. This is the single highest-leverage seismic retrofit.

```
CRIPPLE_WALL_BRACING_MODIFIER = 0.45  // average of 40-70% range; applies only to raised foundation homes
```

**Sources:** PEER-CEA Woodframe Project; FEMA P-1024; FEMA P-1100; California Earthquake Brace+Bolt Program

### 12. Hold-Down Connectors at Shear Wall Ends

| Attribute | Value |
|-----------|-------|
| **Damage reduction** | 213% increase in peak load capacity (928 lbs without vs 2,907 lbs with); 88% stiffness increase |
| **Recommended modifier** | **0.75** |
| **Hazard scope** | Seismic + wind |
| **Evidence quality** | Strong (engineering testing) |

**Evidence:** Published testing shows hold-downs increase wall stiffness (up to 88%), capacity (213% increase), and ductility (up to 83%) of shear wall assemblies. Building codes require Hold-down Effect Factor (Jhd) to reduce design shear strength when anchorages are used instead of hold-downs, implicitly acknowledging the performance gap. Advanced systems (resilient slip friction connectors) provide damage-free self-centering behavior.

```
HOLD_DOWN_CONNECTOR_MODIFIER = 0.75
```

**Sources:** MDPI Buildings (2022), "Contemporary Hold-Down Solutions for Mass Timber"; Springer Bulletin of Earthquake Engineering (2022)

### 13. Flexible Gas Lines

| Attribute | Value |
|-----------|-------|
| **Damage reduction** | 75% reduction in gas leakage; 100% elimination of rigid pipe break-and-ignition |
| **Recommended modifier** | **0.90** (fire component only) |
| **Hazard scope** | Seismic (post-earthquake fire) |
| **Evidence quality** | Strong |

**Evidence:** Approximately 1 in 4 post-earthquake fires are gas-related. Flexible corrugated stainless steel tubing (CSST) bends without breaking during ground movement. Published study of urban district earthquake gas pipeline risks found 75% decrease in leakage probability and 100% elimination of break-and-ignition risk vs rigid piping.

```
FLEXIBLE_GAS_LINE_MODIFIER = 0.90  // applies to fire-after-earthquake component
```

**Sources:** ScienceDirect, "Gas Pipeline Risk Assessment Study"; FEMA Flexible Connections Documentation; Earthquake Country Alliance

### 14. Automatic Gas Shutoff Valve

| Attribute | Value |
|-----------|-------|
| **Damage reduction** | Prevents large gas spills with zero human intervention; activates at ~5.4+ Richter |
| **Recommended modifier** | **0.92** (fire component only) |
| **Hazard scope** | Seismic (post-earthquake fire) |
| **Evidence quality** | Moderate |

**Evidence:** UL-tested and approved. Mandatory for new construction in California Bay Area since ~2000. Uses mechanical trigger (steel ball on tapered support) requiring no power. Prevents fatal gas leaks, fires, and explosions. Note: Less effective than flexible lines for moderate shaking (prevents accumulation but doesn't prevent initial release). Most effective when combined with flexible lines.

```
AUTO_GAS_SHUTOFF_MODIFIER = 0.92  // fire-after-earthquake component
FLEXIBLE_LINES_PLUS_SHUTOFF_MODIFIER = 0.85  // combined
```

**Sources:** Building America Solution Center; Southern California Gas Company; California building codes

---

## FLOOD FEATURES

### 15. Elevation Above BFE

| Attribute | Value |
|-----------|-------|
| **Damage reduction** | See curve below - massive nonlinear benefit |
| **Recommended modifiers** | See table |
| **Hazard scope** | Flood only |
| **Evidence quality** | Strong |

**Evidence:** FEMA and USACE depth-damage functions are the gold standard. The relationship is highly nonlinear: the first foot above BFE provides enormous benefit because it eliminates losses from the most frequent flood events.

| Elevation Relative to BFE | Annual Expected Loss Reduction | NFIP Premium Reduction | Recommended Modifier |
|---------------------------|-------------------------------|----------------------|---------------------|
| At BFE (0 ft) | Baseline | Baseline | 1.00 |
| +1 foot | ~93% | ~30% | 0.15 |
| +2 feet | ~96% | ~50% | 0.08 |
| +3 feet | ~97% | ~65% | 0.05 |
| +4 feet | ~98% | ~75% | 0.04 |

The 93% reduction at +1 foot is from research published in Frontiers in Earth Science on residential flood risk. NFIP premium reductions of ~30% per foot are from Risk Rating 2.0 methodology.

**Critical note:** These modifiers apply to the flood damage component only. A home elevated 2 feet above BFE still faces wind damage from the same storm.

```
ELEVATION_MODIFIERS = {
  0: 1.00,   // at BFE
  1: 0.15,   // +1 foot
  2: 0.08,   // +2 feet
  3: 0.05,   // +3 feet
  4: 0.04,   // +4 feet
}
```

**Sources:** Frontiers in Earth Science, "Homeowner Flood Risk and Risk Reduction from Home Elevation" (2023); FEMA Risk Rating 2.0; FEMA Benefit-Cost Analysis Technical Guide

### 16. Flood Vents in Foundation Walls

| Attribute | Value |
|-----------|-------|
| **Damage reduction** | ~83% insurance premium reduction; prevents catastrophic foundation failure from hydrostatic pressure |
| **Recommended modifier** | **0.60** |
| **Hazard scope** | Flood only (enclosed foundation homes) |
| **Evidence quality** | Moderate |

**Evidence:** FEMA Technical Bulletin 1 requires flood openings sized at 1 sq inch per sq foot of enclosed area. Proper flood vents equalize hydrostatic pressure, preventing foundation wall collapse. The 83% figure comes from insurance premium reductions post-installation. Without vents, hydrostatic pressure differential can collapse foundation walls, causing total structural failure.

Applies only to homes with enclosed foundations (crawlspace, enclosed pier). Slab-on-grade homes do not benefit.

```
FLOOD_VENT_MODIFIER = 0.60  // for enclosed foundation homes in flood zones
```

**Sources:** FEMA Technical Bulletin 1 (Flood Openings); FEMA Technical Bulletin 11 (Crawlspace Construction)

### 17. Backflow Prevention Valve

| Attribute | Value |
|-----------|-------|
| **Damage reduction** | 99.9-100% effective (automatic flood gate valves); prevents sewer backup damage |
| **Recommended modifier** | **0.85** |
| **Hazard scope** | Flood (sewer backup component) |
| **Evidence quality** | Strong |

**Evidence:** Automatic flood gate valves stop backwater under 45+ feet of head pressure with 100% effectiveness after closure. 90% of households installing backwater valves reported decreased water-related events. South Portland ME program (89 homes) experienced zero sewer backup damage after 10+ inches of rain following installation.

Average sewer backup claim: ~$14,000. A single inch of sewer water can cause up to $25,000 in damage. Modifier is modest because sewer backup is one component of total flood loss.

```
BACKFLOW_VALVE_MODIFIER = 0.85  // sewer backup component of flood loss
```

**Sources:** FEMA mitigation guidance; City of South Portland program data; Insurance claims data

### 18. Water-Resistant Materials Below BFE

| Attribute | Value |
|-----------|-------|
| **Damage reduction** | Eliminates replacement cost for interior finishes after flood (cleaning vs gutting) |
| **Recommended modifier** | **0.75** |
| **Hazard scope** | Flood only |
| **Evidence quality** | Moderate |

**Evidence:** FEMA Technical Bulletin 2 (updated January 2025) classifies materials as "Acceptable" or "Unacceptable" for use below BFE. Standard drywall and carpet require complete removal and replacement after any saturation. Flood-resistant alternatives (concrete, ceramic tile, pressure-treated lumber, metal, epoxy coatings) can be cleaned and reused.

The damage reduction is primarily in recovery cost and time, not structural integrity. A home with flood-resistant materials below BFE can be restored to pre-flood condition much faster and cheaper. FEMA does not publish a specific percentage, but the difference between "gut rehab" and "hose out and dry" is substantial.

```
FLOOD_RESISTANT_MATERIALS_MODIFIER = 0.75  // below-BFE interior finishes
```

**Sources:** FEMA Technical Bulletin 2 (Flood Damage-Resistant Materials, January 2025); Building America Solution Center

---

## GENERAL / MULTI-HAZARD FEATURES

### 19. Window Protection

| Protection Type | Damage Reduction | Modifier | Evidence |
|----------------|-----------------|----------|----------|
| No protection | Baseline | 1.00 | — |
| Plywood shutters (properly installed) | ~60-70% (estimated) | 0.80 | Moderate |
| Commercial hurricane shutters | Prevents envelope breach | 0.65 | Strong |
| Impact-rated glazing (hurricane windows) | 87% structural damage reduction; 65% fewer claims | 0.45 | Strong |

**Evidence:** Florida Building Code compliance data shows impact-rated windows produce 87% less structural damage and 65% fewer insurance claims vs unprotected openings. The mechanism: window breach allows internal pressurization, which doubles effective roof uplift forces and causes structural failure. IBHS finds 95% of water intrusion can be prevented by maintaining envelope integrity. Insurance premium reductions of 10-45% for impact-rated windows.

Critical caveat on plywood: 99% of plywood installations do NOT follow code-approved techniques, dramatically reducing real-world effectiveness. Half-inch plywood can be penetrated at impact speeds below 27 mph.

```
NO_WINDOW_PROTECTION_MODIFIER = 1.00
PLYWOOD_SHUTTERS_MODIFIER = 0.80       // assumes proper installation
COMMERCIAL_SHUTTERS_MODIFIER = 0.65
IMPACT_RATED_WINDOWS_MODIFIER = 0.45   // highest-performing option
```

**Sources:** Florida Building Code; IBHS FORTIFIED Silver standards; Miami-Dade County product testing (TAS 201/202/203); FEMA P-804

### 20. Roof Pitch

| Attribute | Value |
|-----------|-------|
| **Damage reduction** | Up to 50% reduction in uplift loads at optimal pitch; 23% higher probability of no sheathing failure at 23 degrees vs 18 degrees |
| **Recommended modifiers** | See table |
| **Hazard scope** | Wind only |
| **Evidence quality** | Strong |

**Evidence:** Wind tunnel testing and CFD modeling confirm a nonlinear relationship between roof pitch and wind performance. At approximately 30 degrees (~7:12 pitch), net roof pressure transitions from uplift-dominated to pressure-dominated. Steeper pitches shed wind more effectively, with optimal performance around 5:12 to 7:12 (22-30 degrees). Very steep pitches (>45 degrees) begin to present more windward surface area.

| Pitch | Approximate Angle | Modifier |
|-------|-------------------|----------|
| 3:12 or lower | <14 degrees | 1.05 (penalty: increased uplift) |
| 4:12 | 18 degrees | 1.00 (baseline) |
| 5:12 | 22 degrees | 0.90 |
| 6:12 | 27 degrees | 0.80 |
| 7:12 | 30 degrees | 0.75 |
| 8:12+ | >34 degrees | 0.75 (diminishing returns) |

```
ROOF_PITCH_MODIFIERS = {
  "3:12_or_less": 1.05,
  "4:12": 1.00,
  "5:12": 0.90,
  "6:12": 0.80,
  "7:12_or_steeper": 0.75,
}
```

**Sources:** ScienceDirect aerodynamic research; ASCE 7 wind load standards; IBHS research

---

## QUICK REFERENCE: ALL MODIFIERS

### Wind Hazard Modifiers

| # | Feature | Modifier | Evidence |
|---|---------|----------|----------|
| 1 | Hurricane clips (only) | 0.75 | Moderate |
| 1b | Full continuous load path | 0.60 | Moderate |
| 2 | 16" OC truss spacing | 0.92 | Expert Est. |
| 3 | Ring-shank nails (code spacing) | 0.70 | Strong |
| 3b | Ring-shank nails + 6"/4" OC | 0.55 | Strong |
| 4 | Hip roof (vs gable baseline) | 0.55 | Strong |
| 5 | Impact-rated garage door | 0.70 | Strong |
| 6 | Reinforced gable ends | 0.80 | Moderate |
| 7 | Sealed roof deck | 0.70 | Strong |
| 8a | Architectural shingles (vs 3-tab) | 0.85 | Strong |
| 8b | Metal roof (vs 3-tab) | 0.65 | Strong |
| 19a | Plywood shutters | 0.80 | Moderate |
| 19b | Commercial shutters | 0.65 | Strong |
| 19c | Impact-rated windows | 0.45 | Strong |
| 20 | Roof pitch 7:12 (vs 4:12 baseline) | 0.75 | Strong |

### Seismic Hazard Modifiers

| # | Feature | Modifier | Evidence |
|---|---------|----------|----------|
| 10 | Tight anchor bolt spacing | 0.90 | Moderate |
| 11 | Cripple wall bracing | 0.45 | Strong |
| 12 | Hold-down connectors | 0.75 | Strong |
| 13 | Flexible gas lines | 0.90 | Strong |
| 14 | Auto gas shutoff valve | 0.92 | Moderate |
| 13+14 | Both gas features combined | 0.85 | Strong |

### Flood Hazard Modifiers

| # | Feature | Modifier | Evidence |
|---|---------|----------|----------|
| 15 | +1 ft above BFE | 0.15 | Strong |
| 15 | +2 ft above BFE | 0.08 | Strong |
| 15 | +3 ft above BFE | 0.05 | Strong |
| 16 | Flood vents (enclosed foundation) | 0.60 | Moderate |
| 17 | Backflow prevention valve | 0.85 | Strong |
| 18 | Flood-resistant materials below BFE | 0.75 | Moderate |

---

## IMPLEMENTATION NOTES

### Stacking Rules

Wind modifiers should stack multiplicatively but with a floor. Suggested approach:

```python
def calculate_wind_modifier(features):
    modifier = 1.0
    for feature in features:
        modifier *= feature.modifier
    return max(modifier, 0.15)  # floor at 85% reduction
```

### Interaction Effects

Some features have synergistic interactions:
- **Sealed roof deck + ring-shank nails**: The deck keeps water out even if shingles fail; the nails keep shingles attached longer. Combined effect exceeds multiplicative stacking.
- **Impact windows + garage door**: Both prevent envelope breach. If both are present, internal pressurization risk is nearly eliminated.
- **Hip roof + any other wind feature**: Hip geometry reduces all wind loads, amplifying the effectiveness of connection and covering upgrades.
- **Cripple wall bracing + anchor bolts**: For raised-foundation homes, both are needed; either alone provides incomplete protection.

### Applicability Flags

Some modifiers only apply to certain home types:

```python
CRIPPLE_WALL_BRACING  # only raised foundation homes
FLOOD_VENTS           # only enclosed foundation homes
GABLE_BRACING         # only gable roof homes (N/A for hip)
IMPACT_GARAGE_DOOR    # only homes with attached garages
ELEVATION_ABOVE_BFE   # only homes in mapped flood zones
```

### Mapping to FORTIFIED Tiers

For homes with FORTIFIED certification, use the composite modifier instead of stacking individual features:

```python
if home.fortified_certification:
    if home.fortified_tier == "Roof":
        wind_modifier = 0.35
    elif home.fortified_tier == "Silver":
        wind_modifier = 0.25
    elif home.fortified_tier == "Gold":
        wind_modifier = 0.20
else:
    wind_modifier = calculate_from_individual_features(home)
```

---

## SOURCE BIBLIOGRAPHY

### IBHS / FORTIFIED
- IBHS, "Study Shows IBHS's FORTIFIED Program Reduced Hurricane Sally Damage" (2021), ibhs.org
- IBHS, "Continuous Load Path Research," ibhs.org/wind/continuous-load-path-clp/
- IBHS, "A Brief History of IBHS Sealed Roof Deck Research" (2020), ibhs.org
- IBHS, "Wind Uplift of Asphalt Shingles" (April 2017)
- IBHS, "Building Performance in SW Florida during Hurricane Ian" (2022)
- IBHS, "Hurricane Michael Demonstrates the Power of Resilience" (2018)
- FORTIFIED Home Program, fortifiedhome.org

### FEMA
- FEMA P-804, "Wind Retrofit Guide for Residential Buildings" (2023)
- FEMA P-2181, Fact Sheet 3.3.1: Roof Systems for Sloped Roofs
- FEMA P-1024, "Earthquake Strengthening of Cripple Walls in Wood Frame Dwellings"
- FEMA P-1100, "Vulnerability-Based Seismic Assessment and Retrofit of One- and Two-Family Dwellings"
- FEMA Technical Bulletin 1, "Requirements for Flood Openings in Foundation Walls"
- FEMA Technical Bulletin 2, "Flood Damage-Resistant Materials Requirements" (January 2025)
- FEMA Technical Bulletin 11, "Crawlspace Construction"
- FEMA Risk Rating 2.0 Methodology
- FEMA Benefit-Cost Analysis Technical Guide

### Academic / Research
- Frontiers in Earth Science, "Homeowner Flood Risk and Risk Reduction from Home Elevation" (2023)
- PEER-CEA Woodframe Project, peer.berkeley.edu
- MDPI Buildings, "Contemporary Hold-Down Solutions for Mass Timber" (2022)
- Springer Bulletin of Earthquake Engineering, "Ductile Hold-Down Research" (2022)
- ScienceDirect, Gas Pipeline Risk Assessment in Urban Districts

### Insurance / Regulatory
- Alabama Department of Insurance, "Performance of IBHS FORTIFIED Home Construction in Hurricane Sally" (2021)
- Alabama Code Title 27-31D (Insurance Discounts for FORTIFIED)
- California Earthquake Authority, Earthquake Brace+Bolt Program
- Florida Building Code, Impact Protection Requirements
- Miami-Dade County, TAS 201/202/203 Product Testing Standards

### Industry
- Building America Solution Center, basc.pnnl.gov
- Simpson Strong-Tie, continuous load path systems
- Federal Alliance for Safe Homes (FLASH), flash.org
