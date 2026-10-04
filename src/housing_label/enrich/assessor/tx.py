#!/usr/bin/env python3
"""Texas — twelve large counties, each from its own appraisal district's roll.

Texas has no county assessor. Each county has an appraisal district (a CAD), and
each CAD keeps and publishes its own roll; there is no state-collected roll of
the kind Florida's Department of Revenue publishes. So this adapter is a table of
services (``COUNTIES``), one per county, routed by the county FIPS the registry
already resolved. It answers for Harris, Dallas, Tarrant, Bexar, Travis, Fort
Bend and Montgomery (the first seven: 5.84 million housing units), and Collin,
Denton, El Paso, Williamson and Cameron (added second: 1.56 million) — 7.40
million of the state's 12.13 million housing units (61%, ACS). Of the large
counties researched for the second round, Hidalgo, Galveston, Bell, Hays,
Brazoria, Nueces and Lubbock are not here; "Counties researched and not added"
says why, county by county.

Why not the statewide layer
---------------------------
TxGIO's StratMap Land Parcels layer
(``feature.geographic.texas.gov/.../stratmap_land_parcels_48_most_recent``) holds
every county's parcels, CC0-licensed, and it is NOT used, for a reason this
codebase treats as absolute. Its ``query`` operation is switched off — every form
tried (point, ``where``, ``objectIds``, statistics, POST, GeoJSON) answers
"Requested operation is not supported", although the layer advertises Query —
and the only operation that works, ``identify``, returns every column on every
row, including ``owner_name``, ``name_care`` and the whole mailing address, with
no field list and no way to leave them out (a ``dynamicLayers`` field list is
silently ignored). This package never fetches owner names, so it cannot use a
source that sends them unasked. If TxGIO re-enables ``query`` with an explicit
``outFields``, StratMap would add about 89 further counties with a usable year
built (measured: 94 counties at 40% or better fill, five of them — Harris,
Tarrant, Collin, Denton and Cameron — already here) — a second adapter, not a
change to this one.

The services
------------
All keyless; all but Williamson are ArcGIS REST with ``query`` enabled and an
explicit ``outFields`` honored. The first seven were read 2026-10-03, the second
five 2026-10-04. "Year built" is the share of ALL rows (vacant lots included)
carrying a plausible year; the share of homes is the next table's.

  ==========  ===============================================  =======  ==========  ==================
  county      service                                          rows     year built  roll
  ==========  ===============================================  =======  ==========  ==================
  Harris      City of Houston, Parcels_Current layer 4         1.52 M   85.8%       HCAD 2025
  Fort Bend   FBCAD, Hosted/FBCADPublicData                    386 k    76.4%       current (to 2026)
  Montgomery  City of Houston, Parcels_Current layer 3         330 k    68.8%       MCAD 2026
  Dallas      DCAD, Property/ParcelQuery layer 4               845 k    76.7%       2026 (live)
  Tarrant     TAD, OD_TAD/OD_ParcelView                        759 k    84.7%       TAD 2025
  Bexar       Bexar County, Parcels layer 0                    711 k    86.6%       BCAD, about 2025
  Travis      Travis County TNR, Parcels layer 0               374 k    85.0%       TCAD, about 2023
  Collin      City of Allen, CCAD Tax Parcels (FeatureServer)  452 k    83.9%       CCAD 2027 (open)
  Denton      Denton County, Parcels_FC layer 0                384 k    83.7%       Denton CAD 2027
  El Paso     City of El Paso, Parcels_Uncached layer 0        407 k    62.9%       EPCAD 2026
  Williamson  WCAD open data (Socrata), parcels + improvements 291 k    79.0%       WCAD 2026
  Cameron     City of Brownsville, CameronCAD_Parcels_05312026 188 k    67.4%       Cameron CAD 2026
  ==========  ===============================================  =======  ==========  ==================

The second five, on homes (the residential category, which is where a reader's
address lands):

  ==========  =====================================  ===================  =================
  county      residential rows with a year           area                 stories
  ==========  =====================================  ===================  =================
  Collin      A1 339,559 of 341,155 (99.5%)          A1, A2, A4           yes
  Denton      A1 281,510 of 282,693 (99.6%)          A1, A2               no
  El Paso     A1 227,420 of 230,136 (98.8%)          none published       none published
  Williamson  A1 213,130 of 213,196 improvements     one-improvement A1   no
  Cameron     A 109,469 of 115,985 (94.4%)           withheld (bare "A")  none published
  ==========  =====================================  ===================  =================

El Paso's and Cameron's lower all-rows share is vacant land: El Paso files 97,340
colonia and vacant lots as C2 and Cameron 30,687 as C1, none with a building.

Each county's vintage is stated as honestly as its layer allows, on every record:

* **Harris** is the City of Houston's republication of the HCAD roll, and it lags
  the CAD: every row says ``Tax_Year`` 2025, the layer's own text says it was
  last updated 2024-09-19 (the service was republished 2025-04-16). HCAD's own
  GIS (``gis.hctx.net``, HCAD/Parcels) carries no year built at all, so the city's
  copy is the only keyless source of it.
* **Fort Bend** was researched as the city's copy too (layer 5), and that copy is
  a year staler: no tax-year column, newest year built 2024, last updated
  2024-09-17. FBCAD publishes its own layer, which carries years to 2026,
  295,008 recorded years against the copy's 284,771, the improvement's own state
  code, and the unit in its own column, so this adapter reads FBCAD directly.
  Both were measured end to end on the same 40 homes: 33 of 39 geocoded resolved
  through each, with no wrong parcel through either; the CAD's own layer is
  kept for being current and for being the CAD's.
* **Montgomery** is the city's copy of the MCAD roll and is current: ``TAX_YEAR``
  2026 on 329,043 of 329,989 rows, years built to 2026. MCAD's own GIS host
  serves a web application, not a REST directory.
* **Dallas** is DCAD's live service (``LASTUPDATE`` 2026-10-02 on the newest
  row). Its ``REVALYR`` is the year the row was last revalued (2024–2026 by row),
  not a roll year, and the record says exactly that.
* **Tarrant**: TAD has two layers. The hosted ``Hosted/TADMap`` is a year fresher
  (tax year 2026) and is NOT used: it idles out. Probed after 0, 5, 10, 20, 40 and
  60 s without traffic, it answered in 0.44–0.48 s up to 20 s and in 5.13 and
  5.22 s at 40 and 60 s; probed every five minutes, 3 of 4 requests took
  5.11–5.14 s; and in the first verification run the first four Tarrant lookups
  failed open on exactly that. A label service that
  sees a Tarrant address every few minutes would pay five seconds or lose the
  answer nearly every time. ``OD_ParcelView`` on the same host, the 2025 roll
  (its ``Appraisal_`` column), answered the same idle pattern in 0.42–0.53 s.
* **Bexar** publishes no tax year, and its metadata is stale text ("Last update:
  October 2021 ... Next update: September/October 2023"). The data is newer:
  12,813 parcels carry a 2024 year built and one carries 2025, so it is about the
  2025 roll. The record says "newest year built in the layer 2024, as measured".
  BCAD's own map service (``maps.bcad.org``) carries no year built.
* **Travis** publishes no tax year, and it is the stalest: the newest year built
  in the layer is 2023, on 123 parcels, against 6,549 in 2022 — the 2023 roll,
  three years old. A house built since is a vacant lot in it (class C1, which
  answers nothing), and a house rebuilt since still carries the old house's year:
  the one way this county can be wrong that no parcel check can catch. The record
  carries the measured newest year, so a reader can date it.
* **Collin** is the City of Allen's copy of the CCAD roll, refreshed by a script
  every Friday, and it is current: 8,873 houses built in 2026, every row in
  appraisal year 2027 with status "InProgress" — CCAD has opened next year's
  roll, and the record says exactly that ("CCAD 2027 appraisal year (in
  progress)"). CCAD's own nightly layer (``CCAD_Parcel_Feature_Set``, layer 4)
  was measured too and set aside: its category column is a bare "A" on all
  363,886 residential rows, which cannot tell a house from a condominium unit, so
  it could give the year alone. On 299 random A1 houses the two agree on the
  year 296 times and on the area 296 times; the three differences are years the
  copy has and CCAD's layer lacks.
* **Denton** is the county GIS's copy of the Denton CAD roll (its item calls it
  "DCAD's Update Parcel data" — Denton's DCAD, not Dallas's), current to 2,849
  houses built in 2026, with ``pYear`` 2027 on every row: like Collin's, the CAD
  has opened next year's roll. No status column is published, so the record says
  "records for appraisal year 2027".
* **El Paso** is the City of El Paso's copy of the EPCAD roll, ``PROP_VAL_Y`` 2026
  on 401,372 of 407,054 rows, 3,428 houses built in 2025. The layer is named
  "testing.DBO.Parcels", in a folder of cached services; it is nonetheless the
  city's only parcel layer with a year (every other folder was scanned), and it
  covers the whole county, Canutillo, Socorro and Clint included. The city's
  firewall answers 403 to the ``requests`` library's own User-Agent; the shared
  helper's header passes.
* **Williamson** is WCAD's own open-data portal: the parcels dataset (refreshed
  2026-10-03) for the polygon and address, joined to the "Property
  Characteristics" export of 2026-07-27, the certified 2026 roll (newest year
  built 2025, on 6,293 improvements). WCAD's ArcGIS layer (``WCAD_Tax_Parcels``)
  publishes a ``RESYRBLT`` column that is empty on all 291,077 rows, and every
  city copy of it found (Leander, Cedar Park, Georgetown, Hutto) is as empty.
* **Cameron** is the Cameron CAD's yearly export (2026-05-31, roll year 2026 on
  185,936 of 187,770 rows), hosted by the City of Brownsville. A static yearly
  copy: it will not see a house finished after May 2026 until the next export,
  and the record names the export date. The CAD's own server
  (``gissvr.cameroncad.org``) publishes polygons with no attributes.

Counties researched and not added
---------------------------------
Searched 2026-10-04 (CAD and county GIS hosts, city copies, ArcGIS Online, the
vendors' hosted services); none has a live, keyless, point-queryable layer with a
per-parcel year built, so none is registered:

* **Hidalgo** (308,556 units). The CAD's map service
  (``propaccess.hidalgoad.org/.../HidalgoMapSearch``) cannot be reached (its host
  does not resolve from here); its hosted ``HidalgoCADWebService`` needs a token;
  the 911 district's copy (``gis.rgv911.org``, 334,098 parcels) has the year and
  state-code columns empty on every row; Edinburg's copy covers 61,036 parcels
  of its own city.
* **Galveston**, **Hays**, **Brazoria**, **Nueces**: every parcel layer found
  (the CADs' vendor-hosted web services, the counties' and cities' copies)
  carries owner, value and legal columns but no year; San Marcos's copy has one
  for its own 29,408 parcels.
* **Bell**: the CAD's market-analysis service publishes a neighborhood's
  *median* year built on every parcel — a fact about the neighbors, not the house.
* **Lubbock**: the CAD's own ``LubbockCADWebService`` (layer 129, 137,468
  parcels) has a year on 107,773 rows, but no state code, only an improvement
  class ("RV5", "WH1", "OFC2A") whose vocabulary is not published, so whether a
  year belongs to a home cannot be read; its ``Class`` layer has the state code
  but stops at houses built in 2023.

Travis's year column, and what it means
---------------------------------------
``F1year_imprv`` is labeled "First year 1st Floor Improvement". TCAD records a
house as improvement segments, each with its own year — the first-floor main area
("1ST"), a second floor, an addition — and this column is the first-floor main
area's year: the year the original house went up, not the year of a later
addition, which is a different segment. Checked against Austin landmarks with
documented dates: the Neill-Cochran House (2310 San Gabriel St, built 1855) and
Westhill (1703 West Ave, 1855) read 1855; the Walter and John Bremond houses of
the Bremond Block (700 Guadalupe St and 402 W 7th St, 1886–87) read 1900, the
round year CADs write for an undocumented nineteenth-century house — and earlier
than any addition to them. None read a year after 1900. Both
1855 houses are filed F5 (commercial residence conversion: museums and offices),
so the adapter itself reports neither; they are evidence about the column.

What a row says about homes
---------------------------
Every CAD files each account under the Comptroller's state property category
(Texas Property Tax Assistance Property Classification Guide, publication
96-313): A single-family residential — houses, townhouses AND condominiums ("Do
not classify condominiums or townhomes as Category B ... They are Category A") —,
B multifamily, C vacant, D open-space land, E rural land and its improvements,
F commercial and industrial, J utilities, L business personal property, M mobile
homes, O residential inventory, S special inventory, X exempt. The CADs add
suffixes and local codes, so each county's reader maps its own column onto five
readings (``ONE_HOME``, ``CONDO``, ``MULTI``, ``SILENT``, ``NOT_A_HOME``):

* **Floor area and stories need an explicit single-family code** (A1, or a
  mobile home on its own land), because A also holds condominiums — plus the
  county's own one-building evidence where it has one: Harris's ``BUILDCOUNT`` of
  1 and a single residential building type, Bexar's one ``Houses`` and a main
  building area equal to the parcel's total. Nothing is ever divided.
* **Condominium units** — Harris's own Z1–Z5 (63,491 rows, all but 6 typed
  "Residential Condo"), DCAD's "SFR - CONDOMINIUMS", the other A sub-codes — report the year
  and nothing else. A unit's floor area is not what the label means by the home.
* **No year from a record that says no one lives there**: vacant land, open-space
  land, commercial and industrial (including Travis's F5 conversions), utilities,
  minerals, inventory; and Bexar's explicit zero ``Houses`` on any record that
  is not multifamily (an apartment complex writes 0 houses). An exempt class,
  E, O and a blank are silence, not refusal: X is an exemption, not a use.
* **Business personal property is not a parcel.** DCAD files 80,394 "COMMERCIAL
  BPP" accounts on the polygon, and under the address, of the parcel they sit in,
  and TAD does the same with L1; offered as candidates, one would make the house
  beneath it ambiguous. They are dropped as non-records.
* DCAD's ``CLASSCD`` is DCAD's own numbering, read off its 32 values; TAD's
  ``Property_C`` and the rest are the Comptroller's. Montgomery appends an
  exemption flag ("A1XV", 331 houses) that is stripped before reading.
* **CCAD's M4 and M5 are common areas, not mobile homes.** 9,996 Collin accounts,
  legal descriptions "LOT COMMON AREA", "(OPEN SPACE)", "SECURITY OFFICE", 211
  of them with a year: a clubhouse's. Collin reads them as no home; its M3,
  which carries HUD numbers, stays a mobile home. CCAD's certified totals give
  A1 single family, A2 mobile home on own land, A3 condominiums, A4 townhomes;
  a townhome is one home, as DCAD's is.
* **A list of codes is never one home.** Denton writes every code an account
  carries ("A1,D1,E1": a house on open-space land with a rural improvement), and
  Williamson has a code per improvement. Several codes describe several parts of
  the account, so the area is withheld; the year stands unless every code
  refuses (``_codes_reading``). Denton's own A3 to A6 and Williamson's A3 to A9
  are published without definitions — read off the rows, they hold houses on
  larger lots, condominiums, fourplexes and townhomes — and report the year
  alone.
* **El Paso and Cameron report the year alone.** El Paso publishes no floor area
  or stories; Cameron publishes a living area, but its residential code is a
  bare "A" (115,985 rows; A1 appears on 2), which does not say the account is
  one house rather than a condominium unit. Their codes still decide whether a
  year is a home's: El Paso's "XV-R", an exempt residence, is silence; its C2
  colonia lots and Cameron's C1 refuse.

Stacks, and the address two accounts share
------------------------------------------
``select_parcel`` refuses more than one candidate under the point, and Texas
produces that two ways that are not ambiguity about which building:

* **Condominium stacks.** 2200 Willowick Rd, Houston is 115 unit rows on one
  footprint; Dallas files a complex's units on the complex's polygon. Rows at one
  street address (unit set aside) are offered as ONE candidate when every row
  agrees on the year built and every row is a home; that candidate carries the
  year alone, and no parcel id unless all rows share one. Rows that disagree (6108
  Abrams Rd, Dallas: units recorded as 1984, 2005, 2019 and 2021) are offered
  as they are and refused. A reader who typed a unit gets that unit's row (Harris
  writes it bare, "829 YALE ST 504"), with the year and still no floor area.
* **One address, two accounts.** Typed "16417 Hubenak Rd, Needville" landed in an
  86-acre farm whose 1930 farmhouse has that address; so does the 1-acre homesite
  cut out of it, a 1984 house more than 80 m away, which was the home sampled.
  Containment confirmed by address chose the farmhouse — the one wrong parcel the
  first verification run found. So every confirmed answer is checked against a
  second search: the rows within ``TWIN_RADIUS_M`` (1 km) whose address carries
  the same house number, an attribute filter that keeps the answer to a handful
  of rows. The address must name exactly one candidate there, or the lookup is
  refused (or answered with the year alone, where the twins agree on it: 721 La
  Mesa Ave, Canutillo is two El Paso accounts, both A1, both 1982).

Williamson: two datasets, one answer
------------------------------------
WCAD's year lives only in its Socrata portal, in a table of improvements keyed
by property id, so Williamson is the one county read in two hops
(``_williamson_rows``): the parcels the point (or the circle) intersects, then
every improvement row of those properties in one ``propertyid in (...)``
request. The parcel query is shaped to ask what the ArcGIS queries ask —
``intersects`` with the point, with a 32-sided polygon inscribed in the 80 m
circle (Socrata's own ``within_circle`` answers a different question; see
``_circle_wkt``), and, for the same-number search, the 1 km polygon plus
``starts_with(siteaddress, '<number> ')`` — and a page that reaches its row
limit is refused as ArcGIS's ``exceededTransferLimit`` is. An account's
improvements must agree on the year; floor area comes only from an account with
one improvement row, coded A1 or A2. A parcel with no improvement row (vacant
land, commercial accounts: the table is residential) says nothing.

Addresses
---------
Every service but El Paso's and Cameron's keeps the street address in one
column. Harris, Dallas, Tarrant, Bexar and Denton write the street alone; Fort
Bend, Montgomery and Williamson append the city after a comma, which the shared
comparison already sets aside, and Collin's runs on to the city after a line
break, cut there (``_first_line``). El Paso and Cameron split the address into
number, street and type, and the reader joins them (El Paso's type column is
named ``SITUS_DIR``); their same-number search asks the number column itself
(``_County.number_field``). Bexar often omits the street type ("509 KING
WILLIAM"), which the shared comparison tolerates. Three spellings are genuinely
local and handled here, each with a test: TAD writes Trail as "TR" (and Terrace
as "TERR", so in this roll TR is only Trail; ``_tarrant_address``); Travis writes
"W 1316 6 ST   TX 78701" — the directional before the number, the city optional
— which ``_travis_address`` rebuilds as "1316 W 6 ST"; and WCAD writes a
directional after the street type ("726 5TH ST W"), where the Census matcher
puts it first, which ``_williamson_address`` moves. A Travis city it does not
know stays in the string, and the address then matches nothing: a refusal,
never a wrong match.

Not carried
-----------
No requested column holds an exterior wall, a foundation or a condition grade the
label can read, so those stay empty. Effective years and remodel years
(``yr_remodel`` in Harris) are not requested.

Timing
------
Measured through the product's own HTTP session over the verification run below
(307 geocoded homes, all seven services):

  ==========================================  ======  ======  ======  ======
  request                                     median     p90     p95     max
  ==========================================  ======  ======  ======  ======
  "which parcel is this dot inside?"           0.09 s  0.12 s  0.16 s  1.24 s
  "what is within 80 m of this dot?"           0.10 s  0.15 s  0.16 s  0.42 s
  "who else has this house number nearby?"     0.11 s  0.15 s  0.16 s  0.43 s
  whole lookup (up to three requests)          0.29 s  0.42 s  0.48 s  1.44 s
  ==========================================  ======  ======  ======  ======

DCAD is the slowest host (buffer median 0.15 s). Every maximum above 0.6 s is a
host's first request of the run, which opened the connection: a fresh TLS
connection took 0.39–0.81 s across the seven hosts in probes five minutes apart,
and the connect half of the timeout has the whole budget anyway. So Texas keeps
the SHARED clock — a one-second read slice that no read among the 869 requests
came near, and a four-second budget against a worst lookup of 1.44 s (the run's
very first, connection included). ``READ_SLICE_S`` and
``LOOKUP_TIMEOUT`` are named so every request visibly passes them, and a test
pins their sum under ``config.UPSTREAM_HOST_BUDGET``.

The second five, measured the same way over their own verification run (216
geocoded homes; the first of two runs, whose maxima include each host's
connection):

  ==========================================  ======  ======  ======  ======
  request                                     median     p90     p95     max
  ==========================================  ======  ======  ======  ======
  "which parcel is this dot inside?"           0.11 s  0.17 s  0.31 s  0.81 s
  "what is within 80 m of this dot?"           0.11 s  0.16 s  0.19 s  0.36 s
  "who else has this house number nearby?"     0.14 s  0.19 s  0.22 s  0.56 s
  Williamson's improvements (second hop)       0.13 s  0.30 s  0.32 s  0.38 s
  whole lookup (up to six requests)            0.36 s  0.71 s  0.93 s  1.85 s
  ==========================================  ======  ======  ======  ======

Williamson is the slowest county by construction — up to six requests, each of
the three searches followed by its improvements — and the run's worst lookup took
1.85 s (1.00 s in the second run), inside the four-second budget with room to
spare. data.wcad.org was the slowest host of the first run (containment p90 0.32 s;
0.14 s in the second); the City of Allen's and Brownsville's are
the quickest (containment medians 0.085 and 0.088 s). Probed with a fresh
connection after five idle minutes, the five hosts answered in 0.43–0.83 s each
time — TLS included, and no idle-out of the kind that disqualified TAD's hosted
layer. So the second five keep the shared clock too.

What the adapter is worth, end to end
-------------------------------------
315 homes drawn at random from the services themselves (random object ids across
each layer; residential class, a single recorded year, a house number), weighted
toward the big counties, geocoded through the Census matcher and
``assessor_address`` exactly as the product does, then looked up with the
geocoder's county:

  ==========  ======  ========  ========  ==========  =========  ==========
  county      drawn   geocoded  resolved  wrong       year       floor area
                                          parcel      exact      exact
  ==========  ======  ========  ========  ==========  =========  ==========
  Harris          60        58        53           0      53/53       51/51
  Dallas          45        44        39           0      39/39       37/37
  Tarrant         45        44        38           0      38/38       38/38
  Bexar           45        45        42           0      42/42       38/38
  Travis          40        39        34           0      34/34         —
  Fort Bend       40        39        33           0      33/33       31/31
  Montgomery      40        38        29           0      29/29       29/29
  **all**      **315**   **307**   **268**      **0**  **268/268**  **224/224**
  ==========  ======  ========  ========  ==========  =========  ==========

Every geocode was routed to its own county. 268 of 307 geocoded homes resolved
(87%); 71 also got a story count (Dallas and Bexar). Montgomery is the weakest
(29 of 38) because its rural addresses geocode farthest from their parcels; it
is kept, since the misses are refusals, not wrong answers. One answer (Travis,
3900 Threadgill St) came from two agreeing accounts at one address, reported as
the year alone.

The 39 that did not resolve: 34 geocodes more than 80 m from their parcel or
spelled differently from the roll (the Census matcher's "CHESTALYNN CT" for TAD's
"CHESTALYN CT", "ROUND OAK LN" for MCAD's "ROUND OAKS LN", "APRIL WATERS W" with
the roll's "DR" dropped); 3 addresses two accounts share within 80 m (1310 Winston
Dr, Richmond: a 1953 house and a second account built 1990); 1 Dallas condominium
complex (4279 Madera Rd, Irving) whose 301 unit rows, each with its own street
address, sit on one polygon, refused as ambiguous under the point; and the
Hubenak farm, refused by the same-address search. 8 addresses the Census
matcher did not find.

The second five were verified the same way on 2026-10-04 (random object ids;
for Williamson, random rows of the improvements table, then that property's
parcel):

  ==========  ======  ========  ========  ==========  =========  ==========
  county      drawn   geocoded  resolved  wrong       year       floor area
                                          parcel      exact      exact
  ==========  ======  ========  ========  ==========  =========  ==========
  Collin          50        49        43           0      43/43       43/43
  Denton          45        44        40           0      40/40       39/39
  El Paso         45        43        36           0      36/36         —
  Williamson      45        42        37           0      37/37       33/33
  Cameron         40        38        33           0      33/33         —
  **all**      **225**   **216**   **189**      **0**  **189/189**  **115/115**
  ==========  ======  ========  ========  ==========  =========  ==========

189 of 216 geocoded homes resolved (88%); every Collin answer also carried its
story count. Every geocode was routed to a county this adapter serves, one of
them to the wrong one: 7519 Alderwood Dr, Garland is on CCAD's roll, and the
Census matcher put it in Dallas County, where DCAD has no such parcel — a
refusal. The 27 that did not resolve: 25 geocodes more than 80 m from their
parcel or spelled differently from the roll (the matcher's "GEN MALONEY CIR" for
EPCAD's "GENERAL MALONEY CIR", "CAROL JESCHKE" for "CAROLE JESCHKE", "304 W EL
PASEO ST" for Denton's "304 EL PASEO ST", "412 W FLEETWOOD AVE" for Cameron's
"412 FLEETWOOD"); 1 new El Paso house (1217 Indigo Sky St, built 2025) whose
point lands on two unaddressed accounts, refused as ambiguous; and 1 Cameron
address (5 Iturbide St) with two accounts, of which the point lands in the one
with no home code and no year — nothing reported. 9 addresses the Census
matcher did not find.

Privacy, and why the field lists are short
------------------------------------------
Every one of these layers carries owner names, and most carry mailing addresses,
deed references and values: ``OWNER``/``OWNER_ADD`` (Houston), ``ownername``/
``oaddr1`` (FBCAD), ``OWNERNME1``/``PSTLADDRESS`` (DCAD), ``Owner_Name``
(TAD), ``Owner``/``AddrLn1`` (Bexar), ``py_owner_name`` and ``deed_date``
(Travis), ``file_as_name``/``addr_line1`` and certified values (Collin's copy),
``name``/``addrDeliveryLine`` and owner values (Denton), ``FILE_AS_NA``/
``ADDR_LINE2`` (El Paso), ``adtnName`` and values (Cameron), ``ownernme1``/
``pstladdres`` on WCAD's parcels and ``totalmktcur``/``deeddate`` on its
characteristics. None is an input to the label, and Tax Code §25.025 makes the
pairing of certain people's names with their home addresses confidential in
these very records — one more reason a field list never asks for a name. Four
to nine columns are requested by name per county (Williamson: four from the
parcels, five from the improvements, by ``$select``); the shared helper refuses
``*``. Nothing from these services is written into the repository.

License and public status
-------------------------
No license text was found for any of the seven services: ``licenseInfo`` is
empty on the Houston, DCAD, Bexar and Travis services; TAD's item carries only a
disclaimer ("for informational purposes only and may not have been prepared for
or be suitable for legal, engineering, or surveying purposes"); DCAD's GIS page
(https://www.dallascad.org/GISDataProducts.aspx) carries the same disclaimer and
offers the same data as free downloads; Travis County's site disclaimer
(https://www.traviscountytx.gov/disclaimer) provides its information "as is";
Bexar's service credits BCAD and states no terms; FBCAD's states none. For the
second five: CCAD's open-data page (https://collincad.org/open-data-portal/)
says "The information provided herein is considered public domain and is
distributed 'as is' without warranty of any kind", and CCAD's own parcel item is
licensed "For public use" with an informational-only disclaimer; the City of
Allen's copy credits CCAD and states no terms. EPCAD's property search describes
its information as "considered in the public domain and distributed without
warranty of any kind" (https://epcad.org/Search, as indexed; the page answers
403 to scripts); the City of El Paso's service states no terms. WCAD's site
provides its information "As Is" without warranty (https://www.wcad.org), and
its portal's datasets carry no license field. The Denton County and City of
Brownsville services state no terms at all. Nothing read restricts querying,
caching or commercial use. Appraisal records are public
information in Texas: information an appraisal district collects or maintains in
its official business is "public information" (Government Code §552.002(a)),
available to the public (§552.021), with the exceptions that touch these rolls —
rendition and other private data (Tax Code §22.27) and the name-to-home-address
confidentiality of §25.025 — falling on columns this adapter does not request.
Public status is not an open license, and a CAD can assert rights in its
compilation, so the posture is the one every adapter takes: query live, cache
in process, bundle nothing; a legal read before a commercial launch is prudent.
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Callable

from housing_label.enrich.assessor import _shared
from housing_label.enrich.assessor._shared import (
    SUFFIXES, address_key, cache_bucket, deadline_from, num, select_parcel, unit_of,
)
from housing_label.enrich.assessor.base import AssessorRecord
from housing_label.enrich.durability import EARLIEST_PLAUSIBLE_YEAR

log = logging.getLogger(__name__)

NAME = "Texas county appraisal districts"
ATTRIBUTION = ("Texas county appraisal districts (Harris, Fort Bend, Montgomery, "
               "Dallas, Tarrant, Bexar, Travis) via their public parcel services, "
               "keyless")
DATA_VINTAGE = "Texas appraisal district rolls, one service per county"

_HOUSTON = ("https://geohwp.houstontx.gov/arcgis/rest/services/03_BaseData_External"
            "/Parcels_Current/MapServer")
#: Harris County: the City of Houston's republication of the HCAD roll.
HARRIS_URL = f"{_HOUSTON}/4/query"
#: Montgomery County: the City of Houston's republication of the MCAD roll.
MONTGOMERY_URL = f"{_HOUSTON}/3/query"
#: Fort Bend County: FBCAD's own public parcel layer. The City of Houston's copy
#: (``_HOUSTON`` layer 5) was measured and replaced; see "Fort Bend" above.
FORT_BEND_URL = ("https://gisweb.fbcad.org/arcgis/rest/services/Hosted"
                 "/FBCADPublicData/FeatureServer/0/query")
#: Dallas County: DCAD's own parcel-query layer ("ParcelPublishing").
DALLAS_URL = ("https://maps.dcad.org/prdwa/rest/services/Property/ParcelQuery"
              "/MapServer/4/query")
#: Tarrant County: TAD's own parcel map service ("ParcelView").
TARRANT_URL = ("https://tad.newedgeservices.com/arcgis/rest/services/OD_TAD"
               "/OD_ParcelView/MapServer/0/query")
#: Bexar County: the county's parcel layer, joined to the BCAD roll.
BEXAR_URL = "https://maps.bexar.org/arcgis/rest/services/Parcels/MapServer/0/query"
#: Travis County: the county's (TNR) tax-map layer, joined to the TCAD roll.
TRAVIS_URL = ("https://taxmaps.traviscountytx.gov/arcgis/rest/services/Parcels"
              "/MapServer/0/query")
#: Collin County: the City of Allen's weekly republication of the CCAD roll.
COLLIN_URL = ("https://gismaps.cityofallen.org/arcgis/rest/services/ReferenceData"
              "/Collin_County_Appraisal_District_Parcels/FeatureServer/1/query")
#: Denton County: the county's copy of the Denton CAD roll.
DENTON_URL = ("https://gis.dentoncounty.gov/arcgis/rest/services/Parcels_FC"
              "/MapServer/0/query")
#: El Paso County: the City of El Paso's copy of the EPCAD roll.
EL_PASO_URL = ("https://gis.elpasotexas.gov/arcgis/rest/services/CachedServices"
               "/Parcels_Uncached/MapServer/0/query")
#: Cameron County: the Cameron CAD's 2026 export, hosted by the City of Brownsville.
CAMERON_URL = ("https://cobgis.brownsvilletx.gov/arcgis/rest/services/Hosted"
               "/CameronCAD_Parcels_05312026/FeatureServer/0/query")
#: Williamson County: WCAD's open-data portal — the parcels (polygons, address)...
WILLIAMSON_URL = "https://data.wcad.org/resource/an3x-cnmw.json"
#: ... joined on the property id to its property characteristics (the year).
WILLIAMSON_CHARACTERISTICS_URL = "https://data.wcad.org/resource/cvyp-ab5t.json"
_WILLIAMSON_IMPROVEMENT_FIELDS = "propertyid,actyrbuilt,sqftcur,fsptb,datadate"

#: How long a service may go quiet before the silence is a stall, and the budget
#: for a whole lookup. See "Timing" in the module docstring.
READ_SLICE_S = _shared._READ_SLICE_S
LOOKUP_TIMEOUT = _shared.TIMEOUT


# ── what a row says about homes ────────────────────────────────────────────────
#
# Every appraisal district files each account under the Comptroller's state
# property category (Property Classification Guide, 96-313): A single-family
# residential (condominiums and townhomes included), B multifamily, C vacant lots,
# D qualified open-space land, E rural land and its improvements, F commercial and
# industrial, G minerals, J utilities, L business personal property, M mobile
# homes, O residential inventory, S special inventory, X totally exempt. The CADs
# add numeric suffixes (A1, B2, F1H) and some add local codes, so each county's
# reader maps its own column onto one of these five readings:

#: One dwelling in one building, as the roll states it: a single-family house, a
#: townhouse on its own lot, a mobile home. Year, floor area and stories.
ONE_HOME = "one home"
#: A unit, or a building of units. The year is the building's and is reported;
#: the floor area and stories are a unit's or the building's, never "the home".
CONDO = "condominium"
#: Multifamily (duplex and up). The year is reported; the area is all the homes.
MULTI = "multifamily"
#: The class says nothing either way: rural land with improvements (E), builder
#: inventory (O), totally exempt (X: an exemption, not a use — a 100% disabled
#: veteran's homestead is totally exempt under Tax Code §11.131, and Fort Bend's
#: XV rows include ordinary houses beside churches), a blank. The year is
#: reported, the area is not.
SILENT = "silent"
#: The class says no one lives here: vacant land, open-space land, commercial or
#: industrial, minerals, utilities, inventory. Nothing is reported.
NOT_A_HOME = "not a home"
#: Not a parcel at all: a business-personal-property account (category L — a
#: shop's fixtures, an aircraft) filed on the polygon of the parcel it sits on,
#: under that parcel's address. A record of nothing about a building, and left in
#: it would make the real parcel beneath look ambiguous, so the row is dropped as
#: a non-record, the sanctioned shape (see ``select_parcel``).
PERSONAL_PROPERTY = "personal property"

#: Comptroller category letter → reading, for the part every CAD shares. A
#: county's reader refines A (which is houses AND condominiums) itself.
_CATEGORY = {
    "A": CONDO,          # refined per county: only an explicit single-family code
                         # is ONE_HOME, because A also holds condominiums
    "B": MULTI,
    "C": NOT_A_HOME,
    "D": NOT_A_HOME,     # D1 open-space land, D2 farm and ranch improvements on it
    "E": SILENT,
    "F": NOT_A_HOME,
    "G": NOT_A_HOME,
    "J": NOT_A_HOME,
    "L": PERSONAL_PROPERTY,
    "M": ONE_HOME,
    "N": NOT_A_HOME,
    "O": SILENT,
    "S": NOT_A_HOME,
    "X": SILENT,
}

# A trailing exemption flag on Montgomery's codes: "A1XV" is an A1 house with a
# total exemption (331 houses carry it), "C1XV" an exempt vacant lot.
_EXEMPTION_FLAG = re.compile(r"^([A-WYZ]\d?)X[A-Z]$")
# A leading digit on Harris's open-space code: "1D1" (4,206 rows) is D1.
_LEADING_DIGIT = re.compile(r"^\d([A-Z]\d?)$")


def _state_code(raw) -> str:
    """The Comptroller code in a CAD's column, upper-cased and stripped of the
    space padding Tarrant and Dallas carry, of Montgomery's exemption flag and of
    Harris's leading digit."""
    code = " ".join(str(raw or "").split()).upper()
    m = _EXEMPTION_FLAG.match(code) or _LEADING_DIGIT.match(code)
    return m.group(1) if m else code


