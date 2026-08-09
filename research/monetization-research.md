# Monetization research

**Status:** research / recommendation. The only code shipped alongside it is caller
identity (`src/housing_label/entitlements.py`), which every option below needs and none
of which commits to a price.

Research date 2026-08-09. Sources are 2024–2026 where available. Where a number could
not be verified it is recorded as unverified rather than rounded into a fact — a large
share of the "pricing" pages for this sector are AI-generated SEO filler, and laundering
one into a plan is how a business gets built on a number nobody ever charged.

---

## Why now

v0.2.0 relicensed to PolyForm Shield 1.0.0 ("to stop someone standing up a competing
housing-label service"), v0.2.1–0.2.2 built `housing-batch` into something that scores a
book of parcels, and `TRADEMARKS.md` asserted the marks. The legal and technical
scaffolding for a business now exists. What did not exist, until the change this file
accompanies, is any way to tell two callers apart.

The gap is not the product. It is that nothing in the repo names a customer, a price, or
a term.

---

## 1. The nearest comparable argues against selling the score

**Walk Score** is the closest structural analogue that has ever existed: a *score*, in US
residential, sold as an API plus a badge.

- Free below published thresholds (5,000 API calls/day, 1,000 widget views/day), Premium
  "starting at $115/mo" — priced on **the licensee's monthly unique visitors**, not on
  calls served. Enterprise is triggered by multiple domains, subscription or fee-based
  services, and offline use.
- At exit: **10 employees, 20 million scores served per day, 30,000 partner sites.**
- Acquired by Redfin, closed 2014-10-22. Per Redfin's S-1: **$5,500K cash** (plus $282K
  adjustments) and **1,333,424 shares valued at $8,520K** — roughly **$14M**.

The reading that matters: with near-total category ubiquity, a score business was worth
~$14M to the strategic buyer who needed it. The value accrued from *distribution*, not
from per-call revenue. The free tier was the product.

**First Street** ran the same play a decade later — Flood Factor on Realtor.com
(2020-08-26), Redfin across all listings (2021-02-19), Wind Factor (2023-07-31), NAR's
RPR — and only then converted default-distribution into enterprise climate-risk licensing
to lenders, insurers and asset owners. Philanthropic capital paid for the free layer that
made it the standard.

Neither monetized the label first. Both monetized the position the free label bought.

## 2. Four ways to monetize a label; one is available to us

| Model | Who pays | What the evidence says | Verdict |
|---|---|---|---|
| **Certification** — the rated party pays to be rated | Owner / seller | LEED: $1,350 registration (USGBC member) / $1,700 non-member, plus ~$0.056–0.076/sf review. WELL: $3,000 enrollment + $0.16/sf, floor $6,500, cap $98,000. Fitwel: $500 registration, $6,500–13,000 scorecards. BBB accreditation: $300–$4,000+/yr | **Reject** |
| **Free label, paid verification** | Owner, to a licensed assessor | ENERGY STAR certification costs **$0** from EPA; the money is third-party PE/RA verification (~$1,500 typical, $2,000–5,000 range). DOE Home Energy Score charges nothing and licenses assessors — ~27 partner organizations, ~400 assessors, 250,000+ scores; market price $150–300 | **Not yet** |
| **Free to display, paid to redistribute** | Platforms, at scale | Walk Score above. Morningstar: **~75% of revenue from subscription licenses**, ~$8,000/yr for a single fund's use of the star rating in shareholder communications, scaled by fund-family size — and **explicitly free in advertising** | **This one** |
| **Issuer-pays ratings** | The rated party | US municipal issuers paid **somewhat more than $500 million** for credit ratings in 2014 (Joffe, Othering & Belonging Institute). Moody's ratings segment runs a **52.2% operating margin** | **Reject** |

### Why the certification model is rejected even though it pays best

1. **Pay-to-play is not hypothetical.** An ABC News investigation found small businesses
   with C/C− BBB ratings upgraded to **A+ within a single day of paying**, and fabricated
   companies given A ratings after paying dues, while non-paying well-known firms got Fs.
   Connecticut's AG announced a corrective agreement in 2020.
2. **Voluntary labels get applied only where flattering.** Nutri-Score bans cherry-picking
   by rule for exactly this reason. "Get your house scored" has the problem on day one.
3. **Ratings shopping** is structural to issuer-pays: the rated party picks the rater.
4. **Fair housing — the risk none of the comparables carry.** An address-level composite
   grade, incorporating neighbourhood and demographically-correlated inputs, used by
   lenders, insurers or landlords, is a disparate-impact surface. GreatSchools' retreat to
   three coarse "bands" (sold as a separate licensing tier from full ratings) and Redfin's
   published methodology are both partly defensive.

