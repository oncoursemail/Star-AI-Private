/* Home: the launcher window in the hero, live totals, the revival cards (most online first), news and projects.
   Truthfulness: "in game" only from a revival's own `players` field; Discord `online` is always "online in Discord". */
"use strict";
(() => {
  const M = window.Metallic;
  const $ = (s) => document.querySelector(s);
  let revivals = [], byId = {}, firstRender = true;

  const name = (r) => r.catalogName || r.name || r.id;
  const online = (r) => (r.discord && typeof r.discord.online === "number" ? r.discord.online : null);
  const players = (r) => (typeof r.players === "number" ? r.players : null);
  const art = (r) => r.discord && (M.cdn(r.discord.banner) || M.cdn(r.discord.splash));
  const link = (r) => M.href(r.website) || M.href(r.invite);

  // most online first, as in the launcher: people in game (only revivals that publish it), then members online in the
  // revival's Discord; a revival without either number goes last. Ties by name.
  const sortRevivals = (list) => list.slice().sort((a, b) =>
    (players(b) ?? -1) - (players(a) ?? -1) || (online(b) ?? -1) - (online(a) ?? -1) || name(a).localeCompare(name(b)));

  // ---- icons: the Discord server icon, else a logo kept on this site, else a monogram ----
  const LOCAL_ICONS = { uranium: "/assets/icons/uranium.png" };
  const iconSrc = (r) => (r.discord && M.cdn(r.discord.icon)) || LOCAL_ICONS[r.id] || null;
  const monogram = (r) => {
    const words = name(r).replace(/[^A-Za-z0-9 ]/g, " ").trim().split(/\s+/);
    return ((words.length > 1 ? words[0][0] + words[1][0] : (words[0] || "?").slice(0, 2))).toUpperCase();
  };
  const iconEl = (r, size) => {
    const box = M.el("span", "ic", monogram(r));
    const src = iconSrc(r);
    if (src) { box.classList.add("has-img"); box.append(M.img(src, "", size)); }
    return box;
  };

  // ---- hero: totals and the launcher window ----
  const stats = (data, list) => {
    const t = data.totals || {}, box = $("[data-stats]");
    const set = (key, n) => {
      const row = box.querySelector('[data-stat="' + key + '"]');
      if (typeof n === "number") row.querySelector("dd").textContent = M.num(n);
      else row.hidden = true;
    };
    set("revivals", list.length);
    set("online", t.online);
    set("inGame", list.some((r) => players(r) !== null) ? t.inGame : null);
    box.hidden = false;
  };
  const fillWindow = (busy) => {  // already most online first, like the board
    const lead = busy.find(art);
    if (lead) {
      const img = $("[data-win-art]");
      img.src = art(lead); img.width = 640; img.height = 360;
      $("[data-win-name]").textContent = name(lead);
      $("[data-win-note]").textContent = lead.blurb ? String(lead.blurb) : "Rec Room revival";
    }
    const rows = busy.filter((r) => r !== lead).slice(0, 4).map((r) => {
      const li = M.el("li");
      let n = r.platforms || "";
      if (players(r) !== null) n = M.num(players(r)) + " in game";
      else if (online(r) !== null) n = M.num(online(r)) + " online in Discord";
      li.append(iconEl(r, 32), M.el("b", null, name(r)), M.el("em", null, n));
      return li;
    });
    if (rows.length) $("[data-win-list]").replaceChildren(...rows);
  };

  // ---- revival cards ----
  const count = (n, label, cls) => {
    const d = M.el("p", "c-num " + cls);
    d.append(M.el("b", null, M.num(n)), M.el("span", null, label));
    return d;
  };
  const card = (r) => {
    const li = M.el("li", "card");
    const head = M.el("div", "c-head");
    const title = M.el("div", "c-title");
    const href = link(r);
    const nm = M.el(href ? "a" : "span", "c-name", name(r));
    if (href) { nm.href = href; nm.rel = "noopener"; }
    title.append(nm);
    const tags = M.el("p", "c-tags");
    if (r.era) tags.append(M.el("span", "tag era", String(r.era)));
    if (r.platforms) tags.append(M.el("span", "tag", String(r.platforms)));
    if (tags.childNodes.length) title.append(tags);
    head.append(iconEl(r, 48), title);
    li.append(head, M.el("p", "c-blurb", r.blurb ? String(r.blurb) : "Rec Room revival"));
    const foot = M.el("div", "c-foot");
    if (players(r) !== null) foot.append(count(players(r), "in game", "game"));
    if (online(r) !== null) foot.append(count(online(r), "online in Discord", "dc"));
    if (!foot.childNodes.length) foot.append(M.el("p", "c-none", r.invite ? "Discord count not available" : "No public Discord yet"));
    li.append(foot);
    return li;
  };
  const renderBoard = () => {
    $("[data-cards]").replaceChildren(...revivals.map(card));
    $("[data-board-empty]").hidden = revivals.length > 0;
  };

  // ---- projects ----
  const kind = (u) => {
    if (/^https:\/\/(www\.)?roblox\.com\//.test(u || "")) return "Roblox game";
    if (/minecraft/i.test(u || "")) return "Minecraft server";
    return "Metallic project";
  };
  const renderProjects = (list) => {
    if (!Array.isArray(list)) return;  // file missing: the section keeps its empty state
    $("[data-projects]").closest("section").hidden = !list.some((p) => p && p.name);  // none listed: no empty section
    const rows = list.filter((p) => p && p.name).map((p) => {
      const li = M.el("li", "project");
      const href = M.href(p.url);
      const a = M.el(href ? "a" : "span", "p-name", p.name);
      if (href) { a.href = href; a.rel = "noopener"; }
      const txt = M.el("div");
      txt.append(a, M.el("span", "p-kind", kind(p.url)));
      li.append(txt);
      if (typeof p.playing === "number") li.append(count(p.playing, "playing now", "game"));
      return li;
    });
    if (rows.length) $("[data-projects]").replaceChildren(...rows);
  };

  // ---- news ----
  const renderNews = (data) => {
    const items = data && Array.isArray(data.items) ? data.items.filter((n) => n && n.title && M.href(n.link)) : [];
    if (!items.length) return;
    items.sort((a, b) => (b.date || 0) - (a.date || 0));
    const tiles = items.slice(0, 6).map((n) => {
      const li = M.el("li", "news-card"), r = byId[n.revival];
      const who = M.el("p", "n-who");
      who.append(r ? iconEl(r, 24) : M.el("span", "ic", "?"), M.el("span", null, r ? name(r) : String(n.revival || "Revival")));
      const a = M.el("a", "n-title", String(n.title));
      a.href = M.href(n.link); a.rel = "noopener";
      li.append(who, a, M.el("p", "n-meta", [n.source, n.date ? M.date(n.date) : ""].filter(Boolean).join(" · ")));
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
      stats(data, revivals);
      if (firstRender) fillWindow(revivals);
      const ago = M.ago(data.checkedAt);
      if (ago) $("[data-checked]").textContent = "Checked " + ago + ". Refreshes every minute.";
    }
    renderProjects(projects);
    renderNews(news);
    if (firstRender) { firstRender = false; M.reveal(); }
  };
  load();
  setInterval(() => { if (!document.hidden) load(); }, 60000);
})();
