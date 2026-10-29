"""Compile + load one plugin/mod answer in a real headless server (runs INSIDE the mc-plugins container, as root).

    python3 loadtest.py job.json          -> one JSON line on stdout
    python3 loadtest.py --warm            first boot of every server (world, Mojang jar, remap caches)

job: {"id", "target": paper|spigot|velocity|fabric|fabric-mojmap|neoforge,
      "sources": {"com/x/Main.java": "..."}, "resources": {"plugin.yml": "...", "fabric.mod.json": "...", ...},
      "commands": ["heal", ...]}     # typed into the server console after start (no arguments)
Result: {"id", "target", "stage": compile|build|load|ok, "ok", "loaded", "errors": [...], "commands": {cmd: ok|
         unknown|exception}, "compile": <diagnostics>, "ms": {...}}
Paper/Spigot/Velocity jars come from the warm javac service (classes + resources); Fabric and NeoForge are built by
Gradle from the templates (Loom remapJar to intermediary; NeoForge needs no remap) with the warm offline cache.
"""
from __future__ import annotations

import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

M = Path("/opt/mcp")
J21 = "/usr/lib/jvm/java-21-openjdk-amd64/bin/java"
J25_HOME = "/usr/lib/jvm/java-25-openjdk-amd64"
SERVER = {
    "paper": (M / "servers/paper", [J21, "-Xmx1500M", "-jar", "paper.jar", "--nogui"], "plugins"),
    "spigot": (M / "servers/paper", [J21, "-Xmx1500M", "-jar", "paper.jar", "--nogui"], "plugins"),
    "velocity": (M / "servers/velocity", [J21, "-Xmx512M", "-jar", "velocity.jar"], "plugins"),
    "fabric": (M / "servers/fabric", [J21, "-Xmx2G", "-jar", "fabric-server.jar", "nogui"], "mods"),
    "fabric-mojmap": (M / "servers/fabric", [J21, "-Xmx2G", "-jar", "fabric-server.jar", "nogui"], "mods"),
    "neoforge": (M / "servers/neoforge", [J21, "-Xmx2G", "@libraries/net/neoforged/neoforge/21.11.48/unix_args.txt",
                                          "nogui"], "mods"),
}
STOP = {"velocity": "shutdown"}
DONE = re.compile(r"Done \(\d+[.,]\d+s\)!")
UNKNOWN = re.compile(r"Unknown or incomplete command|Unknown command|Incorrect argument for command", re.I)
INTERNAL = re.compile(r"An internal error occurred|Unhandled exception executing command|"
                      r"Exception while executing command|threw an exception", re.I)
LOAD_FAIL = re.compile(r"Could not load '|Could not load plugin|Error occurred while enabling|InvalidPluginException|"
                       r"InvalidDescriptionException|UnknownDependencyException|UnsupportedClassVersionError|"
                       r"Can't create plugin|Unable to load plugin|Mod resolution failed|Incompatible mods? found|"
                       r"Could not execute entrypoint|Mixin apply .*failed|InvalidInjectionException|"
                       r"ModLoadingException|Failed to (?:load|create) mod|Encountered an unexpected exception|"
                       r"Loading errors encountered|Missing or unsupported mandatory dependencies|"
                       r"plugin\.yml.*(?:invalid|not found)|NoClassDefFoundError|ClassNotFoundException|"
                       r"Exception in server tick loop|Crash report saved", re.I)


def token() -> str:
    return (M / "token").read_text().strip()


