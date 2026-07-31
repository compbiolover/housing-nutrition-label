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
Only Tennessee is encoded. Every other jurisdiction returns "no correction", which is a
real coverage gap and not a claim that other states lack split rolls — several do, with
different thresholds and different ratios. The rollout plan is
``research/property-tax-classification-rollout.md``; extending the table means reading each
state's constitution or code, one at a time, and must not be guessed from a secondary
source.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from housing_label.data.states import SCORED_JURISDICTIONS

# Date the encoded rules were last checked against their primary sources, in aggregate.
# Per-record ``verified`` gives the per-state granularity; this is the table-level vintage,
# playing the same role as ``DATA_VINTAGE`` in the crosswalk loaders.
LAW_AS_OF = "2026-07-31"

# ── Rule types ────────────────────────────────────────────────────────────────
RULE_ASSESSMENT = "assessment_ratio"   # classes differ by fraction of value assessed
RULE_RATE = "tax_rate"                 # uniform assessment, classes differ by millage
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
        return min(max(raw, 1.0), CLASSIFICATION_MULT_CEIL)


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
    """
    return tuple(sorted(
        f"{usps}:{rule.multiplier():.2f}"
        for usps, rule in CLASSIFICATION_RULES.items()
        if rule.rule_type != RULE_UNIFORM and rule.multiplier() > 1.0
    ))
