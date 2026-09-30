// Runs before the page paints, so the chosen theme shows without a flash.
(function () {
  var theme = 'system';
  try { theme = localStorage.getItem('pi-theme') || 'system'; } catch (e) { /* storage blocked */ }
  if (['light', 'dark', 'system'].indexOf(theme) < 0) theme = 'system';
  document.documentElement.setAttribute('data-theme', theme);
})();
