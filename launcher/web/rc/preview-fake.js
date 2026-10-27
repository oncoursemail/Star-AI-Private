// A pretend RcModule for rc/preview.html and the browser test. It answers the same calls and emits the same task events
// as launcher/rc/module.py, with timers instead of real work. It never starts anything. Not loaded by the launcher.
//
// Scenarios (?scenario=): typical | fresh (no tools) | changed (client files differ) | backend-off | offline-vr | partners-off

const stagesFor = {
  launch: [["prepare", "Preparing"], ["client", "Finding the client"], ["verify", "Checking files"], ["backend", "RC backend"], ["plan", "Planning the start"], ["start", "Starting"], ["confirm", "Waiting for it to open"]],
  tools: [["check", "Looking for the newest RC tools"], ["download", "Getting the package"], ["verify", "Checking the package"], ["unpack", "Unpacking and checking files"], ["switch", "Switching over"]],
  backend: [["check", "Checking the backend"], ["start", "Starting the task"], ["wait", "Waiting for it to answer"]],
  client: [["inspect", "Reading the client's files"], ["register", "Recording the baseline"]],
};

const ERR = {
  files_changed: { code: "files_changed", title: "Client files changed", message: "Some launch files no longer match what was recorded when this client was added. That happens after a game update or a mod. Nothing was started. First: GameAssembly.dll.", detail: "file_changed: GameAssembly.dll", actions: [{ id: "rebaseline", label: "Accept the current files as the new baseline" }, { id: "view_log", label: "View log" }] },
  tools_missing: { code: "tools_missing", title: "RC tools are not installed", message: "The Metallic RC tools (the part that checks and starts the client) are not on this PC yet. Installing them does not touch any game.", detail: "", actions: [{ id: "install_tools", label: "Install RC tools" }] },
};

