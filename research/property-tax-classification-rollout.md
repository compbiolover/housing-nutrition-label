# Scaling property-tax classification to 51 jurisdictions

Plan for extending the Tennessee split-roll correction shipped in #226 to every US
jurisdiction the Infrastructure Burden dimension can actually score.

---

## Context

#226 taught the model that Tennessee reclassifies residential property containing 2+
**rental** units as industrial-and-commercial, assessed at 40% instead of 25%
(Tenn. Const. art. II § 28; Tenn. Code Ann. § 67-5-501(11), § 67-5-801). A Memphis
apartment building generates **1.6×** the property tax the flat residential ratio credited
it — the difference between scoring as a fiscal drain and a net contributor.

Tennessee is not unusual. Spot-checking the Southeast already confirms:

| State | Split | Multiplier |
|---|---|---|
| Alabama | Class III 10% → Class II 20% (apartments in Class II) | **2.00×** |
| South Carolina | 4% owner-occupied legal residence → 6% other | **1.50×** |
| Mississippi | Class I 10% → Class II 15% | **1.50×** |
| Louisiana | 10% residential improvements → 15% other | **1.50×** |

In each of those states the model currently understates rental-housing property tax by
50–100%. But the correction is switched **off everywhere except Shelby County**:
`src/housing_label/enrich/region_context.py` hard-codes `"classification_state": None`
and takes no state parameter at all. The fix that made a Memphis tower legible is
invisible in Birmingham, Columbia, Jackson, and New Orleans.

## Scope — what "all states and territories" resolves to

Verified against the bundled crosswalks:

| Jurisdiction | Status | Why |
|---|---|---|
| 50 states | **In** | Full coverage in `govfinance_county.csv` + `property_tax_county.csv` |
| DC | **In** | Present in every bundled crosswalk as `11001` |
| Puerto Rico | **Out** | 72 municipios in `property_tax_county.csv` but **zero** rows in `govfinance_county.csv`; CRIM administers PR property tax on a wholly different basis |
| AS, GU, MP, VI | **Out** | Absent from every fiscal, socioeconomic, and home-value crosswalk — the dimension cannot score them at all |

**51 jurisdictions.** The territory gap is upstream data availability, not a scoping
preference.

## Decisions

1. **Sourcing — index, then primary.** Lincoln Institute's *Property Tax Classification*
   database finds *which* states classify; every encoded number is verified against that
   state's own constitution, code, or DOR manual before it lands. Lincoln is the search
   index, never the cited authority. Index/primary disagreement ⇒ the state stays
   **unencoded**.
2. **51 jurisdictions**, territory gap documented.
3. **Single-family rentals — conservative default plus an explicit input.** An unqualified
   single-family home stays owner-occupied and gets no uplift; a new `owner_occupied`
   input lets someone who knows otherwise get the right number.

### The governing principle: when in doubt, under-correct

Every ambiguity resolves toward *no correction*. The accessors return "no change" rather
than a best guess, unresearched states are no-ops, local-option states are no-ops, and
exemption-driven differentials are excluded entirely. An under-corrected rental building
looks like today's behavior; an over-corrected one silently invents tax revenue.

---

## Phase 0 — Foundation (before any new state data)

No new jurisdictions. Pilot-path behavior must be bit-identical at the end; the national
path gains the multiplier plumbing but with only TN encoded, so only TN parcels move.
That is deliberate — it lands the mechanism with a near-zero distribution shift, so any
large shift in a later region is a data error rather than mechanism churn.

### 0.1 `src/housing_label/data/states.py` (new)

No shared FIPS↔USPS helper exists. Three build scripts each carry a copy
(`build_air_quality.py:82`, `build_water.py:71`, `build_utility_rates.py:32`) and
`utility_rates._STATE_RATES` embeds a fourth in its data tuples.

- `STATE_FIPS_TO_USPS` — 50 states + DC + PR (`"72"`, present in `property_tax_county.csv`)
- `SCORED_JURISDICTIONS` — the 51 USPS codes eligible for a rule
- `usps_for_fips()` / `fips_for_usps()` — tolerant of ints/floats/NaN, `.zfill(2)`, mirroring
  `region_context.normalize_fips`
