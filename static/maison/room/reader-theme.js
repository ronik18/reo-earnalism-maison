/* Night first: runs before first paint, so the header never flashes light. A saved theme always wins. */
(function () {
  var themes = ["light", "sepia", "dark", "true_black"];
  var body = document.body;
  if (!body || /(^|\s)reader-theme-/.test(body.className)) return;
  var saved = null;
  try {
    var stored = JSON.parse(localStorage.getItem("maison.reader.preferences") || "{}");
    if (stored && themes.indexOf(stored.reader_theme) >= 0) saved = stored.reader_theme;
  } catch (e) {}
  var dark = false;
  try {
    dark = !!(window.matchMedia && matchMedia("(prefers-color-scheme: dark)").matches);
  } catch (e) {}
  body.classList.add("reader-theme-" + (saved || (dark ? "dark" : "light")));
})();
