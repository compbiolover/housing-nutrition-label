"""Property-tax **classification** — the assessment ratio a parcel is taxed on.

Most states assess all housing at one ratio, so appraised value and the effective tax rate
are enough to estimate a parcel's bill. A minority use a *split roll*: they put rental
housing into a higher-taxed class. Where that happens, applying a single-family basis to an
apartment building understates its property-tax revenue — and therefore understates its
Infrastructure Burden fiscal ratio.

Two mechanisms, one correction
------------------------------
A state can split the roll two ways, and they are economically equivalent:

* ``RULE_ASSESSMENT`` — one class is assessed at a higher *fraction of value* (Tennessee
  25% vs 40%; South Carolina 4% vs 6%).
* ``RULE_RATE`` — assessment is uniform but the *millage* differs by class (DC, Rhode
  Island, New York City).

Both reduce to a **multiplier** on what an owner-occupied home pays, which is what the two
scoring paths need:

* The **statutory path** (the Shelby pilot) applies a real assessment ratio against a real
  millage, so it needs the absolute commercial ratio — ``classified_assess_ratio``.
* The **national path** applies an ACS *observed effective rate* (B25103 median taxes ÷
  B25077 median value) computed over **owner-occupied** homes. That rate already embeds
  whatever class owner-occupied homes fall in, so an absolute ratio would double-count.
  It needs the ratio *between* the classes — ``classification_multiplier``.

The multiplier is well-founded on that path for an exact reason: **its denominator must
match the baseline embedded in the observed rate.** In Tennessee owner-occupied homes are
the 25% class; in South Carolina the 4% legal-residence class; in DC Class 1. In every
classifying state the ACS owner-occupied baseline *is* the residential denominator.

What is deliberately NOT encoded
--------------------------------
**Exemptions, credits, and assessment caps are excluded**, even where they produce a large
owner-occupied/rental gap. Florida's Save Our Homes, Texas's homestead cap, California's
Proposition 13 and Louisiana's homestead exemption all fall here. The reasoning is the same
one that makes the multiplier valid: the ACS observed rate already embeds the exemption for
owner-occupied homes, so the rental baseline differs by its *absence* — a correction that is
value-dependent and generally larger than a constant multiplier, not a class ratio. Encoding
one as the other would over-correct. Only a rule assigning rental or non-owner-occupied
property to a distinct statutory class with a distinct ratio or rate is encoded here; a
state where one was found and rejected carries a ``RULE_UNIFORM`` record whose ``notes``
say so, which is how "researched, no correction" is told apart from "not researched".

Tennessee (the pilot)
---------------------
**Tenn. Const. art. II, § 28** sets residential assessment at 25% of value, "provided that
residential property containing two (2) or more rental units is hereby defined as
industrial and commercial property." Codified at **Tenn. Code Ann. § 67-5-501(11)**, which
defines residential property as "all real property that is used, or held for use, for
dwelling purposes and that contains not more than one (1) rental unit" (see also
§ 67-5-501(4)). **Tenn. Code Ann. § 67-5-801** sets the rates: residential 25%, industrial
and commercial 40%.

The operative count is **rental units, not dwelling units**. Tennessee AG Opinion No.
25-016 (Aug. 25, 2025) applies it: a single-family home rented long-term stays residential
(one rental unit), and so does an owner-occupied duplex (the owner's half is not a rental
unit). There is no bright-line physical test — in *Spring Hill, L.P. v. State Board of
Equalization*, No. M2001-02683-COA-R3-CV, 2003 WL 23099679, at *17–*18 (Tenn. Ct. App.
Dec. 31, 2003), 44 detached homes on separate lots were classified industrial and
commercial because they were one commonly owned and managed rental development.

So a 157-unit rental building in Memphis is assessed at 40%, not 25% — 1.6x the revenue a
flat residential ratio credits it. A 157-unit *condominium* is not: each unit is its own
parcel containing at most one rental unit (see ``separately_parceled``).

Coverage
--------
Forty-nine of 51 scorable jurisdictions are encoded — all nine Census divisions have been
worked through. The two that are not, the District of Columbia and Hawaii, are *deferred*
rather than unexamined: both were researched and both were left out deliberately, for
reasons recorded at the end of ``CLASSIFICATION_RULES``.

Eight carry a correction — AL and WV at 2.0x, New York City at 1.81x, TN at 1.6x, MS and SC
at 1.5x, MN at 1.25x and ND at 1.11x. Thirty-nine were researched and found to have no
classification of rental housing, and are recorded as ``RULE_UNIFORM`` rather than left
absent: both produce a 1.0 multiplier at the point of use, so only the record distinguishes
"researched, no correction" from "not researched". Louisiana, Ohio, Missouri and Kansas are
the instructive ones — each has a real class split, but it keys on *use* rather than tenure,
so an apartment building sits in the same class as a detached house.

Minnesota and North Dakota make the other instructive pair: both reclassify at **four**
units, but Minnesota counts units *held for rent* while North Dakota counts family units the
structure *accommodates*. An owner-occupied fourplex is commercial in North Dakota and
residential in Minnesota.

Two more — Rhode Island and Connecticut — have a real classification that DOES reach rental
housing but is set per municipality, and neither state's counties are governmental units, so
no county FIPS can express it. They carry ``local_option`` with an empty ``sub_state``: no
correction applies, but the record says a rule exists rather than claiming there is none.

New York is the only ``local_option`` state resolved so far, and the only one whose
correction comes from a published effective-rate study rather than statutory legs — see
``RULE_EFFECTIVE`` and the NY notes, where the naive statutory reading over-corrects by
2.6x.

The 2 deferred jurisdictions return no correction, which for Hawaii is known to be wrong:
its counties do classify rental housing, and by a lot. It is left out because two of the
four implied multipliers breach ``CLASSIFICATION_MULT_CEIL`` and Honolulu's is a
value-tiered bracket rather than a class ratio — under-correcting a jurisdiction that is
0.44% of the population beats encoding a 3.5x correction from a bracket schedule that has
not been modelled. Between them the two hold 0.65% of the population.

The rollout plan is ``research/property-tax-classification-rollout.md`` and the
per-jurisdiction authority record is ``research/property-tax-classification-research.md``;
extending the table means reading each state's constitution or code, one at a time, and
must not be guessed from a secondary source. ``scripts/report_classification_coverage.py``
prints live coverage by Census division.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from housing_label.data.states import SCORED_JURISDICTIONS

# Date the encoded rules were last checked against their primary sources, in aggregate.
# Per-record ``verified`` gives the per-state granularity; this is the table-level vintage,
# playing the same role as ``DATA_VINTAGE`` in the crosswalk loaders.
LAW_AS_OF = "2026-08-01"

# ── Rule types ────────────────────────────────────────────────────────────────
RULE_ASSESSMENT = "assessment_ratio"   # classes differ by fraction of value assessed
RULE_RATE = "tax_rate"                 # uniform assessment, classes differ by millage
RULE_EFFECTIVE = "effective_rate"      # both differ; a published ETR study is the datum
RULE_UNIFORM = "uniform"               # researched; no classification of rental housing

# What the reclassification threshold counts. Tennessee counts RENTAL units; New York City's
# Class 1 vs Class 2 counts DWELLING units (1-3 family vs 4+), so the distinction has to be
# in the schema from the start rather than retrofitted after states are encoded.
BASIS_RENTAL_UNITS = "rental_units"
BASIS_DWELLING_UNITS = "dwelling_units"

# A split roll that more than triples the tax is not a real rule, it is a research error —
# the widest genuine split found so far is Cook County's 10% vs 25%. Mirrors the clamp
# convention of ``data/govfinance.MULT_FLOOR/CEIL`` and ``data/propertytax.RATE_FLOOR/CEIL``.
CLASSIFICATION_MULT_CEIL = 3.0

# Tenn. Code Ann. § 67-5-801 assessment rates.
TN_RESIDENTIAL_ASSESS_RATIO = 0.25
TN_COMMERCIAL_ASSESS_RATIO = 0.40
# Tenn. Const. art. II, § 28 / Tenn. Code Ann. § 67-5-501(11).
TN_COMMERCIAL_RENTAL_UNIT_THRESHOLD = 2

# Default tenure assumption for a multi-unit building when the caller doesn't say.
# ACS 2024 5-yr table B25032 (tenure by units in structure, US): 86.1% of units in 2+ unit
# structures are renter-occupied, rising to 87.9% in 5+ unit structures — so treating a
# multi-unit building as rental is right for roughly six of every seven. The mirror image
# holds for detached homes: 14.0% are renter-occupied, so defaulting a single home to
# owner-occupied is right ~86% of the time. A condominium or owner-occupied duplex is the
# documented exception and callers can say so explicitly.
MULTIUNIT_RENTAL_DEFAULT = True


@dataclass(frozen=True)
class ClassificationRule:
    """How one jurisdiction classifies rental housing for property tax.

    ``residential``/``commercial`` are assessment ratios when ``rule_type`` is
    ``RULE_ASSESSMENT`` and class tax rates when it is ``RULE_RATE``; either way the
    correction is their quotient. ``effective_multiplier`` overrides that quotient for
    jurisdictions where the published effective differential is the primary datum — in New
    York City the class ratios and the class rates move in opposite directions, so deriving
    the multiplier from either leg alone is wrong.

    ``local_option`` marks a state whose classification is set below the state level. Those
    yield no correction unless ``sub_state`` carries an entry for the parcel's county,
    because a statewide average is wrong nearly everywhere: many of Massachusetts's 351
    municipalities set no shift at all while Boston sets a large one.
    """

    usps: str
    rule_type: str
    authority: str                        # primary-source citation
    verified: str                         # ISO date the citation was read
    threshold_basis: str | None = None
    rental_unit_threshold: int | None = None
    residential: float | None = None
    commercial: float | None = None
    effective_multiplier: float | None = None
    local_option: bool = False
    sub_state: dict[str, "ClassificationRule"] = field(default_factory=dict)
    notes: str = ""

    def multiplier(self) -> float:
        """Ratio of the non-residential class to the residential class, clamped."""
        if self.rule_type == RULE_UNIFORM:
            return 1.0
        if self.effective_multiplier is not None:
            raw = self.effective_multiplier
        elif self.residential and self.commercial:
            raw = self.commercial / self.residential
        else:
            return 1.0
        # Rounded because the legs are decimal statutory percentages whose quotient is
        # not always exact in binary — Mississippi's 0.15/0.10 lands on
        # 1.4999999999999998. Six places is far finer than any real statute distinguishes
        # and keeps the multiplier comparable to the literal a test or a reader expects.
        return round(min(max(raw, 1.0), CLASSIFICATION_MULT_CEIL), 6)


CLASSIFICATION_RULES: dict[str, ClassificationRule] = {
    "TN": ClassificationRule(
        usps="TN",
        rule_type=RULE_ASSESSMENT,
        threshold_basis=BASIS_RENTAL_UNITS,
        rental_unit_threshold=TN_COMMERCIAL_RENTAL_UNIT_THRESHOLD,
        residential=TN_RESIDENTIAL_ASSESS_RATIO,
        commercial=TN_COMMERCIAL_ASSESS_RATIO,
        authority=("Tenn. Const. art. II, § 28; Tenn. Code Ann. § 67-5-501(11), (4); "
                   "§ 67-5-801; Tenn. Att'y Gen. Op. No. 25-016 (Aug. 25, 2025)"),
        verified="2026-07-31",
        notes=("Counts RENTAL units, not dwelling units: a rented single-family home and an "
               "owner-occupied duplex both stay residential. Spring Hill, L.P. v. State Bd. "
               "of Equalization, 2003 WL 23099679, at *17-*18, holds there is no "
               "bright-line physical test."),
    ),
    # ── East South Central ────────────────────────────────────────────────────
    "AL": ClassificationRule(
        usps="AL",
        rule_type=RULE_ASSESSMENT,
        threshold_basis=BASIS_RENTAL_UNITS,
        # Class III requires single-family AND owner-occupied, so ANY rental housing
        # falls to Class II — an apartment building and a rented detached house alike.
        # Threshold 1, unlike Tennessee's 2.
        rental_unit_threshold=1,
        residential=0.10,
        commercial=0.20,
        authority=("Ala. Const. amend. 373 (recompiled as Ala. Const. of 2022, art. XI, "
                   "§ 217); Ala. Code § 40-8-1"),
        verified="2026-07-31",
        notes=("Class III (10%) is 'all agricultural, forest, and single-family, "
               "owner-occupied residential property ... and historic buildings and "
               "sites'; Class II (20%) is 'all property not otherwise classified'. "
               "Verified against the Alabama Department of Revenue's published class "
               "table. UNDER-CORRECTS: Alabama also grants a homestead exemption on "
               "Class III, which depresses the observed owner-occupied rate further, so "
               "the true gap exceeds 2.0x. Safe direction."),
    ),
    "MS": ClassificationRule(
        usps="MS",
        rule_type=RULE_ASSESSMENT,
        threshold_basis=BASIS_RENTAL_UNITS,
        rental_unit_threshold=1,
        residential=0.10,
        commercial=0.15,
        authority="Miss. Const. art. 4, § 112; Miss. Code Ann. § 27-35-4",
        verified="2026-07-31",
        notes=("Class I (10%) is 'single-family, owner-occupied, residential real "
               "property'; Class II (15%) is 'all other real property, except for real "
               "property included in Class I or IV'. Same single-family-AND-owner-"
               "occupied test as Alabama, so the same threshold of 1. UNDER-CORRECTS "
               "for the same homestead-exemption reason."),
    ),
    "KY": ClassificationRule(
        usps="KY",
        rule_type=RULE_UNIFORM,
        authority="Ky. Const. § 172; Ky. Rev. Stat. § 132.020",
        verified="2026-07-31",
        notes=("No classification of real property. Ky. Const. § 172 requires all "
               "property be assessed at fair cash value, which the General Assembly has "
               "confirmed means 100%, and the KRS 132.020 state real property rate does "
               "not distinguish residential from commercial; local district rates apply "
               "uniformly within a district. FOUND AND REJECTED: the Ky. Const. § 170 "
               "homestead exemption for owners 65+ or totally disabled — an exemption "
               "keyed to owner characteristics rather than a property class, so it falls "
               "under the documented exclusion rule."),
    ),
    # ── South Atlantic ────────────────────────────────────────────────────────
    "SC": ClassificationRule(
        usps="SC",
        rule_type=RULE_ASSESSMENT,
        threshold_basis=BASIS_RENTAL_UNITS,
        rental_unit_threshold=1,
        residential=0.04,
        commercial=0.06,
        authority=("S.C. Code Ann. § 12-43-220(c), (e), § 12-37-220(B)(47); "
                   "S.C. Const. art. X, § 1"),
        verified="2026-08-01",
        notes=("§ 12-43-220(c) gives a 4% ratio to an owner-occupied legal residence; all "
               "other real property is 6%. Tenure-based like Alabama and Mississippi, so "
               "threshold 1. 1.50 IS THE RIGHT FIGURE, and an earlier note here claiming "
               "it under-corrects was wrong — recorded because the wrong reading is the "
               "tempting one. South Carolina also exempts owner-occupied legal residences "
               "from school OPERATING millage, so on a TOTAL tax bill a rental really does "
               "pay more than 1.5x an owner. But this dimension nets school taxes out of "
               "both sides and applies the multiplier to the NON-SCHOOL rate, where the "
               "ratio is 0.06/0.04 = 1.5 exactly: the observed owner rate is the base for "
               "both legs, so the exemption changes that base's LEVEL and cancels out of "
               "the RATIO. Michigan's Principal Residence Exemption is the same shape and "
               "correctly yields no correction at all. THE REAL RESIDUAL IS ELSEWHERE: "
               "region_context nets a county-wide school_tax_share off an owner-occupied "
               "ACS rate that has already lost its school operating component, which "
               "over-removes and understates non-school revenue for every South Carolina "
               "parcel, owner and rental alike. That is a revenue-model issue, not a "
               "classification one, and is logged in "
               "research/infrastructure-burden-research.md."),
    ),
    "WV": ClassificationRule(
        usps="WV",
        rule_type=RULE_RATE,
        threshold_basis=BASIS_RENTAL_UNITS,
        rental_unit_threshold=1,
        # Class II vs Class III/IV maximum regular levy rates, county leg (cents per
        # $100). The ratio is what matters, not the absolute cents — school is 45.90 vs
        # 91.80, the same 2.0x. All classes are assessed at 60% of value, so the rate is
        # the ONLY thing that differs. This is the first RULE_RATE jurisdiction.
        residential=0.2860,
        commercial=0.5720,
        authority=("W. Va. Const. art. X, § 1b; W. Va. Code § 11-8-6 et seq.; West "
                   "Virginia Tax Division, Property Tax Rates (maximum regular levy "
                   "rates by class)"),
        verified="2026-08-01",
        notes=("Class II is 'owner-occupied residential property used exclusively for "
               "residential purposes and all farm land used for agricultural purposes by "
               "its owner or bona fide tenant'; Class III is everything else outside a "
               "municipality and Class IV everything else inside. W. Va. Code § 11-8-6's "
               "aggregate caps (50c/$1/$1.50/$2) look like 1.5x for Class III, but those "
               "are ceilings across ALL levying bodies; the per-body maximum rates are "
               "2.0x for both county (28.60 -> 57.20) and school (45.90 -> 91.80), which "
               "are the bulk of any bill. UNDER-CORRECTS inside municipalities, where the "
               "Class IV municipal leg is 4x rather than 2x."),
    ),
    "FL": ClassificationRule(
        usps="FL",
        rule_type=RULE_UNIFORM,
        authority=("Fla. Const. art. VII, § 4(d), (g), (h), § 6; Fla. Stat. §§ 193.155, "
                   "193.1554, 196.031"),
        verified="2026-08-01",
        notes=("Just valuation applies uniformly; there is no class for rental property. "
               "FOUND AND REJECTED: the homestead exemption (§ 196.031) and the split "
               "assessment-increase caps — 3% for homestead (art. VII, § 4(d)) versus 10% "
               "for non-homestead (§ 4(g) for residential of nine units or fewer, § 4(h) "
               "for everything else). Those produce a large and growing owner/rental gap, "
               "but it is keyed to time in ownership and is value-dependent rather than a "
               "fixed class ratio, so a constant multiplier would misstate it. Logged as "
               "a roadmap item, not encoded here."),
    ),
    "GA": ClassificationRule(
        usps="GA",
        rule_type=RULE_UNIFORM,
        authority="Ga. Code Ann. § 48-5-7(a), § 48-5-44, § 48-5-44.2; Ga. Const. art. VII, § I, ¶ III",
        verified="2026-08-01",
        notes=("§ 48-5-7(a) assesses all taxable tangible property at 40% of fair market "
               "value. Every enumerated exception is use-based (agricultural, historic, "
               "conservation, timberland); none distinguishes owner-occupied from rental, "
               "and the constitution leaves no room for a rental-real-property class. "
               "FOUND AND REJECTED: the § 48-5-44 homestead exemption and the § 48-5-44.2 "
               "statewide floating homestead exemption."),
    ),
    "MD": ClassificationRule(
        usps="MD",
        rule_type=RULE_UNIFORM,
        authority="Md. Code, Tax-Prop. §§ 8-101, 8-103(c), 6-302(b), 9-105",
        verified="2026-08-01",
        notes=("§ 6-302(b)(1) requires 'a single county property tax rate for all real "
               "property subject to county property tax', and the § 8-101 subclasses are "
               "use-based with no tenure subclass. FOUND AND REJECTED: the § 9-105 "
               "Homestead Property Tax Credit, which caps assessment growth for a "
               "homeowner's principal residence only — a credit, not a class."),
    ),
    "NC": ClassificationRule(
        usps="NC",
        rule_type=RULE_UNIFORM,
        authority="N.C. Gen. Stat. § 105-283, § 105-277; N.C. Const. art. V, § 2(2)",
        verified="2026-08-01",
        notes=("§ 105-283 appraises all property at true value in money with no tenure "
               "distinction, and the only § 105-277 classes are solar systems and private "
               "water company property. N.C. Const. art. V, § 2(2) forecloses a local "
               "option outright: 'Only the General Assembly shall have the power to "
               "classify property for taxation, which power shall be exercised only on a "
               "State-wide basis and shall not be delegated.' The elderly/disabled "
               "exclusions are age- and income-gated, not a general owner-occupied "
               "preference."),
    ),
    "VA": ClassificationRule(
        usps="VA",
        rule_type=RULE_UNIFORM,
        authority="Va. Const. art. X, § 1; Va. Code § 58.1-3201, § 58.1-3221.3",
        verified="2026-08-01",
        notes=("Uniform assessment at 100% of fair market value. Virginia DOES permit "
               "some locality-level real-property classification, which made this look "
               "like a local-option case — but § 58.1-3221.3, the only one with rate "
               "consequences, EXPRESSLY EXCLUDES rental housing: 'all residential uses "
               "and all multifamily residential uses, including ... apartments, or homes "
               "in a subdivision when leased on a unit by unit basis'. So a locality "
               "levying the extra commercial/industrial transportation rate cannot apply "
               "it to apartments. Uniform, not local option."),
    ),
    "DE": ClassificationRule(
        usps="DE",
        rule_type=RULE_UNIFORM,
        authority="Del. Code tit. 9, § 8306 (as amended by HB 62, 2023); tit. 9, ch. 83",
        verified="2026-08-01",
        notes=("No state property tax; counties assess at fair market value as of the "
               "county base year, now on a five-year reassessment cycle after the 2020 "
               "school-funding litigation. Title 9 ch. 83 differentiates improved from "
               "unimproved land and grants agricultural use-value, but has no tenure "
               "classification. The senior school property tax credit is age-gated, not a "
               "general owner-occupied preference."),
    ),
    # ── West South Central ────────────────────────────────────────────────────
    #
    # All four are uniform, including Louisiana — see its notes. This is the first
    # division that adds no correction at all.
    "LA": ClassificationRule(
        usps="LA",
        rule_type=RULE_UNIFORM,
        authority="La. Const. art. VII, § 18(A), (B), § 20; La. Admin. Code tit. 61, § V-101",
        verified="2026-08-01",
        notes=("Art. VII, § 18(B) does split 10% from 15%, and the rollout memo predicted "
               "that made Louisiana a correcting state. It does not. The five classes are "
               "land 10%, IMPROVEMENTS FOR RESIDENTIAL PURPOSES 10%, electric cooperative "
               "15%, public service 25%, other property 15% — a USE test carrying no "
               "tenure or unit-count qualifier, so an apartment building is an improvement "
               "used for residential purposes and sits in the 10% class beside a detached "
               "house. The Tax Commission's own rule at LAC 61:V-101 reproduces the same "
               "five classes and adds no tenure test. FOUND AND REJECTED: the art. VII, "
               "§ 20 homestead exemption ($7,500 of assessed value, $75,000 of market "
               "value, owner-occupied only) — which is where those Tax Commission rules "
               "DO separate owner from renter, exempting the owner-occupied part of an "
               "income-producing property but not the rented part — and the special "
               "assessment level, which is age-, disability- and "
               "income-gated. CAVEAT: Louisiana assessors colloquially call apartment "
               "buildings 'commercial', and no case or AG opinion squarely construing "
               "'improvements for residential purposes' as to apartments was found. The "
               "text has no tenure hook for the other reading, and uniform is the "
               "under-correcting choice, so text and the governing principle agree."),
    ),
    "TX": ClassificationRule(
        usps="TX",
        rule_type=RULE_UNIFORM,
        authority="Tex. Const. art. VIII, § 1(a), (b); Tex. Tax Code § 11.13, § 23.23, § 23.231",
        verified="2026-08-01",
        notes=("Art. VIII, § 1(a) is the flat command that 'taxation shall be equal and "
               "uniform', and § 1(b) taxes all real property in proportion to its value. "
               "Texas has no property classes at all. FOUND AND REJECTED: the § 11.13 "
               "residence-homestead exemption, the § 23.23 10% homestead appraisal cap, "
               "and the § 23.231 20% circuit-breaker limitation on non-homestead real "
               "property valued at $5M or less. The last of those NARROWS the owner/rental "
               "gap rather than widening it, which is exactly why a fixed class multiplier "
               "cannot represent this regime. Logged as a roadmap item, not encoded."),
    ),
    "OK": ClassificationRule(
        usps="OK",
        rule_type=RULE_UNIFORM,
        authority="Okla. Const. art. X, § 8(A)(2), (B), § 8B, § 8C",
        verified="2026-08-01",
        notes=("§ 8(A)(2) assesses real property at 11%-13.5% of fair cash value, and "
               "§ 8(B) fixes ONE such percentage per county for real property, so the "
               "art. X use categories (agricultural, residential, commercial/industrial) "
               "drive valuation rather than the ratio, and none of them turns on tenure. "
               "FOUND AND REJECTED: the § 8B annual valuation caps, 3% for homestead and "
               "agricultural against 5% for everything else, and the § 8C senior "
               "valuation freeze, which is age- and income-gated."),
    ),
    "AR": ClassificationRule(
        usps="AR",
        rule_type=RULE_UNIFORM,
        authority="Ark. Const. art. 16, § 5, amend. 79; Ark. Code Ann. § 26-26-303",
        verified="2026-08-01",
        notes=("Art. 16, § 5 requires taxation 'equal and uniform throughout the State', "
               "and § 26-26-303 assesses all real property at 20% of appraised value with "
               "no tenure class. FOUND AND REJECTED: the amendment 79 homestead property "
               "tax credit ($500, rising to $600 for 2026 bills) and its split "
               "assessed-value caps, 5% a year for a homestead against 10% for all other "
               "real property. Same shape as Florida — a real owner/rental gap driven by "
               "a cap rather than a class ratio."),
    ),
    # ── Middle Atlantic ───────────────────────────────────────────────────────
    "NY": ClassificationRule(
        usps="NY",
        rule_type=RULE_EFFECTIVE,
        local_option=True,
        sub_state=dict.fromkeys(
            # The five boroughs. New York City is the only assessing unit whose class
            # system this table can resolve; see the notes for why the rest of the state
            # cannot be resolved at county granularity.
            ("36005", "36047", "36061", "36081", "36085"),
            ClassificationRule(
                usps="NY",
                rule_type=RULE_EFFECTIVE,
                threshold_basis=BASIS_DWELLING_UNITS,
                # RPTL § 1805(2) shields class two parcels with FEWER THAN 11 residential
                # units behind the same kind of growth cap class one gets (8%/yr, 30% over
                # five years). The city's own ETR study shows that shield working: small
                # rentals pay LESS than houses. So 11 is not a chosen breakpoint, it is
                # the statutory line where the correction actually begins.
                rental_unit_threshold=11,
                effective_multiplier=1.54 / 0.85,
                authority=("N.Y. Real Prop. Tax Law § 1802 (class definitions), § 1805 "
                           "(assessment caps); NYC Advisory Commission on Property Tax "
                           "Reform, Preliminary Report (2020), Figure 2 and Table 15"),
                verified="2026-08-01",
                notes=("Class one is 1-3 family residential; class two is all other "
                       "residential, so a rental building of four or more units is class "
                       "two. The NAIVE statutory multiplier is 4.70x — class one is "
                       "assessed at 6% of value and taxed at 19.843%, class two at 45% "
                       "and 12.439% (FY2026) — and encoding that would OVER-CORRECT by "
                       "roughly 2.6x. The city's own commission explains why: DOF's "
                       "published class two 'market value' is an income-capitalization "
                       "figure well below sales-based value, so ETRs computed on DOF "
                       "values 'considerably overstated the disparity'. Recomputed on a "
                       "common sales-based denominator (FY2019 median ETR per $100): "
                       "class one 1-3 family $0.85, class two small rentals $0.75, class "
                       "two large rentals $1.54, condos $0.63, coops $0.88. This model's "
                       "denominator is an ACS self-reported market value, which is the "
                       "sales-based concept, so $1.54/$0.85 = 1.81x is the matching "
                       "figure. The Lincoln Institute 50-state study puts the same ratio "
                       "at 2.55x; 1.81 is the under-correcting choice of the two. "
                       "UNDER-CORRECTS in Manhattan, where 1-3 family homes pay a $0.41 "
                       "median ETR against $1.02 on Staten Island."),
            ),
        ),
        authority=("N.Y. Real Prop. Tax Law § 1801 (special assessing units), § 1802; "
                   "§ 1903 (homestead/non-homestead, other assessing units)"),
        verified="2026-08-01",
        notes=("New York classifies BELOW the state level, in two separate regimes, which "
               "is why this is local_option with only New York City resolved. (1) RPTL "
               "art. 18 gives special assessing units — assessing units of 1,000,000 or "
               "more, meaning New York City and Nassau County — a four-class system. (2) "
               "RPTL art. 19 § 1903 lets any other approved assessing unit split a "
               "homestead from a non-homestead class, but only by local law, only after a "
               "revaluation, and one assessing unit at a time. A county contains many "
               "assessing units that may each choose differently, so art. 19 is NOT "
               "resolvable at the county granularity this table keys on, and towns that "
               "adopted it are under-corrected. NASSAU COUNTY (36059) IS DEFERRED: it is "
               "a special assessing unit under the same class definitions, but its "
               "assessment ratios and class rates differ from the city's and no "
               "sales-based ETR study comparable to the NYC commission's was found, so "
               "its multiplier would be a guess."),
    ),
    "NJ": ClassificationRule(
        usps="NJ",
        rule_type=RULE_UNIFORM,
        authority="N.J. Const. art. VIII, § 1, ¶ 1(a); N.J.S.A. 54:4-2.25, 54:4-23",
        verified="2026-08-01",
        notes=("¶ 1(a) requires assessment 'by uniform rules' and that all real property "
               "be assessed 'according to the same standard of value', which § 54:4-2.25 "
               "fixes as true value. The sole constitutional exception is agricultural "
               "and horticultural land, not tenure. Apartments are valued by income "
               "capitalization, but that is an appraisal METHOD reaching the same "
               "standard of value, not a separate class. FOUND AND REJECTED: the ANCHOR "
               "benefit and the senior freeze, both rebates paid outside the assessment."),
    ),
    "PA": ClassificationRule(
        usps="PA",
        rule_type=RULE_UNIFORM,
        authority=("Pa. Const. art. VIII, § 1; Valley Forge Towers Apartments N, LP v. "
                   "Upper Merion Area Sch. Dist., 163 A.3d 962 (Pa. 2017); 53 Pa. Stat. "
                   "§ 8583 (homestead exclusion)"),
        verified="2026-08-01",
        notes=("The Uniformity Clause forecloses classification of real property, and "
               "Valley Forge Towers is squarely about rental housing: a school district "
               "appealed only apartment-complex assessments and not single-family homes, "
               "and the Supreme Court held that unconstitutional because 'all property in "
               "a taxing district is a single class' and sub-classifications may not be "
               "treated disparately. Pennsylvania therefore cannot enact the kind of rule "
               "this table encodes. FOUND AND REJECTED: the Act 1 homestead/farmstead "
               "exclusion, which is an exclusion from assessed value for owner-occupied "
               "homes rather than a class."),
    ),
    # ── East North Central ────────────────────────────────────────────────────
    #
    # All five uniform. Two of them looked like corrections until the primary source was
    # read: Illinois (Cook's ordinance) and Ohio (the HB 920 class split).
    "IL": ClassificationRule(
        usps="IL",
        rule_type=RULE_UNIFORM,
        authority=("35 ILCS 200/9-145; Cook County Assessor, Definitions for the "
                   "Classifications of Real Property (class-code schedule)"),
        verified="2026-08-01",
        notes=("The rollout memo predicted Illinois as the second local_option case, on "
               "Cook County's classification ordinance. IT IS NOT. Cook's own class-code "
               "schedule groups major classes 1, 2 and 3 together under the heading "
               "'RESIDENTIAL ASSESSMENT CLASSES (10% level of assessment)' — class 2 is "
               "houses, condos and buildings of six units or fewer, class 3 is rental "
               "apartment buildings of seven or more units, and BOTH are 10%. The split "
               "that matters in Cook is residential against commercial (class 5A, 25%), "
               "and rental housing sits on the residential side of it. Class 3 was higher "
               "historically and was reduced by ordinance in stages to 10% by 2011, so an "
               "older secondary source shows a differential that no longer exists. The "
               "Assessor's three-year equalization study puts the REALISED levels at 9.15% "
               "for class 2 against 7.89% for class 3, so in practice Cook apartments are "
               "assessed below houses and even the observed gap runs the wrong way for a "
               "correction. Outside Cook, 35 ILCS 200/9-145 is a uniform 33-1/3%."),
    ),
    "OH": ClassificationRule(
        usps="OH",
        rule_type=RULE_UNIFORM,
        authority=("Ohio Const. art. XII, § 2a; Ohio Rev. Code § 5713.03, § 5713.041, "
                   "§ 319.301, § 323.152"),
        verified="2026-08-01",
        notes=("Ohio does have a real two-class system — art. XII, § 2a permits separate "
               "HB 920 tax-reduction factors for class I and class II — but § 5713.041 "
               "draws the line by USE, not tenure: 'Lands and improvements thereon used "
               "for residential or agricultural purposes shall be classified as "
               "residential/agricultural real property, and all other lands and "
               "improvements thereon shall be classified as nonresidential/agricultural.' "
               "An apartment building is used for residential purposes, so it is class I "
               "alongside a detached house. Same shape as Louisiana. Assessment is a "
               "uniform 35% of true value. FOUND AND REJECTED: the § 323.152 2.5% "
               "owner-occupancy credit and the homestead exemption, both credits."),
    ),
    "MI": ClassificationRule(
        usps="MI",
        rule_type=RULE_UNIFORM,
        authority="Mich. Const. art. IX, §§ 3, 31; Mich. Comp. Laws § 211.7cc, § 211.34d",
        verified="2026-08-01",
        notes=("Uniform assessment at 50% of true cash value, with no tenure class. "
               "FOUND AND REJECTED, and the most interesting rejection in the table: the "
               "§ 211.7cc Principal Residence Exemption relieves an owner-occupied "
               "principal residence of up to 18 mills, and multi-family and rental "
               "property do not qualify — a large, genuinely tenure-based differential. "
               "It still warrants no correction here, for a sharper reason than the "
               "general exclusion rule: those 18 mills are a SCHOOL OPERATING levy, and "
               "this dimension nets school taxes out of BOTH sides (non-school cost model, "
               "school_tax_share on the revenue side). The gap is real but sits outside "
               "what the fiscal ratio measures. This case RESOLVED an open question against "
               "South Carolina, whose note used to claim that an owner-occupied exemption "
               "from school operating millage made its 1.50x under-correct. It does not: "
               "the exemption moves the level of the observed owner rate, which is the "
               "base for both legs, so it cancels out of the ratio. Michigan is the clean "
               "case because it has no class split at all to confuse the issue. What both "
               "states DO share is a genuine revenue-model problem — a county-wide "
               "school_tax_share netted off an owner-occupied rate that has already lost "
               "its school component — logged in "
               "research/infrastructure-burden-research.md."),
    ),
    "IN": ClassificationRule(
        usps="IN",
        rule_type=RULE_UNIFORM,
        authority="Ind. Const. art. 10, § 1(f); Ind. Code § 6-1.1-20.6",
        verified="2026-08-01",
        notes=("FOUND AND REJECTED: the constitutional circuit-breaker caps — 1% of gross "
               "assessed value for an owner-occupied homestead, 2% for other residential "
               "and agricultural, 3% for commercial. These bind hard (statewide credits "
               "exceeded $1.2 billion in 2025), so this is the least comfortable uniform "
               "record in the table. STRUCTURALLY DIFFERENT from Florida's and Texas's "
               "caps, which limit the GROWTH of assessed value and so depend on holding "
               "period and appreciation. Indiana caps tax as a share of CURRENT assessed "
               "value, by class, with no time dependence: where the local gross rate "
               "exceeds 2% the owner/rental ratio is exactly 2.0, where it is under 1% it "
               "is exactly 1.0, and in between it is the gross rate over 1%. That makes "
               "Indiana the most tractable member of the cap roadmap item, not a Save Our "
               "Homes lookalike. It is unencodable today only for want of county GROSS "
               "rates: the bundled ACS effective_tax_rate is the owner-occupied rate, "
               "already capped, so the gross rate cannot be recovered from it."),
    ),
    "WI": ClassificationRule(
        usps="WI",
        rule_type=RULE_UNIFORM,
        authority="Wis. Const. art. VIII, § 1; Wis. Stat. § 70.32",
        verified="2026-08-01",
        notes=("The uniformity clause forecloses classification of real property as "
               "firmly as Pennsylvania's does: for direct taxation under the rule of "
               "uniformity there can be but one constitutional class, and the burden must "
               "be borne as nearly as practicable by all property according to value. "
               "§ 70.32 assesses real property at full value with no tenure distinction. "
               "FOUND AND REJECTED: the lottery and gaming credit, available only for an "
               "owner-occupied primary residence."),
    ),
    # ── New England ───────────────────────────────────────────────────────────
    #
    # The most legally varied division. Vermont is the sharpest test of the rule that a
    # tenure split confined to a SCHOOL levy owes no correction; Rhode Island and
    # Connecticut are the first states whose classification is real, reaches rental
    # housing, and cannot be resolved at the county granularity this table keys on.
    "VT": ClassificationRule(
        usps="VT",
        rule_type=RULE_UNIFORM,
        authority="32 V.S.A. § 5401(7), (10), § 5402; Vt. Const. ch. II, § 66",
        verified="2026-08-01",
        notes=("On its face the cleanest RULE_RATE candidate in the country: § 5402 imposes "
               "a statewide education property tax at DIFFERENT RATES on homestead and "
               "nonhomestead property — roughly $1.00 spending-adjusted against $1.59, "
               "about 1.6x — statutory, statewide, tenure-based, no local option. It still "
               "owes no correction, for the same reason Michigan's Principal Residence "
               "Exemption does not: the split lives entirely inside an EDUCATION levy, and "
               "this dimension nets school taxes out of both the cost and the revenue side. "
               "Contrast New Hampshire next door, whose statewide education tax was upheld "
               "in 2025 precisely because it is uniform in rate. UNDER-CORRECTS, and the "
               "reason is worth stating: since Act 60/68 the education tax IS most of the "
               "Vermont property tax bill, and 96% of Vermont's population sits on the "
               "NATIONAL-AVERAGE school share (0.4092) rather than a measured one, because "
               "Vermont funds schools through town-dependent systems carrying no separate "
               "Census of Governments levy. So the model nets away ~41% of a bill that is "
               "far more than 41% education, and the remainder still carries the "
               "differential. That is a revenue-side defect, not a class ratio: encoding "
               "1.59 here would double-count against whatever the 41% netting does remove, "
               "and would become an outright over-correction the moment the school share "
               "is fixed. See research/infrastructure-burden-research.md."),
    ),
    "MA": ClassificationRule(
        usps="MA",
        rule_type=RULE_UNIFORM,
        local_option=False,
        authority="Mass. Gen. Laws ch. 40, § 56; ch. 59, § 2A, § 38; Mass. Const. pt. 2, ch. 1, § 1, art. 4",
        verified="2026-08-01",
        notes=("Massachusetts DOES permit a local classification shift — ch. 40, § 56 lets a "
               "municipality adopt a residential factor moving tax burden toward "
               "commercial, industrial and personal property — which made this look like "
               "the canonical local-option case. It is not, because the shift cannot reach "
               "rental housing: assessors classify real property into residential, open "
               "space, commercial or industrial, and RESIDENTIAL INCLUDES ALL PROPERTY "
               "CONTAINING ONE OR MORE UNITS FOR HUMAN HABITATION, large apartment "
               "buildings among them. The shift moves burden between residential and "
               "commercial; apartments sit on the residential side of it. Same shape as "
               "Virginia, and local_option is set False deliberately so the record says "
               "'the option does not reach rental housing' rather than 'not yet resolved'."),
    ),
    "ME": ClassificationRule(
        usps="ME",
        rule_type=RULE_UNIFORM,
        authority="Me. Const. art. IX, § 8; 36 M.R.S. § 701-A, § 681",
        verified="2026-08-01",
        notes=("Art. IX, § 8 requires that all taxes on real estate be 'apportioned and "
               "assessed equally according to the just value thereof'. Its only exceptions "
               "are classified farm, open space, forest land and working waterfront, all "
               "use-based and none turning on tenure. FOUND AND REJECTED: the § 681 "
               "homestead exemption, available only for a permanent residence."),
    ),
    "NH": ClassificationRule(
        usps="NH",
        rule_type=RULE_UNIFORM,
        authority="N.H. Const. pt. II, art. 5; RSA 75:1; RSA 76:3",
        verified="2026-08-01",
        notes=("Art. 5 permits only 'proportional and reasonable' assessments and rates, "
               "and RSA 75:1 appraises all property at full and true value with no tenure "
               "class. New Hampshire also levies a statewide education property tax (RSA "
               "76:3), and it is the instructive contrast with Vermont: the New Hampshire "
               "Supreme Court upheld it in 2025 precisely because it is administered 'equal "
               "in valuation and uniform in rate throughout the state', where Vermont's "
               "equivalent splits homestead from nonhomestead. Two neighbours, the same "
               "instrument, opposite answers."),
    ),
    "RI": ClassificationRule(
        usps="RI",
        rule_type=RULE_RATE,
        local_option=True,
        # Deliberately no sub_state: the choice is municipal and Rhode Island's counties
        # have no government at all, so no county FIPS can express it. _reclassified
        # returns None on the empty lookup, so this yields no correction — the safe
        # direction — while still recording that a real classification exists.
        authority="R.I. Gen. Laws § 44-5-11.8, § 44-5-11.18",
        verified="2026-08-01",
        notes=("A REAL classification that reaches rental housing, which this table cannot "
               "resolve. § 44-5-11.8 puts residential real estate of NO MORE THAN FIVE "
               "dwelling units in class 1, so a six-unit building falls to class 2 "
               "(commercial and industrial) unless the city provides otherwise; Providence "
               "has its own regime under § 44-5-11.18 with class 1A (fewer than six units), "
               "1B (six to ten) and 1C (more than ten), and rate caps relative to 1A. The "
               "choice is made per municipality — 39 cities and towns — and Rhode Island's "
               "five counties are not governmental units, so a county FIPS cannot express "
               "it. Recorded as local_option with an EMPTY sub_state: no correction "
               "applies, but the record says a classification exists rather than claiming "
               "there is none. UNDER-CORRECTS in every city that taxes 6+ unit buildings "
               "commercially."),
    ),
    "CT": ClassificationRule(
        usps="CT",
        rule_type=RULE_ASSESSMENT,
        local_option=True,
        # Same shape as Rhode Island; Connecticut abolished county government in 1960.
        authority="Conn. Gen. Stat. § 12-62a, § 12-62n, § 12-62r",
        verified="2026-08-01",
        notes=("§ 12-62a fixes a uniform 70% assessment ratio statewide, which alone would "
               "make Connecticut uniform. But § 12-62n is a MUNICIPAL OPTION to set "
               "separate assessment rates, and it names 'apartment property' as a category "
               "distinct from 'residential property' — so unlike the Massachusetts shift, "
               "this one does reach rental housing (§ 12-62r governs annual adjustment of "
               "those rates). The choice is per municipality and Connecticut abolished "
               "county government in 1960, so no county FIPS can express it. Recorded like "
               "Rhode Island: local_option with an EMPTY sub_state, no correction applied, "
               "but the classification recorded as real rather than absent."),
    ),
    # ── West North Central ────────────────────────────────────────────────────
    #
    # Two corrections, and they make a useful pair: both turn on FOUR units, but Minnesota
    # counts units held for rent while North Dakota counts family units the structure
    # accommodates. Same number, different basis, different answer for an owner-occupied
    # fourplex.
    "MN": ClassificationRule(
        usps="MN",
        rule_type=RULE_ASSESSMENT,
        threshold_basis=BASIS_RENTAL_UNITS,
        rental_unit_threshold=4,
        # Minnesota "class rates" multiply market value to give tax capacity, which the
        # local rate is then applied to — so a class rate does the job of an assessment
        # ratio. Class 1a homestead vs class 4a apartment.
        residential=0.0100,
        commercial=0.0125,
        authority="Minn. Stat. § 273.13 subd. 22, subd. 25",
        verified="2026-08-01",
        notes=("Class 1a (residential homestead) is 1.00% of the first $500,000 and 1.25% "
               "above; class 4a (residential real estate containing FOUR OR MORE units and "
               "held for rent for 30 days or more) is a flat 1.25%. TENURE ALONE DOES NOT "
               "RECLASSIFY: a rented single-family home or triplex is class 4bb, which "
               "carries class 1a's rates exactly, so the threshold is 4 rather than the 1 "
               "used by Alabama, Mississippi and South Carolina. The threshold counts "
               "RENTAL units because 4a requires the units be held for rent — Minnesota "
               "assessors split an owner-occupied fourplex between 1a and 4a, which a "
               "single-class model cannot express, so counting rental units leaves it "
               "unreclassified, the under-correcting side of that edge. The 1a tiering "
               "would make the multiplier value-dependent, but no Minnesota county has a "
               "median owner-occupied value at or above $500,000 (highest is Carver at "
               "$453,600, median of county medians $231,900), so the 1a rate at the ACS "
               "baseline is a flat 1.00% statewide and 1.25 is exact rather than a bound."),
    ),
    "ND": ClassificationRule(
        usps="ND",
        rule_type=RULE_ASSESSMENT,
        threshold_basis=BASIS_DWELLING_UNITS,
        rental_unit_threshold=4,
        residential=0.09,
        commercial=0.10,
        authority="N.D.C.C. § 57-02-01(5), (14), § 57-02-27",
        verified="2026-08-01",
        notes=("§ 57-02-27 values residential property at 9% of assessed value and "
               "commercial at 10%, and § 57-02-01(14) draws the line by UNIT COUNT with no "
               "tenure element at all: residential 'does not include structures which "
               "accommodate four or more separate family units', and § 57-02-01(5) puts "
               "'any tract of land with four or more separate family units' in commercial. "
               "So the basis is DWELLING units, not rental units — an owner-occupied "
               "fourplex is commercial in North Dakota, where the same building stays "
               "residential in Minnesota. A separately parceled condominium still escapes, "
               "each parcel accommodating one family unit. The statute itself does not "
               "define the classes; the definitions are § 57-02-01, as set out in the Tax "
               "Commissioner's assessment guidance."),
    ),
    "SD": ClassificationRule(
        usps="SD",
        rule_type=RULE_UNIFORM,
        authority="S.D. Codified Laws § 10-13-39, § 10-13-40; S.D. Const. art. XI, § 2",
        verified="2026-08-01",
        notes=("FOUND AND REJECTED: the § 10-13-39 owner-occupied single-family "
               "classification, which cuts the SCHOOL GENERAL FUND levy roughly in half "
               "for a principal residence, with § 10-13-40 spreading the full levy against "
               "all district property not so classified. A large, genuinely tenure-based "
               "differential — and confined to a school levy, which this dimension nets "
               "out of both the cost and the revenue side. THIRD INSTANCE of that pattern "
               "after Michigan's Principal Residence Exemption and Vermont's "
               "homestead/nonhomestead education rate; see those notes and the shared "
               "test. Outside the school levy South Dakota has no tenure class."),
    ),
    "IA": ClassificationRule(
        usps="IA",
        rule_type=RULE_UNIFORM,
        authority="Iowa Code § 441.21; 2013 Iowa Acts ch. 123; 2021 Iowa Acts ch. 177",
        verified="2026-08-01",
        notes=("Iowa DID have a separate multiresidential class covering apartments, "
               "created in 2013 and phased down toward the residential rollback through "
               "2022 — and it was ELIMINATED effective January 1, 2022, those properties "
               "recategorized as residential. Apartments now take the same assessment "
               "limitation (rollback) as houses, so there is nothing to correct. Same trap "
               "as Cook County: a secondary source written before 2022 shows a "
               "differential that no longer exists, which is why the sourcing standard "
               "requires reading the current primary text."),
    ),
    "MO": ClassificationRule(
        usps="MO",
        rule_type=RULE_UNIFORM,
        authority="Mo. Const. art. X, § 4(b); Mo. Rev. Stat. § 137.016, § 137.115",
        verified="2026-08-01",
        notes=("Art. X, § 4(b) does create subclasses — residential 19%, agricultural 12%, "
               "commercial 32% — but § 137.016 defines residential by USE: 'all real "
               "property improved by a structure which is used or intended to be used for "
               "residential living by human occupants', with no tenure or unit-count "
               "qualifier, and the State Tax Commission subclassifies condominiums and "
               "apartments as residential. So an apartment building is 19% beside a "
               "detached house. Third use-based split after Louisiana and Ohio."),
    ),
    "KS": ClassificationRule(
        usps="KS",
        rule_type=RULE_UNIFORM,
        authority="Kan. Const. art. 11, § 1(a); Kan. Stat. Ann. § 79-1439",
        verified="2026-08-01",
        notes=("Kansas classifies real property — residential 11.5% against commercial and "
               "industrial 25% — but the constitution names rental housing INTO the "
               "residential class expressly: 'real property used for residential purposes "
               "INCLUDING MULTI-FAMILY RESIDENTIAL REAL PROPERTY and real property "
               "necessary to accommodate a residential community of mobile or manufactured "
               "homes' is assessed at 11.5%. The clearest wording of the use-based pattern "
               "found so far — no inference needed, apartments are named."),
    ),
    "NE": ClassificationRule(
        usps="NE",
        rule_type=RULE_UNIFORM,
        authority="Neb. Const. art. VIII, § 1; Neb. Rev. Stat. § 77-201",
        verified="2026-08-01",
        notes=("Art. VIII, § 1 requires taxes levied 'by valuation uniformly and "
               "proportionately upon all real property'. Its ONLY carve-out is "
               "agricultural and horticultural land, which the Legislature may make a "
               "separate class — a use exception, not a tenure one. § 77-201 assesses real "
               "property at 100% of actual value, agricultural at 75%. No tenure class "
               "exists or could."),
    ),
    # ── Mountain ──────────────────────────────────────────────────────────────
    #
    # Every one uniform, and the reason is a division-wide pattern rather than eight
    # coincidences: four of these states have a headline owner-occupied preference, and NOT
    # ONE of them excludes long-term rental housing. Each splits on how the home is
    # OCCUPIED — primary residence against second home or short-term rental — not on who
    # owns it. These are amenity and resort states whose political target is the
    # non-resident owner, not the landlord.
    "UT": ClassificationRule(
        usps="UT",
        rule_type=RULE_UNIFORM,
        authority="Utah Code § 59-2-102, § 59-2-103; Utah Const. art. XIII, § 3",
        verified="2026-08-01",
        notes=("The 45% primary residential exemption looks like a 1.82x tenure split and "
               "is not one: it follows OCCUPANCY, not ownership. The Utah County Assessor's "
               "explainer is explicit — 'Apartments, condos and mobile homes also qualify … "
               "Properties inhabited by TENANTS ALSO QUALIFY, if they reside in the property "
               "for 183 consecutive days or more in a calendar year.' What loses the "
               "exemption is transient use, second homes and condominiums in rental pools, "
               "not renting per se. A long-term apartment is taxed on the same 55% of fair "
               "market value as an owner-occupied house. NEAR MISS: a first pass on the "
               "state tax commission's own page returned the confident answer that a "
               "landlord renting to a tenant would not qualify, which the assessor's "
               "document contradicts; encoding it would have put one of the largest "
               "multipliers in this table on 1% of the population in the wrong direction."),
    ),
    "MT": ClassificationRule(
        usps="MT",
        rule_type=RULE_UNIFORM,
        authority="Mont. Code Ann. § 15-6-134; 2025 Mont. Laws ch. 674 (HB 231)",
        verified="2026-08-01",
        notes=("HB 231 (2025) created a reduced 'homestead rate', which reads as an "
               "owner-occupied preference until you read the definition: the rate covers "
               "principal residences AND LONG-TERM RENTALS, where long-term rental is "
               "defined to include a unit of a multiple-unit dwelling. The higher rate "
               "falls on second homes and short-term rentals. Same shape as Utah — "
               "occupancy, not tenure — and the reason this division needed reading rather "
               "than assuming."),
    ),
    "AZ": ClassificationRule(
        usps="AZ",
        rule_type=RULE_UNIFORM,
        authority=("A.R.S. § 42-12003, § 42-12004, § 42-15003, § 42-15004; § 15-972; "
                   "§ 42-11132"),
        verified="2026-08-01",
        notes=("The rollout memo predicted Arizona as the division's real tenure split — "
               "legal class 3 is owner-occupied primary residence, class 4 is leased or "
               "rented residential, which certainly looks like one. BOTH ARE ASSESSED AT "
               "10%. The only difference is the homeowner rebate: the state pays 40% of the "
               "primary SCHOOL district tax on class 3, capped at $600 a year. That is a "
               "school levy, which this dimension nets out of both the cost and the revenue "
               "side. FOURTH school-levy rejection after Michigan, Vermont and South "
               "Dakota — see the shared test."),
    ),
    "CO": ClassificationRule(
        usps="CO",
        rule_type=RULE_UNIFORM,
        authority=("Colo. Const. art. X, § 3(1)(b); Colo. Rev. Stat. § 39-1-104; "
                   "2024 Colo. Sess. Laws (2nd Ex. Sess.) HB24B-1001"),
        verified="2026-08-01",
        notes=("HB24B-1001 sets a single assessment rate for ALL residential property on "
               "local-government levies — 6.25% for 2025 forward — with multi-family "
               "expressly inside the residential class. The rate does vary, but by LEVY "
               "TYPE (6.25% local against 7.05% school), not by occupancy. The "
               "owner-occupied primary residence subclass Colorado created for 2025 carries "
               "the senior and veteran homestead exemptions, not a different ordinary rate. "
               "The residential/non-residential split (6.25% against 27%) is use-based with "
               "apartments on the residential side, like Louisiana, Ohio, Missouri and "
               "Kansas."),
    ),
    "WY": ClassificationRule(
        usps="WY",
        rule_type=RULE_UNIFORM,
        authority=("Wyo. Const. art. 15, § 11 (as amended 2024); Wyo. Stat. § 39-13-103; "
                   "2025 Wyo. Sess. Laws ch. 106 (SF 69)"),
        verified="2026-08-01",
        notes=("Amendment A (2024) made residential real property a fourth constitutional "
               "class and AUTHORIZED a subclass for owner-occupied primary residences. What "
               "the 2025 legislature actually enacted is SF 69, an EXEMPTION rather than a "
               "class rate: 25% of the first $1,000,000 of fair market value. It applied to "
               "ALL residential structures for FY2026 and narrows to owner-occupied "
               "dwellings from FY2027. FOUND AND REJECTED on two grounds — it is an "
               "exemption, and it is value-capped, so the gap is value-dependent in the "
               "Idaho and Florida shape rather than a fixed class ratio. RE-EXAMINE once "
               "the FY2027 owner-occupied-only phase has been in effect for a full "
               "assessment year: that is the one Mountain preference that does narrow to "
               "ownership, and if it is ever restated as a class rate it becomes encodable."),
    ),
    "NV": ClassificationRule(
        usps="NV",
        rule_type=RULE_UNIFORM,
        authority="Nev. Rev. Stat. § 361.225, § 361.4723, § 361.4724; Nev. Const. art. 10, § 1",
        verified="2026-08-01",
        notes=("All property is assessed at 35% of taxable value, uniformly. FOUND AND "
               "REJECTED: the § 361.4723 partial abatement, which caps the annual increase "
               "in the tax bill at 3% for an owner's primary residence against up to 8% for "
               "everything else under § 361.4724. A growth cap, so the gap depends on "
               "holding period and appreciation rather than being a fixed class ratio — the "
               "Florida shape, and excluded for the same reason."),
    ),
    "ID": ClassificationRule(
        usps="ID",
        rule_type=RULE_UNIFORM,
        authority="Idaho Code § 63-602G, § 63-205; Idaho Const. art. VII, § 5",
        verified="2026-08-01",
        notes=("FOUND AND REJECTED: the § 63-602G homeowner's exemption, the lesser of "
               "$125,000 or 50% of market value, available only where the homestead is "
               "owner-occupied and the owner's primary dwelling. Genuinely tenure-based, "
               "unlike Utah's — but VALUE-CAPPED, so the relief is 50% on a $250,000 home "
               "and 25% on a $500,000 one. The gap is value-dependent rather than a fixed "
               "class ratio, which is exactly what the exclusion rule keeps out."),
    ),
    "NM": ClassificationRule(
        usps="NM",
        rule_type=RULE_UNIFORM,
        authority="N.M. Const. art. VIII, § 1; N.M. Stat. Ann. § 7-37-3, § 7-36-21.2",
        verified="2026-08-01",
        notes=("Art. VIII, § 1 requires taxes 'equal and uniform upon subjects of taxation "
               "of the same class' at no more than 33-1/3% of value, and § 7-37-3 sets that "
               "one-third ratio for all property. FOUND AND REJECTED: § 7-36-21.2, which "
               "limits annual increases in residential valuation and may apply the "
               "limitation by owner-occupancy, age or income. A valuation growth cap, so "
               "the Nevada and Florida shape rather than a class ratio."),
    ),
    # ── Pacific ───────────────────────────────────────────────────────────────
    "WA": ClassificationRule(
        usps="WA",
        rule_type=RULE_UNIFORM,
        authority="Wash. Const. art. VII, § 1, § 2; Wash. Rev. Code § 84.40.030",
        verified="2026-08-01",
        notes=("The most explicit uniform text in the table: art. VII, § 1 provides that "
               "'ALL REAL ESTATE SHALL CONSTITUTE ONE CLASS' and that taxes 'shall be "
               "uniform upon the same class of property', with § 84.40.030 valuing all "
               "property at 100% of true and fair value. One class admits no split, so "
               "there is nothing to reject."),
    ),
    "OR": ClassificationRule(
        usps="OR",
        rule_type=RULE_UNIFORM,
        authority=("Or. Const. art. I, § 32; art. IX, § 1; art. XI, § 11, § 11b; "
                   "Or. Rev. Stat. § 308.149, § 308.153, § 308.156; OAR 150-308-0170"),
        verified="2026-08-01",
        notes=("Taxation uniform on the same class of subjects. FOUND AND REJECTED on "
               "three counts. (1) Measure 50's art. XI, § 11 maximum assessed value, "
               "which may not grow more than 3% a year — a growth cap in the Florida "
               "shape. (2) Measure 5's art. XI, § 11b limits, whose two categories are "
               "defined by THE PURPOSE THE TAX FUNDS — the public school system against "
               "government operations other than the public school system — and not by "
               "property type, so like Vermont's split it cannot reach a class of "
               "housing. (3) The changed property ratio of § 308.153 and § 308.156, "
               "which places newly added value at the same assessed-to-market ratio as "
               "similar existing property. It keys on the § 308.149 'property class', "
               "which OAR 150-308-0170 takes from the Department of Revenue's USE "
               "classification — and it equalises new value rather than preferring "
               "anyone. Nothing in Oregon keys on tenure."),
    ),
    "CA": ClassificationRule(
        usps="CA",
        rule_type=RULE_UNIFORM,
        authority="Cal. Const. art. XIII, § 1, § 3(k); art. XIII A, § 1, § 2, § 2.1",
        verified="2026-08-01",
        notes=("Art. XIII, § 1(a): 'All property is taxable and SHALL BE ASSESSED AT THE "
               "SAME PERCENTAGE OF FAIR MARKET VALUE.' One ratio, and art. XIII A, § 1 "
               "caps the ad valorem rate at 1% for everyone, so the legislature has no "
               "classification power to exercise. FOUND AND REJECTED: the § 3(k) "
               "homeowners' exemption, a flat $7,000 of full value for an owner-occupied "
               "principal residence — a fixed dollar exemption in the Kentucky shape, and "
               "trivial against a modern assessment; and PROPOSITION 13, art. XIII A, § 2, "
               "whose base-year value plus 2% growth cap with reassessment on change of "
               "ownership produces a large owner/rental gap that depends on holding "
               "period rather than on class. California is the largest member of the "
               "cap-driven divergence roadmap item, and the one where the cap is NOT "
               "tenure-neutral: under Proposition 19, art. XIII A, § 2.1, an inherited "
               "home keeps its base year value only if it 'continues as the family home "
               "of the transferee', so an inherited rental is reassessed and an inherited "
               "primary residence is not. Still a transfer-and-cap mechanism rather than "
               "a class ratio, so it is documented, not encoded."),
    ),
    "AK": ClassificationRule(
        usps="AK",
        rule_type=RULE_UNIFORM,
        authority="Alaska Stat. § 29.45.030, § 29.45.050, § 29.45.110",
        verified="2026-08-01",
        notes=("Section 29.45.110 assesses all property at full and true value, with no "
               "class ratios. FOUND AND REJECTED: the § 29.45.050 optional exemptions, "
               "which a municipality may adopt by ordinance or voter approval. They are "
               "dollar-capped and gated on senior, disabled-veteran or residence status "
               "rather than on tenure, so they are locally optional capped exemptions "
               "rather than a classification — and unlike Rhode Island and Connecticut "
               "there is no municipal rule that reaches rental housing as a class, so no "
               "local_option record is warranted."),
    ),
    # HI is deliberately NOT encoded, and for a different reason than DC. Its four
    # counties ARE the taxing units, so unlike Rhode Island and Connecticut a county
    # FIPS resolves the rule cleanly, and the split is genuinely tenure-based: Honolulu's
    # Residential A, Kaua'i's Non-Owner-Occupied and the Maui and Hawai'i County
    # Apartment classes all separate an owner's principal residence from rented housing.
    # What stops it is the SIZE. Modelled on the FY26 rate schedules at a large building,
    # the implied multipliers are Kaua'i 3.56x, Honolulu 3.20x, Maui 2.12x and Hawai'i
    # County 1.97x — two of the four breach CLASSIFICATION_MULT_CEIL, the research-error
    # tripwire, and Honolulu's Residential A is a two-tier bracket above $1,000,000, so
    # its effective rate is value-dependent in the Florida shape rather than a fixed
    # class ratio. Under "when in doubt, under-correct" Hawaii stays out of the table
    # until the brackets are modelled properly. See
    # research/property-tax-classification-research.md.
    # DC is deliberately NOT encoded. It restructured its classes for tax year 2025 (a
    # new Class 1A / 1B split), and sources conflict on where a multifamily rental
    # building lands: one reading keeps residential improved property in Class 1A
    # regardless of unit count, another pushes anything above Class 1B's two-unit limit
    # into the Class 2 commercial catch-all. Those give very different multipliers, so
    # under the sourcing standard DC stays unencoded rather than guessed. See
    # research/property-tax-classification-research.md.
}


def rule_for(state: str | None) -> ClassificationRule | None:
    """The rule for a USPS code, or ``None`` if the state has not been researched."""
    return CLASSIFICATION_RULES.get((state or "").strip().upper())


def rental_unit_count(units: int, *, owner_occupied: bool | None = None,
                      separately_parceled: bool | None = None) -> int:
    """Rental units on a parcel — the count that drives classification.

    ``units`` is the number of dwelling units on the parcel. ``owner_occupied`` says whether
    the owner lives in one of them; ``None`` means unknown, which resolves to the ACS-backed
    default (a multi-unit building is rental, a single home is owner-occupied). One unit is
    subtracted when the owner occupies one, which is what keeps an owner-occupied duplex
    residential under AG Op. 25-016.

    ``separately_parceled=True`` means each unit is its own tax parcel — a condominium — so
    no parcel holds more than one rental unit however large the building is. The unit count
    reaching this module comes from a *structure* record (NSI), which cannot tell a condo
    tower from a rental tower, so this is the caller's way of saying which it is.
    """
    units = max(int(units or 1), 1)
    if separately_parceled:
        units = 1
    if owner_occupied is None:
        owner_occupied = not (units > 1 and MULTIUNIT_RENTAL_DEFAULT)
    return max(units - 1, 0) if owner_occupied else units


def _reclassified(rule: ClassificationRule | None, units: int, *,
                  owner_occupied: bool | None = None,
                  separately_parceled: bool | None = None,
                  county_fips: str | None = None) -> ClassificationRule | None:
    """The rule to apply if this parcel is reclassified, else ``None``.

    Resolves local-option states through ``sub_state`` first: a state whose classification
    is set below the state level yields nothing unless the parcel's county carries its own
    entry.
    """
    if rule is None or rule.rule_type == RULE_UNIFORM:
        return None
    if rule.local_option:
        key = str(county_fips).strip().zfill(5) if county_fips else None
        rule = rule.sub_state.get(key) if key else None
        if rule is None:
            return None
    threshold = rule.rental_unit_threshold
    if not threshold:
        return None
    if rule.threshold_basis == BASIS_DWELLING_UNITS:
        count = 1 if separately_parceled else max(int(units or 1), 1)
    else:
        count = rental_unit_count(units, owner_occupied=owner_occupied,
                                  separately_parceled=separately_parceled)
    return rule if count >= threshold else None


def classified_assess_ratio(state: str | None, units: int, *,
                            owner_occupied: bool | None = None,
                            separately_parceled: bool | None = None,
                            county_fips: str | None = None) -> float | None:
    """The commercial assessment ratio, if this parcel is classified commercial.

    For the **statutory** path only — a caller applying a real assessment ratio against a
    real millage. Returns ``None`` in every other case: no researched rule, a ``RULE_RATE``
    state (where the ratio does not differ, only the millage does), or a parcel that stays
    residential. Returning ``None`` rather than the residential ratio is deliberate — it
    makes this a strictly *additive* correction that can only move parcels the statute
    actually reclassifies, so a caller supplying its own assessment basis is never silently
    overridden for ordinary housing.
    """
    rule = _reclassified(rule_for(state), units, owner_occupied=owner_occupied,
                         separately_parceled=separately_parceled, county_fips=county_fips)
    if rule is None or rule.rule_type != RULE_ASSESSMENT:
        return None
    return rule.commercial


def classification_multiplier(state: str | None, units: int, *,
                              owner_occupied: bool | None = None,
                              separately_parceled: bool | None = None,
                              county_fips: str | None = None) -> float:
    """How much more this parcel pays than an owner-occupied home of the same value.

    For the **national** path — a caller applying an ACS observed effective rate, which is
    computed over owner-occupied homes and therefore already carries the residential class
    in its denominator. Returns exactly ``1.0`` unless the parcel is reclassified, so an
    unresearched state, a uniform state, an unresolved local-option state, and ordinary
    housing all leave the rate untouched.
    """
    rule = _reclassified(rule_for(state), units, owner_occupied=owner_occupied,
                         separately_parceled=separately_parceled, county_fips=county_fips)
    return 1.0 if rule is None else rule.multiplier()


def classification_for(state: str | None, units: int, *,
                       owner_occupied: bool | None = None,
                       separately_parceled: bool | None = None,
                       county_fips: str | None = None) -> dict:
    """Reporting view of the classification decision — always a dict, never ``None``.

    The two computational accessors above return ``None``/``1.0`` because absence *is* the
    signal there; this one honors the always-return-a-dict convention the crosswalk loaders
    use, and carries the provenance a label or a coverage report needs.
    """
    rule = rule_for(state)
    applied = _reclassified(rule, units, owner_occupied=owner_occupied,
                            separately_parceled=separately_parceled, county_fips=county_fips)
    researched = rule is not None
    return {
        "state": (state or "").strip().upper() or None,
        "rule_type": rule.rule_type if researched else None,
        "researched": researched,
        "applied": applied is not None,
        "multiplier": applied.multiplier() if applied is not None else 1.0,
        "assess_ratio": (applied.commercial
                         if applied is not None and applied.rule_type == RULE_ASSESSMENT
                         else None),
        "authority": applied.authority if applied is not None else (
            rule.authority if researched else None),
        "verified": rule.verified if researched else None,
        "local_option": bool(rule.local_option) if researched else False,
        "label": (f"{rule.usps} {rule.rule_type}" if researched
                  else "no researched classification rule"),
    }


def unresearched_jurisdictions() -> list[str]:
    """Scored jurisdictions with no classification record yet, sorted."""
    return sorted(SCORED_JURISDICTIONS - set(CLASSIFICATION_RULES))


def active_basis() -> tuple[str, ...]:
    """Fingerprint of the jurisdictions currently carrying a correction, e.g.
    ``("TN:1.60",)``.

    ``score/all_dimensions.INFRA_XS_BASIS`` records this as of the last recalibration, and
    a test asserts the two match — so adding a state without re-anchoring the national
    breakpoints fails CI instead of silently mis-scoring every parcel in the country.
    A sorted tuple rather than a hash, so the diff is legible as a changelog.

    Sub-state rules are walked too, keyed ``USPS/county_fips``. A local-option state's
    container carries no legs of its own, so counting only top-level rules would let New
    York City enter the reference distribution while the fingerprint stayed unchanged —
    exactly the silent mis-scoring this guard exists to prevent.
    """
    entries = []
    for usps, rule in CLASSIFICATION_RULES.items():
        if rule.rule_type != RULE_UNIFORM and rule.multiplier() > 1.0:
            entries.append(f"{usps}:{rule.multiplier():.2f}")
        for county_fips, sub in rule.sub_state.items():
            if sub.rule_type != RULE_UNIFORM and sub.multiplier() > 1.0:
                entries.append(f"{usps}/{county_fips}:{sub.multiplier():.2f}")
    return tuple(sorted(entries))