- `CENSUS_DIVISION` — USPS → one of nine divisions, so sequencing, the coverage report, and
  any future grouping share one source of truth

Replace the three build-script dicts with imports. **Do not** rewrite
`utility_rates._STATE_RATES` to drop its postal codes — it is a bundled data literal and
retyping it risks a transcription error for no functional gain. Instead assert agreement
between the two tables in a test; that catches a typo in either for free.

### 0.2 Classification schema — `src/housing_label/data/assessment.py`

Keep the inline-literal convention (legal text is not a data feed), but a 3-tuple does not
survive ten fields. Frozen dataclass, table stays an inline dict keyed by USPS.

**Rule types:**

| Constant | Covers | Mechanism |
|---|---|---|
| `RULE_ASSESSMENT` | TN, SC, AL, MS, LA | Two statutory assessment ratios |
| `RULE_RATE` | DC, MA, RI, NYC | Uniform ratio, differential class *rate* |
| `RULE_UNIFORM` | GA, NC, VA, KY, and every "researched, found an exemption not a classification" state | No correction; the record proves it was researched |

Local option is **orthogonal**, not a fourth type: MA is `RULE_RATE` + `local_option`;
IL is `RULE_ASSESSMENT` + `local_option`.

**Fields:** `usps`, `rule_type`, `threshold_basis`, `rental_unit_threshold`,
`residential_assess_ratio`, `commercial_assess_ratio`, `residential_rate`,
`commercial_rate`, `effective_multiplier`, `local_option`, `sub_state`, `authority`,
`verified`, `notes`. Module-level `LAW_AS_OF` plays the `DATA_VINTAGE` role.

Two fields deserve explanation:

- **`threshold_basis`** (`"rental_units"` | `"dwelling_units"`) is required because NYC's
  Class 1 vs Class 2 keys on **dwelling units** (1–3 family vs 4+), not rental units.
  Without it NYC cannot be encoded correctly at all.
- **`effective_multiplier`** overrides the derived ratio. For rate-differential
  jurisdictions the published effective differential is often the *primary* datum, and
  deriving it from ratio arithmetic is wrong because assessment ratios and class rates can
  move in opposite directions — NYC Class 2's higher ratio is partly offset by rate and by
  Class 1 assessment caps.

`sub_state` is keyed by **5-digit county FIPS**, the finest geography `region_context`
resolves. NYC's five boroughs and Cook County are cleanly keyable; MA's 351 municipal
residential factors are not, so MA stays `local_option` with an empty map and no
correction.

### 0.3 The multiplier accessor — what unlocks the national path

The national path passes `assess_ratio=1.0` against an ACS *observed effective rate*
(B25103 median taxes ÷ B25077 median value) computed over **owner-occupied** homes. That
rate already embeds owner-occupied class treatment, so swapping in an absolute commercial
ratio would double-count — which is why classification is off there today.

The correct correction on that path is **multiplicative**, and the argument is exact: *the
multiplier's denominator must match the baseline embedded in the observed rate.* In TN
owner-occupied homes are the 25% class; in SC the 4% legal-residence class; in DC Class 1.
In every case the ACS owner-occupied baseline **is** the residential denominator. That is
precisely why the multiplier is well-founded here and the absolute ratio is not — and it
is also why the same form works for rate-split states where only millage differs.

Three accessors:

- `classified_assess_ratio(...)` — absolute; Shelby statutory path only. Returns `None` for
  every `RULE_RATE` state, every `RULE_UNIFORM` state, and every non-reclassified parcel.
  (Renamed from `commercial_assess_ratio`; two call sites, straight rename.)
- `classification_multiplier(...)` — relative; national path. Returns exactly `1.0` unless
  reclassified. `effective_multiplier` if set, else `commercial/residential` legs.
- `classification_for(...)` — always-returns-a-dict reporting accessor per the loader
  convention, carrying the authority and vintage so a label can eventually say *"assessed
  as commercial under Tenn. Const. art. II § 28."*

