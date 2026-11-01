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

// newest build, from the Tauri updater manifest
M.release = M.json("/releases/latest.json").then((m) => {
  const win = m && m.platforms && m.platforms["windows-x86_64"];
  if (!m || typeof m.version !== "string" || !win) return null;
  const url = typeof win.url === "string" && (win.url.startsWith("/") || M.href(win.url)) ? win.url : null;
  return url ? { version: m.version, notes: typeof m.notes === "string" ? m.notes : "", date: m.pub_date || null, url } : null;
});
M.release.then((r) => {
  if (!r) return;
  document.querySelectorAll("[data-dl]").forEach((a) => {
    if (!a.classList.contains("small")) a.href = r.url;
  });
  document.querySelectorAll("[data-dl-note]").forEach((n) => { n.textContent = "Early Access " + r.version + " · Windows 10 and 11, 64-bit"; });
});

// entrances: parts of each section rise in, staggered, once. Only for what starts below the fold, so nothing flashes.
M.reveal = (root) => {
  if (M.reduced || !("IntersectionObserver" in window)) return;
  const parts = (root || document).querySelectorAll("main h2, main .lede, .board-meta, .two-tone, .tabs, .band, .board-empty, .fine, .lcard, .how-steps p, .mode-text, " +
    ".switch-big, .ledger-lede, .rows li, .hl, .facts > div, .notes-body > *, .req-item, .scene, .scenes-head p, .dl-main > *, .facts, .auto p, .np-row, .np-month, .np-lead img, .np-lead-text, .np-filter, .more-link");
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
