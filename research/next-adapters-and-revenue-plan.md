# Next adapters, how the project makes money, and what to do next

**Status:** research / recommendation. No code changes accompany it.

Research date 2026-09-25. It builds on two earlier memos and does not repeat them:
[`monetization-research.md`](monetization-research.md) (2026-08-09) covers comparables,
pricing anchors, buyer segments and licensing, and
[`parcel-level-data-research.md`](parcel-level-data-research.md) covers the national
parcel-data landscape. This memo answers three narrower questions against the repo as it
stands at v0.2.15:

1. Which assessor adapters should come next, in what order?
2. Given what has shipped since August, which revenue lines are open now?
3. What is the ordered list of next steps?

Every endpoint named in §1 was queried live from this environment on 2026-09-25. "Verified"
means a point query returned a populated year built; it does not mean the terms of use have
been cleared (see §1.3). Housing-unit counts are approximate ACS figures, rounded, and are
there to rank effort, not to quote.

---

## Where things stand

Shipped since the monetization memo:

- **The embeddable badge** (`badge.py`, `GET /badge`, `GET /label.svg`). The memo named it
  "the next step, and the one that actually generates distribution". It exists now.
- **Four assessor adapters** behind `ASSESSOR_ADAPTERS`: Cook County IL, Washington DC
  (including condos), Florida statewide (67 counties), Connecticut statewide (169 towns).
  Together they cover roughly **14M homes, about 10% of US housing**.
- **A measured accuracy harness** (`scripts/measure_accuracy.py`,
  `research/accuracy/results.json`). With the adapter on, year built within 10 years goes
  from 39.7% to 77.8% in Cook and from 29.2% to 85.6% in DC. Construction-type exact match
  goes from 45.2% to 87.8% in Cook. That kind of evidence is what a paying buyer asks for.

Still missing, from the memo's own list: payments, a pricing page, a durable usage ledger
(`entitlements.py` keeps usage in memory), terms of service, a USPTO filing, fair-housing
counsel and outcome validation.

**The adapters were off in production until this change.** Until `ASSESSOR_ADAPTERS` was
set for the hosted API, none of the accuracy gain reached a user. This PR sets it in
`render.yaml`, after measuring the cost: about +0.7 s per label in Cook, DC and CT, about
+3 s in Florida, and nothing elsewhere.

---

## 1. Next assessor adapters

### 1.1 The screening test

`parcel-level-data-research.md` §4.1 sets the bar: the jurisdiction must publish a
characteristics record, keyed to the parcel, that carries at least a year built. Parcel
geometry alone does not count. Below that bar, the priorities follow what the existing
adapters taught:

- **One request beats two.** Florida's single layer carries both the parcel shape and the
  building facts, which makes it the cheapest adapter in the registry.
- **Statewide beats county.** One module for millions of homes.
- **The condo trap is general.** Wherever the parcel is the building, a parcel's total floor
  area and floor count describe the tower, not the unit. `fl.py`'s rule of reporting area
  only when the parcel holds one home in one building has to be carried into every new
  adapter.

### 1.2 Ranked candidates (all keyless ArcGIS REST, Socrata or Carto; verified live)