**`separately_parceled` escape hatch.** A 157-unit condominium tower is 157 parcels each
holding at most one rental unit, but the pipeline gets `units` from NSI for a *structure*
and cannot tell a condo tower from a rental tower. Today that is one over-correction risk
in one state; across several Type B states it multiplies. Add
`separately_parceled: bool | None` to `rental_unit_count` and both computational accessors
— when `True`, rental units are forced to ≤1, short-circuiting reclassification
everywhere. Cleaner than overloading `owner_occupied`, which means something else.

### 0.4 Threading state through

**Derive the state inside `region_context` from `fips[:2]`** rather than plumbing
`Location.state_fips` down from `dimensions.py`. It is strictly less code and strictly
fewer failure modes: no new parameter at `dimensions.py:678-681`, the batch path gets it in
the same edit, and there is no possible state/county mismatch to reason about.
(`Location.state_fips` at `location.py:48` is itself populated with a `county_fips[:2]`
fallback, so the two cannot disagree in practice.)

The returned params dict gains **two new keys rather than reusing one**:

```
"classification_state":      None,       # UNCHANGED — absolute path stays disabled
"classification_rate_state": <usps>,     # NEW — multiplier path
"classification_county_fips": <fips>,    # NEW — sub-state lookup
```

One key with two meanings is how a 1.6 × 1.6 = 2.56 bug gets written. The existing
`tests/test_tier3_enrich.py:66` assertion stays true and stays meaningful.

### 0.5 `src/housing_label/enrich/infrastructure.py` — guard first, compute second

If both `classification_state` and `classification_rate_state` are non-`None`, **raise
`ValueError`**. A caller wiring up both would apply the correction twice, which is exactly
the failure this design exists to prevent. A loud failure in a pure function is cheap and
CI catches it; a silent precedence rule is not auditable.

Emit `classification_multiplier_applied` (default 1.0) next to `assess_ratio_applied`, add
it to `ADDED_COLUMNS` and the docstring column list, and surface it in the payload. The
correction must be *visible* in the row or nobody can audit it in a batch CSV or on a label.

### 0.6 Tenure input

Add `owner_occupied` to the CLI (`--owner-occupied` / `--rental`) and the API label
endpoint. `dimensions.py` **already reads** `cfg.get("owner_occupied")` — only the input
surface is missing.

### 0.7 Calibration — `scripts/calibrate_infra_breakpoints.py`

**(a) Stop duplicating the county-param assembly.** Lines 104–113 hand-rebuild `mult`,
`fee`, and `municipal_rate`, mirroring `region_context.py:67-83`. This is dormant drift
today and actively dangerous once classification lands: a fork means the yardstick is built
by a different model than the app runs, which invalidates the entire "score ≈ national
percentile" claim. Refactor `build_distribution()` to call `infra_params_for_county(fips)`
and pass the result straight into `enrich_row`. Shelby returns `None` — special-case it
explicitly so the skip is a decision, not an accident.

**Preserve the Puerto Rico skip.** PR currently drops out at the `grow is None` check
because it is absent from `govfinance_county.csv`. After the refactor both loaders have
national fallbacks, so PR could silently re-enter the reference distribution at
national-average cost. Keep the explicit skip and test it.

**(b) Tenure enters `DENSITY_ARCHETYPES`.** Extend to
`(label, du_acre, share, is_urban, units_on_parcel, renter_share)`:

| archetype | du/acre | share | units | renter share |
|---|---|---|---|---|
| rural / exurban | 0.5 | 0.12 | 1 | 0.140 |
| large-lot suburb | 1.5 | 0.18 | 1 | 0.140 |
| standard suburb | 4.0 | 0.35 | 1 | 0.140 |
| compact suburb / townhome | 8.0 | 0.20 | 1 | 0.140 |
| urban multifamily (5-19) | 20.0 | 0.069 | 10 | 0.892 |
| large multifamily (20+) | 50.0 | 0.081 | 50 | 0.868 |

