#!/usr/bin/env python3
"""Per-county region context — the seam that de-Shelbyfies the location-driven
enrichment stages.

The Shelby pilot hardcoded Memphis fiscal + climate constants into the batch
enrichers. This module resolves the same values from the bundled national
crosswalks for *any* county FIPS, so the live path (``simulate/dimensions.py``)
and the batch stages (``enrich/infrastructure.py``, ``enrich/noaa_climate.py``)
share one implementation instead of each carrying its own copy.

For Shelby (or an unknown/None county) the helpers return ``None`` / the Memphis
defaults, so the pilot's behavior is unchanged; a real non-Shelby FIPS gets its
county-specific values with a national-average fallback baked into the
underlying loaders.
"""

from __future__ import annotations

SHELBY_COUNTY_FIPS = "47157"  # the single-county pilot; Memphis-calibrated defaults


def normalize_fips(value) -> str | None:
    """Best-effort 5-digit county FIPS from a messy CSV cell.

    Returns ``None`` for missing / NaN so the caller falls back to defaults;
    accepts floats that lost their leading zero or gained a ``.0`` from CSV type
    inference (``6037.0`` → ``"06037"``) and zero-pads short strings.
    """
    if value is None or value != value:              # None or NaN (NaN != NaN)
        return None
    if isinstance(value, (int, float)):              # incl. numpy float64 (a float subclass)
        return str(int(value)).zfill(5)
    s = str(value).strip()
    if not s or s.lower() == "nan":
        return None
    if s.endswith(".0"):                             # "47157.0" from float-parsed CSV
        s = s[:-2]
    return s.zfill(5)


# The two ways the revenue side can be brought to a non-school basis.
BASIS_MEASURED = "school_millage"   # owner's school rate computed and subtracted
BASIS_SHARE = "school_tax_share"    # county-wide school share netted multiplicatively


def _municipal_rate(fips: str, tax: dict, gov: dict) -> tuple[float, str]:
    """Non-school property-tax rate for a county, and which basis produced it.

    Prefers the MEASURED path: where per-county school millage is bundled, the school tax
    an owner-occupier actually pays is computed at the county median home value and
    subtracted. Both terms are then measured over owner-occupied homes.

    Falls back to the SHARE path — today's behaviour — everywhere else. That path multiplies
    an owner-occupied-derived rate by an all-property school share, which over-nets in
    states giving owners school-specific relief; see ``data/school_millage.py``. The
    fallback is byte-identical to the pre-existing computation, so counties outside the
    millage crosswalk are untouched.
    """
    from housing_label.data.propertytax import median_home_value_for_county
    from housing_label.data.school_millage import owner_school_rate

    eff = tax["effective_tax_rate"]
    # B25077 — deliberately the same median value that is the DENOMINATOR of the ACS
    # effective rate above. The subtraction is only coherent if both rates are expressed
    # against the same home.
    school_rate = owner_school_rate(fips, median_home_value_for_county(fips))
    if school_rate is not None:
        # Clamped at zero: a county whose measured school rate exceeds its ACS effective
        # rate is telling us the median home's bill cannot cover the school levy alone,
        # which is an ACS/millage vintage mismatch rather than negative municipal revenue.
        return max(0.0, eff - school_rate), BASIS_MEASURED
    return eff * (1.0 - gov["school_tax_share"]), BASIS_SHARE


def municipal_tax_rate(county_fips: str | None) -> tuple[float | None, str | None]:
    """A county's non-school property-tax rate and the basis that produced it.

    Public because the basis matters and cannot be inferred from the rate: the same
    number could come from either path. Kept OUT of ``infra_params_for_county``'s dict on
    purpose — that dict is splatted into ``enrich_row``, whose signature is an explicit
    keyword list, so a non-computational key there would be a TypeError waiting for the
    next caller.

    Returns ``(None, None)`` for Shelby and unresolvable counties, matching
    ``infra_params_for_county``'s "keep the Memphis defaults" contract.
    """
    fips = normalize_fips(county_fips)
    if not fips or fips == SHELBY_COUNTY_FIPS:
        return None, None
    from housing_label.data.govfinance import govfinance_for_county
    from housing_label.data.propertytax import property_tax_for_county

    return _municipal_rate(fips, property_tax_for_county(fips), govfinance_for_county(fips))


