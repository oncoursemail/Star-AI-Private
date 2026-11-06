/* Downloads: one box with a tile per device (Windows, Linux, Mac, Android, Meta Quest) and the chosen device's panel. The
   visitor's own device is picked and marked "This device"; #windows, #linux, #mac, #android or #quest in the address picks
   one too. The Mac tile stays hidden until the release has a .dmg ("darwin-aarch64-dmg", "darwin-x86_64-dmg"), and the
   Android tile until /releases/android.json exists ({"version","url"}).
   Builds come from /releases/latest.json (the Tauri updater manifest: {"version","notes","pub_date","platforms":
   {"windows-x86_64":{"signature","url"},"linux-x86_64":{..AppImage},"linux-x86_64-deb":{..deb}}}) and the Quest APK
   from /releases/quest.json ({"version","url"}). Until a build is published its button stays disabled. */
"use strict";
(async () => {
  const M = window.Metallic;
  const $ = (s) => document.querySelector(s);
  const $$ = (s) => document.querySelectorAll(s);
  const { onPhone, onMac } = M;
  const device = M.onQuest ? "quest" : M.onLinux ? "linux" : onMac || onPhone ? null : "windows";

  // ---- picking a device ----
  const pick = (id, fromUser) => {
    $$("[data-plat]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.plat === id)));
    $$("[data-pane]").forEach((p) => { p.hidden = p.dataset.pane !== id; });
    if (fromUser) history.replaceState(null, "", "#" + id);
  };
  $$("[data-plat]").forEach((b) => b.addEventListener("click", () => pick(b.dataset.plat, true)));
  // arrow keys move between the tiles
  $(".plats").addEventListener("keydown", (e) => {
    const tiles = [...$$("[data-plat]")].filter((t) => !t.hidden), i = tiles.indexOf(document.activeElement);
    const step = { ArrowDown: 1, ArrowRight: 1, ArrowUp: -1, ArrowLeft: -1 }[e.key];
    if (i < 0 || !step) return;
    e.preventDefault();
    const next = tiles[(i + step + tiles.length) % tiles.length];
    next.focus();
    pick(next.dataset.plat, true);
  });
  if (device) $(`[data-plat="${device}"] .here`).hidden = false;
  const fromHash = ["windows", "linux", "quest"].find((id) => location.hash === "#" + id);
  pick(fromHash || device || "windows");
  const note = $("[data-pick-note]");
  if (onMac) note.textContent = "Metallic does not run on macOS yet. Download it for a Windows or Linux PC, or a Meta Quest headset.";
  else if (onPhone) note.textContent = "Metallic runs on a Windows or Linux PC and on Meta Quest. Open this page there, or pick a device below.";
  else if (device === "quest") note.textContent = "You are on a Meta Quest, so the Quest app is picked for you.";
  else if (device === "linux") note.textContent = "You are on Linux, so the Linux build is picked for you.";
  else note.textContent = "You are on Windows, so the Windows installer is picked for you.";

  // ---- a button that downloads a file (its file name shows on hover) ----
  const fileName = (url) => decodeURIComponent(url.split("?")[0].split("/").pop() || "");
  const arm = (a, url, label) => {
    a.href = url;
    a.removeAttribute("aria-disabled");
    a.hidden = false;
    a.querySelector("span").textContent = label;
    a.title = fileName(url);
  };
  // size: only asked for when the file is on this site (connect-src 'self')
  const sizeOf = async (url, el) => {
    try {
      const u = new URL(url, location.href);
      if (u.origin !== location.origin) return;
      const h = await fetch(u.href, { method: "HEAD", cache: "no-store" });
      const n = Number(h.headers.get("Content-Length"));
      if (h.ok && n > 0) el.textContent = (n / 1048576).toFixed(n < 10485760 ? 1 : 0) + " MB";
    } catch (e) { /* stays "Not stated" */ }
  };

  M.downloads.then((n) => { if (n != null) $('[data-f="downloads"]').textContent = M.num(n); else $(".dl-count").hidden = true; });

  M.android().then((a) => {
    if (!a) return;
    $('[data-plat="android"]').hidden = false;
    arm($("[data-android-dl]"), a.url, "Download for Android");
    $("[data-android-v]").textContent = a.version;
    sizeOf(a.url, $('[data-size="android"]'));
    if (M.onAndroid) {
      $('[data-plat="android"] .here').hidden = false;
      note.textContent = "You are on Android, so the phone and tablet app is picked for you.";
    }
    if (location.hash === "#android" || (M.onAndroid && !fromHash)) pick("android");
  });

  M.quest().then((q) => {
    if (!q) return;
    arm($("[data-quest-dl]"), q.url, "Download for Quest");
    $("[data-plat-sub='quest']").textContent = "Quest app";
    $("[data-quest-v]").textContent = q.version;
    sizeOf(q.url, $('[data-size="quest"]'));
  });

  const r = await M.release;
  if (!r) return;
  $$('[data-v="version"]').forEach((e) => { e.textContent = r.version; });
  const d = r.date ? new Date(r.date) : null;
  $$('[data-v="date"]').forEach((e) => { e.textContent = d && !isNaN(d) ? M.date(d.getTime() / 1000, true) : "Not stated"; });

  arm($('[data-get="windows"]'), r.url, "Download for Windows");
  sizeOf(r.url, $('[data-size="windows"]'));

  // Linux: the AppImage (any distribution) and the .deb, when this release has them
  if (r.linux) {
    arm($('[data-get="linux"]'), r.linux.appimage, "Download AppImage");
    if (r.linux.deb) arm($('[data-get="deb"]'), r.linux.deb, ".deb package");
    $("[data-plat-sub='linux']").textContent = r.linux.deb ? "AppImage or .deb" : "AppImage";
    sizeOf(r.linux.appimage, $('[data-size="linux"]'));
  }

  // Mac: a .dmg per chip, and only now does the tile exist
  if (r.mac) {
    $('[data-plat="mac"]').hidden = false;
    if (r.mac.arm) arm($('[data-get="mac-arm"]'), r.mac.arm, "Download for Apple silicon");
    if (r.mac.intel) arm($('[data-get="mac-intel"]'), r.mac.intel, "Download for Intel");
    sizeOf(r.mac.arm || r.mac.intel, $('[data-size="mac"]'));
    if (onMac) {
      $('[data-plat="mac"] .here').hidden = false;
      note.textContent = "You are on a Mac, so the Mac build is picked for you.";
    } else if (onPhone) note.textContent = "Metallic runs on a Windows, Linux or Mac computer and on Meta Quest. Open this page there, or pick a device below.";
    if (location.hash === "#mac" || (onMac && !fromHash)) pick("mac");
  }

  // notes: plain text; blank lines split paragraphs, "- " or "* " lines become a list
  $("[data-notes-h]").textContent = "What is new in " + r.version;
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
