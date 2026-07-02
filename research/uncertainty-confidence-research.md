# Per-Dimension Uncertainty / Confidence Display — Research & Methodology

**Status:** Research complete; a concrete, buildable proposal for the next label feature
(README roadmap: *"Per-dimension uncertainty / confidence display"*; see also
[`research/lifetime-cost-research.md`](lifetime-cost-research.md) §4).
**Scope:** How to rigorously **quantify** and **display** confidence/uncertainty on the label —
(a) a per-dimension confidence measure for each of the nine scored dimensions, and (b) a composite
confidence for the rolled-up score — using provenance the pipeline **already stores**
(`geo_level`, `*_data_source`, `location_notes`, the climate SSP `score_low/score_high` band, N/A
flags), plus honest flagging of what would require new modeling.

This document follows the pattern of the existing `research/*.md` files: published-benchmark
methods, explicit sourcing with URLs, and honest flagging of where the project's current data is
**insufficient** to support a claimed confidence.

---

## 0. Executive summary / recommendation

**Build a provenance-driven per-dimension *confidence tier* (a small pedigree score → High /
Moderate / Low, buildable today from data the pipeline already stores), rendered as a confidence
dot/badge kept visually *separate* from the score; and a composite confidence that combines the
per-dimension tiers with an explicit *coverage penalty* for missing (N/A) dimensions. Reserve true
numeric error whiskers for the two dimensions that already carry a defensible quantitative interval —
Climate Projections (the SSP2-4.5 → SSP5-8.5 band, already computed as `score_low`/`score_high`) and
Infrastructure Burden (the documented ±30%). Do *not* dress a provenance tier up as a statistical
confidence interval.**

The reasoning, in short:

1. **A single number that conflates uncertainty types is misleading** (§1). The nine dimensions carry
   *different kinds* of uncertainty — model/parametric (energy, durability, resilience, infrastructure,
   environmental), scenario (climate SSPs), input-data-quality/provenance (all of them, via
   geographic-resolution fallbacks and measured-vs-modeled-vs-placeholder), and statistical/aleatory
   (ACS margins of error, PLACES model-based estimates). The honest label expresses **confidence**
   (how much to trust the estimate) *separately* from the **score** (the estimate itself), exactly as
   the IPCC keeps *confidence* separate from *likelihood* (§5).

2. **Provenance is the immediately buildable signal** (§3). The pipeline already records, per parcel
   and per dimension, the geographic resolution that answered (`geo_level` = tract / county / us for
   wildfire and climate), the source/vintage (`env_data_source` with an explicit *"LOW CONFIDENCE"*
   embodied-carbon flag), the fetch outcome (`location_notes`: `"CDC PLACES (tract …)"` vs
   `"no CENSUS_API_KEY"` vs `"national-average fallback"`), and whether a dimension is a real value, a
   uniform placeholder, or N/A (excluded from the composite). A **NUSAP/pedigree** rubric
   (Funtowicz & Ravetz 1990; van der Sluijs et al. 2005) turns exactly this kind of provenance into a
   defensible qualitative confidence score — it is the right, citable framework, and it needs no new
   model runs.

3. **A fuller Monte Carlo interval is warranted only for specific dimensions and only later** (§4).
   The disaster-resilience EAL and the energy EUI are the two dimensions where input-parameter
   uncertainty (damage ratios, hazard frequencies, EUI archetype spread, BRM "v1 estimate" bonuses)
   could be propagated to a real 0–100 confidence interval. That is a genuine modeling project — worth
   staging *after* the provenance tier ships, and only where the inputs to a distribution actually
   exist.

**What to build first:** the pedigree tier + coverage-penalized composite confidence + the two honest
whiskers. It matches the project's "flag what failed verification" ethos, requires no scoring/model
change, and reuses fields already emitted into `sample-parcels.json`.

---

## 1. A taxonomy of uncertainty — and which type each dimension actually has