def infra_params_for_county(
    county_fips: str | None, *, in_urban_area: bool | None = None
) -> dict | None:
    """Build the infrastructure-enrichment params for a county, or ``None`` for
    Shelby / unknown counties (which keep the Memphis-calibrated defaults that
    ``enrich/infrastructure.py`` bakes in).

    Recalibrates the cost curves to the county's local-government spending
    (Census of Governments, cost side) and uses the county's effective
    property-tax rate (Census ACS, revenue side) — each with a national-average
    fallback in the underlying loaders. The school-district share is netted out
    of the tax rate so the revenue side is like-for-like with the non-school
    cost model. Mirrors the assembly the live path uses in
    ``simulate/dimensions.py`` so both paths score a county identically.

    ``in_urban_area`` is parcel-level, not county-level, so it is only included
    when the caller passes a concrete value (the live path does, from the resolved
    Location); left as ``None`` it is omitted so ``enrich_row`` uses its own
    distance-based fallback rather than assuming every parcel is urban.
    """
    fips = normalize_fips(county_fips)
    if not fips or fips == SHELBY_COUNTY_FIPS:
        return None
    from housing_label.data.county_lot_density import county_lot_density_for_county
    from housing_label.data.govfinance import govfinance_for_county
    from housing_label.data.propertytax import property_tax_for_county

    from housing_label.data.states import usps_for_fips

    gov = govfinance_for_county(fips)
    tax = property_tax_for_county(fips)
    municipal_rate, _basis = _municipal_rate(fips, tax, gov)
    params = {
        "assess_ratio": 1.0,
        "tax_rate": municipal_rate,
        "cost_multipliers": gov["multipliers"],
        "fee_recovery": gov["fee_recovery"],
        # Two classification keys, deliberately never one with two meanings — a caller
        # that set both would apply the correction twice, and ``enrich_row`` raises
        # rather than let that happen silently.
        #
        # The ABSOLUTE correction stays off here. It swaps in a statutory assessment
        # ratio, which only makes sense against a statutory millage; ``tax_rate`` above
        # is an ACS effective rate.
        "classification_state": None,
        # The MULTIPLICATIVE correction is on. The ACS rate is derived from
        # OWNER-OCCUPIED homes (B25103 median taxes ÷ B25077 median value), so it
        # already carries the residential class in its denominator — which is exactly
        # the denominator a class multiplier needs. The state comes from the county
        # FIPS rather than a separate parameter: ``Location.state_fips`` is itself
        # populated with a ``county_fips[:2]`` fallback, so deriving it here removes a
        # parameter, covers the batch path too, and makes a state/county mismatch
        # impossible. Unresearched states return a 1.0 multiplier, so this is a no-op
        # everywhere outside the encoded table. See ``data/assessment.py``.
        "classification_rate_state": usps_for_fips(fips),
        "classification_county_fips": fips,
        # Typical lot density, so the cost curve's density shape is expressed
        # relative to the density this county's spending multiplier was measured at
        # rather than multiplied straight into it (which charged for ruralness twice).
        "county_du_acre": county_lot_density_for_county(fips)["du_acre"],
    }
    if in_urban_area is not None:
        params["in_urban_area"] = bool(in_urban_area)
    return params


def climate_zone_for_county_fips(county_fips: str | None) -> tuple[str | None, str | None]:
    """Return ``(iecc_zone, description)`` for a county from the bundled DOE/PNNL
    IECC climate-zone crosswalk, or ``(None, None)`` when unresolved.

    This is the one climate field with a bundled national source; the degree-day
    and temperature normals the Shelby pilot hardcoded have no national bundle
    (the NOAA CDO API is the documented upgrade path), so the batch stage nulls
    those for non-Shelby counties rather than stamping Memphis values on them.
    """
    fips = normalize_fips(county_fips)
    if not fips:
        return None, None
    from housing_label.data.climate import climate_zone_for_county

    zone = climate_zone_for_county(fips)
    return zone, _IECC_ZONE_DESC.get(zone) if zone else None


# IECC climate-zone number → the moisture/thermal descriptor used on the label.
_IECC_ZONE_DESC = {
    "1A": "Very Hot-Humid", "2A": "Hot-Humid", "2B": "Hot-Dry",
    "3A": "Warm-Humid", "3B": "Warm-Dry", "3C": "Warm-Marine",
    "4A": "Mixed-Humid", "4B": "Mixed-Dry", "4C": "Mixed-Marine",
    "5A": "Cool-Humid", "5B": "Cool-Dry", "5C": "Cool-Marine",
    "6A": "Cold-Humid", "6B": "Cold-Dry",
    "7": "Very Cold", "8": "Subarctic",
}
