/* News: every item from /live/news.json, newest first, grouped by month, with a filter by revival. */
"use strict";
(async () => {
  const M = window.Metallic;
  const $ = (s) => document.querySelector(s);
  const [news, rv] = await Promise.all([M.json("/live/news.json"), M.json("/live/revivals.json")]);
  const items = news && Array.isArray(news.items) ? news.items.filter((n) => n && n.title && M.href(n.link)) : [];
  if (!items.length) return;
  items.sort((a, b) => (b.date || 0) - (a.date || 0));
  const byId = {};
  (rv && Array.isArray(rv.revivals) ? rv.revivals : []).forEach((r) => { if (r && r.id) byId[r.id] = r; });
  const name = (id) => (byId[id] && (byId[id].catalogName || byId[id].name)) || String(id || "Revival");
  const icon = (id) => byId[id] && byId[id].discord && M.cdn(byId[id].discord.icon);
  const art = (id) => byId[id] && byId[id].discord && (M.cdn(byId[id].discord.banner) || M.cdn(byId[id].discord.splash));
  const list = $("[data-news]"), filter = $("[data-filter]");
  let only = null;

  const render = () => {
    const out = [];
    let month = "";
    const shown = items.filter((n) => !only || n.revival === only);
    const top = shown[0], topArt = top && art(top.revival);
    if (topArt) {  // the newest item leads, with its revival's banner at full size
      const lead = M.el("article", "np-lead");
      const im = M.img(topArt, "Discord banner of " + name(top.revival), 960);
      im.height = 540; im.loading = "eager";
      const a = M.el("a", "np-lead-title", String(top.title));
      a.href = M.href(top.link); a.rel = "noopener";
      const txt = M.el("div", "np-lead-text");
      txt.append(a, M.el("p", "np-lead-meta", [name(top.revival), top.source, top.date ? M.date(top.date, true) : ""].filter(Boolean).join(" · ")));
      lead.append(im, txt);
      out.push(lead);
      shown.shift();
    }
    shown.forEach((n) => {
      const d = n.date ? new Date(n.date * 1000) : null;
      const m = d ? d.toLocaleDateString("en-GB", { month: "long", year: "numeric" }) : "Undated";
      if (m !== month) { month = m; out.push(M.el("h2", "np-month", m)); }
      const row = M.el("article", "np-row");
      const who = M.el("span", "np-who"), ic = icon(n.revival);
      who.append(ic ? M.img(ic, "", 28) : M.el("i"), M.el("span", null, name(n.revival)));
      const a = M.el("a", "np-title", String(n.title));
      a.href = M.href(n.link); a.rel = "noopener";
      const pic = M.el("span", "np-pic"), src = art(n.revival);
      if (src) { const im = M.img(src, "", 192); im.height = 108; pic.append(im); }
      row.append(pic, M.el("span", "np-date", n.date ? M.date(n.date) : ""), who, a, M.el("span", "np-src", n.source || ""));
      out.push(row);
    });
    list.replaceChildren(...out);
  };

  const ids = [...new Set(items.map((n) => n.revival).filter(Boolean))];
  if (ids.length > 1) {
    const chip = (id, label) => {
      const b = M.el("button", "chip");
      b.type = "button";
      b.setAttribute("aria-pressed", String(id === only));
      const ic = id && icon(id);
      if (ic) b.append(M.img(ic, "", 20));
      b.append(label);
      b.addEventListener("click", () => {
        only = id;
        filter.querySelectorAll(".chip").forEach((c) => c.setAttribute("aria-pressed", String(c === b)));
        render();
      });
      return b;
    };
    const count = (id) => items.filter((n) => n.revival === id).length;
    filter.replaceChildren(chip(null, "Every revival"), ...ids.map((id) => chip(id, name(id) + " " + count(id))));
    filter.hidden = false;
  }
  render();
  M.reveal();
})();