Point 4 is the one to design around rather than disclaim. The engine already holds Health
and Socioeconomic out of both headline axes (`simulate/dimensions.py`, `CONTEXT_ONLY`, with
its redlining note). That instinct was right, and a business model that put the rated party
in the payer's seat would undo it from the outside. `TRADEMARKS.md` reserves "offering a
certification bearing the marks"; the recommendation is that the reservation stays unused.

## 3. Pricing anchors

**Published and verified:**

| Vendor | Price | Unit |
|---|---|---|
| HouseCanary | $190 / $790 / $1,990 per year (Basic / Pro / Teams-of-10); API $0.30–0.50/call basic, $2.50–4.00/call premium; valuation reports $9–12 | Seat-year + metered |
| Geocodio | $1 per 1,000 lookups PAYG above 2,500/day free; 350k credits $325/mo; dedicated instance from $1,350/mo; +$250/user/mo | Per lookup — **and each appended data category counts as one more lookup** |
| Walk Score Professional | Free tier; Premium from $115/mo; Enterprise custom | Licensee's monthly unique visitors |
| Regrid | $400/county (shapefile, all Premium attributes + geometry); $200/county (spreadsheet) | Per county, one-time |
| PropertyRadar | $119 / $249 / $599 per month (1 / 3 / 10 users) | Seat-month |
| Cotality (CoreLogic) Trestle | Brokers $30 or $100/mo per connection; tech providers $100–250/mo | Per MLS connection |
| MLS data access (general) | $50–500/mo per connection; MLS PIN $525/mo flat; OneKey $250/mo + $20/license | Per MLS, per month |
| Estated | $0.25/call essential, $0.50/call enhanced | Per call — *2019 pricing, pre-ATTOM; a historical floor* |

**Contact-sales, no usable public number:** ATTOM, CoreLogic/Cotality, First Street,
ClimateCheck, GreatSchools, Precisely, Regrid's API/subscription tiers, Walk Score
Enterprise, HouseCanary Enterprise minimums, BREEAM US fees, HERS market rates. Figures
circulating for ATTOM ("$95/mo entry", "~$500/mo for a few thousand calls") trace to
AI-generated SEO blogs with no verifiable sourcing. Do not plan against them.

Geocodio is the operational template worth copying, and not only for the price: **each
appended data category counts as an extra lookup.** That is exactly the shape a
thirteen-dimension score wants, and it is why `_meter` in `api.py` charges scoring passes
rather than requests.

## 4. Who has budget

**Tier 1 — real budget, real procurement, buys data today.** Mortgage lenders and
underwriters (per-loan production cost **$11,102**, MBA Q4 2025; a $5–50 per-loan data add
is procurable, but needs investor/GSE acceptance to matter, and SOC 2). Insurance carriers
and MGAs — highest price tolerance, and they will ask for backtested loss correlation we
cannot yet produce. SFR institutional operators (mega-operators hold ~3.0% of the 15.1M
single-family rental properties, Urban Institute 2023): few buyers, large deals, they have
data teams, and `housing-batch` is already the right shape.

**Tier 2 — buys, at low price points.** Brokerages and agents, where the market clears at
$99–599/mo and nobody pays per address. MLSs: RFP, board approval, 6–18 months, then
near-permanent, landing around $10–50K/yr — slow, but it is the Walk Score distribution
path. Appraisers: the national average appraisal is **$357** (Angi, 2025), so anything
over ~$5/report is a hard sell. Relocation firms are a genuine, underserved fit.

**Tier 3 — interested, structurally cannot pay well.** Municipalities (see §5). Housing
nonprofits and CDFIs, who will ask for it free and cite it — good for credibility.
Academic researchers, who will pay $0–5,000 once for a bulk file — good for the
outcome validation Tier 1 will eventually demand.

## 5. The fiscal ratio is built; the buyer is not who you would guess

`fiscal_ratio` (`enrich/infrastructure.py:73-74`), `fiscal_rating()` (`:451`) and the
per-acre productivity lens (`simulate/house.py:2776-2816` → `revenue_per_acre`,
`cost_per_acre`, `net_fiscal_per_acre`) all ship today, nationally calibrated. So the
question is only who pays for them.

