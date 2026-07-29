# Resilience Bonus Modifier Calibration Review

**Purpose:** Retire the last "v1 estimate" feature bonuses in the disaster-resilience
model by grounding each one in published literature — or removing it where the
literature says there is nothing to ground.

**Date:** July 29, 2026

**Scope:** The six modifiers in `src/housing_label/simulate/house.py` that carried no
citation or an explicitly weak one: `BONUS_SOLAR`, `BONUS_GENERATOR`,
`BONUS_SPRINKLERS`, `BONUS_LEAK_DETECT`, `BONUS_SEISMIC_RET`, `BONUS_TRUSS_16OC`.
Three further defects surfaced during the review and are documented in §7.

---

## Executive Summary

Four of the six modifiers had no defensible basis and are now **1.00**. This is a
substantive finding, not a null one: each of those features is real and often
valuable, but none of them reduces expected annual loss from the four perils this
model actually scores (flood, wind/tornado, earthquake, fire). A 1.00 records
"reviewed against the literature, no measurable effect on these perils" — which is
categorically different from an unreviewed default.

The recurring error the review exposed is **peril mismatch**: crediting a feature
against hazards it does not act on, because the feature is good for *some* reason.
Smart leak detection is evidenced against internal plumbing failure and applied to
external inundation. Backup generators are evidenced against winter freeze-burst
pipes, a peril with no leg in this model at all. The fix in each case is to say so
plainly rather than to invent a multiplier.

| Constant | Was | Now | Evidence | Basis for the change |
|---|---|---|---|---|
| `BONUS_SOLAR` | 0.97 | **1.00** | Moderate | Anti-islanding voids the rationale; wind evidence runs negative |
| `BONUS_GENERATOR` | 0.95 | **1.00** | Strong | Avoided losses are real but outside the four perils |
| `BONUS_SPRINKLERS` | 0.92 | **1.00** | Strong | No basis; the legs it touched model perils sprinklers cannot reduce |
| `BONUS_LEAK_DETECT` | 0.95 | **1.00** | Strong (wrong hazard) | Evidenced against escape-of-water, applied to external flood |
| `BONUS_SEISMIC_RET` | 0.75 | **0.75** | Moderate | Value survives; citation was a misattribution, scope redefined |
| `BONUS_TRUSS_16OC` | 0.92 | **removed** | — | No quantification exists in any source; double-counted sheathing attachment |
| `BONUS_FIRE_SPRINKLERS` | 0.40 | **0.45** | Strong | 0.40 came from NFPA's wrong occupancy row |
| `BONUS_SUMP_BACKUP` | — | **0.97** (new) | Weak-moderate | The one genuinely in-peril backup-power mechanism |

---

## 1. `BONUS_SOLAR` — 0.97 → 1.00

### The stated rationale was physically void

The prior comment credited "grid independence [that] reduces post-disaster recovery
loss." A `--solar` flag means rooftop PV. Under UL 1741 / IEEE 1547 anti-islanding
requirements, a grid-tied array without storage and a hybrid inverter disconnects
within roughly two seconds of grid loss and produces **zero** usable power for the
duration of the outage. Grid independence is a property of the battery, not the
panels — so the modifier was rewarding a capability the flagged feature does not
have.

### The property-damage evidence runs the other way

- **FEMA, Recovery Advisory 5** (Hurricanes Irma and Maria, USVI, 2018). Of seven
  buildings with rail-and-clip arrays: "Two of the roofs had all the panels blown
  off… Several panels were blown off, and several were damaged by wind-borne debris
  at another roof." The advisory directs owners to "check the roof covering for
  damage caused by wind-borne PV panels" — FEMA treats the array as a debris source
  that damages its own host roof.
- **RMI / Clinton Climate Initiative, "Solar Under Storm Part II"** (2020). From 500+
  post-event photographs across Harvey, Irma, Maria and Dorian: 96% of assessed
  systems used top-down clips, and those clips failed, with progressive failure once
  one module detaches.
- **FM Global Data Sheet 1-15** requires roof-mounted PV inspection at six-month
  intervals plus after every windstorm, hail, lightning or seismic event. No insurer
  writes an underwriting standard like that for a loss-reducing feature.
- ASCE 7-16 Chapter 29 had to *add* rooftop-PV wind load criteria. The array is an
  added load, not a shield.

