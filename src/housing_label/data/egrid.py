"""Grid CO2 emission factor by location.

v1 (national generalization, Phase 1): returns the EPA eGRID US-average output
emission rate as a keyless, offline default for every county. This makes the
environmental operational-carbon leg location-agnostic but reasonable anywhere.

Phase 2 upgrade path: bundle a county→eGRID-subregion crosswalk + the 27
subregion factors (EPA eGRID2023) for true regional precision; the function
signature already returns (subregion, factor) so callers won't change.
"""

from __future__ import annotations

# EPA eGRID2023 US-average total output CO2-equivalent emission rate.
# (~0.385 kg CO2e/kWh; refresh on each eGRID release.)
US_AVG_FACTOR_KG_PER_KWH = 0.385
US_AVG_LABEL = "US average (eGRID2023)"


def egrid_for_county(county_fips: str | None) -> tuple[str | None, float | None]:
    """Return (egrid_subregion, kgCO2e/kWh) for a county FIPS.

    v1 always returns the US-average factor (subregion label flags it as such).
    """
    return (US_AVG_LABEL, US_AVG_FACTOR_KG_PER_KWH)
