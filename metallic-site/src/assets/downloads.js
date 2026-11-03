/* Downloads: the newest build from /releases/latest.json (the Tauri updater manifest:
   {"version","notes","pub_date","platforms":{"windows-x86_64":{"signature","url"},"linux-x86_64":{..AppImage},
   "linux-x86_64-deb":{..deb}}}), and the Meta Quest APK from /releases/quest.json ({"version","url"}). */
"use strict";
(async () => {
  const M = window.Metallic;
  const $ = (s) => document.querySelector(s);
  M.quest().then((q) => {
    if (!q) return;
    const a = $("[data-quest-dl]");
    a.href = q.url;
    a.removeAttribute("aria-disabled");
    a.textContent = "Download for Quest (APK)";
    $("[data-quest-note]").textContent = "Early Access " + q.version + " · Android app for Meta Quest 2, 3, 3S and Pro, installed by sideloading.";
  });
  const r = await M.release;
  const btn = $("[data-dl-main]");
  if (!r) {
    btn.setAttribute("aria-disabled", "true");
    btn.removeAttribute("href");
    btn.textContent = "Not published yet";
    return;
  }
  $("[data-wait]").hidden = true;
  const v = $("[data-version]");
  v.replaceChildren("Early Access ", M.el("b", null, r.version), r.linux ? " for Windows and Linux" : " for Windows");
  // Linux: the AppImage (any distro) and the .deb, when this release has them
  if (r.linux) {
    $("[data-linux]").hidden = false;
    $("[data-dl-appimage]").href = r.linux.appimage;
    if (r.linux.deb) $("[data-dl-deb]").href = r.linux.deb; else $("[data-deb]").hidden = true;
  }
  $('[data-f="version"]').textContent = r.version;
  const d = r.date ? new Date(r.date) : null;
  $('[data-f="date"]').textContent = d && !isNaN(d) ? M.date(d.getTime() / 1000, true) : "Not stated";
  // File and Size describe the desktop build this visitor's button gives: the AppImage on Linux, else the Windows installer
  const main = M.onLinux && r.linux ? r.linux.appimage : r.url;
  const file = decodeURIComponent(main.split("?")[0].split("/").pop() || "");
  if (file) $('[data-f="file"]').textContent = file;

  M.downloads.then((n) => { if (n != null) $('[data-f="downloads"]').textContent = M.num(n); });

  // size: only asked for when the installer is on this site (connect-src 'self')
  const size = $('[data-f="size"]');
  size.textContent = "Not stated";
  try {
    const u = new URL(main, location.href);
    if (u.origin === location.origin) {
      const h = await fetch(u.href, { method: "HEAD", cache: "no-store" });
      const n = Number(h.headers.get("Content-Length"));
      if (h.ok && n > 0) size.textContent = (n / 1048576).toFixed(n < 10485760 ? 1 : 0) + " MB";
    }
  } catch (e) { /* stays "Not stated" */ }

  // notes: plain text; blank lines split paragraphs, "- " or "* " lines become a list
  const box = $("[data-notes]"), out = [];
  const blocks = (r.notes || "").replace(/\r/g, "").split(/\n\s*\n/).map((b) => b.trim()).filter(Boolean);
  blocks.forEach((b) => {
    const lines = b.split("\n").map((l) => l.trim());
    if (lines.every((l) => /^[-*] /.test(l))) {
      const ul = M.el("ul");
      lines.forEach((l) => ul.append(M.el("li", null, l.slice(2).replace(/\*\*/g, ""))));
      out.push(ul);
    } else out.push(M.el("p", null, lines.join(" ").replace(/^#+\s*/, "").replace(/\*\*/g, "")));
  });
  if (out.length) box.replaceChildren(...out);
  else box.replaceChildren(M.el("p", null, "This build has no release notes."));
})();
