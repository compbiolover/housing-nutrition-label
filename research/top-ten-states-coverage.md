# Assessor coverage in the ten most populous states

Measured 2026-10-03. This note records what was found for each state, so the next
person does not research it again. Each adapter's module docstring has the full
measurements: service URLs, fields, fill rates, timings, terms, and its end-to-end
verification.

"Homes" below means ACS housing units (`src/housing_label/data/year_built_county.csv`).
A county counts as covered when an adapter is registered for it. That is a claim
that an observed year built is available there, so a county is registered only
where the source fills that field for most homes.

## Where each state stands

| State | Before | After | Adapters |
|---|---:|---:|---|
| Florida | 100% | 100% | `fl` (statewide) |
| New York | 80% | 80% | `nyc`, `nys` |
| North Carolina | 64% | 64% | `nc` (46 counties) |
| Texas | 0% | 48% | `tx`: Harris, Dallas, Tarrant, Bexar, Travis, Fort Bend, Montgomery |
| Michigan | 0% | 46% | `mi`: the 7 SEMCOG counties of Southeast Michigan |
| Ohio | 0% | 42% | `oh`: Franklin, Cuyahoga, Summit, Montgomery, Delaware, Butler, Lorain, Fairfield, Licking |
| Illinois | 42% | 42% | `cook_il` |
| California | 25% | 38% | `la`, `ca` (Riverside, Contra Costa, San Joaquin), `sf` |
| Pennsylvania | 13% | 37% | `phl`, `allegheny`, `pa` (Montgomery, York, Northampton, Cumberland) |
| Georgia | 0% | 19% | `ga`: Fulton, Clayton, Chatham, Forsyth |

Across the ten states, 54% of homes are now covered. Nationally the figure is 35%.

## Held back for their terms (a product decision, not a data gap)

These sources carry the data and were measured. Each one's license restricts
reproduction or redistribution, so none is registered. If a decision allows one,
enabling it is a small change. Richmond is already configured in `ga.py`
(`_HELD_FOR_TERMS`).

| County | Homes | What the terms say |
|---|---:|---|
| Gwinnett, GA | 341k | "internal purposes by recipient only and may not be distributed or sold" |
| Cobb, GA | 314k | "Copyright Cobb County. All rights reserved."; the county sells the data |
| Richmond (Augusta), GA | 93k | "strictly forbidden to sell or reproduce these maps or data for any reason without the written consent" of the Commission |
| Berks, PA | 172k | may "NOT be copied, redistributed, resold … or provided in whole or part to any other entity" |
| Lehigh, PA | 151k | building-footprint years stop at 2015; "Not to be sold" |
| Peoria, IL | 85k | licensed to "not for profit" organizations for "internal, governmental consulting purposes only" |
| San Bernardino, CA | 744k | year built is published, but the county removed street addresses from parcel data citing AB 1785 (Gov. Code 7928.205). Confirming an address would mean re-joining it from the county's address-point layer. |
| Ventura, CA | 296k | a layer behind a county web app whose terms say the GIS exists "solely for the convenience of the County" |

These registered sources publish no license text, or only a disclaimer. Each is
public record served without a key. Confirm them before a commercial launch:
- Texas: all seven appraisal-district services.
- San Joaquin, CA.
- Clayton and Forsyth, GA.
- Summit, Butler and Lorain, OH.
- York and Northampton, PA. York's disclaimer says "illustration and demonstration purposes only".

## No usable year built in public data

- **California.** San Diego publishes only a two-digit "effective" year, and its own metadata says not to use it for age. Orange's year built is a snapshot frozen around 1997. Santa Clara, Alameda, Sacramento, Fresno, Kern and San Mateo publish nothing public.
- **Texas.** StratMap, the statewide TxGIO parcel layer, has year built for about 92 more counties, about 28% more of Texas's homes. Its `query` operation is disabled, though. The one operation that works, `identify`, returns owner names and mailing addresses, which this project does not fetch. If TxGIO re-enabled `query`, a statewide adapter would be possible. Separately, El Paso, Williamson, Galveston, Bell, McLennan, Hays, Smith, Webb and Ellis were not looked for at their own appraisal districts.
- **Illinois outside Cook.** DuPage, Lake, Will, Kane, Winnebago, McHenry, St. Clair, Sangamon and Champaign publish none. Township assessors hold those records, and none has a keyless API. Madison's server could not be reached through the proxy because of a TLS error.
- **Pennsylvania.** Bucks, Delaware, Chester, Lancaster, Westmoreland, Luzerne, Dauphin and Erie publish none. PASDA has no statewide layer with year built.
- **Ohio.** Hamilton's regional GIS (CAGIS) has none; its footprint layer's year column is entirely empty. Lucas publishes the year only in an Access download. Stark has none. Mahoning's covers commercial buildings only. Warren's old auditor host now redirects to an unrelated site and must not be used. Lake was unreachable all day; re-check it.
- **Georgia.** DeKalb's year-built columns are empty in every row. Cherokee, Hall, Muscogee, Macon-Bibb, Paulding, Columbia and Clarke have none. No public parcel service was found for Henry, Douglas or Houston.
- **Michigan outside SEMCOG.** Kent, Genesee, Ingham, Ottawa, Kalamazoo and Saginaw have no county-wide source. Flint, Grand Rapids and Kalamazoo publish city-only data, which is too partial to register for a whole county.

## Follow-ups worth doing

- Ask TxGIO to re-enable `query` on StratMap. It is the largest single gain left in these ten states.
- Move house-number range matching ("1622-1624 FORBES AVE") into `_shared`. Philadelphia and Allegheny each have a copy, and SEMCOG's range addresses never confirm without it.
- Move unit-designator comparison into `_shared`. `dc`, `phl`, `allegheny` and `pa` each have their own copy.
- Atlanta's "2304 BOULEVARD GRANADA SW" does not match the matcher's "BLVD GRANADA SW". The leading-type rule does not apply when a quadrant follows the name.
