"""The collector: turns the host gates' streams, the brain router, the forge API and the PC agent's pushes into stored
time series and one live state document (GET /api/state).

It never takes the quiet lock, never asks an unloaded model anything (that would load it), and every source reports
its own freshness: missing data is shown as missing, never filled in.
"""
from __future__ import annotations

import json
import subprocess
import threading
import time
import urllib.parse
import urllib.request

HELPERS = ("star-embed", "star-embed-ft1", "star-rerank")
STALE_S = 30
CPU_FIELDS = 8


# ------------------------------------------------------------------------------------------------ pure helpers

def cpu_percent(before: list[int] | None, after: list[int] | None) -> float | None:
    """Busy share between two /proc/stat cpu lines (idle + iowait count as idle)."""
    if not before or not after or len(before) < 5 or len(after) < 5:
        return None
    total = sum(after[:CPU_FIELDS]) - sum(before[:CPU_FIELDS])
    idle = (after[3] + after[4]) - (before[3] + before[4])
    if total <= 0:
        return None
    return round(100.0 * (total - idle) / total, 1)


def rate(before: float | None, after: float | None, seconds: float) -> float | None:
    if before is None or after is None or seconds <= 0 or after < before:
        return None                       # a counter reset (reboot, NIC reset) gives no rate, not a negative one
    return (after - before) / seconds


def cpu_temperature(temps: dict) -> float | None:
    """Hottest CPU sensor: AMD k10temp Tctl/Tccd, Intel coretemp Package/Core."""
    vals = [v for k, v in temps.items() if k.startswith(("k10temp/", "coretemp/", "zenpower/", "cpu_thermal/"))]
    return max(vals) if vals else None


def parse_prometheus(text: str) -> dict[str, float]:
    """Unlabelled llama.cpp metrics -> {name without the llamacpp: prefix: value}."""
    out = {}
    for line in text.splitlines():
        if not line or line.startswith("#") or "{" in line:
            continue
        name, _, value = line.partition(" ")
        try:
            out[name.removeprefix("llamacpp:")] = float(value)
        except ValueError:
            continue
    return out


def router_models(data) -> list[dict]:
    """GET /v1/models of the llama.cpp router -> [{id, status, port, parallel, ctx}] (args parsed, nothing printed)."""
    out = []
    for row in (data.get("data") or []) if isinstance(data, dict) else []:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            continue
        status = row.get("status") if isinstance(row.get("status"), dict) else {}
        args = status.get("args") if isinstance(status.get("args"), list) else []

        def arg(flag):
            return args[args.index(flag) + 1] if flag in args and args.index(flag) + 1 < len(args) else None
        model = {"id": row["id"], "status": status.get("value") or "loaded", "port": arg("--port"),
                 "parallel": _int(arg("--parallel")), "ctx": _int(arg("--ctx-size")),
                 "cache_ram_mib": _int(arg("--cache-ram")), "spec": arg("--spec-type"),
                 "helper": row["id"] in HELPERS or "--embeddings" in args or "--reranking" in args}
        out.append(model)
    return out


def slot_summary(slots) -> dict:
    rows = [s for s in slots if isinstance(s, dict)] if isinstance(slots, list) else []
    return {"total": len(rows), "busy": sum(1 for s in rows if s.get("is_processing")),
            "ctx": max((s.get("n_ctx") or 0 for s in rows), default=0)}


def model_rates(after: dict) -> dict:
    """What /metrics can honestly say: requests running and waiting now, and since the model loaded the share of
    drafted tokens accepted and of prompt tokens served from the prompt cache. (Token counters only move when a
    request finishes, so live speed comes from the journal's progress lines instead.)"""
    out = {"processing": after.get("requests_processing"), "deferred": after.get("requests_deferred")}
    cached, prompt = after.get("prompt_tokens_cached_total"), after.get("prompt_tokens_total")
    if cached is not None and prompt:
        out["cache_share_total"] = round(cached / (cached + prompt), 3)
    acc, draft = after.get("spec_decode_num_accepted_tokens_total"), after.get("spec_decode_num_draft_tokens_total")
    if acc is not None and draft:
        out["draft_accept_total"] = round(acc / draft, 3)
    return out