def _reading(code: str, one_home_codes: frozenset[str]) -> str:
    """The reading of a Comptroller state code; see the constants above."""
    if not code or code == "NULL":
        return SILENT
    if code in one_home_codes:
        return ONE_HOME
    return _CATEGORY.get(code[0], SILENT)


# ── small parsers ──────────────────────────────────────────────────────────────


def _year(raw) -> int | None:
    """An actual year built, or None.

    Accepts a number or a numeric string. ``0``, blank and Bexar's literal string
    ``'NULL'`` are "not recorded". Harris writes every building on a parcel into
    one comma-separated string ("1968,2004,2007"): the year is reported only when
    every building agrees, because which of them is the home is not recorded.
    """
    if raw is None:
        return None
    parts = {p.strip() for p in str(raw).split(",")} - {""}
    years = set()
    for p in parts:
        y = num(p)
        if y is None or not y or not float(y).is_integer():
            return None
        years.add(int(y))
    if len(years) != 1:
        return None
    y = years.pop()
    return y if EARLIEST_PLAUSIBLE_YEAR <= y <= 2100 else None


def _area(raw) -> float | None:
    """A positive floor area, or None. A comma list (Harris, several buildings)
    is the sum of buildings and is never one home's area."""
    if raw is None or "," in str(raw):
        return None
    area = num(str(raw).strip())
    return area if area is not None and area > 0 else None


