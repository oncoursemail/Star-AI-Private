/* Home page: replace the "no release yet" line when the stable channel has a launcher build. */
(function () {
  "use strict";
  var line = document.querySelector("[data-latest]");
  if (!line) return;
  fetch("/releases/channels/stable.json", { cache: "no-store" })
    .then(function (r) { if (!r.ok) throw new Error(String(r.status)); return r.json(); })
    .then(function (m) {
      var c = m.components && m.components.launcher;
      if (!c) return;
      var d = new Date(c.released);
      line.textContent = "Latest stable launcher: " + c.version + (isNaN(d) ? "" : ", released " + d.toLocaleDateString(undefined, { day: "numeric", month: "long", year: "numeric" })) + ".";
    })
    .catch(function () { /* keep the honest default text */ });
})();
