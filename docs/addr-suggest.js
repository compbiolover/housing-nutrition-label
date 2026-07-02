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

    var picked = null;   // {label, lat, lon} once chosen; cleared on edit
    var items = [];      // current suggestion objects
    var active = -1;     // highlighted index for keyboard nav
    var timer = null;    // debounce handle
    var seq = 0;         // request sequence — drop out-of-order responses

    function setExpanded(v) { if (wrap) wrap.setAttribute("aria-expanded", v ? "true" : "false"); }

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
      fetch(apiBase + "/suggest?q=" + encodeURIComponent(q))
        .then(function (r) { return r.ok ? r.json() : []; })
        .then(function (list) { if (mine === seq) render(Array.isArray(list) ? list : []); })
        .catch(function () { if (mine === seq) close(); });   // never throw to the page
    }

    function choose(i) {
      var s = items[i]; if (!s) return;
      picked = s;                 // remember {label, lat, lon}
      input.value = s.label;
      close();
      onPick(s);
    }

    input.addEventListener("input", function () {
      if (picked) { picked = null; onPick(null); }   // editing invalidates a prior pick
      var q = input.value.trim();
      clearTimeout(timer);
      // Drop any highlight from the now-stale list so a fast Enter (before the
      // debounced fetch returns) can't select a suggestion for the old query.
      setActive(-1);
      if (!apiBase || q.length < minChars) { close(); return; }
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
      close: close
    };
  }

  return { attach: attach };
})();