_STORY_WORDS = {"ONE STORY": 1, "TWO STORIES": 2, "THREE STORIES": 3}


def _stories(raw) -> int | None:
    """A whole story count from Dallas's wording or Bexar's number. Half stories
    ("ONE AND ONE HALF STORIES", "1.5") have no whole-number reading."""
    text = " ".join(str(raw or "").split()).upper()
    if text in _STORY_WORDS:
        return _STORY_WORDS[text]
    n = num(text)
    if n is not None and float(n).is_integer() and 1 <= n <= 4:
        return int(n)
    return None


def _clean(raw) -> str:
    return " ".join(str(raw or "").split())


def _unmarked_unit(address: str) -> str | None:
    """A unit written with no marker after the street type, or None.

    Harris writes a condominium unit bare: "829 YALE ST 504", "2200 WILLOWICK RD
    16J". ``address_key`` already drops such a token for comparison (a trailing
    digit-bearing token right after a street type); this names it, so the row can
    be recognized as a unit record and a typed unit can be matched against it.
    """
    tokens = address.split(",")[0].lower().split()
    if len(tokens) >= 3 and tokens[-2] in SUFFIXES and any(c.isdigit() for c in tokens[-1]):
        return tokens[-1]
    return None


def _unit(address: str, explicit=None) -> str | None:
    """The unit a row names: its own unit column where it has one, else what its
    address carries, marked ("# B") or bare ("ST 504")."""
    own = _clean(explicit)
    if own:
        return own.lower()
    marked = unit_of(address)
    if marked:
        return marked.lower()
    return _unmarked_unit(address)