No residential actuarial study comparing PV to non-PV homes shows lower loss. That
absence is itself the finding.

### Why 1.00 rather than a penalty

A defensible case exists for a small **wind-leg penalty** of 1.02–1.05, driven by
claim-severity amplification: when a wind claim requires roof replacement, the array
must be detached and reset at roughly $1,500–$6,000, a 10–25% severity increase on a
$15k–$25k partial-roof claim. This is contractor cost data rather than actuarial
data, and ignition frequency is genuinely low (~6 fires per 100,000 systems in a
German survey of ~100,000 installations), so the review recommends neutral rather
than adverse. Revisit if residential PV claim data is ever published.

**Solar is not being devalued overall.** The `solar` flag independently drives
`SOLAR_OPERATIONAL_REMAINING` in `simulate/dimensions.py`, cutting operational energy
and carbon. It keeps that well-founded credit; it simply stops claiming a
disaster-loss benefit it does not have.

---

## 2. `BONUS_GENERATOR` — 0.95 → 1.00, plus a new `BONUS_SUMP_BACKUP` = 0.97

### The benefits are real, large, and mostly outside the model

This literature is the strongest of the six — and almost all of it lands on losses
this model does not compute.

| Avoided loss | Documented magnitude | In the four perils? |
|---|---|---|
| Freeze/burst pipe during a winter outage | ~$31,400 average paid claim (State Farm, 2024–H1 2025); Winter Storm Uri: $10.35B across ~500k claims, 85% property (TDI 2022) | **No** — no winter-weather leg |
| Food spoilage | Tens to a few hundred dollars | **No** |
| Work, productivity, comfort, health | Dominant share of ICE/RMI outage cost | **No** — and out of scope for a property model |
| Sump pump operation during a flood | $10k–$50k basement restoration range | **Partially** — see below |

Discounting the *earthquake* leg to represent a January cold snap is a category
error. The honest treatment is to surface the benefit as a non-EAL note, which the
label now does.

### Magnitude sanity check

LBNL's **ICE Calculator 2.0** (Larsen et al., May 2025, 2023$) puts a residential
household's total willingness to pay to avoid a 24-hour outage at **$54.52** — all
categories, property and non-property, and a WTP construct rather than measured
damage. On a $300k home with flood+tornado+seismic summing to roughly a 0.15% EAL
rate (~$450/yr), the former 0.95 claimed ~$22/yr of avoided property damage every
year in perpetuity: approximately the household's entire annual outage welfare cost,
attributed wholly to property damage, on legs that mostly have no outage mechanism.

### What legitimately remains: `BONUS_SUMP_BACKUP` = 0.97

Loss of power is a leading sump-pump failure mode and co-occurs with the storm
driving the flood — a genuine, in-peril, same-event mechanism. Kept conservative
because this model's flood leg is FEMA-flood-zone depth-damage (external
inundation), while sump-pump water is typically groundwater and surface
infiltration: overlapping but not identical loss populations, and usually excluded
from standard HO policies absent a water-backup endorsement.

Note the contrary evidence considered and rejected: insurers do advertise ~5%
homeowners premium credits for standby generators. Every traceable source is a
manufacturer or an agency blog rather than a rate filing, and a homeowners premium
covers all perils *including* the freeze and water damage the credit is for — so it
cannot be carried across to a four-peril EAL that excludes exactly those losses.

---

## 3. `BONUS_SPRINKLERS` — 0.92 → 1.00

The claim implied by 0.92 was that residential fire sprinklers reduce expected annual
**flood, tornado and earthquake** property loss by 8%. Four independent lines
disqualify it.

**The model's own legs contain nothing a sprinkler could reduce.** `calc_seismic_eal`
is a pure shaking fragility — Poisson rates against a HAZUS-MH PGA→damage-ratio step
function — with zero fire-following-earthquake content. The flood leg is FEMA P-259
depth-damage; the tornado leg is FEMA NRI wind. A modifier cannot reduce a loss the
leg never counted.

