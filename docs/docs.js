// Interactions for the reference and setup docs pages: an ARIA tab widget for the
// grouped upgrade tables, scroll-spy highlighting of the "On this page" rail, and
// auto-opening a collapsed section when its anchor is targeted. All progressive
// enhancement — with JS off the tabs show stacked and the rail is plain anchors.
document.addEventListener('DOMContentLoaded', function () {
  var slice = function (nl) { return Array.prototype.slice.call(nl); };

  // ── Tabs ──────────────────────────────────────────────────────────────────
  slice(document.querySelectorAll('.tabs[data-tabs]')).forEach(function (tabs) {
    var tablist = slice(tabs.querySelectorAll('[role="tab"]'));
    var panels = slice(tabs.querySelectorAll('[role="tabpanel"]'));
    if (tablist.length < 2 || panels.length !== tablist.length) return;
    tabs.classList.add('js-tabs');
    function select(i) {
      tablist.forEach(function (t, j) {
        var on = j === i;
        t.setAttribute('aria-selected', on ? 'true' : 'false');
        t.tabIndex = on ? 0 : -1;
      });
      panels.forEach(function (p, j) { p.classList.toggle('is-active', j === i); });
    }
    var start = tablist.findIndex(function (t) { return t.getAttribute('aria-selected') === 'true'; });
    select(start < 0 ? 0 : start);
    tablist.forEach(function (t, i) {
      t.addEventListener('click', function () { select(i); });
      t.addEventListener('keydown', function (e) {
        var n = tablist.length, next = -1;
        if (e.key === 'ArrowRight' || e.key === 'ArrowDown') next = (i + 1) % n;
        else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') next = (i - 1 + n) % n;
        else if (e.key === 'Home') next = 0;
        else if (e.key === 'End') next = n - 1;
        if (next >= 0) { e.preventDefault(); select(next); tablist[next].focus(); }
      });
    });
  });

  // ── "On this page" rail: open a collapsed section on anchor, and scroll-spy ──
  var links = slice(document.querySelectorAll('.doc-toc a[href^="#"]'));
  var linkById = {};
  links.forEach(function (a) { linkById[a.getAttribute('href').slice(1)] = a; });

  function openTarget(id) {
    var sec = document.getElementById(id);
    if (!sec) return;
    var det = sec.matches('details') ? sec : sec.querySelector('details.acc');
    if (det && !det.open) det.open = true;
  }
  links.forEach(function (a) {
    a.addEventListener('click', function () { openTarget(a.getAttribute('href').slice(1)); });
  });
  if (location.hash) openTarget(location.hash.slice(1));
  window.addEventListener('hashchange', function () { if (location.hash) openTarget(location.hash.slice(1)); });

  var sections = links
    .map(function (a) { return document.getElementById(a.getAttribute('href').slice(1)); })
    .filter(Boolean);
  if ('IntersectionObserver' in window && sections.length) {
    var spy = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (!en.isIntersecting) return;
        var a = linkById[en.target.id];
        if (!a) return;
        links.forEach(function (l) { l.classList.remove('active'); });
        a.classList.add('active');
      });
    }, { rootMargin: '-15% 0px -75% 0px', threshold: 0 });
    sections.forEach(function (s) { spy.observe(s); });
  }
});