# ── the counties ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class _County:
    """One county's service and how to read its rows."""

    name: str
    url: str
    fields: str
    source: str
    read: Callable[[dict], dict | None]
    #: The column the street address is in, for the same-address search.
    address_field: str
    #: The column holding the house number ALONE, where the service splits the
    #: address into parts (El Paso, Cameron): the same-number search then asks for
    #: it exactly instead of searching inside a whole address string.
    number_field: str | None = None
    #: Where the rows come from, for a county they do not come from as one ArcGIS
    #: layer (Williamson: two Socrata datasets). Called like ``_arcgis_rows``.
    fetch: Callable[..., list[dict]] | None = None

    def same_number(self, number: str) -> str:
        """The attribute filter for "rows whose address carries this house
        number". ``number`` is digits only (``address_key`` insists), so it is
        safe to write into the predicate."""
        if self.number_field:
            f = self.number_field
            return f"{f} = '{number}' OR {f} LIKE '{number} %'"
        f = self.address_field
        return f"{f} LIKE '{number} %' OR {f} LIKE '% {number} %'"


def _candidate(pid, address, *, unit=None, year=None, reading=SILENT, sqft=None,
               stories=None, vintage=None) -> dict | None:
    """The normalized shape every county's reader returns, or None for a row that
    is a record of nothing (no identifier)."""
    pid = _clean(pid)
    if not pid or reading == PERSONAL_PROPERTY:
        return None
    address = _clean(address)
    unit = _unit(address, unit)
    one = reading == ONE_HOME and not unit
    return {
        "pid": pid, "address": address or None, "unit": unit, "reading": reading,
        "year": year if reading != NOT_A_HOME else None,
        # Area and stories only where the row is one home in one building and
        # names no unit. A reader passes them already gated on its own evidence.
        "sqft": sqft if one else None,
        "stories": stories if one else None,
        "vintage": vintage,
    }


