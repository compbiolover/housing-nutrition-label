// Mobile nav toggle — vanilla, no deps.
document.addEventListener('click', function (e) {
  var toggle = e.target.closest('.nav-toggle');
  if (toggle) {
    var links = document.querySelector('.nav-links');
    if (links) links.classList.toggle('open');
    return;
  }
  // Close menu when a link is tapped
  if (e.target.closest('.nav-links a')) {
    var open = document.querySelector('.nav-links.open');
    if (open) open.classList.remove('open');
  }
});
