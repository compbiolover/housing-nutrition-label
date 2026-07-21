/* addr-suggest.js — shared address autocomplete for the Housing Nutrition Label
 * site, backed by the scoring API's /suggest proxy. Used by index.html,
 * examples.html, and label.html so there is one debounced-typeahead
 * implementation (keyboard nav + ARIA combobox wiring included).
 *
 * Usage:
 *   var ac = AddrSuggest.attach({
 *     input:   <input> element,
 *     box:     <ul> listbox element,
 *     apiBase: scoring-API base URL (calls apiBase + "/suggest?q="),
 *     onPick:  optional fn(suggestion | null) — a {label, lat, lon} object when
 *              a suggestion is chosen, or null when the user edits (invalidating
 *              a prior pick),
 *   });
 *   // In the form's submit handler:
 *   var p = ac.picked();            // current {label, lat, lon} or null
 *   if (p && p.label === input.value.trim()) { ...score p.lat / p.lon directly... }
 *   ac.close();                     // dismiss the suggestion list
 *
 * No build step: exposes a single global `window.AddrSuggest`.
 */
window.AddrSuggest = (function () {
  "use strict";

  function esc(s) { var d = document.createElement("div"); d.textContent = s == null ? "" : s; return d.innerHTML; }

  function attach(opts) {
    var input = opts.input;
    var box = opts.box;
    var apiBase = opts.apiBase || "";
    var onPick = typeof opts.onPick === "function" ? opts.onPick : function () {};
    var minChars = opts.minChars || 3;
    var idPrefix = opts.idPrefix || ((box.id || "addr") + "-opt-");
    // The element carrying aria-expanded (the combobox wrapper), if present.
    var wrap = (input.closest && input.closest('[aria-haspopup="listbox"], .addr-ac')) || null;

    var picked = null;   // chosen suggestion; cleared on edit. Google results carry a
                         // {label, place_id} (coords resolved on pick via /place);
                         // Geoapify/Photon carry {label, lat, lon} directly.
    var items = [];      // current suggestion objects
    var active = -1;     // highlighted index for keyboard nav
    var timer = null;    // debounce handle
    var seq = 0;         // request sequence — drop out-of-order responses
    var session = null;  // Google session token: bundles a typeahead's autocomplete
                         // calls + its one /place lookup into one billed session.

    function setExpanded(v) { if (wrap) wrap.setAttribute("aria-expanded", v ? "true" : "false"); }

    function newToken() {
      try { if (window.crypto && crypto.randomUUID) return crypto.randomUUID(); } catch (e) {}
      return "s-" + new Date().getTime().toString(36) + "-"
        + Math.random().toString(36).slice(2) + Math.random().toString(36).slice(2);
    }

    function close() {
      clearTimeout(timer);   // cancel a pending debounced fetch
      seq++;                 // invalidate any in-flight /suggest response (mine !== seq)
      box.hidden = true; box.innerHTML = ""; items = []; active = -1;
      setExpanded(false);
      input.setAttribute("aria-activedescendant", "");
    }

    function setActive(i) {
      var lis = box.querySelectorAll("li");
      for (var j = 0; j < lis.length; j++) {
        var on = j === i;
        lis[j].classList.toggle("active", on);
        lis[j].setAttribute("aria-selected", on ? "true" : "false");
      }
      active = i;
      input.setAttribute("aria-activedescendant", i >= 0 ? idPrefix + i : "");
    }

    function render(list) {
      items = list; active = -1;
      if (!list.length) { close(); return; }
      box.innerHTML = list.map(function (s, i) {
        return '<li role="option" id="' + idPrefix + i + '" data-i="' + i + '" aria-selected="false">' + esc(s.label) + '</li>';
      }).join("");
      box.hidden = false;
      setExpanded(true);
    }

    function fetchSuggest(q) {
      var mine = ++seq;
      if (!session) session = newToken();   // one session per typeahead → selection
      fetch(apiBase + "/suggest?q=" + encodeURIComponent(q) + "&session=" + encodeURIComponent(session))
        .then(function (r) { return r.ok ? r.json() : []; })
        .then(function (list) { if (mine === seq) render(Array.isArray(list) ? list : []); })
        .catch(function () { if (mine === seq) close(); });   // never throw to the page
    }

    // Resolve a picked suggestion to coordinates. Geoapify/Photon results already
    // have lat/lon; a Google result has only a place_id → GET /place (Place Details)
    // closes the session and fills in lat/lon (+ refined label/residential). The
    // promise is cached on the picked object so an eager pick-time resolve and the
    // submit-time await share one network call. Never rejects — resolves to the
    // picked object (with coords when available), so the caller can fall back to
    // geocoding the label text if resolution failed.
    function resolvePicked() {
      if (!picked) return Promise.resolve(null);
      if (picked._resolve) return picked._resolve;
      if (picked.lat != null && picked.lon != null) {
        picked._resolve = Promise.resolve(picked); return picked._resolve;
      }
      if (!picked.place_id || !apiBase) {
        picked._resolve = Promise.resolve(picked); return picked._resolve;
      }
      var target = picked, sess = session;
      var url = apiBase + "/place?place_id=" + encodeURIComponent(picked.place_id)
        + (sess ? "&session=" + encodeURIComponent(sess) : "");
      session = null;             // this session is spent on the details lookup
      picked._resolve = fetch(url)
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (d) {
          if (d && d.lat != null && d.lon != null) {
            target.lat = d.lat; target.lon = d.lon;
            // Keep the label the user picked (still in the input) — overwriting it
            // with the details label breaks the submit-time input-vs-pick match.
            // Only ever *add* a non-residential flag (never downgrade one the
            // prediction already set), so the screen can't be lost on resolve.
            if (d.residential === false) target.residential = false;
          }
          return target;
        })
        .catch(function () { return target; });   // network error → caller falls back
      return picked._resolve;
    }

    function choose(i) {
      var s = items[i]; if (!s) return;
      picked = s;
      input.value = s.label;
      close();
      resolvePicked();            // eager: have coords ready by the time Score is pressed
      onPick(s);
    }

    input.addEventListener("input", function () {
      if (picked) { picked = null; onPick(null); }   // editing invalidates a prior pick
      var q = input.value.trim();
      clearTimeout(timer);
      // Drop any highlight from the now-stale list so a fast Enter (before the
      // debounced fetch returns) can't select a suggestion for the old query.
      setActive(-1);
      // Query cleared below the threshold → end this typeahead session so the next
      // real search starts a fresh Google token (don't bill two searches as one).
      if (!apiBase || q.length < minChars) { session = null; close(); return; }
      timer = setTimeout(function () { fetchSuggest(q); }, 250);
    });
    input.addEventListener("keydown", function (e) {
      if (box.hidden || !items.length) return;
      if (e.key === "ArrowDown") { e.preventDefault(); setActive((active + 1) % items.length); }
      else if (e.key === "ArrowUp") { e.preventDefault(); setActive((active - 1 + items.length) % items.length); }
      else if (e.key === "Enter" && active >= 0) { e.preventDefault(); choose(active); }
      else if (e.key === "Escape") { close(); }
    });
    box.addEventListener("mousedown", function (e) {   // mousedown beats input blur
      var li = e.target.closest ? e.target.closest("li[data-i]") : null;
      if (!li) return;
      e.preventDefault();
      choose(parseInt(li.getAttribute("data-i"), 10));
    });
    input.addEventListener("blur", function () { setTimeout(close, 120); });

    return {
      picked: function () { return picked; },
      resolvePicked: resolvePicked,
      close: close
    };
  }

  return { attach: attach };
})();