def backup_alerts(row: dict, now: float) -> list[tuple[str, str]]:
    """(level, text) for one backup set: stale success, an error newer than the last success, an old restore check,
    a repository near its budget."""
    out = []
    name = row.get("set", "?")
    limit = {"hourly": 2.5 * 3600, "daily": 26 * 3600}.get(row.get("schedule", ""), 26 * 3600)
    last = _ts(row.get("last_success_utc"))
    if row.get("error"):
        out.append(("warn", f"backup {name}: {row['error']}"))
    elif last is None:
        out.append(("warn", f"backup {name}: no successful backup recorded"))
    elif now - last > limit:
        out.append(("warn", f"backup {name}: last success {int((now - last) / 3600)} h ago"))
    err = row.get("last_error") or {}
    err_at = _ts(err.get("at"))
    # an error is current only if nothing of the same kind succeeded after it (a later retention clears a retention
    # failure, a later verification clears a verify failure)
    later = {"retention": row.get("last_retention_utc"),
             "verify": (row.get("last_restore_verification") or {}).get("verified_utc"),
             "baseline": (row.get("baseline_verification") or {}).get("verified_utc")}.get(str(err.get("action")))
    cleared = max([t for t in (last, _ts(later)) if t is not None], default=None)
    if err_at and (cleared is None or err_at > cleared):
        out.append(("warn", f"backup {name}: {err.get('action', 'run')} failed: {err.get('message', '')[:80]}"))
    ver = _ts((row.get("last_restore_verification") or {}).get("verified_utc"))
    if row.get("last_restore_verification") is not None and (ver is None or now - ver > 2 * 86400):
        out.append(("warn", f"backup {name}: restore check older than 2 days"))
    used, budget = row.get("repository_bytes"), row.get("max_repository_bytes")
    if used and budget and used / budget >= 0.85:
        out.append(("warn", f"backup {name}: repository at {round(100 * used / budget)} % of its budget"))
    return out


def _ts(text) -> float | None:
    if not isinstance(text, str) or not text:
        return None
    from datetime import datetime
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------------------------------------------ machine state