def compile_classes(target: str, sources: dict, outdir: Path) -> dict:
    req = urllib.request.Request("http://127.0.0.1:8105/compile",
                                 json.dumps({"target": target, "files": sources, "outdir": str(outdir)}).encode(),
                                 {"Content-Type": "application/json", "Authorization": f"Bearer {token()}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def make_jar(classes: Path, resources: dict, dest: Path):
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\n")
        for f in sorted(classes.rglob("*")):
            if f.is_file():
                z.write(f, f.relative_to(classes).as_posix())
        for name, text in resources.items():
            if name not in z.namelist():
                z.writestr(name, text)


def gradle_build(target: str, sources: dict, resources: dict, work: Path) -> tuple[Path | None, str]:
    proj = work / "proj"
    shutil.copytree(M / "templates" / target, proj, ignore=shutil.ignore_patterns("build", ".gradle", "run"))
    for rel, text in sources.items():
        p = proj / "src/main/java" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    for rel, text in resources.items():
        p = proj / "src/main/resources" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    task = "remapJar" if target.startswith("fabric") else "jar"
    env = dict(os.environ, JAVA_HOME=J25_HOME if target.startswith("fabric") else "/usr/lib/jvm/java-21-openjdk-amd64")
    r = subprocess.run(["gradle", "--offline", "-q", "--console=plain", task], cwd=proj, env=env,
                       capture_output=True, text=True, timeout=600)
    jars = sorted((proj / "build/libs").glob("testmod-*.jar")) if r.returncode == 0 else []
    jars = [j for j in jars if not j.name.endswith(("-sources.jar", "-dev.jar"))]
    return (jars[0] if jars else None), (r.stdout + r.stderr)[-4000:]


def eula_ok(target: str) -> bool:
    """Velocity has no EULA. Paper/Fabric/NeoForge run Mojang's server: only when the OWNER accepted the EULA
    himself (eula.txt = eula=true, written by hand after his OK; setup.sh writes eula=false)."""
    if target == "velocity":
        return True
    try:
        return "eula=true" in (SERVER[target][0] / "eula.txt").read_text().replace(" ", "").lower()
    except OSError:
        return False


def run_server(target: str, jar: Path | None, commands: list[str], timeout_s: int = 240) -> dict:
    import fcntl
    with open(SERVER[target][0] / ".run.lock", "w") as lock:      # one run per server folder at a time
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _run_server(target, jar, commands, timeout_s)


def _run_server(target: str, jar: Path | None, commands: list[str], timeout_s: int = 240) -> dict:
    sdir, cmd, sub = SERVER[target]
    plug = sdir / sub
    if plug.exists():
        for f in plug.iterdir():                       # only our jar (+ Fabric API for Fabric)
            if f.name.startswith(".paper-remapped") or f.name == ".paper-remapped":
                continue
            shutil.rmtree(f) if f.is_dir() else f.unlink()
    plug.mkdir(exist_ok=True)
    if target.startswith("fabric"):
        shutil.copy(sdir / "base-mods/fabric-api.jar", plug / "fabric-api.jar")
    if jar is not None:
        shutil.copy(jar, plug / "testplugin.jar")
    for d in ("crash-reports",):
        shutil.rmtree(sdir / d, ignore_errors=True)
    t0 = time.monotonic()
    p = subprocess.Popen(cmd, cwd=sdir, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, bufsize=1)
    lines: list[str] = []
    q: queue.Queue = queue.Queue()

    def pump():
        for ln in p.stdout:
            lines.append(ln.rstrip("\n"))
            q.put(ln)
        q.put(None)
    threading.Thread(target=pump, daemon=True).start()
    done = False
    while time.monotonic() - t0 < timeout_s:
        try:
            ln = q.get(timeout=1)
        except queue.Empty:
            continue
        if ln is None:
            break
        if DONE.search(ln):
            done = True
            break
    start_s = round(time.monotonic() - t0, 1)
    results = {}
    if done:
        time.sleep(1.5)
        for c in commands:
            mark = len(lines)
            try:
                p.stdin.write(c + "\n")
                p.stdin.flush()
            except OSError:
                break
            time.sleep(2.0)
            out = "\n".join(lines[mark:])
            results[c] = "unknown" if UNKNOWN.search(out) else ("exception" if INTERNAL.search(out) else "ok")
    try:
        p.stdin.write(STOP.get(target, "stop") + "\n")
        p.stdin.flush()
        p.wait(timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        p.kill()
        p.wait()
    return {"done": done, "start_s": start_s, "lines": lines, "commands": results}


def norm(line: str) -> str:
    return re.sub(r"\d+", "#", re.sub(r"^\[[^\]]*\]\s*", "", line.strip()))[:200]


def baseline(target: str) -> set:
    """Error-looking lines the server prints with no plugin at all (netty kqueue probe etc.): not the answer's."""
    f = SERVER[target][0] / f"baseline-{target}.json"
    try:
        return set(json.loads(f.read_text()))
    except (OSError, ValueError):
        return set()


def analyse(target: str, run: dict, ids: list[str]) -> tuple[bool, list[str]]:
    """(loaded, error lines). Lines mentioning our plugin/mod id, its package or a load failure pattern."""
    errs = []
    lines = run["lines"]
    noise = baseline(target)
    for i, ln in enumerate(lines):
        if norm(ln) in noise:
            continue
        if LOAD_FAIL.search(ln) or (("ERROR" in ln or "Exception" in ln) and any(x and x in ln for x in ids)):
            ctx = [ln] + [x for x in lines[i + 1:i + 4] if x.lstrip().startswith(("at ", "Caused by")) or "Exception" in x]
            errs.append(" | ".join(s.strip() for s in ctx)[:400])
    if target in ("paper", "spigot"):
        enabled = any(re.search(r"\[[^\]]+\] Enabling ", ln) and any(x and x in ln for x in ids) for ln in lines)
        loaded = run["done"] and enabled and not errs
    else:
        loaded = run["done"] and not errs
        if target == "velocity" and run["done"]:
            loaded = loaded and any("Loaded plugin" in ln and any(x and x in ln for x in ids) for ln in lines)
    return loaded, errs[:12]


def job(j: dict) -> dict:
    t0 = time.monotonic()
    target = j["target"]
    work = M / "work" / re.sub(r"[^\w.-]", "_", str(j["id"]))
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    os.chmod(work, 0o777)
    res = {"id": j["id"], "target": target, "ok": False, "loaded": False, "errors": [], "commands": {}, "ms": {}}
    ids = [str(x) for x in j.get("ids", [])]
    if target in ("paper", "spigot", "velocity"):
        (work / "classes").mkdir()
        os.chmod(work / "classes", 0o777)
        c = compile_classes(target, j["sources"], work / "classes")
        res["compile"] = [d for d in c.get("diagnostics", []) if d["kind"] == "ERROR"][:20]
        res["ms"]["compile"] = c.get("ms")
        if not c.get("ok"):
            res["stage"] = "compile"
            return res
        jar = work / "plugin.jar"
        make_jar(work / "classes", j.get("resources", {}), jar)
    else:
        t1 = time.monotonic()
        jar, log = gradle_build(target, j["sources"], j.get("resources", {}), work)
        res["ms"]["build"] = round((time.monotonic() - t1) * 1000)
        if jar is None:
            res["stage"], res["errors"] = "build", [ln for ln in log.splitlines() if ln.strip()][-25:]
            return res
    if not eula_ok(target):
        res["stage"], res["ok"] = "built", None
        res["note"] = "not loaded: running a Minecraft server needs the owner's own OK to Mojang's EULA (eula.txt)"
        return res
    run = run_server(target, jar, j.get("commands", []))
    res["ms"]["server_start"] = run["start_s"] * 1000
    loaded, errs = analyse(target, run, ids)
    res.update(loaded=loaded, errors=errs, commands=run["commands"], done=run["done"])
    res["ok"] = loaded and all(v != "unknown" for v in run["commands"].values())
    res["stage"] = "ok" if res["ok"] else "load"
    if not run["done"]:
        res["log_tail"] = run["lines"][-30:]
    res["ms"]["total"] = round((time.monotonic() - t0) * 1000)
    return res


def main(argv: list[str]) -> int:
    if argv and argv[0] == "--warm":
        for t in ("paper", "velocity", "fabric", "neoforge"):
            if not eula_ok(t):
                print(t, "skipped: Mojang EULA not accepted by the owner (eula.txt)")
                continue
            r = run_server(t, None, [], timeout_s=600)
            print(t, "done" if r["done"] else "NOT done", r["start_s"], "s", flush=True)
            noise = sorted({norm(ln) for ln in r["lines"] if LOAD_FAIL.search(ln) or "ERROR" in ln or "Exception" in ln})
            for alias in {t, "spigot" if t == "paper" else t, "fabric-mojmap" if t == "fabric" else t}:
                (SERVER[t][0] / f"baseline-{alias}.json").write_text(json.dumps(noise))
            print(" baseline noise lines:", len(noise))
            if not r["done"]:
                print("\n".join(r["lines"][-15:]))
        return 0
    j = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    print(json.dumps(job(j)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
