/* Shared by every page: safe JSON loading, number and date formats, the download button, and entrances. Text goes in with textContent only. */
"use strict";
document.documentElement.classList.add("js");

const M = (window.Metallic = {});
const CDN = "https://cdn.discordapp.com/";
M.reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

M.json = async (url) => {
  try {
    const r = await fetch(url, { cache: "no-store", headers: { Accept: "application/json" } });
    if (!r.ok) return null;
    return await r.json();
  } catch (e) {
    return null;
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

// newest build, from the Tauri updater manifest (Linux: "linux-x86_64" is the AppImage, "linux-x86_64-deb" the .deb)
M.release = M.json("/releases/latest.json").then((m) => {
  const p = (m && m.platforms) || {};
  const ok = (e) => (e && typeof e.url === "string" && (e.url.startsWith("/") || M.href(e.url)) ? e.url : null);
  const url = ok(p["windows-x86_64"]);
  if (!m || typeof m.version !== "string" || !url) return null;
  const appimage = ok(p["linux-x86_64"]);
  const linux = appimage ? { appimage, deb: ok(p["linux-x86_64-deb"]) } : null;
  return { version: m.version, notes: typeof m.notes === "string" ? m.notes : "", date: m.pub_date || null, url, linux };
});
// a Linux visitor (not Android) gets the Linux build on the Download buttons, when there is one
M.onLinux = /Linux/.test(navigator.userAgent) && !/Android/.test(navigator.userAgent);
// installer downloads from the site (self-updates not included), counted by metallic-live
M.downloads = M.json("/live/downloads.json").then((d) => (d && typeof d.downloads === "number" ? d.downloads : null));
M.release.then(async (r) => {
  if (!r) return;
  const linux = M.onLinux && r.linux;
  document.querySelectorAll("[data-dl]").forEach((a) => {
    if (!a.classList.contains("small")) a.href = linux ? r.linux.appimage : r.url;
    if (linux && /Windows/.test(a.textContent)) a.textContent = a.textContent.replace("Windows", "Linux");
  });
  const n = await M.downloads;
  const count = n == null ? "" : " · " + M.num(n) + (n === 1 ? " download" : " downloads");
  const what = linux ? " · Linux AppImage, 64-bit" : " · Windows 10 and 11, 64-bit";
  document.querySelectorAll("[data-dl-note]").forEach((e) => { e.textContent = "Early Access " + r.version + what + count; });
});

// entrances: parts of each section rise in, staggered, once. Only for what starts below the fold, so nothing flashes.
M.reveal = (root) => {
  if (M.reduced || !("IntersectionObserver" in window)) return;
  const parts = (root || document).querySelectorAll(".sec-head, .card, .empty, .fine, .steps li, .news-card, .project, .cta-band, " +
    ".facts > div, .notes-body > *, .req-item, .scene, .np-row, .np-month, .np-lead, .np-filter");
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
