/*
 * label-form.js — the unified scoring widget for Housing Nutrition Label.
 *
 * One module used by every "score an address" surface (home, examples, label).
 * It owns the WHOLE interactive scoring UI: API-endpoint resolution + privacy
 * disclosure, the address input + autocomplete, the Detected / Single / Compare
 * view modes, the "Refine building details" auto-fill panel, the optional
 * density-on-this-parcel comparison, deep-linking, shareable-URL sync,
 * remembered last location, and "use my location". Rendering of the label card
 * itself stays in label-core.js (LabelCore); autocomplete stays in AddrSuggest.
 *
 * No build step, no framework: exposes a single global `window.LabelForm` whose
 * `mount(opts)` generates the widget markup into a container and wires it up.
 *
 *   LabelForm.mount({
 *     container: document.getElementById("score-widget"),
 *     modes: ["detected", "single", "compare"],  // subset; order = toggle order
 *     density: true,                              // show the density comparison
 *     geolocate: true,                            // show "Use my location"
 *     persist: true,                              // sync URL + remember last loc
 *     defaultLat: 35.13, defaultLon: -89.99,      // used when no address entered
 *   });
 *
 * Everything is feature-flagged so a page shows exactly what it needs — e.g. the
 * examples page mounts detected-only, the home page adds density, the label page
 * adds Compare.
 */