**Fire-following-earthquake does not rescue it.** FFE is real and can dominate a
major-earthquake loss — the ShakeOut Scenario models ~1,600 post-earthquake ignitions
contributing **$87B of $191B** total. But NFPA 13D systems are fed from the domestic
water main, which is exactly what fails (Northridge: 23,200+ service-line breaks;
Scawthorn/CSSC identifies water-system failure as the controlling factor in
post-earthquake conflagration), and 2024 IRC §R301.2.2.10 exempts residential
sprinkler systems from seismic bracing in the highest seismic design categories.

**The documented effect points the other way.** FM Global found that in the 1994
Northridge earthquake, **74% of surveyed facilities in areas of highest ground
shaking with inadequately braced sprinkler systems experienced leakage or failure**
(cited in FEMA E-74). ATC-69 documents Olive View Hospital, where the structure
performed well but "compromised fire sprinkler and chilled water piping … led to
evacuation," and notes secondary leak damage as "a major source of costly repairs."
Tian, Filiatrault & Mosqueda (*Earthquake Spectra* 30(4), 2014) established water
leakage fragilities for 48 sprinkler tee joints. This argues an earthquake modifier
**above** 1.00, not below.

**No source credits sprinklers against flood, wind or earthquake property loss.**
Insurance sprinkler credits are fire-line rating credits only.

Narrowing to the earthquake leg for fire-following was considered and rejected: an
unquantified-and-probably-small benefit combined with a documented-but-unquantified
harm yields a number defensible in neither direction. 1.00 is the honest answer.

---

## 4. `BONUS_LEAK_DETECT` — 0.95 → 1.00 (peril mismatch)

The device class is well evidenced. Every study measures **escape of water /
non-weather water damage** — burst supply lines, failed water heaters, appliance hose
failures:

| Source | Population | Effect |
|---|---|---|
| LexisNexis / Flo by Moen (2020) | 2,306 device homes vs 1.3M controls | −96% claim frequency, −72% severity |
| Nationwide + Resideo (2018–2022) | Nationwide policyholders | −$4,000 average claim cost |
| Carrier synthesis (2024) | — | Auto-shutoff 60–80% effective; alarm-only 15–35% |

The headline 96% is a vendor-partnered correlation study with severe self-selection
(households buying a $500 shutoff are maintenance-attentive, and many install after a
loss), so the 60–80% carrier band is the defensible figure.

**None of it transfers to this model's flood leg**, which is unambiguously external
inundation: `score/resilience.py` computes NFIP-zone AEP × mean damage ratio with
FEMA P-259 depth-damage curves and no plumbing, sump or non-weather-water component.
Four confirmations:

1. **Mechanism.** Auto-closing the supply main is inert against water entering
   through walls, foundation and openings.
2. **FEMA gives it no credit.** NFIP Risk Rating 2.0 recognises exactly three
   building-level mitigations — elevating the building (~34%), elevating machinery
   (~5%), flood openings (~5%). The model already credits two of the three correctly
   via `BONUS_ELEVATION_*` and `BONUS_FLOOD_VENTS`.
3. **FEMA P-312** enumerates residential flood-protection measures (elevation,
   relocation, barriers, dry and wet floodproofing, demolition). Leak detection is
   absent. `BONUS_BACKFLOW_VALVE` traces to this document; this constant cannot.
4. **The warning-value argument fails on its own numbers.** Flood-warning benefit is
   a function of lead time. The USACE Day Curve gives 23% damage reduction at 12
   hours and **zero at zero warning**; Carsell, Pingel & Ford (2004) find 24% avoided
   *contents* damage at 6 hours. A floor sensor alarms at t=0 of inundation — below
   the left edge of every published warning-benefit curve — and cannot reach an
   absent occupant.

**Where it belongs.** A future non-weather-water-damage peril, which is ~24% of
homeowners claims (~1 in 60 insured homes per year, ~$15,400 average — Triple-I) and
larger than tornado for most of the country. Defensible modifiers there would be
~0.30–0.40 for automatic in-line shutoff and ~0.75–0.85 for alarm-only sensors. The
flag is retained with no credit rather than deleted, since it appears in the public
API `upgrades` parameter, the CLI and both docs pages.

---

## 5. `BONUS_SEISMIC_RET` — 0.75 retained, redefined and re-cited

### The FEMA P-420 citation was a misattribution

