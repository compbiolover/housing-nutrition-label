# Building vs Location sub-scores

**Status:** research / recommendation. No code changed.
**Date:** 2026-08-04
**Question:** should the label replace one blended composite with two sub-scores — building quality and location — and if so, how should the thirteen dimensions be assigned, aggregated, graded and guarded?

---

## 0. Recommendation in one page

**Split it. But not into the two buckets the request assumes, and not with the arithmetic the composite uses today.**

Concretely:

1. **Three display groups, two of them graded.**

   | Group | Dimensions | Graded? |
   |---|---|---|
   | **The building** | `energy`, `durability`, `environmental` | yes |
   | **The location** | `resilience`, `infrastructure`, `air_quality`, `noise`, `walkability`, `climate`, `solar`, `water` | yes |
   | **About the people nearby** | `health`, `socioeconomic` | shown, **not** aggregated, **not** graded |

2. **`infrastructure` moves out of the building bucket.** It is currently in `CONSTRUCTION_DRIVEN` and it is the single biggest reason the product owner's motivating example fails today. See §2.4 and the measured numbers in §1.3.

3. **`resilience` is the one true 50/50 hybrid** and must eventually be *decomposed*, not assigned. The engine can already do this — `eal_rate_to_score(sum of raw EALs)` is the site's hazard with a neutral building, and the reported score is the same thing after the Building Resilience Modifier. Until that decomposition is calibrated and shipped, park it in **Location** and show the construction delta in the row. This is the assignment I hold with least confidence (§2.2).

4. **`health` and `socioeconomic` come out of the headline.** They measure *the population that lives nearby*, not the property or its physical environment. A single letter grade attached to a census tract, driven by ACS income/poverty/cost-burden and CDC PLACES disease prevalence, is functionally a residential security map. This is the highest-severity risk in the whole proposal and the mitigation is cheap (§5).

5. **Stop grading sub-composites on the per-dimension absolute thresholds.** `A ≥ 80` was calibrated for a single dimension's distribution. The mean of *k* roughly-percentile dimensions has a standard deviation near `29/√k`, so the 13-dimension composite is crushed toward 50 and an A is a four-sigma event. That compression is exactly the "middling composite that tells you neither fact" the product owner is complaining about — it is an arithmetic artefact, not a property of the houses. Each sub-composite needs its own reference distribution, built with the machinery `scripts/calibrate_construction_percentiles.py` already has (§4).

6. **Keep the overall composite, demote it.** Drop it to a one-line secondary figure, or replace it with a conjunctive statement ("B building / C location") the way IIHS reports separate ratings and Euro NCAP reports four percentages under one star.

Measured on the golden fixtures, with the engine's real numbers (§1.3 shows how these were produced):

| case | Building | Location | today's composite |
|---|---|---|---|
| 2025 code-built frame house, LA | **88.6 A** | **50.5 C** | 56.1 C |
| ICF passive, LA | 96.4 A | 51.5 C | 58.5 C |
| ICF passive, Shelby | 94.5 A | 60.6 B | 68.5 B |
| 1970s baseline, Shelby | 63.1 B | 58.4 C | 59.9 C |
| worst-case, Shelby | 37.7 D | 52.4 C | 50.3 C |

The first row is the product owner's example, and the split does exactly what they asked: A for the structure, C for the surroundings, where today one number says "C" and means neither.

---

## 1. What the code actually does — and four contradictions worth knowing about

### 1.1 There are not two groupings. There are four.

| # | Location in code | Purpose | `resilience` | `infrastructure` |
|---|---|---|---|---|
| 1 | `simulate/dimensions.py:198-199` `CONSTRUCTION_DRIVEN` / `LOCATION_DRIVEN` → payload `kind` at line 1023 | drives the **rendered grouping** | falls through the `else` → **"construction"** | **construction** |
| 2 | `data/national_percentile.py:57` `CONSTRUCTION_DIMS` / `:77` `IDENTITY_DIMS` | drives **score→percentile routing** | **CONSTRUCTION_DIMS** | **IDENTITY_DIMS** |
| 3 | `scripts/sync_readme.py:67-73` `_driver()` | drives the **README table** | **"Construction + location"** (three-valued!) | Construction |
| 4 | `scripts/sync_docs.py:660` + `docs/methodology.html` TOC | drives the **methodology page** | counted as construction-driven | construction |

So the README already tells the public that resilience is "Construction + location" while the payload tells the renderer it is "construction". `docs/methodology.html` puts Disaster Resilience under the heading *"Construction-driven (how the home is built)"*, which is the strongest version of the wrong claim.

**Grouping #2 is not really in conflict with the others, and calling it a contradiction is a mistake worth avoiding.** `national_percentile.CONSTRUCTION_DIMS` is not a taxonomy of causation — it is a routing table answering "does this score already mean a percentile, or does it need remapping through a modelled curve?" `infrastructure` sits in `IDENTITY_DIMS` because `INFRA_XS` is anchored to national quantiles (`all_dimensions.py:228`), not because infrastructure is location-driven. The name is what misleads. **Rename `CONSTRUCTION_DIMS` → `REMAPPED_DIMS` (or `CURVE_DIMS`)** as part of this work, so the next reader does not treat it as a second opinion about what drives what. That is a pure rename; `tests/test_national_percentile.py:79` pins coverage and would follow.

### 1.2 The UI already does most of the split

`docs/label-core.js:262-274`:

```js
var GROUP_LABEL = { construction: "The building itself", location: "The neighborhood &amp; location" };
```

The thirteen rows are **already** rendered under two headings, driven by the payload's `kind`. This materially changes the shape of the work: the request is not "build a two-axis label", it is "**finish** the two-axis label — fix the taxonomy that feeds it and give each group a number". That is a much smaller and safer change than a redesign, and it means the taxonomy bug is already visible to users: Disaster Resilience currently appears under *"The building itself"*.

### 1.3 The numbers behind the recommendation

Everything quantitative below came from running the engine offline against the golden fixtures' supplied geography (`tests/golden/label_snapshot.json`, `tests/test_golden_label.py` `SHELBY_GEO` / `LA_GEO`), plus one scored variant: the `baseline` preset at the LA point with `year_built=2025, condition="excellent"` — i.e. the product owner's "house built in 2025".

That house scores:

```
resilience 75.3  energy 87.4  durability 97.7  environmental 80.6  infrastructure 40.8
health 26.7  air_quality 21.8  noise 0.9  socioeconomic 33.0  walkability 66.4
climate 41.6  solar 80.7  water 76.3        →  composite 56.1  C
```

Three bucketings of the same numbers:

| building bucket | building score | grade |
|---|---|---|
| today's `CONSTRUCTION_DRIVEN` + resilience (what `kind` renders) | 76.4 | **B** |
| `{energy, durability, environmental, resilience}` | 85.3 | A |
| **recommended `{energy, durability, environmental}`** | **88.6** | **A** |

**`infrastructure` alone costs this house a full letter grade on the building axis.** The product owner's stated goal — "a house built in 2025 should earn roughly an A for the building sub-score" — is *not* achieved by splitting the label as the code currently groups it. It is achieved by fixing the taxonomy. That is the most load-bearing empirical finding in this document.

### 1.4 Resilience decomposes cleanly, and the two legs are the same size

`score/resilience.py` computes four raw hazard EAL rates and multiplies each by a Building Resilience Modifier. Scoring the *raw* sum gives the site's hazard with a neutral building; the reported score is the same curve after the BRM. Same Shelby point, varying only flood zone and build:

| flood zone | build | hazard-only (BRM = 1) | as built |
|---|---|---|---|
| X | 1975 frame, average | 67.1 | 62.7 |
| X | 2025 ICF, excellent | 67.1 | **81.6** |
| AE | 1975 frame, average | 38.2 | 36.4 |
| AE | 2025 ICF, excellent | 38.2 | **63.4** |

The **location** leg spans 29 points (67.1 → 38.2). The **building** leg spans 19–27 points depending on the site. They are comparable in magnitude. Resilience is not "mostly location" or "mostly building" — it is genuinely both, and any single-bucket assignment is wrong by roughly half. This is the empirical case for treating it specially (§2.2).

### 1.5 Other facts that constrain the design

- The composite is `sum(scored) / len(scored)` (`dimensions.py:1026-1027`), skipping unscored dimensions — never zeroing them, which is right.
- The composite gets an **absolute** grade (`score_to_grade`) and **no percentile**. Every individual dimension gets a percentile; the roll-up does not. That asymmetry is a bug in waiting once you add two more roll-ups (§4.2).
- `data/health.py:77` `states_without_data()` returns **Kentucky (21), Pennsylvania (42), Puerto Rico (72)**. Those are statewide holes, not per-tract gaps. Under a split, every address in two states gets a location sub-score composed of a different dimension set from everyone else's (§6.4).
- `confidence.py` already runs a per-dimension pedigree channel (High/Moderate/Low) deliberately separate from the score. Sub-composites need to inherit from it (§6.3).
- `tests/test_dimensions.py:245-252` pins `n_scored == 5` offline and asserts `CONSTRUCTION_DRIVEN | {"resilience"}` are all scored — it hard-codes the current taxonomy and will fail on any reassignment. That is the test doing its job.
- `tests/golden/label_snapshot.json` locks the numeric core of `label_payload` and must be regenerated (`UPDATE_GOLDEN=1`) once sub-composites enter the payload.

---

## 2. Precedent: how established labels present multi-axis scores

### 2.1 The pattern that repeats

Across food, energy, buildings, cars and environmental justice, the same three-way split shows up:

- **Summary-only** (Nutri-Score, NHTSA overall star, Home Energy Score 1–10)
- **Components-only, no roll-up** (IIHS, EJScreen, Walk/Transit/Bike Score, First Street's four Factors)
- **Components with a roll-up** (Euro NCAP, LEED, BREEAM, EPC)

And the evidence points in a consistent direction: **summary scores win on comprehension; component scores win on actionability and on not lying.** The right answer for a label that is trying to do both is components with a *disciplined* roll-up — which is where the recommendation lands.

### 2.2 What the research on presentation actually says

The strongest empirical body is front-of-pack nutrition. Across a 12-country European experiment and Swiss and French replications, the **single summary graded label (Nutri-Score) beat nutrient-specific Multiple Traffic Lights on objective understanding** ([PLOS One, 12-country](https://journals.plos.org/plosone/article?id=10.1371%2Fjournal.pone.0202095); [Swiss comparison](https://journals.plos.org/plosone/article?id=10.1371%2Fjournal.pone.0228179); [FDA's 2023 FOP literature review](https://www.fda.gov/media/175617/download)). Summary systems were consistently easier to understand than nutrient-specific ones. That is a genuine argument *against* the split and it should be stated plainly rather than waved away.

Three things blunt it for this product:

1. **Task difference.** Nutri-Score's task is a two-second supermarket comparison of substitutable goods. A home purchase is a months-long, single-item, high-stakes decision where the buyer will read a methodology page. The comprehension penalty of a second number is far less binding.
2. **Hsee's evaluability hypothesis** ([Hsee 1996, OBHD](https://pages.ucsd.edu/~cmckenzie/Hsee1996OBHDP.pdf); [Hsee, attribute evaluability](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=936581)) predicts the *direction* of the failure precisely. Attributes that are hard to evaluate in isolation get ignored in separate evaluation and matter in joint evaluation. Homes are almost always evaluated jointly (a shortlist). In joint evaluation, two numbers is where the extra attribute starts to *carry weight* rather than being noise — which is the whole point.
3. **Haberman's subscore criterion** is the honest statistical test and it is the one to actually run. A subscore has added value only when it is reliable enough and **distinct enough from the total** to beat the total as a predictor of its own true value ([Haberman 2008, *When Can Subscores Have Value?*](https://journals.sagepub.com/doi/10.3102/1076998607302636); [Sinharay 2019](https://journals.sagepub.com/doi/10.3102/1076998618788862)). Two sub-scores that correlate 0.9 with each other and with the composite would be theatre. The fixture spread above (Building 37.7–96.4 against Location 49.9–61.5, essentially orthogonal — the location leg barely moves across seven very different buildings at two points) is a strong prima-facie case that they *are* distinct. Test it properly on the calibration panel before shipping (§7.5).

### 2.3 Labels that split the way this one wants to

**IIHS vs NHTSA** is the cleanest natural experiment. NHTSA rolls frontal (40%), side (40%) and rollover (20%) into one star rating; the criticism is explicit and standard — the overall rating **masks weaknesses in individual tests** ([NHTSA usage guidelines](https://www.nhtsa.gov/ratings/government-5-star-safety-ratings-motor-vehicles-advertising-and-communication-usage)). IIHS deliberately publishes per-test Good/Acceptable/Marginal/Poor and **no combined score**, using *Top Safety Pick+* as a **conjunctive award** — you must clear a bar on every test — rather than an average. Meanwhile nearly every new car earns four or five NHTSA stars, so the summary has lost its discriminating power. That is precisely the compression failure the housing composite is showing (§4.1), from the same cause.

**Euro NCAP** is the middle path and probably the closest analogue: four percentage scores (Adult Occupant, Child Occupant, Vulnerable Road User, Safety Assist) *plus* an overall star rating in which a poor score in one area drags the star down ([Euro NCAP, The Ratings Explained](https://www.euroncap.com/en/car-safety/the-ratings-explained)). Four axes is more than two and consumers cope. Worth noting the star is **not** an average — it is closer to a minimum, which is the aggregation rule §4.4 recommends considering.

**EPA EJScreen** is the strongest precedent for *refusing* to aggregate, and its stated reason maps onto this problem exactly: there is no single composite EJ index, because "there is no widely-accepted, objective way to combine the differing environmental concerns into one number because of the value judgments and scientific challenges inherent in deciding how much weight or importance should be given to each" ([EPA, EJ Indexes in EJScreen](https://19january2021snapshot.epa.gov/ejscreen/environmental-justice-indexes-ejscreen_.html)). This label has thirteen dimensions in wildly different units — kBTU/sqft, dB exposure share, fiscal ratio, EAL rate — and asserts equal weight by taking a mean. That is a value judgement, currently unstated.

**LEED v4** did the exact taxonomic move being proposed here: it **split the old Sustainable Sites category into "Location and Transportation" (16 pts, the building's relationship to its surroundings) and "Sustainable Sites"** (the parcel's own ecosystem), then still reports one point total and a Certified/Silver/Gold/Platinum band ([USGBC LEED v4 credit library](https://www.usgbc.org/credits?Version=%22v4%22&Rating_System=%22New+Construction%22)). The precedent cuts both ways: the field found the location/building line worth drawing, *and* it kept a single headline.

**Walk Score / Transit Score / Bike Score** ship three independent 0–100 scores with three separate methodologies and no blend ([Walk Score methodology](https://www.walkscore.com/methodology.shtml), [Bike Score methodology](https://www.walkscore.com/bike-score-methodology.shtml)) — and are widely quoted individually in listings. Note `score_walkability` in `all_dimensions.py:314` blends them 60/25/15 when a Walk Score enrichment is present; that is a local weighting choice the vendor itself declines to make.

**First Street** publishes four separate 1–10 Factors — Flood, Fire, Heat, Wind — per property with no combined risk score ([First Street help centre](https://help.firststreet.org/hc/en-us/articles/360053574994-Risk-Factor-improvements-and-updates)). This is the closest product to ours in market and it chose components-only.

### 2.4 The two-score cautionary tale: the UK EPC

Domestic UK EPCs originally carried **two** headline ratings: the Energy Efficiency Rating (a cost metric) and the Environmental Impact Rating (a CO₂ metric). The EIR **has been demoted to the last page** and the EER is the sole headline ([UK Government, technical annex: what EPCs measure](https://www.gov.uk/government/consultations/reforms-to-the-energy-performance-of-buildings-regime/technical-annex-for-chapter-2-what-epcs-measure); [Designing Buildings, EIR](https://www.designingbuildings.co.uk/wiki/Environmental_impact_rating)). Why it failed is instructive and is a direct warning for this design: the two ratings **conflicted in ways users could not resolve** — a cheap-gas-heated home gets a good EER and a poor EIR — and the headline metric was itself misleadingly named (people read "Energy Efficiency" as fabric efficiency when it measures cost).

The lesson is not "don't ship two scores". It is: **two scores only work when a reader can say in one sentence why they differ and what to do about it.** "The house is good, the block is not" passes that test. "Energy efficiency is B but environmental impact is E" did not.

### 2.5 The precedent for the *actionability* framing (§3)

DOE's **Home Energy Score** publishes the current 1–10 score **and a "Score with Improvements"** — the score the home would reach if the recommended upgrades were made ([DOE Home Energy Score methodology](https://betterbuildingssolutioncenter.energy.gov/sites/default/files/attachments/Home_Energy_Score_Methodology_Paper.pdf); [About the Score](https://betterbuildingssolutioncenter.energy.gov/home-energy-score/home-energy-score-about-score)). This is the single best precedent for the "what the owner can change" cut, and note the *form* it takes: not a second axis, but a **second value of the same axis**. That is a much lighter-weight way to carry actionability than a second grade.

Both HEScore and HERS are **asset** ratings — they hold occupant behaviour constant so the score describes fixed characteristics and homes are comparable ([RESNET/HERS Index](https://www.hersindex.com/hers-index/what-is-the-hers-index/); [GreenBuildingAdvisor, "A Home Energy Rating Is an Asset Label"](https://www.greenbuildingadvisor.com/article/a-home-energy-rating-is-an-asset-label); [DOE Building Energy Asset Score](https://www.energy.gov/cmei/buildings/building-energy-asset-score)). The asset/operational distinction is a *third* cut, orthogonal to both of the ones under discussion, and this engine is already firmly an asset rater. Worth knowing so nobody proposes it as a fourth axis later.

### 2.6 On composite index construction generally

The OECD/JRC *Handbook on Constructing Composite Indicators* is the standard reference and its central warning applies verbatim: **additive aggregation implies full and constant compensability** — a great score on one indicator fully offsets a terrible score on another — whereas geometric aggregation limits it ([OECD/JRC Handbook, 2008](https://www.oecd.org/content/dam/oecd/en/publications/reports/2008/08/handbook-on-constructing-composite-indicators-methodology-and-user-guide_g1gh9301/9789264043466-en.pdf)). A house in a floodplain with excellent insulation currently gets those two facts averaged into "fine".

And **ESG is the field's cautionary tale about sub-pillars**. Berg, Kölbel & Rigobon's *Aggregate Confusion* found pairwise correlations of only 0.38–0.71 across six major ESG raters, decomposing the divergence into measurement (56%), scope (38%) and **weight (6%)** ([Review of Finance 2022](https://academic.oup.com/rof/article/26/6/1315/6590670)). Two things follow. First, weighting matters far less than people fight about — which supports keeping equal weights inside each bucket and spending the effort on scope instead. Second, they found a **rater effect**: an overall view of a firm bleeds into the measurement of individual categories. Publishing two headline grades creates exactly that pressure here, on whoever tunes the models next.

---

## 3. The taxonomy problem

### 3.1 The four options, and why (a)-with-decomposition wins

| Option | What it is | Fatal problem |
|---|---|---|
| **(a) one bucket each** | every dimension assigned to Building or Location | hybrids are misattributed; a floodplain home's excellent construction lands in the wrong column |
| **(b) split weights** | e.g. resilience contributes 0.5 to each | **the weights are unfalsifiable.** Is resilience 50/50 or 60/40? §1.4 says it depends on the flood zone — the true split varies *per address*. A fixed weight is a fiction that is hard to explain and impossible to defend in a methodology page. And the same 0–100 number appearing in two aggregates double-counts it. |
| **(c) decompose hybrids** | compute the building leg and the location leg separately from the model internals | correct, but needs new reference distributions for the new quantities, so it is real calibration work. Only possible where the model exposes the seam. |
| **(d) third graded bucket** | "hybrid" as a third grade | worst of both. Three grades is past what a label can carry (Euro NCAP's four work because each is a *concrete named risk*, not "mixed"), and "hybrid: C" is uninterpretable and unactionable. |

**Recommendation: (a) as the shipping structure, with (c) applied where the model already has a seam, and never (b) or (d).**

The key move is that **(c) informs the explanation, not the aggregation.** The label already has expandable per-dimension detail rows (`dimension_details`, rendered by `label-core.js` `dimDetail`). Put the decomposition there. "This site's hazard scores 38; your construction lifts it to 63" is more useful in a sentence than any weighted average would be as a number.

### 3.2 The thirteen, one at a time

| Dimension | Bucket | Confidence | Reasoning |
|---|---|---|---|
| `durability` | **Building** | certain | Component-lifespan model from CAMA attributes and condition. Nothing about the surroundings enters. The only unambiguous building dimension in the roster. |
| `energy` | **Building** | high | Envelope/HVAC × IECC climate zone. The climate-zone leg is real but it is a *normalisation*, not a judgement about the neighbourhood — `base_eui(climate_zone, vintage, building_type)` asks "how much energy does this house need **here**". Two identical houses in 4A and 2A get different scores, which is correct and is the same thing HEScore does. Not worth decomposing; a "climate-adjusted" caveat in the row is enough. |
| `environmental` | **Building** | high | Embodied carbon + operational carbon + water. Operational carbon runs through the eGRID subregion factor and the Cambium marginal rate, so the grid region is a genuine location leg — a Vermont house looks better than an identical Wyoming one. But the buyer's actionable question ("is this house wasteful?") is a building question, and the embodied leg is pure building. **Decomposable if wanted**: `model_parcel_environment` takes `grid_factor` as a parameter, so a "same house on the national average grid" counterfactual is one extra call. Worth doing as a detail row, not as a bucket change. |
| `resilience` | **Location** *(park)* → **decompose** | **low — the real judgement call** | §1.4: the location leg spans 29 points, the building leg 19–27. Neither dominates. Today it lands in "construction" via a fall-through `else`, which is the worst outcome because nobody chose it. Parking it in Location is defensible on the grounds that the **hazard baseline is the part the buyer cannot change**, and a label must never let good construction imply a floodplain is safe. But the counter-argument is strong: the BRM is the largest single construction lever the engine models, and removing it leaves the Building bucket at three dimensions, two of which (`energy`, `environmental`) share the energy model's output and are therefore correlated. **If the decomposition can be built in the same change, build it and put both legs where they belong.** If not, park it in Location and say so out loud in the row. |
| `infrastructure` | **Location** | high | The label calls it "Infrastructure Burden" and it is a fiscal ratio: property tax + user fees over modelled cost of services. The revenue side is the county's effective tax rate and the state's classification rules; the cost side is county spending from the Census of Governments, shaped by density. The building contributes lot area per unit and assessed value — real, but second-order. Empirically decisive: the parcel's density and the county's fiscal structure move this far more than the structure does, and leaving it in Building costs the 2025 house a letter grade (§1.3). Also note `all_dimensions.py:228` anchors it to a **national percentile** already, so it behaves like the location dimensions statistically. |
| `air_quality` | **Location** | high | Tract PM2.5 + ozone + county radon zone. One wrinkle worth flagging: `radon_adjusted_reading` (`dimensions.py:811-813`) already moves this score based on **foundation type and radon mitigation** — a building input inside a location dimension. This is small and correct, but it means air quality is technically a hybrid, and it is the best existing example in the codebase of decomposition-done-right: the comment at line 809 says exactly why radon is the one component the building moves. |
| `noise` | **Location** | certain | BTS transportation-noise exposure, refined by distance to road/rail. Purely about where the parcel sits. (Windows and insulation would move perceived interior noise; the engine does not model that, and should not pretend to.) |
| `walkability` | **Location** | certain | EPA National Walkability Index at the tract. Built environment, not building. |
| `climate` | **Location** | certain | CMIP6-LOCA2 tract projection. |
| `solar` | **Location** | high | PVGIS specific yield, now refined to the parcel point. Roof pitch/orientation/shading would be building factors; the engine does not model them, so as scored this is purely a location resource. If roof geometry ever enters, revisit. |
| `water` | **Location** | certain | EPA SDWIS compliance for the serving system. The house has no influence (correctly, the engine refuses to score private wells rather than substituting a county figure). |
| `health` | **neither — context row** | high | CDC PLACES *health outcomes of the resident population*: asthma, diabetes, mental-health prevalence. This describes people, not property or environment. See §5. |
| `socioeconomic` | **neither — context row** | high | Census ACS income, poverty, housing-cost burden at tract level. Describes people. See §5. |

### 3.3 The line I am drawing, stated once

**The Location score measures the physical environment of the parcel. It does not measure the people who live around it.**

That sentence is defensible in a methodology page, survives a fair-housing review far better than the alternative, and produces a clean assignment for eleven of thirteen dimensions with one genuine hard case (resilience). It also happens to be the line LEED drew when it separated Location & Transportation from Sustainable Sites — about the building's relationship to infrastructure and place, not about demographics.

The cost is real: buyers do care about neighbourhood income and health outcomes, and the rows stay visible so the information is not destroyed. What changes is that the engine stops *grading* it and stops folding it into a headline letter.

---

## 4. Is "building vs location" the right cut? The changeable/fixed alternative

### 4.1 The alternative framing

Cut instead on **what the owner can change vs what they cannot**:

| Changeable (retrofit) | Fixed |
|---|---|
| energy (insulation, HVAC, windows) | walkability, noise, air quality (PM2.5/ozone), climate, solar, water, infrastructure, socioeconomic, health |
| environmental (operational leg, solar) | environmental (embodied leg — already built) |
| durability (roof, systems replacement) | resilience (hazard baseline) |
| resilience (retrofits: roof straps, elevation, defensible space) | |
| air quality (radon mitigation only) | |

This is genuinely more actionable, and the engine already models it: `simulate/house.py` carries above-code feature credits (fortified roof, elevation, ignition-resistant assemblies) and `dimensions.py` carries `radon_mitigation`, `passive_house`, `solar`. The buyer's real question after "should I buy this" is "what can I do about the bad parts", and this cut answers it directly.

### 4.2 Why it should not be the headline

Three reasons.

1. **It is not stable.** Changeability is a function of budget, not of the house. Elevating a house is "changeable" for $80k. Replacing a roof is changeable for $20k. Adding a radon fan is changeable for $1,500. A binary split hides a four-order-of-magnitude cost range, and the label would be making an implicit affordability assumption it cannot defend.
2. **It splits dimensions worse, not better.** Under building/location, one dimension is a genuine hybrid (resilience). Under changeable/fixed, *four* are (environmental splits embodied/operational; durability splits shell/components; resilience splits hazard/retrofit; air quality splits radon/ambient). You would trade one hard case for four.
3. **It answers a post-purchase question with a pre-purchase label.** At the moment of comparing three houses, "which of these is a better house and which is a better place" is the decision. "What could I fix later" is the next conversation.

### 4.3 Carry both — but not as two axes

**Yes, the label should carry both framings, and the precedent for how is DOE's Home Energy Score: a second *value*, not a second *axis*.**

Ship building/location as the two graded axes. Then add, per dimension and only where the engine can actually compute it, a **"with improvements"** figure — the same score after the modelled retrofit. The engine can already produce these:

- `energy` / `environmental`: re-run with `passive_house` or an envelope factor → the achievable score.
- `air_quality`: `radon_adjusted_reading(..., mitigated=True)` — already implemented.
- `resilience`: re-run with the above-code feature credits enabled.
- `durability`: re-run with components reset to new.

Then a single roll-up sentence under the Building score — *"could reach 94 with the recommended upgrades"* — carries the whole actionability framing in one number, with no second taxonomy and no second grade to explain. This is the highest value-per-unit-of-complexity item in this document and it is close to free given what the models already do.

---

## 5. Fair housing: the part to take seriously

### 5.1 The risk, stated plainly

**A single letter grade attached to a census tract, derived substantially from the income, poverty and disease prevalence of the people living there, and published per-address on a real-estate-adjacent product, is a modern residential security map.**

That is not rhetoric. The HOLC "Residential Security" maps graded neighbourhoods A–D; the 1934 FHA underwriting manual named "the ingress of undesirable racial or nationality groups" as an adverse factor in *neighbourhood rating*; and the causal literature finds the maps reduced home ownership, house values and rents and increased segregation for decades afterward ([Chicago Fed working paper on the effects of the 1930s HOLC maps](https://www.chicagofed.org/~/media/publications/working-papers/2017/wp2017-12-pdf.pdf); [NCRC, HOLC maps and persistent inequality](https://ncrc.org/holc/)). The same literature explicitly notes that HOLC was an *innovation in statistical technology* that automated mortgage decisions — and draws the parallel to today's algorithmic scoring itself.

Three properties make this label's location score *especially* exposed:

1. **It is constant within a tract.** `health`, `socioeconomic`, `walkability`, `air_quality`, `noise` and `climate` all resolve at the tract; `infrastructure`, `solar` and `water` largely at the county. So the location grade for two neighbouring addresses is **identical**. Publishing it per-address is publishing a tract-level map, one address at a time. Anyone can reconstruct the map by querying addresses.
2. **`socioeconomic` is a close proxy for tract racial composition.** ACS income + poverty + housing-cost burden at census-tract resolution correlates strongly with race in most US metros. Nothing in the engine intends this and it does not matter — Fair Housing Act disparate-impact analysis is about effect, not intent.
3. **The letter grade is the problem, more than the number.** "This neighbourhood is a D" is a *verdict*. "PM2.5 is 11.4 µg/m³, 22nd percentile nationally" is a *measurement*. The first invites avoidance of a place; the second invites a question about air.

### 5.2 What the industry already did about this

The market has run this experiment. In December 2021 Redfin **declined to add neighbourhood crime data**, stating that given "the long history of redlining and racist housing covenants in the United States there's too great a risk of this inaccuracy reinforcing racial bias" ([Redfin, *Neighborhood Crime Data Doesn't Belong on Real Estate Sites*](https://www.redfin.com/news/neighborhood-crime-data-doesnt-belong-on-real-estate-sites/)). **Realtor.com removed crime maps** and **Trulia phased them out** within days ([Inman](https://www.inman.com/2021/12/13/redfin-calls-on-real-estate-websites-to-drop-crime-data/); [GeekWire](https://www.geekwire.com/2021/trulia-to-drop-neighborhood-crime-data-from-home-listings-after-redfin-speaks-out-against-practice/)).

School ratings, by contrast, stayed — and remain contested, described as a "legal gray area", with the ratings colour-coded green/yellow/red and school racial composition a click away ([NPR Ed](https://www.npr.org/sections/ed/2016/10/10/495944682/race-school-ratings-and-real-estate-a-legal-gray-area)). And Redfin paid **$4 million** in 2022 to settle a National Fair Housing Alliance suit over a minimum-price policy that produced disparate service by neighbourhood ([Bloomberg](https://www.bloomberg.com/news/articles/2022-04-29/redfin-settles-digital-redlining-suit-ends-price-threshold); [PBS NewsHour on the original complaint](https://www.pbs.org/newshour/nation/fair-housing-groups-say-redfin-redlines-minority-communities)).

On the regulatory side, HUD's May 2024 guidance applied the FHA to tenant screening and housing advertising **when algorithms and AI perform those functions**, expecting models to be tested for equally accurate prediction across groups and assessed for less discriminatory alternatives ([summary](https://www.consumerfinancialserviceslawmonitor.com/2024/05/hud-issues-guidance-on-applicability-of-the-fair-housing-act-to-tenant-screening-and-housing-related-advertising-that-relies-upon-algorithms-and-ai/)). Note the landscape is unsettled — HUD has since moved to remove its discriminatory-effects regulation and leave disparate-impact questions to courts ([Federal Register, Jan 2026](https://www.federalregister.gov/documents/2026/01/14/2026-00590/huds-implementation-of-the-fair-housing-acts-disparate-impact-standard); [Brookings](https://www.brookings.edu/articles/algorithms-and-housing-discrimination-rethinking-huds-new-disparate-impact-rule/)) — so the regulatory floor may drop while the reputational and litigation risk does not.

**A scoring engine is not a broker and not a tenant-screening tool, and the FHA analysis is different.** But the reputational analysis is not, and the direction of industry practice is unambiguous.

### 5.3 Mitigations, in priority order

1. **Exclude `socioeconomic` and `health` from the headline location aggregate.** They stay as rows with their own numbers and percentiles, under a heading that says what they are: *"About the people who live nearby — not about this property."* This is the one mitigation that changes the risk class rather than the risk magnitude, and it costs almost nothing. (§3.3)
2. **Rename what remains.** "Location score" invites the neighbourhood-verdict reading. **"Site & environment"** or **"Surroundings"** describes what it actually aggregates: hazard, air, noise, water, sun, climate, walkability, infrastructure cost.
3. **Never render a location grade on a map, and rate-limit bulk address queries.** The per-tract constancy (§5.1.1) means map rendering and bulk export turn the label into the map directly. If the API is public, this is a live concern today, before any split.
4. **Show the drivers with the grade, always.** A location C that expands into "noise 0.9 — the property is close to a highway" is a measurement. A bare C is a verdict. The label already does this well per dimension; the sub-composite row must not become an exception.
5. **Do not let the location score be a filter.** If any surface ever lets a user sort or filter listings by location grade, it has become a steering instrument regardless of what the methodology page says.
6. **Run a disparate-impact check on the score itself.** The engine has ACS tract data on hand. Regress the proposed location sub-composite on tract racial composition and publish the R². If the correlation is high even after removing `socioeconomic` and `health`, that is a finding the methodology page should carry, not one to discover later. My expectation, stated as a prediction to be tested: correlation drops a lot but stays materially positive, because environmental burdens are themselves unequally distributed — which is EJScreen's entire premise. **A location score that correlates with race because polluted places really are disproportionately non-white is a true measurement of an unjust reality, and it is still dangerous to package as a grade.** Both things are true and the methodology page should say so.

### 5.4 The counter-argument, honestly

Suppressing environmental information for fair-housing reasons has its own equity cost: the buyer denied the information is disproportionately the first-time, lower-income buyer without an agent who "knows the area". EJScreen exists precisely to *surface* environmental burden by place. The distinction that resolves this is **measurement vs verdict, and per-dimension vs aggregated**: publish air quality, noise, flood and water at full fidelity with sources and percentiles; do not compress them plus tract demographics into one letter that reads as a judgement of a place.

---

## 6. Aggregation and statistics

### 6.1 Is the mean of a subset of percentiles meaningful?

**It is a well-defined index. It is not a percentile, and it must not be graded as one.**

Two separate problems.

**(i) The mean of percentiles is not the percentile of the mean.** Percentile transformation is non-linear and rank-based. Averaging destroys the property that makes the input interpretable. The composite value 56.1 does *not* mean "better than 56% of US homes" — nothing in the code claims it does, but the shared `score_to_grade` and the shared 0–100 bar make readers assume it.

**(ii) Averaging compresses.** If the *k* dimensions were independent and uniform on [0,100], their mean has standard deviation `28.87/√k`:

| k | SD of the mean | implied share above 80 (normal approx.) |
|---|---|---|
| 13 (today's composite) | 8.0 | ~0.01% |
| 9 (location) | 9.6 | ~0.1% |
| 4 | 14.4 | ~2% |
| 3 (recommended building) | 16.7 | ~4% |
| 1 (a dimension) | 28.9 | 20% |

Real dimensions are positively correlated, so the true SDs are larger — but the direction is certain and severe. **The 13-dimension composite graded on `A ≥ 80` is a scale on which almost nothing can earn an A.** The seven golden fixtures span 50.3 to 68.5 — a 18-point range covering profiles from "worst case" to "ICF passive house". That is the compression, visible in the shipped data.

This is the actual root cause of the product owner's complaint. They diagnosed it as "the composite blends two things"; it is *also* "the composite is an average of thirteen things and averages of thirteen things do not move". Splitting into 3 and 8 fixes roughly half of it by arithmetic alone; recalibrating the thresholds fixes the rest.

### 6.2 So a sub-composite needs its own reference distribution

**Yes — and the machinery exists.** `scripts/calibrate_construction_percentiles.py` already scores a household-weighted national panel of `{US county} × {building archetype}` through the real models and emits score-at-percentile curves into `src/housing_label/data/construction_percentiles.csv`. Extend it to also compute, per panel member, the two sub-composites, and emit two more rows:

```
building_composite,p1,...,p99
location_composite,p1,...,p99
```

Then a sub-composite maps to a national percentile through `_interp` exactly as the construction dimensions do today, and the letter grade is derived **from that percentile**, not from the raw mean. This is the single most important technical recommendation in §4/§6, and it is maybe a day of work on top of a calibration run.

Without it you have two options, both worse: grade the sub-composite on `A ≥ 80` (wrong — different distribution per bucket, so a "B building" and a "B location" would not mean comparable things), or show the numbers with no letters (defensible, and a reasonable phase-1, but the product owner asked for grades).

### 6.3 Equal weights inside each bucket?

**Yes, keep equal weights, and say out loud that it is a choice.** Berg/Kölbel/Rigobon found weight contributes only 6% of ESG rating divergence against measurement's 56% — arguing about weights is usually the least productive place to spend effort. Equal weighting is transparent, does not encode a hidden theory of what matters to a buyer, and is what the engine does today.

Two caveats:

- **Correlated dimensions get implicit extra weight.** In the Building bucket, `environmental`'s operational leg is computed *from the energy model's output* (`dimensions.py:459-473` feeds `env_kwh` in). So a well-insulated house scores well on both, and equal weights over three dimensions is closer to equal weights over ~2.2 independent signals. Worth documenting; not worth "fixing" with reweighting.
- **Compensability.** Equal-weight additive aggregation lets a 100 offset a 20 exactly. `worst_case_shelby` has durability 13.5 and resilience 17.9 and still gets a D, not an F, because energy 56.8 and environmental 42.8 pull it up. If the label wants floors — "no A building score with any dimension below 40" — that is the conjunctive rule IIHS's *Top Safety Pick+* and Euro NCAP's star both use, and it is more defensible than a geometric mean because it is explainable in one sentence.

### 6.4 Should an overall composite survive?

**Keep it, demote it, and stop leading with it.** Reasons to keep: continuity for existing API consumers (`composite_score` is in the payload, the golden snapshot, `label-core.js`, the compare table at `label-core.js:407`, and the presets grid); a single sortable number has real utility; and removing it forces every consumer to invent their own blend, which is worse.

Reasons to demote: it is the number that provoked this request; it is statistically compressed (§6.1); and Euro NCAP shows a roll-up can coexist with components as long as the components are the visual focus.

If you want the roll-up to actually discriminate, make it **`min(building, location)`** rather than the mean of thirteen. That is the Euro NCAP/IIHS pattern, it is honest about compensability, it is one sentence to explain — *"a home is only as good as its weaker half"* — and it would move `icf_passive_la` from 58.5 C to 51.5 C, which is arguably the truer summary of "excellent house, mediocre surroundings". I flag this as a genuine product decision, not a technical one, and I would not make it in the same release as the split.

---

## 7. Failure modes and gaming

### 7.1 The luxury new build in a deprived area

Building A, Location D. This is the case the split exists to reveal, and it is also the case most likely to generate complaints — from developers, from listing agents, and from residents of the area. Two mitigations, both required:

- The location grade must expand into named physical drivers (highway 60 m away, PM2.5 at the 22nd percentile), never stand alone.
- With `socioeconomic` and `health` out of the aggregate (§5.3), the D is far more likely to be *about measurable environmental burden* than about who lives there. That is the difference between a defensible claim and an indefensible one.

### 7.2 The modest old house in an affluent walkable neighbourhood

Building D, Location A — the mirror case, and the one that gets **less** scrutiny while being just as consequential. The risk here is different: the split makes the *house's* problems (a 1920s roof, knob-and-tube, no insulation) newly legible and separately gradeable, which is good for the buyer and bad for the seller. Expect pushback from the listing side, not the fair-housing side. This is the split working correctly.

Note also that under today's blend, this house's composite is propped up by the neighbourhood — and `worst_case_shelby` demonstrates it: building 37.7 (D), location 52.4 (C), composite 50.3 (C). **The composite currently launders a D-grade structure into a C.** That is a consumer-protection argument *for* splitting that has not been made in the request and probably should be.

### 7.3 Gaming: the building score becomes the sellable number

This is the most underrated risk. The simulator's building inputs — `construction`, `condition`, `year_built`, `passive_house`, `radon_mitigation`, `solar`, upgrade flags — are **caller-supplied**. Today they are diluted across a thirteen-dimension mean. Give them their own headline grade and you have created a number that a seller can move by typing.

Test: the LA baseline preset at `year_built=2025, condition="excellent"` moves durability from 46.1 to 97.7 and the Building sub-score from ~63 to 88.6 — **two letter grades from two form fields.** Mitigations:

- **Per-input provenance.** The payload already distinguishes detected from entered for some fields (`house.value_source`, NSI-detected structure in `effective_structure`). Extend this to every input that drives the Building score, and surface it: *"Building score based on 2 detected and 5 self-reported attributes."*
- **Cap or badge unverified A grades.** A building A from wholly self-reported inputs should be badged, not suppressed — suppression makes the label useless for the simulator's actual purpose (exploring hypotheticals).
- **The `confidence` channel already exists and is the right home for this.** `confidence.py` computes per-dimension High/Moderate/Low from provenance. A sub-composite's tier should be the **minimum** of its members', not the mode — a bucket is only as trustworthy as its weakest input.

### 7.4 The two-number confusion mode (the EPC failure)

§2.4: two headline ratings failed on UK EPCs because users could not resolve conflicts. Guard against it with a **required one-sentence reconciliation** rendered whenever the two grades differ by two or more letters: *"Well-built house, difficult surroundings"* / *"Good location, the house itself needs work"*. This is cheap, it is the sentence a reader is trying to construct anyway, and it is what makes the second number carry information instead of cognitive load.

### 7.5 Verify the sub-scores are actually distinct before shipping

Run Haberman's test, or at minimum the correlation, on the calibration panel: if `corr(building_composite, location_composite)` is high across the national panel, two scores add nothing and the effort belongs elsewhere. The fixture evidence is encouraging (Building ranges 37.7–96.4 while Location barely moves, 49.9–61.5, across seven very different buildings at two points), but seven fixtures at two points is not a test. This should be a gate on the whole project, not an afterthought.

### 7.6 Missing dimensions break sub-composite comparability harder than they break the composite

Kentucky, Pennsylvania and Puerto Rico have **no** `health` score at all (`data/health.py` `states_without_data()`), statewide. Today that drops the composite from a 13-mean to a 12-mean — a small, roughly unbiased perturbation. Under the recommended split, `health` is out of the aggregate anyway, so **this particular gap becomes a non-issue**, which is a nice side-effect of the §5 recommendation.

But the general problem stays for other gaps (a private well leaves `water` unscored; a non-CONUS point leaves `climate` and `air_quality` unscored; offline runs lose all tract-resolved dimensions). Rules:

- **Available-case mean, never zero-fill** — the engine's existing policy, and it is right.
- **Publish `n_scored` per sub-composite**, not just overall. The payload has one `n_scored` today; it needs three.
- **A coverage floor for the letter grade.** Below some threshold — I would suggest **5 of 8** for Location and **2 of 3** for Building — show the number and suppress the letter. A location grade computed from three of eight dimensions is not the same measurement as one from eight, and the letter implies it is.
- **Say which are missing.** `label-core.js` `compositeConfLine` already does this for the composite ("Not scored: …"). Replicate per bucket.

---

## 8. Implementation sketch

### 8.1 The two sets, as code

In `simulate/dimensions.py`, replace the two sets with an explicit, total, three-valued map — so no dimension can ever again fall through an `else`:

```python
# Every dimension names its group explicitly. A KeyError here is the point:
# adding a 14th dimension must not silently inherit a bucket.
DIMENSION_GROUP = {
    "energy":         "building",
    "durability":     "building",
    "environmental":  "building",

    "resilience":     "location",   # hybrid — see research/building-vs-location-subscores.md §3.2
    "infrastructure": "location",
    "air_quality":    "location",
    "noise":          "location",
    "walkability":    "location",
    "climate":        "location",
    "solar":          "location",
    "water":          "location",

    "health":         "context",    # about the resident population, not the property
    "socioeconomic":  "context",
}
```

Keep `CONSTRUCTION_DRIVEN` / `LOCATION_DRIVEN` as derived aliases for one release if `scripts/sync_readme.py` and `scripts/sync_docs.py` are not updated in the same change — but they read those sets directly, so update them together and delete the aliases.

### 8.2 Payload

`dimensions.py:1016-1024`, the per-dimension dict: `"kind"` becomes three-valued (`"building" | "location" | "context"`). `label-core.js:262` needs a third `GROUP_LABEL` entry; its `grouped` guard (`groups.every(k => !!GROUP_LABEL[k])`) already fails safe to a flat list if the label is missing, so an unversioned static asset degrades rather than breaks — worth verifying before deploying, since `docs/` is served independently of the API.

New keys alongside the existing composite (`dimensions.py:1127-1136` and `house.py:2128-2133`):

```python
"subscores": {
    "building": {"score": 88.6, "national_grade": "A", "national_percentile": 91,
                 "n_scored": 3, "n_total": 3, "confidence": "moderate",
                 "unscored": []},
    "location": {"score": 50.5, "national_grade": "C", "national_percentile": 47,
                 "n_scored": 8, "n_total": 8, "confidence": "moderate",
                 "unscored": []},
},
```

Additive only. `composite_score` / `composite_national_grade` / `n_scored` stay exactly as they are, so `/presets`, the compare table, and any external consumer keep working. `context` dimensions are excluded from both sub-composites **and remain in `composite_score`** — changing the composite's membership in the same release would make the diff unreadable and break the golden snapshot for two unrelated reasons at once. Decide about removing them from the composite in a follow-up.

### 8.3 Grading and percentiles

Phase 1 (ship-able immediately): compute sub-composites as available-case means; grade with `score_to_grade`; **document that the thresholds are the per-dimension ones and are known to be conservative for a mean.** Set `national_percentile: null`.

Phase 2 (the honest version): extend `scripts/calibrate_construction_percentiles.py` to emit `building_composite` and `location_composite` rows into `construction_percentiles.csv`; route them through `national_percentile()`; derive the letter **from the percentile** (A = top 20%, B = 60–80th, …) so a "B building" and a "B location" mean the same thing about relative standing. Note this makes sub-composite grades percentile-banded while individual dimension grades stay absolute — an inconsistency that needs a sentence in the methodology page, and is still better than the alternative.

Do not skip phase 2. Phase 1 alone reproduces the compression problem inside each bucket.

### 8.4 Unscored dimensions

```python
def _subcomposite(scores: dict, keys: list[str], floor: int):
    vals = [scores[k] for k in keys if scores.get(k) is not None]
    if not vals:
        return None
    score = round(sum(vals) / len(vals), 1)
    return {"score": score,
            "national_grade": score_to_grade(score) if len(vals) >= floor else "—",
            "n_scored": len(vals), "n_total": len(keys),
            "unscored": [k for k in keys if scores.get(k) is None]}
```

Floors: `building` 2 of 3, `location` 5 of 8. Both are judgement calls; state them in a constant with a comment rather than inlining the integers.

### 8.5 Decomposition rows (the §3.1 option (c) work, deferrable)

For `resilience`, in `simulate/house.py` where `r` is already available:

```python
hazard_only = eal_rate_to_score(r["flood_raw"] + r["tornado_raw"]
                                + r["seismic_raw"] + r["fire_raw"])
# r["total_score"] is the same curve after the BRM and feature credits.
```

Surface both in `dimension_details["resilience"]`: *"This site's hazards score 38 for a typical build; this home's construction lifts it to 63."* Verified working (§1.4). Analogous counterfactuals are available for `environmental` (re-run `model_parcel_environment` with the national mean `grid_factor`) and `energy` (`base_eui` at a reference zone). These are detail rows, not new dimensions.

### 8.6 What needs pinning in tests

| Test | Change |
|---|---|
| `tests/test_dimensions.py:235-252` | Rewrite. It asserts `n_scored == 5` offline and iterates `CONSTRUCTION_DRIVEN \| {"resilience"}`. Under the new taxonomy the offline-scoreable set is `{energy, durability, environmental, resilience, infrastructure}` — same five dimensions, different groups — so the count survives but the grouping assertions do not. |
| **new** `test_dimension_group_total` | Assert `set(DIMENSION_GROUP) == {k for k, _ in DIMENSIONS}` in **both** directions. This is the guard that stops a 14th dimension silently inheriting a bucket — the exact failure mode the current `else` at line 1023 represents. Model it on `tests/test_national_percentile.py:79`, which already does this for percentile routing and is the best test in the repo for this class of bug. |
| **new** `test_subcomposite_excludes_unscored` | A location dimension set to `None` must reduce `n_scored`, not the score, and must appear in `unscored`. |
| **new** `test_subcomposite_grade_coverage_floor` | Below the floor, `national_grade == "—"` while `score` is still present. |
| **new** `test_context_dims_not_in_subscores` | `health` and `socioeconomic` appear in `dimensions` with `kind == "context"` and in neither sub-composite. This is the fair-housing invariant; it should fail loudly if someone folds them back in. |
| **new** `test_subscores_reconcile_with_composite` | Every scored dimension is in exactly one of {building, location, context}; the three partition the roster. |
| `tests/test_golden_label.py` | Regenerate with `UPDATE_GOLDEN=1`. The seven fixtures gain `subscores` and their `kind` values change. Review the diff — it is the release's audit trail, and the point of the snapshot. |
| `tests/test_label_payload.py` | Add the `subscores` shape to whatever structural assertions it makes. |
| `scripts/sync_readme.py`, `scripts/sync_docs.py` | Both read `CONSTRUCTION_DRIVEN` / `LOCATION_DRIVEN` directly. `sync_readme._driver()` is already three-valued and should now read `DIMENSION_GROUP`. `sync_docs.gen_setup_dimension_counts` hard-codes "resilience is construction-driven" at line 660 and must change. Re-run both with `--write`. |
| `docs/methodology.html` | Its TOC and section headings put Disaster Resilience under *"Construction-driven (how the home is built)"* — the strongest public statement of the wrong taxonomy. Partly autogenerated, partly curated; the curated prose needs a hand edit. |
| `data/national_percentile.py` | Rename `CONSTRUCTION_DIMS` → `REMAPPED_DIMS`. Pure rename; update `tests/test_national_percentile.py:90`. |

### 8.7 Suggested sequencing

1. **Taxonomy + rename only.** `DIMENSION_GROUP`, three-valued `kind`, the totality test, docs/README regeneration, golden snapshot regen. No new payload keys, no new numbers. The rendered grouping changes (resilience and infrastructure move columns) and nothing else does — a reviewable, low-risk change that already fixes the visible bug.
2. **Distinctness gate.** Correlation / Haberman check on the calibration panel (§7.5). If it fails, stop.
3. **Sub-composites, ungraded.** Numbers + `n_scored` + `unscored` in the payload; UI shows numbers, no letters.
4. **Calibrate the two reference distributions**, add percentiles and percentile-derived letters.
5. **"With improvements"** counterfactual figures (§4.3) — the actionability framing, at a fraction of the cost of a second taxonomy.

---

## 9. Where I am uncertain

Stated plainly, because most of this document is not hedged and these parts should be.

- **`resilience`'s bucket is a genuine coin-flip** and §1.4's numbers say so quantitatively (29-point location leg vs 19–27-point building leg). I recommend Location on the grounds that the un-changeable hazard baseline should not be masked by good construction, and because the Building bucket's other members are already correlated with each other. Someone could argue the reverse — that the BRM is the engine's biggest construction lever and belongs where the buyer looks for construction quality — and I would not call them wrong. **The real answer is decomposition; the bucket choice is what you do until then.**
- **Whether `health` should leave the headline** is more debatable than `socioeconomic`. It measures real outcomes that plausibly reflect environmental exposure, not just demography. I recommend excluding it for consistency with the "measure the place, not the people" line and because two of its own states have no data — but a defensible alternative keeps it in and drops only `socioeconomic`.
- **The coverage floors (2 of 3, 5 of 8) are invented.** They have no empirical basis. They should be set by looking at how sub-composite percentile error grows as coverage drops on the calibration panel, which is a straightforward experiment nobody has run.
- **I have not verified the sub-scores are statistically distinct** on anything larger than seven golden fixtures at two coordinates. §7.5 is a gate for a reason.
- **The compression arithmetic in §6.1 assumes independence**, which is false — the dimensions are positively correlated, so real SDs are larger than the table shows and the A-is-unreachable claim is somewhat overstated. The *direction* is certain; the magnitude is an upper bound on the problem, not a measurement of it. The fixture range (50.3–68.5 across profiles from "worst case" to "ICF passive") is the actual evidence, and it is consistent with severe compression.
- **`min(building, location)` as the roll-up** (§6.4) is the boldest suggestion here and I hold it loosest. It is more honest about compensability and it has good precedent (IIHS, Euro NCAP), but it changes every published composite and should not ride along with the split.

---

## Sources

- [PLOS One — Objective understanding of Nutri-Score vs other FOP label formats](https://journals.plos.org/plosone/article?id=10.1371%2Fjournal.pone.0202095)
- [PLOS One — Nutri-Score most efficient FOP label, Swiss consumers](https://journals.plos.org/plosone/article?id=10.1371%2Fjournal.pone.0228179)
- [FDA — Front of Package Labeling Literature Review (April 2023)](https://www.fda.gov/media/175617/download)
- [Hsee (1996) — The Evaluability Hypothesis, *OBHDP*](https://pages.ucsd.edu/~cmckenzie/Hsee1996OBHDP.pdf)
- [Hsee — Attribute Evaluability and Joint-Separate Evaluation Reversals (SSRN)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=936581)
- [Haberman (2008) — When Can Subscores Have Value? *JEBS*](https://journals.sagepub.com/doi/10.3102/1076998607302636)
- [Sinharay (2019) — Added Value of Subscores and Hypothesis Testing](https://journals.sagepub.com/doi/10.3102/1076998618788862)
- [OECD/JRC — Handbook on Constructing Composite Indicators (2008)](https://www.oecd.org/content/dam/oecd/en/publications/reports/2008/08/handbook-on-constructing-composite-indicators-methodology-and-user-guide_g1gh9301/9789264043466-en.pdf)
- [EPA — Environmental Justice Indexes in EJScreen](https://19january2021snapshot.epa.gov/ejscreen/environmental-justice-indexes-ejscreen_.html)
- [EPA — EJScreen Technical Documentation](https://www.epa.gov/sites/default/files/2015-05/documents/ejscreen_technical_document_20150505.pdf)
- [Euro NCAP — The Ratings Explained](https://www.euroncap.com/en/car-safety/the-ratings-explained)
- [NHTSA — 5-Star Safety Ratings advertising and communication usage guidelines](https://www.nhtsa.gov/ratings/government-5-star-safety-ratings-motor-vehicles-advertising-and-communication-usage)
- [USGBC — LEED v4 credit library (Location & Transportation, Sustainable Sites)](https://www.usgbc.org/credits?Version=%22v4%22&Rating_System=%22New+Construction%22)
- [UK Government — Technical annex: what EPCs measure (EER vs EIR)](https://www.gov.uk/government/consultations/reforms-to-the-energy-performance-of-buildings-regime/technical-annex-for-chapter-2-what-epcs-measure)
- [Designing Buildings — Environmental impact rating](https://www.designingbuildings.co.uk/wiki/Environmental_impact_rating)
- [DOE — Home Energy Score Scoring Methodology](https://betterbuildingssolutioncenter.energy.gov/sites/default/files/attachments/Home_Energy_Score_Methodology_Paper.pdf)
- [DOE — About the Home Energy Score](https://betterbuildingssolutioncenter.energy.gov/home-energy-score/home-energy-score-about-score)
- [RESNET — What Is the HERS Index](https://www.hersindex.com/hers-index/what-is-the-hers-index/)
- [GreenBuildingAdvisor — A Home Energy Rating Is an Asset Label](https://www.greenbuildingadvisor.com/article/a-home-energy-rating-is-an-asset-label)
- [DOE — Building Energy Asset Score](https://www.energy.gov/cmei/buildings/building-energy-asset-score)
- [Walk Score — Methodology](https://www.walkscore.com/methodology.shtml) · [Bike Score methodology](https://www.walkscore.com/bike-score-methodology.shtml)
- [First Street — Risk Factor improvements and updates](https://help.firststreet.org/hc/en-us/articles/360053574994-Risk-Factor-improvements-and-updates)
- [Berg, Kölbel & Rigobon (2022) — Aggregate Confusion: The Divergence of ESG Ratings, *Review of Finance*](https://academic.oup.com/rof/article/26/6/1315/6590670)
- [Redfin — Neighborhood Crime Data Doesn't Belong on Real Estate Sites (Dec 2021)](https://www.redfin.com/news/neighborhood-crime-data-doesnt-belong-on-real-estate-sites/)
- [Inman — Redfin, Realtor.com abandon crime data on real estate portals](https://www.inman.com/2021/12/13/redfin-calls-on-real-estate-websites-to-drop-crime-data/)
- [GeekWire — Trulia to drop neighborhood crime data](https://www.geekwire.com/2021/trulia-to-drop-neighborhood-crime-data-from-home-listings-after-redfin-speaks-out-against-practice/)
- [NPR Ed — Race, School Ratings and Real Estate: A 'Legal Gray Area'](https://www.npr.org/sections/ed/2016/10/10/495944682/race-school-ratings-and-real-estate-a-legal-gray-area)
- [PBS NewsHour — Fair housing groups say Redfin redlines minority communities](https://www.pbs.org/newshour/nation/fair-housing-groups-say-redfin-redlines-minority-communities)
- [Bloomberg — Redfin settles digital-redlining suit, ends price threshold](https://www.bloomberg.com/news/articles/2022-04-29/redfin-settles-digital-redlining-suit-ends-price-threshold)
- [Federal Reserve Bank of Chicago — The Effects of the 1930s HOLC "Redlining" Maps](https://www.chicagofed.org/~/media/publications/working-papers/2017/wp2017-12-pdf.pdf)
- [NCRC — HOLC "redlining" maps: the persistent structure of segregation and economic inequality](https://ncrc.org/holc/)
- [HUD guidance on the FHA, tenant screening and advertising using algorithms/AI (May 2024)](https://www.consumerfinancialserviceslawmonitor.com/2024/05/hud-issues-guidance-on-applicability-of-the-fair-housing-act-to-tenant-screening-and-housing-related-advertising-that-relies-upon-algorithms-and-ai/)
- [Federal Register — HUD's Implementation of the Fair Housing Act's Disparate Impact Standard (Jan 2026)](https://www.federalregister.gov/documents/2026/01/14/2026-00590/huds-implementation-of-the-fair-housing-acts-disparate-impact-standard)
- [Brookings — Algorithms and housing discrimination: rethinking HUD's new disparate impact rule](https://www.brookings.edu/articles/algorithms-and-housing-discrimination-rethinking-huds-new-disparate-impact-rule/)