class Machine:
    """One machine's latest numbers and the rates between its last two samples."""

    def __init__(self, conf: dict):
        self.conf = conf
        self.id = conf["id"]
        self.prev: dict | None = None
        self.state: dict = {"id": self.id, "name": conf.get("name", self.id), "role": conf.get("role", ""),
                            "kind": conf.get("kind", "server"), "online": False, "last_seen": None}
        if conf.get("pending"):
            self.state["pending"] = conf["pending"]
        self.slow: dict = {}
        self.inventory: list = []
        self.error = ""

    def on_sample(self, row: dict) -> dict[str, float | None]:
        """Update the state from one gate sample; returns the values to store."""
        t = float(row.get("t") or time.time())
        prev, self.prev = self.prev, row
        dt = t - float(prev["t"]) if prev else 0.0
        st = self.state
        st.update(online=True, last_seen=t, ncpu=row.get("ncpu"), load=row.get("load"))
        values: dict[str, float | None] = {}
        mem = row.get("mem") or {}
        if mem.get("total"):
            used = mem["total"] - mem.get("available", 0)
            st["mem"] = {"total": mem["total"], "used": used, "pct": round(100 * used / mem["total"], 1),
                         "swap_total": mem.get("swap_total"), "swap_used": (mem.get("swap_total") or 0)
                         - (mem.get("swap_free") or 0)}
            values.update({"mem_used": used, "mem_pct": st["mem"]["pct"]})
        fs = row.get("fs") or {}
        st["fs"] = [{"mount": m, "total": v[0], "used": v[1],
                     "pct": round(100 * v[1] / (v[1] + v[2]), 1) if len(v) > 2 and v[1] + v[2] else None}
                    for m, v in fs.items()]
        for f in st["fs"]:
            values[f"fs_pct:{f['mount']}"] = f["pct"]
        temps = row.get("temps") or {}
        st["temps"] = temps
        st["temp_cpu"] = cpu_temperature(temps)
        values["temp_cpu"] = st["temp_cpu"]
        st["psi_cpu"] = row.get("psi_cpu")
        if row.get("load"):
            values["load1"] = row["load"][0]
        if prev and dt > 0:
            st["cpu"] = cpu_percent(prev.get("cpu"), row.get("cpu"))
            values["cpu"] = st["cpu"]
            rx = tx = 0.0
            seen = False
            for nic, (r, x) in (row.get("net") or {}).items():
                old = (prev.get("net") or {}).get(nic)
                if old:
                    a, b = rate(old[0], r, dt), rate(old[1], x, dt)
                    if a is not None and b is not None:
                        rx, tx, seen = rx + a, tx + b, True
            if seen:
                st["net"] = {"rx": round(rx), "tx": round(tx)}
                values.update({"net_rx": rx, "net_tx": tx})
            dr = dw = 0.0
            seen = False
            for disk, (r, w) in (row.get("disk") or {}).items():
                old = (prev.get("disk") or {}).get(disk)
                if old:
                    a, b = rate(old[0], r, dt), rate(old[1], w, dt)
                    if a is not None and b is not None:
                        dr, dw, seen = dr + a * 512, dw + b * 512, True
            if seen:
                st["disk_io"] = {"read": round(dr), "write": round(dw)}
                values.update({"disk_r": dr, "disk_w": dw})
            cts = []
            for name, c in sorted((row.get("ct") or {}).items()):
                old = (prev.get("ct") or {}).get(name) or {}
                cores = rate(old.get("cpu_usec"), c.get("cpu_usec"), dt)
                cores = round(cores / 1e6, 3) if cores is not None else None
                cts.append({"name": name, "cores": cores, "mem": c.get("mem"), "mem_max": c.get("mem_max")})
                values[f"ct:{name}:cores"] = cores
                values[f"ct:{name}:mem"] = c.get("mem")
            st["containers"] = cts
        if "slow" in row:
            self.slow = row["slow"]
            st["procs"] = self.slow.get("procs") or []
        if "inventory" in row:
            self.inventory = row["inventory"]
        if self.inventory:
            limits = {i.get("name"): i for i in self.inventory}
            for c in st.get("containers", []):
                inv = limits.get(c["name"]) or {}
                c["limits"] = inv.get("limits") or {}
                c["status"] = inv.get("status")
            st["instances"] = [{"name": i.get("name"), "status": i.get("status"), "type": i.get("type"),
                                "limits": i.get("limits") or {}} for i in self.inventory]
        return {f"{self.id}.{k}": v for k, v in values.items()}

    def check_stale(self, now: float) -> None:
        if self.state["last_seen"] and now - self.state["last_seen"] > STALE_S:
            self.state["online"] = False


# ------------------------------------------------------------------------------------------------ the collector