FEMA P-420, *Engineering Guideline for Incremental Seismic Rehabilitation* (2009), is
a companion to FEMA 395–400 addressing phased rehabilitation of **institutional and
commercial** buildings. It says nothing about one- and two-family dwellings, cripple
walls, or a ~25–40% loss reduction. The current dwelling standard is **FEMA P-1100**
(2019) — which publishes **no loss-reduction percentages at all**, being a
prescriptive prestandard that explicitly disclaims damage prevention.

### What the value actually rests on

PEER Report 2020/22 (Welch & Deierlein, Stanford Blume Center) computes FEMA P-58
losses for 32 index-building variants across four California sites, for two distinct
foundation vulnerabilities:

| Retrofit | EAL residual (retrofit ÷ existing) |
|---|---|
| **Cripple-wall bracing** (Tbl 7.13/7.14, n=32) | min 0.159, median 0.271, max 0.470 |
| **Stem-wall sill anchorage, no cripple wall** (Tbl 7.38/7.39, n=16, one-story) | min 0.574, **mean 0.713**, max 0.848 |

The second row — bolting *without* bracing — lands almost exactly on the 0.75 already
in the file, reached from an entirely different direction. The value was right; its
justification and scope were wrong. `BONUS_SEISMIC_RET` is now defined as the
stem-wall anchorage case.

Independent corroboration: Moody's RMS for the CEA (2023) reports loss reductions "as
high as 70 percent" for cripple-wall retrofit "much larger than for retrofitting
those same homes on stem walls where loss reductions were as high as 35 percent." The
CEA's own actuarially-mandated premium discounts show the same split — 20–25% for
raised foundations versus 10–15% for other non-slab.

### The double-count, and the supersede rule

Cripple-wall bracing *is* the canonical US dwelling retrofit, and FEMA P-1100's
crawlspace scope bolts the sill **and** braces the wall — you cannot brace a cripple
wall to an unbolted sill. Stacking gave `0.45 × 0.75 = 0.34` for one physical
intervention; adding the other two seismic flags reached 0.258, a 74% cut exceeding
the best single case in PEER's 32-case study. The flags are now mutually exclusive
via `SEISMIC_FOUNDATION_FLAGS`, with cripple-wall bracing superseding — the same
composite-supersedes-components pattern as the FORTIFIED tiers.

### Caveats recorded honestly

- **One-story only.** PEER computes the two-story stem-wall retrofit as net-neutral
  to net-harmful: connection failure and sliding "results in a base isolation effect
  for the superstructure." The model has no story count on the seismic leg.
- **California ground motions only.** Four CA sites; this repo's default locale is
  Shelby County (New Madrid), with different spectral shape and an unvalidated
  transfer.
- **HAZUS cannot supply this.** The Hazus Earthquake Model indexes W1 fragility by
  Seismic Design Level, with no retrofitted-vs-unretrofitted curve pair — and design
  level encodes original code vintage, not current foundation condition.

### Base isolation removed from this constant

Base isolation is a ~0.25 intervention (Dong et al. 2025: EAL ~4× lower than
fixed-base under FEMA P-58; Jampole et al. 2020: near-elimination of light-frame
superstructure damage), targets a different failure mode, and is essentially absent
from US single-family housing on cost grounds. One constant cannot honestly serve
both it and a 0.75 bolt-only retrofit, and as a self-reported checkbox it would draw
more false positives than true ones. The flag is relabelled "Foundation anchorage
retrofit (bolting)".

---

## 6. `BONUS_TRUSS_16OC` — removed

No test program, fragility model, FEMA MAT report, or claims study isolates framing
spacing as a wind variable. This was an explicit negative result, consistent across
APA, IBHS/FORTIFIED, FEMA, ASCE/IRC prescriptive tables, the ARA studies underpinning
Florida's wind-mitigation credits, and the UF/Clemson/FIU wind-engineering
literature. Every quantified source treats **fastener schedule as the governing
variable and 24" o.c. as the fixed baseline**.

**The decisive finding is that regulators treat spacing as fungible with, not
additional to, fastening.** Florida's Uniform Mitigation Verification Inspection Form
(OIR-B1-1802) defines each roof-deck attachment category as "(spaced a maximum of 24"
o.c.)" and then names spacing as a substitute pathway: "…**-OR- any system of screws,
nails, adhesives, other deck fastening system or truss/rafter spacing that has an
equivalent mean uplift resistance of 182 psf**." Truss spacing earns credit only
through the deck uplift capacity it produces, and lands in the *same* rated bin as a
fastener upgrade — never on top of one.