# Harris — the City of Houston's "Current HCAD Parcels".
#
# HCAD codes condominium units Z1–Z5 (63,491 rows, all but 6 typed "Residential
# Condo"), so a Z is a unit. A1 is single-family, A2 a mobile home on its own land. A third
# piece of evidence is required for floor area, because HCAD aggregates every
# building on a parcel into one row: BUILDCOUNT must be 1 and the building type a
# single residential type (not "Residential Duplex,Residential Single Family").
_HARRIS_ONE = frozenset({"A1", "A2"})
_HARRIS_ONE_TYPES = frozenset({"residential single family", "residential townhome",
                               "residential mobile homes"})


def _read_harris(r: dict) -> dict | None:
    code = _state_code(r.get("STATECLASS"))
    reading = CONDO if code.startswith("Z") else _reading(code, _HARRIS_ONE)
    one_building = (num(r.get("BUILDCOUNT")) == 1
                    and _clean(r.get("BLDTYPE_DS")).lower() in _HARRIS_ONE_TYPES)
    if reading == ONE_HOME and not one_building:
        reading = SILENT
    roll = _year(r.get("TAX_YEAR"))
    return _candidate(
        r.get("PARCEL_ID"), r.get("ADDRESS"), year=_year(r.get("YEAR_BUILT")),
        reading=reading, sqft=_area(r.get("IMPR_SQ_FT")),
        vintage=(f"HCAD {roll} appraisal roll, as republished by the City of Houston"
                 if roll else "HCAD appraisal roll, as republished by the City of "
                 "Houston"))


# Fort Bend — FBCAD's own public parcel layer. ``building_sptb_code`` is the
# Comptroller code of the improvement, ``land_state_code`` that of the land; the
# improvement's is the statement about the building, and the land's is read only
# where the improvement carries none.
_FORT_BEND_ONE = frozenset({"A1", "A2"})


def _read_fort_bend(r: dict) -> dict | None:
    code = _state_code(r.get("BUILDING_SPTB_CODE")) or _state_code(r.get("LAND_STATE_CODE"))
    return _candidate(
        r.get("QUICKREFID") or r.get("PROPNUMBER"), r.get("SITUS"),
        unit=r.get("SITUSAPT"), year=_year(r.get("YEARBUILT")),
        reading=_reading(code, _FORT_BEND_ONE), sqft=_area(r.get("TOTSQFTLVG")),
        vintage=("FBCAD public parcel data (no tax year published; newest year "
                 "built in the layer 2026, as measured 2026-10-03)"))


# Montgomery — the City of Houston's "Current MCAD Parcels".
_MONTGOMERY_ONE = frozenset({"A1", "A2"})


def _read_montgomery(r: dict) -> dict | None:
    roll = _year(r.get("TAX_YEAR"))
    return _candidate(
        r.get("PARCEL_ID"), r.get("ADDRESS"), year=_year(r.get("YEAR_BUILT")),
        reading=_reading(_state_code(r.get("STATECLASS")), _MONTGOMERY_ONE),
        sqft=_area(r.get("IMPR_SQ_FT")),
        vintage=(f"MCAD {roll} appraisal roll, as republished by the City of Houston"
                 if roll else "MCAD appraisal roll, as republished by the City of "
                 "Houston"))


# Dallas — DCAD's ParcelQuery layer. CLASSCD is DCAD's own code, not the
# Comptroller's, and its description travels in CLASSDSCRP; read off the layer's
# 32 values (2026-10-03):
_DALLAS_CLASS = {
    "1": ONE_HOME,       # SINGLE FAMILY RESIDENCES
    "2": ONE_HOME,       # SFR - TOWNHOUSES
    "3": CONDO,          # SFR - CONDOMINIUMS
    "4": ONE_HOME,       # MOBILE HOME ON OWNERS LAND
    "35": ONE_HOME,      # MOBILE HOMES ON LEASED SPACES
    "5": MULTI,          # MFR - APARTMENTS
    "6": MULTI,          # MFR - DUPLEXES
    "15": SILENT,        # RURAL LAND AND IMPROVEMENTS NON QUALIFIED
    "40": SILENT,        # RESIDENTIAL - IMPROVEMENTS AS INVENTORY
    "0": SILENT,         # UNASSIGNED
}
# Everything else is a statement that no one lives there — vacant lots and tracts
# (7, 8, 9, 10, 39), open-space land (11), commercial and industrial improvements
# (17, 18), utilities and railroads (22–29, 49), minerals (41), special inventory
# (46) — except the personal-property accounts (31 COMMERCIAL BPP, 32 INDUSTRIAL
# BPP, 33 WATERCRAFT, 34 AIRCRAFT), which are not parcels at all: 80,394 business
# accounts filed on the polygon, and under the address, of the parcel they sit in.
for _code in ("31", "32", "33", "34"):
    _DALLAS_CLASS[_code] = PERSONAL_PROPERTY


def _read_dallas(r: dict) -> dict | None:
    code = _clean(r.get("CLASSCD"))
    revalued = _year(r.get("REVALYR"))
    return _candidate(
        r.get("PARCELID"), r.get("SITEADDRESS"), unit=r.get("UNIT"),
        year=_year(r.get("RESYRBLT")), reading=_DALLAS_CLASS.get(code, NOT_A_HOME),
        sqft=_area(r.get("RESFLRAREA")), stories=_stories(r.get("RESSTRTYP")),
        vintage=(f"DCAD appraisal records (ParcelQuery), last revalued {revalued}"
                 if revalued else "DCAD appraisal records (ParcelQuery)"))


# Tarrant — TAD's "ParcelView" map service: TAD's parcel polygons joined to its
# published PropertyData-FullSet. ``Property_C`` is the Comptroller code (A1
# single-family, A2 mobile home on its land, A3 condominium and townhouse units,
# B multifamily, L1 business personal property, ...), ``Year_Built`` and
# ``Living_Are`` space-padded strings, ``Appraisal_`` the roll year. TAD's newer
# hosted layer (Hosted/TADMap, a year fresher) was measured and not used; see
# "Tarrant" in the module docstring.
_TARRANT_ONE = frozenset({"A1", "A2"})


def _tarrant_address(raw) -> str:
    """TAD's situs address with its one source-specific spelling made standard.

    TAD writes Trail as "TR" ("2828 CONCHO TR"), where the Census matcher writes
    "TRL"; the shared table leaves "TR" out on purpose, because elsewhere it can
    mean Terrace — but TAD spells Terrace "TERR" ("1509 CARSWELL TERR"), so in
    this roll "TR" is only ever Trail. Without this, 2 of 44 geocoded Tarrant homes
    in the verification run were refused.
    """
    tokens = _clean(raw).split()
    if len(tokens) >= 3 and tokens[-1].upper() == "TR":
        tokens[-1] = "TRL"
    return " ".join(tokens)


def _read_tarrant(r: dict) -> dict | None:
    roll = _year(r.get("APPRAISAL_"))
    return _candidate(
        r.get("TAXPIN"), _tarrant_address(r.get("SITUS_ADDR")),
        year=_year(r.get("YEAR_BUILT")),
        reading=_reading(_state_code(r.get("PROPERTY_C")), _TARRANT_ONE),
        sqft=_area(r.get("LIVING_ARE")),
        vintage=f"TAD {roll} appraisal roll" if roll else "TAD appraisal roll")


# Bexar — the county's parcel layer. ``Houses`` counts the parcel's houses, which
# is the one-dwelling evidence; ``GBA`` is the main building's area and
# ``TOT_GBA`` all of them, so the two must agree as well.
_BEXAR_ONE = frozenset({"A1", "A2"})
# Neither the Bexar nor the Travis layer carries a tax year, and both describe
# themselves out of date, so the newest year built either holds is stated with the
# date it was measured: a reader can then date the roll rather than trust it.
_BEXAR_VINTAGE = ("BCAD roll via Bexar County GIS (no tax year published; newest "
                  "year built in the layer 2024, as measured 2026-10-03)")


def _read_bexar(r: dict) -> dict | None:
    pid = r.get("PROPID")
    pid = str(int(pid)) if isinstance(pid, (int, float)) and pid else pid
    code = _state_code(r.get("STATE_CD"))
    reading = _reading(code, _BEXAR_ONE)
    houses = num(r.get("HOUSES"))
    # An explicit zero houses on a record that is not multifamily is the roll
    # saying no dwelling stands there (an apartment complex records its buildings
    # elsewhere and reads 0). The same rule as Florida's dwelling count.
    if houses == 0 and reading != MULTI:
        reading = NOT_A_HOME
    gba, total = _area(r.get("GBA")), _area(r.get("TOT_GBA"))
    one = houses == 1 and gba is not None and gba == total
    if reading == ONE_HOME and not one:
        reading = SILENT
    return _candidate(
        pid, r.get("SITUS"), year=_year(r.get("YRBLT")), reading=reading,
        sqft=gba, stories=_stories(r.get("STORIES")),
        vintage=_BEXAR_VINTAGE)


