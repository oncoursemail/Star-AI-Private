"""Self-upgrade watcher: official releases of what STAR runs on, checked weekly; llama.cpp tried on one node at night.

Check (runs inside the self-model service once a week, or `python -m mesh.upgrade.watch check`):
  llama.cpp  GitHub ggml-org/llama.cpp releases: newest bNNNNN build that has the configured asset (the Windows CUDA zip)
  Forgejo    Codeberg forgejo/forgejo: newest non-prerelease
  models     Hugging Face repos we pin: commit sha changed
Each component gets one decision record (kind "upgrade"): none | available | trial. Forgejo and models are report-only
(a server with a database and pinned model files are upgraded by hand); llama.cpp becomes "trial" when a node has
trials switched on.

Trial (ON a node PC, night, `python watch.py trial --home D:\\Litha`, copied next to node_agent.py and autotune.py):
  gates as autotune (night window, node idle, no OFF file) + node.json "upgrade": {"trial_enabled": true}; downloads the
  release zip from the GitHub API URL, verifies its sha256 digest, unpacks it into <home>/upgrade/<tag>/ (sandbox;
  cudart/cublas DLLs copied from the current engine folder when the zip has none), benchmarks + mini-evals it against
  the current engine with the same config (autotune.measure), and promotes only on a win (node.json "llama_server" ->
  the sandbox exe, node restarted, automatic rollback when it does not come back). Every decision is logged and reported.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
LLAMA_API = "https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=30"
FORGEJO_API = "https://codeberg.org/api/v1/repos/forgejo/forgejo/releases?limit=10"
HF_API = "https://huggingface.co/api/models/"
ASSET = r"^llama-b\d+-bin-win-cuda-12\.4-x64\.zip$"
WEEK_S = 7 * 86400


def http_get(url: str, timeout: float = 20) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "star-upgrade-watch", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(20_000_000)


def build_of(tag_or_version: str) -> int | None:
    m = re.search(r"\bb(?:uild\s*)?(\d{3,6})\b", tag_or_version or "")
    return int(m.group(1)) if m else None


def latest_llama(releases: list, asset_rx: str = ASSET) -> dict | None:
    best = None
    for r in releases or []:
        b = build_of(r.get("tag_name", ""))
        if b is None or r.get("draft"):
            continue
        asset = next((a for a in r.get("assets") or [] if re.match(asset_rx, a.get("name", ""))), None)
        if asset and (best is None or b > best["build"]):
            best = {"tag": r["tag_name"], "build": b, "published": r.get("published_at"),
                    "asset": {"name": asset["name"], "url": asset.get("browser_download_url"),
                              "digest": asset.get("digest"), "size": asset.get("size")}}
    return best


def latest_stable(releases: list) -> str | None:
    for r in releases or []:
        if not r.get("prerelease") and not r.get("draft"):
            return str(r.get("tag_name") or "").lstrip("v") or None
    return None


def version_tuple(v: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", v or "")[:4])


def check(cfg: dict, state: dict, get=http_get, now: float | None = None) -> list[dict]:
    """-> decision records (kind "upgrade"). `state` keeps current versions and last trial times (updated here)."""
    now = now or time.time()
    out = []
    comps = cfg.get("components") or {}
    if "llama.cpp" in comps:
        c = comps["llama.cpp"]
        cur = state.get("llama.cpp", {}).get("current") or c.get("current", "")
        try:
            latest = latest_llama(json.loads(get(LLAMA_API)), c.get("asset", ASSET))
        except (OSError, ValueError) as e:
            latest, err = None, f"{type(e).__name__}"
        else:
            err = ""
        rec = {"kind": "upgrade", "component": "llama.cpp", "current": cur, "latest": latest["tag"] if latest else None}
        if latest is None:
            rec.update(decision="none", why=f"no release with the asset found {err}".strip())
        elif (build_of(cur) or 0) >= latest["build"]:
            rec.update(decision="none", why="up to date")
        else:
            behind = latest["build"] - (build_of(cur) or 0)
            trial = c.get("trial_nodes") or []
            rec.update(decision="trial" if trial else "available", nodes=trial, asset=latest["asset"],
                       why=f"{behind} builds newer ({latest['published']}); " +
                           (f"night trial on {', '.join(trial)} against the fixed benchmark + mini-eval" if trial
                            else "no node has trials switched on (node.json upgrade.trial_enabled)"))
        out.append(rec)
    if "forgejo" in comps:
        cur = comps["forgejo"].get("current", "")
        try:
            latest = latest_stable(json.loads(get(FORGEJO_API)))
        except (OSError, ValueError):
            latest = None
        newer = bool(latest and version_tuple(latest) > version_tuple(cur))
        out.append({"kind": "upgrade", "component": "forgejo", "current": cur, "latest": latest,
                    "decision": "available" if newer else "none",
                    "why": "newer stable release: upgrade by hand (server with a database; check the release notes and "
                           "the signature)" if newer else ("up to date" if latest else "release list unreadable")})
    for repo, pinned in (comps.get("models") or {}).items():
        try:
            info = json.loads(get(HF_API + repo))
            sha = info.get("sha")
        except (OSError, ValueError):
            sha, info = None, {}
        changed = bool(sha and pinned and sha != pinned)
        out.append({"kind": "upgrade", "component": f"model {repo}", "current": (pinned or "")[:12],
                    "latest": (sha or "")[:12], "decision": "available" if changed else "none",
                    "why": f"repo changed {info.get('lastModified', '')}: re-run the model eval before switching"
                           if changed else ("same commit" if sha else "repo unreadable")})
    state["checked_at"] = now
    return out


def due(state: dict, now: float | None = None, every_s: float = WEEK_S) -> bool:
    return (now or time.time()) - float(state.get("checked_at") or 0) >= every_s


# ---------- the trial on a node ----------

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch_build(home: Path, latest: dict, current_exe: Path, download=None) -> Path:
    """Download + verify + unpack into <home>/upgrade/<tag>/; returns the sandbox llama-server.exe."""
    asset = latest["asset"]
    digest = (asset.get("digest") or "").removeprefix("sha256:")
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("the release asset has no sha256 digest: not trusted")
    if not str(asset.get("url", "")).startswith("https://github.com/ggml-org/llama.cpp/releases/download/"):
        raise ValueError("unexpected download URL")
    box = home / "upgrade" / latest["tag"]
    box.mkdir(parents=True, exist_ok=True)
    zpath = box / asset["name"]
    if not zpath.is_file() or sha256_file(zpath) != digest:
        (download or _download)(asset["url"], zpath)
    if sha256_file(zpath) != digest:
        zpath.unlink(missing_ok=True)
        raise ValueError("sha256 mismatch: download deleted")
    with zipfile.ZipFile(zpath) as z:
        for name in z.namelist():
            target = (box / name).resolve()
            if not str(target).startswith(str(box.resolve())):
                raise ValueError("zip entry outside the sandbox")
        z.extractall(box)
    exe = next(box.rglob("llama-server.exe"), None)
    if exe is None:
        raise ValueError("llama-server.exe not in the zip")
    for dll in current_exe.parent.glob("*.dll"):          # CUDA runtime from the current engine when the zip lacks it
        if re.match(r"(?i)(cudart|cublas|cublasLt)64_", dll.name) and not (exe.parent / dll.name).exists():
            shutil.copy2(dll, exe.parent / dll.name)
    zpath.unlink(missing_ok=True)
    return exe


def _download(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "star-upgrade-watch"})
    with urllib.request.urlopen(req, timeout=600) as r, open(dest, "wb") as f:
        shutil.copyfileobj(r, f, 1 << 20)


def exe_build(exe: Path) -> int | None:
    try:
        out = subprocess.run([str(exe), "--version"], capture_output=True, text=True, timeout=30)
        return build_of(out.stdout + out.stderr)
    except (OSError, subprocess.SubprocessError):
        return None


def trial(home: Path, *, now: bool = False, get=http_get, download=None, engine=None, status=None, restart=None,
          sleep=time.sleep, current_build=None) -> dict:
    sys.path.insert(0, str(home))
    import autotune as at   # noqa: PLC0415 - next to this file on the node PC
    import node_agent       # noqa: PLC0415
    cfg = node_agent.load_config(home)
    status = status or at.node_status
    restart = restart or at.restart_node
    up = cfg.get("upgrade") or {}
    rec = {"ts": round(time.time(), 1), "kind": "upgrade", "component": "llama.cpp", "node": cfg.get("node")}

    def finish(decision, why, **more):
        rec.update(decision=decision, why=why, **more)
        at.log(home, rec)
        url, tok = (cfg.get("router_url") or "").rstrip("/"), at._token(cfg, home)
        if url and tok:
            try:
                req = urllib.request.Request(url + "/mesh/self/report", data=json.dumps(rec).encode(),
                                             headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
                urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=8).close()
            except OSError:
                pass
        return rec

    if not up.get("trial_enabled"):
        return finish("skip", "trials are off on this node (node.json upgrade.trial_enabled)")
    lo, hi = up.get("hours") or (cfg.get("autotune") or {}).get("hours") or at.DEFAULTS["hours"]
    if not now and not lo <= at._now_hour() < hi:
        return finish("skip", f"outside the night window {lo:02d}-{hi:02d}h")
    if (home / "OFF").exists() or (home / "AUTOTUNE_RUNNING").exists():
        return finish("skip", "node parked or autotune running")
    cur_exe = node_agent.resolve(home, cfg["llama_server"])
    cur = current_build if current_build is not None else exe_build(cur_exe)
    latest = latest_llama(json.loads(get(LLAMA_API)), up.get("asset", ASSET))
    rec.update(current=f"b{cur}" if cur else "?", latest=latest["tag"] if latest else None)
    if not latest or (cur or 0) >= latest["build"]:
        return finish("none", "up to date")
    st = status(cfg, home)
    m = (st.get("models") or [{}])[0]
    if st.get("state") != "idle" or not m.get("loaded") or m.get("in_flight"):
        return finish("skip", f"node not idle ({st.get('state')})")
    engine = engine or at.Engine(home)
    off = home / "OFF"
    off.write_text("upgrade trial\n")
    try:
        new_exe = fetch_build(home, latest, cur_exe, download)
        for _ in range(60):
            try:
                if status(cfg, home).get("state") == "off":
                    break
            except (OSError, ValueError):
                pass
            sleep(1)
        g = engine.gpu() or {}
        step = node_agent.pick_step(cfg, int(g.get("free") or 0))
        if step is not None and step < 0:
            return finish("abort", "no ladder step fits")
        cand_cfg = {**cfg, "llama_server": str(new_exe)}
        base = [at.measure(engine, cfg, step)]
        try:
            res = at.measure(engine, cand_cfg, step)
        except (RuntimeError, OSError, ValueError) as e:
            res = {"tok_s": None, "quality": 0, "error": f"{type(e).__name__}: {e}"[:160]}
        base.append(at.measure(engine, cfg, step))
        cand = {**res, "name": latest["tag"]}
        verdict = at.decide(base, [cand], float(up.get("min_gain", 0.02)), int(cfg.get("min_free_loaded_mb") or 0))
        more = {"tok_s": res.get("tok_s"), "quality": res.get("quality"), "baseline_tok_s": verdict.get("baseline_tok_s"),
                "baseline_quality": verdict.get("baseline_quality")}
        if verdict["decision"] != "keep":
            return finish("reject", f"{verdict['why']}: {cand.get('verdict') or res.get('error') or '-'}", **more)
        backup = home / "autotune" / f"node-{time.strftime('%Y%m%d-%H%M%S')}-upgrade.json"
        backup.parent.mkdir(exist_ok=True)
        shutil.copy2(home / "node.json", backup)
        on_disk = json.loads((home / "node.json").read_text(encoding="utf-8"))
        on_disk["llama_server"] = str(new_exe)
        (home / "node.json").write_text(json.dumps(on_disk, indent=2) + "\n", encoding="utf-8")
    except Exception as e:
        return finish("abort", f"{type(e).__name__}: {e}"[:200])
    finally:
        engine.stop()
        off.unlink(missing_ok=True)
    restart(home)
    st = at.wait_loaded(cfg, home, float(cfg.get("resume_seconds", 180)) + float(up.get("load_timeout_s", 120)),
                        status, sleep)
    if st is None:
        shutil.copy2(backup, home / "node.json")
        restart(home)
        return finish("rollback", f"node did not load with {latest['tag']}; previous engine restored", **more)
    return finish("promote", verdict["why"], **more)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="watch")
    ap.add_argument("command", choices=["check", "trial"])
    ap.add_argument("--home", default=str(HERE))
    ap.add_argument("--config", help="check: JSON with components (see the self-model's upgrade config)")
    ap.add_argument("--now", action="store_true")
    a = ap.parse_args(argv)
    if a.command == "trial":
        print(json.dumps(trial(Path(a.home), now=a.now), indent=1))
        return 0
    cfg = json.loads(Path(a.config).read_text(encoding="utf-8")) if a.config else {"components": {
        "llama.cpp": {"current": os.environ.get("LLAMA_CURRENT", "")}, "forgejo": {"current": ""}}}
    for rec in check(cfg, {}):
        print(json.dumps(rec))
    return 0


if __name__ == "__main__":
    sys.exit(main())
