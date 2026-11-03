"use strict";
// Litha's face: reads /api/state every 20 s (not while the tab is hidden) and renders it with textContent only.
const $ = (id) => document.getElementById(id);
const SVG = "http://www.w3.org/2000/svg";
let S = null;
let repoPick = null;
const openPrs = new Set();

function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of kids.flat(Infinity)) if (c !== null && c !== undefined && c !== false) el.append(c instanceof Node ? c : String(c));
  return el;
}
function s(tag, attrs, ...kids) {
  const el = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs || {})) el.setAttribute(k, v);
  for (const c of kids) el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  return el;
}
function fill(id, ...nodes) { const el = $(id); el.replaceChildren(...nodes.flat(Infinity).filter(Boolean)); }
function ago(ts) {
  if (!ts) return "never";
  const t = typeof ts === "string" ? Date.parse(ts) / 1000 : ts;
  const m = (Date.now() / 1000 - t) / 60;
  if (m < 1) return "just now";
  if (m < 90) return `${Math.round(m)} min ago`;
  if (m < 48 * 60) return `${(m / 60).toFixed(1)} h ago`;
  return `${Math.round(m / 1440)} d ago`;
}
function clock(ts) {
  if (!ts) return "";
  const d = new Date((typeof ts === "string" ? Date.parse(ts) / 1000 : ts) * 1000);
  return d.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}
const money = (v) => `$${Number(v || 0).toFixed(2)}`;
const tone = { merged: "b-good", merge: "b-good", ready: "b-info", hold: "b-warn", fixed: "b-good", failed: "b-bad",
  rerun: "b-info", "flaky-rerun": "b-info", skip: "", would: "b-info", error: "b-bad" };
const badge = (text, cls) => h("span", { class: `badge ${cls ?? tone[text] ?? ""}` }, text);
const empty = (text) => h("div", { class: "empty" }, text);
function facts(pairs) {
  return h("dl", { class: "facts" }, pairs.filter(Boolean).flatMap(([k, v]) => [h("dt", {}, k), h("dd", {}, v)]));
}

async function api(path, body) {
  const opt = body === undefined ? {} : { method: "POST", body: JSON.stringify(body),
    headers: { "Content-Type": "application/json", "X-Litha-Face": "1" } };
  const r = await fetch(path, { ...opt, credentials: "same-origin" });
  if (r.status === 403) { location.href = "/login"; throw new Error("sign in needed"); }
  const j = await r.json().catch(() => ({ error: `HTTP ${r.status}` }));
  if (!r.ok || j.error) throw new Error(j.error || `HTTP ${r.status}`);
  return j;
}

// ---- header + now -------------------------------------------------------------------------------------------------
function renderTop(n) {
  const c = n.controls;
  let label, detail;
  if (c.off) { label = "Off"; detail = "the OFF file stops her whole loop"; }
  else if (c.paused && c.paused_info.at && n.last_start > c.paused_info.at + 5) {
    label = "Pause not honored"; detail = `a run started ${ago(n.last_start)}, after the pause: the loop she runs from does not check PAUSED yet`;
  }
  else if (c.paused) { label = "Paused"; detail = `since ${ago(c.paused_info.at)}; her next run skips its work`; }
  else if (n.stuck) { label = "Running too long"; detail = `started ${ago(n.last_start)}`; }
  else if (n.running) { label = "Running"; detail = `${n.step ? "step " + n.step + ", " : ""}started ${ago(n.last_start)}`; }
  else if (n.late) { label = "Late"; detail = `no run since ${ago(n.last_start)} (she runs every 10 min)`; }
  else { label = "Idle"; detail = `last run ${ago(n.last_end)}, rc ${n.end_rc}`; }
  fill("state", h("b", {}, label), ` · ${detail}`);
  const p = $("pause");
  p.disabled = false;
  p.textContent = c.paused ? "Resume" : "Pause";
  p.className = c.paused ? "btn primary" : "btn warn";
}

