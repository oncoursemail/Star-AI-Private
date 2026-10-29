"""Star tunes herself: a nightly, bounded, measured autotuner for one Litha GPU node (runs ON the node PC).

    python autotune.py run [--home DIR] [--now] [--dry-run] [--max-minutes 25]    (copied next to node_agent.py)
    python autotune.py rollback [--home DIR]                                       restore the last backup
    python autotune.py candidates [--home DIR]                                     show tonight's candidates

What it does, in order (every step can stop the run; a stop always gives the card back):
  1. Gate: inside the night window (local hours `hours`, default 01-06), node state idle with nothing in flight, no OFF
     file (someone parked the node: a bench lane, the owner), no other autotune running.
  2. Parks the node (OFF file: the node unloads at once), then measures the CURRENT config at the ladder step the node
     would load now, with a fixed benchmark (BENCH, temperature 0) and a fixed mini-eval (EVAL, checkable answers).
  3. Tries at most `max_candidates` single-knob changes (threads, micro-batch, draft depth, KV cache type), rotated
     night by night so every knob gets its turn. Stops early if another program starts using the card.
  4. Measures the current config again (drift), and keeps the fastest candidate only if it beats the mean baseline by
     `min_gain` (3%) with no mini-eval loss and the node's free-memory reserve kept.
  5. Writes node.json (backup first), restarts the node, waits for it to load, and ROLLS BACK automatically if it does
     not come back idle+loaded at >= 80% of the baseline speed.
  6. Logs to logs/autotune.jsonl and reports to the self-model (POST <router>/mesh/self/report, mesh token).
Owns: node.json's llama_args / step_args on this PC only. Never touches brain1, the router's mesh.json or STAR's app.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
TUNE_PORT = 18197
DEFAULTS = {"hours": [1, 6], "max_candidates": 5, "min_gain": 0.03, "max_minutes": 25, "verify_ratio": 0.8,
            "load_timeout_s": 120}

BENCH = [   # fixed speed prompts (generation-heavy, varied)
    "Explain in about 120 words how a Roblox RemoteEvent works and one common mistake.",
    "Write a short Luau ModuleScript with a function that shuffles a table in place.",
    "List eight ideas for a cozy farming game, one line each.",
    "Tell a friendly 100-word story about a robot learning to paint.",
]
EVAL = [    # fixed mini-eval: checkable answers, temperature 0
    ("What is 17 * 23? Reply with only the number.", r"\b391\b"),
    ("What is the capital of Australia? One word.", r"(?i)canberra"),
    ("Spell the word 'planet' backwards. Reply with only the result.", r"(?i)tenalp"),
    ("How many legs does a spider have? Reply with only the number.", r"(?i)\b8\b|eight"),
    ("Write a Luau function named add that takes a and b and returns their sum. Only code.",
     r"function\s+add\s*\(\s*a\s*,\s*b\s*\)[\s\S]*return\s+a\s*\+\s*b"),
    ("In Roblox Luau, which service gives you the list of players? Reply with the service name only.", r"\bPlayers\b"),
    ("Convert 3 kilometers to meters. Reply with only the number.", r"\b3,?000\b"),
    ("What is the next number: 2, 4, 8, 16, ...? Reply with only the number.", r"\b32\b"),
    ("Which planet is known as the Red Planet? One word.", r"(?i)mars"),
    ("Is 91 a prime number? Answer yes or no first.", r"(?i)^\W*no\b"),
]


# ---------- config knobs (pure) ----------

def get_arg(args: list, flag: str):
    args = [str(a) for a in args]
    return args[args.index(flag) + 1] if flag in args[:-1] else None


def set_arg(args: list, flag: str, value) -> list:
    args = [str(a) for a in args]
    if flag in args[:-1]:
        args[args.index(flag) + 1] = str(value)
    else:
        args += [flag, str(value)]
    return args


def step_name(cfg: dict, step: int | None) -> str | None:
    ladder = cfg.get("ngl_ladder") or []
    if step is None or not 0 <= step < len(ladder) or len(ladder[step]) < 3:
        return None
    return ladder[step][2] if isinstance(ladder[step][2], str) else None


def candidates(cfg: dict, step: int | None, cores: int | None = None, night: int = 0, limit: int = 5) -> list[dict]:
    """Single-knob changes of the current config: [{"name", "knob", "from", "to", "config"}], at most `limit`, rotated
    by `night` so each knob is tried over a few nights. Bounded values only."""
    args = [str(a) for a in cfg.get("llama_args") or []]
    cores = cores or max(2, (os.cpu_count() or 4) // 2)
    out: list[dict] = []

    def add(knob, frm, to, new_cfg):
        out.append({"name": f"{knob} {frm}->{to}", "knob": knob, "from": frm, "to": to, "config": new_cfg})

    t = get_arg(args, "-t")
    if t and t.isdigit():
        for v in (int(t) - 2, int(t) + 2):
            if 2 <= v <= cores:
                add("threads", t, str(v), {**cfg, "llama_args": set_arg(args, "-t", v)})
    ub, b = get_arg(args, "-ub"), get_arg(args, "-b")
    if ub and ub.isdigit():
        ladder = [64, 128, 256, 512]
        i = ladder.index(int(ub)) if int(ub) in ladder else None
        for j in ((i - 1, i + 1) if i is not None else ()):
            if 0 <= j < len(ladder) and ladder[j] <= int(b or 2048):
                add("ubatch", ub, str(ladder[j]), {**cfg, "llama_args": set_arg(args, "-ub", ladder[j])})
    name = step_name(cfg, step)
    sargs = ((cfg.get("step_args") or {}).get(name) or []) if name else []
    n = get_arg(sargs, "--spec-draft-n-max")
    if n and n.isdigit():
        for v in (int(n) - 1, int(n) + 1):
            if 1 <= v <= 8:
                add("draft_n", n, str(v), {**cfg, "step_args": {**cfg["step_args"],
                                                                 name: set_arg(sargs, "--spec-draft-n-max", v)}})
    k = get_arg(args, "-ctk")
    if k in ("q4_0", "q8_0") and get_arg(args, "-ctv") == k:
        other = "q8_0" if k == "q4_0" else "q4_0"
        add("kv_type", k, other, {**cfg, "llama_args": set_arg(set_arg(args, "-ctk", other), "-ctv", other)})
    if not out:
        return []
    start = night % len(out)
    return (out[start:] + out[:start])[:limit]


def quality(answers: list[str]) -> int:
    return sum(1 for (_, rx), a in zip(EVAL, answers) if re.search(rx, (a or "").strip()))


def decide(base: list[dict], tried: list[dict], min_gain: float, reserve_mb: int) -> dict:
    """base: baseline measurements (start, end); tried: candidate results. -> {"decision", "winner"?, "why"}."""
    ok_base = [b for b in base if b.get("tok_s")]
    if not ok_base:
        return {"decision": "abort", "why": "baseline could not be measured"}
    base_tok = statistics.mean(b["tok_s"] for b in ok_base)
    base_q = min(b["quality"] for b in ok_base)
    good = []
    for c in tried:
        why = None
        if not c.get("tok_s"):
            why = c.get("error") or "did not run"
        elif c["quality"] < base_q:
            why = f"quality {c['quality']} < {base_q}"
        elif c.get("free_at_peak_mb") is not None and c["free_at_peak_mb"] < reserve_mb:
            why = f"only {c['free_at_peak_mb']} MB free at peak (< {reserve_mb})"
        elif c["tok_s"] < base_tok * (1 + min_gain):
            why = f"{c['tok_s']} tok/s is not {round(min_gain * 100)}% above {base_tok:.1f}"
        c["verdict"] = why or "better"
        if not why:
            good.append(c)
    if not good:
        return {"decision": "reject", "why": "no candidate beat the current config", "baseline_tok_s": round(base_tok, 1),
                "baseline_quality": base_q}
    win = max(good, key=lambda c: c["tok_s"])
    return {"decision": "keep", "winner": win, "baseline_tok_s": round(base_tok, 1), "baseline_quality": base_q,
            "why": f"{win['name']}: {win['tok_s']} vs {base_tok:.1f} tok/s, quality {win['quality']}/{base_q}"}


# ---------- measuring (llama-server on a private port) ----------

class Engine:
    """Starts llama-server for a config at a ladder step on 127.0.0.1:TUNE_PORT (node_agent builds the command)."""

    def __init__(self, home: Path):
        sys.path.insert(0, str(home))
        import node_agent   # noqa: PLC0415 - lives next to this file on the node PC
        self.na, self.home, self.proc = node_agent, home, None

    def gpu(self) -> dict | None:
        return self.na.read_gpu()

    def foreign_mb(self) -> int:
        """Card memory used by programs other than our tuning server (someone started a game, ...)."""
        tool = shutil.which("nvidia-smi") or r"C:\Windows\System32\nvidia-smi.exe"
        try:
            out = subprocess.run([tool, "--query-compute-apps=pid,used_memory", "--format=csv,noheader,nounits"],
                                 capture_output=True, text=True, timeout=5, creationflags=self.na.NO_WINDOW).stdout
        except (OSError, subprocess.SubprocessError):
            return 0
        own = self.proc.pid if self.proc else -1
        total = 0
        for line in out.splitlines():
            try:
                pid, mb = (int(x.strip()) for x in line.split(","))
            except ValueError:
                continue
            total += mb if pid != own else 0
        return total

    def start(self, cfg: dict, step: int | None) -> None:
        argv = self.na.llama_argv({**cfg, "internal_port": TUNE_PORT}, self.home, step=step)
        log = open(self.home / "logs" / "autotune-llama.log", "ab")
        self.proc = subprocess.Popen(argv, stdout=log, stderr=log, creationflags=self.na.NO_WINDOW)
        self.na.die_with_me(self.proc)
        t0 = time.time()
        while time.time() - t0 < 120:
            if self.proc.poll() is not None:
                raise RuntimeError(f"llama-server exited ({self.proc.returncode})")
            if self.na.health(TUNE_PORT):
                return
            time.sleep(0.5)
        raise RuntimeError("llama-server did not become healthy in 120 s")

    def chat(self, prompt: str, max_tokens: int) -> tuple[str, float | None]:
        body = {"messages": [{"role": "user", "content": prompt}], "max_tokens": max_tokens, "temperature": 0,
                "seed": 1, "cache_prompt": False}
        status, data = self.na.http_json("POST", f"http://127.0.0.1:{TUNE_PORT}/v1/chat/completions", body, timeout=180)
        text = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        return text, (data.get("timings") or {}).get("predicted_per_second")

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.kill()
            try:
                self.proc.wait(20)
            except subprocess.TimeoutExpired:
                pass
        self.proc = None


def measure(engine, cfg: dict, step: int | None) -> dict:
    gpu0 = engine.gpu() or {}
    engine.start(cfg, step)
    try:
        engine.chat("Say hello in five words.", 16)   # warm-up
        speeds, low = [], None
        for p in BENCH:
            _, tps = engine.chat(p, 160)
            if tps:
                speeds.append(tps)
            g = engine.gpu()
            if g:
                low = g.get("free") if low is None else min(low, g.get("free"))
        answers = [engine.chat(q, 80)[0] for q, _ in EVAL]
    finally:
        engine.stop()
    return {"tok_s": round(statistics.median(speeds), 1) if speeds else None, "quality": quality(answers),
            "free_at_peak_mb": low, "free_before_mb": gpu0.get("free"), "answers": [a[:80] for a in answers]}


# ---------- the nightly run ----------

def _now_hour() -> int:
    return datetime.datetime.now().hour


def _stamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime())


def node_status(cfg: dict, home: Path) -> dict:
    tok = _token(cfg, home)
    req = urllib.request.Request(f"http://127.0.0.1:{int(cfg.get('status_port', 8099))}/status",
                                 headers={"Authorization": f"Bearer {tok}"} if tok else {})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=5) as r:
        return json.loads(r.read())


def _token(cfg: dict, home: Path) -> str:
    p = cfg.get("token_file") or "~/.star/mesh_token"
    path = Path(os.path.expanduser(p))
    path = path if path.is_absolute() else home / path
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def open_hold(path: Path, now: float | None = None, within_s: float = 7200) -> str | None:
    """The GPU lab schedule (docs/agents/gpu-lab-schedule.md, owner PC): a lane's HOLD without a later FREE from the
    same lane, written in the last `within_s`, means someone else has the card -> its line; else None."""
    import calendar
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    now = now or time.time()
    held: dict[str, tuple[float, str]] = {}
    for line in lines:
        m = re.match(r"^(HOLD|FREE)\s+(\S+)\s+(\d{4}-\d\d-\d\dT\d\d:\d\dZ)", line)
        if not m:
            continue
        kind, lane, stamp = m.groups()
        ts = calendar.timegm(time.strptime(stamp, "%Y-%m-%dT%H:%MZ"))
        if kind == "HOLD":
            held[lane] = (ts, line)
        else:
            held.pop(lane, None)
    for lane, (ts, line) in held.items():
        if lane != "autotune" and now - ts < within_s:
            return line
    return None


def schedule_note(path: Path | None, text: str) -> None:
    if path and path.is_file():
        with open(path, "a", encoding="utf-8") as f:
            f.write(text.rstrip() + "\n")


def report(cfg: dict, home: Path, rec: dict) -> str:
    url = (cfg.get("router_url") or "").rstrip("/")
    tok = _token(cfg, home)
    if not url or not tok:
        return "no router/token"
    req = urllib.request.Request(url + "/mesh/self/report", data=json.dumps({"kind": "autotune", **rec}).encode(),
                                 headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=8) as r:
            return f"HTTP {r.status}"
    except OSError as e:
        return f"report failed: {type(e).__name__}"


def log(home: Path, rec: dict) -> None:
    (home / "logs").mkdir(exist_ok=True)
    with open(home / "logs" / "autotune.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def restart_node(home: Path) -> None:
    """Node re-reads node.json only at start: end it (its job object takes llama-server down) and start the task."""
    pid_file = home / "logs" / "node.pid"
    if os.name == "nt":
        if pid_file.is_file() and pid_file.read_text().strip().isdigit():
            subprocess.run(["taskkill", "/F", "/PID", pid_file.read_text().strip()], capture_output=True)
        subprocess.run(["schtasks", "/run", "/tn", "Litha mesh node"], capture_output=True)


def wait_loaded(cfg: dict, home: Path, timeout_s: float, status=node_status, sleep=time.sleep) -> dict | None:
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        try:
            st = status(cfg, home)
            m = (st.get("models") or [{}])[0]
            if st.get("state") == "idle" and m.get("loaded"):
                return st
        except (OSError, ValueError):
            pass
        sleep(5)
    return None


def run(home: Path, *, now: bool = False, dry_run: bool = False, max_minutes: float | None = None,
        engine=None, status=node_status, restart=restart_node, sleep=time.sleep) -> dict:
    sys.path.insert(0, str(home))
    import node_agent   # noqa: PLC0415
    cfg = node_agent.load_config(home)
    opts = {**DEFAULTS, **(cfg.get("autotune") or {})}
    max_minutes = max_minutes or opts["max_minutes"]
    rec: dict = {"ts": round(time.time(), 1), "node": cfg.get("node") or "node"}
    off, marker = home / "OFF", home / "AUTOTUNE_RUNNING"

    def finish(decision: str, why: str, **more) -> dict:
        rec.update({"decision": decision, "why": why, **more})
        log(home, rec)
        rec["report"] = report(cfg, home, {k: v for k, v in rec.items() if k not in ("tried",)} |
                               {"tried": [{k: c.get(k) for k in ("name", "tok_s", "quality", "verdict")}
                                          for c in rec.get("tried", [])]})
        return rec

    lo, hi = opts["hours"]
    if not now and not lo <= _now_hour() < hi:
        return finish("skip", f"outside the night window {lo:02d}-{hi:02d}h")
    if off.exists():
        return finish("skip", "node is parked (OFF file): someone else is using the card")
    if marker.exists() and time.time() - marker.stat().st_mtime < 3600:
        return finish("skip", "another autotune is running")
    sched = Path(os.path.expanduser(opts["schedule_file"])) if opts.get("schedule_file") else None
    hold = open_hold(sched) if sched else None
    if hold:
        return finish("skip", f"the GPU lab schedule has an open hold: {hold[:120]}")
    try:
        st = status(cfg, home)
    except (OSError, ValueError) as e:
        return finish("skip", f"node status unreadable ({type(e).__name__})")
    m = (st.get("models") or [{}])[0]
    if st.get("state") != "idle" or not m.get("loaded") or m.get("in_flight"):
        return finish("skip", f"node not idle ({st.get('state')}: {st.get('reason') or '-'})")
    engine = engine or Engine(home)
    deadline = time.time() + max_minutes * 60
    marker.write_text(str(os.getpid()))
    off.write_text("autotune\n")
    schedule_note(sched, f"HOLD autotune {_stamp()} planned end +{int(max_minutes)} min (nightly autotuner: node "
                         f"parked, candidates on 127.0.0.1:{TUNE_PORT}; restored at the end)")
    try:
        for _ in range(60):                       # node unloads at its next tick
            try:
                if status(cfg, home).get("state") == "off":
                    break
            except (OSError, ValueError):
                pass
            sleep(1)
        sleep(3)
        g = engine.gpu() or {}
        free = int(g.get("free") or 0)
        step = node_agent.pick_step(cfg, free)
        if step is not None and step < 0:
            return finish("abort", f"no ladder step fits {free} MB free")
        rec.update({"step": node_agent.step_label(cfg, step), "free_mb": free})
        night = datetime.date.today().toordinal()
        cands = candidates(cfg, step, night=night, limit=opts["max_candidates"])
        reserve = int(cfg.get("min_free_loaded_mb") or 0)
        base = [measure(engine, cfg, step)]
        tried = []
        for c in cands:
            if time.time() > deadline - 180:
                break
            if engine.foreign_mb() > 300:
                return finish("abort", "another program started using the card", tried=tried)
            try:
                res = measure(engine, c["config"], step)
            except (RuntimeError, OSError, ValueError) as e:
                res = {"tok_s": None, "quality": 0, "error": f"{type(e).__name__}: {e}"[:160]}
            tried.append({**res, "name": c["name"], "knob": c["knob"], "to": c["to"], "config": c["config"]})
        base.append(measure(engine, cfg, step))
        verdict = decide(base, tried, opts["min_gain"], reserve)
        rec["tried"] = [{k: v for k, v in t.items() if k != "config"} for t in tried]
        rec["baseline"] = [{k: b.get(k) for k in ("tok_s", "quality", "free_at_peak_mb")} for b in base]
        if verdict["decision"] != "keep" or dry_run:
            dec = verdict["decision"] if not dry_run or verdict["decision"] != "keep" else "would-keep"
            return finish(dec, verdict["why"], baseline_tok_s=verdict.get("baseline_tok_s"),
                          baseline_quality=verdict.get("baseline_quality"),
                          candidate=(verdict.get("winner") or {}).get("name"),
                          tok_s=(verdict.get("winner") or {}).get("tok_s"),
                          quality=(verdict.get("winner") or {}).get("quality"))
        win = verdict["winner"]
        backup = home / "autotune" / f"node-{time.strftime('%Y%m%d-%H%M%S')}.json"
        backup.parent.mkdir(exist_ok=True)
        shutil.copy2(home / "node.json", backup)
        on_disk = json.loads((home / "node.json").read_text(encoding="utf-8"))
        for key in ("llama_args", "step_args"):            # only the keys the autotuner owns
            if key in win["config"]:
                on_disk[key] = win["config"][key]
        (home / "node.json").write_text(json.dumps(on_disk, indent=2) + "\n", encoding="utf-8")
        rec.update({"backup": backup.name, "candidate": win["name"], "tok_s": win["tok_s"], "quality": win["quality"],
                    "baseline_tok_s": verdict["baseline_tok_s"], "baseline_quality": verdict["baseline_quality"]})
    except Exception as e:   # any failure while parked: give the card back, log it, change nothing
        return finish("abort", f"{type(e).__name__}: {e}"[:200])
    finally:
        engine.stop()
        off.unlink(missing_ok=True)
        marker.unlink(missing_ok=True)
        schedule_note(sched, f"FREE autotune {_stamp()} (node unparked)")
    # applied: restart the node with the new config and check it really comes back
    restart(home)
    st = wait_loaded(cfg, home, float(cfg.get("resume_seconds", 180)) + opts["load_timeout_s"], status, sleep)
    got = ((st or {}).get("models") or [{}])[0].get("tok_s") if st else None
    if st is None or (got and got < opts["verify_ratio"] * rec["baseline_tok_s"]):
        shutil.copy2(backup, home / "node.json")
        restart(home)
        return finish("rollback", f"node did not come back well with {rec['candidate']} "
                                  f"({'not loaded' if st is None else f'{got} tok/s'}); previous node.json restored")
    return finish("keep", verdict["why"] + f"; node back at {got} tok/s")


def rollback(home: Path) -> str:
    backups = sorted((home / "autotune").glob("node-*.json"))
    if not backups:
        return "no backup"
    shutil.copy2(backups[-1], home / "node.json")
    restart_node(home)
    log(home, {"ts": round(time.time(), 1), "decision": "manual-rollback", "backup": backups[-1].name})
    return f"restored {backups[-1].name}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="autotune")
    ap.add_argument("command", choices=["run", "rollback", "candidates"])
    ap.add_argument("--home", default=str(HERE))
    ap.add_argument("--now", action="store_true", help="ignore the night window")
    ap.add_argument("--dry-run", action="store_true", help="measure and decide, change nothing")
    ap.add_argument("--max-minutes", type=float)
    a = ap.parse_args(argv)
    home = Path(a.home)
    if a.command == "rollback":
        print(rollback(home))
        return 0
    if a.command == "candidates":
        sys.path.insert(0, str(home))
        import node_agent   # noqa: PLC0415
        cfg = node_agent.load_config(home)
        g = node_agent.read_gpu() or {}
        step = node_agent.pick_step(cfg, int(g.get("free") or 99999))
        for c in candidates(cfg, step, night=datetime.date.today().toordinal(),
                            limit=({**DEFAULTS, **(cfg.get("autotune") or {})})["max_candidates"]):
            print(c["name"])
        return 0
    rec = run(home, now=a.now, dry_run=a.dry_run, max_minutes=a.max_minutes)
    print(json.dumps({k: rec.get(k) for k in ("node", "decision", "why", "step", "candidate", "tok_s",
                                              "baseline_tok_s", "report")}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
