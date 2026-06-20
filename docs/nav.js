document.addEventListener('DOMContentLoaded', function() {
  var btn = document.querySelector('.hamburger');
  var menu = document.querySelector('nav ul');
  if (btn && menu) {
    btn.addEventListener('click', function() { menu.classList.toggle('open'); });
  }
});