function renderNow(n) {
  const hl = n.health || {};
  fill("now-body",
    facts([
      ["Loop", n.running ? `running${n.step ? " (" + n.step + ")" : ""}` : "idle"],
      ["Last start", n.last_start ? `${clock(n.last_start)} (${ago(n.last_start)})` : "none in the log"],
      ["Last end", n.last_end ? `${clock(n.last_end)}, rc ${n.end_rc}, ${n.seconds} s` : (n.running ? "still running" : "none")],
      ["Health", hl.ok === true ? badge("ok", "b-good") : hl.ok === false ? badge("problems", "b-warn") : "no check yet"],
      ["Health check", hl.at ? ago(hl.at) : "never"],
      ["Autonomy", n.controls.apply ? badge("APPLY", "b-warn") : badge("dry run", "")],
      ["Claude caps", `${money(n.controls.caps.day)} a day, ${money(n.controls.caps.total)} total`],
    ]),
    n.bad_steps.length || n.errors.length ? [h("div", { class: "sub" }, "Errors in the last run"),
      h("ul", { class: "list" }, [...n.bad_steps, ...n.errors].map((e) => h("li", { class: "mono" }, e)))] :
      h("div", { class: "sub" }, "No errors in the last run"),
    hl.problems && hl.problems.length ? [h("div", { class: "sub" }, "Health problems"),
      h("ul", { class: "list" }, hl.problems.map((e) => h("li", {}, e)))] : null,
    hl.info && hl.info.length ? [h("div", { class: "sub" }, "Health notes (at her last check)"),
      h("ul", { class: "list" }, hl.info.map((e) => h("li", { class: "muted" }, e)))] : null);
}

// ---- PRs ----------------------------------------------------------------------------------------------------------
function renderPrs(p) {
  $("prs-hint").textContent = `her last decision on each PR she looked at in the last ${p.days} days (from her log, not live GitHub)`;
  const repos = p.repos;
  if (!repoPick || !repos.some((r) => r.repo === repoPick)) repoPick = (repos.find((r) => r.prs.length) || repos[0] || {}).repo;
  fill("repo-chips", repos.map((r) => h("button", { type: "button", class: "chip", role: "tab",
    "aria-selected": r.repo === repoPick ? "true" : "false",
    onclick: () => { repoPick = r.repo; renderPrs(S.prs); } },
    r.repo.split("/")[1], h("span", { class: "n" }, r.prs.length))));
  const r = repos.find((x) => x.repo === repoPick);
  if (!r) return fill("prs-body", empty("No repositories."));
  const head = h("div", { class: "muted" }, `${r.repo} · ${r.mode}${r.base && r.base !== "*" ? " into " + r.base : ""} · `,
    Object.entries(r.counts).map(([k, v]) => `${v} ${k}`).join(", ") || "nothing decided this week");
  fill("prs-body", head, r.prs.length ? r.prs.map((x) => prRow(r.repo, x)) : empty("She logged no decision here this week."));
}

function prRow(repo, x) {
  const key = `${repo}#${x.pr}`;
  const state = x.merged ? "merged" : x.action;
  const said = Object.entries(x.said || {}).map(([k, v]) => `${k} ${v}`).join(" · ");
  const d = h("details", { class: "pr", open: openPrs.has(key) },
    h("summary", {}, h("span", { class: "num" }, `#${x.pr}`), h("span", { class: "title", title: x.title }, x.title || "(no title)",
        x.reasons.length ? h("span", { class: "why" }, x.reasons[0]) : null),
      badge(state), h("span", { class: "when" }, ago(x.ts))),
    h("div", { class: "detail" },
      facts([["Head", h("span", { class: "mono" }, x.head || "?")], ["Files", x.files ?? "?"],
        x.verdict ? ["Her review", `${x.verdict}${said ? " (parts: " + said + ")" : ""}`] : ["Her review", "none (a gate decided first)"],
        x.not_reviewed ? ["Not reviewed", `${x.not_reviewed} file(s)`] : null, ["Decided", clock(x.ts)]]),
      x.reasons.length ? [h("div", { class: "sub" }, "Reasons"), h("ul", { class: "list" }, x.reasons.map((t) => h("li", {}, t)))] : null,
      x.summary ? [h("div", { class: "sub" }, "Review summary"), h("p", {}, x.summary)] : null,
      x.risks.length ? [h("div", { class: "sub" }, "Risks she named"), x.risks.map((k) => h("div", { class: `risk ${k.severity}` },
        badge(k.severity || "?", k.severity === "high" ? "b-bad" : ""), " ", h("span", { class: "mono" }, `${k.file}:${k.line}`), " ", k.why))] : null));
  d.addEventListener("toggle", () => (d.open ? openPrs.add(key) : openPrs.delete(key)));
  return d;
}

