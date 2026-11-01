/* Home: the hero reel, the live revivals board, the launcher card, the PC/VR switch, projects and the news strip.
   Truthfulness: "in game" only from a revival's own `players` field; Discord `online` is always "online in Discord". */
"use strict";
(() => {
  const M = window.Metallic;
  const $ = (s) => document.querySelector(s);
  const SHOWN = 10;
  let revivals = [], byId = {}, year = "all", expanded = false, firstRender = true;

  const name = (r) => r.catalogName || r.name || r.id;
  const online = (r) => (r.discord && typeof r.discord.online === "number" ? r.discord.online : null);
  const players = (r) => (typeof r.players === "number" ? r.players : null);
  const art = (r) => r.discord && (M.cdn(r.discord.banner) || M.cdn(r.discord.splash));
  const icon = (r) => r.discord && M.cdn(r.discord.icon);
  const link = (r) => M.href(r.website) || M.href(r.invite);

  // "2016-2020", "2018 · 2023 · 2025", "Early 2021" -> the years of Rec Room a revival brings back
  const years = (r) => {
    const out = new Set(), era = String(r.era || "");
    era.replace(/(\d{4})\s*[-–]\s*(\d{4})/g, (_, a, b) => {
      for (let y = +a; y <= +b && y - a < 15; y++) out.add(y);
      return "";
    }).replace(/\d{4}/g, (y) => { out.add(+y); return ""; });
    return [...out].filter((y) => y >= 2015 && y <= 2030);
  };

  const sortRevivals = (list) => list.slice().sort((a, b) =>
    (players(b) ?? -1) - (players(a) ?? -1) || (online(b) ?? -1) - (online(a) ?? -1) || name(a).localeCompare(name(b)));

  // ---- hero reel ----
  const reel = $("[data-reel-track]");
  let reelAt = 1, reelTimer = null;
  const placeReel = () => {
    const frames = reel.children;
    if (!frames.length) return;
    reelAt %= frames.length;
    [...frames].forEach((f, i) => { f.classList.toggle("on", i === reelAt); f.classList.toggle("far", Math.abs(i - reelAt) > 1); });
    const f = frames[reelAt], box = reel.parentElement;
    reel.style.transform = "translateY(" + Math.round(box.clientHeight / 2 - (f.offsetTop + f.offsetHeight / 2)) + "px)";
  };
  const startReel = () => {
    placeReel();
    clearInterval(reelTimer);
    if (!M.reduced && reel.children.length > 1) reelTimer = setInterval(() => { if (!document.hidden) { reelAt++; placeReel(); } }, 4200);
  };
  const buildReel = (list) => {
    const withArt = list.filter(art).slice(0, 7);
    if (withArt.length < 3) return;
    withArt.unshift(withArt.pop());  // the busiest revival sits in the middle, the last one above it
    const frames = withArt.map((r) => {
      const fig = M.el("figure", "frame");
      const im = M.img(art(r), "Discord banner of " + name(r), 640);
      im.height = 360; im.loading = "eager";
      im.addEventListener("load", placeReel, { once: true });
      fig.append(im);
      const cap = M.el("figcaption");
      if (icon(r)) cap.append(M.img(icon(r), "", 28));
      cap.append(M.el("span", "cap-name", name(r)));
      const num = M.el("span", "cap-num");
      const p = players(r), o = online(r);
      if (p !== null) { num.append(M.el("b", null, M.num(p))); num.append(" in game"); }
      else if (o !== null) { num.append(M.el("b", null, M.num(o))); num.append(" online in Discord"); }
      cap.append(num);
      fig.append(cap);
      return fig;
    });
    reel.replaceChildren(...frames);
    reelAt = 1;
    startReel();
  };
  window.addEventListener("resize", placeReel);
  reel.querySelectorAll("img").forEach((i) => i.addEventListener("load", placeReel, { once: true }));

  // ---- pulse (totals) ----
  const pulse = (data, list) => {
    const t = data.totals || {};
    const inGame = typeof t.inGame === "number" ? t.inGame : null;
    const on = typeof t.online === "number" ? t.online : null;
    if (inGame === null && on === null) return;
    const box = $("[data-pulse]");
    const withP = list.filter((r) => players(r) !== null).length;
    const withO = list.filter((r) => online(r) !== null).length;
    const rows = box.querySelectorAll("p");
    if (inGame !== null && withP) {
      rows[0].querySelector("strong").textContent = M.num(inGame);
      rows[0].querySelector("span").textContent = "in game right now, in the " + withP + (withP === 1 ? " revival that publishes it" : " revivals that publish it");
    } else rows[0].hidden = true;
    if (on !== null) {
      rows[1].querySelector("strong").textContent = M.num(on);
      rows[1].querySelector("span").textContent = "online in Discord across " + withO + " revival servers";
    } else rows[1].hidden = true;
    box.hidden = false;
  };

  // ---- board ----
  const tabsBox = $("[data-tabs]"), bands = $("[data-bands]"), more = $("[data-more]");
  const tab = (key, label, count) => {
    const b = M.el("button", "tab");
    b.type = "button"; b.setAttribute("role", "tab"); b.dataset.year = key;
    b.setAttribute("aria-selected", String(key === year));
    b.tabIndex = key === year ? 0 : -1;
    b.append(M.el("b", null, label), M.el("span", null, count + (count === 1 ? " revival" : " revivals")));
    b.addEventListener("click", () => { year = key; expanded = false; renderBoard(); });
    return b;
  };
  tabsBox.addEventListener("keydown", (e) => {
    if (!["ArrowDown", "ArrowUp", "ArrowLeft", "ArrowRight"].includes(e.key)) return;
    const all = [...tabsBox.children], i = all.indexOf(document.activeElement);
    if (i < 0) return;
    e.preventDefault();
    const next = all[(i + (e.key === "ArrowDown" || e.key === "ArrowRight" ? 1 : all.length - 1)) % all.length];
    next.click(); next.focus();
  });
  const renderTabs = () => {
    const count = new Map();
    revivals.forEach((r) => years(r).forEach((y) => count.set(y, (count.get(y) || 0) + 1)));
    const ys = [...count.keys()].sort((a, b) => a - b);
    if (ys.length < 2) { tabsBox.hidden = true; return; }
    if (year !== "all" && !count.has(+year)) year = "all";
    tabsBox.replaceChildren(tab("all", "Any year", revivals.length), ...ys.map((y) => tab(String(y), String(y), count.get(y))));
    tabsBox.hidden = false;
  };
  const num = (cls, n, label) => {
    const d = M.el("div", "b-num " + cls);
    if (n === null) { d.classList.add("empty"); return d; }
    d.append(M.el("b", null, M.num(n)), M.el("span", null, label));
    return d;
  };
  const band = (r) => {
    const li = M.el("li", "band");
    const ic = icon(r);
    if (ic) li.append(M.img(ic, "", 48, "b-icon"));
    else li.append(M.el("i", "b-icon", name(r).replace(/[^A-Za-z0-9]/g, "").charAt(0).toUpperCase() || "?"));
    const main = M.el("div", "b-main");
    const href = link(r);
    const nm = M.el(href ? "a" : "span", "b-name", name(r));
    if (href) { nm.href = href; nm.rel = "noopener"; }
    main.append(nm);
    const note = [];
    if (r.era) note.push(String(r.era));
    if (r.blurb) note.push(String(r.blurb));
    main.append(M.el("span", "b-note", note.join(" · ") || "Rec Room revival"));
    li.append(main, M.el("span", "b-plat", r.platforms || ""));
    li.append(num("game", players(r), "in game"));
    li.append(num("dc", online(r), "online in Discord"));
    return li;
  };
  const renderBoard = () => {
    renderTabs();
    const list = year === "all" ? revivals : revivals.filter((r) => years(r).includes(+year));
    const shown = year === "all" && !expanded ? list.slice(0, SHOWN) : list;
    bands.replaceChildren(...shown.map(band));
    more.hidden = shown.length >= list.length;
    more.textContent = "Show all " + list.length + " revivals";
    $("[data-board-empty]").hidden = list.length > 0;
  };
  more.addEventListener("click", () => { expanded = true; renderBoard(); });

  // ---- launcher card (how it works) ----
  const fillCard = (r) => {
    if (!r) return;
    $("[data-lc-name]").textContent = name(r);
    if (r.blurb) $("[data-lc-blurb]").textContent = String(r.blurb);
    $("[data-lc-plat]").textContent = r.platforms || "PC";
    const a = art(r), ic = icon(r), img = $("[data-lc-img]"), ico = $("[data-lc-icon]");
    if (a) { img.src = a; img.width = 640; img.height = 360; }
    ico.textContent = name(r).charAt(0).toUpperCase();
    if (ic) { ico.textContent = ""; ico.classList.add("has-img"); ico.append(M.img(ic, "", 40)); }
  };
  const steps = document.querySelectorAll(".how-steps li");
  const card = $("[data-lcard]");
  if ("IntersectionObserver" in window) {
    const io = new IntersectionObserver((es) => es.forEach((e) => {
      if (!e.isIntersecting) return;
      steps.forEach((s) => s.classList.toggle("on", s === e.target));
      card.dataset.step = e.target.dataset.step;
    }), { rootMargin: "-45% 0px -45% 0px" });
    steps.forEach((s) => io.observe(s));
    steps[0].classList.add("on");
  }

  // ---- PC or VR ----
  const mode = $(".mode"), word = $("[data-mode-word]"), picks = document.querySelectorAll("[data-pick]");
  const pick = (m) => {
    mode.dataset.mode = m;
    word.textContent = m === "pc" ? "on PC" : "in VR";
    picks.forEach((b) => { const on = b.dataset.pick === m; b.setAttribute("aria-checked", String(on)); b.tabIndex = on ? 0 : -1; });
  };
  picks.forEach((b) => {
    b.addEventListener("click", () => pick(b.dataset.pick));
    b.addEventListener("keydown", (e) => {
      if (!["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(e.key)) return;
      e.preventDefault();
      const next = b.dataset.pick === "pc" ? "vr" : "pc";
      pick(next);
      document.querySelector('[data-pick="' + next + '"]').focus();
    });
  });
  pick("pc");

  // ---- projects ----
  const kind = (u) => {
    if (/^https:\/\/(www\.)?roblox\.com\//.test(u || "")) return "Roblox game";
    if (/minecraft/i.test(u || "")) return "Minecraft server";
    return "Metallic project";
  };
  const renderProjects = (list) => {
    if (!Array.isArray(list)) return;
    const rows = list.filter((p) => p && p.name).map((p) => {
      const li = M.el("li");
      const href = M.href(p.url);
      const a = M.el(href ? "a" : "span", "r-name", p.name);
      if (href) { a.href = href; a.rel = "noopener"; }
      const n = typeof p.playing === "number" ? M.num(p.playing) + " playing now" : "";
      li.append(a, M.el("span", "r-kind", kind(p.url)), M.el("span", "r-num", n));
      return li;
    });
    if (rows.length) $("[data-projects]").replaceChildren(...rows);
  };

  // ---- news strip ----
  const renderNews = (data) => {
    const items = data && Array.isArray(data.items) ? data.items.filter((n) => n && n.title && M.href(n.link)) : [];
    if (!items.length) return;
    items.sort((a, b) => (b.date || 0) - (a.date || 0));
    const tiles = items.slice(0, 6).map((n) => {
      const li = M.el("li", "hl"), a = M.el("a", "hl-title", String(n.title));
      a.href = M.href(n.link); a.rel = "noopener";
      const r = byId[n.revival];
      li.append(M.el("span", "hl-who", r ? name(r) : String(n.revival || "Revival")), a,
        M.el("span", "hl-meta", [n.source, n.date ? M.date(n.date) : ""].filter(Boolean).join(" · ")));
      return li;
    });
    $("[data-news-strip]").replaceChildren(...tiles);
  };

  // ---- load, then refresh every minute ----
  const load = async () => {
    const [data, projects, news] = await Promise.all([M.json("/live/revivals.json"), M.json("/live/projects.json"), M.json("/live/news.json")]);
    if (data && Array.isArray(data.revivals)) {
      revivals = sortRevivals(data.revivals.filter((r) => r && r.id));
      byId = Object.fromEntries(revivals.map((r) => [r.id, r]));
      renderBoard();
      pulse(data, revivals);
      const ago = M.ago(data.checkedAt);
      if (ago) $("[data-checked]").textContent = "Checked " + ago + ". This page refreshes every minute.";
      if (firstRender) { buildReel(revivals); fillCard(revivals.filter(art)[2] || revivals[0]); }
    }
    renderProjects(projects);
    renderNews(news);
    if (firstRender) { firstRender = false; M.reveal(); }
  };
  startReel();
  load();
  setInterval(() => { if (!document.hidden) load(); }, 60000);
})();