window.LabelForm = (function () {
  "use strict";
  // Resolved in mount() (not at eval time) so a clear error fires if a page
  // includes the scripts in the wrong order, instead of a cryptic later crash.
  var LC, AS;

  // Construction fields shown in the refine panel. `key` is the /label query
  // param; the input carries data-field="<key>" so the controller can read/write
  // it without global IDs (multiple widgets never collide).
  var FIELDS = [
    { key: "year_built", label: "Year built", type: "number",
      attrs: 'min="1850" max="2030" step="1" placeholder="e.g. 1998"' },
    { key: "construction", label: "Wall type", type: "select", options: [
      ["", "(unknown)"], ["frame", "Wood frame"], ["brick", "Brick (masonry)"],
      ["brick-frame", "Brick veneer / frame"], ["block", "Concrete block (CMU)"],
      ["icf", "Insulated concrete form (ICF)"], ["sip", "Structural insulated panel (SIP)"],
      ["stone", "Stone"], ["vinyl", "Vinyl-sided frame"]] },
    { key: "foundation", label: "Foundation", type: "select", options: [
      ["", "(unknown)"], ["slab", "Slab on grade"], ["crawl", "Crawlspace"],
      ["partial-basement", "Partial basement"], ["full-basement", "Full basement"]] },
    { key: "condition", label: "Condition", type: "select", options: [
      ["", "(unknown)"], ["excellent", "Excellent"], ["good", "Good"], ["average", "Average"],
      ["fair", "Fair"], ["poor", "Poor"], ["unsound", "Unsound"]] },
    { key: "sqft", label: "Living area (sqft, per unit)", type: "number",
      attrs: 'min="200" max="20000" step="50" placeholder="one unit, not the whole building"' },
    { key: "value", label: "Home value ($)", type: "number",
      attrs: 'min="1000" max="100000000" step="1000" placeholder="market value"' },
    { key: "lot_acres", label: "Lot size (acres)", type: "number",
      attrs: 'min="0.01" max="1000" step="0.01" placeholder="e.g. 0.18"' },
    { key: "units", label: "Dwelling units", type: "number",
      attrs: 'min="1" max="500" step="1" placeholder="1 (house), 4 (quadplex)"' },
    { key: "bldg_material", label: "Building material", type: "select", options: [
      ["", "(if a multi-unit building)"], ["wood", "Wood frame"], ["masonry", "Load-bearing masonry"],
      ["concrete", "Reinforced concrete"], ["steel", "Steel frame"]] },
    { key: "stories", label: "Stories", type: "number",
      attrs: 'min="1" max="150" step="1" placeholder="floors"' }
  ];
  var UPGRADES = [
    ["solar", "Solar panels"], ["backup_generator", "Backup generator / battery"],
    ["fire_sprinklers", "Fire sprinklers"], ["hurricane_straps", "Hurricane straps"],
    ["fortified_roof", "FORTIFIED roof"], ["tornado_safe_room", "Tornado safe room"],
    ["seismic_retrofit", "Seismic retrofit"], ["flood_vents", "Flood vents"]
  ];
  // Toggle labels + a one-line explanation of what each view actually scores.
  // The old "Detected / Single / Compare" gave no hint of the difference; these
  // say it in plain terms (the real home vs. hypothetical construction profiles).
  var MODE_LABELS = {
    detected: "This home",
    single: "What-if build",
    compare: "Compare builds"
  };
  var MODE_HELP = {
    detected: "Scores the real home at this address, using building details "
      + "pulled from public records. Edit any detail under “Refine building "
      + "details” to correct it and the label updates.",
    single: "Scores one hypothetical construction profile at this location — "
      + "pick a build type to see how construction choices alone move each "
      + "dimension. The home’s real details are ignored here.",
    compare: "Scores two hypothetical construction profiles side by side at this "
      + "location, with the per-dimension difference between them."
  };
  var SUPPORTED_MODES = ["detected", "single", "compare"];
  var _mountSeq = 0;   // per-page counter → unique element IDs when >1 widget mounts

  function esc(s) { return LC.esc(s); }

  // ── Markup generation ──────────────────────────────────────────────────────
  function fieldHtml(f) {
    var tag = '<span class="field-tag" data-tag="' + f.key + '"></span>';
    var control;
    if (f.type === "select") {
      control = '<select data-field="' + f.key + '">' + f.options.map(function (o) {
        return '<option value="' + o[0] + '">' + esc(o[1]) + '</option>';
      }).join("") + '</select>';
    } else {
      control = '<input type="number" data-field="' + f.key + '" ' + (f.attrs || "") + '>';
    }
    return '<label>' + esc(f.label) + ' ' + tag + control + '</label>';
  }

  function refineHtml() {
    return '<details class="addr-details lf-refine" style="max-width:640px;margin:0 auto 1rem;display:none;">'
      + '<summary><span>Refine building details</span> <span class="refine-count lf-refine-count"></span></summary>'
      + '<p class="addr-hint" style="margin:0 0 0.5rem;font-size:0.82rem;opacity:0.85;">'
      + 'We estimate these from public data (USACE structure records + Census) and score with them. '
      + 'Anything looks off? Edit it and the label updates. Living area is <strong>per unit</strong>.</p>'
      + '<div class="addr-fields">' + FIELDS.map(fieldHtml).join("") + '</div>'
      + '<fieldset class="addr-upgrades"><legend>Resilience upgrades</legend>'
      + UPGRADES.map(function (u) {
          return '<label><input type="checkbox" value="' + u[0] + '"> ' + esc(u[1]) + '</label>';
        }).join("")
      + '</fieldset></details>';
  }

  function formHtml(opts) {
    var buttons = '<button type="submit" class="go">Score it</button>';
    if (opts.geolocate) buttons += '<button type="button" class="reset lf-locate">Use my location</button>';
    if (opts.persist)   buttons += '<button type="button" class="reset lf-reset">Reset</button>';
    var lb = opts.listboxId;   // links the combobox input ↔ its suggestions listbox
    return '<form class="label-addr-form lf-form">'
      + '<div class="addr-ac" role="combobox" aria-haspopup="listbox" aria-expanded="false" aria-owns="' + lb + '">'
      + '<input type="text" class="lf-addr" aria-label="US address or place name to score" autocomplete="off" '
      + 'role="textbox" aria-autocomplete="list" aria-controls="' + lb + '" aria-activedescendant="" '
      + 'placeholder="Enter a U.S. address or place name &mdash; e.g. 111 S Grand Ave, Los Angeles">'
      + '<ul class="addr-suggest lf-suggest" id="' + lb + '" role="listbox" hidden></ul></div>'
      + buttons + '</form>'
      + '<p class="label-privacy lf-geo" role="status" aria-live="polite" style="display:none;"></p>'
      + '<p class="label-privacy lf-privacy" style="display:none;"></p>'
      + '<div class="insight warn lf-warn" style="display:none;max-width:640px;margin:-0.5rem auto 1rem;"></div>'
      + '<div class="insight lf-note" style="display:none;max-width:640px;margin:0 auto 1rem;">'
      + 'Set a scoring API to run live scores — append <code>?api=&lt;your-endpoint&gt;</code> to the URL '
      + 'or configure <code>window.HOUSING_LABEL_API</code>.</div>';
  }

  function densityHtml() {
    return '<div class="lf-density-wrap" hidden style="max-width:640px;margin:0.75rem auto 0;">'
      + '<button type="button" class="density-btn lf-density-btn">Compare densities on this parcel</button>'
      + '<p class="label-privacy lf-density-status" style="display:none;"></p>'
      + '<div class="lf-density-result"></div></div>';
  }

  // ── Controller ──────────────────────────────────────────────────────────────
  function mount(opts) {
    opts = opts || {};
    var root = opts.container;
    if (!root) { throw new Error("LabelForm.mount: opts.container is required"); }
    // Hard dependencies — fail loudly and actionably if the page loaded scripts
    // out of order (label-core.js and addr-suggest.js must come before this).
    LC = window.LabelCore; AS = window.AddrSuggest;
    if (!LC || !AS) {
      var miss = (!LC ? "label-core.js (LabelCore)" : "") + (!LC && !AS ? " and " : "")
        + (!AS ? "addr-suggest.js (AddrSuggest)" : "");
      var err = "LabelForm.mount: missing dependency — load " + miss + " before label-form.js.";
      root.innerHTML = '<div class="error">' + err + '</div>';
      throw new Error(err);
    }
    // Keep only supported modes, in caller order, de-duped — an unknown/typo'd
    // value must not silently fall through to the Compare branch.
    var modes = (opts.modes || []).filter(function (m, i, a) {
      return SUPPORTED_MODES.indexOf(m) >= 0 && a.indexOf(m) === i;
    });
    if (!modes.length) modes = ["detected"];
    var wantDensity = !!opts.density;
    var wantGeo = !!opts.geolocate;
    var persist = !!opts.persist;
    var DEFAULT_LAT = opts.defaultLat != null ? opts.defaultLat : 35.13;
    var DEFAULT_LON = opts.defaultLon != null ? opts.defaultLon : -89.99;
    var LS_KEY = "hlabel:lastLocation";
    var uid = "lf" + (++_mountSeq) + "-";   // namespaces this widget's generated IDs

    // Resolve the scoring API endpoint: ?api= wins, else window.HOUSING_LABEL_API.
    var apiFromQuery = null;
    try { apiFromQuery = new URLSearchParams(location.search).get("api"); } catch (e) {}
    var API_BASE = (apiFromQuery || window.HOUSING_LABEL_API || "").replace(/\/+$/, "");
    function apiHost() { try { return new URL(API_BASE).host || API_BASE; } catch (e) { return API_BASE; } }

    // Build the widget markup. The scored label card (.lf-app) comes before the
    // density comparison, which is a follow-on "what if this parcel were denser?".
    root.innerHTML = formHtml({ geolocate: wantGeo, persist: persist, listboxId: uid + "listbox" })
      + refineHtml()
      + '<div class="lf-app"><div class="loading">Scoring this address&hellip;</div></div>'
      + (wantDensity ? densityHtml() : "");

    // Element refs (scoped to this widget's root — no global IDs).
    function q(sel) { return root.querySelector(sel); }
    function qa(sel) { return Array.prototype.slice.call(root.querySelectorAll(sel)); }
    var app = q(".lf-app");
    var form = q(".lf-form"), addrInput = q(".lf-addr");
    var geoEl = q(".lf-geo"), privEl = q(".lf-privacy"), warnEl = q(".lf-warn"), noteEl = q(".lf-note");
    var refineEl = q(".lf-refine"), refineCount = q(".lf-refine-count");
    var densWrap = wantDensity ? q(".lf-density-wrap") : null;
    var densBtn = wantDensity ? q(".lf-density-btn") : null;
    var densStatus = wantDensity ? q(".lf-density-status") : null;
    var densResult = wantDensity ? q(".lf-density-result") : null;
    var locateBtn = wantGeo ? q(".lf-locate") : null;
    var resetBtn = persist ? q(".lf-reset") : null;

    // Privacy disclosure: no API → hint; ?api= link → loud warning; default → quiet note.
    if (!API_BASE) {
      noteEl.style.display = "";
    } else if (apiFromQuery) {
      warnEl.textContent = "Heads up: addresses you enter (including partial text typed for "
        + "suggestions) are sent to the API at " + apiHost() + " (set via this link's ?api= parameter).";
      warnEl.style.display = "";
    } else {
      privEl.textContent = "Addresses you type (including partial text for suggestions) are sent to "
        + "our scoring API (" + apiHost() + ") to look up location data.";
      privEl.style.display = "";
    }

    var ac = AS.attach({ input: addrInput, box: q(".lf-suggest"), apiBase: API_BASE, idPrefix: uid + "opt-" });

    // View state. `presets`/`detected` are cached per location so switching modes
    // doesn't refetch; `desc` is the current location descriptor.
    // `idle` is the pre-scoring state: on a fresh visit the widget waits for the
    // user to enter an address (or use their location) instead of auto-scoring a
    // default — auto-scoring a place nobody asked for read as confusing. A shared
    // deep link (?address / ?lat,lon) clears it and scores immediately.
    var state = { mode: modes[0], idx: 0, idxA: 0, idxB: 0,
                  presets: null, detected: null, building: null, detectedCtx: null,
                  detectedQuery: "", desc: null, error: null, initialized: false, idle: true };
    var touched = {};                 // field key -> true once the user edits it
    var reqSeq = 0;                   // drop out-of-order responses from rapid submits

    // ── helpers ────────────────────────────────────────────────────────────────
    function clone(o) { var c = {}, h = Object.prototype.hasOwnProperty; for (var k in o) if (h.call(o, k)) c[k] = o[k]; return c; }
    function findIdx(re) { for (var i = 0; i < state.presets.length; i++) if (re.test(state.presets[i].name)) return i; return -1; }
    function clampIdx(i) { return Math.max(0, Math.min(i, state.presets.length - 1)); }
    function okJson(r) {
      if (!r.ok) return r.json().then(
        function (j) { var e = new Error((j && j.detail) || ("HTTP " + r.status)); e.status = r.status; throw e; },
        function () { var e = new Error("HTTP " + r.status); e.status = r.status; throw e; });
      return r.json();
    }
    function fieldEl(key) { return q('[data-field="' + key + '"]'); }
    function gradeSpan(g) {
      var c = (g || "").toLowerCase();
      return "abcdf".indexOf(c) >= 0 && c.length === 1
        ? '<span class="grade grade-' + c + '">' + esc(g) + '</span>' : esc(g);
    }

    // ── render ──────────────────────────────────────────────────────────────────
    function gradeLegend() {
      return '<div class="legend">' + ["A", "B", "C", "D", "F"].map(function (g) {
        return '<span><span class="swatch" style="background:' + LC.GRADE_COLORS[g] + '"></span>' + g + '</span>';
      }).join("") + '</div>';
    }
    function toggleBar() {
      if (modes.length < 2) return "";     // single-mode widget → no toggle
      return '<div class="mode-toggle" role="group" aria-label="View mode">'
        + modes.map(function (m) {
            return '<button data-mode="' + m + '"' + (state.mode === m ? ' class="on"' : '')
              + ' aria-pressed="' + (state.mode === m) + '" title="' + esc(MODE_HELP[m] || "") + '">'
              + esc(MODE_LABELS[m] || m) + '</button>';
          }).join("") + '</div>'
        // Plain-language caption for the active view, so the toggle is
        // self-explanatory rather than three opaque one-word buttons.
        + (MODE_HELP[state.mode]
            ? '<p class="mode-help lf-mode-help">' + esc(MODE_HELP[state.mode]) + '</p>'
            : "");
    }
    function pickerSel(cls, id, val) {
      return '<select class="' + cls + '" id="' + id + '">' + state.presets.map(function (p, i) {
        return '<option value="' + i + '"' + (i === val ? ' selected' : '') + '>' + esc(p.name) + '</option>';
      }).join("") + '</select>';
    }
    // The "typical comparable" for a Single profile is the Baseline preset here.
    function baselineCost() {
      var bi = findIdx(/baseline/i); if (bi < 0) bi = 0;
      var b = state.presets[bi];
      if (!b || !b.cost) return null;
      var c = clone(b.cost); c.label = b.name + " (typical here)"; return c;
    }
    function cardFor(idx, baseline) {
      var p = state.presets[idx], d = clone(p);
      d.baseline_cost = baseline || null;
      return LC.renderCard(d, { heading: p.name, subline: esc(p.description) });
    }
    function detectedCard() {
      var data = state.detected, h = data.house || {}, ctx = state.detectedCtx || {}, bits = [];
      if (h.construction) bits.push(LC.WALL_LABELS[h.construction] || h.construction);
      if (h.year_built) bits.push("built " + h.year_built);
      if (h.sqft != null) bits.push(Math.round(h.sqft).toLocaleString() + " sqft");
      if (ctx.upgradeLabels && ctx.upgradeLabels.length) bits.push(ctx.upgradeLabels.join(", "));
      var profileText = ctx.isCustom ? "This home (custom)" : "This home (detected from address)";
      var subline = '<strong>' + esc(profileText) + '</strong>'
        + (bits.length ? " &middot; " + esc(bits.join(" · ")) : "");
      return LC.renderCard(data, { subline: subline });
    }

    function render() {
      if (!API_BASE) { app.innerHTML = ""; return; }
      if (state.idle) {
        // Nothing scored yet — prompt for input rather than auto-scoring a default.
        var locateHint = wantGeo ? " or use <strong>your location</strong>" : "";
        app.innerHTML = '<div class="insight label-prompt">Enter a U.S. address or place name above'
          + locateHint + ' to generate its nutrition label. You can search by street address '
          + '(<em>111 S Grand Ave, Los Angeles</em>) or by the name of a place or business.</div>';
        if (densWrap) densWrap.hidden = true;
        return;
      }
      if (state.error) {
        // A 422 is the residential-only screen (a non-residential address), not an
        // outage — show the guidance as a neutral notice, without the "retry" line.
        if (state.errorStatus === 422) {
          app.innerHTML = '<div class="insight warn label-notice">' + esc(state.error) + '</div>';
        } else {
          app.innerHTML = '<div class="error">Could not load the label: ' + esc(state.error)
            + '.<br>The scoring API may be temporarily unavailable &mdash; retry in a moment.</div>';
        }
        return;
      }
      var loadingData = state.mode === "detected" ? !state.detected : !state.presets;
      if (loadingData) {
        app.innerHTML = '<div class="loading">'
          + (state.mode === "detected" ? 'Scoring this address&hellip;' : 'Scoring construction profiles&hellip;')
          + '</div>';
        return;
      }
      var loc0 = state.mode === "detected"
        ? ((state.detected || {}).location || {})
        : (((state.presets || [])[0] || {}).location || {});
      var locName = loc0.label || loc0.county_name || "";
      var scoredWhat = state.mode === "detected" ? "This home scored at" : "Profiles scored at";
      var html = locName ? '<div class="label-loc">' + scoredWhat + ' <strong>' + esc(locName) + '</strong></div>' : "";
      html += toggleBar();
      if (state.mode === "detected") {
        html += detectedCard() + gradeLegend();
      } else if (state.mode === "single") {
        html += '<div class="picker"><label for="' + uid + 'p-sel">Construction profile: </label>'
          + pickerSel("lf-p-sel", uid + "p-sel", state.idx) + '</div>';
        html += cardFor(state.idx, baselineCost()) + gradeLegend();
      } else {
        var A = state.presets[state.idxA], B = state.presets[state.idxB];
        A._name = A.name; B._name = B.name;   // deltaTable() headers use _name (else "A"/"B")
        html += '<div class="compare-pickers">'
          + '<div class="picker"><label for="' + uid + 'a-sel">Compare A (baseline): </label>'
          + pickerSel("lf-a-sel", uid + "a-sel", state.idxA) + '</div>'
          + '<div class="picker"><label for="' + uid + 'b-sel">against B: </label>'
          + pickerSel("lf-b-sel", uid + "b-sel", state.idxB) + '</div></div>';
        var aCost = A.cost ? (function () { var c = clone(A.cost); c.label = A.name; return c; })() : null;
        html += '<div style="max-width:640px;margin:0 auto 1.25rem;">' + LC.costStrip(B.cost, aCost) + '</div>';
        html += '<div class="compare-grid">' + cardFor(state.idxA, null) + cardFor(state.idxB, null) + '</div>';
        html += LC.deltaTable(A, B);
        html += '<p class="conf-legend" style="max-width:640px;margin:0.5rem auto 0;text-align:center;">'
          + '&Delta; is B minus A; green favors B, red favors A. Location-driven dimensions are identical across profiles here, so they show &Delta;&nbsp;0.</p>';
        html += gradeLegend();
      }
      app.innerHTML = html;
      if (densWrap) {
        // The density sweep varies a parcel from 1 to a few units on a fixed lot,
        // so it's only meaningful for a home that isn't already a multi-unit
        // building. Hide it once we've detected one (mirrors label-core's
        // multi-family test) — you can't add hypothetical density to a tower.
        var st = (state.detected || {}).structure;
        var alreadyMulti = !!(st && (st.structure_type === "multifamily"
          || (st.num_units && st.num_units > 1)));
        densWrap.hidden = !(state.mode === "detected" && state.detected) || alreadyMulti;
      }
    }

    // ── density comparison (fixed lot, vary units — Detected mode) ──────────────
    function renderDensity(data) {
      var scn = (data && data.scenarios) || [];
      if (!scn.length) { densResult.innerHTML = ""; return; }
      var head = '<tr><th>Metric</th>' + scn.map(function (s) {
        return '<th>' + esc(s.name) + '<br><small>' + esc(s.units) + (s.units === 1 ? " unit" : " units") + '</small></th>';
      }).join("") + '</tr>';
      function row(label, fn) {
        return '<tr><td><strong>' + label + '</strong></td>'
          + scn.map(function (s) { return '<td>' + fn(s) + '</td>'; }).join("") + '</tr>';
      }
      var rows = "";
      rows += row("Total value", function (s) { return s.value == null ? "—" : "$" + Math.round(s.value).toLocaleString(); });
      rows += row("Per-unit value", function (s) { return s.per_unit_value == null ? "—" : "$" + Math.round(s.per_unit_value).toLocaleString(); });
      rows += row("Density (DU/acre)", function (s) { return s.per_unit_acres ? (1 / s.per_unit_acres).toFixed(1) : "—"; });
      rows += row("Infrastructure", function (s) { return s.infrastructure_score == null ? "—" : s.infrastructure_score.toFixed(0) + " " + gradeSpan(s.infrastructure_grade); });
      rows += row("Fiscal ratio", function (s) { return s.fiscal_ratio == null ? "—" : s.fiscal_ratio.toFixed(2); });
      rows += row("Energy", function (s) { return s.energy_score == null ? "—" : s.energy_score.toFixed(0); });
      rows += row("Energy / unit / mo", function (s) { return s.est_monthly_energy_cost == null ? "—" : "$" + Math.round(s.est_monthly_energy_cost); });
      rows += row("Composite", function (s) { return s.composite_score == null ? "—" : s.composite_score.toFixed(0) + " " + gradeSpan(s.composite_national_grade); });
      rows += row("Property tax / acre", function (s) { return s.revenue_per_acre == null ? "—" : "$" + Math.round(s.revenue_per_acre).toLocaleString() + "/ac"; });
      rows += row("Net fiscal / acre", function (s) {
        return s.net_fiscal_per_acre == null ? "—"
          : (s.net_fiscal_per_acre < 0 ? "−$" + Math.round(-s.net_fiscal_per_acre).toLocaleString()
                                       : "$" + Math.round(s.net_fiscal_per_acre).toLocaleString()) + "/ac"; });
      var html = '<table class="comparison density-table"><thead>' + head + '</thead><tbody>' + rows + '</tbody></table>';
      var dd = data.density_dividend || {};
      if (dd.fiscal_ratio_from != null && dd.fiscal_ratio_to != null) {
        html += '<div class="insight"><strong>The density dividend:</strong> going from '
          + esc(dd.from_units) + ' to ' + esc(dd.to_units) + ' unit' + (dd.to_units === 1 ? "" : "s")
          + ' on this same lot moves the fiscal ratio ' + dd.fiscal_ratio_from.toFixed(2)
          + ' &rarr; ' + dd.fiscal_ratio_to.toFixed(2) + ' and Infrastructure Burden '
          + gradeSpan(dd.infrastructure_grade_from) + ' &rarr; ' + gradeSpan(dd.infrastructure_grade_to)
          + '. Same land &amp; services, shared across more homes.';
        if (dd.revenue_per_acre_from && dd.revenue_per_acre_to) {
          html += ' It also generates <strong>' + (dd.revenue_per_acre_to / dd.revenue_per_acre_from).toFixed(1)
            + '&times; the property-tax revenue per acre</strong> ($'
            + Math.round(dd.revenue_per_acre_from).toLocaleString() + ' &rarr; $'
            + Math.round(dd.revenue_per_acre_to).toLocaleString()
            + '/acre) on the same land &mdash; the value-per-acre dividend.';
        }
        html += '</div>';
      }
      if (data.value_source) {
        html += '<p class="meta" style="font-size:0.8rem;">Per-unit value auto-filled from the '
          + 'county median (ACS); total value scales with the number of units.</p>';
      }
      (data.caveats || []).forEach(function (c) {
        html += '<div class="insight warn" style="margin-top:0.6rem;font-size:0.82rem;">' + esc(c) + '</div>';
      });
      densResult.innerHTML = html;
    }
    if (densBtn) densBtn.addEventListener("click", function () {
      if (!API_BASE || !state.detectedQuery) return;
      densResult.innerHTML = "";
      densStatus.textContent = "Comparing densities on this parcel …"; densStatus.style.display = "";
      densBtn.disabled = true;
      fetch(API_BASE + "/density?" + state.detectedQuery)
        .then(okJson)
        .then(function (data) { densStatus.style.display = "none"; renderDensity(data); })
        .catch(function (err) { densStatus.textContent = "Could not compare densities: " + err.message; })
        .finally(function () { densBtn.disabled = false; });
    });

    // ── refine panel ────────────────────────────────────────────────────────────
    var TAG_LABEL = { confirmed: "you edited", estimated: "estimated", assumed: "default" };
    // The refine panel only makes sense in Detected mode AND when there's an API to
    // re-score against — without one it would be an empty, non-functional control.
    function syncRefineVisibility() {
      refineEl.style.display = (API_BASE && state.mode === "detected" && !state.idle) ? "" : "none";
    }
    function applyBuilding(building) {
      var estimated = 0, total = 0;
      FIELDS.forEach(function (f) {
        var el = fieldEl(f.key), tag = q('[data-tag="' + f.key + '"]'), info = building && building[f.key];
        if (!el || !tag) return;
        if (!info) { tag.className = "field-tag"; tag.textContent = ""; if (document.activeElement !== el) el.value = ""; return; }
        total++;
        var status = touched[f.key] ? "confirmed" : info.status;
        if (status === "estimated") estimated++;
        if (document.activeElement !== el) el.value = info.value == null ? "" : info.value;
        tag.className = "field-tag " + status;
        tag.textContent = TAG_LABEL[status] || status;
        tag.title = (info.source || "") + (info.confidence ? " · " + info.confidence + " confidence" : "");
      });
      refineCount.textContent = total ? "— " + estimated + " of " + total + " estimated from public data (edit any to refine)" : "";
      if (total && !refineEl.open) refineEl.open = true;
    }
    function buildDetectedParams() {
      var params = new URLSearchParams(), d = state.desc, edited = false;
      if (d && d.lat != null) { params.set("lat", d.lat); params.set("lon", d.lon); }
      else if (d && d.address) { params.set("address", d.address); }
      else { params.set("lat", DEFAULT_LAT); params.set("lon", DEFAULT_LON); }
      FIELDS.forEach(function (f) {
        if (!touched[f.key]) return;
        var el = fieldEl(f.key), v = el.value != null ? el.value : "";
        v = v.trim ? v.trim() : v;
        if (v !== "") { params.set(f.key, v); edited = true; }
      });
      var ups = qa(".addr-upgrades input:checked").map(function (c) { return c.value; });
      if (ups.length) params.set("upgrades", ups.join(","));
      var qs = params.toString();
      return { qs: qs ? "?" + qs : "", query: qs,
               ctx: { isCustom: edited || ups.length > 0,
                      upgradeLabels: ups.map(function (v) { return LC.UPGRADE_LABELS[v] || v; }) } };
    }

    // ── data loading ────────────────────────────────────────────────────────────
    function fail(seq) { return function (err) { if (seq === reqSeq) { state.error = err.message; state.errorStatus = err.status || 0; render(); } }; }
    function persistLocation() { if (persist) { syncUrl(state.desc || null); saveLast(state.desc || null); } }

    function loadPresets() {
      if (state.presets) { render(); return; }
      if (!API_BASE) { return; }
      var seq = ++reqSeq; state.error = null; render();
      fetch(API_BASE + "/presets" + descQuery(state.desc))
        .then(okJson)
        .then(function (data) {
          if (seq !== reqSeq) return;
          var ps = (data && data.presets) || [];
          if (!ps.length) throw new Error("no presets returned");
          state.presets = ps; applyDefaults();
          state.idx = clampIdx(state.idx); state.idxA = clampIdx(state.idxA); state.idxB = clampIdx(state.idxB);
          persistLocation(); render();
        })
        .catch(fail(seq));
    }
    function loadDetected(force) {
      if (state.detected && !force) { render(); applyBuilding(state.building); return; }
      if (!API_BASE) { return; }
      var seq = ++reqSeq; state.error = null;
      if (!state.detected) render();
      var built = buildDetectedParams();
      fetch(API_BASE + "/label" + built.qs)
        .then(okJson)
        .then(function (data) {
          if (seq !== reqSeq) return;
          state.detected = data; state.building = data.building || null;
          state.detectedCtx = built.ctx; state.detectedQuery = built.query;
          persistLocation(); render(); applyBuilding(state.building);
        })
        .catch(fail(seq));
    }
    function ensureData() { if (state.mode === "detected") loadDetected(false); else loadPresets(); }
    function load(desc) {
      state.idle = false;               // a location was requested — leave the prompt state
      state.desc = desc || null;
      state.presets = null; state.detected = null; state.building = null;
      state.detectedCtx = null; state.detectedQuery = "";
      touched = {}; applyBuilding(null);
      qa(".addr-upgrades input").forEach(function (cb) { cb.checked = false; });
      if (densResult) densResult.innerHTML = "";
      syncRefineVisibility();           // reveal the refine panel now that we're scoring
      ensureData();
    }
    // Return to the pre-scoring prompt (Reset) — clears the scored result and any
    // in-flight response rather than re-scoring a default location.
    function resetToIdle() {
      reqSeq++;                         // invalidate any in-flight response
      state.idle = true; state.error = null; state.desc = null;
      state.presets = null; state.detected = null; state.building = null;
      state.detectedCtx = null; state.detectedQuery = "";
      touched = {}; applyBuilding(null);
      qa(".addr-upgrades input").forEach(function (cb) { cb.checked = false; });
      if (densResult) densResult.innerHTML = "";
      syncRefineVisibility(); render();
    }
    function applyDefaults() {
      if (state.initialized) return;
      var base = findIdx(/baseline/i), cheap = findIdx(/icf|passive/i);
      if (base >= 0) state.idxA = base;
      if (cheap >= 0) { state.idx = cheap; state.idxB = cheap; }
      else if (state.presets.length > 1) state.idxB = state.presets.length - 1;
      state.initialized = true;
    }

    // ── location descriptors, URL sync, remembered location ─────────────────────
    function coord(lat, lon) {
      var la = parseFloat(lat), lo = parseFloat(lon);
      if (isFinite(la) && isFinite(lo) && Math.abs(la) <= 90 && Math.abs(lo) <= 180) return { lat: la, lon: lo };
      return null;
    }
    function descQuery(desc) {
      if (desc && desc.lat != null && desc.lon != null)
        return "?lat=" + encodeURIComponent(desc.lat) + "&lon=" + encodeURIComponent(desc.lon);
      if (desc && desc.address) return "?address=" + encodeURIComponent(desc.address);
      return "";
    }
    function descFromUrl() {
      var p; try { p = new URLSearchParams(location.search); } catch (e) { return null; }
      var c = coord(p.get("lat"), p.get("lon"));
      if (c) return c;
      var a = p.get("address");
      return a && a.trim() ? { address: a.trim() } : null;
    }
    function syncUrl(desc) {
      if (!window.history || !history.replaceState) return;
      var params; try { params = new URLSearchParams(location.search); } catch (e) { return; }
      params.delete("address"); params.delete("lat"); params.delete("lon");
      if (desc && desc.lat != null && desc.lon != null) { params.set("lat", desc.lat); params.set("lon", desc.lon); }
      else if (desc && desc.address) { params.set("address", desc.address); }
      var qs = params.toString();
      try { history.replaceState(null, "", location.pathname + (qs ? "?" + qs : "") + location.hash); } catch (e) {}
    }
    function saveLast(desc) {
      try {
        if (desc && (desc.address || (desc.lat != null && desc.lon != null))) localStorage.setItem(LS_KEY, JSON.stringify(desc));
        else localStorage.removeItem(LS_KEY);
      } catch (e) {}
    }
    function loadLast() {
      try {
        var d = JSON.parse(localStorage.getItem(LS_KEY));
        if (d && d.address && String(d.address).trim()) return { address: String(d.address).trim() };
        var c = coord(d && d.lat, d && d.lon);
        // Carry a picked suggestion's address label so a coord-only descriptor can
        // still pre-fill the box on the next visit (it has no `address` text).
        if (c) { if (d && d.label) c.label = String(d.label); return c; }
      } catch (e) {}
      return null;
    }

    // ── events ────────────────────────────────────────────────────────────────
    app.addEventListener("click", function (e) {
      var b = e.target.closest ? e.target.closest("button[data-mode]") : null;
      if (b) setMode(b.getAttribute("data-mode"));
    });
    app.addEventListener("change", function (e) {
      var t = e.target;
      if (t.classList.contains("lf-p-sel")) state.idx = +t.value;
      else if (t.classList.contains("lf-a-sel")) state.idxA = +t.value;
      else if (t.classList.contains("lf-b-sel")) state.idxB = +t.value;
      else return;
      render();
    });
    function setMode(m) {
      if (m === state.mode || modes.indexOf(m) < 0) return;
      state.mode = m; state.error = null;
      syncRefineVisibility(); ensureData();
    }

    FIELDS.forEach(function (f) {
      var el = fieldEl(f.key);
      if (!el) return;
      el.addEventListener("change", function () {
        var v = (el.value || "").trim();
        var noop = (v === "") || (f.key === "units" && Number(v) <= 1);
        if (noop) delete touched[f.key]; else touched[f.key] = true;
        if (state.mode === "detected") loadDetected(true);
      });
    });
    qa(".addr-upgrades input").forEach(function (cb) {
      cb.addEventListener("change", function () { if (state.mode === "detected") loadDetected(true); });
    });

    function geoStatus(msg, isError) {
      geoEl.textContent = msg || "";
      geoEl.style.display = msg ? "" : "none";
      geoEl.classList.toggle("err", !!isError);
    }
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      if (!API_BASE) { noteEl.style.display = ""; return; }
      ac.close(); geoStatus("");
      var addr = addrInput.value.trim(), p = ac.picked();
      if (p && p.label === addr) { load({ lat: p.lat, lon: p.lon, label: p.label }); return; }
      if (addr) { load({ address: addr }); return; }
      // Empty submit: nudge for input instead of scoring an unchosen default —
      // scoring DEFAULT_LAT/LON here would undo the "wait for input" behavior.
      addrInput.focus();
      geoStatus("Enter a U.S. address or place name to score"
        + (wantGeo ? ", or use your location." : "."), false);
    });
    if (resetBtn) resetBtn.addEventListener("click", function () {
      ac.close(); addrInput.value = ""; geoStatus("");
      syncUrl(null); saveLast(null);
      resetToIdle();
    });
    if (locateBtn) locateBtn.addEventListener("click", function () {
      if (!navigator.geolocation) { geoStatus("Your browser doesn't support location sharing.", true); return; }
      geoStatus("Locating…"); locateBtn.disabled = true;
      navigator.geolocation.getCurrentPosition(
        function (pos) {
          locateBtn.disabled = false; geoStatus(""); ac.close(); addrInput.value = "";
          // No label here: "your location" isn't a re-typable address, so it must
          // not be persisted as pre-fill text for the next visit.
          load({ lat: pos.coords.latitude, lon: pos.coords.longitude });
        },
        function (err) {
          locateBtn.disabled = false;
          geoStatus(err && err.code === 1
            ? "Location permission denied — enter an address instead."
            : "Couldn't get your location — enter an address instead.", true);
        },
        { enableHighAccuracy: false, timeout: 10000, maximumAge: 600000 }
      );
    });

    // ── init ────────────────────────────────────────────────────────────────────
    syncRefineVisibility();
    if (!API_BASE) { render(); return; }   // no endpoint: markup + disclosure only
    // Only an explicit shared/bookmarked link (?lat,lon or ?address=) auto-scores
    // on load — that's a deliberate deep link. A fresh visit (or just a remembered
    // last location) shows the prompt instead of auto-scoring something unasked-for.
    var urlDesc = descFromUrl();
    var lastDesc = persist ? loadLast() : null;
    // Pre-fill the address box for convenience (so the user can just hit "Score
    // it"), but don't score it automatically.
    var prefill = urlDesc || lastDesc;
    // Pre-fill from the typed address or a picked suggestion's remembered label
    // (coord deep links / geolocation have no re-typable text and stay empty).
    var prefillText = prefill ? (prefill.address || prefill.label || "") : "";
    if (prefillText) addrInput.value = prefillText;
    if (urlDesc) load(urlDesc);            // deep link → score it now
    else render();                         // fresh visit → idle prompt, awaiting input
  }

  return { mount: mount };
})();