export function makeFakeRc(scenario = "typical") {
  const listeners = new Set();
  const emit = (ev) => listeners.forEach((fn) => fn(ev));
  let ids = 0;
  const S = {
    settings: { mode: "screen", startBackendWithClient: false, source: {}, lastClient: "steam" },
    toolsInstalled: scenario !== "fresh", toolsKind: "adopted", toolsVersion: "0.2",
    backend: scenario === "backend-off" ? "stopped" : "running",
    changed: scenario === "changed", registered: { steam: true, campus: true },
    log: ["2026-10-26 18:50:02 launch t1 done", "2026-10-26 18:52:40 tools t2 failed [hash_mismatch] expected 497c..., got 0000..."],
  };

  const clients = () => {
    const base = (key, name, blurb, extra) => ({ key, name, blurb, kind: key === "steam" ? "baseline" : "partner", state: "not_found", installRoot: null, installationId: null, evidence: null, launcherPath: null, launcherRegistered: false, usesOwnLauncher: false, unityVersion: null, files: null, bytes: null, verification: null, actions: [], ...extra });
    const steam = base("steam", "Rec Room 2026 (Steam)", "Your installed Steam client. This is the baseline Metallic RC is built around.", { state: S.changed ? "changed" : (S.verified ? "verified" : "registered"), installRoot: "C:\\Program Files (x86)\\Steam\\steamapps\\common\\RecRoom", installationId: "5853", unityVersion: "6000.0.27f1", files: 3298 });
    if (!S.toolsInstalled) return [base("steam", "Rec Room 2026 (Steam)", "Your installed Steam client. This is the baseline Metallic RC is built around."), base("campus", "Campus", "A community revival of Rec Room. Started through its own launcher."), base("nexanet", "NexaNet", "A community revival. Modified client: it needs its own launcher."), base("meownet", "MeowNet", "A community revival. Modified client: it needs its own launcher.")];
    const off = scenario === "partners-off";
    return [steam,
      base("campus", "Campus", "A community revival of Rec Room. Started through its own launcher.", off ? {} : { state: "registered", installRoot: "C:\\Users\\player\\Documents\\Campus\\Campus2025", installationId: "fbcd", launcherPath: "C:\\Users\\player\\Desktop\\Campus.exe", launcherRegistered: true, usesOwnLauncher: true, unityVersion: "2021.3.1f1" }),
      base("nexanet", "NexaNet", "A community revival. Modified client: it needs its own launcher.", off ? {} : { state: "found", installRoot: "C:\\Users\\player\\Downloads\\NexaNet\\NexaNet", usesOwnLauncher: true }),
      base("meownet", "MeowNet", "A community revival. Modified client: it needs its own launcher.", off ? {} : { state: "found", installRoot: "C:\\Meow.Net", usesOwnLauncher: true })];
  };

  const backend = () => ({ state: S.backend, port: 4187, task: S.backend === "running" ? null : "Ready", instanceId: S.backend === "running" ? "212d47d0" : null, ready: S.backend === "running", nativeClientReady: false, actualGameClientVerified: false,
    implemented: S.backend === "running" ? { ownedAccounts: true, persistentRoomDirectory: true } : {}, native: S.backend === "running" ? { nativeLogin: false, nativeRoomJoin: false, nativeGameplay: false, nativeVoice: false } : undefined,
    honesty: "This is Metallic's own RC backend. The original Rec Room client has not logged into it.", checkedAt: Date.now() / 1000 });

  function startTask(kind, title, steps, work) {
    const task = { id: `t${++ids}`, kind, title, state: "queued", stages: stagesFor[kind].map(([id, label]) => ({ id, label, state: "pending", detail: "" })), fraction: null, detail: "", error: null, result: null, startedAt: Date.now() / 1000, finishedAt: null };
    const push = () => emit({ type: "task", task: JSON.parse(JSON.stringify(task)) });
    push();
    (async () => {
      task.state = "running"; push();
      const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
      const stage = (id, detail = "") => { let hit = false; task.stages.forEach((s) => { if (s.id === id) { s.state = "active"; s.detail = detail; hit = true; } else if (!hit && (s.state === "pending" || s.state === "active")) s.state = "done"; }); task.fraction = null; task.detail = detail; push(); };
      const progress = (f, d) => { task.fraction = f; if (d) task.detail = d; push(); };
      try { task.result = await work({ stage, progress, sleep }) || {}; task.stages.forEach((s) => { if (s.state === "pending" || s.state === "active") s.state = "done"; }); task.state = "done"; task.fraction = 1; }
      catch (e) { task.state = "failed"; task.error = e.rc || ERR.files_changed; const a = task.stages.find((s) => s.state === "active"); if (a) a.state = "failed"; }
      task.finishedAt = Date.now() / 1000; push();
    })();
    return JSON.parse(JSON.stringify(task));
  }
  const fail = (rc) => Object.assign(new Error(rc.title), { rc });

  const handlers = {
    overview: async () => ({ settings: S.settings, tools: tools(), tasks: [], clients: clients(), backend: backend(), vr: { available: scenario !== "offline-vr", runtimes: scenario === "offline-vr" ? [] : ["SteamVR"], steamvrRunning: false, note: scenario === "offline-vr" ? "No VR runtime found (SteamVR or an OpenXR runtime). VR mode may not start." : "VR runtime found: SteamVR" }, steamUrl: "https://store.steampowered.com/app/471710/",
      ...(S.toolsInstalled ? {} : { clientsError: ERR.tools_missing }) }),
    "backend.status": async () => backend(),
    "settings.set": async (p) => Object.assign(S.settings, p),
    "log.tail": async () => ({ lines: S.log }),
    "tools.check_update": async () => ({ installed: S.toolsInstalled, current: S.toolsVersion, latest: { version: "0.3", name: "Metallic-RC-0.3-tools-win-x64.zip", size: 98158674, sha256: "..." }, updateAvailable: true }),
    "tools.install": async () => ({ task: startTask("tools", "Installing RC tools", 0, async ({ stage, progress, sleep }) => {
      stage("check", "Looking for the newest RC tools"); await sleep(500); stage("download", "Copying Metallic-RC-0.3-tools-win-x64.zip");
      for (let i = 1; i <= 10; i++) { progress(i / 10); await sleep(120); }
      stage("verify", "Checking the package against its published SHA-256"); await sleep(700);
      stage("unpack", "Unpacking and checking every file"); for (let i = 1; i <= 10; i++) { progress(i / 10, `Unpacking lib/${i}.dll`); await sleep(110); }
      stage("switch", "Switching to the new version"); await sleep(300);
      S.toolsInstalled = true; S.toolsKind = "managed"; S.toolsVersion = "0.3"; return { version: "0.3", changed: true };
    }) }),
    "tools.verify": async () => ({ task: startTask("tools", "Checking RC tools", 0, async ({ stage, progress, sleep }) => { stage("check", "Checking every file"); for (let i = 1; i <= 8; i++) { progress(i / 8, `Checking file ${i}`); await sleep(120); } return { ok: true, checked: 575, missing: [], changed: [], missingCount: 0, changedCount: 0 }; }) }),
    "backend.start": async () => ({ task: startTask("backend", "Starting the RC backend", 0, async ({ stage, progress, sleep }) => { stage("check"); await sleep(300); stage("start", "Asking Windows to start the backend task"); await sleep(500); stage("wait", "Waiting for it to answer"); for (let i = 1; i <= 6; i++) { progress(i / 8); await sleep(250); } S.backend = "running"; return { state: "running", changed: true }; }) }),
    "backend.stop": async () => ({ task: startTask("backend", "Stopping the RC backend", 0, async ({ stage, sleep }) => { stage("check"); await sleep(300); stage("stop", "Asking the backend to shut down cleanly"); await sleep(600); S.backend = "stopped"; return { state: "stopped", changed: true }; }) }),
    "clients.verify": async (p) => ({ task: startTask("client", "Checking client files", 0, async ({ stage, sleep }) => { stage("inspect", "Comparing launch files with the baseline"); await sleep(900); if (p.client === "steam") S.verified = !S.changed; return { isValid: !S.changed, problems: [] }; }) }),
    "clients.rebaseline": async () => ({ task: startTask("client", "Accepting the current files", 0, async ({ stage, sleep }) => { stage("inspect"); await sleep(600); stage("register", "Recording the files' fingerprints"); await sleep(700); S.changed = false; return { replaced: true }; }) }),
    "clients.register": async () => ({ task: startTask("client", "Adding a client", 0, async ({ stage, sleep }) => { stage("inspect"); await sleep(600); stage("register"); await sleep(600); return {}; }) }),
    "task.cancel": async () => ({ cancelled: true }),
    "repair.run": async (p) => {
      if (p.action === "install_tools") return handlers["tools.install"]();
      if (p.action === "install_from_steam") return { openUrl: "https://store.steampowered.com/app/471710/" };
      if (p.action === "view_log") return { lines: S.log };
      if (p.action === "register_client") return handlers["clients.register"](p.params || {});
      if (p.action === "use_screen") { S.settings.mode = "screen"; return { settings: S.settings, message: "Screen mode is on." }; }
      if (p.action === "restart_backend") return handlers["backend.start"]();
      return {};
    },
    "launch.start": async (p) => {
      if (!S.toolsInstalled) throw fail(ERR.tools_missing);
      return { task: startTask("launch", "Starting Rec Room", 0, async ({ stage, progress, sleep }) => {
        stage("prepare", "Checking the RC tools"); await sleep(500);
        stage("client", "Looking for the client"); await sleep(400);
        stage("verify", "Comparing launch files with the baseline"); await sleep(900);
        if (S.changed && p.client === "steam") throw fail(ERR.files_changed);
        stage("backend", "Looking at the RC backend"); await sleep(400);
        stage("plan", "Asking RC for the exact start command"); await sleep(400);
        const cmd = p.client === "campus" ? "Campus.exe" : `RecRoom.exe +forcemode:${p.mode}`;
        stage("start", cmd); await sleep(600);
        stage("confirm", "Waiting for it to open"); for (let i = 1; i <= 5; i++) { progress(i / 6); await sleep(250); }
        const warnings = [];
        if (S.backend !== "running") warnings.push("The RC backend is not running, so Metallic rooms and accounts are unavailable. The client starts with its own services.");
        if (p.mode === "vr" && scenario === "offline-vr") warnings.push("No VR runtime found (SteamVR or an OpenXR runtime). VR mode may not start.");
        return { processId: 4242, command: cmd, mode: p.mode, target: p.client === "campus" ? "external" : "client", running: true, warnings, client: p.client, backend: S.backend };
      }) };
    },
  };
  const tools = () => S.toolsInstalled ? { installed: true, kind: S.toolsKind, version: S.toolsVersion, exe: "C:\\...\\Metallic.RC.Launcher.exe", installedAt: S.toolsKind === "managed" ? new Date().toISOString() : null, previous: S.toolsKind === "managed" ? "0.2" : null } : { installed: false, kind: "none", version: null, exe: null, installedAt: null, previous: null };

  return {
    request: async (method, params = {}) => { const fn = handlers[method]; if (!fn) throw fail({ code: "bad_request", title: "That request was not understood", message: `The preview has no ${method}.`, detail: "", actions: [] }); await new Promise((r) => setTimeout(r, 60)); return fn(params); },
    onEvent: (fn) => { listeners.add(fn); return () => listeners.delete(fn); },
    pickFolder: async () => "D:\\Games\\RecRoomCopy",
    pickFile: async () => "D:\\Games\\Nexa\\Nexa.exe",
    openUrl: (u) => { window.__opened = u; },
  };
}