Renter shares from ACS 2024 5-yr B25032. Each archetype contributes **two** weighted points
— an owner leg and a renter leg — with total weight unchanged, so the only delta to the
distribution is reclassification of renter legs in states that have a rule. Fully
attributable. Hold `du_acre` and `share` fixed here; refining the archetype roster is a
separate, separately-reviewed change — which is what the large-multifamily row below was,
landing after Phase 4.

**(c) `INFRA_XS_BASIS` — the drift guard.** Next to `INFRA_XS` in
`src/housing_label/score/all_dimensions.py`, record a sorted tuple of the jurisdictions
carrying an active correction when the constant was last computed, e.g.
`("AL:2.00", "LA:1.50", "MS:1.50", "SC:1.50", "TN:1.60")`. A test recomputes it from
`assessment.py` and asserts equality.

This makes *"you added a state and forgot to recalibrate"* a red CI failure. A sorted tuple
beats a hash because the diff **is** the changelog — a reviewer sees exactly which
jurisdictions entered the reference distribution. It is the single most important test here.

### 0.8 Tests

- `tests/test_states.py` (new, dual-mode) — FIPS↔USPS round-trip, 51 jurisdictions, messy-
  input normalization, `utility_rates` cross-check, `CENSUS_DIVISION` covers each exactly once.
- `tests/test_assessment.py` — every existing TN case must pass **unchanged in value** after
  the rename; that is the regression signal for the whole refactor. Add schema-integrity
  (every record has a non-empty `authority` and a parseable, non-future `verified`; the
  fields its `rule_type` requires), multiplier-equals-ratio-of-legs (catches a pre-divided
  number pasted where the two source legs belong), `RULE_RATE` ⇒ absolute accessor always
  `None`, unresearched/uniform/local-option ⇒ multiplier exactly `1.0`,
  `separately_parceled=True` suppresses reclassification everywhere, the both-kwargs
  `ValueError`, and a documented sanity ceiling on the multiplier.
- **Add a multi-unit golden case.** All six cases in `tests/test_golden_label.py` are
  single-family at `units=1`, so classification never fires in the snapshot and only the
  yardstick is locked. Add `("quadplex_shelby", "quadplex", 35.13, -89.99)` — the preset
  already exists — so the correction itself is numerically pinned. Add a second in a Type B
  state once Phase 1 lands, to pin the *multiplier* path too.

### 0.9 Docs

- `research/property-tax-classification-research.md` (new) — the per-jurisdiction table and
  the methodology preamble.
- `scripts/report_classification_coverage.py` (new) — prints per-division rule type,
  multiplier, authority, verified date and age, plus the population-weighted share of US
  households covered. Status tool, print-to-stdout per `build_utility_rates.py`.
- `README.md` — the *"Known gap: only Tennessee is encoded"* line becomes wrong the moment
  Phase 1 lands; rewrite it in Phase 0.
- `docs/methodology.html` — generalize the "Tax Classification of Rental Housing" section
  from "Tennessee, the pilot state" to the rule taxonomy plus a coverage count. Not under
  `sync_docs.py` management, so a hand edit.

---

## Regional sequence

Census divisions, ordered by rule density and schema-exercise value, with the sub-state
machinery deferred until the mechanism is proven. "Southeast" as asked for = Phases 1–2.