Any credible uncertainty display must first say *what kind* of uncertainty it is reporting. The
standard reference typology in model-based decision support is **Walker et al. (2003), "Defining
Uncertainty"**, which classifies uncertainty by *location* (where in the model it enters), *level*
(from statistical uncertainty through scenario uncertainty to "total ignorance"), and *nature*
(aleatory vs. epistemic)
([Walker et al. 2003, *Integrated Assessment*](https://repository.tudelft.nl/record/uuid:fdc0105c-e601-402a-8f16-ca97e9963592)).
The categories that matter for this project:

| Type | Definition | Reducible? | Where it shows up here |
|---|---|---|---|
| **Statistical / aleatory** | Inherent variability; a well-characterized probability distribution (a "±" you can put a number on). | No (irreducible) | Census ACS sampling **margins of error**; CDC PLACES model-based small-area estimates; the spread of homes within a ResStock archetype. |
| **Model / parametric (epistemic)** | Imperfect knowledge of parameters or model form; reducible with better data/models. | Yes | Resilience EAL (damage ratios, hazard frequencies, BRM "v1 estimates"); energy EUI archetype mapping; durability service-life constants; environmental embodied-carbon intensities; infrastructure cost curves (the documented **±30%**). |
| **Scenario** | Genuinely different plausible futures, not weighable by probability; you report a *range across scenarios*, not a distribution. | No (it is a choice of assumptions) | **Climate Projections**: the SSP2-4.5 (low) → SSP5-8.5 (high) band, *already computed* as `score_low`/`score_high`. |
| **Input-data-quality / "fitness-for-use"** | Is the value measured, modeled, or a fallback? At what geographic resolution? How recent? Is it present at all? | Yes (better data) | **Every** dimension, via `geo_level` (tract → county → national fallback), `*_data_source`/vintage, and `location_notes` (real value vs. placeholder vs. N/A). This is the provenance layer. |
| **Deep uncertainty** | Analysts cannot agree on the model, the distributions, or even how to rank outcomes. | — | Not claimed here, but relevant honesty framing for the long climate horizon and for compound-hazard interactions the EAL model assumes independent. |

The "fitness-for-use" framing is the geospatial-data-quality standard: **ISO 19157** defines data
quality as *completeness, thematic accuracy, logical consistency, temporal quality, positional
accuracy, and usability*, explicitly so a **user can decide whether data are of sufficient quality
for their particular application** — i.e. fitness for use
([ISO 19157:2013](https://www.iso.org/standard/32575.html);
[ICA overview](https://wiki.icaci.org/index.php?title=ISO_19157:2013_Geographic_information_-_Data_quality)).
This is precisely what a tract → county → national fallback degrades, and it is what the project's
`geo_level` tag already records.

**The load-bearing consequence:** a provenance/pedigree confidence tier is an honest statement about
*data-quality* uncertainty. It is **not** a statistical confidence interval and must never be drawn as
one (§7). Only Climate (scenario band) and Infrastructure (±30% parametric) currently carry an
interval that can honestly be drawn as a whisker.

---

## 2. Uncertainty taxonomy applied to the nine dimensions

| # | Dimension | Dominant uncertainty type | Concrete drivers in the code |
|---|---|---|---|
| 1 | **Disaster Resilience** | Model/parametric + input-quality | EAL = Σ(freq × damage-ratio) × BRM; damage ratios and hazard frequencies are model constants; BRM feature bonuses are flagged *"v1 estimates, pending literature review"* (`src/housing_label/simulate/house.py`, `src/housing_label/simulate/dimensions.py`); wildfire leg resolves tract→county→us (`wildfire_geo_level`); tornado is sparse/spatially noisy (scoring-research.md §6 warns tornado "has higher uncertainty"). |
| 2 | **Energy Efficiency** | Model/parametric | Modeled EUI from ResStock archetypes × vintage × construction × IECC climate zone. No metered data; envelope/passive factors are v1 estimates. Deterministic point estimate. |
| 3 | **Durability** | Model/parametric + completeness | Component-lifespan / effective-age model + assessor condition. **NaN (unscored)** for vacant/non-residential parcels with no CAMA building data. |
| 4 | **Environmental Footprint** | Model/parametric, *heterogeneous by leg* | Operational leg = strongest (metered-equivalent kWh/therms × EPA eGRID2022 factors); embodied leg **explicitly flagged "LOW CONFIDENCE"** in `env_data_source` (sparse US single-family benchmarks, order-of-magnitude); water leg locally favorable. eGRID **vintage** stored. |
| 5 | **Infrastructure Burden** | Model/parametric (**quantified**) + input-quality | Header documents **±30%** on absolute dollars; per-county calibration (Census of Governments) and property-tax rate (Census ACS) each with a **national-average fallback** when the county is unmapped. |
| 6 | **Health Impact** | Statistical/aleatory + input-quality | CDC PLACES tract-level *model-based* chronic-disease estimates (carry their own CIs upstream); `location_notes` records `"CDC PLACES (tract …)"` vs `"no PLACES data for tract …"`. |
| 7 | **Socioeconomic** | Statistical/aleatory + completeness | Census ACS income/poverty/education — ACS estimates ship with **published margins of error**. When no `CENSUS_API_KEY`, falls back to a **uniform placeholder (50)** and is **excluded from the composite** (`SOCIO_PLACEHOLDER`, `src/housing_label/score/all_dimensions.py`). |
| 8 | **Walkability** | Input-quality (present/absent) | Walk Score API; **N/A** when no `WALKSCORE_API_KEY` (`location_notes: "no WALKSCORE_API_KEY"`). When present, a defensible measured index. |
| 9 | **Climate Projections** | **Scenario** (+ resolution) | SSP2-4.5 (low, headline) → SSP5-8.5 (high) **band already computed** (`score_low`/`score_high`); ensemble-mean over CMIP6-LOCA2 models; tract→county→us (`geo_level`); sub-county but **not parcel-scale**; fire leg is a single RCP8.5 pathway (no scenario spread). |

**Reading:** five dimensions are dominated by *model/parametric* uncertainty (candidates for eventual
Monte Carlo), one is *scenario* (Climate — already banded), two are *statistical/aleatory with
upstream CIs* (Health, Socioeconomic), and *all* carry an *input-quality* layer that the pedigree tier
captures directly.

---

## 3. Per-dimension confidence — proposed method + rubric (buildable today)

### 3.1 Why a pedigree rubric, and its provenance

The rigorous, citable way to turn *data provenance* into a confidence score is the **pedigree matrix**
from the **NUSAP** system (Numeral, Unit, Spread, Assessment, Pedigree), introduced by **Funtowicz &
Ravetz (1990)** and operationalized for model-based environmental assessment by **van der Sluijs et
al. (2005)**. NUSAP extends a bare number with a qualitative, multi-criteria judgement of the
*strength* of its underpinning
([van der Sluijs et al. 2005, *Risk Analysis* 25(2) / Saltelli mirror PDF](http://www.andreasaltelli.eu/file/repository/08_vdSluijs_et_al2005.pdf);
[NUSAP overview](https://en.wikipedia.org/wiki/NUSAP)).
The **pedigree matrix** scores each parameter on a small set of criteria, each on a **0–4** scale from
well-founded to speculative
([nusap.net — pedigree matrix for parameter strength](https://www.nusap.net/sections.php?op=viewarticle&artid=12)):

| Criterion | Score 4 (strong) | Score 0 (weak) |
|---|---|---|
| **Proxy** | An exact measure of the desired quantity | Not clearly related to the quantity |
| **Empirical basis** | Controlled experiments / large-sample direct measurement | Crude speculation |
| **Methodological rigour** | Best practice in a well-established discipline | No discernible rigour |
| **Validation** | Compared against independent measurements over a long domain | No validation performed |

The same idea is the backbone of **ecoinvent's LCA data-quality pedigree matrix** (reliability,
completeness, temporal/geographic/technological correlation), which converts pedigree scores into
uncertainty factors — a mature, widely-cited precedent for provenance → uncertainty
([Ciroth et al. 2013, *Int. J. LCA*](https://link.springer.com/article/10.1007/s11367-013-0670-5)).

This maps cleanly onto **ISO 19157**'s geospatial data-quality elements (completeness, positional
accuracy, temporal quality) and onto the IPCC's *"type, amount, quality, and consistency of
evidence"* basis for confidence (§5). It is the correct framework and requires **no new model runs** —
only a read of fields the pipeline already stores.

### 3.2 The proposed rubric for this project

Four criteria, each scored **0–2** (a coarser scale than NUSAP's 0–4 is honest given we are reading a
handful of provenance flags, not eliciting expert panels), adapted from the pedigree matrix + ISO
19157:

| Criterion (0 / 1 / 2) | 2 (strong) | 1 (moderate) | 0 (weak) | Field(s) read |
|---|---|---|---|---|
| **P — Provenance / method** (measured vs. modeled vs. placeholder) | Measured / authoritative index (Walk Score, CDC PLACES, ACS, eGRID operational leg) | Modeled from parcel attributes / calibrated benchmarks (energy, durability, resilience EAL, infra) | Fixed placeholder or "v1 estimate / weak evidence" leg (socio placeholder 50; embodied-carbon leg) | `*_data_source`, `location_notes`, model docstrings |
| **R — Geographic resolution** | Parcel / point (flood zone, seismic PGA, EUI) | Tract internal point (climate, health, socio, wildfire tract) | County or national-average **fallback** | `geo_level`, `location_notes` ("… fallback") |
| **T — Recency / temporal** | Current vintage (eGRID2022, ACS 5-yr latest, PLACES latest) | Recent but static reference (ResStock, service-life tables) | Dated or undated constant | vintage strings in `*_data_source` |
| **C — Completeness** | Real value present | Present but with a documented wide band (embodied; infra ±30%) | N/A / excluded from composite | null score handling, composite exclusion |

**Aggregation to a tier.** Sum the four criteria (0–8), then map to three tiers — deliberately few, to
avoid false precision (the same reasoning that makes the score itself a letter grade, scoring-research.md §7):

- **High confidence** — total **≥ 6** *and* no criterion = 0
- **Moderate confidence** — total **3–5**, or any single 0 with the rest strong
- **Low confidence** — total **≤ 2**, or a **placeholder/N/A** value (C = 0)

Optionally expose the underlying 0–1 as `confidence = total / 8` for tooltip/debugging, but **display
only the tier** on the label. This mirrors IPCC's choice to publish a *qualitative* confidence level
(very low → very high) rather than a spurious number (§5).

### 3.3 Worked examples using this project's real provenance (Cooper-Young sample)

From `docs/data/sample-parcels.json` `meta.location_notes` and the models, for the shipped Memphis
label:

| Dimension | P (method) | R (resolution) | T (recency) | C (complete) | Total | **Tier** | Basis (real provenance) |
|---|---|---|---|---|---|---|---|
| Disaster Resilience | 1 (modeled EAL) | 2 (parcel: flood zone + PGA) | 2 | 2 | **7** | **High** | Parcel-level flood/seismic; wildfire `geo_level=county` here (Memphis); BRM v1 caveat keeps it off "very high". |
| Energy Efficiency | 1 (modeled EUI) | 2 (parcel attrs + IECC zone) | 1 (ResStock static) | 2 | **6** | **High** | Deterministic archetype model; no metered data → not "measured". |
| Durability | 1 (modeled) | 2 (parcel CAMA) | 1 (service-life tables) | 2 | **6** | **High** (Low/NaN when no CAMA) | Unscored → Low for vacant/non-residential. |
| Environmental Footprint | 1 overall (op leg strong, **embodied leg flagged LOW**) | 2 (parcel) | 2 (eGRID2022) | 1 (embodied order-of-magnitude) | **6** | **Moderate** | `env_data_source` literally carries *"LOW CONFIDENCE"* on embodied — hold at Moderate. |
| Infrastructure Burden | 1 (modeled) | 1 (county calibration) | 2 (2022 CoG/ACS) | 1 (**±30%** documented) | **5** | **Moderate** | The one dimension with a quantified parametric band → also gets a whisker (§6). |
| Health Impact | 2 (CDC PLACES) | 1 (tract) | 2 | 2 | **7** | **High** | `location_notes: "CDC PLACES (tract 47157003100)"`. |
| Socioeconomic | **0 (placeholder / no key)** | 0 | — | **0 (excluded)** | **0** | **Low** | `location_notes: "no CENSUS_API_KEY"` → placeholder 50, excluded from composite. |
| Walkability | **0 (no key → N/A)** | — | — | **0 (N/A)** | **0** | **Low (N/A)** | `location_notes: "no WALKSCORE_API_KEY"`. |
| Climate Projections | 1 (ensemble model) | 1 (tract) | 1 (mid-century) | 1 (**scenario band**) | **4** | **Moderate** | `geo_level=tract`; SSP band already computed → also gets a whisker (§6). |

This table is *mechanically derivable* from fields already present — the feature is a presentation +
small-rubric layer, not a modeling change.

---

## 4. Model/parametric uncertainty propagation — the fuller (later) approach

For the five model-driven dimensions, a genuine numeric 0–100 confidence interval requires propagating
*input-parameter* uncertainty through the score. Three standard methods, in ascending rigour/cost:

1. **First-order (Gaussian) error propagation.** If a score `S = f(x₁…xₙ)` and each input `xᵢ` has
   std `σᵢ`, then `σ_S² ≈ Σ (∂f/∂xᵢ)² σᵢ²` (independent) — the *Guide to the Expression of Uncertainty
   in Measurement* (GUM) standard
   ([JCGM 100:2008 / BIPM GUM](https://www.bipm.org/documents/20126/2071204/JCGM_100_2008_E.pdf)).
   Cheap and analytic, but assumes small, roughly-linear perturbations — shaky for the log-linear
   score mappings and the EAL's multiplicative form.
2. **Monte Carlo simulation.** Sample each uncertain input from its distribution (e.g. flood
   damage-ratio ~ triangular over the Hazus range, EUI ~ archetype spread, BRM bonus ~ ± its v1
   uncertainty), recompute the score thousands of times, and report the 5th–95th percentile as the
   band. This is exactly how **First Street** runs its hazard models (millions of scenarios;
   scoring-research.md §1) and is the method the OECD/JRC handbook recommends for composite indicators
   (§5). It handles the non-linear mappings honestly. Cost: it needs *defensible input distributions*,
   which today exist only sketchily (the ±30% infra figure, the Hazus damage-ratio ranges in
   scoring-research.md tables).
3. **Variance-based sensitivity analysis (Sobol' indices).** Decomposes output variance into
   contributions from each input, telling you *which* input to improve — the "sensitivity analysis"
   half of the OECD/JRC handbook, drawing on Saltelli's work
   ([Saltelli et al., *Global Sensitivity Analysis: The Primer*](https://onlinelibrary.wiley.com/doi/book/10.1002/9780470725184)).

**Recommendation:** stage Monte Carlo *only* for Disaster Resilience and Energy first, where the input
ranges are best documented, and *only after* the pedigree tier ships. Presenting a Monte Carlo 90%
band as a whisker on those two bars would be the natural "phase 2". Do **not** fabricate input
distributions for dimensions that lack them (durability service-life spread, embodied-carbon
intensity) — a pedigree tier is the honest statement there.

---

## 5. Composite confidence — proposed method

The composite is the **mean of the scored dimensions** (`add_composite`, `src/housing_label/score/all_dimensions.py`), which
already **skips N/A dimensions**. The authoritative reference for uncertainty in exactly this kind of
construction is the **OECD/JRC *Handbook on Constructing Composite Indicators*** (2008), whose **Step 7,
"Uncertainty and sensitivity analysis,"** states that uncertainty analysis *"focuses on how
uncertainty in the input factors propagates through the structure of the composite indicator"* and
that combining it with sensitivity analysis *"can be used to gauge the robustness of the composite
indicator … and to increase transparency"*
([OECD/JRC Handbook, full PDF](https://www.oecd.org/content/dam/oecd/en/publications/reports/2008/08/handbook-on-constructing-composite-indicators-methodology-and-user-guide_g1gh9301/9789264043466-en.pdf)).
The handbook is emphatic that **imputation of missing data and the number of indicators included are
themselves sources of uncertainty** in the composite — which is the formal justification for a
missing-dimension penalty.

### 5.1 The math

Let the composite be over `n` scored dimensions with scores `Sᵢ`. Two ingredients:

**(a) Aggregate the per-dimension confidence.** Two defensible rollups; the label should use a blend:

- **Averaged confidence** — mean of the per-dimension `confidenceᵢ` (0–1). Rewards a label most of
  whose dimensions are well-founded.
- **Weakest-link** — `min(confidenceᵢ)`. A composite is only as trustworthy as its shakiest included
  input; this is the conservative reading and prevents a single placeholder-quality dimension from
  hiding behind eight good ones.

Recommended: report the **averaged** confidence as the headline but **cap it at one tier above the
weakest included dimension** (so a composite containing a Low-confidence dimension can be at most
Moderate). This is the honest compromise between the two.

**(b) If/when numeric variances exist** (Monte Carlo, §4), the variance of a simple mean is:

```
independent:  σ_composite² = (1/n²) · Σ σᵢ²
correlated:   σ_composite² = (1/n²) · [ Σ σᵢ² + Σ_{i≠j} ρ_ij · σᵢ · σⱼ ]
```

Crucially, the dimensions are **not** independent — `src/housing_label/score/all_dimensions.py` already computes a **Pearson
correlation matrix** across dimension scores in `print_summary`, so the `ρ_ij` are in hand. Positive
correlation (e.g. resilience ↔ durability for a well-built home) *widens* the composite band relative
to the naïve independent formula; ignoring it would overstate confidence. Until Monte Carlo exists,
use the tier rollup in (a), not this formula — do not invent σᵢ.

### 5.2 The missing-dimension (coverage) penalty

The composite already *silently* drops N/A dimensions. That silence is the problem: a composite over
6 of 9 dimensions is genuinely less trustworthy than one over 9, and the label should say so. Apply a
**coverage factor**:

```
coverage = n_scored / n_total          (e.g. 7 / 9 = 0.78 on the shipped Memphis label)
composite_confidence = tier_rollup(a) × coverage
```

and, for legibility, degrade the *tier* by **how many dimensions are missing**: **at most one
missing** keeps the rollup tier (a near-complete label should not be penalized for a single gap —
e.g. 8/9 keeps its tier); **two or more missing** drops it one tier; **≤ ~⅓ coverage** forces Low.
Using the missing *count* (not a raw coverage ratio) avoids the ambiguous middle band. On the shipped
sample (Socioeconomic +
Walkability absent → 7/9 scored, and Socioeconomic/Walkability are the Low ones anyway), the composite
should read **"Moderate confidence · 7 of 9 dimensions scored,"** never a bare grade that hides the
two gaps. This directly implements the handbook's warning about indicator count as an uncertainty
source.

### 5.3 Worked composite (shipped Memphis label, illustrative)

Included dimensions and tiers (§3.3): Resilience High, Energy High, Durability High, Environmental
Moderate, Infrastructure Moderate, Health High, Climate Moderate — Socioeconomic and Walkability are
N/A (excluded). Averaged confidence ≈ (High,High,High,Mod,Mod,High,Mod) → skew High/Moderate ≈ 0.75;
weakest included = Moderate → cap at High is not triggered; **two dimensions missing** (7/9 scored) →
drops one tier. **Composite: "Moderate confidence · 7 of 9 scored."** Honest, and it moves the moment
a key is added.

---

## 6. Design / UX recommendation for `docs/label.html`

The label renders nine D3 horizontal bars (`DimensionChart`), each row = label + track + grade-colored
fill + `score  grade` text, above a composite summary (`.label-summary`) with a big number and a
`GradeBadge`. Confidence must fit this without visually outranking the score or implying false
precision. Reuse existing tokens (`--navy`, `--muted`, `--border`, `.grade-*`), no new dependencies.

**Recommended treatment — three pieces:**

1. **A per-row confidence dot** — a small glyph in the right gutter (after the `score grade` text),
   rendered as three states: ● High, ◐ Moderate, ○ Low. **Use a neutral hue (gray/`--muted`), NOT the
   grade color**, so "confident" is never read as "good." This is the honesty-critical choice: the IPCC
   keeps confidence a separate axis from the estimate (§5), and consumer research on probability-of-
   precipitation shows a single conflated number is routinely misread
   ([McGill OSS on PoP misperception](https://www.mcgill.ca/oss/article/environment/problematic-perceptions-probability-precipitation)).
2. **Honest whiskers on the two dimensions that have a real interval.** For **Climate** draw a faint
   error bar from `score_low` (SSP2-4.5) to `score_high` (SSP5-8.5) over the fill — the data is already
   in the band (`src/housing_label/simulate/dimensions.py` surfaces `"Climate band (SSP2-4.5–5-8.5, mid-century)"`). For
   **Infrastructure**, draw ±30% around the fill (documented in `src/housing_label/enrich/infrastructure.py`). Do **not**
   draw whiskers on dimensions whose only uncertainty is a provenance tier — that would fake a CI.
3. **A composite confidence line** — beside the big composite grade, one muted line:
   *"Moderate confidence · 7 of 9 dimensions scored"* (§5.2), with the two missing dimensions named on
   hover. This is the credit-score-band / Zestimate-range analogue (§7): a trust signal attached to the
   headline number.

**Tooltip / drill-down.** On hover of a row's dot, show the plain-language provenance already stored —
e.g. *"CDC PLACES, census tract 47157003100"* or *"No Census API key — socioeconomic excluded from
composite."* This is a direct read of `location_notes` / `*_data_source` and doubles as the seed of the
roadmap's "show-your-math" drill-down.

**Legend.** Add a one-line confidence legend beside the existing A–F grade legend: *"● measured/parcel
● modeled ○ placeholder or unavailable."*

Keep it restrained: a dot and two whiskers, not nine error bars. Confidence is a *secondary* channel.

---

## 7. Consumer-facing precedents — what is honest vs. misleading

| Precedent | What it shows | Lesson for this label |
|---|---|---|
| **IPCC AR5/AR6 calibrated language** | Two *separate* axes: **confidence** (very low → very high, from *evidence* × *agreement*) and **likelihood** (probability ranges). Confidence is deliberately *not* a number when the evidence can't support one. | The gold standard: keep the **confidence tier separate from the score**, and use words/tiers, not fake precision. ([IPCC AR5 Guidance Note, Mastrandrea et al. 2010, PDF](https://www.ipcc.ch/site/assets/uploads/2018/05/uncertainty-guidance-note.pdf); [Climatic Change paper](https://link.springer.com/article/10.1007/s10584-011-0178-6)) |
| **Zillow Zestimate** | Publishes a **median error rate** (≈1.9–2.4% on-market, ≈7.5% off-market) and shows a **value range**, not just a point. | Publish the *quality* of the estimate honestly; a range/tier builds trust rather than eroding it. Note Zillow uses *median* (not mean) error — robust to outliers. ([Zillow — What is a Zestimate](https://www.zillow.com/zestimate/)) |
| **NWS Probability of Precipitation** | A single % that *combines* forecaster confidence and areal coverage — and is chronically misread by the public. | Cautionary: a **conflated** single number misleads. Keep confidence and score on different visual channels. ([NWS PoP explainer](https://www.weather.gov/lmk/pops)) |
| **Credit-score bands** (e.g. 300–850, "Good/Very Good") | Ordinal bands, not spurious single-point precision. | Supports the letter-grade + tier approach over decimals. |
| **First Street** | Property 1–10 hazard scores from Monte Carlo, but faced accuracy criticism (Zillow removed the scores from 1M+ listings in late 2025; scoring-research.md §1). | Even rigorous models draw fire when precision outruns validation — *display* honesty (tiers, provenance) matters as much as the model. |

**Honest visual patterns:** a separate confidence dot/tier; a whisker *only* where a real interval
exists; a named coverage caveat ("7 of 9 scored"); opacity/italic for N/A (the label already italicizes
N/A). **Misleading patterns to avoid:** a whisker drawn from a provenance tier (fakes a CI); coloring
the confidence indicator with the grade palette (conflates "certain" with "good"); a single blended
"reliability-adjusted score."

---

## 8. What the project can support **today** vs. what needs new modeling

| Capability | Supported today? | From what |
|---|---|---|
| Per-dimension **provenance/pedigree tier** (High/Moderate/Low) | ✅ **Yes** | `geo_level`, `*_data_source`, `location_notes`, placeholder/N/A flags — all already stored. |
| Per-row **confidence dot** on the label | ✅ Yes (presentation) | Tier from the rubric; `location_notes` for tooltip. |
| **Climate** scenario whisker (SSP2-4.5 → SSP5-8.5) | ✅ Yes | `score_low`/`score_high` already computed; surfaced as a band string. |
| **Infrastructure** ±30% whisker | ✅ Yes | Documented constant in `src/housing_label/enrich/infrastructure.py`. |
| **Coverage-penalized composite confidence** ("7 of 9 scored") | ✅ Yes | `n_scored` already tracked in `src/housing_label/simulate/dimensions.py`. |
| Composite band from **correlated** per-dimension variances | ⚠️ Partial | Correlation matrix exists (`print_summary`) but per-dimension **variances do not** — needs Monte Carlo. |
| **Monte Carlo 90% band** on Resilience / Energy scores | ❌ New modeling | Needs defensible input distributions (damage ratios, EUI spread, BRM v1 ranges). |
| **Statistical CIs** on Health / Socioeconomic | ⚠️ Upstream only | CDC PLACES & ACS publish margins of error, but the pipeline does not currently carry them through — a fetch/plumbing change, not new modeling. |
| Per-dimension band on Durability / Embodied carbon | ❌ Not honestly | No defensible distribution; a pedigree **tier** is the honest statement. |

---

## 9. Alternatives / ranked options

1. **Provenance/pedigree confidence tier + coverage-penalized composite + two honest whiskers
   (RECOMMENDED).** Zero model change, reads fields already stored, matches the "flag what failed
   verification" ethos, and is honest about being a data-quality statement. Ships now.
2. **Tier + whiskers, *plus* plumb through the ACS/PLACES upstream margins of error.** Adds real
   statistical CIs for the two survey-based dimensions at modest cost (carry the MoE columns the APIs
   already return). Good "phase 1.5".
3. **Monte Carlo bands for Resilience + Energy.** The rigorous parametric interval, but a genuine
   modeling project needing input distributions; do it *after* (1), and only for the two
   best-documented dimensions.
4. **Full OECD/JRC uncertainty-and-sensitivity analysis over the whole composite** (vary weighting,
   aggregation, imputation; Sobol' indices). The most complete and the most work; valuable for a
   methodology white paper, overkill for the label's first confidence display.
5. **Single "reliability-adjusted score" (shrink the score toward the mean by its uncertainty).**
   *Rejected* — conflates score and confidence, exactly the IPCC/PoP anti-pattern; destroys the
   separation that makes the display honest.

---

## 10. Risks & honesty caveats

- **Do not present a provenance tier as a statistical confidence interval.** The pedigree tier answers
  *"how well-founded is this input?"*, not *"there is a 90% chance the true score is in [x, y]."* Draw
  whiskers **only** for Climate (scenario band) and Infrastructure (±30%); everything else gets a
  qualitative dot. Say so in the caption.
- **High confidence ≠ good score.** A parcel can be *confidently* an F (well-measured, genuinely
  hazardous). Keep the confidence channel neutral-colored and separate so "high confidence" never
  reads as reassurance. This is the single most important framing risk.
- **Scenario uncertainty is not probability.** The SSP2-4.5→SSP5-8.5 band is a *range across policy
  choices*, not a confidence interval; label it "emissions-scenario range," not "±".
- **The coverage penalty must not be gameable.** Adding a low-quality dimension to raise `n_scored`
  should not raise composite confidence — hence the weakest-link cap (§5.1) alongside coverage.
- **Placeholder ≠ data.** The socioeconomic placeholder (50) is *excluded from the composite* and must
  render as **Low / N/A**, never as a Moderate-confidence real value.
- **Ensemble mean hides model spread.** The climate WMMM is a *mean* over models; the SSP band captures
  scenario spread but not inter-model spread. Note this rather than implying the band is the full
  uncertainty.
- **Don't over-claim resolution.** A tract internal-point value is not parcel-scale; the resolution
  criterion (R) already docks it, and the tooltip should say "tract-level."
- **Correlation widens, not narrows.** If numeric bands are ever added, remember positive
  inter-dimension correlation *increases* composite uncertainty — do not use the independent formula
  for a correlated composite.

---

## 11. References

**Uncertainty taxonomy & frameworks**
- Walker et al. (2003), *Defining Uncertainty: A Conceptual Basis for Uncertainty Management in
  Model-Based Decision Support*, Integrated Assessment (location/level/nature typology):
  https://repository.tudelft.nl/record/uuid:fdc0105c-e601-402a-8f16-ca97e9963592
- ISO 19157:2013 — *Geographic information — Data quality* (completeness, positional/thematic accuracy,
  temporal quality, usability; fitness for use):
  https://www.iso.org/standard/32575.html
  (overview: https://wiki.icaci.org/index.php?title=ISO_19157:2013_Geographic_information_-_Data_quality)

**NUSAP / pedigree matrix (provenance → confidence)**
- Funtowicz & Ravetz (1990), *Uncertainty and Quality in Science for Policy* (origin of NUSAP &
  pedigree matrix) — overview: https://en.wikipedia.org/wiki/NUSAP
- van der Sluijs et al. (2005), *Combining Quantitative and Qualitative Measures of Uncertainty in
  Model-Based Environmental Assessment: The NUSAP System*, Risk Analysis:
  http://www.andreasaltelli.eu/file/repository/08_vdSluijs_et_al2005.pdf
- nusap.net — pedigree matrix for parameter strength (proxy / empirical / method / validation, 0–4):
  https://www.nusap.net/sections.php?op=viewarticle&artid=12
- Ciroth et al. (2013), *Empirically based uncertainty factors for the pedigree matrix in ecoinvent*,
  Int. J. LCA (pedigree → uncertainty factors, LCA precedent):
  https://link.springer.com/article/10.1007/s11367-013-0670-5

**Propagation & sensitivity**
- JCGM 100:2008 — *Guide to the Expression of Uncertainty in Measurement* (GUM; first-order
  propagation): https://www.bipm.org/documents/20126/2071204/JCGM_100_2008_E.pdf
- Saltelli et al., *Global Sensitivity Analysis: The Primer* (variance-based / Sobol'):
  https://onlinelibrary.wiley.com/doi/book/10.1002/9780470725184

**Composite-indicator uncertainty (authoritative for the roll-up)**
- OECD/JRC (2008), *Handbook on Constructing Composite Indicators: Methodology and User Guide*,
  Step 7 "Uncertainty and sensitivity analysis":
  https://www.oecd.org/content/dam/oecd/en/publications/reports/2008/08/handbook-on-constructing-composite-indicators-methodology-and-user-guide_g1gh9301/9789264043466-en.pdf
  (landing: https://www.oecd.org/en/publications/handbook-on-constructing-composite-indicators-methodology-and-user-guide_9789264043466-en.html)

**Calibrated uncertainty language (score-vs-confidence separation)**
- IPCC AR5 Guidance Note — Mastrandrea et al. (2010), *Guidance Note for Lead Authors … on Consistent
  Treatment of Uncertainties* (confidence from evidence × agreement; separate likelihood scale):
  https://www.ipcc.ch/site/assets/uploads/2018/05/uncertainty-guidance-note.pdf
- Mastrandrea et al. (2011), *The IPCC AR5 guidance note …*, Climatic Change:
  https://link.springer.com/article/10.1007/s10584-011-0178-6

**Consumer-facing precedents**
- Zillow — *What is a Zestimate?* (published median error rate; value range):
  https://www.zillow.com/zestimate/
- NWS — *What Does Probability of Precipitation Mean?* (conflated single number, misreading):
  https://www.weather.gov/lmk/pops
- McGill Office for Science and Society — *Problematic Perceptions of Probability of Precipitation*:
  https://www.mcgill.ca/oss/article/environment/problematic-perceptions-probability-precipitation

**Project-internal cross-references**
- `research/scoring-research.md` §6–7 (EAL uncertainty; "avoid false precision," letter grades)
- `research/lifetime-cost-research.md` §4 (this feature as the top-ranked next step)
- `src/housing_label/score/all_dimensions.py` (`add_composite`, correlation matrix, `SOCIO_PLACEHOLDER`)
- `src/housing_label/simulate/dimensions.py` (`location_notes`, `n_scored`, climate band)
- `src/housing_label/enrich/environmental.py` (`env_data_source` "LOW CONFIDENCE" embodied flag)
- `src/housing_label/enrich/infrastructure.py` (±30% documented), `src/housing_label/data/climate_projections.py` (`geo_level`, SSP band)

---

*Prepared as a research/design proposal only. No pipeline or scoring code was modified. The
recommended provenance-tier + coverage-penalized composite confidence + two honest whiskers require
**no model change** — only a small rubric and presentation layer over fields the pipeline already
stores. Monte Carlo bands and upstream statistical CIs are honestly flagged as later, larger work.*
