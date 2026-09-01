/*
 * label-form.js — the unified scoring widget for Housing Nutrition Label.
 *
 * One module used by every "score an address" surface (home, examples, label).
 * It owns the WHOLE interactive scoring UI: API-endpoint resolution + privacy
 * disclosure, the address input + autocomplete, the Detected / Single / Compare
 * view modes, the "Refine building details" auto-fill panel, the optional
 * density-on-this-parcel comparison (on the real home, or on a hypothetical
 * construction profile), deep-linking, shareable-URL sync, remembered last
 * location, "use my location", and the busy/confirmation states that bracket
 * every request. Rendering of the label card itself stays in label-core.js
 * (LabelCore); autocomplete stays in AddrSuggest.
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
 * "buildDensity" — the density sweep run on a hypothetical construction profile
 * rather than the real home — is the two what-ifs combined, so it needs both
 * halves: it appears automatically when a widget offers "single" AND density,
 * and can also be named in `modes` outright.
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
      ["steel", "Steel frame / steel wall"],
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
      attrs: 'min="0.01" max="10000" step="0.01" placeholder="e.g. 0.18 — or 40 for a farm"' },
    { key: "lot_context", label: "Lot context", type: "select", options: [
      ["", "(detected)"], ["rural", "Rural / unincorporated"],
      ["suburban", "Suburban"], ["urban", "Urban"]] },
    { key: "units", label: "Dwelling units", type: "number",
      attrs: 'min="1" max="500" step="1" placeholder="1 (house), 4 (quadplex)"' },
    { key: "bldg_material", label: "Building material", type: "select", options: [
      ["", "(if a multi-unit building)"], ["wood", "Wood frame"], ["masonry", "Load-bearing masonry"],
      ["concrete", "Reinforced concrete"], ["steel", "Steel frame"]] },
    { key: "stories", label: "Stories", type: "number",
      attrs: 'min="1" max="150" step="1" placeholder="floors"' },
    { key: "water_source", label: "Drinking water", type: "select", options: [
      ["", "(public water)"], ["public", "Public / community system"],
      ["well", "Private well"]] },
    { key: "sewer", label: "Wastewater", type: "select", options: [
      ["", "(public sewer)"], ["public", "Public sewer"], ["septic", "Septic system"]] }
  ];
  var UPGRADES = [
    ["solar", "Solar panels"], ["backup_generator", "Backup generator / battery"],
    ["fire_sprinklers", "Fire sprinklers"], ["hurricane_straps", "Hurricane straps"],
    ["fortified_roof", "FORTIFIED roof"], ["tornado_safe_room", "Tornado safe room"],
    ["seismic_retrofit", "Seismic retrofit"], ["flood_vents", "Flood vents"],
    ["radon_mitigation", "Radon mitigation system"]
  ];
  // Toggle labels + a one-line explanation of what each view actually scores.
  // The old "Detected / Single / Compare" gave no hint of the difference; these
  // say it in plain terms (the real home vs. hypothetical construction profiles).
  // "What-if denser" is the old free-floating "Compare densities on this parcel"
  // button: it is another view of the same address, so it belongs in this group
  // with the rest rather than orphaned below the card, and it inherits the
  // group's plain-language caption instead of having to explain itself.
  // "What-if build + denser" is the two hypotheticals at once — a construction
  // profile (from What-if build) re-scored at several unit counts (from What-if
  // denser). It sits last because it composes the two views before it.
  // "Over time" sits last because it is the only view that answers a question
  // about change rather than about a choice: everything above it re-scores a
  // hypothetical, this one holds the address fixed and moves the clock.
  var MODE_LABELS = {
    detected: "This home",
    single: "What-if build",
    compare: "Compare builds",
    density: "What-if denser",
    buildDensity: "What-if build + denser",
    timeline: "Over time"
  };
  var MODE_HELP = {
    detected: "Scores the real home at this address, using building details "
      + "pulled from public records. Edit any detail under “Refine building "
      + "details” to correct it and the label updates.",
    single: "Scores one hypothetical construction profile at this location — "
      + "pick a build type to see how construction choices alone move each "
      + "dimension. The home’s real details are ignored here.",
    compare: "Scores two hypothetical construction profiles side by side at this "
      + "location, with the per-dimension difference between them.",
    density: "Re-scores this same lot with more homes on it — one house, a duplex, "
      + "a fourplex — so you can see how sharing the same streets, pipes, and "
      + "services across more homes moves the cost per home and the Infrastructure "
      + "Burden grade. The building itself stays as it is.",
    buildDensity: "Both what-ifs at once: pick a construction profile, then "
      + "re-score this lot with more homes of that build on it — one house, a "
      + "duplex, a fourplex. Shows how the build type and the number of homes "
      + "move the cost per home and the Infrastructure Burden grade together. "
      + "The home’s real details are ignored here.",
    // Says what the view IS. The claim every number in it rests on — that the
    // scale is held fixed — is stated once by the panel's own legend, which
    // comes from the API, so repeating it here would put the same sentence on
    // screen twice.
    timeline: "Holds this address fixed and moves the clock instead: how the "
      + "climate here is projected to shift, and how the building’s own grade "
      + "changes as it ages. Dimensions with no time series are listed at the "
      + "bottom with the reason why."
  };
  var SUPPORTED_MODES = ["detected", "single", "compare", "density", "buildDensity",
                         "timeline"];
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

  // The panel used to assert one sourcing story for every label. Which one is true
  // depends on whether an assessor adapter answered for this address — adapters
  // are off unless deployed with ASSESSOR_ADAPTERS, and even on they cover two
  // counties and two states — so promising a "county parcel record" to every reader
  // describes something most of them are not getting. The line is chosen per label
  // instead.
  var HINT_ESTIMATED = "We estimate these from public data (USACE structure records "
    + "+ Census) and score with them.";
  var HINT_OBSERVED = "Some of these are your county's own parcel record; the rest we "
    + "estimate from public data (USACE structure records + Census). We score with both.";

  function refineHtml() {
    return '<details class="addr-details lf-refine" style="max-width:640px;margin:0 auto 1rem;display:none;">'
      + '<summary><span>Refine building details</span> <span class="refine-count lf-refine-count"></span></summary>'
      + '<p class="addr-hint lf-refine-hint" style="margin:0 0 0.5rem;font-size:0.82rem;opacity:0.85;">'
      + HINT_ESTIMATED + ' '
      + 'Anything looks off? Edit it and the label updates. Living area is <strong>per unit</strong>.</p>'
      + '<div class="addr-fields">' + FIELDS.map(fieldHtml).join("") + '</div>'
      + '<fieldset class="addr-upgrades"><legend>Resilience upgrades</legend>'
      + UPGRADES.map(function (u) {
          return '<label><input type="checkbox" value="' + u[0] + '"> ' + esc(u[1]) + '</label>';
        }).join("")
      + '</fieldset></details>'
      // Outside the <details> on purpose. The panel deliberately stays collapsed
      // after a score (see applyBuilding), so anything inside it is invisible to a
      // reader who never opens it — and this note is the one thing that tells them
      // opening it is worth their time. Hidden until there is something to say.
      + '<p class="lf-yb-note" style="max-width:640px;margin:-0.5rem auto 1rem;'
      + 'font-size:0.82rem;line-height:1.45;opacity:0.9;display:none;"></p>';
  }

  function formHtml(opts) {
    var lb = opts.listboxId;   // links the combobox input ↔ its suggestions listbox
    var uid = opts.uid;
    // Two rows by design. The field and its primary action ("Score this address")
    // stay on one row so the submit sits with the input it acts on. The
    // alternate/clear actions group on a second row, kept subordinate to the
    // primary and never orphan-wrapping beneath the field the way a single shared
    // row did on mid-width screens.
    //
    // Every button says what it does to the *label*, not to the form: a bare
    // "Reset" gave no hint of what it would throw away. Each also carries a
    // one-line description — `title` for pointers, aria-describedby for screen
    // readers — so the effect is knowable before the click, not after it.
    function hint(id, text) { return '<span id="' + id + '" class="lf-sr-only">' + esc(text) + '</span>'; }
    var secondary = "", hints = "";
    if (opts.geolocate) {
      var gh = uid + "locate-h", gt = "Scores where you are now instead of a typed address. Your browser asks permission first.";
      secondary += '<button type="button" class="reset lf-locate" title="' + esc(gt) + '" aria-describedby="' + gh + '">Use my location</button>';
      hints += hint(gh, gt);
    }
    if (opts.persist) {
      var rh = uid + "reset-h", rt = "Clears the address and the label on screen, and forgets this location for next time.";
      secondary += '<button type="button" class="reset lf-reset" title="' + esc(rt) + '" aria-describedby="' + rh + '">Start over</button>';
      hints += hint(rh, rt);
    }
    // Take-it-with-you, in the same row rather than under the card. A label runs
    // several phone screens, so a control at its foot is a control nobody scrolls
    // to — and both of these act on the whole label, which is exactly what this
    // row is for. They are the only buttons here that need something to already
    // exist, so they ship unavailable and syncActions() switches them on when
    // there is a label to act on.
    //
    // `aria-disabled`, not the `disabled` attribute. A disabled button is out of
    // the tab order, so a keyboard or screen-reader user would never meet these
    // two — nor the descriptions below that say what they do — until after a
    // label existed. That is the opposite of the point: the row is meant to show
    // what a label will let you do before you have one, and dimming a control
    // only sighted readers can find is showing it to half the audience. They stay
    // focusable and announce themselves as unavailable; the click handler is what
    // makes them inert, and says why. (The form's own buttons keep the real
    // attribute: a submit that is mid-request must be genuinely uninvokable, and
    // it was already discoverable.)
    var ph = uid + "print-h", pt = "Prints the label below. The controls drop out, and the printed sheet carries its source and date.";
    secondary += '<button type="button" class="reset lf-print" aria-disabled="true" title="' + esc(pt) + '" aria-describedby="' + ph + '">Print label</button>';
    hints += hint(ph, pt);
    var vh = uid + "svg-h", vt = "Downloads the label below as a one-page SVG: vector, prints at any size, opens in any browser or design tool.";
    secondary += '<button type="button" class="reset lf-svg" aria-disabled="true" title="' + esc(vt) + '" aria-describedby="' + vh + '">Save as SVG</button>';
    hints += hint(vh, vt);
    secondary += '<span class="lf-actions-note" role="status" aria-live="polite"></span>';
    var sh = uid + "go-h", stt = "Looks up the address in the box and scores it across all thirteen dimensions.";
    return '<form class="label-addr-form lf-form">'
      + '<div class="addr-primary">'
      + '<div class="addr-ac" role="combobox" aria-haspopup="listbox" aria-expanded="false" aria-owns="' + lb + '">'
      + '<input type="text" class="lf-addr" aria-label="US address or place name to score" autocomplete="off" '
      + 'role="textbox" aria-autocomplete="list" aria-controls="' + lb + '" aria-activedescendant="" '
      + 'placeholder="Enter a U.S. address or place name &mdash; e.g. 111 S Grand Ave, Los Angeles">'
      + '<ul class="addr-suggest lf-suggest" id="' + lb + '" role="listbox" hidden></ul></div>'
      + '<button type="submit" class="go" title="' + esc(stt) + '" aria-describedby="' + sh + '">Score this address</button></div>'
      + (secondary ? '<div class="addr-actions">' + secondary + '</div>' : '')
      + hint(sh, stt) + hints
      + '</form>'
      + '<p class="label-privacy lf-geo" role="status" aria-live="polite" style="display:none;"></p>'
      + '<p class="label-privacy lf-privacy" style="display:none;"></p>'
      // Shown the moment a non-residential suggestion is picked, so the reader knows
      // it won't score *before* pressing "Score it" (not only via the 422 after).
      + '<div class="insight warn lf-poi-hint" role="status" aria-live="polite" style="display:none;max-width:640px;margin:-0.5rem auto 1rem;"></div>'
      + '<div class="insight warn lf-warn" style="display:none;max-width:640px;margin:-0.5rem auto 1rem;"></div>'
      + '<div class="insight lf-note" style="display:none;max-width:640px;margin:0 auto 1rem;">'
      + 'Set a scoring API to run live scores — append <code>?api=&lt;your-endpoint&gt;</code> to the URL '
      + 'or configure <code>window.HOUSING_LABEL_API</code>.</div>';
  }

  // The density comparison's own panel. It has no button of its own any more —
  // the "What-if denser" entry in the mode toggle is the control, and this panel
  // is its result. It stays a sibling of .lf-app (rather than markup inside it)
  // so its status banner and table survive .lf-app's re-renders; in density mode
  // .lf-app holds only the caption + toggle, which puts this directly beneath the
  // buttons that opened it.
  function densityHtml() {
    return '<div class="lf-density-wrap" hidden>'
      + '<div class="lf-status lf-density-status" role="status" aria-live="polite" hidden></div>'
      + '<div class="lf-density-result"></div></div>';
  }

  // The in-place "a label is coming" panel: a shimmering outline of the card
  // being built, shown wherever there's no previous card to keep on screen. It
  // carries no words — the status banner right above it says what's happening,
  // and repeating the sentence twice in a row just read as noise.
  function loadingHtml() {
    var rows = [96, 88, 92, 80, 90].map(function (w) {
      return '<span class="lf-skel-row" style="width:' + w + '%"></span>';
    }).join("");
    return '<div class="lf-loading" aria-hidden="true">'
      + '<div class="lf-skel">'
      + '<div class="lf-skel-head"><span class="lf-skel-num"></span><span class="lf-skel-grade"></span></div>'
      + rows + '</div></div>';
  }

  // The density panel's own waiting state: a ghost of the table that's coming,
  // shown only when there's no previous table to keep on screen. Same shimmer
  // pieces as the card skeleton, arranged as rows of a comparison table.
  function densitySkeleton() {
    var rows = [92, 84, 88, 80, 86, 78].map(function (w) {
      return '<span class="lf-skel-row" style="width:' + w + '%"></span>';
    }).join("");
    return '<div class="lf-loading" aria-hidden="true"><div class="lf-skel">'
      + '<div class="lf-skel-head"><span class="lf-skel-num"></span>'
      + '<span class="lf-skel-grade"></span></div>' + rows + '</div></div>';
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
    // Density is a view of the same parcel, so it joins the toggle rather than
    // sitting as a lone button under the card. Last in the row keeps the two
    // "what-if" views next to each other. `density: true` stays the page-facing
    // switch; naming it in `modes` works too.
    var wantSweep = !!opts.density || modes.indexOf("density") >= 0;
    if (wantSweep && modes.indexOf("density") < 0) modes.push("density");
    // The combined view is the density sweep applied to a construction profile,
    // so it needs both halves present: a page that already offers "What-if
    // build" and the sweep gets it for free, and naming it in `modes` works too.
    var wantBuildDensity = modes.indexOf("buildDensity") >= 0
      || (wantSweep && modes.indexOf("single") >= 0);
    if (wantBuildDensity && modes.indexOf("buildDensity") < 0) modes.push("buildDensity");
    // Either sweep view paints into the density panel, so the panel (and its
    // status banner) exists whenever one of them is on the toggle.
    var wantDensity = wantSweep || wantBuildDensity;
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

    // Build the widget markup. The density panel trails .lf-app so that in
    // density mode — where .lf-app renders only the caption and the view toggle —
    // its table lands right under the buttons. The busy/confirmation banner sits
    // directly above the result area so the start and the finish of a score both
    // land where the reader is looking.
    root.innerHTML = formHtml({ geolocate: wantGeo, persist: persist, uid: uid, listboxId: uid + "listbox" })
      + refineHtml()
      + '<div class="lf-status lf-main-status" role="status" aria-live="polite" hidden></div>'
      + '<div class="lf-app">' + loadingHtml() + '</div>'
      + (wantDensity ? densityHtml() : "");

    // Element refs (scoped to this widget's root — no global IDs).
    function q(sel) { return root.querySelector(sel); }
    function qa(sel) { return Array.prototype.slice.call(root.querySelectorAll(sel)); }
    var app = q(".lf-app");
    var form = q(".lf-form"), addrInput = q(".lf-addr"), goBtn = q(".lf-form .go");
    var geoEl = q(".lf-geo"), privEl = q(".lf-privacy"), warnEl = q(".lf-warn"), noteEl = q(".lf-note");
    var poiHintEl = q(".lf-poi-hint");
    var refineEl = q(".lf-refine"), refineCount = q(".lf-refine-count");
    var ybNote = q(".lf-yb-note");
    var densWrap = wantDensity ? q(".lf-density-wrap") : null;
    var densResult = wantDensity ? q(".lf-density-result") : null;
    var locateBtn = wantGeo ? q(".lf-locate") : null;
    var resetBtn = persist ? q(".lf-reset") : null;
    var printBtn = q(".lf-print"), svgBtn = q(".lf-svg");

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

    // Pre-score heads-up: when the picked suggestion is a non-residential POI (a
    // stadium/office/store the geocoder flagged), tell the reader it won't score
    // *now*, not only after they press "Score it". Editing (onPick null) clears it.
    function showPoiHint(s) {
      if (s && s.residential === false) {
        var name = (s.label || "").split(",")[0];
        poiHintEl.innerHTML = '<strong>' + esc(name || "This place")
          + '</strong> looks like a business or venue, not a home &mdash; the label scores '
          + 'residential addresses only, so it won’t be graded.';
        poiHintEl.style.display = "";
      } else {
        poiHintEl.style.display = "none";
      }
    }
    var ac = AS.attach({ input: addrInput, box: q(".lf-suggest"), apiBase: API_BASE,
                         idPrefix: uid + "opt-", onPick: showPoiHint });

    // View state. `presets`/`detected` are cached per location so switching modes
    // doesn't refetch; `desc` is the current location descriptor.
    // `idle` is the pre-scoring state: on a fresh visit the widget waits for the
    // user to enter an address (or use their location) instead of auto-scoring a
    // default — auto-scoring a place nobody asked for read as confusing. A shared
    // deep link (?address / ?lat,lon) clears it and scores immediately.
    // `density` caches the sweep on the real home; `densityBuilds` caches one
    // sweep per construction profile (keyed by preset slug), so flipping between
    // profiles — or back to a profile already seen — repaints without refetching.
    // `profiles` is the construction-profile roster: names and slugs only, the
    // same for every address, so unlike everything else here it survives a change
    // of location and is fetched at most once per page.
    var state = { mode: modes[0], idx: 0, idxA: 0, idxB: 0,
                  presets: null, profiles: null, buildSlug: null,
                  detected: null, building: null, detectedCtx: null,
                  density: null, densityBuilds: {}, timeline: null,
                  desc: null, error: null, initialized: false, idle: true };
    var touched = {};                 // field key -> true once the user edits it
    var reqSeq = 0;                   // drop out-of-order responses from rapid submits

    // ── helpers ────────────────────────────────────────────────────────────────
    function clone(o) { var c = {}, h = Object.prototype.hasOwnProperty; for (var k in o) if (h.call(o, k)) c[k] = o[k]; return c; }
    function findIdx(re) { for (var i = 0; i < state.presets.length; i++) if (re.test(state.presets[i].name)) return i; return -1; }
    function clampIdx(i) { return Math.max(0, Math.min(i, state.presets.length - 1)); }
    // ── No scoring request waits forever ────────────────────────────────────────
    // A label is a dozen federal datasets fetched live, and the API's own budget
    // lets a single stuck upstream cost tens of seconds — several of them, minutes.
    // Without a deadline here the page just kept saying "Still working", which is
    // the one thing it could say that was not useful: the reader cannot tell a slow
    // score from a dead one, and has nothing to do but wait or leave. After this
    // long we stop, say what happened, and offer the retry that the spinner never
    // did. 45s is past a normal cold score (a few seconds warm, ~15s cold) and well
    // short of the minutes a wedged upstream can take.
    //
    // This is now the backstop rather than the fix. The API stops paying for a
    // dataset that has used its share of a score (config.UPSTREAM_HOST_BUDGET) and
    // for a score that has used its wall clock (config.UPSTREAM_BUDGET), so the
    // one-slow-dataset case — the case this deadline was written for — comes back
    // as a complete answer with a few N/A rows and slowDataNote() above them, well
    // inside 45s. Reaching this now means something bigger: the API itself is cold
    // or down, or the reader's own connection is gone.
    var SCORE_TIMEOUT_MS = 45000;
    function fetchScoring(url) {
      if (typeof AbortController !== "function") return fetch(url);   // pre-2017 browser
      var ctl = new AbortController(), expired = false;
      var timer = setTimeout(function () { expired = true; ctl.abort(); }, SCORE_TIMEOUT_MS);
      var pending;
      try {
        pending = fetch(url, { signal: ctl.signal });
      } catch (err) {
        // fetch() throws synchronously on a malformed URL or a bad init — rare,
        // but it would leave the timer above running for 45 seconds, and one per
        // attempt if the reader keeps trying.
        clearTimeout(timer);
        throw err;
      }
      return pending.then(
        function (r) { clearTimeout(timer); return r; },
        function (err) {
          clearTimeout(timer);
          if (!expired) throw err;          // a real network error, not our deadline
          var e = new Error("the scoring API didn't answer within "
            + Math.round(SCORE_TIMEOUT_MS / 1000) + " seconds");
          e.status = 0; e.timedOut = true;
          throw e;
        });
    }
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

    // ── busy / done status banner ───────────────────────────────────────────────
    // Scoring is a multi-second round trip (geocode, then a dozen federal
    // datasets), and the only signal used to be one grey "Scoring this address…"
    // line — quiet enough to miss, and nothing at all marked the finish. Every
    // request now opens with a spinner and a moving bar, and closes with a green
    // confirmation that fades out on its own. The banner is a single aria-live
    // region, so screen readers get the same start/finish beats.
    var SLOW_MS = 6000;    // how long before the banner admits it's taking a while
    var DONE_MS = 7000;    // how long the confirmation stays before fading out
    var SLOW_TEXT = "Still working — pulling federal datasets for this location.";
    function makeStatus(el) {
      var slowT = null, doneT = null, fadeT = null;
      var base = el.className;   // the element's own classes survive every repaint
      function stopTimers() {
        clearTimeout(slowT); clearTimeout(doneT); clearTimeout(fadeT);
        slowT = doneT = fadeT = null;
      }
      function paint(kind, icon, msg, sub) {
        el.className = base + " " + kind;
        el.innerHTML = '<div class="lf-status-row">' + icon
          + '<span class="lf-status-text"><strong>' + esc(msg) + '</strong>'
          + '<span class="lf-status-sub">' + esc(sub || "") + '</span></span></div>'
          + (kind === "busy" ? '<span class="lf-bar" aria-hidden="true"><span></span></span>' : "");
        el.hidden = false;
      }
      return {
        busy: function (msg, sub) {
          stopTimers();
          paint("busy", '<span class="lf-spinner" aria-hidden="true"></span>', msg, sub);
          slowT = setTimeout(function () { el.querySelector(".lf-status-sub").textContent = SLOW_TEXT; }, SLOW_MS);
        },
        done: function (msg, sub) {
          stopTimers();
          paint("done", '<span class="lf-check" aria-hidden="true">&#10003;</span>', msg, sub);
          doneT = setTimeout(function () {
            el.classList.add("fade");
            fadeT = setTimeout(function () { el.hidden = true; el.classList.remove("fade"); }, 700);
          }, DONE_MS);
        },
        error: function (msg, sub) {
          stopTimers();
          paint("error", '<span class="lf-x" aria-hidden="true">!</span>', msg, sub);
        },
        hide: function () { stopTimers(); el.hidden = true; el.className = base; el.innerHTML = ""; }
      };
    }
    var mainStatus = makeStatus(q(".lf-main-status"));
    var densStatus = wantDensity ? makeStatus(q(".lf-density-status")) : null;

    // The address the reader typed or picked, when there is one. Everywhere we
    // name the scored place, this comes first: the API's location label is only
    // city/county level ("Memphis city"), which reads as though a different,
    // vaguer place got scored than the address that was entered. Geolocation and
    // coordinate deep links have no re-typable text, so those fall back to the
    // API's label.
    function enteredAddress() {
      var d = state.desc || {};
      return String(d.address || d.label || "").trim();
    }
    function placeText() { return enteredAddress() || "this location"; }
    // Mirror the in-flight state onto the controls: the submit button becomes a
    // spinner, and a stale card left on screen during a re-score is dimmed so it
    // reads as superseded rather than current.
    var goLabel = goBtn ? goBtn.innerHTML : "";
    var busy = false;              // a score is in flight (see syncActions)
    function setFormBusy(on) {
      if (goBtn) {
        goBtn.disabled = !!on;
        goBtn.setAttribute("aria-busy", on ? "true" : "false");
        goBtn.innerHTML = on
          ? '<span class="lf-spinner lf-spinner-btn" aria-hidden="true"></span>Scoring&hellip;'
          : goLabel;
      }
      if (locateBtn) locateBtn.disabled = !!on;
      app.setAttribute("aria-busy", on ? "true" : "false");
      app.classList.toggle("is-busy", !!on && !!app.querySelector(".label-card"));
      // A card left on screen during a re-score is superseded, not current, so
      // the actions that would carry it away go off with it.
      busy = !!on;
      syncActions();
    }

    // ── render ──────────────────────────────────────────────────────────────────
    // The thresholds travel with the swatches: a reader who sees "C" can't learn
    // what C means from a legend that only names the colors.
    var GRADE_RANGE = { A: "80+", B: "60–79", C: "40–59", D: "20–39", F: "under 20" };
    function gradeLegend() {
      return '<div class="legend">' + ["A", "B", "C", "D", "F"].map(function (g) {
        return '<span><span class="swatch" style="background:' + LC.GRADE_COLORS[g] + '"></span>'
          + g + ' <span class="range">' + GRADE_RANGE[g] + '</span></span>';
      }).join("") + '</div>';
    }
    // The density sweep varies a parcel from 1 to a few units on a fixed lot, so
    // it's only meaningful for a home that isn't already a multi-unit building —
    // you can't add hypothetical density to a tower. Drop that button once we've
    // detected one (mirrors label-core's multi-family test).
    function availableModes() {
      var st = (state.detected || {}).structure;
      var alreadyMulti = !!(st && (st.structure_type === "multifamily"
        || (st.num_units && st.num_units > 1)));
      return modes.filter(function (m) {
        return !(alreadyMulti && (m === "density" || m === "buildDensity"));
      });
    }
    function isSweep(m) { return m === "density" || m === "buildDensity"; }
    // The profile list the combined view's picker is built from. Scored presets
    // when we happen to have them (the reader visited "What-if build"), else the
    // roster — same profiles, same order, from the same server constant, but
    // without paying for five scored labels to fill a dropdown.
    function profileList() { return state.presets || state.profiles || []; }
    // The construction profile the combined view sweeps, tracked by SLUG rather
    // than by list position: the list can arrive from either source, and an index
    // into the wrong one silently sweeps the wrong build.
    function sweepPreset() {
      var list = profileList();
      if (!list.length) return null;
      if (state.buildSlug) {
        for (var i = 0; i < list.length; i++) {
          if (list[i] && list[i].preset === state.buildSlug) return list[i];
        }
      }
      // No slug, or one that names nothing in this list: the picker shows the
      // first entry (no <option> carries `selected`), so the sweep must mean the
      // same one. A list whose entries have no slugs at all lands here too, and
      // loadDensity's guard refuses it rather than sweeping a generic home.
      return list[0];
    }
    // Default profile for the combined view: whatever "What-if build" would show
    // (ICF Passive when present — see applyDefaults), else the first entry.
    function defaultSlug(list) {
      for (var i = 0; i < list.length; i++) {
        if (list[i] && /icf|passive/i.test(list[i].name || "") && list[i].preset) return list[i].preset;
      }
      return (list[0] || {}).preset || null;   // never undefined: an absent slug is null
    }
    // Keep the two profile-picking views agreed: entering the combined view adopts
    // the profile "What-if build" is showing, and vice versa. Slugs, not indices.
    function syncSlugFromIdx() {
      var p = (state.presets || [])[state.idx];
      if (p && p.preset) state.buildSlug = p.preset;
    }
    function syncIdxFromSlug() {
      var ps = state.presets || [];
      for (var i = 0; i < ps.length; i++) {
        if (ps[i] && ps[i].preset === state.buildSlug) { state.idx = i; return; }
      }
    }
    function toggleBar() {
      var ms = availableModes();
      if (ms.length < 2) return "";     // single-mode widget → no toggle
      var helpId = uid + "mode-help";
      // A heading over the group: the buttons are one question ("what should we
      // score?"), and without it a reader has to infer that from the labels.
      return '<p class="mode-cap" id="' + uid + 'mode-cap">What do you want to score?</p>'
        + '<div class="mode-toggle" role="group" aria-labelledby="' + uid + 'mode-cap" aria-describedby="' + helpId + '">'
        + ms.map(function (m) {
            return '<button data-mode="' + m + '"' + (state.mode === m ? ' class="on"' : '')
              + ' aria-pressed="' + (state.mode === m) + '" title="' + esc(MODE_HELP[m] || "") + '">'
              + esc(MODE_LABELS[m] || m) + '</button>';
          }).join("") + '</div>'
        // Plain-language caption for the active view, so the toggle is
        // self-explanatory rather than three opaque one-word buttons.
        + '<p class="mode-help lf-mode-help" id="' + helpId + '">' + esc(MODE_HELP[state.mode] || "") + '</p>';
    }
    function pickerSel(cls, id, val) {
      return '<select class="' + cls + '" id="' + id + '">' + state.presets.map(function (p, i) {
        return '<option value="' + i + '"' + (i === val ? ' selected' : '') + '>' + esc(p.name) + '</option>';
      }).join("") + '</select>';
    }
    // The combined view's picker carries slugs, not positions — its list may come
    // from the roster or from scored presets, and only the slug means the same
    // thing in both.
    function sweepPickerSel(cls, id) {
      return '<select class="' + cls + '" id="' + id + '">' + profileList().map(function (p) {
        return '<option value="' + esc(p.preset) + '"' + (p.preset === state.buildSlug ? ' selected' : '')
          + '>' + esc(p.name) + '</option>';
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
      // Title the card with the address the user entered/picked (the API's
      // location label is only county-level and just repeats the meta line). Falls
      // back to the default heading (county) for geolocation / coord deep links.
      var addrHeading = enteredAddress();
      var cardOpts = { subline: subline };   // not mount()'s `opts` — distinct name to avoid shadowing
      if (addrHeading) cardOpts.heading = addrHeading;
      return LC.renderCard(data, cardOpts);
    }

    // The "Over time" view. The legend leads because it is the claim every number
    // below it depends on: without "scored on today's scale" a reader can't tell
    // a place that improved from a national average that moved underneath it.
    function timelinePanel() {
      var data = state.timeline;
      if (!data) return "";
      var html = '<p class="conf-legend traj-legend">' + esc(data.legend || "") + '</p>';
      html += LC.trajTable(data);
      var rows = (data.as_of || []).map(function (a) {
        return '<tr><td>' + esc(String(a.year)) + '</td><td>'
          + (a.durability == null ? "—" : a.durability.toFixed(1)) + '</td><td>'
          + (a.building_score == null ? "—"
             : a.building_score.toFixed(0) + " " + gradeSpan(a.building_national_grade))
          + '</td></tr>';
      }).join("");
      if (rows) {
        html += '<table class="delta-table traj-table"><thead><tr>'
          + '<th>Building grade as it ages</th><th>Durability</th><th>Building</th>'
          + '</tr></thead><tbody>' + rows + '</tbody></table>'
          + '<p class="conf-legend traj-caveat">Only Durability moves with the '
          + 'calendar here — Energy Efficiency is keyed to the construction era and '
          + 'the Environmental Footprint’s embodied carbon was fixed when the home '
          + 'was built — so this is what ageing alone does to the Building grade.</p>';
      }
      html += LC.trajPointInTime(data);
      // The card renderer carries the notice on every other view; this one draws
      // tables instead of cards, so it has to ask for it.
      html += LC.legalNote(data);
      return html;
    }

    // ── Take it with you: print, or save the sheet ──────────────────────────────
    // Two ways out of the browser, because they are two different artifacts and a
    // reader wants different things from them:
    //
    //   Print  — the page as it stands, disclosure state and all. What a reader
    //            has opened is what they are reading, so print takes it rather
    //            than second-guessing it; the print stylesheet drops the controls
    //            and adds a colophon (label-core.js printStamp) so the sheet says
    //            where it came from and when.
    //   SVG    — the whole label redrawn as one Letter page by the API
    //            (housing_label.label_svg), as vector, with text still text. That
    //            is the copy that goes into a report, an email, or a listing
    //            packet, and it must not depend on this page's fonts, theme, or
    //            width to survive the trip.
    //
    // The SVG is asked for with the SAME parameters that scored what's on screen —
    // including refine-panel edits — so a saved sheet cannot quietly disagree with
    // the label it was saved from.
    function sheetQuery() {
      if (state.mode === "detected") return buildDetectedParams().query;
      if (state.mode === "single") {
        var pr = state.presets && state.presets[state.idx];
        if (!pr || !pr.preset) return null;
        var d = descQuery(state.desc).replace(/^\?/, "");
        return "preset=" + encodeURIComponent(pr.preset) + (d ? "&" + d : "");
      }
      return null;   // compare / density / timeline are not one label
    }
    // What the sheet is titled. A hypothetical profile scored at this address is
    // NOT this address's home, and a saved sheet headed by the street address
    // alone would say it was — to a reader who has only the sheet, months later,
    // with nothing on it to contradict them. So the build is named in the title.
    function sheetCaption() {
      var addr = enteredAddress();
      if (state.mode !== "single") return addr;
      var pr = state.presets && state.presets[state.idx];
      if (!pr) return addr;
      return pr.name + " (hypothetical build)" + (addr ? " at " + addr : "");
    }
    // Both buttons are switched from one place, after every render and on every
    // change of busy state.
    //
    // "Is there a label yet" is asked of the DOM rather than re-derived from
    // state: six view modes each have their own way of being half-loaded, and the
    // question the buttons actually ask is whether there is something on screen
    // to take away. Print takes whatever that is — every view prints. The sheet
    // needs a view that maps to a single /label.svg query, which Compare and the
    // density sweeps do not.
    function syncActions() {
      // A sweep that is re-scoring dims its table rather than emptying it (see
      // loadDensity), which means the table on screen is the *previous* answer.
      // Superseded is not printable — the same rule `busy` applies to a card
      // being re-scored, and the reason .is-busy is read here rather than just
      // the presence of a table.
      var sweep = !!densResult && !!densResult.querySelector("table")
        && !densResult.classList.contains("is-busy");
      var have = !busy && !state.idle && !state.error
        && (!!app.querySelector(".label-card, table")   // a card, or Over time's tables
            || sweep);
      setAvailable(printBtn, have);
      // A sheet already being drawn owns its button until it lands. Availability
      // is otherwise recomputed from scratch here, so any re-render during the
      // fetch — a mode switch, a re-score finishing — would hand the button back
      // and let a second press start a second download of the same sheet.
      if (!drawing()) setAvailable(svgBtn, have && !!sheetQuery());
      // A guard message answers "why did that press do nothing", and anything that
      // moves the switch can change the answer — including making the button
      // available, which would leave the explanation standing beside a button
      // that now works. ("Drawing the sheet…" and "Saved." belong to the save and
      // are left alone.)
      if (noteKind === "guard") actionsNote("");
      else if (!have && !drawing()) actionsNote("");
    }
    function setAvailable(btn, on) {
      if (btn) btn.setAttribute("aria-disabled", on ? "false" : "true");
    }
    // Every flip of the sweep's dimmed state goes through here, because the class
    // is now part of the answer syncActions gives.
    function setSweepBusy(on) {
      if (!densResult) return;
      densResult.classList.toggle("is-busy", !!on);
      syncActions();
    }
    // Why a press did nothing. The switch has several reasons and they are not
    // interchangeable: telling somebody to score an address while a score is
    // already running is both wrong and irritating, and "this view is more than
    // one label" is no answer at all when the real problem is that nothing has
    // been scored yet.
    function whyUnavailable(does) {
      if (busy) return "Still scoring \u2014 then this " + does + ".";
      if (state.error) return "That score didn\u2019t finish. Score again, and this " + does + ".";
      return "Score an address first \u2014 then this " + does + ".";
    }
    function whySheetUnavailable() {
      if (drawing()) return "Still drawing the sheet\u2026";
      // Only once there IS a label does the view itself become the reason.
      if (!busy && !state.error && !state.idle && !sheetQuery()) {
        return "This view is more than one label. Switch to a single label to save one.";
      }
      return whyUnavailable("saves the label as an SVG");
    }
    function drawing() {
      return !!svgBtn && svgBtn.getAttribute("aria-busy") === "true";
    }
    // Busy counts as unavailable whoever set it, so the guard holds even if some
    // path leaves aria-disabled behind.
    function unavailable(btn) {
      return !btn || btn.getAttribute("aria-disabled") === "true"
        || btn.getAttribute("aria-busy") === "true";
    }
    // "guard" answers a press that did nothing; "status" belongs to a save in
    // progress. They expire differently, which is the whole reason for the tag.
    var noteKind = "";
    function actionsNote(text, kind) {
      var n = q(".lf-actions-note");
      noteKind = text ? (kind || "status") : "";
      if (n) n.textContent = text || "";
    }
    // Fetch-then-blob rather than a plain link: the API is on another origin, where
    // an <a download> is ignored and the browser navigates away from the label
    // instead of saving beside it. A failed fetch (offline, CORS, a self-hosted API
    // that hasn't allowed this origin) falls back to opening the URL, which at
    // worst shows the reader the sheet they asked for.
    function saveSheet(btn) {
      var query = sheetQuery();                 // not `q` — that is this widget's querySelector
      if (!query || !API_BASE) return;
      var caption = sheetCaption();
      var url = API_BASE + "/label.svg?" + query + "&theme=light"
        + (caption ? "&label_text=" + encodeURIComponent(caption) : "")
        + "&scored=" + encodeURIComponent(new Date().toISOString().slice(0, 10));
      setAvailable(btn, false);          // one press at a time; the guard enforces it
      btn.setAttribute("aria-busy", "true");
      actionsNote("Drawing the sheet\u2026");
      fetchScoring(url + "&download=1")
        .then(function (r) { if (!r.ok) throw new Error(String(r.status)); return r.blob(); })
        .then(function (blob) {
          var href = URL.createObjectURL(blob), a = document.createElement("a");
          a.href = href;
          a.download = sheetFilename(caption);
          document.body.appendChild(a); a.click(); document.body.removeChild(a);
          setTimeout(function () { URL.revokeObjectURL(href); }, 1000);
          // Retires itself, the same way the scoring confirmation does — a
          // status line that never clears stops reading as a status line.
          actionsNote("Saved.");
          setTimeout(function () {
            // Through the setter, not the node: the text and its kind are one
            // fact, and clearing the first while leaving the second saying
            // "status" is how the next reader of noteKind gets a wrong answer.
            var n = q(".lf-actions-note");
            if (n && n.textContent === "Saved.") actionsNote("");
          }, 4000);
        })
        .catch(function () {
          actionsNote("");
          window.open(url, "_blank", "noopener");
        })
        // Not `disabled = false`: by the time this lands the reader may have
        // started another score, and the switch above owns that answer.
        .then(function () { btn.removeAttribute("aria-busy"); syncActions(); });
    }
    // Mirrors housing_label.label_svg.filename_for — ASCII, lowercase, no spaces,
    // so the file survives every filesystem it gets emailed to, and so a file
    // saved through this button is named the same as one fetched straight from
    // the API. That includes the empty case: no caption is "housing-label.svg",
    // not "housing-label-.svg" and not a "label" the address slot invented.
    function sheetFilename(caption) {
      var slug = String(caption || "").toLowerCase().replace(/[^a-z0-9]+/g, "-");
      slug = slug.replace(/^-+|-+$/g, "").slice(0, 60).replace(/-+$/, "");
      return slug ? "housing-label-" + slug + ".svg" : "housing-label.svg";
    }

    // ── when one dataset was too slow to wait for ────────────────────────────────
    // The API stops paying for a dataset that has used its share of a score and
    // returns the rest of the label rather than the whole thing late or not at
    // all, so a slow upstream now costs a few rows an N/A instead of costing the
    // reader everything. That trade is only fair if the reader is told: an N/A
    // with no explanation reads as "we know nothing about your address", when
    // what happened is that one public service was slow for a minute and the
    // very same address will score completely on the next try.
    //
    // The API names the datasets it dropped (payload.slow_upstreams); the wording
    // is here, because it is the page that has to say it in a sentence.
    function slowDataNote() {
      // Every payload on screen, not the one this mode happens to render from.
      // Picking per mode looked tidier and quietly dropped the disclosure in the
      // combined view, which can reach its profile list through /presets without
      // a /label having been scored at all — the one path where `detected` is
      // null and `presetsSlow` is not. These four are all scored at the same
      // location and the reader toggles between them freely, so a dataset that
      // was too slow for any of them is a caveat on all of them until the next
      // score clears it (each load replaces its own payload, so a name here is
      // never older than the view it came from).
      var seen = {}, list = [];
      [(state.detected || {}).slow_upstreams,
       state.presetsSlow,
       (densityCache() || {}).slow_upstreams,
       (state.timeline || {}).slow_upstreams].forEach(function (from) {
        (from || []).forEach(function (u) {
          var key = (u && (u.host || u.dataset)) || "";
          if (key && !seen[key]) { seen[key] = 1; list.push(u); }
        });
      });
      if (!list.length) return "";
      var names = list.map(function (u) { return esc((u && (u.dataset || u.host)) || "a public dataset"); });
      var which = names.length === 1 ? names[0]
        : names.slice(0, -1).join(", ") + " and " + names[names.length - 1];
      var one = names.length === 1;
      // Careful about what is promised. A dropped dataset does not always leave an
      // N/A: several of them refine something the label can also answer from a
      // bundled county table, and those rows come back coarser rather than empty.
      // So the sentence says what is certainly true — the score went ahead without
      // it — and describes both outcomes rather than the dramatic one.
      //
      // The dataset names lead with a lower-case "the" ("the Census geocoder"), so
      // the sentence is built to put something else at the front of it.
      return '<div class="insight warn label-notice">'
        + (one ? '<strong>One dataset was too slow to wait for.</strong> '
               : '<strong>Some datasets were too slow to wait for.</strong> ')
        + 'The score went ahead without ' + which + '. Rows that depend on '
        + (one ? 'it' : 'them') + ' fall back to a coarser estimate, or show N/A '
        + 'where there is no substitute. Nothing is wrong with the address — '
        + 'scoring it again in a minute usually gets the full picture.'
        + '<br><button type="button" class="reset lf-retry" style="margin-top:0.7rem;">'
        + 'Score again</button></div>';
    }

    function render() {
      if (!API_BASE) { app.innerHTML = ""; return; }
      if (state.idle) {
        // Nothing scored yet — say so rather than auto-scoring a default.
        //
        // Kept to one line, because this panel sits immediately below the address
        // field and the buttons, and the long version restated all three: it
        // opened with the field's own placeholder ("Enter a U.S. address or place
        // name…") almost verbatim, repeated that placeholder's example address,
        // re-described the "Use my location" button, and re-described what "Score
        // this address" does. What survives is what the controls don't say — that
        // the result lands here, and that a business name resolves too.
        app.innerHTML = '<div class="insight label-prompt">Your label will appear here. '
          + 'You can search by street address, or by the name of a place or business.</div>';
        if (densWrap) densWrap.hidden = true;
        return;
      }
      if (state.error) {
        // A 422 is the residential-only screen (a non-residential address), not an
        // outage — show the guidance as a neutral notice, without the "retry" line.
        if (state.errorStatus === 422) {
          app.innerHTML = '<div class="insight warn label-notice">' + esc(state.error) + '</div>';
        } else if (state.timedOut) {
          // Not an outage and not a dead end: name the likely cause, and put the
          // retry in the reader's hand rather than making them retype the address.
          app.innerHTML = '<div class="insight warn label-notice">'
            + '<strong>This is taking longer than it should.</strong> One of the public '
            + 'datasets behind the label is slow to answer right now, so scoring '
            + esc(placeText()) + ' didn\u2019t finish in '
            + Math.round(SCORE_TIMEOUT_MS / 1000) + ' seconds. Nothing is wrong with '
            + 'the address.<br><button type="button" class="reset lf-retry" '
            + 'style="margin-top:0.7rem;">Try again</button></div>';
        } else {
          app.innerHTML = '<div class="error">Could not load the label: ' + esc(state.error)
            + '.<br>The scoring API may be temporarily unavailable &mdash; retry in a moment.</div>';
        }
        return;
      }
      // Density paints into its own persistent panel below, so it never waits on
      // the card skeleton here. The combined view waits only on the profile list
      // — that's what its picker is built from — and that list is a constant, not
      // a scored result, so this is a blink rather than five scoring passes.
      var loadingData = state.mode === "density" ? false
        : state.mode === "buildDensity" ? !profileList().length
        : state.mode === "timeline" ? !state.timeline
        : state.mode === "detected" ? !state.detected : !state.presets;
      if (loadingData) {
        app.innerHTML = loadingHtml();
        if (densWrap) densWrap.hidden = true;
        return;
      }
      // Where the place name comes from, in the order it becomes available. A
      // sweep view can be reached without ever scoring a /label — pick "Use my
      // location" while already in one and only /density runs — and geolocation
      // carries no re-typable address either, so neither the entered text nor
      // `detected` has a name to show. The sweep's own payload does.
      var loc0 = state.mode === "single" || state.mode === "compare"
        ? (((state.presets || [])[0] || {}).location || {})
        : ((state.detected || {}).location
           || (isSweep(state.mode) ? (densityCache() || {}).location : null)
           // Same reason the sweeps carry their own: "Over time" can be reached
           // without ever scoring a /label, and its payload is then the only
           // place a place name exists.
           || (state.mode === "timeline" ? (state.timeline || {}).location : null)
           || {});
      // Say the address back, not the city the API resolved it to.
      var locName = enteredAddress() || loc0.label || loc0.county_name || "";
      var scoredWhat = state.mode === "detected" ? "This home scored at"
        : state.mode === "timeline" ? "This home scored over time at"
        : isSweep(state.mode) ? "This lot scored at"
        : "Profiles scored at";
      // The tick is the finished-state marker that outlives the confirmation
      // banner: the caption itself says the score on screen is a completed one.
      var html = locName ? '<div class="label-loc"><span class="lf-tick" aria-hidden="true">&#10003;</span> '
        + scoredWhat + ' <strong>' + esc(locName) + '</strong></div>' : "";
      html += toggleBar();
      html += slowDataNote();
      if (state.mode === "density") {
        // Nothing more here: the density panel is the next node in the DOM, so
        // the table lands directly under the button that asked for it.
      } else if (state.mode === "buildDensity") {
        // Only the profile picker: the sweep for the picked build paints into
        // the density panel right below, same as the detected sweep does.
        html += '<div class="picker"><label for="' + uid + 'd-sel">Construction profile: </label>'
          + sweepPickerSel("lf-d-sel", uid + "d-sel") + '</div>';
      } else if (state.mode === "detected") {
        html += detectedCard() + gradeLegend();
      } else if (state.mode === "timeline") {
        html += timelinePanel();
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
      if (densWrap) densWrap.hidden = !isSweep(state.mode);
      syncActions();
    }

    // ── density comparison (fixed lot, vary units) ──────────────────────────────
    // Two views share this panel: the sweep on the real home ("What-if denser")
    // and the sweep on a hypothetical build ("What-if build + denser").
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
      // Plain-language row labels: this is a view a first-time reader can land on
      // now, not a follow-on table for someone already deep in the methodology,
      // so "Energy / unit / mo" and "Net fiscal / acre" say what they mean.
      var rows = "";
      rows += row("Total value on the lot", function (s) { return s.value == null ? "—" : "$" + Math.round(s.value).toLocaleString(); });
      rows += row("Value per home", function (s) { return s.per_unit_value == null ? "—" : "$" + Math.round(s.per_unit_value).toLocaleString(); });
      rows += row("Homes per acre", function (s) { return s.per_unit_acres ? (1 / s.per_unit_acres).toFixed(1) : "—"; });
      rows += row("Infrastructure Burden", function (s) { return s.infrastructure_score == null ? "—" : s.infrastructure_score.toFixed(0) + " " + gradeSpan(s.infrastructure_grade); });
      rows += row("Revenue ÷ cost to serve", function (s) { return s.fiscal_ratio == null ? "—" : s.fiscal_ratio.toFixed(2) + "×"; });
      rows += row("Energy Efficiency score", function (s) { return s.energy_score == null ? "—" : s.energy_score.toFixed(0); });
      rows += row("Energy bill per home", function (s) { return s.est_monthly_energy_cost == null ? "—" : "$" + Math.round(s.est_monthly_energy_cost) + "/mo"; });
      rows += row("Overall score", function (s) { return s.composite_score == null ? "—" : s.composite_score.toFixed(0) + " " + gradeSpan(s.composite_national_grade); });
      rows += row("Revenue raised per acre", function (s) { return s.revenue_per_acre == null ? "—" : "$" + Math.round(s.revenue_per_acre).toLocaleString() + "/ac"; });
      rows += row("Left over for the city, per acre", function (s) {
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
            + '&times; the revenue per acre</strong> ($'
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
      // In the combined view every row is a hypothetical build, not the home
      // that's standing there — say so above the table so the numbers aren't
      // read as the real house at four densities.
      if (state.mode === "buildDensity") {
        var bp = sweepPreset();
        if (bp) {
          html = '<p class="meta" style="text-align:center;margin:0 auto 0.6rem;">'
            + 'Every scenario below is built as <strong>' + esc(bp.name) + '</strong>'
            + (bp.description ? ' &mdash; ' + esc(bp.description) : "")
            + '. The home that’s there now is ignored.</p>' + html;
        }
      }
      html += LC.legalNote(data);               // tables, not cards — see timelinePanel()
      densResult.innerHTML = html;
      setSweepBusy(false);                      // fresh numbers — undim
    }
    // Picking either sweep runs the comparison straight away — it's a view, not a
    // two-step ritual, so selecting it should produce the answer. The detected
    // sweep is cached per location (a refine edit clears it — see loadDetected);
    // the build sweep is cached per construction profile.
    // The slug is what identifies a build to /density, so it's also the cache
    // key. A profile without one can't be swept at all (see loadDensity): the
    // request would drop the profile and quietly sweep a generic home instead.
    function sweepSlug(p) { return p && p.preset ? String(p.preset) : ""; }
    function densityCache() {
      if (state.mode !== "buildDensity") return state.density;
      var slug = sweepSlug(sweepPreset());
      return slug ? (state.densityBuilds[slug] || null) : null;
    }
    // What the sweep runs on: the real (optionally refined) home, or — for the
    // combined view — this same lot with a hypothetical profile built on it. The
    // refine-panel edits describe the existing home, so they don't travel with a
    // build that isn't there; only the location and the profile do.
    function densityQuery() {
      if (state.mode !== "buildDensity") return buildDetectedParams().query;
      var qs = descQuery(state.desc).replace(/^\?/, "");
      if (!qs) qs = "lat=" + DEFAULT_LAT + "&lon=" + DEFAULT_LON;   // same fallback as /label
      var slug = sweepSlug(sweepPreset());
      return qs + (slug ? "&preset=" + encodeURIComponent(slug) : "");
    }
    function loadDensity(force) {
      if (!API_BASE || !wantDensity) return;
      state.error = null;
      var cached = densityCache();
      if (cached && !force) {
        // The two sweeps share one panel, so a cached result still has to be
        // repainted — the table on screen may belong to the other view. Bumping
        // the sequence drops any request still in flight for the view we left,
        // which would otherwise paint over this panel when it lands.
        reqSeq++;
        densStatus.hide(); render(); renderDensity(cached);
        return;
      }
      var seq = ++reqSeq;
      var build = state.mode === "buildDensity" ? sweepPreset() : null;
      render();
      // Without a slug there's no way to ask for this build, and a request with
      // the profile dropped would sweep a generic home under the profile's name
      // — a wrong answer wearing the right label. Say so instead of scoring it.
      if (build && !sweepSlug(build)) {
        densResult.innerHTML = "";
        setSweepBusy(false);
        densStatus.error("Could not compare densities",
          "The " + build.name + " profile came back without an identifier, so it "
          + "can’t be built at other densities here.");
        return;
      }
      // Don't empty the panel. Switching profiles used to blank the table for the
      // whole round trip, which reads as "broken" rather than "working" — the
      // numbers vanish and nothing takes their place. A table left up but dimmed
      // (the same treatment a re-scoring card gets) reads as superseded, and the
      // busy banner right above it says what's happening. Only the first sweep,
      // with nothing to keep, gets a skeleton.
      if (densResult.querySelector("table")) {
        setSweepBusy(true);
      } else {
        densResult.innerHTML = densitySkeleton();
        setSweepBusy(false);
      }
      densStatus.busy(build ? "Comparing densities for the " + build.name + " build…"
                            : "Comparing densities on this lot…",
        "Re-scoring " + placeText() + " at several unit counts"
        + (build ? " as " + build.name + "." : "."));
      fetchScoring(API_BASE + "/density?" + densityQuery())
        .then(okJson)
        .then(function (data) {
          if (seq !== reqSeq) return;
          // Was the header missing a place name? Only then is a repaint worth it:
          // rendering replaces the profile picker, and pulling it out from under
          // a reader who is mid-selection to change nothing else would be rude.
          var headerless = !app.querySelector(".label-loc");
          if (build) state.densityBuilds[sweepSlug(build)] = data;
          else state.density = data;
          var n = ((data && data.scenarios) || []).length;
          if (headerless) render();     // the payload's location can name it now
          renderDensity(data);
          densStatus.done("Density comparison ready",
            n ? n + " scenario" + (n === 1 ? "" : "s") + " scored on this lot"
                + (build ? " as " + build.name : "") + " — see the table below." : "");
        })
        .catch(function (err) {
          if (seq !== reqSeq) return;
          // The stale table stays, but undimmed: it is the last real answer, and
          // leaving it greyed out under an error would imply it's still updating.
          setSweepBusy(false);
          densStatus.error("Could not compare densities", err.message);
        });
    }

    // ── refine panel ────────────────────────────────────────────────────────────
    // "county record" is the strongest tag the reader can be shown that they did not
    // type themselves: an assessor went and looked, where "estimated" and "default"
    // are both derived. Ranked above them in the count line below for the same reason.
    var TAG_LABEL = { confirmed: "you edited", observed: "county record",
                      estimated: "estimated", assumed: "default" };
    // The refine panel only makes sense in Detected mode AND when there's an API to
    // re-score against — without one it would be an empty, non-functional control.
    function syncRefineVisibility() {
      var on = !!(API_BASE && state.mode === "detected" && !state.idle);
      refineEl.style.display = on ? "" : "none";
      // The year-built note lives OUTSIDE the <details> so it survives the panel
      // being collapsed — which means hiding the panel does not hide it, and in a
      // what-if / compare / over-time view it would sit there telling the reader to
      // open a panel that is no longer on screen. Its own content rule still
      // applies underneath: this only ever hides it, never shows it.
      if (!on) ybNote.style.display = "none";
      else if (ybNote.textContent) ybNote.style.display = "";
    }
    function applyBuilding(building) {
      var estimated = 0, observed = 0, total = 0;
      FIELDS.forEach(function (f) {
        var el = fieldEl(f.key), tag = q('[data-tag="' + f.key + '"]'), info = building && building[f.key];
        if (!el || !tag) return;
        if (!info) { tag.className = "field-tag"; tag.textContent = ""; if (document.activeElement !== el) el.value = ""; return; }
        total++;
        var status = touched[f.key] ? "confirmed" : info.status;
        if (status === "estimated") estimated++;
        if (status === "observed") observed++;
        if (document.activeElement !== el) el.value = info.value == null ? "" : info.value;
        tag.className = "field-tag " + status;
        tag.textContent = TAG_LABEL[status] || status;
        tag.title = (info.source || "") + (info.confidence ? " · " + info.confidence + " confidence" : "");
      });
      // Lead with what the county measured when there is any, because it is the
      // one part of this panel a reader has no reason to second-guess.
      refineCount.textContent = !total ? ""
        : (observed ? "— " + observed + " of " + total + " from county records, "
                      + estimated + " estimated (edit any to refine)"
                    : "— " + estimated + " of " + total + " estimated from public data (edit any to refine)");
      var hintEl = q(".lf-refine-hint");
      if (hintEl && total) {
        hintEl.firstChild.nodeValue = (observed ? HINT_OBSERVED : HINT_ESTIMATED) + " ";
      }
      renderYearBuiltNote(building);
      // Deliberately does NOT open the panel. It used to force itself open on
      // every score, which pushed the label — the thing that was just asked for —
      // a full phone screen below the fold behind ten fields and eight
      // checkboxes. The collapsed summary still reports what matters ("5 of 9
      // estimated from public data — edit any to refine"), so the provenance and
      // the invitation to correct it survive; only the form itself waits to be
      // asked for. A panel the reader opened stays open across re-scores, since
      // nothing here closes it either.
    }
    // Says how much the unknown year is costing this reader, and nothing when the
    // answer is "nothing". The API omits the sensitivity block entirely unless the
    // year is still a stand-in AND a grade actually moves across the tract's
    // plausible range, so the presence of the block IS the decision — there is no
    // threshold to re-litigate here.
    var AXIS_LABEL = "the Building grade";
    function renderYearBuiltNote(building) {
      var yb = building && building.year_built, s = yb && yb.sensitivity;
      if (!s || !s.moves || !s.moves.length) { ybNote.style.display = "none"; ybNote.textContent = ""; return; }

      // Real dimension names from the payload rather than a hardcoded map here —
      // the roster is generated from DIMENSIONS in Python and a second copy would
      // drift the first time one is renamed.
      var names = {};
      ((state.detected && state.detected.dimensions) || []).forEach(function (d) {
        if (d && d.key) names[d.key] = d.label || d.key;
      });

      var parts = s.moves.map(function (k) {
        var name = k === "construction_axis" ? AXIS_LABEL : (names[k] || k);
        // The span across the range, not a single arrow: three grades are in play
        // (p25, the typical, p75) and picking two of them would overstate what is
        // known. Letters are ordered best-first so "A–C" reads the way a scale does.
        var seen = [s.low, s.current, s.high].map(function (pt) {
          return pt && pt.grades ? pt.grades[k] : null;
        }).filter(Boolean).filter(function (g, i, a) { return a.indexOf(g) === i; });
        seen.sort();
        return seen.length > 1 ? name + " (" + seen.join("–") + ")" : name;
      });

      var list = parts.length === 1 ? parts[0]
        : parts.slice(0, -1).join(", ") + " and " + parts[parts.length - 1];
      var where = s.geo_level === "tract" ? "here"
        : s.geo_level === "county" ? "in this county" : "nationally";
      var lo = s.low && s.low.year, hi = s.high && s.high.year;
      ybNote.innerHTML =
        '<strong>Year built is a neighborhood typical, not this home\u2019s.</strong> '
        + 'Most homes ' + esc(where) + ' were built ' + esc(String(lo)) + '\u2013' + esc(String(hi))
        + '. Confirming the real year could change ' + esc(list)
        + ' \u2014 open <em>Refine building details</em> above to set it.';
      ybNote.style.display = "";
    }

    function buildDetectedParams() {
      var params = new URLSearchParams(), d = state.desc, edited = false;
      if (d && d.lat != null) { params.set("lat", d.lat); params.set("lon", d.lon); }
      else if (d && d.address) { params.set("address", d.address); }
      else { params.set("lat", DEFAULT_LAT); params.set("lon", DEFAULT_LON); }
      // The picked place was a non-residential POI — ask the API to refuse it.
      if (d && d.nonResidential) params.set("nonresidential", "1");
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
    // A failure ends the busy state too — the error panel takes over from the
    // banner, so leaving a spinner running underneath it would contradict it.
    function fail(seq) {
      return function (err) {
        if (seq !== reqSeq) return;
        state.error = err.message; state.errorStatus = err.status || 0;
        state.timedOut = !!err.timedOut;
        mainStatus.hide(); setFormBusy(false); render();
      };
    }
    function persistLocation() { if (persist) { syncUrl(state.desc || null); saveLast(state.desc || null); } }

    // The construction-profile roster: names and slugs, no scores. The combined
    // view only needs the profiles NAMED to offer them and to ask for one by
    // slug, but the only list available used to be /presets — five complete
    // scored labels, several seconds of work, to populate a dropdown, all of it
    // ahead of the sweep the reader actually asked for. This is the roster alone.
    // It is the same for every address, so it is fetched at most once per page
    // and survives a change of location.
    var profilesPending = null;         // in-flight promise → never fetched twice
    function loadProfiles() {
      if (!API_BASE || state.profiles || profilesPending) return profilesPending;
      profilesPending = fetchScoring(API_BASE + "/preset-profiles")
        .then(okJson)
        .then(function (data) {
          var ps = (data && data.profiles) || [];
          if (!ps.length) throw new Error("no profiles returned");
          state.profiles = ps;
          if (!state.buildSlug) state.buildSlug = defaultSlug(ps);
          return ps;
        })
        .catch(function () {
          // Not fatal and not worth a banner: the scored /presets list is the
          // fallback, and ensureData falls back to it on the next pass.
          profilesPending = null;
          return null;
        });
      return profilesPending;
    }
    // Name the place in the confirmation — the entered address first, the
    // payload's city/county label only when there isn't one.
    function scoredAt(data) {
      var loc = (data && data.location) || {};
      return enteredAddress() || loc.label || loc.county_name || "this location";
    }

    function loadPresets() {
      if (state.presets) { render(); return; }
      if (!API_BASE) { return; }
      var seq = ++reqSeq; state.error = null; render();
      mainStatus.busy("Scoring construction profiles…", "Building each profile at " + placeText() + ".");
      setFormBusy(true);
      fetchScoring(API_BASE + "/presets" + descQuery(state.desc))
        .then(okJson)
        .then(function (data) {
          if (seq !== reqSeq) return;
          var ps = (data && data.presets) || [];
          if (!ps.length) throw new Error("no presets returned");
          // Carried on the wrapper rather than on each profile: a dataset that
          // was too slow was too slow for the whole grid, which is scored in one
          // request at one location. See slowDataNote().
          state.presetsSlow = (data && data.slow_upstreams) || null;
          state.presets = ps; applyDefaults();
          state.idx = clampIdx(state.idx); state.idxA = clampIdx(state.idxA); state.idxB = clampIdx(state.idxB);
          // Scored presets are a superset of the roster, so they also serve the
          // combined view's picker — and keep the two views on the same profile.
          if (!state.buildSlug) syncSlugFromIdx(); else syncIdxFromSlug();
          persistLocation(); setFormBusy(false); render();
          mainStatus.done("Profiles scored", ps.length + " construction profiles scored at "
            + scoredAt(ps[0]) + ".");
          // Only relevant if the roster never arrived and this was the fallback
          // route into the combined view — otherwise the sweep is already running.
          if (state.mode === "buildDensity") loadDensity(false);
        })
        .catch(fail(seq));
    }
    function loadDetected(force) {
      if (state.detected && !force) { render(); applyBuilding(state.building); return; }
      if (!API_BASE) { return; }
      var seq = ++reqSeq; state.error = null;
      if (!state.detected) render();
      // A refine-panel edit re-scores with the previous card still on screen, so
      // say which of the two is happening rather than "Scoring…" for both.
      var rescore = !!state.detected;
      mainStatus.busy(rescore ? "Re-scoring with your details…" : "Scoring this address…",
        rescore ? "Applying your edits to " + placeText() + "."
                : "Reading flood, climate, energy, and neighborhood data for " + placeText() + ".");
      setFormBusy(true);
      var built = buildDetectedParams();
      fetchScoring(API_BASE + "/label" + built.qs)
        .then(okJson)
        .then(function (data) {
          if (seq !== reqSeq) return;
          state.detected = data; state.building = data.building || null;
          state.detectedCtx = built.ctx;
          // Refine edits change the parcel both sweeps run on. The timeline is
          // hit hardest: its aging series keys off the build year, so a corrected
          // year_built invalidates every point, not just the level.
          state.density = null;
          state.timeline = null;
          // Detection can retire a view: the density sweep is meaningless once
          // this turns out to be a multi-unit building.
          if (availableModes().indexOf(state.mode) < 0) state.mode = availableModes()[0];
          persistLocation(); setFormBusy(false); render(); applyBuilding(state.building);
          // The payload uses "—" when there's no composite to grade; only a real
          // letter grade belongs in the confirmation line.
          var grade = String(data.composite_national_grade || "");
          var hasGrade = grade.length === 1 && "ABCDF".indexOf(grade) >= 0;
          mainStatus.done(rescore ? "Label updated" : "Label ready",
            "Scored " + scoredAt(data) + (hasGrade ? " — overall grade " + grade + "." : "."));
        })
        .catch(fail(seq));
    }
    // ── timeline (fixed address, vary time) ────────────────────────────────────
    // Scored on the real (optionally refined) home, exactly like the detected
    // card — so it takes the same query and is invalidated by the same edits.
    function loadTimeline(force) {
      if (!API_BASE) return;
      if (state.timeline && !force) { render(); return; }
      var seq = ++reqSeq; state.error = null;
      render();
      mainStatus.busy("Scoring this address over time…",
        "Reading the climate record and aging the building for " + placeText() + ".");
      fetchScoring(API_BASE + "/timeline?" + buildDetectedParams().query)
        .then(okJson)
        .then(function (data) {
          if (seq !== reqSeq) return;
          state.timeline = data;
          render();
          var n = Object.keys((data && data.series) || {}).length;
          mainStatus.done("Timeline ready",
            n ? "Scored " + scoredAt(data) + " — " + n
                + (n === 1 ? " dimension" : " dimensions") + " with a time series."
              : "No dimension at this address carries a time series.");
        })
        .catch(fail(seq));
    }

    // Retry after a deadline: clear the failure and ask for the same view again,
    // forcing past the caches, since what is cached is nothing.
    function retryLoad() {
      state.error = null; state.errorStatus = 0; state.timedOut = false;
      if (state.mode === "detected") { loadDetected(true); return; }
      state.timeline = null; state.density = null; state.presets = null;
      ensureData();
    }
    function ensureData() {
      if (state.mode === "density") loadDensity(false);
      else if (state.mode === "detected") loadDetected(false);
      else if (state.mode === "buildDensity") ensureBuildDensity();
      else if (state.mode === "timeline") loadTimeline(false);
      else loadPresets();
    }
    // The combined view needs a profile list before it can sweep one — but only
    // the NAMES, so it waits on the roster (a constant) rather than on five
    // scored labels. If the roster can't be had, the scored list is the fallback.
    function ensureBuildDensity() {
      if (profileList().length) { loadDensity(false); return; }
      var pending = loadProfiles();
      if (!pending) { loadPresets(); return; }
      render();                        // skeleton while the roster is in flight
      pending.then(function (ps) {
        if (state.mode !== "buildDensity") return;   // reader moved on
        if (ps && ps.length) { render(); loadDensity(false); }
        else loadPresets();                          // roster failed → scored list
      });
    }
    function load(desc) {
      state.idle = false;               // a location was requested — leave the prompt state
      state.desc = desc || null;
      state.presets = null; state.detected = null; state.building = null;
      state.detectedCtx = null; state.density = null; state.densityBuilds = {};
      touched = {}; applyBuilding(null);
      qa(".addr-upgrades input").forEach(function (cb) { cb.checked = false; });
      if (densResult) densResult.innerHTML = "";
      if (densStatus) densStatus.hide();
      syncRefineVisibility();           // reveal the refine panel now that we're scoring
      ensureData();
    }
    // Return to the pre-scoring prompt (Reset) — clears the scored result and any
    // in-flight response rather than re-scoring a default location.
    function resetToIdle() {
      reqSeq++;                         // invalidate any in-flight response
      state.idle = true; state.error = null; state.desc = null;
      state.presets = null; state.detected = null; state.building = null;
      state.detectedCtx = null; state.density = null; state.densityBuilds = {};
      touched = {}; applyBuilding(null);
      qa(".addr-upgrades input").forEach(function (cb) { cb.checked = false; });
      if (densResult) densResult.innerHTML = "";
      if (densStatus) densStatus.hide();
      poiHintEl.style.display = "none";
      mainStatus.hide(); setFormBusy(false);
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
      if (!e.target.closest) return;
      var b = e.target.closest("button[data-mode]");
      if (b) { setMode(b.getAttribute("data-mode")); return; }
      if (e.target.closest(".lf-retry")) retryLoad();
    });
    // Bound directly, not delegated: these two are built once with the form and
    // survive every re-render of .lf-app, which is the whole point of moving them.
    //
    // The guard is what aria-disabled costs, and a press that lands on it says
    // why rather than doing nothing — a dead click is the one thing worse than a
    // control you cannot reach. (Enter and Space on a focused button both arrive
    // here as a click, so this is the only place that needs to check.)
    if (printBtn) printBtn.addEventListener("click", function () {
      if (unavailable(printBtn)) {
        actionsNote(whyUnavailable("prints the label"), "guard");
        return;
      }
      window.print();
    });
    if (svgBtn) svgBtn.addEventListener("click", function () {
      if (unavailable(svgBtn)) {
        // "Nothing happened" is the wrong answer to every one of these — least of
        // all to a second press on a sheet already drawing.
        actionsNote(whySheetUnavailable(), "guard");
        return;
      }
      saveSheet(svgBtn);
    });
    // Prefetch on intent: a pointer resting on the combined view's button, a
    // finger landing on it, or a keyboard tab onto it all mean the click is
    // probably coming, and the roster is the one thing that gates the picker.
    // Fetching it now takes it off the click's critical path entirely. Only the
    // roster — a constant, cached for a day — never the sweep, which is a real
    // scoring request that shares the reader's rate-limit budget.
    if (wantBuildDensity) {
      ["mouseover", "focusin", "touchstart"].forEach(function (ev) {
        app.addEventListener(ev, function (e) {
          var t = e.target;
          if (t && t.closest && t.closest('button[data-mode="buildDensity"]')) loadProfiles();
        }, { passive: true });
      });
    }
    app.addEventListener("change", function (e) {
      var t = e.target;
      // The combined view's picker changes what gets swept, not just what's
      // drawn, so it goes through the loader (cached profiles repaint instantly).
      if (t.classList.contains("lf-d-sel")) {
        state.buildSlug = t.value;     // slug, not position
        syncIdxFromSlug();             // carry the choice into "What-if build"
        loadDensity(false);
        return;
      }
      if (t.classList.contains("lf-p-sel")) state.idx = +t.value;
      else if (t.classList.contains("lf-a-sel")) state.idxA = +t.value;
      else if (t.classList.contains("lf-b-sel")) state.idxB = +t.value;
      else return;
      render();
    });
    function setMode(m) {
      if (m === state.mode || modes.indexOf(m) < 0) return;
      state.mode = m; state.error = null;
      // The two profile-picking views stay on the same build as the reader moves
      // between them — by slug, since their lists can come from different places.
      if (m === "buildDensity") {
        if (!state.buildSlug) syncSlugFromIdx();
        if (!state.buildSlug) state.buildSlug = defaultSlug(profileList());
      } else if (m === "single" || m === "compare") {
        syncIdxFromSlug();
      }
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
      ac.close(); geoStatus(""); poiHintEl.style.display = "none";   // 422 notice replaces the pre-hint
      var addr = addrInput.value.trim(), p = ac.picked();
      if (p && p.label === addr) {
        // A Google pick carries a place_id, not coordinates — resolve them (Place
        // Details) before scoring. Fill the gap with a loading line so the button
        // feels responsive during the lookup. Carry the geocoder's non-residential
        // verdict so the scorer refuses a stadium/office the coordinate can't reveal.
        app.innerHTML = loadingHtml();
        mainStatus.busy("Looking up this address…", p.label);
        setFormBusy(true);
        ac.resolvePicked().then(function (rp) {
          // Forward the geocoder's non-residential verdict on BOTH paths — a
          // failed /place lookup must not let a flagged business slip through by
          // geocoding its name (the API screens `nonresidential` on ?address= too).
          var nonRes = !!(rp && rp.residential === false);
          if (rp && rp.lat != null && rp.lon != null) {
            load({ lat: rp.lat, lon: rp.lon, label: rp.label, nonResidential: nonRes });
          } else {
            load({ address: addr, nonResidential: nonRes });   // coords unresolved → geocode the text
          }
        });
        return;
      }
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
      geoStatus(""); locateBtn.disabled = true;
      // The permission prompt + fix can take a while, so it gets the same banner
      // as a score rather than a one-line "Locating…" that reads as nothing.
      mainStatus.busy("Getting your location…", "Waiting for your browser to share it.");
      navigator.geolocation.getCurrentPosition(
        function (pos) {
          locateBtn.disabled = false; geoStatus(""); ac.close(); addrInput.value = "";
          // No label here: "your location" isn't a re-typable address, so it must
          // not be persisted as pre-fill text for the next visit.
          load({ lat: pos.coords.latitude, lon: pos.coords.longitude });
        },
        function (err) {
          locateBtn.disabled = false;
          mainStatus.hide();
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
