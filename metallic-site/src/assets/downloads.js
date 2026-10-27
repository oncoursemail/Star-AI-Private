/* Downloads page: lists what the release channel really contains. Reads /releases/channels/<channel>.json, the same
   file the launcher verifies. The browser cannot check the signature, so this page only describes; the launcher
   verifies. Text goes in through textContent. */
(function () {
  "use strict";
  var list = document.getElementById("dl-list");
  var note = document.getElementById("dl-channel-note");
  var buttons = Array.prototype.slice.call(document.querySelectorAll("[data-channel]"));
  var NOTES = {
    stable: "Stable builds are the ones we recommend.",
    beta: "Beta builds are tried here first. They can break; the launcher can switch back to the last good version."
  };
  var NAMES = { launcher: "Metallic Launcher", litha: "Litha add-on", rc: "Metallic RC", mc: "Metallic MC", rb: "Metallic RB" };

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }
  function size(n) {
    if (n >= 1 << 30) return (n / (1 << 30)).toFixed(1) + " GB";
    if (n >= 1 << 20) return (n / (1 << 20)).toFixed(1) + " MB";
    return Math.max(1, Math.round(n / 1024)) + " KB";
  }
  function day(iso) {
    var d = new Date(iso);
    return isNaN(d) ? "" : d.toLocaleDateString(undefined, { day: "numeric", month: "long", year: "numeric" });
  }
  function empty(text) { list.textContent = ""; list.appendChild(el("p", "empty", text)); }

  function render(manifest, channel) {
    list.textContent = "";
    var names = Object.keys(manifest.components || {}).sort();
    if (!names.length) return empty("Nothing has been published on the " + channel + " channel yet.");
    names.forEach(function (name) {
      var c = manifest.components[name];
      var card = el("article", "dl-card");
      var main = el("div");
      var h = el("h3", null, NAMES[name] || name);
      h.appendChild(el("span", "ver", "version " + c.version));
      main.appendChild(h);
      var meta = [c.released ? "Released " + day(c.released) : "", c.platform && c.platform !== "any" ? c.platform : "", size(c.size || 0) + " installed"].filter(Boolean);
      main.appendChild(el("p", "dl-meta", meta.join(" · ")));
      if (c.notes) main.appendChild(el("p", "dl-notes", c.notes));
      if (c.installer) main.appendChild(el("p", "hash", "SHA-256 " + c.installer.sha256));
      card.appendChild(main);
      var act = el("div", "act");
      if (c.installer) {
        var a = el("a", "btn primary", "Download (" + size(c.installer.size) + ")");
        a.href = "/releases/" + c.installer.path.split("/").map(encodeURIComponent).join("/");
        act.appendChild(a);
      } else {
        act.appendChild(el("p", "m3", "Installed and updated by the launcher."));
      }
      card.appendChild(act);
      list.appendChild(card);
    });
  }

  function load(channel) {
    note.textContent = NOTES[channel] || "";
    note.className = channel === "beta" ? "warn" : "m3";
    buttons.forEach(function (b) { b.setAttribute("aria-pressed", String(b.dataset.channel === channel)); });
    empty("Loading the release list...");
    fetch("/releases/channels/" + channel + ".json", { cache: "no-store" })
      .then(function (r) { if (!r.ok) throw new Error(String(r.status)); return r.json(); })
      .then(function (m) { render(m, channel); })
      .catch(function () { empty("No " + channel + " release has been published yet."); });
  }

  buttons.forEach(function (b) { b.addEventListener("click", function () { load(b.dataset.channel); }); });
  load("stable");

})();
