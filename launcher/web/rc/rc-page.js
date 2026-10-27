// Metallic RC page: install, check, launch and repair the RC client, the RC backend, partner revivals.
//
//   import { mountRcPage, makeRcClient } from "./rc/rc-page.js";
//   const rc = makeRcClient(channel.objects.rc);          // QWebChannel object from launcher/rc_bridge.py
//   const page = mountRcPage(containerElement, { rc, toast, art });
//   ...later: page.unmount();
//
// rc    { request(method, params) -> Promise<result>, onEvent(fn) -> off, pickFolder(title), pickFile(title, filter), openUrl(url) }
// toast optional (message) => void.   art optional hero picture URL (default art/rc.jpg).
//
// Every word from the module goes in through textContent, never innerHTML. The page only draws what RcModule reports:
// it never decides that something worked.

const STATE = {
  not_found: ["Not found", "off"], found: ["Found, not added", "info"], registered: ["Added", "info"], verified: ["Files verified", "ok"],
  changed: ["Files changed", "bad"], needs_launcher: ["Needs its own launcher", "warn"],
};
const BACKEND = {
  running: ["Running", "ok"], stopped: ["Stopped", "off"], disabled: ["Turned off", "warn"], not_installed: ["Not set up", "warn"],
  conflict: ["Port in use by something else", "bad"], unhealthy: ["Not answering", "bad"],
};
const STAGE_MARK = { pending: "", active: "", done: "done", failed: "failed", skipped: "skipped" };

export function makeRcClient(obj) {
  // Adapts the Qt object (string slots, one signal) to promises and parsed events.
  const waiting = new Map();
  const listeners = new Set();
  let n = 0;
  obj.event.connect((text) => {
    let ev; try { ev = JSON.parse(text); } catch { return; }
    if (ev.type === "reply" && waiting.has(ev.id)) {
      const { resolve, reject } = waiting.get(ev.id); waiting.delete(ev.id);
      ev.ok ? resolve(ev.result) : reject(Object.assign(new Error(ev.error?.title || "RC problem"), { rc: ev.error }));
      return;
    }
    listeners.forEach((fn) => fn(ev));
  });
  const ask = (name, ...args) => new Promise((res) => obj[name](...args, res));
  return {
    request: (method, params = {}) => new Promise((resolve, reject) => {
      const id = `q${++n}`; waiting.set(id, { resolve, reject }); obj.request(id, method, JSON.stringify(params));
    }),
    onEvent: (fn) => { listeners.add(fn); return () => listeners.delete(fn); },
    pickFolder: (title) => ask("pickFolder", title),
    pickFile: (title, filter) => ask("pickFile", title, filter || "Programs (*.exe)"),
    openUrl: (u) => obj.openUrl(u),
  };
}

function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (v === true) el.setAttribute(k, "");
    else el.setAttribute(k, v);
  }
  for (const kid of kids.flat()) { if (kid == null || kid === false) continue; el.append(kid.nodeType ? kid : document.createTextNode(String(kid))); }
  return el;
}

// replaceChildren would write the text "null" for a missing child, so empty slots are dropped first.
const set = (el, ...kids) => el.replaceChildren(...kids.flat().filter((k) => k != null && k !== false));