**Urban3** is the anchor for the obvious answer: 160+ communities across 35 states, plus
NZ/Canada/Australia, and one verifiable price — Rapid City, SD (pop. ~75,000) approved a
professional services agreement with Urban3, LLC **not to exceed $226,227** in 2024.
TischlerBise (1,100+ impact fee studies, 1,000+ fiscal impact analyses) bills hourly:
Gwinnett County's contract lists **Principal $250–375/hr, Analyst $170–195/hr**.

But 160 communities over ~15 years is roughly ten engagements a year. That is a
consultancy, not a scaling business, and Urban3 has had a fifteen-year head start without
productizing it. The reason is structural and worth stating because it constrains us
identically: the numerator (assessed value) is nationally assemblable, the denominator
(allocated municipal service cost per parcel) needs jurisdiction-specific budget data that
does not normalize. An automated score yields defensible *intra*-jurisdictional rankings
and indefensible cross-jurisdiction ones. That limitation is already the published
position — `docs/methodology.html:264` says to treat the score as a rank, not a verdict —
so the product must inherit it rather than quietly outgrow it.

Meanwhile the free substitute is well funded: the Lincoln Institute's Fiscally
Standardized Cities database covers 212 central cities and 115 revenue/expenditure/debt
categories, 1977–2023, alongside a Municipal Fiscal Health Dashboard, all free. And the
procurement reality is a $1,788 one-year OpenGov trial against six-figure consulting
lines. ClearGov (2,000+ local governments) and OpenGov (1,000+) are budgeting and
transparency platforms; neither computes per-parcel value-per-acre.

**So the commercially interesting move is not selling this to cities.** It is selling
*parcel-level fiscal fragility as an underwriting signal*: a parcel in a structurally
insolvent service area carries future property-tax-increase and service-decline risk over
a 30-year mortgage or a 10-year SFR hold. That is a civic metric reframed as a risk input
for the Tier 1 buyers who have budget — the First Street move exactly — and it uses
`fiscal_ratio` and `net_fiscal_per_acre` precisely as they already are.

## 6. Licensing reality check — including one risk that turned out not to apply

**The ODbL question, and its answer.** The general risk is real and worth recording: the
ODbL distinguishes a *Produced Work* (any licence, but recipients may request the
derivative database under ODbL) from a *Derivative Database* (full share-alike). The OSMF
guideline test is whether "the published result of your project is intended for the
extraction of the original data". A rendered label image is defensibly a Produced Work; a
JSON API of numeric subscores keyed to addresses — and much more so `housing-batch` CSV
output — looks like a database. If OSM fed any subscore, a plausible reading would force
the whole score database to ODbL, and anyone could then compete with us using it. That
would gut a PolyForm Shield strategy.

**It does not apply.** `grep -riE "openstreetmap|osm|photon|overpass|nominatim"` across
`src/` and `scripts/` returns three files, none in the scoring path:

- `data/walkability.py:35` — a comment naming an in-house OSM amenity score as a *future*
  option. Walkability actually uses the EPA National Walkability Index, chosen because it
  is public domain and storable where the Walk Score API's terms prohibit caching
  (`data/walkability.py:5`).
- `config.py:56-58` and `api.py` — Photon and Geoapify power `/suggest` autocomplete only.

Every scoring input is a US federal public-domain work, and `data/home_value.py:10`
explicitly declines a commercial AVM. **The score database is clean and resellable.** That
is the most valuable single finding here, and it is a consequence of data-sourcing
decisions taken years before there was a business reason for them.

**The residual exposure, narrowly.** `/suggest` proxies Photon (OSM/ODbL), Geoapify and
Google Places — all three restrict caching or storage. A paid autocomplete tier, or
persisting suggest results, is the one place third-party terms bite. `geocode_cache.py` is
unaffected: it caches the Census geocoder, which is public domain.

**Census / ACS.** Public domain and commercial use is contemplated, with two obligations:
carry "This product uses the Census Bureau Data API but is not endorsed or certified by
the Census Bureau", and do not use the Census name to imply endorsement. Also: content may
not be modified and still represented as Census-sourced — which bears on how a derived
subscore is attributed.

**FEMA NFHL.** Public domain, but the disclaimers matter: a derived flood subscore must
not be presented as a flood zone determination, which is a regulated activity. Needs
counsel before any flood claim is sold.

**County assessor data** is the patchwork that keeps ATTOM and CoreLogic in business.
Maricopa County requires a formal Commercial Purpose Public Record Request and bars
commercial resale without express written consent; assessors commonly assert IP in the
format, presentation and compilation even where the underlying facts are public record.
3,000+ counties, each with its own terms. If parcel attributes are ever needed, license
from Regrid at $200–400/county rather than scraping.