So `truss_16oc` and `ring_shank_nails` were two routes to a single physical quantity,
applied as independent multipliers: `0.88 × 0.92 = 0.81`, a 19% wind-EAL reduction
for the roof deck alone, stacking further with `sealed_roof_deck` (0.80). For scale,
ARA prices its "Enhanced Roof Deck" — 5/8" plywood *and* ring-shank nails, layered on
top of the already-best Level C 6"/6" schedule — at a loss relativity of **0.96–0.99**.

Secondary reasons the flag is not worth keeping at a reduced value: 24" o.c. is the
near-universal baseline for metal-plate-connected residential trusses (IRC §R802.10.2
caps trusses at 24"; APA T325D writes one schedule for "24 inches on center or
less"); where 16" appears it is usually a snow or tile dead-load driver rather than a
wind decision; it is confounded with other construction-quality markers the BRM
already handles; and it is not reliably self-reportable — ARA notes deck attachment
can practically only be established "by a trained inspector going into the attic."

A tombstone comment records this so the flag is not reintroduced without a quantified
source.

---

## 7. Defects found during the review

### 7.1 Sprinklers discounted the wildfire EAL

`fire_raw = FIRE_EAL_BASE + wildfire_base`, and the sprinkler modifier was applied to
the whole `fire_adj`. Interior NFPA 13D sprinklers were therefore credited with
cutting **wildfire** loss by 60%. The NFPA figure is derived entirely from interior
NFIRS structure fires, and IBHS attributes wildfire structure survival to exterior
hardening — Class A roof, 1/8" ember-resistant vent mesh, noncombustible 0–5 ft zone,
deck detailing — stating sprinklers should "be a supplement to, and not a replacement
for" those measures. In a WUI county where `wildfire_base` dominates the 0.0002
structural baseline, this was a large unearned credit.

**Fixed:** the modifier now applies to the structural fire term only. On a test parcel
with a wildfire base 15× the structural baseline, the sprinkler credit drops from 55%
of the whole leg to 3.4%.

### 7.2 `BONUS_FIRE_SPRINKLERS` = 0.40 was not traceable

NFPA's *US Experience with Sprinklers* (McGree, April 2024, NFIRS 2017–2021) reports
**55%** lower average property loss per fire for **home** fires ($10.5M vs $23.5M per
1,000 fires, Fig. 20) and **60%** for the broader **residential** occupancy class,
which also covers hotels, motels and dormitories. The 0.40 read the residential row;
this model scores homes. The 2017 edition shows the same split (58% home, 63%
residential), so it is stable across editions.

A larger caveat is the counterfactual: NFPA compares against homes with "no AES,"
mixing homes with and without smoke alarms. NIST's **NISTIR 7451** ran the
apples-to-apples comparison and found one- and two-family dwellings with wet-pipe
sprinklers had a **32% reduction over dwellings with smoke alarms only** — the honest
marginal effect, since ~97% of US homes have alarms. The defensible bracket is
therefore 32–55% (multiplier 0.68–0.45).

**Changed to 0.45**, the optimistic end, with the band recorded in the comment.

Note: advocacy-group figures (Home Fire Sprinkler Coalition et al.) circulate claims
like "$2,166 vs $45,019 average loss," implying a 95% reduction — roughly double
NFPA's own measurement. None were relied on. The widely-repeated blog claim that
"NFPA data shows sprinklers slash property damage up to 60%" is the same
residential-row misreading that likely produced the original 0.40.

### 7.3 General modifiers were mislabelled as "all hazards"

`BONUS_MODIFIER_DESC` advertised solar, generator, passive house and sprinklers as
"×N all hazards", but `gen_mod` is applied to flood, tornado and seismic only — the
fire leg is deliberately excluded. `sync_docs.py` already grouped them correctly, so
only the CLI readout was wrong. Fixed separately.

---

## 8. Known limitations and follow-on work

- ~~**No applicability gating.**~~ **Resolved.** Both foundation retrofit tiers are
  now gated on `foundation` (`CRIPPLE_WALL_FOUNDATIONS`,
  `SEISMIC_ANCHORAGE_FOUNDATIONS`), implementing what
  `feature-modifiers-research.md` §"Applicability Flags" had specified but the code
  never applied. Cripple-wall bracing scores only on raised foundations (crawl,
  partial basement) — a slab has no cripple wall, and a full basement has
  full-height walls instead. Sill anchorage is the broader tier and needs only a
  non-slab foundation; on a slab the sill bolts into the slab itself, which is not
  the stem-wall case PEER-CEA measured. This mirrors the CEA's own eligibility
  split (20–25% raised, 10–15% other non-slab, nothing on slab). A claimed but
  impossible upgrade earns no credit and is named in a user-facing note rather than
  being silently dropped. `seismic_hold_downs` is deliberately left ungated — it
  acts on superstructure shear walls, not the foundation connection.
- **No seismic modifier floor.** The wind leg has FORTIFIED tiers that supersede and
  the flood leg has mutually-exclusive elevation; the seismic leg has neither beyond
  the new foundation-tier rule, making it the easiest leg to drive toward zero.
- **`BONUS_RING_SHANK_NAILS` = 0.88 warrants its own review.** Its comment cites
  "IBHS: 12-25% better withdrawal resistance" — a *material property* being read
  directly as an EAL multiplier, which is the same category error corrected
  elsewhere in this pass. ARA prices a verified ring-shank + 5/8" deck upgrade above
  Level C at 0.96–0.99.
- **`BONUS_SEISMIC_HOLD_DOWNS` doc/code drift.** `feature-modifiers-research.md`
  recommends 0.75; the code uses 0.85. One is stale. Hold-downs also partially
  overlap cripple-wall bracing, since hold-downs at braced-panel ends are part of the
  P-1100 detail.
- **Metric composition.** This model's HAZUS-derived damage ratios are ground-up
  structural loss; PEER's EAL is FEMA P-58 repair cost normalised by replacement
  value. Close enough to compose, but not identical metrics.
- **A non-weather-water peril** would give leak detection a legitimate home and would
  cover ~24% of homeowners claims that the four-peril model currently ignores
  entirely.

---

## 9. Sources

**Solar / backup power**
- FEMA, *Rooftop Solar Panel Attachment: Design, Installation, and Maintenance*, Hurricanes Irma and Maria in the USVI, Recovery Advisory 5, April 2018 (rev. Aug 2018).
- RMI / Clinton Climate Initiative / FCX Solar, *Solar Under Storm Part II: Select Best Practices for Resilient Roof-Mount PV Systems with Hurricane Exposure*, 2020.
- FM Global, *Property Loss Prevention Data Sheet 1-15: Roof-Mounted Solar Photovoltaic Panels*.
- UK Building Safety Regulator / HSE (OFR Consultants), *Thermal exposure to roofs from fires involving photovoltaic panels*, Feb 2026.
- Larsen, P. et al., *ICE Calculator 2.0: Final Report for Phase 1*, Lawrence Berkeley National Laboratory, May 2025 (2023$).
- RMI, *Battery Energy Storage Systems as a Resilience Solution*, 2026.
- Texas Department of Insurance, *Insured Losses Resulting from the February 2021 Texas Winter Weather Event*, March 2022.
- NREL, *Valuing the Resilience Provided by Solar and Battery Energy Storage Systems*, NREL/TP-7A40-70679, 2018.
- EPA / CDC mold guidance: dry water-damaged materials within 24–48 hours.

**Fire sprinklers**
- McGree, T., *US Experience with Sprinklers*, NFPA Research, April 2024 (NFIRS 2017–2021).
- Ahrens, M., *U.S. Experience with Sprinklers*, NFPA, July 2017 (NFIRS 2010–2014).
- Butry, D.T., Brown, M.H. & Fuller, S.K., *Benefit-Cost Analysis of Residential Fire Sprinkler Systems*, NISTIR 7451, NIST, 2007.
- FM Global, *Lack of Earthquake Bracing on Sprinkler Systems* (P0042), cited in FEMA E-74, *Reducing the Risks of Nonstructural Earthquake Damage*, Dec 2012.
- Applied Technology Council, *ATC-69: Reducing the Risks of Nonstructural Earthquake Damage — State-of-the-Art and Practice Report*, FEMA/DHS, 2008.
- Tian, Y., Filiatrault, A. & Mosqueda, G., "Experimental Seismic Fragility of Pressurized Fire Suppression Sprinkler Piping Joints," *Earthquake Spectra* 30(4):1733–1748, 2014.
- Porter, K., Jones, L., Cox, D., Scawthorn, C., Seligson, H. et al., "The ShakeOut Scenario," *Earthquake Spectra* 27(2), 2011; USGS OFR 2008-1150.
- Scawthorn, C., *Water Supply in regard to Fire Following Earthquake*, California Seismic Safety Commission CSSC 2011-02, 2011.
- 2024 IRC §R301.2.2.10 (sprinkler systems exempt from bracing in SDC D0/D1/D2).
- IBHS, *Wildland Fire Embers and Flames: Home Mitigations That Matter*.

**Leak detection**
- LexisNexis Risk Solutions, *Loss Correlation Study: In-Line Water Shutoff*, May 2020.
- Nationwide Insurance / Resideo, claims data 2018–2022.
- Insurance Journal, "Insurers Making Waves with Wider Use of IoT Leak, Temp Sensors," Jan 2022.
- Insurance Information Institute, *Facts + Statistics: Homeowners and renters insurance*, 2019–2023 data.
- FEMA / NFIP, *Risk Rating 2.0 — What Goes Into a Rate?*
- FEMA P-312, *Homeowner's Guide to Retrofitting*, 3rd ed., 2014.
- USACE, ETL 1110-2-540 (1996), "Day Curve," via HEC documentation.
- Carsell, K.M., Pingel, N.D. & Ford, D.T., "Quantifying the Benefit of a Flood Warning System," *Natural Hazards Review* 5(3):131–140, 2004.

**Seismic retrofit**
- Welch, D.P. & Deierlein, G.G., *Technical Background Report for Structural Analysis and Performance Assessment (PEER-CEA Project)*, PEER Report 2020/22, 2020.
- Cobeen, K. et al., *Project Technical Summary (PEER-CEA Project)*, PEER Report 2020/12, 2020.
- Moody's RMS / California Earthquake Authority, *CEA Invests in Research and Development to Enhance Brace and Bolt*, Oct 2023.
- California Earthquake Authority, *Earthquake Insurance Policy Premium Discounts* (CIC §10089.40).
- FEMA P-1100, *Vulnerability-Based Seismic Assessment and Retrofit of One- and Two-Family Dwellings*, Vol. 1 Prestandard, Oct 2019.
- FEMA P-420, *Engineering Guideline for Incremental Seismic Rehabilitation*, May 2009 (cited to document the misattribution).
- Dong, C., Sullivan, T. & Pettinga, D., "Investigating the impacts of design ductility values and importance levels on the performance of base-isolated buildings in New Zealand," *Bulletin of the NZ Society for Earthquake Engineering* 58(3):169–186, 2025.
- Jampole, E., Swensen, S., Miranda, E. & Deierlein, G.G., "Parametric Study of Seismic Isolation Properties for Light-Frame Houses," *Journal of Structural Engineering* 146(10):04020207, 2020.
- FEMA, *Hazus Earthquake Model Technical Manual, Hazus 6.1*, July 2024.
- Schiller, B. et al., "Experimental damage observations and component fragilities for wood-framed houses with cripple walls," *Earthquake Spectra*, 2023.

**Truss spacing**
- APA – The Engineered Wood Association, *Roof Sheathing Fastening Schedules for Wind Uplift*, Form T325D, rev. March 2006.
- Florida OIR, *Uniform Mitigation Verification Inspection Form* OIR-B1-1802 (Rule 69O-170.0155).
- Applied Research Associates, *2008 Florida Residential Wind Loss Mitigation Study*, ARA Report 18401, for Florida OIR.
- Showalter, J., "Wood Roof Detailing for Wind Uplift," *STRUCTURE Magazine*, 2022.
- FEMA 499 / P-499, Technical Fact Sheet No. 18, *Roof Sheathing Installation*, 2005/2010.
- IBHS, *FORTIFIED Home 2025 Standard and Technical Documents*.
- ICC, IRC Table R602.3(1) and §R802.10.2; ASCE 7-16 §26.2 and Fig. 30.3-2.