// ---- fixes --------------------------------------------------------------------------------------------------------
function renderFixes(f) {
  const tiles = h("div", { class: "tiles" }, Object.entries(f.week).sort((a, b) => b[1] - a[1]).map(([k, v]) =>
    h("div", { class: "tile" }, h("div", { class: "v" }, v), h("div", { class: "k" }, `${k} this week`))));
  const rows = f.recent.slice(0, 12).map((x) => h("tr", {},
    h("td", { class: "n" }, ago(x.ts)), h("td", { class: "nw" }, x.repo === "oncoursemail/Star-AI-Project" ? `#${x.pr}` : `${x.repo.split("/")[1]} #${x.pr}`, x.fix_pr ? h("div", { class: "muted" }, `fix PR #${x.fix_pr}`) : null),
    h("td", {}, badge(x.result)), h("td", {}, x.why, x.tests.length ? h("div", { class: "muted mono" }, x.tests.join(", ")) : null)));
  fill("fixes-body", Object.keys(f.week).length ? tiles : empty("No fixes logged this week."),
    rows.length ? h("table", {}, h("thead", {}, h("tr", {}, h("th", { class: "n" }, "When"), h("th", {}, "PR"), h("th", {}, "Result"), h("th", {}, "Why"))),
      h("tbody", {}, rows)) : null);
}