| # | Jurisdiction | Endpoint | Homes (≈) | Fields beyond year built | Shape | Watch-outs |
|---|---|---|---|---|---|---|
| 1 | **Massachusetts** (statewide, MassGIS L3) | `services1.arcgis.com/hGdibHYSPO59RG1h/.../Massachusetts_Property_Tax_Parcels/FeatureServer/0` | 3.0M | `RES_AREA`, `STORIES`, `STYLE`, `UNITS`, `FY` | One request, like Florida | `RES_AREA` is null on multi-unit records; condo units appear as stacked records on one footprint, so DC-style unit matching is needed. `FY` gives the vintage. |
| 2 | **North Carolina** (statewide, NC OneMap, all 100 counties) | `services.nconemap.gov/secure/rest/services/NC1Map_Parcels/FeatureServer/1` | 4.9M | `structyear`, `struct` (Y/N), `parusedesc` | One request | Year built only, no floor area or materials. **`structyear = 0` means missing**; map it to None, never to year 0. Fill varies by county, so measure before claiming coverage. |
| 3 | **Utah** (UGRC LIR, 29 per-county layers) | `services1.arcgis.com/99lidPhWCzftIe9K/.../Parcels_<County>_LIR/FeatureServer/0` | 1.2M | `BUILT_YR`, `EFFBUILT_YR`, `BLDG_SQFT`, `FLOORS_CNT`, `CONST_MATERIAL`, `CURRENT_ASOF` | One request; 29 URLs from one template | Condo trap confirmed live: Salt Lake condos report `FLOORS_CNT = 27`, the tower's floor count. `CONST_MATERIAL` is coded (e.g. `MT`) and needs a mapping table; translate only unambiguous codes. `EFFBUILT_YR` is a useful durability input the other adapters lack. |
| 4 | **Los Angeles County** | `public.gis.lacounty.gov/public/rest/services/LACounty_Cache/LACounty_Parcel/MapServer/0` | 3.6M | `YearBuilt1..5`, `EffectiveYear1..5`, `SQFTmain1..5`, `Units1..5`, `QualityClass1..5`, `Roll_Year` | One request | Up to five buildings per parcel in numbered columns. Pick the residential one, or return nothing when it is ambiguous. `YearBuilt1` is a string. The largest single county in the US. |
| 5 | **New York City** (PLUTO, Socrata `64uk-42ks`) | `data.cityofnewyork.us/resource/64uk-42ks.json` | 3.7M | `yearbuilt`, `yearalter1/2`, `numfloors`, `bldgarea`, `resarea`, `unitsres`, `bsmtcode`, `bldgclass` | Needs a BBL: point-to-lot via MapPLUTO, then the row | `bldgarea` is lot-level, so apply the one-home rule to `unitsres`. PLUTO carries `ownername`; drop it at ingest as the base contract requires. |
| 6 | **New York State** (NYS ITS public parcels) | `gisservices.its.ny.gov/arcgis/rest/services/NYS_Tax_Parcels_Public/MapServer/1` | ~3–5M (opt-in counties only) | `YR_BLT`, `SQFT_LIVING`, `BLDG_STYLE_DESC`, **`HEAT_TYPE_DESC`, `FUEL_TYPE_DESC`, `SEWER_DESC`, `WATER_DESC`** | One request | Only counties that opted in to public release are present, so the `COUNTY_FIPS` list must be taken from the data, not the state. It is the only candidate with heating fuel, sewer and water supply, which feed Energy, Environmental and Water Quality directly. NYC is not in it (see #5). Albany's sample had `SQFT_LIVING` null. |
| 7 | **Philadelphia** (OPA, Carto SQL) | `phl.carto.com/api/v2/sql` on `opa_properties_public` | 0.7M | `year_built`, `total_livable_area`, `number_stories`, `exterior_condition`, `interior_condition` | Two hops (point → parcel → OPA row), or one SQL query with `ST_Contains` | Condition is a 1–7 code; map it the way DC's CNDTN is mapped. Small, but full condition data. |
| 8 | **Maryland** (MDP statewide CAMA) | `mdgeodata.md.gov/imap/rest/services/PlanningCadastre/MD_ComputerAssistedMassAppraisal/MapServer/0,1` | 2.6M | `BL_YEARBLT`, `BL_ENCSQFT`, `BL_BLDSTYL`, `BL_BLDGRAD`, `CM_BLDUNTS` | Point layers keyed on `ACCTID`; needs a parcel→account hop via `MD_ParcelBoundaries` | `geodata.md.gov` returned a maintenance page during this check; `mdgeodata.md.gov` answered. The CAMA layers have `minScale 10000`, so check that attribute queries are not scale-gated. |

**Adding all eight takes coverage from about 14M to about 37M homes, roughly a quarter of
US housing.** For comparison, the whole existing registry covers about 14M.

Suggested build order: **MA → NC → Utah → LA → NYC → NYS → Philadelphia → Maryland**.
MA, NC and Utah are one-request statewide layers like Florida's, so each is about a
one-PR job on top of `_shared.arcgis_parcels`. LA is a single county but the largest. NYC
and NYS are worth their extra work: NYC for its density, NYS because it is the only source
with fuel, sewer and water fields.

### 1.3 Excluded, and why

- **Maricopa County, AZ.** Requires a Commercial Purpose Public Record Request and bars
  commercial resale without written consent (monetization memo §6).
- **Wisconsin V11 statewide.** Carries assessment values and zoning but no year built, so
  it fails the screening test.
- **El Paso County / Colorado Springs, CO.** Already ruled out in
  `parcel-level-data-research.md` §4.1.
- **Texas CADs** (Harris, Dallas, Tarrant, Bexar, Travis). The richest data in the country
  (exterior wall, foundation, HVAC), but published as bulk tab-delimited exports with no
  point-query API. They need a cached-extract adapter, which is a different pattern from
  the four that exist. Worth doing after the eight above, as its own design decision.
- **Washington State counties.** RCW 42.56.070(8) restricts commercial use of lists of
  individuals. Dropping owner fields probably clears it, but it needs a read of the statute
  first.

**Before each adapter merges:** read that jurisdiction's terms of use and record the
verdict in the module docstring, as `base.py` does for Cook. Querying and caching live
without bundling is the posture every existing adapter takes, and it is what keeps the
score database resellable (monetization memo §6).

### 1.4 Distribution adapters (the other kind)

Assessor adapters make the label more accurate. Distribution adapters put it in front of
more people, and per the monetization memo, distribution is where the value comes from.
Each is small because `/badge` and `/label.svg` already exist:

- **A WordPress / Squarespace embed block** that wraps `EMBED_SNIPPET`. Most agent and
  small-brokerage sites run on these platforms.
- **A RESO Web API field mapping**, so an MLS vendor can show the two badge grades as
  listing fields. This is the Walk Score and First Street path, with a 6–18-month sales
  cycle, so start the conversation early.
- **A Zapier / Make action** ("score this address") on the existing `/label` endpoint, for
  property managers and relocation firms who will not write code.
- **A Google Sheets custom function** (`=HOUSINGLABEL(A2)`). Brokers and small SFR
  investors work in spreadsheets, and it meters naturally through API keys.

---

## 2. Ways to actually make money

The monetization memo's conclusion stands: **sell the right to syndicate the label, never
the right to be rated.** Below, that conclusion is turned into specific offers, ordered by
how soon each could bring in cash. The prices are proposals anchored on the memo's
verified comparables (§3 there). They are not market-tested.

| # | Offer | Buyer | Proposed shape | What it still needs | Time to first dollar |
|---|---|---|---|---|---|
| A | **Self-serve metered API** | Proptech developers, relocation firms, small SFR investors | Free tier (the existing `basic` plan's 5,000/day, or lower); then pay-as-you-go per 1,000 labels, Geocodio-style, with an **"observed" surcharge** on addresses where an assessor adapter answered | Stripe, a durable ledger, a pricing page, ToS | Weeks |
| B | **Badge syndication licence** | Brokerages, MLS vendors, listing portals, property managers | Free with attribution below a monthly unique-visitor cap; paid above it or for multiple domains, paywalled use or offline use. Priced on the licensee's traffic, as Walk Score priced. Free in advertising, licensed in operational use (the Morningstar split). | Traffic-based metering on `/badge`, a trademark filing to enforce the licence | 1–3 months |
| C | **Portfolio scoring reports** | SFR operators, CDFIs, housing nonprofits, climate-risk teams at small lenders | Per-parcel price for a scored CSV plus a written summary, run with `housing-batch`. Per-parcel pricing falls with volume. The observed share, per the accuracy harness, is shown on the report. | A report template and a data-licence agreement | Weeks (sold by hand) |
| D | **Fiscal-fragility underwriting signal** | Lenders, SFR investors, municipal-bond analysts | `fiscal_ratio` and `net_fiscal_per_acre` sold as a parcel-level forward risk for property-tax increases and service decline (monetization memo §5) | Intra-jurisdiction framing only, plus counsel review | 3–6 months |
| E | **Municipal fiscal studies (consulting)** | Cities and counties | A fixed-fee Urban3-style engagement built on the per-acre productivity lens that already ships. Urban3's verified comparable is $226K for Rapid City. | A slide template and one reference city | 1–3 months, but lumpy |
| F | **Research data licence** | Universities, think tanks | A one-time bulk file, cheap or free in exchange for a published outcome-validation study | A licence agreement and a data dictionary | Low cash; high strategic value (see step 7) |
| G | **Grants** | Climate and housing philanthropy, DOE and HUD programmes | Fund the free consumer layer, as philanthropic capital funded First Street's | An application; the accuracy page is the evidence | 3–9 months |

**Where to start:** A and C together. A is the infrastructure every other offer bills
through. C can be sold by hand this month with no new code, and every portfolio sold is a
customer-discovery conversation. B is the long-term engine but depends on the trademark and
traffic metering. D is the largest prize and needs outcome validation first.

**The adapters are the moat, so price them.** Anyone can recompute the location dimensions
from the same federal data. The observed building facts, with measured accuracy per
jurisdiction, are the part a competitor cannot rebuild quickly. That is why offer A carries
an "observed" surcharge, and why the adapter roadmap in §1 is also a revenue roadmap: each
new state increases the share of labels that can be sold at the higher rate.

**Do not build (restated from the memo):** issuer-pays certification ("get your home
rated"), and any sale of the Health or Socioeconomic context dimensions into lending,
insurance or tenant screening. Both are fair-housing exposures, and `CONTEXT_ONLY` already
keeps those two dimensions out of the headline grades for that reason.

---

## 3. Next steps, in order

Engineering and business work run in parallel. The legal items are listed first because
nothing in §2 should take money before they are done.

**Legal and business blockers (start now; mostly waiting on other people)**

1. **Fair-housing counsel.** Get a written opinion on which buyer segments may receive an
   address-level composite. It bounds offers C and D.
2. **Terms of service and a data-licence agreement** for the hosted API and bulk output.
3. **USPTO filing** for the Housing Nutrition Label mark. `TRADEMARKS.md` still asserts
   only common-law ™, and offer B depends on the trademark to enforce its licence.
4. **Five customer-discovery calls per segment** (SFR operator, CDFI, brokerage, relocation
   firm, small lender) before building anything customer-specific. Offer C doubles as the
   excuse for the calls.

**Engineering, ordered by value per effort**

1. ~~**Turn `ASSESSOR_ADAPTERS` on in production.**~~ Done in this PR (`render.yaml`). It
   takes effect when the Render blueprint is synced, or when the variable is set in the
   dashboard, because `autoDeploy` is off.
2. **Durable usage ledger plus Stripe.** `entitlements.py` explains why the in-memory
   ledger cannot bill. A managed Postgres, or SQLite on a Render disk, plus Stripe metered
   billing keyed on the existing SHA-256 key digests, closes the gap. Add the "observed"
   flag to the metered event now so offer A's surcharge needs no migration later.
3. **A pricing page on `housinglabel.dev`** with published prices ("Publish prices" is
   recommendation 2 of the monetization memo).
4. **Adapters MA, NC and Utah** (§1.2 #1–3). Each is a one-request statewide layer; about
   +9M homes combined. Extend `measure_accuracy.py` to each on landing, as was done for FL
   and CT.
5. **Traffic metering on `/badge`** (unique Referer hosts per month) so offer B's
   free-below-a-cap can be enforced. `api._anon_ident` already attributes by Referer.
6. **Adapters LA, NYC, NYS, Philadelphia and Maryland** (§1.2 #4–8).
7. **Outcome validation.** Offer the research licence (F) to one academic group, in
   exchange for a backtest of the Disaster Resilience score against FEMA NFIP claims or
   insurer loss data. Tier-1 buyers (lenders, insurers) cannot buy without it, and the
   monetization memo calls it the gap that "nothing in §4 Tier 1 closes without".
8. **One distribution adapter** from §1.4. Start with the WordPress block (smallest effort,
   largest reach among agents), then the RESO mapping once an MLS conversation starts.
9. **Texas bulk-extract adapter design.** A new pattern (a cached extract refreshed on a
   schedule, not a live query). Decide on it once 1–6 are done.

**What would change this plan:** a counsel opinion that rules out a segment; a discovery
call that turns up a buyer segment not listed here; or production latency after the switch-on
turning out worse than measured, which would push the adapter work toward cached extracts
sooner.