# Travis — the county's tax-map layer. ``situs_address`` is written "<predir>
# <number> <street> [<city>] TX <zip>", with the leading directional BEFORE the
# number ("W 1316 6 ST   TX 78701" is 1316 W 6th St), and ``situs_street`` holds
# "TX" on every row sampled, so the address is rebuilt from the one column.
_TRAVIS_ONE = frozenset({"A1", "A2"})
_TRAVIS_VINTAGE = ("TCAD roll via Travis County tax maps (no tax year published; "
                   "newest year built in the layer 2023, as measured 2026-10-03)")
_TRAVIS_CITIES = tuple(sorted((tuple(c.split()) for c in (
    "AUSTIN", "PFLUGERVILLE", "MANOR", "LAKEWAY", "LAGO VISTA", "WEST LAKE HILLS",
    "ROLLINGWOOD", "SUNSET VALLEY", "BEE CAVE", "BRIARCLIFF", "CREEDMOOR",
    "JONESTOWN", "MUSTANG RIDGE", "POINT VENTURE", "SAN LEANNA", "THE HILLS",
    "VOLENTE", "WEBBERVILLE", "ELGIN", "DEL VALLE", "LEANDER", "CEDAR PARK",
    "ROUND ROCK", "SPICEWOOD", "DRIPPING SPRINGS", "DRIPPING SPGS", "MANCHACA",
    "BUDA", "KYLE", "COUPLAND", "HUTTO", "BASTROP", "CEDAR CREEK")),
    key=len, reverse=True))
_LEADING_DIRECTIONS = frozenset({"N", "S", "E", "W", "NE", "NW", "SE", "SW"})
_ZIP = re.compile(r"^\d{5}(-\d{4})?$")


def _travis_address(raw) -> str:
    """Travis's situs string as an ordinary street address.

    "W 1316 6 ST   TX 78701" → "1316 W 6 ST"; "  1707 BAY HILL DR AUSTIN TX
    78746" → "1707 BAY HILL DR". A city this table does not know stays in the
    string, where it makes the address fail to match anything — a refusal, never
    a wrong match. A city is removed only when a number and a name would remain,
    so a street that is itself named after a city survives.
    """
    tokens = _clean(raw).upper().split()
    if tokens and _ZIP.match(tokens[-1]):
        tokens.pop()
    if tokens and tokens[-1] == "TX":
        tokens.pop()
    for city in _TRAVIS_CITIES:
        n = len(city)
        if len(tokens) > n + 1 and tuple(tokens[-n:]) == city:
            tokens = tokens[:-n]
            break
    if len(tokens) >= 3 and tokens[0] in _LEADING_DIRECTIONS and tokens[1].isdigit():
        tokens[0], tokens[1] = tokens[1], tokens[0]
    return " ".join(tokens)


def _read_travis(r: dict) -> dict | None:
    return _candidate(
        r.get("PROP_ID"), _travis_address(r.get("SITUS_ADDRESS")),
        year=_year(r.get("F1YEAR_IMPRV")),
        reading=_reading(_state_code(r.get("LAND_STATE_CD")), _TRAVIS_ONE),
        vintage=_TRAVIS_VINTAGE)


def _codes_reading(raw, one_home_codes: frozenset[str],
                   overrides: dict[str, str] | None = None) -> str:
    """The reading of a column that may list several state codes.

    Denton writes every code an account carries, comma-joined ("A1,D1,E1": a
    house on open-space land with a rural improvement), and Williamson's
    characteristics carry a code per improvement. One code reads as usual.
    Several codes are never one home, even "A1,A1": each describes a part of the
    account, and which part the reader lives in is not stated, so the area is
    withheld. They refuse together only when every one of them refuses; a code
    that admits a home, or says nothing ("A1,F1", "C1,PLAN"), leaves the year
    standing.
    """
    overrides = overrides or {}
    codes = [c for c in (_state_code(p) for p in str(raw or "").split(",")) if c]
    readings = {overrides.get(c) or _reading(c, one_home_codes) for c in codes}
    if not readings:
        return SILENT
    if len(readings) == 1 and len(codes) == 1:
        return readings.pop()
    if readings == {NOT_A_HOME}:
        return NOT_A_HOME
    if PERSONAL_PROPERTY in readings and readings <= {PERSONAL_PROPERTY, NOT_A_HOME}:
        return PERSONAL_PROPERTY
    return SILENT


def _first_line(raw) -> str:
    """The street line of an address that runs on to the city on a new line."""
    return _clean(str(raw or "").replace("\r", "\n").split("\n")[0])


def _whole_number(raw) -> str:
    """An identifier that a service stores as a float (``364745.0``), as text."""
    n = num(raw)
    return str(int(n)) if n is not None and float(n).is_integer() and n else _clean(raw)


# Collin — CCAD's roll as the City of Allen republishes it weekly (its "CCAD Tax
# Parcels", fed by a script every Friday). The columns arrive prefixed with the
# joined table's name. CCAD's own codes, from its certified totals: A1
# residential single family, A2 mobile home on its own land, A3 condominiums, A4
# townhomes. Its M4 and M5 are not mobile homes: read off the layer, they are
# subdivisions' common areas — 9,996 accounts, legal descriptions such as "LOT
# COMMON AREA", "(OPEN SPACE)", "SECURITY OFFICE", nearly all with no situs — and
# a clubhouse's year is no one's home's. M3 carries HUD numbers: a mobile home.
_COLLIN_ONE = frozenset({"A1", "A2", "A4", "M3"})
_COLLIN_CODES = {"M4": NOT_A_HOME, "M5": NOT_A_HOME}
_COLLIN_PREFIX = "GIS_DBO_AD_ENTITY_"
# CCAD's ``property_status`` values, as the record should say them.
_STATUS = {"InProgress": "in progress", "Preliminary": "preliminary",
           "Certified": "certified", "": "status not stated"}


def _read_collin(r: dict) -> dict | None:
    def col(name):
        return r.get(_COLLIN_PREFIX + name)

    roll, status = _year(col("CURR_VAL_YR")), _clean(col("PROPERTY_STAT"))
    # ``living_area`` is CCAD's "improvement main area", which the layer's own
    # alias glosses "(of all bldgs)": the living area, garages and porches apart.
    # On a code that says one house (A1), one townhouse (A4) or one mobile home
    # it is that home's; it is never reported on anything else.
    return _candidate(
        col("PROP_ID"), _first_line(col("SITUS_DISPLAY")),
        year=_year(col("YR_BLT")),
        reading=_codes_reading(col("STATE_CD"), _COLLIN_ONE, _COLLIN_CODES),
        sqft=_area(col("LIVING_AREA")), stories=_stories(col("STORIES")),
        vintage=(f"CCAD {roll} appraisal year ({_STATUS.get(status, status.lower())}), "
                 "as republished by the City of Allen" if roll else
                 "CCAD appraisal records, as republished by the City of Allen"))


# Denton — the county's copy of the Denton CAD roll ("DCAD's Update Parcel data",
# where DCAD is Denton's, not Dallas's). ``stateCodes`` lists every code the
# account carries. A1 is a single-family house and A2 a mobile home on its own
# land (its improvements read MS/MD, single- and double-wide); the CAD's other A
# codes — A3 and A6 houses on larger lots by the look of them, A4 and A5
# condominiums, fourplexes and townhomes (improvement class 26, "VISTA RIDGE
# CONDOMINIUMS") — are not published with definitions, so they report the year
# and nothing a single home owns.
_DENTON_ONE = frozenset({"A1", "A2"})


def _read_denton(r: dict) -> dict | None:
    roll = _year(r.get("PYEAR"))
    return _candidate(
        r.get("PID"), r.get("SITUS_STREET_ADDRESS"),
        year=_year(r.get("IMPRVACTUALYEARBUILT")),
        reading=_codes_reading(r.get("STATECODES"), _DENTON_ONE),
        # The main area, not ``imprvTotalArea``, which adds garages and porches
        # (8950 Crockett Dr: 4,282 main, 5,649 total).
        sqft=_area(r.get("IMPRVMAINAREA")),
        vintage=(f"Denton CAD records for appraisal year {roll}, via Denton County GIS"
                 if roll else "Denton CAD records, via Denton County GIS"))


# El Paso — the City of El Paso's copy of the EPCAD roll (layer
# "testing.DBO.Parcels" in its CachedServices folder, which despite the name is
# the city's live parcel service: 407,054 rows, the whole county, roll year 2026
# on 401,372). The address is in parts — number, street (with any leading
# directional), type in ``SITUS_DIR`` despite its name, unit — and rebuilt here.
# No floor area or stories are published, so El Paso reports the year alone,
# whatever the code says; the code still decides whether a year is a home's.
def _read_el_paso(r: dict) -> dict | None:
    roll = _year(r.get("PROP_VAL_Y"))
    street = " ".join(_clean(r.get(k)) for k in ("SITUS_NUM", "SITUS_STRE", "SITUS_DIR"))
    return _candidate(
        _whole_number(r.get("PROP_ID")), street, unit=r.get("SITUS_UNIT"),
        year=_year(r.get("YR_BLT")),
        reading=_reading(_state_code(r.get("STATE_CD")), frozenset()),
        vintage=(f"EPCAD {roll} appraisal roll, as republished by the City of El Paso"
                 if roll else "EPCAD appraisal roll, as republished by the City of El Paso"))


# Cameron — the Cameron CAD's yearly parcel export as the City of Brownsville
# hosts it (``CameronCAD_Parcels_05312026``: exported 2026-05-31, roll year 2026,
# the whole county). Its residential code is a bare "A" on 115,985 of 187,770
# rows, which does not separate a house from a condominium unit, so Cameron
# reports the year alone. ``situsDispl`` runs the city on without a comma
# ("2147  SHADOWBROOK CIRCLE  HARLINGEN TX"), so the address is rebuilt from its
# parts.
def _read_cameron(r: dict) -> dict | None:
    roll, exported = _year(r.get("PYEAR")), _clean(r.get("EXPORTDT"))
    street = " ".join(_clean(r.get(k)) for k in ("SITUSNO", "SITPFX", "SITSTR", "SITSFX"))
    return _candidate(
        r.get("PROP_ID"), street, year=_year(r.get("YRBUILT")),
        reading=_reading(_state_code(r.get("STATECD")), frozenset()),
        vintage=(f"Cameron CAD {roll} appraisal roll (exported {exported or 'date not stated'}), "
                 "as republished by the City of Brownsville" if roll else
                 "Cameron CAD appraisal roll, as republished by the City of Brownsville"))


