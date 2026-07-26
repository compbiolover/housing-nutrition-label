/* label-core.js — the single, dependency-free renderer for the Housing
 * Nutrition Label, shared by index.html, examples.html, and label.html.
 *
 * All three pages are fed by the same live scoring API (`/label`, `/presets`);
 * this module turns one API payload into the label card markup, so there is one
 * implementation of the grade bars, the data-quality confidence channel, and
 * the lifetime "cost over a mortgage" strip. The per-dimension confidence tiers
 * and the climate score band come from the API (housing_label.confidence is the
 * Python source of truth); this file only *renders* them and rolls up the
 * composite confidence. Markup matches the #addr-result CSS in style.css.
 *
 * No build step, no framework: exposes a single global `window.LabelCore`.
 */
window.LabelCore = (function () {
  "use strict";

  // ── Grades ─────────────────────────────────────────────────────────────────
  // Chip backgrounds + their letter ink. White on the light A–D fills failed WCAG
  // AA (~1.9–2.3:1); dark ink clears it. A is green-600 so the chip never reads as
  // the brand/CTA green; F keeps white-on-red at a darker red that passes.
  var GRADE_COLORS = { A: "#16a34a", B: "#84cc16", C: "#eab308", D: "#f97316", F: "#dc2626" };
  var GRADE_INK = { A: "#0f172a", B: "#0f172a", C: "#0f172a", D: "#0f172a", F: "#ffffff" };
  function gradeFor(s) {
    if (s >= 80) return "A"; if (s >= 60) return "B"; if (s >= 40) return "C";
    if (s >= 20) return "D"; return "F";
  }
  // The grade the API sent, falling back to the score's own band. Everything that
  // carries a color for a row — the chip and the bar fill — reads from this one
  // letter, so color and letter can never disagree.
  function gradeOf(d) {
    var g = String(d.national_grade || "");
    if (g.length === 1 && "ABCDF".indexOf(g) >= 0) return g;
    return typeof d.score === "number" ? gradeFor(d.score) : "";
  }

  var WALL_LABELS = {
    frame: "wood frame", brick: "brick", "brick-frame": "brick veneer", block: "concrete block",
    icf: "ICF", sip: "SIP", stone: "stone", vinyl: "vinyl-sided frame"
  };
  var UPGRADE_LABELS = {
    solar: "solar", backup_generator: "backup generator", fire_sprinklers: "fire sprinklers",
    hurricane_straps: "hurricane straps", fortified_roof: "FORTIFIED roof",
    tornado_safe_room: "tornado safe room", seismic_retrofit: "seismic retrofit",
    flood_vents: "flood vents"
  };

  function esc(s) { var d = document.createElement("div"); d.textContent = s == null ? "" : s; return d.innerHTML; }

  // ── Plain-language "what this row measures" (one sentence per dimension) ────
  // Static editorial copy (the numbers behind each score come from the API's
  // per-dimension `details`); shown when a row is expanded.
  var DIM_ABOUT = {
    resilience: "The average yearly dollar loss this home faces from local natural disasters — flood, wind/tornado, earthquake, and wildfire — as a share of its value. Lower expected loss scores higher.",
    energy: "How much energy the home needs per square foot each year (its Energy Use Intensity), from its age, construction, and local climate zone. Less energy per square foot scores higher.",
    durability: "How much service life the home's major components — structure, roof, systems — still have, from its material, age, grade, and condition. More remaining life scores higher.",
    environmental: "The home's yearly climate footprint: operational carbon from energy, embodied carbon from materials (spread over the building's life), and water use. A smaller total scores higher.",
    infrastructure: "The property tax this home generates versus the public cost to serve it (roads, water, sewer, fire, police). A ratio above ~1 means it pays its own way. Higher is better.",
    health: "A neighborhood health index (CDC PLACES) — the census tract's percentile against the national distribution of US tracts across chronic-disease and health-outcome measures, so it's comparable across cities. Higher means a healthier local context.",
    air_quality: "The neighborhood's ambient air quality — annual fine-particulate (PM2.5) and ozone at the census tract from the CDC Tracking model, plus the county's EPA radon zone — scored against the national distribution of US tracts. Higher means cleaner, safer air.",
    noise: "How quiet the location is — the share of the census tract's residents exposed to loud (≥60 dB) transportation noise from aircraft, highways, and railroads (US DOT BTS National Transportation Noise Map), scored against the national distribution of US tracts. Higher means quieter.",
    socioeconomic: "A census-tract socioeconomic index (Census ACS: poverty, income, housing-cost burden, education, and unemployment) scored against the national distribution of US tracts, comparable across locations. Higher is a stronger local socioeconomic profile.",
    walkability: "How easy it is to run daily errands on foot and by transit (EPA National Walkability Index — intersection density, transit proximity, and land-use mix). Higher means more walkable.",
    climate: "How exposed this location is to worsening climate hazards by mid-century (CMIP6-LOCA2 downscaled projections). Higher means less projected hazard.",
    solar: "How productive rooftop solar is here — the annual energy a standard array makes per kW installed (PVGIS on NSRDB satellite data), scored against the national distribution of US counties. Higher means sunnier, so a system pays off faster. The details show what a typical system would produce, save, and offset in CO₂.",
    water: "How safe the tap water is — of the county's residents on a community water system, the share served by a system that had a recent health-based drinking-water violation (EPA SDWIS), scored against the national distribution of US counties. Higher means cleaner, safer drinking water. (Covers community water systems, not private wells.)"
  };

  // ── Confidence (data quality, separate from the grade) ─────────────────────
  var CONFIDENCE = {
    high: { glyph: "●", label: "High" },
    moderate: { glyph: "◐", label: "Moderate" },
    low: { glyph: "○", label: "Low" }
  };
  var CONF_RANK = { low: 1, moderate: 2, high: 3 };
  function confInfo(t) { return CONFIDENCE[t] || null; }

  // Coverage-penalized composite confidence: average the scored tiers, cap one
  // tier above the weakest, drop a tier when ≥2 dimensions are missing (≤⅓ → Low).
  function compositeConfidence(data) {
    var conf = data.confidence || {}, dims = data.dimensions || [];
    var nTotal = dims.length, nScored = 0, ranks = [];
    dims.forEach(function (d) {
      if (typeof d.score === "number") {
        nScored++;
        var r = CONF_RANK[conf[d.key]];
        if (r) ranks.push(r);
      }
    });
    if (!ranks.length) return null;
    var avg = Math.round(ranks.reduce(function (a, b) { return a + b; }, 0) / ranks.length);
    var capped = Math.min(avg, Math.min.apply(null, ranks) + 1);
    var coverage = nScored / nTotal, nMissing = nTotal - nScored, rank = capped;
    if (coverage <= 1 / 3) rank = 1;
    else if (nMissing >= 2) rank = Math.max(1, capped - 1);
    return { tier: ["low", "moderate", "high"][rank - 1], nScored: nScored, nTotal: nTotal };
  }

  // ●/◐/○ differ by a few pixels of ink at row size, so the glyph alone can't
  // carry the tier — it's paired with its word ("High data", "Low data") and a
  // per-tier weight. Shape, text, and value, so it survives small type and
  // grayscale. No tabindex here: the row's own panel repeats the provenance in
  // full, and 13 focusable dots put 13 dead stops before the caveats.
  function confDot(data, key) {
    var t = (data.confidence || {})[key], i = confInfo(t);
    if (!i) return "";
    return '<span class="conf-dot conf-' + t + '" aria-hidden="true">' + i.glyph + '</span> ' + esc(i.label) + ' data';
  }

  // ── Lifetime "cost over a mortgage" (delta vs. a typical comparable) ───────
  function annuityFactor(years, rate) { return rate === 0 ? years : (1 - Math.pow(1 + rate, -years)) / rate; }
  function fmtMoney(v) { return "$" + Math.round(Math.abs(v)).toLocaleString(); }
  function fmtK(v) { var a = Math.abs(v); return a >= 1000 ? "$" + (Math.round(a / 100) / 10).toFixed(1) + "k" : "$" + Math.round(a); }
  function roundMoney(v) {
    var a = Math.abs(v);
    if (a < 1000) return Math.round(v / 50) * 50;
    var mag = Math.pow(10, Math.floor(Math.log10(a)) - 1);
    return Math.round(v / mag) * mag;
  }
  // house/baseline: {annualEnergyCost, expectedAnnualLoss}. baseline.label names
  // the comparable. Present value of the annual (energy + expected-loss) delta
  // over a 30-yr mortgage, banded across 2%–4% real discount rates.
  // The 30-yr present value of the (energy + expected-loss) annual delta between
  // `house` and a comparable, at a 4% real discount rate. Returns null when
  // neither flow can be compared. Shared by the headline and the secondary line.
  function costPv(house, comparable, rate) {
    var cmpEnergy = house.annualEnergyCost != null && comparable.annualEnergyCost != null;
    var cmpLoss = house.expectedAnnualLoss != null && comparable.expectedAnnualLoss != null;
    if (!cmpEnergy && !cmpLoss) return null;
    var dAnnual = (cmpEnergy ? comparable.annualEnergyCost - house.annualEnergyCost : 0)
      + (cmpLoss ? comparable.expectedAnnualLoss - house.expectedAnnualLoss : 0);
    return dAnnual * annuityFactor(30, rate == null ? 0.04 : rate);
  }

  // `secondary` (optional) adds a second comparison line — the density dividend on
  // multi-unit buildings: this unit vs. "the same home standing alone" (detached).
  // `monthly` (optional) is the modeled energy bill, promoted here from the
  // metrics footnote: it's the one figure on the card a reader can check against
  // their own life, and it belongs with the other money.
  //
  // The headline names what it's measured against and in what units. "$2,600
  // higher" beside a house reads as a purchase-price difference; it is in fact the
  // present value of a modeled running-cost gap — around $90 a year — so the
  // referent ("than a typical home here"), the scope, and the per-year figure sit
  // with the number instead of two smaller lines below it.
  function costStrip(house, baseline, secondary, monthly) {
    if (!house || !baseline) return "";
    var pv = costPv(house, baseline, 0.04);
    if (pv == null) return "";
    var pvs = [Math.abs(pv), Math.abs(costPv(house, baseline, 0.02))];
    var lo = Math.min.apply(null, pvs), hi = Math.max.apply(null, pvs);
    var same = Math.abs(pv) < 1, cheaper = pv > 0;
    var dir = same ? "about the same" : (cheaper ? "less" : "more");
    var head = same ? "About the same to run"
      : fmtMoney(roundMoney(pv)) + ' <span class="' + (cheaper ? "cheaper" : "pricier") + '">' + dir + '</span> to run';
    var perYear = Math.round(Math.abs(pv / annuityFactor(30, 0.04)) / 10) * 10;
    var secLine = "";
    if (secondary) {
      var spv = costPv(house, secondary, 0.04);
      if (spv != null && Math.abs(spv) >= 1) {
        var sdir = spv > 0 ? "less" : "more";
        secLine = '<div class="cost-secondary">' + fmtMoney(roundMoney(spv))
          + ' <span class="' + (spv > 0 ? "cheaper" : "pricier") + '">' + sdir + '</span> to run than '
          + esc(secondary.label || "the same home standing alone") + '</div>';
      }
    }
    return '<div class="cost-strip"><div class="cost-cap">Cost to run, over a 30-year mortgage</div>'
      + '<div class="cost-delta">' + head + '</div>'
      + (same
          ? '<div class="cost-vs">as ' + esc(baseline.label || "a typical comparable here") + '</div>'
          : '<div class="cost-vs">than ' + esc(baseline.label || "a typical comparable here")
            + ' &mdash; about ' + fmtMoney(perYear) + ' a year</div>')
      + (same ? "" : '<div class="cost-band">' + fmtK(lo) + '–' + fmtK(hi) + ' ' + dir
          + ' depending on how future costs are weighed</div>')
      + secLine
      + (monthly != null ? '<div class="cost-energy">Estimated energy bill: <strong>$'
          + Math.round(monthly) + ' a month</strong></div>' : "")
      + '<div class="cost-note">Counts energy bills and likely disaster losses only &mdash; not the '
      + 'purchase price, property tax, or upkeep. In today’s dollars.</div></div>';
  }

  // Expandable detail panel body: plain-language "what this measures" + the real
  // per-dimension numbers from the API + a data-quality provenance line.
  function dimDetail(d, data) {
    var html = "";
    var about = DIM_ABOUT[d.key];
    if (about) html += '<p class="dim-about">' + esc(about) + '</p>';
    var rows = (data.details || {})[d.key] || [];
    var pct = typeof d.national_percentile === "number" && isFinite(d.national_percentile)
      ? d.national_percentile : null;
    if (rows.length || pct != null) {
      html += '<dl class="dim-nums">';
      // The percentile spelled out, in the one place with room for a sentence.
      if (pct != null) {
        html += '<div class="dim-num"><dt>Compared with US homes</dt><dd>Better than ' + pct + '% of them</dd></div>';
      }
      rows.forEach(function (row) {
        html += '<div class="dim-num"><dt>' + esc(row.label) + '</dt><dd>' + esc(row.value) + '</dd></div>';
      });
      html += '</dl>';
    }
    var ci = confInfo((data.confidence || {})[d.key]);
    if (ci) {
      var note = (data.confidence_notes || {})[d.key];
      html += '<p class="dim-prov"><span class="conf-dot" aria-hidden="true">' + ci.glyph + '</span> Data quality: '
        + '<strong>' + esc(ci.label) + '</strong>' + (note ? ' &mdash; ' + esc(note) : '') + '</p>';
    }
    return html;
  }

  // ── Per-dimension row — a tap/click-to-expand disclosure (native <details>) ──
  // The summary is the score bar + grade + confidence dot; expanding reveals what
  // the category measures and the actual numbers behind the score. Native
  // <details> gives free mobile-tap, mouse-click, and keyboard/screen-reader
  // support with no JS wiring and no inline handlers (CSP-safe).
  // The row is three beats: name + score/grade, the bar, then a small caption for
  // everything that used to be crowded onto the first line. That caption is where
  // the percentile gets to be a sentence — "17th US" reads as a rank *from the
  // top* (i.e. excellent) when it means the opposite — and where the data-quality
  // tier can carry its own word instead of an 11px glyph nobody can resolve.
  function dimRow(d, data) {
    var chev = '<span class="dim-chevron" aria-hidden="true">&#9656;</span>';
    var right, bar, notes = [];
    if (d.score == null) {
      right = '<span class="na">Not scored here</span>';
      bar = '<div class="score-bar"></div>';
      notes.push("No data for this address &mdash; left out of the overall score");
    } else {
      var sc = Number(d.score);
      if (!isFinite(sc)) sc = 0;
      sc = Math.max(0, Math.min(100, sc));
      var band = (data.bands || {})[d.key], whisker = "";
      if (band && isFinite(band.low) && isFinite(band.high)) {
        var wlo = Math.max(0, Math.min(100, band.low)), whi = Math.max(0, Math.min(100, band.high));
        whisker = '<div class="ci-whisker" style="left:' + wlo + '%;width:' + Math.max(0, whi - wlo)
          + '%"><div class="ci-line"></div></div>';
      }
      if (typeof d.national_percentile === "number" && isFinite(d.national_percentile)) {
        notes.push("Beats " + d.national_percentile + "% of US homes");
      }
      var g = gradeOf(d);
      // Score and grade, not "48.5 / C" — a slash between them reads as a
      // fraction ("48.5 out of C"). The chip is the same badge the composite
      // uses, and the bar takes its color from the same letter.
      right = '<span class="dim-score">' + sc.toFixed(1)
        + (g ? '<span class="grade grade-' + g.toLowerCase() + '">' + esc(g) + '</span>' : '') + '</span>';
      bar = '<div class="score-bar"><div class="fill" style="width:' + sc + '%'
        + (g ? ';background:' + GRADE_COLORS[g] : '') + '"></div>' + whisker + '</div>';
    }
    var dot = confDot(data, d.key);
    if (dot) notes.push(dot);
    return '<details class="score-bar-container dim-row"><summary class="dim-summary">'
      + '<div class="score-bar-label"><span class="dim-name">' + esc(d.label) + '</span>' + right + '</div>'
      + bar
      + '<div class="dim-meta"><span class="dim-notes">' + notes.join(" &middot; ") + '</span>' + chev + '</div>'
      + '</summary><div class="dim-detail">' + dimDetail(d, data) + '</div></details>';
  }

  // The 13 rows split the way a buyer's question does: is the problem the house,
  // or the block? The payload already tags each dimension `construction` or
  // `location` — this only draws the line it already knows about.
  var GROUP_LABEL = { construction: "The building itself", location: "The neighborhood &amp; location" };
  function dimRows(dims, data) {
    var groups = [], byKind = {};
    dims.forEach(function (d) {
      var k = d.kind === "location" || d.kind === "construction" ? d.kind : "";
      if (!byKind[k]) { byKind[k] = []; groups.push(k); }
      byKind[k].push(d);
    });
    var grouped = groups.length > 1 && groups.every(function (k) { return !!GROUP_LABEL[k]; });
    return groups.map(function (k) {
      var rows = byKind[k].map(function (d) { return dimRow(d, data); }).join("");
      return (grouped ? '<div class="dim-group">' + GROUP_LABEL[k] + '</div>' : "") + rows;
    }).join("");
  }

  // Two facts, not one: how the overall number was built (an average over only the
  // dimensions that could be scored — so two addresses with different coverage
  // aren't strictly comparable), and how solid the underlying data is. Joining
  // them with a middot made them look like the same kind of claim.
  function compositeConfLine(data) {
    var cc = compositeConfidence(data);
    if (!cc) return { html: "", cc: null };
    var ci = confInfo(cc.tier);
    var missing = (data.dimensions || []).filter(function (d) { return d.score == null; })
      .map(function (d) { return d.label; });
    var ccLbl = ci.label + " data quality overall. " + (data.confidence_legend || "");
    var html = '<div class="composite-conf">'
      + '<div class="cc-avg">The average of the ' + cc.nScored + ' dimension'
      + (cc.nScored === 1 ? "" : "s") + ' we could score'
      + (cc.nTotal !== cc.nScored ? ' here, out of ' + cc.nTotal : "") + '.'
      + (missing.length ? ' Not scored: ' + esc(missing.join(", ")) + '.' : "") + '</div>'
      + '<div class="cc-conf tip" tabindex="0" aria-label="' + esc(ccLbl) + '" data-tip="' + esc(data.confidence_legend || "") + '">'
      + '<span class="conf-dot conf-' + cc.tier + '" aria-hidden="true">' + ci.glyph + '</span> '
      + esc(ci.label) + ' data quality overall</div></div>';
    return { html: html, cc: cc };
  }

  // The instruction for the card's core interaction, placed *above* the rows it
  // describes. It used to sit below all thirteen — two-and-a-half phone screens
  // past the first row it was explaining — and only when confidence data existed,
  // even though the rows expand either way.
  function tapHint() {
    return '<p class="dim-hint"><strong>Tap any row</strong> to see what it measures and the numbers behind it.</p>';
  }
  function legendHtml() {
    return '<div class="conf-legend">&nbsp;●&nbsp;High &nbsp;◐&nbsp;Moderate &nbsp;○&nbsp;Low &mdash; '
      + 'the dot shows how solid the data is (not how good the score is); the whisker shows the climate range</div>';
  }

  // Full label card. `opts` may carry {heading, subline} to override the header
  // (label.html supplies a preset name + description; the address pages supply
  // the resolved location + a build summary). Returns an HTML string.
  function renderCard(data, opts) {
    opts = opts || {};
    var loc = data.location || {};
    var comp = data.composite_score;
    var compGrade = data.composite_national_grade || "—";
    var color = GRADE_COLORS[compGrade] || "#64748b";
    var ink = GRADE_INK[compGrade] || "#ffffff";   /* white on the gray fallback = 4.7:1 */
    var m = data.metrics || {};
    var h = data.house || {};

    // The energy bill moves into the cost strip when there is one; the two terms
    // of art left here get their plain-language gloss inline, because "fiscal
    // ratio 0.14" tells a reader nothing on its own.
    var strip = costStrip(data.cost, data.baseline_cost, data.detached_cost, m.est_monthly_energy_cost);
    var metricBits = [];
    if (m.eui_kbtu_sqft_yr != null)
      metricBits.push("Uses " + m.eui_kbtu_sqft_yr.toFixed(1) + " kBTU of energy per sqft a year (EUI)");
    if (!strip && m.est_monthly_energy_cost != null)
      metricBits.push("Estimated energy bill $" + Math.round(m.est_monthly_energy_cost) + " a month");
    if (m.fiscal_ratio != null)
      metricBits.push("Its property tax covers " + m.fiscal_ratio.toFixed(2)
        + "× what city services here cost (fiscal ratio)");

    var heading = opts.heading || loc.label || (h.lat + ", " + h.lon);
    // The scored/total count is stated in words under the composite ("the average
    // of the 12 dimensions we could score here, out of 13"), so the bare "12/13
    // dimensions" here was the same fact twice, in the more cryptic form.
    var metaParts = [];
    if (loc.county_name) metaParts.push(esc(loc.county_name));
    if (loc.climate_zone) metaParts.push("IECC " + esc(loc.climate_zone));

    var subline = opts.subline != null ? opts.subline : (function () {
      var bits = [];
      if (h.construction) bits.push(WALL_LABELS[h.construction] || h.construction);
      if (h.year_built) bits.push("built " + h.year_built);
      if (h.sqft != null) bits.push(Math.round(h.sqft).toLocaleString() + " sqft");
      return bits.length ? esc(bits.join(" · ")) : "";
    })();

    // Detected building context (NSI). Shown only for multi-unit buildings — for
    // a single-family home it just confirms the default assumption, so it's noise.
    var st = data.structure, structLine = "";
    if (st && (st.structure_type === "multifamily" || (st.num_units && st.num_units > 1))) {
      var sbits = [(st.num_units ? st.num_units + "-unit " : "") + "building"];
      if (st.stories) sbits.push(st.stories + (st.stories === 1 ? " story" : " stories"));
      structLine = "Detected here: " + esc(sbits.join(" · ")) + " (" + esc(st.source || "NSI") + ")";
    }

    var html = '<div class="label-card"><div class="label-head"><div>'
      + '<div class="label-title">' + esc(heading) + '</div>'
      + (metaParts.length ? '<div class="meta">' + metaParts.join(" &middot; ") + '</div>' : "")
      + (subline ? '<div class="build-line">' + subline + '</div>' : '')
      + (structLine ? '<div class="build-line">' + structLine + '</div>' : '')
      // "59.9" alone is not a quantity — readers guess percent, price, or index.
      // The denominator and a one-word caption say what it is before the grade
      // chip has to.
      + '</div><div class="label-score"><div class="composite-cap">Overall</div>'
      + '<div class="composite-num">'
      + (comp == null ? "N/A" : comp.toFixed(1)) + (comp == null ? "" : '<span class="of100">/100</span>') + '</div>'
      + '<span class="grade-lg" style="background:' + color + ';color:' + ink + '">' + esc(compGrade) + '</span></div></div>';

    var confLine = compositeConfLine(data);
    html += confLine.html;
    // Caveats change how a specific row should be read ("Infrastructure Burden
    // falls back to the pilot cost model"), so they land before the numbers they
    // qualify rather than below all thirteen.
    (data.caveats || []).forEach(function (c) {
      html += '<div class="insight warn card-caveat">' + esc(c) + '</div>';
    });
    html += strip;
    html += tapHint();
    html += dimRows(data.dimensions || [], data);
    if (metricBits.length) html += '<p class="meta card-metrics">' + esc(metricBits.join("  ·  ")) + '</p>';
    if (confLine.cc) html += legendHtml();
    return html + '</div>';
  }

  // Per-dimension A→B delta table for compare mode.
  function deltaTable(a, b) {
    var dims = a.dimensions || [];
    var bScore = {};
    (b.dimensions || []).forEach(function (d) { bScore[d.key] = d.score; });
    function cell(v) { return typeof v === "number" ? v.toFixed(1) : "N/A"; }
    function deltaCell(va, vb) {
      if (typeof va !== "number" || typeof vb !== "number") return { txt: "—", cls: "flat" };
      var dd = vb - va;
      return { txt: (dd > 0 ? "+" : "") + dd.toFixed(1), cls: dd > 0.05 ? "up" : dd < -0.05 ? "down" : "flat" };
    }
    var rows = dims.map(function (d) {
      var va = d.score, vb = bScore[d.key], dc = deltaCell(va, vb);
      return '<tr><td>' + esc(d.label) + '</td><td>' + cell(va) + '</td><td>' + cell(vb)
        + '</td><td class="' + dc.cls + '">' + dc.txt + '</td></tr>';
    }).join("");
    var cd = deltaCell(a.composite_score, b.composite_score);
    rows += '<tr><td><strong>Composite</strong></td><td><strong>' + cell(a.composite_score)
      + '</strong></td><td><strong>' + cell(b.composite_score) + '</strong></td>'
      + '<td class="' + cd.cls + '"><strong>' + cd.txt + '</strong></td></tr>';
    return '<table class="delta-table"><thead><tr><th>Dimension</th><th>'
      + esc(a._name || "A") + '</th><th>' + esc(b._name || "B") + '</th><th>&Delta;</th></tr></thead>'
      + '<tbody>' + rows + '</tbody></table>';
  }

  return {
    GRADE_COLORS: GRADE_COLORS, gradeFor: gradeFor, gradeOf: gradeOf, esc: esc,
    WALL_LABELS: WALL_LABELS, UPGRADE_LABELS: UPGRADE_LABELS,
    CONFIDENCE: CONFIDENCE, confInfo: confInfo, compositeConfidence: compositeConfidence,
    confDot: confDot, dimRow: dimRow, dimRows: dimRows, costStrip: costStrip,
    renderCard: renderCard, deltaTable: deltaTable, legendHtml: legendHtml, tapHint: tapHint
  };
})();
