#!/usr/bin/env python3
"""Regenerate the residential utility-rate table in data/utility_rates.py.

Fetches two keyless, public EIA workbooks and prints the ``_STATE_RATES`` literal
(state FIPS → postal, $/kWh, $/therm) plus the US-average fallbacks, so a
maintainer can paste the refreshed table into
``src/housing_label/data/utility_rates.py`` on a new EIA release.

Sources (no API key)
--------------------
  - Electricity: EIA "Average Price of Electricity to Ultimate Customers by
    State" — Total Electric Industry, Residential, cents/kWh → $/kWh.
    https://www.eia.gov/electricity/data/state/avgprice_annual.xlsx
  - Natural gas: EIA "Price of Natural Gas Delivered to Residential Consumers"
    by state, $/thousand cubic feet → $/therm (÷ 10.37 therms/Mcf); each state's
    latest available annual value.
    https://www.eia.gov/dnav/ng/xls/NG_PRI_SUM_A_EPG0_PRS_DMCF_A.xls

Requires ``openpyxl`` and ``xlrd``. Run: ``python scripts/build_utility_rates.py``
"""

from __future__ import annotations

import io
import urllib.request

ELEC_URL = "https://www.eia.gov/electricity/data/state/avgprice_annual.xlsx"
GAS_URL = "https://www.eia.gov/dnav/ng/xls/NG_PRI_SUM_A_EPG0_PRS_DMCF_A.xls"
THERMS_PER_MCF = 10.37

# Postal → 2-digit state FIPS (50 states + DC).
FIPS = {
    "AL": "01", "AK": "02", "AZ": "04", "AR": "05", "CA": "06", "CO": "08",
    "CT": "09", "DE": "10", "DC": "11", "FL": "12", "GA": "13", "HI": "15",
    "ID": "16", "IL": "17", "IN": "18", "IA": "19", "KS": "20", "KY": "21",
    "LA": "22", "ME": "23", "MD": "24", "MA": "25", "MI": "26", "MN": "27",
    "MS": "28", "MO": "29", "MT": "30", "NE": "31", "NV": "32", "NH": "33",
    "NJ": "34", "NM": "35", "NY": "36", "NC": "37", "ND": "38", "OH": "39",
    "OK": "40", "OR": "41", "PA": "42", "RI": "44", "SC": "45", "SD": "46",
    "TN": "47", "TX": "48", "UT": "49", "VT": "50", "VA": "51", "WA": "53",
    "WV": "54", "WI": "55", "WY": "56",
}


def _fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as r:  # noqa: S310
        return r.read()


def electricity_by_state() -> tuple[dict[str, float], float]:
    """{postal: $/kWh} for the latest year + US-average $/kWh."""
    import openpyxl

    ws = openpyxl.load_workbook(io.BytesIO(_fetch(ELEC_URL)),
                                read_only=True, data_only=True)["Price"]
    rows = list(ws.iter_rows(values_only=True))
    year = max(x[0] for x in rows[2:] if isinstance(x[0], int))
    out = {}
    for x in rows[2:]:
        if x[0] == year and x[2] == "Total Electric Industry" and isinstance(x[3], (int, float)):
            out[x[1]] = round(x[3] / 100, 4)
    if "US" not in out:
        raise ValueError("EIA electricity workbook has no US total row — cannot set US-average fallback")
    return out, out.pop("US")


def gas_by_state() -> tuple[dict[str, float], float]:
    """{postal: $/therm} latest available per state + US-average $/therm."""
    import xlrd

    book = xlrd.open_workbook(file_contents=_fetch(GAS_URL))
    sh = book.sheet_by_name("Data 1")
    keys = [str(sh.cell_value(1, c)) for c in range(sh.ncols)]
    out = {}
    for c in range(1, sh.ncols):
        if not keys[c].startswith("N3010"):
            continue
        postal = keys[c][5:-1]
        for r in range(sh.nrows - 1, 2, -1):
            v = sh.cell_value(r, c)
            if isinstance(v, (int, float)) and v:
                out[postal] = round(v / THERMS_PER_MCF, 3)
                break
    if "US" not in out:
        raise ValueError("EIA gas workbook has no US column — cannot set US-average fallback")
    return out, out.pop("US")


def main() -> None:
    elec, us_elec = electricity_by_state()
    gas, us_gas = gas_by_state()
    print("US_AVG_ELEC_PER_KWH =", round(us_elec, 4))
    print("US_AVG_GAS_PER_THERM =", round(us_gas, 3))
    print("_STATE_RATES = {")
    for postal, fips in sorted(FIPS.items(), key=lambda kv: kv[1]):
        e, g = elec.get(postal), gas.get(postal)
        if e is None or g is None:
            print(f"    # MISSING {postal} ({fips}): elec={e} gas={g}")
            continue
        print(f'    "{fips}": ("{postal}", {e:.4f}, {g:.3f}),')
    print("}")


if __name__ == "__main__":
    main()
