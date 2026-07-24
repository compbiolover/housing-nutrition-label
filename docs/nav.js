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
    btn.addEventListener('click', function() { setOpen(!menu.classList.contains('open')); });
    // Close on Escape or after following a link, so the menu never traps focus.
    menu.addEventListener('click', function(e) { if (e.target.closest('a')) setOpen(false); });
    document.addEventListener('keydown', function(e) {
      if (e.key === 'Escape' && menu.classList.contains('open')) { setOpen(false); btn.focus(); }
    });
  }
});