class Collector:
    def __init__(self, conf: dict, store, runner=None, clock=time.time):
        self.conf, self.store, self.runner, self.clock = conf, store, runner, clock
        self.machines = {m["id"]: Machine(m) for m in conf.get("machine", [])}
        self.sources: dict[str, dict] = {}
        self.star: dict = {"brains": {}, "models": [], "requests": []}
        self.dev: dict = {}
        self.pc_extra: dict = {}
        self.forge_backups: dict | None = None
        self.lock = threading.Lock()
        self.stop = threading.Event()
        last = store.get("state")
        if isinstance(last, dict):          # last known state after a restart, marked stale until fresh data lands
            self.dev = last.get("dev") or {}
            self.pc_extra = {"dev_pc": last.get("dev_pc")} if last.get("dev_pc") else {}

    def source(self, name: str, ok: bool, error: str = "") -> None:
        row = self.sources.setdefault(name, {"name": name, "last_ok": None, "error": ""})
        if ok:
            row["last_ok"], row["error"] = self.clock(), ""
        else:
            row["error"] = error[:160]

    # -------------------------------------------------------------- host gate streams
    def on_host_line(self, machine_id: str, line: str) -> None:
        try:
            row = json.loads(line)
        except ValueError:
            return
        if not isinstance(row, dict) or row.get("kind") != "sample":
            return
        m = self.machines.get(machine_id)
        if m is None:
            return
        with self.lock:
            values = m.on_sample(row)
            slow = row.get("slow") or {}
            if slow.get("facts"):
                self.star["brains"][machine_id] = {"facts": slow["facts"], "at": self.clock()}
            if slow.get("backups"):
                self.store.put(f"backups:{machine_id}", slow["backups"])
            if slow.get("runners") is not None:
                self.store.put(f"runners:{machine_id}", slow["runners"])
            if slow.get("timers"):
                self.store.put(f"timers:{machine_id}", slow["timers"])
            if row.get("forge_backups"):
                self.forge_backups = row["forge_backups"]
                self.store.put("forge_backups", row["forge_backups"])
            reqs = row.get("reqs") or []
            ports = {mod.get("port"): mod["id"] for mod in self.star.get("models", []) if mod.get("port")}

            def model_of(r):
                return ports.get(r.get("port")) or self.conf.get("brain_models", {}).get(machine_id) or (
                    f"port {r.get('port')}" if r.get("port") else "model")
            if "gen" in row:                    # slots generating right now, with their live tokens/s
                gen = [{"machine": machine_id, "model": model_of(g), "slot": g.get("slot"), "tps": g.get("tg3"),
                        "n_gen": g.get("n_gen"), "t": g.get("t")} for g in row["gen"] if isinstance(g, dict)]
                self.star.setdefault("gen", {})[machine_id] = gen
                totals: dict = {}
                for g in gen:
                    totals[g["model"]] = totals.get(g["model"], 0.0) + (g["tps"] or 0.0)
                for model, tps in totals.items():
                    values[f"llm.{machine_id}.{model}.gen_tps"] = tps
            for r in reqs:
                r["model"] = model_of(r)
                if r.get("eval_ms") and r.get("eval_tokens"):
                    values[f"llm.{machine_id}.{r['model']}.tps"] = r["eval_tokens"] * 1000.0 / r["eval_ms"]
                if r.get("prompt_ms") is not None:
                    values[f"llm.{machine_id}.{r['model']}.prompt_ms"] = r["prompt_ms"]
        if reqs:
            self.store.add_requests(machine_id, reqs)
        self.store.add(row.get("t") or self.clock(), values)
        self.source(f"gate:{machine_id}", True)

    def run_host(self, machine: dict, ssh_base: list[str]) -> None:
        """Keep one `stream` connection open per host; reconnect with back-off."""
        wait = 5.0
        while not self.stop.is_set():
            started = self.clock()
            try:
                proc = subprocess.Popen([*ssh_base, machine["ssh"], "stream"], stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, text=True, bufsize=1)
                for line in proc.stdout:
                    self.on_host_line(machine["id"], line)
                    if self.stop.is_set():
                        break
                proc.terminate()
                err = (proc.stderr.read() or "").strip().splitlines()
                self.source(f"gate:{machine['id']}", False, f"stream ended: {err[-1] if err else 'no output'}")
            except OSError as exc:
                self.source(f"gate:{machine['id']}", False, f"ssh failed: {type(exc).__name__}")
            wait = 5.0 if self.clock() - started > 120 else min(wait * 2, 120.0)
            self.stop.wait(wait)

    # -------------------------------------------------------------- brain router
    def poll_brain(self, fetch) -> None:
        """One look at the router: model list, then slots + metrics of LOADED chat models only."""
        brain = self.conf.get("brain") or {}
        now = self.clock()
        try:
            models = router_models(json.loads(fetch("/v1/models")))
        except (OSError, ValueError) as exc:
            self.source("brain", False, f"router: {type(exc).__name__}")
            return
        rows, values = [], {}
        for mod in models:
            row = dict(mod)
            if mod["status"] == "loaded" and not mod["helper"]:
                q = urllib.parse.quote(mod["id"])
                try:
                    row["slots"] = slot_summary(json.loads(fetch("/slots?model=" + q)))
                    row["live"] = model_rates(parse_prometheus(fetch("/metrics?model=" + q).decode("utf-8", "replace")))
                    m = brain.get("machine", "brain1")
                    values[f"llm.{m}.{mod['id']}.busy"] = row["slots"]["busy"]
                    values[f"llm.{m}.{mod['id']}.deferred"] = row["live"].get("deferred")
                except (OSError, ValueError) as exc:
                    row["error"] = type(exc).__name__
            rows.append(row)
        with self.lock:
            self.star["models"] = rows
            self.star["models_at"] = now
        self.store.add(now, values)
        self.source("brain", True)

    def brain_fetcher(self):
        brain = self.conf.get("brain") or {}
        key = _read_secret(brain.get("key_file"))

        def fetch(path: str) -> bytes:
            req = urllib.request.Request(brain["url"].rstrip("/") + path)
            if key:
                req.add_header("Authorization", "Bearer " + key)
            try:
                with urllib.request.urlopen(req, timeout=4) as reply:
                    return reply.read(2_000_000)
            except (OSError, ValueError) as exc:
                raise OSError(type(exc).__name__) from None
        return fetch

    # -------------------------------------------------------------- forge
    def poll_forge(self, get) -> None:
        forge = self.conf.get("forge") or {}
        org = forge.get("org", "metallic")
        try:
            repos = get(f"/orgs/{org}/repos?limit=50")
            out = {"repos": [], "prs": [], "releases": [], "runs": [], "milestones": []}
            for r in repos:
                name = r["name"]
                out["repos"].append({"name": name, "open_issues": r.get("open_issues_count"),
                                     "open_prs": r.get("open_pr_counter"), "releases": r.get("release_counter"),
                                     "size_kb": r.get("size"), "updated": r.get("updated_at"),
                                     "branch": r.get("default_branch"), "url": r.get("html_url")})
                for pr in get(f"/repos/{org}/{name}/pulls?state=open&limit=20&sort=recentupdate"):
                    out["prs"].append({"repo": name, "number": pr.get("number"), "title": str(pr.get("title", ""))[:140],
                                       "draft": bool(pr.get("draft")), "updated": pr.get("updated_at"),
                                       "author": (pr.get("user") or {}).get("login"), "url": pr.get("html_url")})
                for rel in get(f"/repos/{org}/{name}/releases?limit=3"):
                    out["releases"].append({"repo": name, "tag": rel.get("tag_name"), "name": rel.get("name"),
                                            "published": rel.get("published_at"), "url": rel.get("html_url")})
                for ms in get(f"/repos/{org}/{name}/milestones?state=all&limit=20"):
                    out["milestones"].append({"repo": name, "title": ms.get("title"), "open": ms.get("open_issues"),
                                              "closed": ms.get("closed_issues"), "state": ms.get("state"),
                                              "due": ms.get("due_on")})
                runs = get(f"/repos/{org}/{name}/actions/tasks?limit=8")
                for run in (runs.get("workflow_runs") or []) if isinstance(runs, dict) else []:
                    out["runs"].append({"repo": name, "name": run.get("name"), "status": run.get("status"),
                                        "branch": run.get("head_branch"), "started": run.get("run_started_at"),
                                        "updated": run.get("updated_at"), "url": run.get("url")})
            out["runners"] = [{"name": r.get("name"), "status": r.get("status"), "version": r.get("version"),
                               "labels": r.get("labels")} for r in get("/admin/actions/runners")]
            out["prs"].sort(key=lambda p: p.get("updated") or "", reverse=True)
            out["runs"].sort(key=lambda p: p.get("updated") or "", reverse=True)
            out["at"] = self.clock()
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self.source("forge", False, f"forge API: {type(exc).__name__}")
            return
        with self.lock:
            self.dev = out
        self.source("forge", True)

    def forge_getter(self):
        forge = self.conf.get("forge") or {}
        token = _read_secret(forge.get("token_file"))
        base = forge.get("url", "").rstrip("/") + "/api/v1"

        def get(path: str):
            req = urllib.request.Request(base + path, headers={"Authorization": "token " + token} if token else {})
            try:
                with urllib.request.urlopen(req, timeout=8) as reply:
                    return json.loads(reply.read(4_000_000))
            except (OSError, ValueError) as exc:
                raise OSError(type(exc).__name__) from None
        return get

    # -------------------------------------------------------------- the PC agent
    def on_pc_push(self, payload: dict) -> list[dict]:
        """A push from the PC agent; returns pending commands for it."""
        m = self.machines.get("pc")
        if m is None or not isinstance(payload, dict):
            return []
        s = payload.get("sample") if isinstance(payload.get("sample"), dict) else {}
        now = self.clock()
        values: dict[str, float | None] = {}
        with self.lock:
            st = m.state
            prev, m.prev = m.prev, {"t": now, **s}
            dt = now - prev["t"] if prev else 0
            st.update(online=True, last_seen=now, ncpu=s.get("ncpu"))
            if prev and dt > 0 and s.get("cpu") and prev.get("cpu"):
                busy = (s["cpu"][0] - prev["cpu"][0])
                total = (s["cpu"][1] - prev["cpu"][1])
                st["cpu"] = round(100 * busy / total, 1) if total > 0 else None
                values["pc.cpu"] = st["cpu"]
            if s.get("mem"):
                total, avail = s["mem"]
                st["mem"] = {"total": total, "used": total - avail, "pct": round(100 * (total - avail) / total, 1)}
                values.update({"pc.mem_used": total - avail, "pc.mem_pct": st["mem"]["pct"]})
            st["fs"] = [{"mount": d["mount"], "total": d["total"], "used": d["used"],
                         "pct": round(100 * d["used"] / d["total"], 1) if d.get("total") else None}
                        for d in s.get("fs", []) if isinstance(d, dict)]
            for f in st["fs"]:
                values[f"pc.fs_pct:{f['mount']}"] = f["pct"]
            if prev and dt > 0 and s.get("net") and prev.get("net"):
                rx, tx = rate(prev["net"][0], s["net"][0], dt), rate(prev["net"][1], s["net"][1], dt)
                if rx is not None and tx is not None:
                    st["net"] = {"rx": round(rx), "tx": round(tx)}
                    values.update({"pc.net_rx": rx, "pc.net_tx": tx})
            gpu = s.get("gpu") if isinstance(s.get("gpu"), dict) else None
            st["gpu"] = gpu
            if gpu:
                values.update({"pc.gpu_util": gpu.get("util"), "pc.gpu_mem": gpu.get("mem_used"),
                               "pc.gpu_temp": gpu.get("temp"), "pc.gpu_power": gpu.get("power")})
                st["temp_cpu"] = None
                st["temps"] = {"gpu": gpu.get("temp")} if gpu.get("temp") is not None else {}
            st["services"] = s.get("services") or {}
            if isinstance(payload.get("dev"), dict):
                self.pc_extra["dev_pc"] = {**payload["dev"], "at": now}
            if isinstance(payload.get("backup"), dict):
                self.pc_extra["backup_pc"] = payload["backup"]
        self.store.add(now, values)
        self.source("pc-agent", True)
        if self.runner:
            self.runner.pc_results(payload.get("results") or [])
            return self.runner.pc_commands()
        return []

    # -------------------------------------------------------------- state and alerts
    def alerts(self, now: float) -> list[dict]:
        out = []

        def add(level, where, text):
            out.append({"level": level, "where": where, "text": text})
        for m in self.machines.values():
            st = m.state
            if st.get("pending"):
                continue
            if not st["online"]:
                add("crit" if st["last_seen"] else "warn", m.id,
                    f"{st['name']} is not reporting" + (f" (last data {int(now - st['last_seen'])} s ago)"
                                                         if st["last_seen"] else ""))
                continue
            t = st.get("temp_cpu")
            if t is not None and t >= 85:
                add("crit" if t >= 95 else "warn", m.id, f"{st['name']} CPU at {t:.0f} °C")
            for f in st.get("fs", []):
                if f.get("pct") is not None and f["pct"] >= 90:
                    add("crit" if f["pct"] >= 95 else "warn", m.id, f"{st['name']} disk {f['mount']} {f['pct']:.0f} % full")
            mem = st.get("mem") or {}
            if mem.get("pct") and mem["pct"] >= 95:
                add("warn", m.id, f"{st['name']} memory {mem['pct']:.0f} % used")
            for c in st.get("containers", []):
                if c.get("mem") and c.get("mem_max") and c["mem"] / c["mem_max"] >= 0.9:
                    add("warn", m.id, f"{c['name']} on {st['name']} at {round(100 * c['mem'] / c['mem_max'])} % of its "
                                      "memory limit")
        for mid, brain in self.star["brains"].items():
            facts = brain.get("facts") or {}
            name = self.machines[mid].state["name"] if mid in self.machines else mid
            for svc in facts.get("services", []):
                if svc.get("active") == "failed":
                    add("crit", mid, f"{svc['unit']} failed on {name}")
            wd = facts.get("knowledge_watchdog")
            if wd and not wd.get("ok"):
                add("warn", mid, f"knowledge watchdog on {name}: not ok ({wd.get('failures', 0)} failures)")
        for mid in self.machines:
            for row in self.store.get(f"backups:{mid}") or []:
                for level, text in backup_alerts(row, now):
                    add(level, "backups", text)
            for r in self.store.get(f"runners:{mid}") or []:
                if r.get("state") != "active":
                    add("warn", "dev", f"runner {r['runner']} is {r['state']}")
        for name, src in self.sources.items():
            if src["error"] and (src["last_ok"] is None or now - src["last_ok"] > 120):
                add("warn", "sources", f"{name}: {src['error']}")
        order = {"crit": 0, "warn": 1, "info": 2}
        return sorted(out, key=lambda a: order.get(a["level"], 3))

    def state(self) -> dict:
        now = self.clock()
        with self.lock:
            for m in self.machines.values():
                m.check_stale(now)
            backups = []
            for mid in self.machines:
                for row in self.store.get(f"backups:{mid}") or []:
                    backups.append({**row, "machine": mid})
            runners = []
            for mid in self.machines:
                for row in self.store.get(f"runners:{mid}") or []:
                    runners.append({**row, "machine": mid})
            doc = {"generated": now,
                   "machines": [m.state for m in self.machines.values()],
                   "star": {"brains": {k: {"at": v["at"], **(v.get("facts") or {})}
                                       for k, v in self.star["brains"].items()},
                            "models": self.star.get("models", []), "models_at": self.star.get("models_at"),
                            "generating": [g for rows in self.star.get("gen", {}).values() for g in rows],
                            "requests": self.store.requests(now - 3600, 40)},
                   "dev": self.dev, "dev_pc": self.pc_extra.get("dev_pc"), "runners": runners,
                   "backups": backups, "backup_pc": self.pc_extra.get("backup_pc"),
                   "forge_backups": self.forge_backups or self.store.get("forge_backups"),
                   "timers": {mid: self.store.get(f"timers:{mid}") or [] for mid in self.machines},
                   "sources": list(self.sources.values())}
        doc["alerts"] = self.alerts(now)
        return doc

    # -------------------------------------------------------------- loops
    def start(self, ssh_base: list[str]) -> list[threading.Thread]:
        threads = []
        for m in self.conf.get("machine", []):
            if m.get("ssh"):
                threads.append(threading.Thread(target=self.run_host, args=(m, ssh_base), daemon=True,
                                                name=f"gate-{m['id']}"))
        threads.append(threading.Thread(target=self._loop, daemon=True, name="pollers"))
        for t in threads:
            t.start()
        return threads

    def _loop(self) -> None:
        fetch = self.brain_fetcher() if self.conf.get("brain") else None
        get = self.forge_getter() if self.conf.get("forge") else None
        brain_every = float((self.conf.get("brain") or {}).get("every", 10))
        last = {"brain": 0.0, "forge": 0.0, "rollup": 0.0, "state": 0.0}
        while not self.stop.is_set():
            now = self.clock()
            if fetch and now - last["brain"] >= brain_every:
                last["brain"] = now
                self.poll_brain(fetch)
            if get and now - last["forge"] >= 120:
                last["forge"] = now
                self.poll_forge(get)
            if now - last["rollup"] >= 60:
                last["rollup"] = now
                self.store.rollup()
            if now - last["state"] >= 300:          # survive a restart with the last known dev data
                last["state"] = now
                self.store.put("state", {"dev": self.dev, "dev_pc": self.pc_extra.get("dev_pc")})
            self.stop.wait(1.0)


def _read_secret(path) -> str:
    if not path:
        return ""
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.readline().strip()
    except OSError:
        return ""


__all__ = ["Collector", "Machine", "cpu_percent", "rate", "parse_prometheus", "router_models", "model_rates",
           "backup_alerts", "slot_summary", "cpu_temperature"]