| Phase | Division | Jurisdictions | Why here |
|---|---|---|---|
| **1** | East South Central | KY, TN, MS, AL | Smallest division and it contains the pilot — TN is a *re-encode* under the new schema, so an unchanged-value assertion is a strong regression signal. Two known Type B (MS, AL), one Type D (KY). AL's 2.00× is the largest simple multiplier found. |
| **2** | South Atlantic | DE, MD, DC, VA, WV, NC, SC, GA, FL | The South's largest household weight. SC (Type B), DC (first `RULE_RATE`, and a single jurisdiction so no local-option complication), three known Type D, and FL — the exemption trap. |
| **3** | West South Central | AR, LA, OK, TX | Completes the South. **Landed: all four uniform.** LA was predicted Type B on its 10%/15% split, but the split keys on *use*, not tenure, so an apartment sits in the residential class — the prediction did not survive the primary source. TX, OK and AR are all exemption/cap traps. |
| **4** | Middle Atlantic | NY, NJ, PA | Only three, but NY is the hardest jurisdiction in the country. First real exercise of `sub_state` and `threshold_basis`. Kept small deliberately. **Landed: NYC ×1.81 in five counties, NJ and PA uniform.** NY also forced a new `RULE_EFFECTIVE` type and a fix to `active_basis`, which had been blind to sub-state rules. Nassau deferred. |
| **5** | East North Central | OH, IN, IL, MI, WI | IL predicted as the second sub-state case (Cook's ordinance vs uniform downstate). **Landed: all five uniform, and the prediction was wrong** — Cook assesses class 2 (houses) and class 3 (7+ unit rentals) at the same 10%, so no `sub_state` was needed. OH is a second use-based split like LA; MI's 18-mill gap is a school levy this dimension already nets out; IN's caps are rejected but flagged as the tractable cap case. |
| **6** | New England | ME, NH, VT, MA, RI, CT | Predicted MA as the canonical local-option case. **Landed: that was wrong** — Massachusetts counts every property with one or more habitable units as residential, so its ch. 40 § 56 shift cannot reach apartments at all. The real local-option states are **RI and CT**, and neither is resolvable: both set classification per municipality in states whose counties are not governmental units, so they are the first records to carry `local_option` with an **empty** `sub_state`. VT is the sharpest test of the school-levy rule — an explicit statewide homestead/nonhomestead education rate split that still owes no correction. |
| **7** | West North Central | MN, IA, MO, ND, SD, NE, KS | Predicted "mostly uniform; fast. MN's class rates are explicit." **Landed: TWO corrections, not one.** MN ×1.25 as expected, but **ND ×1.11 was missed by the prediction** — its residential class excludes "structures which accommodate four or more separate family units", found only by reading the § 57-02-01 definitions the valuation statute does not carry. The two make the table's most useful pair: both reclassify at four units, MN counting units *held for rent*, ND counting units the structure *accommodates*. SD is the third school-levy rejection; IA's multiresidential class was abolished in 2022; MO and KS are use-based like LA and OH. |
| **8** | Mountain | MT, ID, WY, CO, NM, AZ, UT, NV | Predicted AZ as a real legal-class system separating owner-occupied from rental residential. **Landed: all eight uniform, and the prediction was wrong division-wide.** AZ's classes 3 and 4 do split owner from renter but carry the *same* 10% ratio; the difference is a rebate on *school* taxes — the fourth school-levy rejection. And four Mountain states' headline owner-occupied preferences turn out to key on **occupancy, not tenure**: Utah's exemption covers tenants, Montana's homestead rate names long-term rentals, Colorado applies one residential rate. These are amenity states targeting second homes, not landlords. |
| **9** | Pacific | WA, OR, CA, AK, HI | Last: mostly uniform, and CA is where both golden LA cases live, so the final recalibration's effect on them gets undivided attention. |

The nine phases partition all 51 jurisdictions exactly. Encode that as a **coverage test**:
each jurisdiction belongs to exactly one phase, and once a phase lands every jurisdiction in
it appears in the table. That turns "we finished the Southeast" into an assertion, and makes
a forgotten state fail CI rather than silently score as a no-op.

One PR per state (or a small batch of same-rule-type states), then exactly one
recalibration PR to close each phase.

---

## Per-state checklist

**Research.** Locate the primary authority in this order: state constitution's taxation
article → classification/assessment statute → DOR or state board assessor manual → any AG
opinion or controlling appellate case. Then answer, in order:

1. More than one assessment ratio, or more than one rate, for *real* property?
2. What distinguishes the classes — dwelling-unit count, rental-unit count, owner-occupancy,
   or use?
3. Is the residential class defined by owner-occupancy (threshold 1) or unit count
   (threshold 2+)?
4. Uniform statewide, or local option?
5. Does the differential attach to the **assessment ratio**, the **rate**, or an
   **exemption/credit**?

**The exemption/credit exclusion rule.** If the answer to (5) is exemption, credit, or
assessment cap, the record is `RULE_UNIFORM` with a note explaining what was found and why
it was rejected. FL (Save Our Homes + homestead), TX (homestead cap), CA (Prop 13), and
LA's $75,000 homestead exemption all fall here — several *in addition to* a real
classification. The rationale belongs in the module docstring, not in a reviewer's head:
the ACS observed rate already embeds the exemption for owner-occupied homes, and the rental
baseline differs by the *absence* of that exemption — a different correction, larger, and
value-dependent rather than a constant multiplier. Encoding it as a multiplier over-corrects.
**Only a rule assigning rental / non-owner-occupied property to a distinct statutory class
with a distinct ratio or rate gets encoded.**

**Record known under-corrections and accept them.** SC's 4% ratio requires the owner to
claim it, and SC additionally exempts owner-occupied property from school operating millage
— so the observed owner-occupied rate sits below what 6/4 arithmetic implies and the encoded
1.5× under-corrects. Safe direction. Note direction and rough magnitude in `notes`.

**Check the school-share interaction.** The national path already nets `school_tax_share`
out of the rate. Where a differential attaches specifically to a school levy, the netting
partially cancels it, and the residual on the non-school rate is what the multiplier
represents.

**Encode** one record per commit, with citation and today's date in `verified`. Never batch-
enter a region without a citation per state.

**Test**, per state: single-family owner-occupied → no correction; single-family explicit
`owner_occupied=False` → correct per type; single-family tenure unknown → **no** correction
(locks the 14.0% B25032 default in the safe direction); fully-rented duplex → the
multiplier; owner-occupied duplex → per type; `separately_parceled=True` at 157 units → no
correction; `RULE_RATE` ⇒ absolute accessor `None`; multiplier equals ratio of legs.

---

## Recalibration cadence

**Once per regional phase, in a dedicated PR** containing only the constant, the regenerated
golden snapshot, and the doc numbers. Nine recalibrations total.

Not per state: `INFRA_XS` is six numbers, and every change churns `all_dimensions.py`, the
narrative numbers in two research docs, the copy in `docs/methodology.html`, and forces a
full golden regeneration. Fifty-one times makes each diff unreviewable by attrition.

Not once at the end either: if the live path classifies four states while `INFRA_XS` is
anchored to a distribution assuming none, labels and yardstick disagree for however long the
next phase takes. The magnitude is small — the split-roll states in Phases 1–3 are perhaps
9% of US households and renter legs within them roughly a third of that — but *"the
reference distribution is built by the same model the app runs"* is the entire basis for the
percentile claim and should not be knowingly broken across a phase boundary.

Each recalibration PR states the expected direction and magnitude **before** regenerating.
All non-infrastructure dimensions must be byte-identical; anything else in the diff is a bug.

---

## Risks

**Silent over-correction** — the primary risk:

| Mechanism | Mitigation |
|---|---|
| Both paths fire at once (1.6 × 1.6 = 2.56 in TN) | `enrich_row` raises `ValueError`; two distinct dict keys, never one with two meanings |
| An exemption encoded as a classification | The exclusion rule in the module docstring; `notes` records what was rejected. FL and TX most likely to trip it |
| Condo towers indistinguishable from rental towers | `separately_parceled` escape hatch; scaling of an already-accepted risk, not a new one |
| The multi-unit tenure default (86.1% right overall, weakest at 2 units: 76.1%) | Per-band tenure defaults as an explicit, separately-reviewed decision — see below |
| A pre-divided multiplier pasted where two legs belong | Multiplier-equals-ratio-of-legs test, per state |
| Type B reclassifying a rented single-family home with no tenure evidence | Unknown tenure resolves to owner-occupied, so it does not fire; locked by test. Do **not** change the default to make it fire |
| A multiplier that is simply too large | Documented sanity ceiling with a test; above it is a research error, not a real rule |

**Open decision — per-band tenure defaults.** `MULTIUNIT_RENTAL_DEFAULT` is one bool for
every multi-unit building, but B25032 renter shares are not flat (2-unit 76.1%, 3–4 86.1%,
5–9 88.3%, 10–19 90.2%, 20–49 87.1%, 50+ 86.6%). Duplexes are both the weakest case and the
most common multi-unit type. A per-band lookup with a documented reclassification threshold
would be more honest — but it changes pilot behavior (a units=2 unknown-tenure TN parcel
would stop being reclassified, breaking `tests/test_density.py:108` and moving the golden
snapshot). Take it in Phase 0 as **its own commit and PR**, decided on the merits, or record
it as an open over-correction on duplexes. Note the symmetry either way: 1-unit detached is
14.0% renter, so defaulting single-family to owner-occupied is right ~86% of the time — the
mirror image of the multi-unit default, and why Type B states correctly do not fire on a
single-family home with unknown tenure.

**Local-option states.** The failure mode is a statewide average wrong everywhere: many of
MA's 351 municipalities set their residential factor at 1.0, so a statewide mean
over-corrects those and under-corrects Boston. `local_option=True` ⇒ multiplier 1.0 unless a
`sub_state[county_fips]` entry matches. Ship MA as researched-and-deliberately-not-applied.

**NYC** deserves its own callout: Class 1 vs Class 2 is a **dwelling-unit** threshold, and
the effective differential is *not* the ratio of the class ratios, because class rates run
in the opposite direction and Class 1 carries assessment-increase caps. Encode via
`effective_multiplier` from NYC DOF's published effective rates by class, with its own
citation. Also flag that the four outer boroughs are missing from `govfinance_county.csv`
(the Census of Governments aggregates NYC as one unit).

**Golden-snapshot habituation.** Every recalibration rewrites the snapshot, so a genuine
regression can hide in a large expected diff and reviewers habituate to `UPDATE_GOLDEN=1`.
Recalibration PRs carry no logic changes; non-infrastructure dimensions must be byte-identical.

**Copy risk.** The label says Infrastructure is a national percentile rank. When corrections
land, an apartment building's ratio rises *and* the yardstick shifts underneath it — the net
per-parcel direction is genuinely ambiguous. Documentation should describe what changed and
why, and must not promise anyone's score will go up.

---

## Future work: cap-driven owner/rental divergence

**Indiana is the tractable one, and should be attempted first.** Ind. Const. art. 10, § 1(f)
caps tax at 1% of gross assessed value for an owner-occupied homestead against 2% for other
residential — a *rate ceiling by class*, not a growth cap, so unlike every other state below
it carries no holding-period or appreciation dependence. Where the local gross rate exceeds
2% the owner/rental ratio is exactly 2.0; under 1% it is exactly 1.0; between, it is the
gross rate over 1%. All that is missing is county **gross** rates — the bundled ACS
`effective_tax_rate` is the owner-occupied rate, already capped, so the gross rate cannot be
recovered from it. One new county-level data source would make Indiana encodable outright,
which is not true of any of the others.

Florida, Texas, California, Arkansas and Oklahoma are together **30.2% of the US
population**, and in all five the owner-occupied/rental tax gap is real and large — but it
comes from assessment-increase caps and homestead exemptions rather than from a property
class, so the exclusion rule above correctly keeps it out of the classification table.

Phase 3 made this the dominant finding of the rollout so far rather than a footnote: four of
the five are now encoded as `RULE_UNIFORM`, so the table records them as *researched* while
the effect itself stays unmodeled.

It is the **single largest known unmodeled effect** in this dimension, and it deserves a
tracked work item rather than a sentence in a `notes` field. It needs its own method,
because the gap is not a fixed ratio: it grows with time in ownership and with the drift
between assessed and market value, so two identical adjacent houses can carry very different
effective rates purely by purchase date. A constant class multiplier would misstate it in
both directions.

**And the caps do not all push the same way.** Texas's § 23.231 circuit breaker caps
*non-homestead* appraisal growth, narrowing the gap that § 23.23's homestead cap widens.
Any method here has to be signed, not just magnitude-aware.

---

## Resolved: the reference distribution had no large apartment building

**Status: fixed, in its own PR after Phase 4.**

The problem. `scripts/calibrate_infra_breakpoints.py` weighted five density archetypes and
the densest — "urban multifamily" — was a **10-unit** parcel. Nothing in the national
distribution represented a mid-rise or a high-rise, so every large apartment building in the
country was percentile-ranked against a population of houses, duplexes and small walk-ups.
Because big buildings spread infrastructure cost over many doors, excluding them held the
top of the distribution artificially low and inflated their own percentiles.

Phase 4 made it concrete: New York City's correction begins at **11** dwelling units (RPTL
§ 1805(2)), one above the densest archetype, so the city's ×1.81 was live for a real label
request and invisible to the yardstick.

