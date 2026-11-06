/* Shared by every page: safe JSON loading, number and date formats, the download button, and entrances. Text goes in with textContent only. */
"use strict";
document.documentElement.classList.add("js");

const M = (window.Metallic = {});
const CDN = "https://cdn.discordapp.com/";
M.reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

// a missing, broken or slow file (no answer in 10 s) gives null, so every block keeps its empty state
M.json = async (url) => {
  const ctl = "AbortController" in window ? new AbortController() : null;
  const timer = ctl && setTimeout(() => ctl.abort(), 10000);
  try {
    const r = await fetch(url, { cache: "no-store", headers: { Accept: "application/json" }, signal: ctl ? ctl.signal : undefined });
    if (!r.ok) return null;
    return await r.json();
  } catch (e) {
    return null;
  } finally {
    clearTimeout(timer);
  }
};
M.num = (n) => (typeof n === "number" && isFinite(n) ? Math.round(n).toLocaleString("en-US") : null);
M.cdn = (u) => (typeof u === "string" && u.startsWith(CDN) ? u : null);           // CSP allows only this image host
M.href = (u) => (typeof u === "string" && /^https:\/\/[^\s"'<>]+$/.test(u) ? u : null);
M.el = (tag, cls, text) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
};
M.img = (src, alt, size, cls) => {
  const i = M.el("img", cls);
  i.src = src; i.alt = alt || ""; i.width = size; i.height = size; i.loading = "lazy"; i.decoding = "async";
  i.addEventListener("error", () => i.remove(), { once: true });
  return i;
};
M.ago = (sec) => {
  if (typeof sec !== "number") return null;
  const m = Math.max(0, Math.round((Date.now() / 1000 - sec) / 60));
  if (m < 1) return "just now";
  if (m < 60) return m + (m === 1 ? " minute ago" : " minutes ago");
  const h = Math.round(m / 60);
  if (h < 48) return h + (h === 1 ? " hour ago" : " hours ago");
  return Math.round(h / 24) + " days ago";
};
M.date = (sec, withYear) => {
  const d = new Date(sec * 1000);
  if (isNaN(d)) return "";
  return d.toLocaleDateString("en-GB", withYear ? { day: "numeric", month: "long", year: "numeric" } : { day: "numeric", month: "short" });
};

// newest build, from the Tauri updater manifest (Linux: "linux-x86_64" is the AppImage, "linux-x86_64-deb" the .deb;
// macOS: "darwin-*" is the updater's .app.tar.gz, "darwin-*-dmg" the .dmg people download)
M.release = M.json("/releases/latest.json").then((m) => {
  const p = (m && m.platforms) || {};
  const ok = (e) => (e && typeof e.url === "string" && (e.url.startsWith("/") || M.href(e.url)) ? e.url : null);
  const url = ok(p["windows-x86_64"]);
  if (!m || typeof m.version !== "string" || !url) return null;
  const appimage = ok(p["linux-x86_64"]);
  const linux = appimage ? { appimage, deb: ok(p["linux-x86_64-deb"]) } : null;
  const arm = ok(p["darwin-aarch64-dmg"]), intel = ok(p["darwin-x86_64-dmg"]);
  const mac = arm || intel ? { arm, intel } : null;
  return { version: m.version, notes: typeof m.notes === "string" ? m.notes : "", date: m.pub_date || null, url, linux, mac };
});
// the Meta Quest app, from /releases/quest.json ({"version","url"}); null until an APK is published. Asked for only
// where it is used (the downloads page, a Quest headset's browser), once.
let questReq = null;
M.quest = () => questReq || (questReq = M.json("/releases/quest.json").then((q) =>
  (q && typeof q.version === "string" && typeof q.url === "string" && (q.url.startsWith("/") || M.href(q.url)) ? { version: q.version, url: q.url } : null)));
// the app for Android phones and tablets, from /releases/android.json ({"version","url"}); null until an APK is published
let androidReq = null;
M.android = () => androidReq || (androidReq = M.json("/releases/android.json").then((a) =>
  (a && typeof a.version === "string" && typeof a.url === "string" && (a.url.startsWith("/") || M.href(a.url)) ? { version: a.version, url: a.url } : null)));
// which build the Download buttons offer: a Quest headset's browser (its user agent says Linux, not Android) gets the
// Quest app once published, a Linux visitor (not Android) the AppImage, everyone else the Windows installer
const UA = navigator.userAgent;
M.onQuest = /OculusBrowser|Quest/.test(UA);
M.onLinux = /Linux/.test(UA) && !/Android/.test(UA) && !M.onQuest;
// phones and tablets first: an iPhone's browser also says "Mac OS X", and an iPad's says "Macintosh"
M.onPhone = /Android|iPhone|iPad|iPod/.test(UA) || (/Macintosh/.test(UA) && "ontouchend" in document);
M.onMac = /Macintosh|Mac OS X/.test(UA) && !M.onPhone && !M.onQuest;
M.onAndroid = /Android/.test(UA) && !M.onQuest;
// installer downloads from the site (self-updates not included), counted by metallic-live
M.downloads = M.json("/live/downloads.json").then((d) => (d && typeof d.downloads === "number" ? d.downloads : null));
M.release.then(async (r) => {
  if (!r) return;
  // "for Windows" in the copy names every system the release has a build for
  const oses = ["Windows", r.linux && "Linux", r.mac && "Mac"].filter(Boolean);
  if (oses.length > 1) document.querySelectorAll("[data-os]").forEach((e) => { e.textContent = oses.slice(0, -1).join(", ") + " and " + oses[oses.length - 1]; });
  const quest = M.onQuest ? await M.quest() : null;
  const android = M.onAndroid ? await M.android() : null; // an APK and its steps, so the downloads page shows them
  const linux = !quest && M.onLinux && r.linux;
  const mac = M.onMac && r.mac; // two .dmg files, so the downloads page lets the visitor choose
  const os = quest ? "Quest" : android ? "Android" : linux ? "Linux" : mac ? "Mac" : "Windows";
  document.querySelectorAll("[data-dl]").forEach((a) => {
    if (!a.classList.contains("small")) a.href = quest ? quest.url : android ? "/downloads/#android" : linux ? r.linux.appimage : mac ? "/downloads/#mac" : r.url;
    if (os !== "Windows" && /Windows/.test(a.textContent)) a.textContent = a.textContent.replace("Windows", os);
  });
  const n = await M.downloads;
  const count = quest || android || n == null ? "" : " · " + M.num(n) + (n === 1 ? " download" : " downloads");
  const what = quest ? " · Meta Quest app (APK), sideloaded" : android ? " · Android 10 or newer, 64-bit phones and tablets" : linux ? " · Linux AppImage, 64-bit" : mac ? " · macOS 13 or newer, not signed by Apple" : " · Windows 10 and 11, 64-bit";
  document.querySelectorAll("[data-dl-note]").forEach((e) => { e.textContent = "Early Access " + (quest ? quest.version : android ? android.version : r.version) + what + count; });
});

// people in Metallic now (launchers that sent their anonymous beat in the last 5 minutes) and the Metallic Discord's
// online count, both written by metallic-live every 2 minutes. A file older than STALE seconds (metallic-live stopped) is
// not shown as "right now"; 0 stays hidden (before launchers send the beat).
const STALE = 600;
M.live = () => M.json("/live/metallic.json").then((d) => (d && typeof d.at === "number" && Date.now() / 1000 - d.at < STALE ? d : null));
const showLive = async () => {
  const d = await M.live();
  const online = d && typeof d.online === "number" ? d.online : 0;
  document.querySelectorAll("[data-presence]").forEach((box) => {
    box.hidden = !(online > 0);
    if (box.hidden) return;
    box.querySelector("[data-presence-n]").textContent = M.num(online);
    box.querySelector("[data-presence-label]").textContent = (online === 1 ? "person" : "people") + " in Metallic right now";
    const peak = typeof d.peak_24h === "number" && d.peak_24h > online ? d.peak_24h : null;
    box.querySelector("[data-presence-peak]").textContent = peak ? "24-hour peak " + M.num(peak) : "";
  });
  const dc = d && d.discord;
  document.querySelectorAll("[data-discord-online]").forEach((box) => {
    box.hidden = !(dc && typeof dc.online === "number" && dc.online > 0);
    if (box.hidden) return;
    const members = typeof dc.members === "number" ? " · " + M.num(dc.members) + " members" : "";
    box.querySelector("[data-discord-text]").textContent = M.num(dc.online) + " online in the Metallic Discord" + members;
  });
};
if (document.querySelector("[data-presence], [data-discord-online]")) {
  showLive();
  setInterval(() => { if (!document.hidden) showLive(); }, 120000);
}

// entrances: parts of each section rise in, staggered, once. Only for what starts below the fold, so nothing flashes.
M.reveal = (root) => {
  if (M.reduced || !("IntersectionObserver" in window)) return;
  const parts = (root || document).querySelectorAll(".sec-head, .card, .empty, .fine, .steps li, .news-card, .project, .cta-band, " +
    ".notes-body > *, .np-row, .np-month, .np-lead, .np-filter, .discord-band");
  const io = new IntersectionObserver((entries) => {
    entries.forEach((en) => {
      if (!en.isIntersecting) return;
      en.target.classList.add("in");
      io.unobserve(en.target);
    });
  }, { rootMargin: "0px 0px -8% 0px" });
  const groups = new Map();
  parts.forEach((p) => {
    if (p.classList.contains("pre") || p.classList.contains("in")) return;
    if (p.getBoundingClientRect().top < window.innerHeight) return;
    const sec = p.closest("section") || document.body;
    const i = groups.get(sec) || 0;
    groups.set(sec, i + 1);
    p.style.setProperty("--d", Math.min(i, 8) * 70 + "ms");
    p.classList.add("pre");
    io.observe(p);
  });
};
document.addEventListener("DOMContentLoaded", () => M.reveal());