export function mountRcPage(root, ctx) {
  const rc = ctx.rc;
  const toast = ctx.toast || (() => {});
  const S = { ov: null, tasks: {}, error: {}, selected: null, mode: "screen", confirm: null, loading: true, loadError: null, update: null, warnings: [] };
  const off = [];
  const views = {};
  let pollTimer = 0, raf = 0, dirtyTasks = new Set();

  const page = h("div", { class: "rc-page" });
  root.replaceChildren(page);

  // ---- calls -------------------------------------------------------------------------------------------------------
  const call = async (method, params) => {
    try { return await rc.request(method, params); }
    catch (err) { throw err.rc ? err : Object.assign(err, { rc: { code: "rc_error", title: "Something went wrong", message: String(err.message || err), detail: "", actions: [] } }); }
  };

  async function refresh(quiet) {
    try {
      S.ov = await call("overview");
      S.loadError = null;
      S.mode = S.ov.settings.mode || "screen";
      if (!S.selected || !S.ov.clients.some((c) => c.key === S.selected)) {
        S.selected = S.ov.clients.some((c) => c.key === S.ov.settings.lastClient) ? S.ov.settings.lastClient : "steam";
      }
      for (const t of S.ov.tasks || []) S.tasks[t.kind] = t;
    } catch (err) { S.loadError = err.rc; }
    S.loading = false;
    renderAll();
  }

  async function refreshBackend() {
    if (!S.ov || document.hidden) return;
    try {
      const b = await call("backend.status");
      const same = ["state", "ready", "instanceId", "task"].every((k) => b[k] === S.ov.backend[k]);
      S.ov.backend = b;
      if (!same) { renderBackend(); renderHero(); }  // no redraw when nothing changed, so focus is not lost every 15 seconds
    } catch { /* the next poll will try again */ }
  }

  async function run(method, params, kindKey) {
    try {
      const out = await call(method, params);
      if (out.task) { S.tasks[out.task.kind] = out.task; S.error[out.task.kind] = null; dirtyTasks.add(out.task.kind); scheduleTasks(); }
      return out;
    } catch (err) {
      const e = err.rc;
      if (kindKey) S.error[kindKey] = e; else toast(e.message || e.title);
      renderAll();
      return null;
    }
  }

  async function repair(action, params) {
    if (action === "retry") return;
    const out = await run("repair.run", { action, params: params || {} });
    if (!out) return;
    if (out.openUrl) rc.openUrl(out.openUrl);
    if (out.help) toast(out.help.join(" "));
    if (out.message) toast(out.message);
    if (out.needsInput === "folder") await chooseFolderAndAdd();
    if (out.needsInput === "launcher") await chooseLauncherAndAdd();
    if (out.lines) openLog();
    if (out.settings) { S.ov.settings = out.settings; S.mode = out.settings.mode; }
    renderAll();
  }

  // ---- events --------------------------------------------------------------------------------------------------------
  off.push(rc.onEvent((ev) => {
    if (ev.type !== "task") return;
    const t = ev.task;
    S.tasks[t.kind] = t;
    dirtyTasks.add(t.kind);
    scheduleTasks();
    if (["done", "failed", "cancelled"].includes(t.state)) {
      if (t.state === "failed") S.error[t.kind] = t.error;
      if (t.kind === "launch" && t.state === "done") S.warnings = t.result?.warnings || [];
      if (t.kind === "launch" && t.state === "failed") S.warnings = [];
      setTimeout(() => refresh(true), 150);
    }
  }));
  function scheduleTasks() { if (!raf) raf = requestAnimationFrame(() => { raf = 0; for (const k of dirtyTasks) views[k]?.update(S.tasks[k]); dirtyTasks.clear(); renderGates(); }); }

  // ---- task view (stage track + bar + detail + cancel) --------------------------------------------------------------
  function taskView(kind) {
    const track = h("ol", { class: "rc-stages", "aria-label": "Steps" });
    const bar = h("div", { class: "rc-bar" }, h("i"));
    const detail = h("p", { class: "rc-detail", "aria-live": "polite" });
    const cancel = h("button", { class: "rc-btn sm", "data-nav": true, onclick: () => { const t = S.tasks[kind]; if (t) call("task.cancel", { id: t.id }); } }, "Cancel");
    const wrap = h("div", { class: "rc-task", hidden: true }, track, bar, h("div", { class: "rc-task-foot" }, detail, cancel));
    let shownId = "";
    return {
      el: wrap,
      update(t) {
        if (!t || (t.state !== "running" && t.state !== "queued")) { wrap.hidden = true; return; }
        wrap.hidden = false;
        if (shownId !== t.id) { shownId = t.id; track.replaceChildren(...t.stages.map((s) => h("li", { "data-id": s.id }, h("span", { class: "rc-dot" }), h("span", {}, s.label)))); }
        t.stages.forEach((s, i) => { const li = track.children[i]; if (li) { li.dataset.state = s.state; if (s.state === "active") li.setAttribute("aria-current", "step"); else li.removeAttribute("aria-current"); } });
        const fill = bar.firstChild;
        if (t.fraction == null) { bar.classList.add("indeterminate"); fill.style.width = ""; } else { bar.classList.remove("indeterminate"); fill.style.width = `${Math.round(t.fraction * 100)}%`; }
        detail.textContent = t.detail || t.title;
        cancel.hidden = t.state !== "running";
      },
    };
  }

  function errorCard(kind, onDismiss) {
    const e = S.error[kind];
    if (!e) return null;
    const actions = (e.actions || []).filter((a) => a.id !== "retry");
    return h("div", { class: "rc-error", role: "alert" },
      h("div", { class: "rc-error-text" }, h("strong", {}, e.title), h("p", {}, e.message)),
      h("div", { class: "rc-actions" },
        ...actions.map((a) => h("button", { class: "rc-btn sm", "data-nav": true, onclick: () => (a.id === "rebaseline" ? askRebaseline(selected()) : repair(a.id, { client: S.selected })) }, a.label)),
        h("button", { class: "rc-link", "data-nav": true, onclick: () => { S.error[kind] = null; onDismiss?.(); renderAll(); } }, "Dismiss")),
      e.detail ? h("details", { class: "rc-details" }, h("summary", {}, "Details"), h("code", {}, e.detail)) : null);
  }

  function askRebaseline(c) { if (!c) return; S.confirm = { kind: "rebaseline", client: c }; renderClients(); }

  // ---- hero / play -------------------------------------------------------------------------------------------------
  const selected = () => S.ov?.clients.find((c) => c.key === S.selected);
  const busy = () => ["launch", "client", "tools"].some((k) => ["running", "queued"].includes(S.tasks[k]?.state));
  views.launch = taskView("launch");
  views.client = taskView("client");
  views.tools = taskView("tools");
  views.backend = taskView("backend");
  const hero = h("section", { class: "rc-hero", "aria-label": "Play Metallic RC" });
  const heroArt = h("img", { class: "rc-hero-art", src: ctx.art || "art/rc.jpg", alt: "" });
  const heroBody = h("div", { class: "rc-hero-body" });
  hero.append(heroArt, h("div", { class: "rc-hero-shade" }), heroBody);

  const toolsMissing = () => S.ov?.clientsError?.code === "tools_missing";

  function playLabel(c) {
    if (toolsMissing()) return "Install RC tools";
    if (!c) return "Play";
    if (c.state === "not_found") return c.key === "steam" ? "Get Rec Room" : "Locate folder";
    if (c.state === "found") return c.usesOwnLauncher && !c.launcherPath ? "Choose launcher" : "Add and play";
    if (c.state === "needs_launcher") return "Choose launcher";
    return "Play";
  }

  function whatPlayDoes(c) {
    if (toolsMissing()) return "The RC tools check your client and start it. Install them first; this does not touch any game.";
    if (!c) return "";
    if (c.state === "not_found") return c.key === "steam" ? "Rec Room is not installed. Metallic never downloads the game for you; this opens its Steam page." : "No folder found at the usual place.";
    if (c.usesOwnLauncher) return c.launcherPath ? `Checks the files, then opens ${c.name}'s own launcher. It picks screen or VR itself.` : `${c.name} must be started through its own launcher. Choose it once.`;
    return `Checks the launch files, then starts RecRoom.exe with +forcemode:${S.mode}.`;
  }

  async function onPlay() {
    const c = selected();
    if (!c || busy()) return;
    if (toolsMissing()) { run("tools.install", {}, "launch"); return; }
    if (c.state === "not_found") { c.key === "steam" ? repair("install_from_steam") : chooseFolderAndAdd(); return; }
    if ((c.state === "needs_launcher") || (c.state === "found" && c.usesOwnLauncher && !c.launcherPath)) { chooseLauncherAndAdd(); return; }
    if (c.usesOwnLauncher && c.launcherPath && !S.confirm) { S.confirm = { kind: "external", client: c }; renderHero(); return; }
    await startLaunch(c, c.usesOwnLauncher);
  }

  async function startLaunch(c, confirmExternal) {
    S.confirm = null; S.error.launch = null; S.warnings = [];
    await run("launch.start", { client: c.key, mode: S.mode, confirmExternal: !!confirmExternal }, "launch");
    renderHero();
  }

  async function chooseFolderAndAdd() {
    const folder = await rc.pickFolder("Choose the Rec Room folder");
    if (!folder) return;
    await run("clients.register", { client: S.selected === "steam" ? "custom" : S.selected, folder }, "client");
  }

  async function chooseLauncherAndAdd() {
    const c = selected();
    const file = await rc.pickFile(`Choose ${c ? c.name : "the client"}'s own launcher`, "Programs (*.exe)");
    if (!file) return;
    await run("clients.register", { client: c.key, launcher: file }, "client");
  }

  function renderHero() {
    if (!S.ov) return;
    const c = selected();
    const running = ["running", "queued"].includes(S.tasks.launch?.state);
    const vr = S.ov.vr;
    const external = c && c.usesOwnLauncher && c.launcherPath;
    const last = S.tasks.launch;
    const ok = last && last.state === "done" && last.result;
    set(heroBody,
      h("p", { class: "rc-eyebrow" }, c ? c.name : "Metallic RC"),
      h("h1", {}, "Metallic RC"),
      h("p", { class: "rc-blurb" }, "Rec Room, started the careful way: files checked first, the exact command shown, and nothing hidden."),
      h("div", { class: "rc-playrow" },
        h("button", { class: "rc-btn primary play", "data-nav": true, id: "rcPlay", disabled: busy(), onclick: onPlay }, h("span", {}, running ? "Starting" : playLabel(c))),
        h("div", { class: "rc-seg", role: "radiogroup", "aria-label": "Screen or VR" },
          ...["screen", "vr"].map((m) => h("button", { role: "radio", "aria-checked": String(S.mode === m), "data-nav": true, disabled: !!external || running,
            onclick: async () => { S.mode = m; await call("settings.set", { mode: m }); renderHero(); } }, m === "screen" ? "Screen" : "VR")))),
      h("p", { class: "rc-does" }, whatPlayDoes(c)),
      S.mode === "vr" && !external && vr && !vr.available ? h("p", { class: "rc-warn-line" }, vr.note) : null,
      S.confirm ? confirmCard() : null,
      views.launch.el,
      ok && !running ? h("p", { class: "rc-ok-line" }, `Running: ${last.result.command}.`) : null,
      ...(ok && !running ? (S.warnings || []).map((w) => h("p", { class: "rc-warn-line" }, w)) : []),
      errorCard("launch"));
    views.launch.update(S.tasks.launch);
  }

  function confirmCard() {
    const c = S.confirm.client;
    return h("div", { class: "rc-confirm", role: "group", "aria-label": "Confirm" },
      h("p", {}, `This opens ${c.name}'s own launcher (${(c.launcherPath || "").split("\\").pop()}), not Metallic's. It then starts the game and handles screen or VR itself.`),
      h("div", { class: "rc-actions" },
        h("button", { class: "rc-btn primary sm", "data-nav": true, onclick: () => startLaunch(c, true) }, `Open ${c.name}'s launcher`),
        h("button", { class: "rc-btn sm", "data-nav": true, onclick: () => { S.confirm = null; renderHero(); } }, "Cancel")));
  }

  // ---- clients ----------------------------------------------------------------------------------------------------
  const clientsPanel = h("section", { class: "rc-panel", "aria-label": "Clients" });

  function clientRow(c) {
    const [label, tone] = STATE[c.state] || [c.state, "off"];
    const isSel = c.key === S.selected;
    const acts = [];
    if (c.state === "found" || c.state === "needs_launcher") acts.push([c.usesOwnLauncher && !c.launcherPath ? "Choose launcher" : "Add", () => (c.usesOwnLauncher && !c.launcherPath ? (S.selected = c.key, chooseLauncherAndAdd()) : run("clients.register", { client: c.key, launcher: c.launcherPath || undefined }, "client"))]);
    if (["registered", "verified", "changed"].includes(c.state)) acts.push(["Check files", () => run("clients.verify", { client: c.key }, "client")]);
    if (c.state === "changed") acts.push(["Accept new files", () => askRebaseline(c)]);
    if (c.state === "not_found") acts.push(["Choose folder", () => { S.selected = c.key; chooseFolderAndAdd(); }]);
    return h("li", { class: "rc-client", "aria-current": String(isSel) },
      h("button", { class: "rc-client-main", "data-nav": true, "aria-pressed": String(isSel), onclick: () => { S.selected = c.key; call("settings.set", { lastClient: c.key }); renderHero(); renderClients(); } },
        h("span", { class: "rc-client-name" }, c.name),
        h("span", { class: `rc-chip ${tone}` }, label),
        h("span", { class: "rc-client-sub" }, c.installRoot ? shorten(c.installRoot) : c.blurb)),
      h("div", { class: "rc-client-acts" }, ...acts.map(([t, fn]) => h("button", { class: "rc-btn sm", "data-nav": true, disabled: busy(), onclick: fn }, t))),
      S.confirm && S.confirm.kind === "rebaseline" && S.confirm.client.key === c.key ? h("div", { class: "rc-confirm wide" },
        h("p", {}, "Some launch files differ from what was recorded. That is normal after a game update. Only accept if you know why they changed."),
        h("div", { class: "rc-actions" },
          h("button", { class: "rc-btn primary sm", "data-nav": true, onclick: () => { S.confirm = null; run("clients.rebaseline", { client: c.key, confirm: true }, "client"); } }, "Accept the current files"),
          h("button", { class: "rc-btn sm", "data-nav": true, onclick: () => { S.confirm = null; renderClients(); } }, "Cancel"))) : null);
  }

  function renderClients() {
    if (!S.ov) return;
    const list = S.ov.clients;
    const base = list.filter((c) => c.kind !== "partner");
    const partners = list.filter((c) => c.kind === "partner");
    set(clientsPanel,
      h("div", { class: "rc-panel-head" }, h("h2", {}, "Your clients"), h("button", { class: "rc-link", "data-nav": true, onclick: () => refresh() }, "Look again")),
      S.ov.clientsError ? h("p", { class: "rc-note" }, `${S.ov.clientsError.title}. ${S.ov.clientsError.message}`) : null,
      S.ov.clientsError ? null : h("ul", { class: "rc-clients" }, ...base.map(clientRow)),
      S.ov.clientsError ? null : h("h3", { class: "rc-sub" }, "Partner revivals"),
      S.ov.clientsError ? null : h("p", { class: "rc-muted" }, "Looked for at their usual install places. They are community projects and start through their own launchers; Metallic only checks that their files match what you added."),
      S.ov.clientsError ? null : h("ul", { class: "rc-clients" }, ...partners.map(clientRow)),
      views.client.el, errorCard("client"));
    views.client.update(S.tasks.client);
  }

  // ---- tools --------------------------------------------------------------------------------------------------------
  const toolsPanel = h("section", { class: "rc-panel", "aria-label": "RC tools" });

  function renderTools() {
    if (!S.ov) return;
    const t = S.ov.tools;
    const running = ["running", "queued"].includes(S.tasks.tools?.state);
    const done = S.tasks.tools?.state === "done" ? S.tasks.tools : null;
    const upd = S.update;
    let lead;
    if (!t.installed) lead = "Not installed. These small tools check your client and start it. Installing them does not touch any game.";
    else if (t.kind === "adopted") lead = "Found the RC tools installed earlier on this PC. They are used as they are. Install a managed copy to get updates and repairs.";
    else lead = `Version ${t.version}${t.installedAt ? `, installed ${new Date(t.installedAt).toLocaleDateString()}` : ""}.`;
    const verifyResult = done && done.result && "ok" in done.result && done.result.checked != null ? done.result : null;
    set(toolsPanel,
      h("div", { class: "rc-panel-head" }, h("h2", {}, "RC tools"), t.installed ? h("span", { class: `rc-chip ${t.kind === "managed" ? "ok" : "info"}` }, t.kind === "managed" ? `v${t.version}` : "Existing copy") : h("span", { class: "rc-chip warn" }, "Not installed")),
      h("p", { class: "rc-note" }, lead),
      upd ? h("p", { class: `rc-note ${upd.updateAvailable ? "info" : ""}` }, upd.updateAvailable ? `Version ${upd.latest.version} is available${upd.latest.size ? ` (${(upd.latest.size / 1048576).toFixed(0)} MB)` : ""}.` : "You have the newest version.") : null,
      verifyResult ? h("p", { class: `rc-note ${verifyResult.ok ? "ok" : "bad"}` }, verifyResult.ok ? `All ${verifyResult.checked} files match.` : `${verifyResult.changedCount} changed and ${verifyResult.missingCount} missing of ${verifyResult.checked} files.`) : null,
      h("div", { class: "rc-actions" },
        !t.installed || t.kind === "adopted" ? h("button", { class: "rc-btn primary sm", "data-nav": true, disabled: running, onclick: () => run("tools.install", {}, "tools") }, t.installed ? "Install a managed copy" : "Install RC tools") : null,
        t.installed && upd && upd.updateAvailable && t.kind === "managed" ? h("button", { class: "rc-btn primary sm", "data-nav": true, disabled: running, onclick: () => run("tools.update", {}, "tools") }, "Update") : null,
        h("button", { class: "rc-btn sm", "data-nav": true, disabled: running, onclick: checkUpdate }, "Check for updates"),
        t.installed ? h("button", { class: "rc-btn sm", "data-nav": true, disabled: running, onclick: () => run("tools.verify", {}, "tools") }, "Check files") : null,
        t.installed ? h("button", { class: "rc-btn sm", "data-nav": true, disabled: running, onclick: () => run("tools.repair", {}, "tools") }, "Repair") : null,
        t.previous ? h("button", { class: "rc-btn sm", "data-nav": true, disabled: running, onclick: async () => { await run("tools.rollback", {}, "tools"); refresh(); } }, `Back to ${t.previous}`) : null),
      views.tools.el, errorCard("tools"),
      sourceBlock());
    views.tools.update(S.tasks.tools);
  }

  async function checkUpdate() {
    try { S.update = await call("tools.check_update"); S.error.tools = null; } catch (err) { S.error.tools = err.rc; S.update = null; }
    renderTools();
  }

  function sourceBlock() {
    const src = S.ov.settings.source || {};
    const kind = h("select", { "aria-label": "Source type", "data-nav": true }, h("option", { value: "folder" }, "Folder"), h("option", { value: "url" }, "Address"));
    kind.value = src.kind || "folder";
    const field = h("input", { type: "text", "aria-label": "Source", value: src.path || src.url || "", placeholder: kind.value === "url" ? "https://... release address" : "Folder with the package and SHA256SUMS.txt", spellcheck: "false" });
    kind.addEventListener("change", () => { field.placeholder = kind.value === "url" ? "https://... release address" : "Folder with the package and SHA256SUMS.txt"; });
    return h("details", { class: "rc-details" }, h("summary", {}, "Where updates come from"),
      h("p", { class: "rc-muted" }, src.kind ? "Packages are only installed after their SHA-256 and every file inside match." : "Using the packages folder from the earlier RC install on this PC. Packages are only installed after their SHA-256 and every file inside match."),
      h("div", { class: "rc-source" }, kind, field,
        h("button", { class: "rc-btn sm", "data-nav": true, onclick: async () => { const f = await rc.pickFolder("Choose the package folder"); if (f) { kind.value = "folder"; field.value = f; } } }, "Browse"),
        h("button", { class: "rc-btn sm", "data-nav": true, onclick: async () => {
          const v = field.value.trim();
          const source = !v ? {} : kind.value === "url" ? { kind: "url", url: v } : { kind: "folder", path: v };
          S.ov.settings = await call("settings.set", { source }); S.update = null; toast(v ? "Update source saved." : "Back to the default source."); renderTools();
        } }, "Save")));
  }

  // ---- backend ----------------------------------------------------------------------------------------------------
  const backendPanel = h("section", { class: "rc-panel", "aria-label": "RC backend" });

  function renderBackend() {
    if (!S.ov) return;
    const b = S.ov.backend;
    const [label, tone] = BACKEND[b.state] || [b.state, "off"];
    const run_ = ["running", "queued"].includes(S.tasks.backend?.state);
    const rows = [];
    const impl = b.implemented || {};
    if (b.state === "running") {
      rows.push(["Accounts and rooms", impl.ownedAccounts || impl.persistentRoomDirectory ? "Working" : "Not reported", impl.ownedAccounts || impl.persistentRoomDirectory ? "ok" : "off"]);
      const n = b.native || {};
      rows.push(["Original game sign-in", n.nativeLogin ? "Working" : "Not yet", n.nativeLogin ? "ok" : "off"]);
      rows.push(["Joining rooms from the game", n.nativeRoomJoin ? "Working" : "Not yet", n.nativeRoomJoin ? "ok" : "off"]);
      rows.push(["Voice", n.nativeVoice ? "Working" : "Not yet", n.nativeVoice ? "ok" : "off"]);
    }
    set(backendPanel,
      h("div", { class: "rc-panel-head" }, h("h2", {}, "RC backend"), h("span", { class: `rc-chip ${tone}` }, label)),
      h("p", { class: "rc-note" }, backendLead(b)),
      rows.length ? h("dl", { class: "rc-caps" }, ...rows.map(([k, v, t]) => h("div", {}, h("dt", {}, k), h("dd", { class: t }, v)))) : null,
      b.state === "running" ? h("p", { class: "rc-muted" }, b.honesty) : null,
      h("div", { class: "rc-actions" },
        b.state !== "running" && b.state !== "conflict" && b.state !== "not_installed" ? h("button", { class: "rc-btn primary sm", "data-nav": true, disabled: run_, onclick: () => run("backend.start", { enable: b.state === "disabled" }, "backend") }, b.state === "disabled" ? "Turn on and start" : "Start") : null,
        b.state === "running" ? h("button", { class: "rc-btn sm", "data-nav": true, disabled: run_, onclick: () => run("backend.stop", {}, "backend") }, "Stop") : null,
        b.state === "running" || b.state === "unhealthy" ? h("button", { class: "rc-btn sm", "data-nav": true, disabled: run_, onclick: () => repair("restart_backend") }, "Restart") : null),
      views.backend.el, errorCard("backend"),
      h("label", { class: "rc-switch" },
        h("input", { type: "checkbox", checked: !!S.ov.settings.startBackendWithClient, "data-nav": true, onchange: async (e) => { S.ov.settings = await call("settings.set", { startBackendWithClient: e.target.checked }); } }),
        h("span", { class: "rc-track" }), h("span", {}, "Start it when I press Play")),
      logBlock());
    views.backend.update(S.tasks.backend);
  }

  function backendLead(b) {
    return ({
      running: `Answering on this PC only (port ${b.port}).`,
      stopped: "Stopped. It runs on this PC only. Start it to use Metallic accounts and rooms.",
      disabled: "Its Windows task was turned off earlier, so it will not start by itself.",
      not_installed: "The Windows task that runs it was not found. The RC backend installer creates it.",
      conflict: `Port ${b.port} answers, but not as the Metallic RC backend. Left alone.`,
      unhealthy: "The task is running but the backend is not answering.",
    })[b.state] || "";
  }

  function logBlock() {
    const pre = h("pre", { class: "rc-log" });
    const d = h("details", { class: "rc-details" }, h("summary", {}, "Log"), pre);
    d.addEventListener("toggle", async () => { if (d.open) { const r = await call("log.tail", { lines: 80 }); pre.textContent = r.lines.join("\n") || "Nothing logged yet."; } });
    S.logEl = d;
    return d;
  }
  function openLog() { if (S.logEl) { S.logEl.open = true; S.logEl.dispatchEvent(new Event("toggle")); } }

  // ---- whole page ---------------------------------------------------------------------------------------------------
  function renderGates() { const b = page.querySelector("#rcPlay"); if (b) b.disabled = busy(); }

  function renderAll() {
    if (S.loading) { page.replaceChildren(h("p", { class: "rc-muted pad" }, "Looking at your PC...")); return; }
    if (S.loadError) { page.replaceChildren(h("div", { class: "rc-error" }, h("strong", {}, S.loadError.title), h("p", {}, S.loadError.message), h("button", { class: "rc-btn sm", "data-nav": true, onclick: () => refresh() }, "Try again"))); return; }
    renderHero(); renderClients(); renderTools(); renderBackend();
    const left = h("div", { class: "rc-col" }, hero, clientsPanel);
    const right = h("div", { class: "rc-col" }, toolsPanel, backendPanel);
    page.replaceChildren(left, right);
  }

  const shorten = (p) => (p.length > 58 ? `${p.slice(0, 22)}...${p.slice(-32)}` : p);

  refresh();
  pollTimer = setInterval(refreshBackend, 15000);
  return {
    refresh,
    unmount() { clearInterval(pollTimer); off.forEach((f) => f()); cancelAnimationFrame(raf); root.replaceChildren(); },
  };
}