**Third-party scores are not recomputable-and-resellable.** Walk Score, GreatSchools,
First Street and ClimateCheck are licensed IP, and Walk Score's Enterprise tier is
triggered by exactly "subscription or fee-based services". Zillow/Bridge terms bar sharing
data in raw, aggregate **or derivative** form, and the Public Records API is invite-only.
The project's existing refusal to depend on any of them is what keeps the score sellable.

**Our own position.** PolyForm Shield is not OSI-approved: no "open source" claim, no
Debian/Fedora, and exclusion from procurement lists that require an OSI licence. The
trademark is the stronger asset, because it is what enforces a display/syndication licence
regardless of what the code licence says — that is the Morningstar and Nutri-Score
mechanism. Worth noting that m3o/Micro, an early Shield adopter, is defunct: the licence
did not save it.

## 7. Business models for a solo operator, and how they fail

**What works, with evidence:** developer-first metered API with published prices
(Geocodio — small team, no public VC, self-serve, transparent, genuinely useful free
tier); free ubiquity into strategic acquisition (Walk Score, ~$14M); philanthropy-funded
free consumer layer into enterprise licensing (First Street, 3–5 years and grant capital);
bespoke consulting off a public methodology (Urban3 $226K, TischlerBise $250–375/hr) —
which does not scale but is cash-positive from month one and funds the product.

**Failure modes, specifically:**

- **The relicense removed a real asset to protect a theoretical one.** For a large project
  the risk is a fork (HashiCorp→OpenTofu, Elastic→OpenSearch, Redis→Valkey). For a solo
  project the failure is quieter and more likely: nobody forks you, they just stop
  contributing, stop starring, stop writing tutorials — and the free distribution that was
  the only advantage over ATTOM's balance sheet evaporates, against competitors who were
  never going to fork you anyway. This is not an argument to reverse it. It *is* the
  argument that the free tier must now be deliberately generous, because generosity is no
  longer produced for free by the licence.
- **"Contact sales" without a sales team.** Every opaque competitor in §3 has one. A
  quote-based offer loses to HouseCanary's published $790/yr on velocity alone.
- **Selling to municipalities as SaaS.** RFP cycles, council presentations, $1,788 trial
  budgets, and the Lincoln Institute giving away the adjacent thing.
- **Validation debt.** Insurers and lenders will ask for backtested loss correlation. A
  score with no outcome validation sells to agents at $99/mo and to nobody at $50K/yr.
  This is the strongest argument for courting the academic users in Tier 3 early: they are
  the cheapest route to the citation an insurer will ask for.

---

## Recommendation

**Price it like Geocodio, distribute it like Walk Score, validate it like First Street,
fund the first year like Urban3.**

1. **The label is monetizable as a right to *syndicate*, never a right to be *rated*.**
   Free embeddable badge with attribution, capped by volume; paid licence for multi-domain,
   paywalled, offline or systematic use, priced on the licensee's traffic or portfolio
   rather than our compute. Free in advertising, licensed in operational use — Morningstar's
   split, deliberately copied. Trademark enforces this, not the code licence.
2. **Publish prices.**
3. **Meter per address scored, with the per-dimension subscores as the volume lever.**
4. **Batch/portfolio is the high-value SKU.** `batch.py` already is the product; it needs
   a licence and a price, not features.
5. **Do not build issuer-pays certification.** The Home Energy Score model only works
   because municipal mandates create demand and DOE absorbs the credibility cost. Without a
   mandate you get BBB's incentive structure and none of BBB's brand.

## Shipped alongside this memo

`src/housing_label/entitlements.py` and the `_caller` / `_meter` path in `api.py`: API
keys, per-caller rate-limit buckets, a daily scoring allowance, and `GET /usage`. It is the
narrow waist every option above needs — the free badge tier cannot be "free below N views
a day" until N is countable — and it commits to no price. Anonymous access stays unmetered
by default so a self-hosted instance is unchanged.

Not built, deliberately: the badge/SVG endpoint (the next step, and the one that actually
generates distribution), payments, a pricing page, and any durable usage ledger.

## Open, and not settleable in a commit

- **Fair-housing counsel** on which buyer segments an address-level composite grade can be
  sold to. This constrains §4 more than any pricing decision does.
- **Terms of service** for the hosted API before money changes hands.
- **A USPTO filing.** `TRADEMARKS.md:53` still says common-law ™, and PR #275's own
  closing recommendation — "trademark is your strongest lever, and it's the one that works
  retroactively" — is the load-bearing assumption under recommendation 1.
- **Outcome validation.** Nothing in §4 Tier 1 closes without it.
