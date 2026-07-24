document.addEventListener('DOMContentLoaded', function() {
  var btn = document.querySelector('.hamburger');
  var menu = document.querySelector('nav ul');
  if (btn && menu) {
    btn.setAttribute('aria-expanded', 'false');
    btn.setAttribute('aria-controls', menu.id || (menu.id = 'primary-nav'));
    function setOpen(open) {
      menu.classList.toggle('open', open);
      btn.setAttribute('aria-expanded', open ? 'true' : 'false');
    }
    btn.addEventListener('click', function(e) { e.stopPropagation(); setOpen(!menu.classList.contains('open')); });
    // Close after following a link, so the menu never traps focus.
    menu.addEventListener('click', function(e) { if (e.target.closest('a')) setOpen(false); });
    // Close on Escape (returning focus to the toggle) or on a click outside the menu.
    document.addEventListener('keydown', function(e) {
      if (e.key === 'Escape' && menu.classList.contains('open')) { setOpen(false); btn.focus(); }
    });
    document.addEventListener('click', function(e) {
      if (menu.classList.contains('open') && !menu.contains(e.target) && e.target !== btn) setOpen(false);
    });
  }

  // Make each horizontally-scrollable table a keyboard-reachable region and fade
  // the clipped edge as a cue. Only tables that actually overflow become focusable,
  // so we don't add empty tab stops on desktop where everything fits.
  var scrollers = document.querySelectorAll('.table-scroll');
  Array.prototype.forEach.call(scrollers, function(el) {
    function update() {
      var overflow = el.scrollWidth - el.clientWidth > 1;
      if (overflow && !el.hasAttribute('tabindex')) {
        el.setAttribute('tabindex', '0');
        el.setAttribute('role', 'region');
        if (!el.hasAttribute('aria-label')) el.setAttribute('aria-label', 'Table, scroll sideways to see more');
      } else if (!overflow && el.getAttribute('tabindex') === '0') {
        el.removeAttribute('tabindex'); el.removeAttribute('role');
      }
      el.classList.toggle('can-scroll-left', overflow && el.scrollLeft > 1);
      el.classList.toggle('can-scroll-right', overflow && el.scrollLeft < el.scrollWidth - el.clientWidth - 1);
    }
    el.addEventListener('scroll', update, { passive: true });
    window.addEventListener('resize', update);
    update();
  });
});