# Williamson — WCAD's own open-data portal (Socrata, data.wcad.org), two datasets
# joined on the property id: "Parcels" (the polygons, with the situs address) and
# "Property Characteristics" (one row per improvement: actual year built, current
# square footage, the improvement's state code). WCAD's ArcGIS parcel layer
# carries a year-built column that is empty on every one of its 291,077 rows, so
# the portal is the only keyless source of the year. See ``_williamson_rows``.
_WILLIAMSON_ONE = frozenset({"A1", "A2"})


def _read_williamson(r: dict) -> dict | None:
    improvements = r.get("_IMPROVEMENTS") or []
    years = {_year(i.get("actyrbuilt")) for i in improvements}
    year = years.pop() if len(years) == 1 else None
    reading = _codes_reading(",".join(_clean(i.get("fsptb")) for i in improvements),
                             _WILLIAMSON_ONE)
    # Floor area only from an account with ONE improvement row: ``sqftcur`` is
    # the account's current square footage, and two rows are two improvements
    # (78745: two rows, one house and something else) whose sum is not a home.
    sqft = _area(improvements[0].get("sqftcur")) if len(improvements) == 1 else None
    dates = {_clean(i.get("datadate"))[:10] for i in improvements} - {""}
    return _candidate(
        r.get("PARCELID"), _williamson_address(r.get("SITEADDRESS")), unit=r.get("UNIT"),
        year=year, reading=reading, sqft=sqft,
        vintage=("WCAD property characteristics, via the WCAD open-data portal"
                 + (f" (exported {dates.pop()})" if len(dates) == 1 else "")))


def _williamson_address(raw) -> str:
    """WCAD's situs address with its one source-specific spelling made standard.

    WCAD writes a street's directional AFTER the street type where the street
    has one ("726 5TH ST W, TAYLOR, TX  76574" — about 5,500 addresses, most of
    Taylor and old Round Rock), and the Census matcher writes it before the name
    ("726 W 5TH ST"): checked on four such addresses in Taylor, Bartlett and
    Austin, all four came back from the matcher with the directional first. The
    shared comparison keeps a directional where it stands, on purpose (a quadrant
    city's "NEWARK ST NW" is not "NW NEWARK ST"), so here, and only after a street
    type, it is moved in front of the name. The city after the comma is left for
    the shared comparison to set aside.
    """
    street, sep, rest = _clean(raw).partition(",")
    tokens = street.split()
    if (len(tokens) >= 4 and tokens[0].isdigit() and tokens[-1] in _LEADING_DIRECTIONS
            and tokens[-2].lower() in SUFFIXES):
        tokens = [tokens[0], tokens[-1], *tokens[1:-1]]
    return " ".join(tokens) + sep + rest


#: The most rows one Socrata request may return before the answer is treated as
#: cut short. A point or an 80 m circle meets a few dozen parcels; reaching this
#: means the page is not the whole answer, which is refused like ArcGIS's
#: ``exceededTransferLimit``.
_SOCRATA_LIMIT = 500


def _circle_wkt(lat: float, lon: float, radius_m: float, sides: int = 32) -> str:
    """A polygon standing in for "within ``radius_m`` of the point", in WKT.

    Socrata's own ``within_circle`` does not ask what ArcGIS's buffer asks
    ("which parcels does the circle touch?"): probed at 101 Main Ave W, Round
    Rock, it returned 14 parcels within 80 m where intersecting a drawn circle
    returned 27. ``intersects`` against a 32-sided polygon does ask it: the
    polygon is inscribed in the circle and its sides fall short of the arc by at
    most 0.5% of the radius (40 cm at 80 m).
    """
    pts = []
    for i in range(sides + 1):
        a = 2 * math.pi * (i % sides) / sides
        dlat = radius_m * math.cos(a) / 111_320
        dlon = radius_m * math.sin(a) / (111_320 * math.cos(math.radians(lat)))
        pts.append(f"{lon + dlon:.7f} {lat + dlat:.7f}")
    return f"POLYGON(({', '.join(pts)}))"


def _socrata(url: str, params: dict, deadline: float) -> list[dict]:
    rows = _shared.get_json(url, dict(params, **{"$limit": str(_SOCRATA_LIMIT)}),
                            deadline, READ_SLICE_S)
    if not isinstance(rows, list):
        raise RuntimeError(f"unexpected Socrata response from {url}")
    if len(rows) >= _SOCRATA_LIMIT:
        raise _shared.TruncatedResponse(f"{url}: {len(rows)} rows, the request's limit")
    return rows


def _williamson_rows(county: _County, lat: float, lon: float, distance_m: float,
                     *, deadline: float, number: str | None = None) -> list[dict]:
    """Williamson's parcels at (or within ``distance_m`` of) a point, each with
    its improvements attached as ``_IMPROVEMENTS``.

    Two requests: the parcels the point or circle intersects (and, for the
    same-number search, whose address starts with the number), then every
    improvement row of those properties in one ``propertyid in (...)`` query.
    Only the columns named are asked for in either: the characteristics dataset
    also carries market values and deed dates, the parcels dataset owner names
    and mailing addresses.
    """
    shape = (_circle_wkt(lat, lon, distance_m) if distance_m
             else f"POINT({lon:.7f} {lat:.7f})")
    where = f"intersects(geometry, '{shape}')"
    if number:
        where += f" AND starts_with(siteaddress, '{number} ')"
    parcels = _socrata(county.url, {"$select": county.fields, "$where": where}, deadline)
    ids = sorted({str(p.get("propertyid")) for p in parcels
                  if str(p.get("propertyid") or "").isdigit()}, key=int)
    by_id: dict[str, list[dict]] = {}
    if ids:
        for row in _socrata(WILLIAMSON_CHARACTERISTICS_URL,
                            {"$select": _WILLIAMSON_IMPROVEMENT_FIELDS,
                             "$where": f"propertyid in ({','.join(ids)})"}, deadline):
            by_id.setdefault(_whole_number(row.get("propertyid")), []).append(row)
    return [dict(p, _IMPROVEMENTS=by_id.get(str(p.get("propertyid")), []))
            for p in parcels]


#: County FIPS → its service. Field lists are explicit and carry no owner name,
#: mailing address, deed, sale or value column; see "Privacy" in the docstring.
COUNTIES = {
    "48201": _County(
        "Harris", HARRIS_URL,
        "PARCEL_ID,ADDRESS,TAX_YEAR,STATECLASS,YEAR_BUILT,IMPR_SQ_FT,BLDTYPE_DS,"
        "BUILDCOUNT",
        "Harris Central Appraisal District, via City of Houston GIS (keyless)",
        _read_harris, "ADDRESS"),
    "48157": _County(
        "Fort Bend", FORT_BEND_URL,
        "propnumber,quickrefid,situs,situsapt,yearbuilt,totsqftlvg,"
        "building_sptb_code,land_state_code",
        "Fort Bend Central Appraisal District public parcel data (keyless)",
        _read_fort_bend, "situs"),
    "48339": _County(
        "Montgomery", MONTGOMERY_URL,
        "PARCEL_ID,ADDRESS,TAX_YEAR,STATECLASS,YEAR_BUILT,IMPR_SQ_FT",
        "Montgomery Central Appraisal District, via City of Houston GIS (keyless)",
        _read_montgomery, "ADDRESS"),
    "48113": _County(
        "Dallas", DALLAS_URL,
        "PARCELID,SITEADDRESS,UNIT,CLASSCD,RESYRBLT,RESFLRAREA,RESSTRTYP,REVALYR",
        "Dallas Central Appraisal District ParcelQuery (keyless)",
        _read_dallas, "SITEADDRESS"),
    "48439": _County(
        "Tarrant", TARRANT_URL,
        "TAXPIN,Situs_Addr,Property_C,Year_Built,Living_Are,Appraisal_",
        "Tarrant Appraisal District ParcelView (keyless)",
        _read_tarrant, "Situs_Addr"),
    "48029": _County(
        "Bexar", BEXAR_URL,
        "PropID,Situs,YrBlt,GBA,TOT_GBA,Stories,State_cd,Houses",
        "Bexar Appraisal District roll, via Bexar County GIS (keyless)",
        _read_bexar, "Situs"),
    "48453": _County(
        "Travis", TRAVIS_URL,
        "PROP_ID,situs_address,F1year_imprv,land_state_cd",
        "Travis Central Appraisal District roll, via Travis County GIS (keyless)",
        _read_travis, "situs_address"),
    "48085": _County(
        "Collin", COLLIN_URL,
        "GIS_DBO_AD_Entity_prop_id,GIS_DBO_AD_Entity_situs_display,"
        "GIS_DBO_AD_Entity_state_cd,GIS_DBO_AD_Entity_yr_blt,"
        "GIS_DBO_AD_Entity_living_area,GIS_DBO_AD_Entity_stories,"
        "GIS_DBO_AD_Entity_curr_val_yr,GIS_DBO_AD_Entity_property_stat",
        "Collin Central Appraisal District roll, via City of Allen GIS (keyless)",
        _read_collin, "GIS_DBO_AD_Entity_situs_display"),
    "48121": _County(
        "Denton", DENTON_URL,
        "pid,pYear,stateCodes,situs_street_address,imprvActualYearBuilt,imprvMainArea",
        "Denton Central Appraisal District roll, via Denton County GIS (keyless)",
        _read_denton, "situs_street_address"),
    "48141": _County(
        "El Paso", EL_PASO_URL,
        "PROP_ID,PROP_VAL_Y,STATE_CD,SITUS_NUM,SITUS_STRE,SITUS_DIR,SITUS_UNIT,YR_BLT",
        "El Paso Central Appraisal District roll, via City of El Paso GIS (keyless)",
        _read_el_paso, "SITUS_STRE", number_field="SITUS_NUM"),
    "48061": _County(
        "Cameron", CAMERON_URL,
        "prop_id,pyear,exportdt,statecd,situsno,sitpfx,sitstr,sitsfx,yrbuilt",
        "Cameron Appraisal District roll, via City of Brownsville GIS (keyless)",
        _read_cameron, "sitstr", number_field="situsno"),
    "48491": _County(
        "Williamson", WILLIAMSON_URL,
        "parcelid,propertyid,siteaddress,unit",
        "Williamson Central Appraisal District open data (keyless)",
        _read_williamson, "siteaddress", fetch=_williamson_rows),
}
COUNTY_FIPS = frozenset(COUNTIES)


