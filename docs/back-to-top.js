/* back-to-top.js — a shared, dependency-free "back to top" floating button.
 *
 * Include on any long page (e.g. methodology). The button self-injects, stays
 * hidden until the reader scrolls past a threshold, then fades in at the
 * bottom-right and smooth-scrolls to the top on click. No build step and no
 * inline handlers (CSP-safe); styling lives in style.css (.back-to-top).
 */
(function () {
  "use strict";
  if (typeof document === "undefined") return;

  function init() {
    if (document.querySelector(".back-to-top")) return;   // avoid a double-insert

    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "back-to-top";
    btn.setAttribute("aria-label", "Back to top");
    btn.title = "Back to top";
    btn.innerHTML = '<span aria-hidden="true">&#8593;</span>';
    document.body.appendChild(btn);

    var SHOW_AT = 600;   // px scrolled before the button appears
    var reduce = false;
    try { reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches; } catch (e) {}

    function currentY() { return window.pageYOffset || document.documentElement.scrollTop || 0; }
    function sync() { btn.classList.toggle("show", currentY() > SHOW_AT); }

    // rAF-throttled passive scroll handler — cheap even on a very long page.
    var ticking = false;
    window.addEventListener("scroll", function () {
      if (ticking) return;
      ticking = true;
      window.requestAnimationFrame(function () { sync(); ticking = false; });
    }, { passive: true });
    sync();   // set the initial state (e.g. when reloaded mid-page)

    btn.addEventListener("click", function () {
      window.scrollTo({ top: 0, behavior: reduce ? "auto" : "smooth" });
      // Don't strand keyboard users at the bottom: move focus to the first
      // focusable element (the nav logo) without yanking the scroll position.
      var first = document.querySelector("nav .logo");
      if (first) { try { first.focus({ preventScroll: true }); } catch (e) { first.focus(); } }
    });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