// ---- spend --------------------------------------------------------------------------------------------------------
function meter(label, used, cap) {
  const pct = cap > 0 ? Math.min(100, (used / cap) * 100) : 100;
  return h("div", { class: "meter" }, h("div", { class: "lbl" }, h("span", {}, label), h("span", { class: "mono" }, `${money(used)} of ${money(cap)}`)),
    h("div", { class: "bar", role: "img", "aria-label": `${label}: ${money(used)} of ${money(cap)}` },
      h("div", { class: `fill ${pct >= 90 ? "bad" : pct >= 70 ? "warn" : ""}`, style: null, "data-w": pct })));
}
function dayBars(days, today) {
  if (!days.length) return null;
  const W = 420, H = 110, pad = 18, max = Math.max(...days.map((d) => d.usd), 0.01);
  const bw = Math.min(40, (W - pad) / days.length - 6);
  const g = s("svg", { class: "chart", viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Claude spend per day" });
  g.append(s("line", { class: "axis", x1: 0, x2: W, y1: H - pad, y2: H - pad }));
  days.forEach((d, i) => {
    const x = i * (bw + 6) + 4, bh = ((H - pad - 16) * d.usd) / max;
    g.append(s("rect", { class: `bar${d.day === today ? " today" : ""}`, x, y: H - pad - bh, width: bw, height: Math.max(1, bh), rx: 2 }));
    g.append(s("text", { x: x + bw / 2, y: H - pad - bh - 3, "text-anchor": "middle" }, money(d.usd)));
    g.append(s("text", { x: x + bw / 2, y: H - 4, "text-anchor": "middle" }, d.day.slice(5)));
  });
  return g;
}
function renderSpend(sp) {
  const today = new Date().toLocaleDateString("en-CA");
  fill("spend-body", meter("Today", sp.today, sp.caps.day), meter("All time", sp.total, sp.caps.total),
    h("div", { class: "sub" }, `Per day (${sp.calls} calls in all)`), dayBars(sp.days, today),
    h("div", { class: "sub" }, "Last calls"),
    sp.recent.length ? h("table", {}, h("tbody", {}, sp.recent.slice(0, 8).map((r) =>
      h("tr", {}, h("td", { class: "n" }, ago(r.ts)), h("td", {}, r.what), h("td", { class: "n" }, money(r.usd)))))) : empty("No Claude calls yet."));
  document.querySelectorAll(".meter .fill").forEach((el) => { el.style.width = `${el.dataset.w}%`; });
  const inp = $("cap-input");
  if (document.activeElement !== inp) inp.value = sp.caps.day;
}

// ---- autonomy -----------------------------------------------------------------------------------------------------
function renderAutonomy(a) {
  fill("apply-text", a.off ? h("span", {}, badge("off", "b-bad"), " the autonomy OFF file is set: she does not pick work")
    : a.apply ? h("span", {}, badge("APPLY", "b-warn"), " she acts on her queue (push, open PRs, comment, re-queue)")
    : h("span", {}, badge("dry run"), " she only builds the queue; nothing is acted on"));
  const b = $("apply");
  b.disabled = false;
  b.textContent = a.apply ? "Turn APPLY off" : "Turn APPLY on";
  b.className = a.apply ? "btn" : "btn warn";
  fill("autonomy-body",
    h("div", { class: "muted" }, `Queue built ${ago(a.built)}`),
    h("div", { class: "sub" }, `Queue (${a.tasks.length})`),
    a.tasks.length ? h("ul", { class: "list" }, a.tasks.map((t) => h("li", {}, badge(t.kind || "task", "b-info"), " ",
      h("b", {}, `${(t.repo || "").split("/")[1] || ""} #${t.number ?? "?"}`), ` score ${t.score ?? "?"}: `, t.why))) : empty("Empty queue."),
    a.skipped.length ? [h("div", { class: "sub" }, "Skipped"), h("ul", { class: "list" }, a.skipped.map((t) => h("li", { class: "muted" }, `${t.key}: ${t.why}`)))] : null,
    a.notes.length ? [h("div", { class: "sub" }, "Notes"), h("ul", { class: "list" }, a.notes.map((t) => h("li", { class: "muted" }, t)))] : null,
    h("div", { class: "sub" }, "Last runs"),
    a.runs.length ? h("ul", { class: "list" }, a.runs.map((r) => h("li", {}, `${ago(r.ts)} · ${r.mode} · ${r.tasks} task(s)`,
      r.acted.map((x) => h("div", { class: "muted" }, badge(x.result || "?"), " ", x.why))))) : empty("No runs yet."));
}

// ---- self-tune ----------------------------------------------------------------------------------------------------
function lineChart(points, label) {
  if (!points.length) return null;
  const W = 420, H = 120, L = 34, B = 18, T = 10;
  const ys = points.map((p) => p.y), lo = Math.min(...ys), hi = Math.max(...ys), span = Math.max(hi - lo, 1);
  const x = (i) => L + (points.length === 1 ? (W - L) / 2 : (i * (W - L - 8)) / (points.length - 1));
  const y = (v) => T + (H - T - B) * (1 - (v - lo + span * 0.1) / (span * 1.2));
  const g = s("svg", { class: "chart", viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": label });
  g.append(s("line", { class: "axis", x1: L, x2: W, y1: H - B, y2: H - B }));
  [lo, hi].forEach((v) => g.append(s("text", { x: L - 4, y: y(v) + 3, "text-anchor": "end" }, `${v.toFixed(1)}%`)));
  g.append(s("polyline", { class: "line", points: points.map((p, i) => `${x(i)},${y(p.y)}`).join(" ") }));
  points.forEach((p, i) => {
    const dot = s("circle", { class: "dot", cx: x(i), cy: y(p.y), r: 3 });
    dot.append(s("title", {}, p.tip));
    g.append(dot);
  });
  g.append(s("text", { x: L, y: H - 4 }, points[0].x));
  if (points.length > 1) g.append(s("text", { x: W - 8, y: H - 4, "text-anchor": "end" }, points[points.length - 1].x));
  return g;
}
function renderSelftune(st) {
  const pts = st.runs.filter((r) => r.total).map((r) => ({ y: (100 * r.points) / r.total, x: clock(r.ts),
    tip: `${clock(r.ts)}: ${r.points}/${r.total} points, prompt ${r.prompt}${(r.overrides || []).length ? " (" + r.overrides.join(", ") + ")" : ""}` }));
  const last = st.runs[st.runs.length - 1];
  const suites = {};
  st.bench.forEach((b) => { (suites[b.suite] = suites[b.suite] || []).push(b); });
  fill("selftune-body",
    h("div", { class: "sub" }, "Merge replay score per run (points / total)"),
    pts.length ? [lineChart(pts, "Self-tune score over runs"),
      h("div", { class: "muted" }, `Last: ${last.points}/${last.total} with prompt ${last.prompt}, ${ago(last.ts)}`)] : empty("No self-tune runs yet."),
    h("div", { class: "sub" }, "Fixer bench (solved / cases)"),
    Object.keys(suites).length ? h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "Suite"), h("th", { class: "n" }, "Last"), h("th", { class: "n" }, "Best"), h("th", { class: "n" }, "Runs"), h("th", { class: "n" }, "When"))),
      h("tbody", {}, Object.entries(suites).map(([k, v]) => {
        const l = v[v.length - 1], best = v.reduce((a, b) => (b.solved / b.n > a.solved / a.n ? b : a));
        return h("tr", {}, h("td", {}, k), h("td", { class: "n" }, `${l.solved}/${l.n}`), h("td", { class: "n" }, `${best.solved}/${best.n}`),
          h("td", { class: "n" }, v.length), h("td", { class: "n" }, ago(l.at)));
      }))) : empty("No bench runs yet."),
    st.proposals.length ? [h("div", { class: "sub" }, "Prompt proposals"), h("ul", { class: "list" }, st.proposals.map((p) =>
      h("li", {}, h("span", { class: "mono" }, p.name), ` · ${ago(p.ts)} · ${p.failures} failure(s) studied · ${money(p.spent)}`)))] : null);
}

