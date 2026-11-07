/* PX progress page. Renders px.json (see launcher/px/build.py) into any element. Text only goes in through
   textContent, so data from the forge cannot inject markup.

   Launcher:   MetallicPX.mount(el, async (refresh) => JSON.parse(await bridge.pxData(refresh)))
   Site/standalone: MetallicPX.mount(el, async () => (await fetch("px.json")).json())                  */
(function () {
  "use strict";
  var STATES = ["planned", "implemented", "tested", "accepted", "released"];
  var DEFS = {
    planned: "Written down. No working code yet, or only a design.",
    implemented: "The code exists. Our own checks have not passed yet, or have not been run.",
    tested: "Our own automated or measured checks passed. Not yet confirmed by a real run.",
    accepted: "The owner or a real player run confirmed it works.",
    released: "A supported download exists."
  };

  function el(tag, attrs, kids) {
    var n = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === "text") n.textContent = attrs[k];
      else if (k === "class") n.className = attrs[k];
      else if (attrs[k] !== false && attrs[k] != null) n.setAttribute(k, attrs[k]);
    });
    (kids || []).forEach(function (c) { if (c) n.appendChild(typeof c === "string" ? document.createTextNode(c) : c); });
    return n;
  }
  function plural(n, one, many) { return n + " " + (n === 1 ? one : many || one + "s"); }
  function when(iso) { return iso ? new Date(iso.length === 10 ? iso + "T12:00:00Z" : iso) : null; }
  function fmtDate(iso) {
    var d = when(iso);
    return d && !isNaN(d) ? d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }) : "no date";
  }
  function ago(iso) {
    var d = when(iso);
    if (!d || isNaN(d)) return "";
    var m = Math.round((Date.now() - d.getTime()) / 60000);
    if (m < 1) return "just now";
    if (m < 60) return m + " min ago";
    if (m < 2880) return Math.round(m / 60) + " h ago";
    return Math.round(m / 1440) + " days ago";
  }
  function stateWord(s) { return s.charAt(0).toUpperCase() + s.slice(1); }

  function mount(root, loader, opts) {
    opts = opts || {};
    root.classList.add("px");
    var tip = el("div", { class: "px-tip", role: "tooltip", hidden: "" });
    var focusProject = "all";
    var data = null;

    function showTip(target, text) {
      tip.textContent = text;
      tip.hidden = false;
      var r = target.getBoundingClientRect();
      tip.style.left = Math.max(8, Math.min(window.innerWidth - 296, r.left + r.width / 2 - 140)) + "px";
      tip.style.top = Math.max(8, r.top - tip.offsetHeight - 8) + "px";
    }
    function tipOn(node, text) {
      node.setAttribute("tabindex", "0");
      node.setAttribute("aria-label", text);
      node.addEventListener("mouseenter", function () { showTip(node, text); });
      node.addEventListener("focus", function () { showTip(node, text); });
      node.addEventListener("mouseleave", function () { tip.hidden = true; });
      node.addEventListener("blur", function () { tip.hidden = true; });
    }

    function stateBar(p) {
      var bar = el("div", { class: "px-bar", role: "img",
        "aria-label": p.name + ": " + STATES.map(function (s) { return p.states[s] + " " + s; }).join(", ") });
      STATES.forEach(function (s) {
        if (!p.states[s]) return;
        var seg = el("div", { class: "px-seg", "data-s": s });
        seg.style.flex = p.states[s] + " 1 0";
        var titles = p.items.filter(function (i) { return i.state === s; }).map(function (i) { return i.title; });
        tipOn(seg, stateWord(s) + ": " + plural(p.states[s], "item") + (titles.length <= 3 ? ". " + titles.join("; ") : ""));
        bar.appendChild(seg);
      });
      return bar;
    }
    function counts(p) {
      var wrap = el("div", { class: "px-counts" });
      STATES.forEach(function (s) {
        wrap.appendChild(el("span", { class: p.states[s] ? "" : "zero" }, [el("i", { "data-s": s }), p.states[s] + " " + s]));
      });
      return wrap;
    }

    function overview() {
      var rows = el("div", { class: "px-rows" });
      data.projects.forEach(function (p) {
        var left = el("div", { class: "px-name" }, [el("b", { text: p.name }), el("span", { class: "m3", text: p.role + " · " + plural(p.total, "item") })]);
        var right = el("div", {}, [stateBar(p), counts(p)]);
        rows.appendChild(el("div", { class: "px-row" }, [left, right]));
      });
      return rows;
    }

    function itemRow(i) {
      var li = el("li", { class: "px-item" }, [
        el("span", { class: "px-state", "data-s": i.state }, [el("i"), stateWord(i.state)]),
        el("span", { text: i.title }),
        el("span", { class: "m3 num", text: "confirmed " + fmtDate(i.evidence) })
      ]);
      var extra = [];
      if (i.note) extra.push(el("p", { text: i.note }));
      (i.blockers || []).forEach(function (b) { extra.push(el("p", { class: "px-block", text: "Blocked: " + b })); });
      if (i.waiting_on && i.waiting_on.length) {
        var names = i.waiting_on.map(function (id) {
          var found = null;
          data.projects.forEach(function (p) { p.items.forEach(function (x) { if (x.id === id) found = x.title; }); });
          return found || id;
        });
        extra.push(el("p", { class: "m3", text: "Waiting on: " + names.join("; ") }));
      }
      if (extra.length) li.appendChild(el("div", { class: "px-extra" }, extra));
      return li;
    }

    function roadmap() {
      var wrap = el("div");
      var filter = el("div", { class: "px-filter", role: "group", "aria-label": "Show project" });
      [{ id: "all", name: "All" }].concat(data.projects).forEach(function (p) {
        var b = el("button", { type: "button", "aria-pressed": String(focusProject === p.id), text: p.name });
        b.addEventListener("click", function () { focusProject = p.id; render(); });
        filter.appendChild(b);
      });
      wrap.appendChild(filter);
      data.projects.forEach(function (p) {
        if (focusProject !== "all" && focusProject !== p.id) return;
        var d = el("details", focusProject === "all" ? {} : { open: "" });
        d.appendChild(el("summary", {}, [el("h3", { class: "grow", text: p.name }),
          el("span", { class: "m3 num", text: "updated " + fmtDate(p.updated) })]));
        var ul = el("ul", { class: "px-items" });
        var order = STATES.slice().reverse();
        p.items.slice().sort(function (a, b) { return order.indexOf(a.state) - order.indexOf(b.state); })
          .forEach(function (i) { ul.appendChild(itemRow(i)); });
        d.appendChild(ul);
        wrap.appendChild(d);
      });
      return wrap;
    }

    function spark(weeks) {
      var max = Math.max.apply(null, weeks.map(function (w) { return w.closed; }).concat([1]));
      var box = el("div", { class: "px-spark" });
      weeks.forEach(function (w) {
        var b = el("b", { "data-z": w.closed ? "0" : "1" });
        b.style.height = Math.max(4, Math.round((w.closed / max) * 100)) + "%";
        tipOn(b, "Week of " + fmtDate(w.start) + ": " + plural(w.closed, "issue") + " closed, " + w.opened + " opened");
        box.appendChild(b);
      });
      var total = weeks.reduce(function (a, w) { return a + w.closed; }, 0);
      return el("div", {}, [
        el("p", { class: "m2 num", text: total ? plural(total, "issue") + " closed in the last " + weeks.length + " weeks (busiest week: " + max + ")" : "No issues closed in the last " + weeks.length + " weeks." }),
        box,
        el("div", { class: "px-axis" }, [el("span", { text: fmtDate(weeks[0].start) }), el("span", { text: "this week" })])
      ]);
    }
    function tracker() {
      var wrap = el("div", { class: "px-trk" });
      var shown = 0;
      data.projects.forEach(function (p) {
        var t = p.tracker;
        if (!t) return;
        shown++;
        var right = el("div");
        var all = t.open + t.closed;
        right.appendChild(el("p", { class: "m2 num", text: t.closed + " of " + plural(all, "tracker issue") + " closed. This counts tickets, not how finished the product is." }));
        t.milestones.forEach(function (m) {
          var tot = m.open + m.closed;
          var track = el("div", { class: "track", role: "img", "aria-label": m.closed + " of " + tot + " closed" });
          if (m.closed) { var dn = el("div", { class: "done" }); dn.style.flex = m.closed + " 1 0"; track.appendChild(dn); }
          right.appendChild(el("div", { class: "px-ms" }, [
            el("span", { text: m.title }), track,
            el("span", { class: "m3 num", text: m.closed + "/" + tot + " · " + (m.due ? "due " + fmtDate(m.due) : "no date") })
          ]));
        });
        if (!t.milestones.length) right.appendChild(el("p", { class: "m3", text: "No milestones set in the forge yet." }));
        right.appendChild(spark(t.weeks));
        wrap.appendChild(el("div", { class: "px-trk-card" }, [
          el("div", { class: "px-name" }, [el("b", { text: p.name }), el("span", { class: "m3", text: "from the forge" })]), right]));
      });
      if (!shown) wrap.appendChild(el("p", { class: "px-empty", text: data.mode === "public" ? "Tracker numbers are not published." : "The tracker is not connected. Add the forge address in settings to see milestones and weekly activity." }));
      return wrap;
    }

    function releases() {
      var wrap = el("div");
      var any = false;
      data.projects.forEach(function (p) {
        p.releases.slice(0, 6).forEach(function (r) {
          any = true;
          var row = el("div", { class: "px-rel" }, [el("span", { class: "m3 num", text: fmtDate(r.date) }),
            el("span", { class: "m2", text: p.name }), el("b", { text: r.name + (r.prerelease ? " (pre-release)" : "") })]);
          if (r.notes) row.appendChild(el("p", { class: "px-note", text: r.notes }));
          wrap.appendChild(row);
        });
      });
      if (!any) wrap.appendChild(el("p", { class: "px-empty", text: "No supported downloads have been released yet." }));
      return wrap;
    }

    function changelog() {
      var wrap = el("div"), month = "";
      var names = {};
      data.projects.forEach(function (p) { names[p.id] = p.name; });
      data.changelog.forEach(function (c) {
        var d = when(c.date), key = d && !isNaN(d) ? d.toLocaleDateString(undefined, { month: "long", year: "numeric" }) : "Undated";
        if (key !== month) { month = key; wrap.appendChild(el("p", { class: "px-month", text: key })); }
        var line = el("div", { class: "px-rel" }, [el("span", { class: "m3 num", text: fmtDate(c.date) }),
          el("span", { class: "px-state", "data-s": c.kind === "release" ? "released" : c.kind }, [el("i"), (names[c.project] || c.project)]),
          el("span", { text: (c.kind === "release" ? "Released " : stateWord(c.kind) + ": ") + c.title })]);
        if (c.text) line.appendChild(el("p", { class: "px-note", text: c.text }));
        wrap.appendChild(line);
      });
      if (!data.changelog.length) wrap.appendChild(el("p", { class: "px-empty", text: "Nothing to list yet." }));
      return wrap;
    }

    function definitions() {
      var dl = el("dl", { class: "px-defs" });
      STATES.forEach(function (s) {
        dl.appendChild(el("dt", {}, [el("span", { class: "px-state", "data-s": s }, [el("i"), stateWord(s)])]));
        dl.appendChild(el("dd", { text: DEFS[s] }));
      });
      return dl;
    }

    function render() {
      root.textContent = "";
      if (!data || data.error) {
        root.appendChild(el("p", { class: "px-empty", text: data && data.error ? "Progress could not be loaded: " + data.error : "Loading progress..." }));
        return;
      }
      var f = data.forge || { state: "off" };
      var fl = { online: "Forge connected", partial: "Forge partly reachable", stale: "Forge offline, showing saved data", offline: "Forge offline", off: data.mode === "public" ? "Roadmap only" : "Tracker not connected" }[f.state] || f.state;
      var refresh = el("button", { class: "px-btn", type: "button", text: "Refresh" });
      refresh.addEventListener("click", function () { load(true); });
      root.appendChild(el("header", { class: "px-head" }, [
        opts.title === false ? el("div") : el("div", {}, [el("h1", { text: "Progress" }),
          el("p", { class: "m2", text: "What exists, what is tested, what a player can actually download." })]),
        el("div", { class: "px-meta" }, [
          el("span", { class: "px-chip", "data-k": f.state, title: f.detail || "" }, [el("i"), fl]),
          el("span", { class: "px-chip", text: "Updated " + ago(data.generated) }),
          data.mode === "internal" ? refresh : null])
      ]));
      root.appendChild(el("h2", { text: "Where each project stands" }));
      root.appendChild(el("div", { class: "px-legend m2", text: "Each bar is one project's roadmap items, split by state. Hollow means planned. Darker to lighter means further along." }));
      root.appendChild(overview());
      root.appendChild(el("h2", { text: "Roadmap" }));
      root.appendChild(roadmap());
      root.appendChild(el("h2", { text: "Milestones and activity" }));
      root.appendChild(tracker());
      root.appendChild(el("h2", { text: "Releases" }));
      root.appendChild(releases());
      root.appendChild(el("h2", { text: "Changelog" }));
      root.appendChild(changelog());
      root.appendChild(el("h2", { text: "How to read this" }));
      root.appendChild(definitions());
      root.appendChild(el("p", { class: "m3 px-foot", text: "A merged pull request is not a finished feature, and an issue count is not a completion percentage. Dates show when a state was last confirmed." }));
      root.appendChild(tip);
    }

    function load(refresh) {
      loader(!!refresh).then(function (d) { data = d; render(); })
        .catch(function (e) { data = { error: String(e && e.message || e) }; render(); });
    }
    render();
    load(false);
    return { reload: load };
  }

  window.MetallicPX = { mount: mount };
})();