**How big the gap was.** ACS 2024 5-yr B25032 puts structures of 20+ units at **53.8% of all
occupied units in 5+ unit buildings** — the majority of multifamily housing, not its tail —
with the 50+ band alone (6.4% of all occupied units) larger than any other multifamily band.

**The fix.** The 0.15 urban share was split 46.2/53.8 by those ACS proportions into
`urban multifamily (5-19)` (20 DU/acre, units 10, renter 0.892) and
`large multifamily (20+)` (50 DU/acre, units 50, renter 0.868). The other four archetypes
were left untouched, so the change is attributable.

| anchor | before | after | Δ |
|---|---|---|---|
| F (p5) | 0.325 | 0.325 | +0.00% |
| D (p20) | 0.469 | 0.469 | +0.00% |
| C (p40) | 0.602 | 0.604 | +0.33% |
| B (p60) | 0.730 | 0.736 | +0.82% |
| A (p80) | 0.934 | 0.947 | +1.39% |
| A+ (p95) | 1.456 | 1.553 | **+6.66%** |

An A is now modestly harder to earn, which is the correct direction. The share of US homes
clearing a 1.0 fiscal ratio rose **13% → 18%** — not a loosened standard, but the housing
type most likely to pay its way finally being counted.

**It was not about New York.** Deleting the NY rule entirely and recalibrating leaves p95 at
1.553, unchanged to three decimals: five counties out of ~3,140 cannot move a
population-weighted national percentile. NYC's rule reaching the distribution is a
correctness win; the anchor movement is the archetype alone.