// ---- log ----------------------------------------------------------------------------------------------------------
async function loadLog() {
  try {
    const j = await api("/api/log");
    const pre = $("log-body");
    const atEnd = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 20;
    pre.replaceChildren(...j.lines.map((l) => h("span", { class: /Traceback|Error\b|HOLD/.test(l) ? (/HOLD/.test(l) ? "" : "e") : /MERGE|READY|merged|fixed/.test(l) ? "s" : "" }, l + "\n")));
    if (atEnd || !pre.dataset.seen) { pre.scrollTop = pre.scrollHeight; pre.dataset.seen = "1"; }
  } catch (e) { $("log-body").textContent = `Could not read the log: ${e.message}`; }
}

// ---- refresh + controls -------------------------------------------------------------------------------------------
async function refresh() {
  try {
    S = await api("/api/state");
    const parts = [["now", () => { renderTop(S.now); renderNow(S.now); }], ["prs", () => renderPrs(S.prs)],
      ["fixes", () => renderFixes(S.fixes)], ["spend", () => renderSpend(S.spend)],
      ["autonomy", () => renderAutonomy(S.autonomy)], ["selftune", () => renderSelftune(S.selftune)]];
    for (const [id, fn] of parts) {
      try { fn(); } catch (e) { fill(`${id}-body`, h("div", { class: "msg err" }, `This panel failed to draw: ${e.message}`)); }
    }
    $("updated").textContent = `updated ${new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })} · read ${S.read_ms} ms`;
  } catch (e) {
    fill("state", h("b", {}, "No data"), ` · ${e.message}`);
  }
}

async function control(name, value, confirmText) {
  if (confirmText && !confirm(confirmText)) return;
  try { await api("/api/control", { control: name, value }); } catch (e) { alert(`Not changed: ${e.message}`); }
  refresh();
}

function addMsg(cls, text, meta) {
  const m = h("div", { class: `msg ${cls}` }, text, meta ? h("span", { class: "meta" }, meta) : null);
  $("chat-log").append(m);
  m.scrollIntoView({ block: "nearest" });
  return m;
}

document.addEventListener("DOMContentLoaded", () => {
  $("pause").addEventListener("click", () => {
    const on = !(S && S.now.controls.paused);
    control("pause", on, on ? "Pause Litha? Her next scheduled run will skip all work (fixing, merging, promoting) until you resume." : null);
  });
  $("apply").addEventListener("click", () => {
    const on = !(S && S.autonomy.apply);
    control("apply", on, on ? "Turn APPLY on? From her next run she acts on her autonomy queue: pushes fix branches, opens PRs, comments, re-queues." : null);
  });
  $("cap-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const v = Number($("cap-input").value);
    try { await api("/api/control", { control: "day_cap", value: v }); $("cap-note").textContent = `saved: ${money(v)} a day`; }
    catch (e) { $("cap-note").textContent = `not saved: ${e.message}`; }
    refresh();
  });
  $("chat-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const q = $("chat-q").value.trim();
    if (!q) return;
    const smart = $("chat-smart").checked;
    addMsg("q", q);
    const wait = addMsg("a", smart ? "Asking Claude..." : "Asking her local model (can take a minute if she is busy)...");
    $("chat-send").disabled = true;
    try {
      const r = await api("/api/chat", { q, smart });
      wait.remove();
      if (r.answer) addMsg("a", r.answer, `${r.via === "claude" ? "Claude (paid)" : "her local model"} · ${r.seconds} s`);
      else addMsg("err", r.error || "no answer", `${r.via} · ${r.seconds} s`);
      $("chat-q").value = "";
    } catch (e) { wait.remove(); addMsg("err", e.message); }
    $("chat-send").disabled = false;
  });
  $("chat-q").addEventListener("keydown", (ev) => {
    if (ev.key === "Enter" && (ev.ctrlKey || ev.metaKey)) $("chat-form").requestSubmit();
  });
  $("log-refresh").addEventListener("click", loadLog);
  refresh();
  loadLog();
  setInterval(() => { if (!document.hidden) { refresh(); loadLog(); } }, 20000);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(); });
});