# ── choosing the parcel ────────────────────────────────────────────────────────


def _arcgis_rows(county: _County, lat: float, lon: float, distance_m: float,
                 *, deadline: float, number: str | None = None) -> list[dict]:
    """The rows of a county served as one ArcGIS layer, the common case."""
    return _shared.arcgis_parcels(
        county.url, lat, lon, county.fields, distance_m, deadline=deadline,
        read_slice=READ_SLICE_S, where=county.same_number(number) if number else None)


def _rows(county: _County, lat: float, lon: float, distance_m: float,
          *, deadline: float, number: str | None = None) -> list[dict]:
    """Normalized candidate rows at (or within ``distance_m`` of) a point.

    Column names are upper-cased first: the Houston services answer
    ``TAX_YEAR`` and ``Year_Built`` for columns their own metadata spells
    ``Tax_Year`` and ``YEAR_BUILT``. Rows that are records of nothing (no
    identifier, a personal-property account) are dropped, and a row repeated
    verbatim — one parcel per polygon part — is kept once.
    """
    fetch = county.fetch or _arcgis_rows
    raw = fetch(county, lat, lon, distance_m, deadline=deadline, number=number)
    out, seen = [], set()
    for row in raw:
        cand = county.read({str(k).upper(): v for k, v in row.items()})
        if cand is None:
            continue
        key = tuple(sorted(cand.items()))
        if key not in seen:
            seen.add(key)
            out.append(cand)
    return out


def _collapse(cands: list[dict]) -> list[dict]:
    """One candidate per street address where every row at it agrees.

    A condominium stack is many unit rows on one footprint (115 at 2200 Willowick
    Rd, Houston), and Dallas files a condominium's units as rows on the complex's
    polygon. Offered raw they are many candidates, and ``select_parcel`` refuses —
    so no condominium would ever answer. Picking one unit would be the confident
    guess this layer exists to refuse. So rows sharing a street address (unit set
    aside) are offered as ONE candidate only when they agree on the year built
    and every one of them is somebody's home; that candidate carries the year and
    nothing else — no floor area, no stories, since those belong to one unit, and
    no parcel id unless all rows share it. Rows that disagree (6108 Abrams Rd,
    Dallas: units of 1984, 2005, 2019 and 2021) are offered as they are, and the
    ambiguity is refused downstream, exactly as before.
    """
    groups: dict = {}
    order = []
    for c in cands:
        key = address_key(c["address"])
        key = key if key is not None else ("pid", c["pid"])
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(c)
    out = []
    for key in order:
        rows = groups[key]
        years = {r["year"] for r in rows}
        if (len(rows) == 1 or len(years) != 1 or None in years
                or any(r["reading"] == NOT_A_HOME for r in rows)):
            out.extend(rows)
            continue
        pids = {r["pid"] for r in rows}
        vintages = {r["vintage"] for r in rows}
        out.append({
            "pid": pids.pop() if len(pids) == 1 else None,
            "address": rows[0]["address"], "unit": None, "reading": CONDO,
            "year": years.pop(), "sqft": None, "stories": None,
            "vintage": vintages.pop() if len(vintages) == 1 else None,
            "stack": len(rows),
        })
    return out


def _same_unit(cand: dict, unit: str) -> bool:
    own = cand.get("unit")
    return own is not None and own.lower().lstrip("#") == unit.lower().lstrip("#")


def _for_unit(rows: list[dict], unit: str) -> list[dict]:
    """The rows that could be the typed unit's.

    A row naming a DIFFERENT unit cannot be. And where some row names the typed
    unit itself, the rows naming no unit at all — a condominium's master record,
    its common element — are not the reader's either: Fort Bend files "2710
    Grants Lake Blvd #M1" beside two unit-less records at 2710 Grants Lake Blvd,
    and offered together the three were refused.
    """
    if any(_same_unit(r, unit) for r in rows):
        return [r for r in rows if _same_unit(r, unit)]
    return [r for r in rows if r.get("unit") is None]


#: How far the same-address search looks. A shared address sits on one road; a
#: kilometer covers the farm in the case that taught this (see
#: ``_shares_its_address``) with room to spare, and because the search asks only
#: for rows carrying the same house number its answer stays a handful of rows.
TWIN_RADIUS_M = 1000


def _parcel_at(county: _County, lat: float, lon: float, address: str | None,
               *, deadline: float | None = None) -> dict | None:
    """The candidate this point and address name, or None.

    The choice is ``_shared.select_parcel``'s; see it for why the nearest parcel
    is never taken. Before it sees the rows, two things happen in ``fetch`` —
    both the sanctioned "drop what cannot be an answer" shape, so both can only
    turn "ambiguous" into "one", never admit a parcel the address check would not:

    * a reader who typed a unit cannot live in a row naming a different unit
      (``_for_unit``), and
    * agreeing rows at one street address become one candidate (``_collapse``).

    After it, one check of our own: the address must not belong to a second
    parcel nearby (``_shares_its_address``).
    """
    deadline = deadline_from(deadline, LOOKUP_TIMEOUT)
    unit = unit_of(address)

    def prepared(rows):
        return _collapse(_for_unit(rows, unit) if unit else rows)

    fetched: dict[float, list[dict]] = {}

    def fetch(distance_m):
        if distance_m not in fetched:
            fetched[distance_m] = prepared(
                _rows(county, lat, lon, distance_m, deadline=deadline))
        return fetched[distance_m]

    chosen = select_parcel(fetch, address, lambda c: c["address"])
    if chosen is None or not address:
        return chosen
    number = address_key(address)[0]      # digits only: address_key insists
    same_number = prepared(_rows(county, lat, lon, TWIN_RADIUS_M, deadline=deadline,
                                 number=number))
    return _shares_its_address(chosen, address, same_number)


def _shares_its_address(chosen: dict, address: str,
                        same_number: list[dict]) -> dict | None:
    """``chosen``, unless another parcel within a kilometer has its address.

    Containment confirmed by address is ``select_parcel``'s strongest answer, and
    in Texas it is not enough on its own, because an appraisal district can give
    one street address to several accounts. In the verification run, typed
    "16417 Hubenak Rd, Needville" landed inside an 86-acre farm whose 1930
    farmhouse carries that address — and so does the 1-acre homesite cut out of
    it, a 1984 house, which was the home sampled. Containment named the
    farmhouse, and the adapter reported 1930 for a 1984 house. The homesite was
    more than 80 m from the point, so the ordinary buffer could not see it.

    So once a parcel is chosen, the service is asked for every row carrying the
    same house number within ``TWIN_RADIUS_M`` (an attribute filter on the
    address column, so the answer is a handful of rows), read with the same rules
    (unit filter, agreeing rows collapsed), and the address must name exactly one
    candidate among them. Two or more is the ambiguity ``select_parcel`` refuses
    in its buffer, and is refused here. One that is a collapsed group — the chosen
    row and a twin that agree on the year — is answered as the group: the year,
    and no floor area, since which of the two the reader lives in is unknown.

    It costs one more request on every confirmed lookup (measured median about
    0.1 s; see "Timing").
    """
    hits = [c for c in same_number if _shared.same_address(address, c["address"])]
    if len(hits) != 1:
        # Two or more: shared. None: the search did not even find the chosen
        # parcel, so it has not looked, and its silence is not evidence.
        return None
    if hits[0].get("stack"):
        return hits[0]
    # Exactly one, and it must be the parcel already chosen. Anything else means
    # another parcel has the address and this one is missing from the search.
    return chosen if hits[0]["pid"] == chosen["pid"] else None


# ── the record ─────────────────────────────────────────────────────────────────


@lru_cache(maxsize=4096)
def _lookup_cached(lat: float, lon: float, address: str | None,
                   county_fips: str | None, _bucket: int = 0) -> AssessorRecord | None:
    county = COUNTIES.get(county_fips or "")
    if county is None:
        return None
    cand = _parcel_at(county, lat, lon, address)
    if cand is None or cand["reading"] == NOT_A_HOME:
        return None
    year, sqft, stories = cand["year"], cand["sqft"], cand["stories"]
    if year is None and sqft is None and stories is None:
        return None
    return AssessorRecord(
        source=county.source,
        data_vintage=cand["vintage"] or DATA_VINTAGE,
        parcel_id=cand["pid"],
        year_built=year,
        sqft=sqft,
        stories=stories,
        # None of these services carries an exterior wall, foundation or condition
        # column in a vocabulary the label can read; see the module docstring.
    )


def url_for(county_fips: str) -> str | None:
    """The parcel layer that answers for this county, or None if none does — so a
    dropped lookup is named after the county's own publisher, not another's."""
    county = COUNTIES.get(county_fips)
    return county.url if county else None


def lookup(lat: float, lon: float, address: str | None = None,
           county_fips: str | None = None) -> AssessorRecord | None:
    """What the county appraisal district says is standing at this point, or None.

    ``address`` is the geocoder's matched address, used only to confirm the
    parcel. ``county_fips`` is the county the registry routed on, which it passes
    to adapters that accept it; it picks the county's service. Without one the
    lookup answers None rather than guess which of seven services to ask.

    Fails open on everything. The caller then keeps whatever it had, which is the
    behavior that existed before this adapter.
    """
    try:
        fips = str(county_fips).strip().zfill(5) if county_fips else None
        return _lookup_cached(round(float(lat), 5), round(float(lon), 5), address,
                              fips, cache_bucket())
    except Exception as exc:  # noqa: BLE001
        log.debug("Texas assessor lookup failed at %s,%s: %s", lat, lon, exc)
        return None
