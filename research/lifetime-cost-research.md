# Lifetime Cost of Ownership ("Money Over a Mortgage") — Research & Methodology

**Status:** Research complete; a concrete, buildable proposal for a new *derived* label feature.
**Scope:** How to rigorously capture and display the dollar difference between housing choices
over the life of a mortgage (a lifetime / total-cost-of-ownership framing), using quantities the
pipeline **already produces**, plus a defensible net-present-value (NPV) method with cited default
assumptions. Includes an explicit dollarizable-vs-qualitative audit of all nine dimensions, a UX
proposal for `docs/label.html`, ranked alternative directions, and an honesty/caveats section.

This document follows the pattern of the existing `research/*.md` files: published-benchmark
methods, explicit sourcing, and honest flagging of where the project's current data is **insufficient**
to support a claim.

---

## 0. Executive summary / recommendation

**Build a comparative, present-value "cost-over-the-mortgage" strip on the label — but only over the
quantities the project can already defend in dollars, and only as a *difference vs. a typical
comparable*, never as an absolute "total cost of the home."**

The project already computes, per house, three genuinely dollar-denominated annual flows:

1. **Expected Annual Loss (EAL)** — `total_loss = total_eal × value` (`simulate/house.py`), already
   shown on the label as *"Expected Annual Loss: $X/yr."*
2. **Annual energy cost** — `est_annual_kwh × $0.105 + est_annual_therms × $1.10`
   (`enrich/energy.py`), already shown as *"Monthly Energy: $X."*
3. **Annual property tax** — `est_property_tax` (`enrich/infrastructure.py`), a homeowner-facing
   cash outflow (currently used only inside the fiscal ratio, not displayed as a cost).

These three are exactly the "operating + risk" costs that a home's **physical and locational
characteristics** move — which is precisely what a nutrition label is for. Discount that annual
stream over a 15- or 30-year horizon and you get a rigorous lifetime figure, expressed the way the
EPA fuel-economy sticker expresses it: **"Over a 30-year mortgage, this home's energy + expected
losses run about $X less/more than a typical comparable at this location."** That comparative,
delta-against-a-baseline framing is the single most important design choice for making the number
trustworthy rather than misleading (§3, §5).

**Do not** roll purchase price, principal, or the public infrastructure cost externality into the
headline; **do not** force health/socioeconomic/walkability/climate into dollars (§2). The honest
scope is *operating + expected-loss cost*, and the label copy must say so.

---

## 1. The money-over-a-mortgage direction — a defensible methodology

### 1.1 What "total cost of ownership" means, and the standard non-hand-wavy construction

The credible precedent for a homeowner TCO is the mortgage industry's **PITI** identity — Principal +
Interest + Taxes + Insurance — extended by the energy-efficiency community to net out utility bills.
DOE/HUD and the ENERGY STAR energy-efficient-mortgage (EEM) literature formalize this as

> **PITI − Energy Savings = true monthly cost of ownership**,

