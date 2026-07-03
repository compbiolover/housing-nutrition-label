"""Residential utility rates by state (EIA, keyless + offline).

Returns average residential electricity ($/kWh) and natural-gas ($/therm) prices
for a property's state, so the energy dimension's cost estimate reflects local
rates instead of a single Memphis (MLGW/TVA) pilot constant. A state that can't
be resolved (or a missing FIPS) falls back to the US-average pair.

Data
----
  • Electricity — EIA "Average Price of Electricity to Ultimate Customers by
    State" (Total Electric Industry, Residential), cents/kWh → $/kWh.
    https://www.eia.gov/electricity/data/state/  (avgprice_annual.xlsx, 2020)
  • Natural gas — EIA "Price of Natural Gas Delivered to Residential Consumers"
    by state, $/thousand cubic feet → $/therm (÷ 10.37 therms/Mcf), each state's
    latest available annual value (2024–2025).
    https://www.eia.gov/dnav/ng/ng_pri_sum_a_epg0_prs_dmcf_a.htm

These are dated public averages; refresh with scripts/build_utility_rates.py on
new EIA releases. The function signature is stable, so callers never change.
"""

from __future__ import annotations

# 2-digit state FIPS → (postal code, residential $/kWh, residential $/therm).
# Electricity: EIA 2020 residential average. Gas: EIA latest annual (2024–25).
_STATE_RATES: dict[str, tuple[str, float, float]] = {
    "01": ("AL", 0.1258, 1.693),
    "02": ("AK", 0.2257, 1.250),
    "04": ("AZ", 0.1227, 1.792),
    "05": ("AR", 0.1041, 1.856),
    "06": ("CA", 0.2045, 2.122),
    "08": ("CO", 0.1236, 1.077),
    "09": ("CT", 0.2271, 1.623),
    "10": ("DE", 0.1256, 1.540),
    "11": ("DC", 0.1263, 1.608),
    "12": ("FL", 0.1127, 2.457),
    "13": ("GA", 0.1202, 1.969),
    "15": ("HI", 0.3028, 5.051),
    "16": ("ID", 0.0995, 0.742),
    "17": ("IL", 0.1304, 1.085),
    "18": ("IN", 0.1283, 1.108),
    "19": ("IA", 0.1246, 1.023),
    "20": ("KS", 0.1285, 1.428),
    "21": ("KY", 0.1087, 1.372),
    "22": ("LA", 0.0967, 1.676),
    "23": ("ME", 0.1681, 1.827),
    "24": ("MD", 0.1301, 1.556),
    "25": ("MA", 0.2197, 2.417),
    "26": ("MI", 0.1626, 1.053),
    "27": ("MN", 0.1317, 1.059),
    "28": ("MS", 0.1117, 1.605),
    "29": ("MO", 0.1122, 1.441),
    "30": ("MT", 0.1124, 0.867),
    "31": ("NE", 0.1080, 1.099),
    "32": ("NV", 0.1134, 1.267),
    "33": ("NH", 0.1904, 1.795),
    "34": ("NJ", 0.1603, 1.370),
    "35": ("NM", 0.1294, 0.948),
    "36": ("NY", 0.1836, 1.695),
    "37": ("NC", 0.1138, 1.583),
    "38": ("ND", 0.1044, 0.916),
    "39": ("OH", 0.1229, 1.336),
    "40": ("OK", 0.1012, 1.349),
    "41": ("OR", 0.1117, 1.611),
    "42": ("PA", 0.1358, 1.450),
    "44": ("RI", 0.2201, 2.089),
    "45": ("SC", 0.1278, 1.631),
    "46": ("SD", 0.1175, 0.951),
    "47": ("TN", 0.1076, 1.142),
    "48": ("TX", 0.1171, 1.873),
    "49": ("UT", 0.1044, 0.983),
    "50": ("VT", 0.1954, 1.736),
    "51": ("VA", 0.1203, 1.619),
    "53": ("WA", 0.0987, 1.699),
    "54": ("WV", 0.1180, 1.331),
    "55": ("WI", 0.1432, 1.036),
    "56": ("WY", 0.1111, 1.132),
}

# EIA US-average residential rates — the fallback when a state can't be resolved.
US_AVG_ELEC_PER_KWH = 0.1315   # $/kWh  (EIA 2020 US residential average)
US_AVG_GAS_PER_THERM = 1.479   # $/therm (EIA latest US residential average)
US_AVG_LABEL = "US average (EIA)"


def utility_rates_for_state(state_fips: str | None) -> dict:
    """Return residential utility rates for a 2-digit state FIPS.

    Looks the state up in the bundled EIA table and returns
    ``{"elec_per_kwh", "gas_per_therm", "label"}``. An unresolved or missing
    FIPS falls back to the US-average pair (label flags it), so a concrete dict
    is always returned, never None.
    """
    if state_fips:
        row = _STATE_RATES.get(str(state_fips).strip().zfill(2))
        if row is not None:
            postal, elec, gas = row
            return {"elec_per_kwh": elec, "gas_per_therm": gas,
                    "label": f"{postal} residential (EIA)"}
    return {"elec_per_kwh": US_AVG_ELEC_PER_KWH,
            "gas_per_therm": US_AVG_GAS_PER_THERM,
            "label": US_AVG_LABEL}