**Still coarse, deliberately.** B25032 puts 5+ unit structures at 18.5% of occupied units
against the 0.15 assigned here. The other four shares are round numbers that do not map onto
ACS structure categories at all — "compact suburb / townhome" is 8 DU/acre carrying
`units=1` — so rebalancing the whole roster is a separate redesign, not a tweak.

Florida is the cleanest first case, because both caps are explicit in the constitution —
3% annual growth for homestead property (Fla. Const. art. VII, § 4(d)) against 10% for
non-homestead residential of nine units or fewer (§ 4(g)) and all other non-homestead
(§ 4(h)). Modeling it would need a holding-period assumption the label does not currently
have, which is the main open design question.

---

## Verification

Per phase:

```bash
ruff check .
pytest -q
python tests/test_assessment.py                     # dual-mode footer
python tests/test_states.py
python scripts/report_classification_coverage.py
python scripts/calibrate_infra_breakpoints.py       # capture printed percentiles
UPDATE_GOLDEN=1 pytest tests/test_golden_label.py -q
python scripts/sync_readme.py --check && python scripts/sync_docs.py --check
```

After Phase 0 the printed percentiles should move only from the TN renter legs — a fraction
of a percent nationally. **If any anchor moves more than ~1%, something is wrong**, most
likely the multiplier firing where it should not.

End-to-end spot check per new state, at `units=1` and `units=8`:

```bash
housing-simulate --lat 33.52 --lon -86.81 --units 100 --rental \
    --lot-acres 1.0 --json | jq '.details.infrastructure'
```

Birmingham, AL is the sharpest case in the Southeast — a 2.00× multiplier is the largest
correction there, so wiring errors surface first.

Where a state DOR publishes an assessment/sales ratio study with separate residential,
apartment, and commercial ratios, cross-check the encoded multiplier against it. That is a
direct empirical test of the number rather than a re-reading of the statute.