and HUD's own analysis quantifies it: ENERGY STAR-class homes save "almost $1,000 per household per
year" for single-family, "over a 30-year mortgage, families will save $10,500/unit in energy bills,
producing an estimated net savings of $6,350" after the efficiency premium
([ENERGY STAR EEM](https://www.energystar.gov/newhomes/energy-efficient-mortgages);
[FHA EEM fact sheet](https://www.energystar.gov/ia/partners/bldrs_lenders_raters/EEM_Fact_Sheet.pdf)).
This is the mainstream, underwriting-grade way to put energy into a cost-of-ownership number, and it
is the direct analogue of what this project should do — except this project can extend it to
**expected disaster losses** (its EAL model) as well as energy, which most TCO tools cannot.

The **location-cost** analogue is the Center for Neighborhood Technology **H+T Affordability Index**,
which argues that the "true cost" of a location must add the household's *transportation* cost
(usually its second-largest expense) to housing cost, thresholding affordability at ≤45% of income
(30% H + 15% T) via a regression of auto ownership/use and transit use on neighborhood
characteristics ([H+T Index](https://cnt.org/tools/housing-and-transportation-affordability-index);
[H+T Methods 2022](https://htaindex.cnt.org/about/method-2022.pdf)). This is the intellectual warrant
for treating *location* as a cost driver — but see §2: this project only has a Walk Score, not the
H+T regression inputs, so transportation cost is **not** currently dollarizable here.

The **energy-burden** literature (DOE/NREL LEAD tool; ACEEE) frames annual energy cost as a share of
income — "high energy burden" ≥ 6% of income, low-income households averaging ~6% vs ~2% for others
([DOE LEAD tool](https://www.energy.gov/scep/low-income-energy-affordability-data-lead-tool-and-community-energy-solutions);
[ACEEE Energy Burden](https://www.aceee.org/energy-burden)). This is a useful *secondary* display
(cost ÷ local median income) but is not required for the core NPV.

### 1.2 The NPV / discounting math

A stream of annual real costs `C_t` (in today's dollars) over an `N`-year horizon has present value

```
        N
PV  =   Σ    C_t · (1 + g)^(t)  /  (1 + d)^(t)
       t=1
```

where `g` is the **real escalation rate** of that cost stream and `d` is the **real discount rate**.
When `C_t = C₀` and `g`, `d` are constant, this collapses to the closed-form growing annuity

```
PV = C₀ · (1+g)/(d−g) · [ 1 − ((1+g)/(1+d))^N ]        (d ≠ g)
```

and with `g = 0` (constant real cost) to the ordinary annuity factor `a(N,d) = (1 − (1+d)^(−N)) / d`.

**Real vs. nominal (choose real).** Do the whole calculation in **constant (real) dollars** and use a
**real** discount rate. This is the OMB-standard approach for constant-dollar streams: *"Real
Treasury rates are obtained by removing expected inflation … from nominal Treasury interest rates"*
([OMB Circular A-94](https://www.whitehouse.gov/wp-content/uploads/2023/11/CircularA-94.pdf)). Working
in real terms avoids the classic error of discounting an *inflating* cost with a *nominal* rate and
double-counting inflation, and it keeps the headline legible ("in today's dollars").

**Which discount rate, and how to defend it.** Two defensible anchors, and the label should offer both:

- **Homeowner opportunity cost = the mortgage rate (recommended default for the headline).** For a
  mortgaged buyer, a dollar of avoided operating cost is a dollar not borrowed at the mortgage APR, so
  the mortgage rate is the economically correct personal discount rate. The Freddie Mac PMMS 30-year
  fixed averaged **6.49% (nominal) as of 25 Jun 2026**
  ([Freddie Mac PMMS](https://www.freddiemac.com/pmms)); at ~2.5% expected inflation that is
  **≈ 3.9% real**. Use **~4% real** as the shipped default and store the source rate + date.
- **Social/analytical rate = OMB A-94.** For a "public-cost" or scenario view, OMB Circular A-94
  Appendix C publishes updated **real Treasury discount rates annually**; for a 30-year horizon these
  have recently been on the order of ~2% real
  ([A-94 Appendix C, rev. Nov 2024](https://www.whitehouse.gov/wp-content/uploads/2023/12/CircularA-94AppendixC.pdf);
  [2025 rates memo M-25-08](https://bidenwhitehouse.archives.gov/wp-content/uploads/2025/01/M-25-08-2025-Discount-Rates-for-OMB-Circular-No.-A-94.pdf)).
  A lower rate weights far-future savings more heavily; showing it as a sensitivity band is honest.

**Escalation assumptions (keep conservative, cite, and expose as sensitivities):**

| Stream | Recommended real escalation `g` | Basis |
|---|---|---|
| Energy | **0%/yr real** (headline); show 0–1% band | EIA notes 2013–2023 electricity prices "closely tracked inflation," i.e. ~0% real, though near-term increases are outpacing inflation ([EIA AEO 2026](https://www.eia.gov/outlooks/aeo/); [EIA "electricity prices continue steady increase"](https://www.eia.gov/todayinenergy/detail.php?id=65284)). 0% real is the defensible neutral default. |
| Expected loss (EAL) | **0%/yr real** in the headline; note upward risk | EAL rates are hazard-model constants in this project; insurance (the market price of that risk) is rising fast — homeowners' rates rose double digits two years running (2024 ≈ 10.4%, 2023 ≈ 12.7% weighted average rate change; [S&P Global](https://www.spglobal.com/market-intelligence/en/news-insights/articles/2025/1/us-homeowners-rates-rise-by-double-digits-for-2nd-straight-year-in-2024-87061085); [US Treasury FIO report](https://home.treasury.gov/news/press-releases/jy2791)) — so escalating EAL is defensible but uncertain; keep it out of the headline and flag it. |
| Property tax | **0%/yr real** | Millage/assessment growth is location-specific and roughly tracks values in real terms; neutral default. |
| Maintenance | **0%/yr real** | Rule-of-thumb reserve (see §2), inherently imprecise. |

**Communicating uncertainty.** Every source above is a point estimate over a distribution. The
report should present the headline as a **rounded** figure (EPA rounds its 5-year fuel number to the
nearest $50; [40 CFR 600.311](https://www.ecfr.gov/current/title-40/chapter-I/subchapter-Q/part-600/subpart-D)),
accompanied by a **low–high band** spanning the two discount rates (≈2% and ≈4% real) and the energy
escalation band. Do not print more than 2 significant figures.

### 1.3 What the headline should say

Mirror the EPA fuel-economy sticker's **comparative** construction — *"You save $X in fuel costs over
5 years compared to the average new vehicle"* (40 CFR 600.311; the reference "average vehicle" is a
fixed, published benchmark). The housing analogue:

> **"Over a 30-year mortgage, this home's energy bills and expected disaster losses run about
> $18,000 less than a typical comparable at this location — in today's dollars."**

A comparative delta is *far* more defensible than an absolute "total cost" because (a) it cancels
everything common to all homes at that location (land, most of the mortgage, base taxes), isolating
the part the *building* actually controls; (b) it never implies the number is the whole cost of
owning; (c) it degrades gracefully when a component is missing. The **baseline comparable** should be
the same idea the project already uses elsewhere: a *typical* home (e.g. the `baseline` preset, or the
county-median vintage/construction) at the **same location**, so location-driven costs net out.

### 1.4 Worked example using the project's own sample data (illustrative, not fabricated)

From `docs/data/sample-parcels.json` (same Memphis location, Memphis energy rates):

| | Baseline | ICF Passive | Annual delta (ICF better) |
|---|---|---|---|
| Energy | $133/mo → **$1,596/yr** | $52/mo → **$624/yr** | **$972/yr** |
| Expected Annual Loss | **$115/yr** | **$72/yr** | **$43/yr** |
| **Total operating+risk** | **$1,711/yr** | **$696/yr** | **≈ $1,015/yr** |

Discounting a constant $1,015/yr real over 30 years:

- at **4% real** (`a = (1−1.04⁻³⁰)/0.04 ≈ 17.29`): **PV ≈ $17,600**
- at **2% real** (`a ≈ 22.40`): **PV ≈ $22,700**
- undiscounted 30-yr sum: $30,450

So the label could state: *"~$18,000–23,000 lower operating + expected-loss cost over 30 years vs. a
typical 2000-era frame home here."* **Caveat that must ship with it:** this is *operating + risk*
cost only — it excludes the higher **purchase/construction price** of an ICF passive house, which the
label does not know. The figure answers "which home is cheaper to *run and insure*," not "which is
cheaper *all-in*." (This is the same scope limit as the EnergyGuide label, which shows operating cost,
not price.)

### 1.5 Exactly which existing quantities feed it

| Feed | Source in code | Status | Include in headline? |
|---|---|---|---|
| EAL $ (`total_loss`, and flood/tornado/seismic/fire sub-losses) | `simulate/house.py` `simulate()` | Already $/yr | **Yes** |
| Annual energy cost (`est_annual_kwh`,`est_annual_therms` × rates; `est_monthly_energy_cost`) | `enrich/energy.py` | Already $/yr | **Yes** |
| Property tax (`est_property_tax`) | `enrich/infrastructure.py` | Already $/yr, homeowner-facing | **Optional** (it's the "T" in PITI; include only if the baseline holds tax constant so it doesn't dominate the delta) |
| Maintenance reserve | *not currently emitted* | Convertible via 1%/yr rule (§2), scaled by durability/age | **Optional, flagged** |
| Public infra cost (`est_annual_infra_cost`, `fiscal_ratio`) | `enrich/infrastructure.py` | Public externality, **not** a homeowner outflow | **No** (keep separate; see §2) |

---

## 2. What's dollarizable vs. what isn't — the nine-dimension audit

Be honest: only flows that are (a) an actual homeowner cash stream and (b) already modeled belong in
the headline. Everything else is either a *public* externality, a *quality* signal, or *insufficiently
supported by current data*.

| # | Dimension | Classification | Rationale / what exists today |
|---|---|---|---|
| 1 | **Disaster Resilience** | **Already-$** | `total_loss` = EAL rate × value; sub-losses per peril. The cleanest dollar in the project. |
| 2 | **Energy Efficiency** | **Already-$** | `est_monthly_energy_cost`, `est_annual_kwh/therms` × MLGW/TVA rates. Underwriting-grade (matches the EEM/ENERGY STAR approach). |
| 3 | **Durability** | **Convertible-to-$ (approx., flag it)** | Component-lifespan/effective-age model → *implies* a maintenance/replacement reserve, but the model emits a 0–100 score, **not** replacement-cost dollars. A defensible proxy is the industry **1%/yr of value** maintenance rule (older/poorer stock 3–4%+; [Fannie Mae](https://yourhome.fanniemae.com/own/how-build-your-maintenance-and-repair-budget)), scaled by the durability score/condition/age. **Flag:** this is a rule-of-thumb, not a modeled cash flow — show it only as an optional line with a wide band, never in the precise headline. |
| 4 | **Environmental Footprint** | **Keep-qualitative** (operational leg already counted via energy) | Operational CO₂e is *derived from the same kWh/therms already dollarized under Energy* — dollarizing it again would **double-count**. Embodied carbon and water are not meaningful homeowner cash flows (water is small and already scored). A social cost of carbon could be attached for a *societal* view, but that is a different number from homeowner TCO and must be labeled as such. |
| 5 | **Infrastructure Burden** | **Split: property tax = already-$ (homeowner); infra cost/fiscal ratio = public externality, keep separate** | `est_property_tax` is a real homeowner outflow (PITI "T"). `est_annual_infra_cost`/`fiscal_ratio` measure whether the *municipality* recovers its costs — a **public** externality, explicitly documented at ±30% uncertainty (`enrich/infrastructure.py` header). It is *not* a homeowner bill and must **not** be summed into the headline; show it, if at all, in a separate "public cost" line. |
| 6 | **Health Impact** | **Keep-qualitative** | CDC PLACES chronic-disease prevalence. No defensible, non-inflammatory way to convert tract health to a dollar on a house's cost sheet. |
| 7 | **Socioeconomic** | **Keep-qualitative** | ACS income/poverty/education index. Dollarizing neighborhood socioeconomics is both statistically unsupported here and ethically fraught (redlining risk). |
| 8 | **Walkability** | **Keep-qualitative** (transportation $ is *conceptually* dollarizable but **data insufficient**) | The CNT H+T Index dollarizes location via a regression on auto ownership/use + transit — but this project has only a 0–100 Walk Score, **not** the H+T inputs. Do not invent a transportation-cost dollar from Walk Score alone. |
| 9 | **Climate Projections** | **Keep-qualitative** | Forward-looking hazard index (LOCA2 + ClimRR), reported as a mid-century band. It is a *future risk* signal that partly overlaps the present-day EAL already dollarized in Resilience; converting it to dollars would risk **double-counting** the hazard and layering scenario uncertainty onto a "hard number." Keep as a directional flag. |

**Net:** 2 dimensions are cleanly dollar (Resilience, Energy), 1 is a homeowner-facing line item
(Infrastructure→property tax), 1 is approximable with a flagged rule of thumb (Durability→maintenance),
and 5 should stay qualitative or would double-count. The headline should be built from **Resilience +
Energy** (the robust core), with property tax and maintenance as clearly-labeled optional lines.

---

## 3. Design / UX recommendation for `docs/label.html`

The label today has a `metrics-row` (flex row of `$`-figures) above the D3 bar chart, and a profile
picker. The lifetime view should slot in as a **new strip between the composite summary and the
dimension bars**, reusing the existing design tokens (`--navy`, `--card`, `.grade-*` colors), no new
dependencies.

**Recommended: a "Cost over a 30-year mortgage" comparison strip.**

1. **Headline delta chip** — one large signed number in `--navy`:
   *"≈ $18,000 lower over 30 yr vs. a typical comparable here"* with a smaller "$17.6k–22.7k across
   discount-rate assumptions" band beneath, echoing EPA's rounded "You save $X over 5 years" and the
   EnergyGuide comparability range.
2. **Tiny stacked breakdown** — a single horizontal stacked bar (D3, same idiom as the dimension bars)
   splitting the annual delta into **Energy** vs **Expected losses** (and optionally Maintenance / Tax
   as lighter segments), so the user sees *what drives it*. This mirrors KBB/Edmunds "5-Year Cost to
   Own," which itemizes fuel, maintenance, insurance, depreciation
   ([KBB](https://www.kbb.com/new-cars/total-cost-of-ownership/);
   [Edmunds TCO](https://www.edmunds.com/tco.html)).
3. **Horizon + rate controls** — a small toggle for 15 vs 30 years and a discount-rate select
   (mortgage ~4% real / social ~2% real), so the number is transparently a function of stated
   assumptions rather than a magic constant. Default 30 yr @ 4% real.
4. **Persistent scope caveat** — one muted line: *"Operating + expected-loss cost only; excludes
   purchase price, and neighborhood/health/climate factors shown above. In today's dollars."*

Because the label already switches construction profiles at a *fixed* location, the "typical
comparable" baseline is naturally the `baseline` preset — the strip can compute the delta live in JS
from the same per-parcel `$` metrics already in `sample-parcels.json` (they are all present: EAL,
monthly energy, fiscal ratio). To ship the richer version, `scripts/generate_label_data.py` would need
to also emit `est_property_tax` and the raw annual energy $ (trivial additions from existing model
output). **No backend or model change is required for the Resilience+Energy core.**

Keep the aesthetic restrained: this is a *derived* convenience number, not a tenth dimension. It must
not visually outrank the composite grade.

---

## 4. Alternative next steps (ranked)

1. **Per-dimension uncertainty / confidence display (highest fit with the project's ethos).** The
   models already carry explicit uncertainty (infrastructure ±30%; embodied carbon "order-of-magnitude";
   climate scenario bands; several BRM bonuses marked "v1 estimate/weak evidence"). Surface a small
   confidence badge or error whisker per bar and a data-quality note (the code already stores
   `location_notes`/`*_data_source`). This *strengthens* every other feature — including the money
   number — and matches the existing "flag what failed verification" culture.
2. **True comparison mode (A/B).** The label already re-renders on profile switch; add a genuine
   side-by-side of two profiles/addresses with a per-dimension **delta** column. This is the natural
   host for the money-delta strip (§3) and is low-risk UX.
3. **Methodology "show-your-math" drill-down.** Expandable per-dimension provenance (sources,
   the EAL/BRM breakdown, the exact eGRID subregion, the calibrating county's spending) — the data
   already flows through the simulator; it's a presentation layer. Builds trust and pre-empts the
   "false precision" critique.
4. **Wire live address lookup into the label page.** The address-search API and `/suggest`
   autocomplete already exist (README §Address-search API) but the `label.html` page is fixed to
   Cooper-Young. Letting a visitor score their own address is the single biggest reach/utility win,
   independent of the money feature.

---

## 5. Risks & honesty caveats

- **Scope creep into "total cost."** The number is *operating + expected-loss* cost, **not** all-in
  cost of ownership. It excludes purchase/construction price (the ICF example saves ~$18k running cost
  but costs more to build), the mortgage principal itself, closing costs, and resale/appreciation.
  Say so on the label; frame as a *difference*, not a total.
- **Double-counting.** Environmental operational CO₂ is the *same energy* already in the energy dollar;
  Climate Projections overlaps present-day EAL; property tax partly funds the infrastructure whose
  fiscal ratio is a separate dimension. Only Resilience + Energy (+ optional tax/maintenance) may be
  summed, and never the same physical quantity twice.
- **False precision.** Every input is a distribution mean (energy rates are Memphis 2024 constants; EAL
  uses model damage ratios; maintenance is a rule of thumb). Round hard (nearest ~$1,000 over 30 yr,
  per EPA's nearest-$50-over-5-yr precedent) and always show the discount-rate band.
- **Discount-rate sensitivity.** The 30-yr PV swings ~30% between 2% and 4% real (§1.4). Never present
  a single point without the band, and disclose the rate and its source/date.
- **Escalation is genuinely uncertain.** Insurance is rising double-digits (§1.2) while EIA sees
  electricity roughly tracking inflation; escalating EAL/energy would raise the headline but adds
  fragile assumptions — keep the headline at 0% real escalation and offer escalation only as a
  sensitivity.
- **Ignoring resale/appreciation.** A durable, efficient, low-risk home may also command a resale
  premium (and lower insurance) — upside the operating-cost delta omits, biasing the number
  *conservative*. Note this rather than trying to model it.
- **Location-specific rates.** Energy $ uses MLGW/TVA rates; property tax uses the county effective
  rate. The headline is only valid at the scored location — do not generalize it.
- **Equity framing.** Keep neighborhood health/socioeconomic/walkability *out* of the dollar figure;
  monetizing them invites discriminatory readings and is unsupported by the current data.

---

## 6. References

- ENERGY STAR — Energy-Efficient Mortgages (PITI − energy savings; TCO framing):
  https://www.energystar.gov/newhomes/energy-efficient-mortgages
- FHA Energy Efficient Mortgage (EEM) Fact Sheet:
  https://www.energystar.gov/ia/partners/bldrs_lenders_raters/EEM_Fact_Sheet.pdf
- U.S. DOE — Financing Energy-Efficient Homes:
  https://www.energy.gov/energysaver/financing-energy-efficient-homes
- Center for Neighborhood Technology — H+T Affordability Index (true cost of location):
  https://cnt.org/tools/housing-and-transportation-affordability-index
- CNT — H+T Index Methods (Nov 2022):
  https://htaindex.cnt.org/about/method-2022.pdf
- DOE/NREL — Low-Income Energy Affordability Data (LEAD) tool (energy burden):
  https://www.energy.gov/scep/low-income-energy-affordability-data-lead-tool-and-community-energy-solutions
- ACEEE — Energy Burden research (≥6% = high burden):
  https://www.aceee.org/energy-burden
- OMB Circular A-94 — Guidelines and Discount Rates for Benefit-Cost Analysis (real vs nominal; NPV):
  https://www.whitehouse.gov/wp-content/uploads/2023/11/CircularA-94.pdf
- OMB Circular A-94 Appendix C — real/nominal discount rates (rev. Nov 2024):
  https://www.whitehouse.gov/wp-content/uploads/2023/12/CircularA-94AppendixC.pdf
- OMB 2025 Discount Rates memo (M-25-08):
  https://bidenwhitehouse.archives.gov/wp-content/uploads/2025/01/M-25-08-2025-Discount-Rates-for-OMB-Circular-No.-A-94.pdf
- Freddie Mac Primary Mortgage Market Survey (30-yr fixed = 6.49%, 25 Jun 2026):
  https://www.freddiemac.com/pmms
- EIA — Annual Energy Outlook 2026 (residential price projections):
  https://www.eia.gov/outlooks/aeo/
- EIA — "U.S. electricity prices continue steady increase" (prices ~tracking inflation 2013–2023):
  https://www.eia.gov/todayinenergy/detail.php?id=65284
- EPA fuel-economy label — "You save $X over 5 years vs. average," rounding & reference vehicle
  (40 CFR Part 600 Subpart D / §600.311):
  https://www.ecfr.gov/current/title-40/chapter-I/subchapter-Q/part-600/subpart-D
- EPA — Fuel Economy label program:
  https://www.epa.gov/fueleconomy
- FTC EnergyGuide / Energy Labeling Rule — estimated annual operating cost + comparability range
  (16 CFR Part 305):
  https://www.ecfr.gov/current/title-16/chapter-I/subchapter-C/part-305
- FTC — EnergyGuide Labeling FAQs (national-average energy prices from DOE):
  https://www.ftc.gov/business-guidance/resources/energyguide-labeling-faqs-appliance-manufacturers
- Kelley Blue Book — 5-Year Cost to Own (itemized TCO):
  https://www.kbb.com/new-cars/total-cost-of-ownership/
- Edmunds — True Cost to Own® methodology (depreciation, financing, insurance, fuel, maintenance):
  https://www.edmunds.com/about/more-about-tco.html
- Fannie Mae — home maintenance & repair budget (1%-of-value rule of thumb):
  https://yourhome.fanniemae.com/own/how-build-your-maintenance-and-repair-budget
- S&P Global — US homeowners' rates rose double digits two straight years (2024 ≈ 10.4%):
  https://www.spglobal.com/market-intelligence/en/news-insights/articles/2025/1/us-homeowners-rates-rise-by-double-digits-for-2nd-straight-year-in-2024-87061085
- U.S. Treasury Federal Insurance Office — homeowners insurance costs rising with climate events:
  https://home.treasury.gov/news/press-releases/jy2791

---

*Prepared as a research/design proposal only. No pipeline or scoring code was modified. The
Resilience + Energy core requires no model changes; adding property-tax and maintenance lines is an
optional, clearly-flagged extension.*
