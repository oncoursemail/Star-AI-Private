"""STAR eval farm: paired A/B eval batches on this PC's graphics card while the owner is away (research M1 + S3).

    python eval_farm.py [--home DIR] queue --name NAME --suite evals/roblox/golden-tasks-v2.json \
        --candidate-set api_hints_enabled=true [--baseline-set NAME=VALUE ...] [--tasks ID,ID] [--k 1]
    python eval_farm.py [--home DIR] status          the supervisor's state and every batch's progress
    python eval_farm.py [--home DIR] gate --name NAME   the paired verdict (star.eval_gate) of a batch
    python eval_farm.py [--home DIR] run             the supervisor loop (one copy at a time)
    python eval_farm.py [--home DIR] off | on        the off switch (the file DIR/OFF); off stops a running session

When the farm may run is the night turbo's rule set (turbo.Turbo: owner input, full-screen programs, games, other
llama-servers, other processes on the card, free video memory and RAM, ComfyUI), tuned to tools/pc_guard.py: a session
starts after 5 minutes without keyboard or mouse input, or 2 minutes between 00:00 and 08:00 local time, and stops
within seconds when the owner touches the PC (`back_seconds`). The app's "Use my PC" switch is not required
(`require_app_switch` false; pc_guard is the rule for agent work on this PC, owner 2026-10-22).

A session = star-fast on the card through the GPU switch's own launcher (star.gpu_helper.GpuHelper: same llama-server
command line, -np 1, no fallback to any brain) + one worker process that runs the queued batches with
star.eval_runner's real answer path (desktop_core.run_task, every role pinned to star-fast, temperature 0). STAR
Knowledge (docs search, Luau compile/analyze) is `knowledge_url` (kb_replica.py on this PC keeps brain 1 out of it), and
the Luau VM unit tests run in `sandbox_ssh`'s container (brain 2); model-written code never runs on this PC.

Paired by construction: every task runs in both arms back to back (order alternating per task and sample), so a night
that ends early still leaves whole pairs. A stopped worker loses only the task in flight; the result files are
eval_runner's (rewritten after every task, resumed on the next session). They are read unchanged by
`python -m star.evals gate --paired-session` and record the model as `star-fast@pc-gpu`, so the gate refuses to pair a
farm arm with a brain arm (different numerics). The gate's 36-hour session rule applies: size a batch for one night
plus a day.

DIR/config.json (never in the repository): llama_server, model, knowledge_url, sandbox_ssh, key_file, python; optional
server_ssh (brain 1's LXD host; set it only when knowledge or sandbox are brain 1's: its quiet lock then pauses the farm).
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import dataclasses
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
for _path in (str(REPO), str(HERE)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import turbo  # noqa: E402  (the night turbo's supervisor, rules and launcher)

ARMS = ("baseline", "candidate")
FARM_TAG = "@pc-gpu"
MUTEX = "Local\\STAR-eval-farm"
DEFAULTS = {
    **turbo.DEFAULTS,
    "day_idle_minutes": 5,           # tools/pc_guard.py: the owner is idle after 5 minutes without input
    "night_idle_minutes": 2,
    "night_start": 0, "night_end": 8,  # pc_guard's night: 00:00-08:00 local time
    "require_app_switch": False,
    "knowledge_url": "",             # STAR Knowledge: kb_replica.py on this PC, or a brain's :8091
    "sandbox_ssh": "",               # user@host whose STAR container runs the Luau VM tests (brain 2)
    "server_ssh": "",                # brain 1's LXD host, only when knowledge or sandbox are brain 1's (quiet lock)
}
NEEDED = ("llama_server", "model", "knowledge_url", "sandbox_ssh")


def default_home() -> Path:
    return Path(os.environ.get("STAR_FARM_HOME") or Path(os.environ.get("LOCALAPPDATA", Path.home())) / "STAR-eval-farm")


def load_config(home: Path) -> dict:
    config = dict(DEFAULTS)
    path = home / "config.json"
    if path.is_file():
        config.update(json.loads(path.read_text(encoding="utf-8")))
    return config


# ---- the queue -----------------------------------------------------------------------------------------------------
def queue_dir(home: Path) -> Path:
    return Path(home) / "queue"


def results_dir(home: Path, name: str) -> Path:
    return Path(home) / "results" / name


def batches(home: Path) -> list[dict]:
    folder = queue_dir(home)
    if not folder.is_dir():
        return []
    specs = [json.loads(p.read_text(encoding="utf-8")) for p in folder.glob("*.json")]
    return sorted(specs, key=lambda s: s["created_at"])


def pending(home: Path) -> list[dict]:
    return [s for s in batches(home) if not (queue_dir(home) / f"{s['name']}.done").exists()]


def make_batch(name: str, suite_path: Path, *, baseline: list[str], candidate: list[str], tasks: list[str],
               k: int = 1, model: str = "star-fast", mode: str = "auto", packs: str = "off") -> dict:
    """A checked batch spec. Raises SystemExit with the reason when it cannot run."""
    from star import eval_runner
    if not name.replace("-", "").replace("_", "").isalnum() or len(name) > 60:
        raise SystemExit("--name: letters, digits, - and _ (at most 60)")
    if not 1 <= k <= 4:
        raise SystemExit("--k: 1 to 4 samples per arm")
    arms = {"baseline": eval_runner.parse_sets(baseline), "candidate": eval_runner.parse_sets(candidate)}
    if arms["baseline"] == arms["candidate"]:
        raise SystemExit("both arms have the same settings: nothing to compare")
    suite = eval_runner.load_suite(suite_path)
    runnable = [t["id"] for t in suite.runnable()]
    unknown = [t for t in tasks if t not in runnable]
    if unknown:
        raise SystemExit("not automated tasks of this suite: " + ", ".join(unknown))
    return {"schema": 1, "name": name, "suite": str(Path(suite_path).resolve()), "tasks": list(tasks) or runnable,
            "k": k, "model": model, "mode": mode, "packs": packs,
            "arms": {"baseline": list(baseline), "candidate": list(candidate)},
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def add_batch(home: Path, spec: dict) -> Path:
    folder = queue_dir(home)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{spec['name']}.json"
    if path.exists():
        raise SystemExit(f"a batch named {spec['name']} is already queued")
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(spec, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


def arm_files(home: Path, spec: dict, arm: str) -> list[Path]:
    return [results_dir(home, spec["name"]) / f"{arm}-{j + 1}.json" for j in range(spec["k"])]


def progress(home: Path, spec: dict) -> dict:
    """Whole pairs done, and per arm: pass/scored and the median seconds per answer."""
    runs = {arm: [json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {"tasks": {}}
                  for p in arm_files(home, spec, arm)] for arm in ARMS}
    pairs = sum(1 for tid in spec["tasks"] if all(tid in run["tasks"] for arm in ARMS for run in runs[arm]))
    out = {"pairs": pairs, "tasks": len(spec["tasks"]), "k": spec["k"]}
    for arm in ARMS:
        rows = [r for run in runs[arm] for r in run["tasks"].values() if r.get("status") in ("pass", "fail", "error")]
        seconds = [r["seconds"] for r in rows if r.get("status") != "error" and r.get("seconds")]
        out[arm] = {"pass": sum(r["status"] == "pass" for r in rows),
                    "scored": sum(r["status"] in ("pass", "fail") for r in rows),
                    "error": sum(r["status"] == "error" for r in rows),
                    "median_s": round(statistics.median(seconds), 1) if seconds else None}
    return out


# ---- the worker: one session's batches against the card's server --------------------------------------------------
@contextmanager
def knowledge_at(url: str):
    """While eval_runner.build_real wires a runner, every task and its Luau checks use STAR Knowledge at `url` instead
    of the one next to the model server (there is none next to the card's server). The wired functions keep it."""
    from star import desktop_core, doc_knowledge
    run_task, client_for = desktop_core.run_task, doc_knowledge.client_for

    def run_task_here(settings, prompt, **kwargs):
        return run_task(dataclasses.replace(settings, knowledge_endpoint=url), prompt, **kwargs)

    def client_for_here(settings, **kwargs):
        return client_for(dataclasses.replace(settings, knowledge_endpoint=url), **kwargs)

    desktop_core.run_task, doc_knowledge.client_for = run_task_here, client_for_here
    try:
        yield
    finally:
        desktop_core.run_task, doc_knowledge.client_for = run_task, client_for


def build_arm(spec: dict, arm: str, base: str, config: dict, suite, log=print):
    """(run_info, ask, scorer, secrets) for one arm: eval_runner's real wiring with the card's server as the model."""
    from star import eval_runner, gpu_helper
    args = argparse.Namespace(suite=Path(spec["suite"]), server=base, ssh="", sandbox_ssh=config["sandbox_ssh"],
                              key_file=str(Path(config["key_file"]).expanduser()), model=spec["model"],
                              mode=spec["mode"], packs=spec["packs"], pin_model=True, set=list(spec["arms"][arm]))
    args._suite = suite
    with knowledge_at(config["knowledge_url"]):
        run_info, ask, scorer, _probe, secrets = eval_runner.build_real(args, log=log)
    # build_real marks the process as background work so it names a brain's background slot; the card's server has
    # one slot, which is the farm's alone.
    os.environ.pop("STAR_BACKGROUND_WORK", None)
    run_info["model"] = spec["model"] + FARM_TAG
    run_info["farm"] = {"batch": spec["name"], "arm": arm, "host": "pc-gpu", "n_cpu_moe": gpu_helper.N_CPU_MOE,
                        "context": gpu_helper.CONTEXT}
    return run_info, ask, scorer, [*secrets, config["knowledge_url"], config["sandbox_ssh"]]


def run_batch(home: Path, spec: dict, base: str, config: dict, *, build=build_arm, log=print) -> bool:
    """Every task in both arms, back to back, alternating which arm goes first. True when every pair has a record."""
    from star import eval_runner
    suite = eval_runner.load_suite(Path(spec["suite"]))
    wired = {arm: build(spec, arm, base, config, suite, log=log) for arm in ARMS}
    for number, tid in enumerate(spec["tasks"]):
        for j in range(spec["k"]):
            for arm in (ARMS if (number + j) % 2 == 0 else ARMS[::-1]):
                run_info, ask, scorer, secrets = wired[arm]
                done = eval_runner.run_suite(suite, out=arm_files(home, spec, arm)[j], ask=ask, scorer=scorer,
                                             run_info=run_info, task_ids=[tid], secrets=secrets, log=log)
                if done["run"].get("stopped"):            # Ctrl-C: the checkpoint is saved, the batch resumes later
                    return False
    return progress(home, spec)["pairs"] == len(spec["tasks"])


def work(home: Path, base: str, config: dict, *, build=build_arm, log=print) -> int:
    for spec in pending(home):
        log(f"batch {spec['name']}: {len(spec['tasks'])} tasks x {spec['k']} x 2 arms on {base}")
        if not run_batch(home, spec, base, config, build=build, log=log):
            log(f"batch {spec['name']}: stopped with pairs missing")
            return 2
        (queue_dir(home) / f"{spec['name']}.done").write_text(json.dumps(progress(home, spec)) + "\n", encoding="utf-8")
        log(f"batch {spec['name']}: done {json.dumps(progress(home, spec))}")
    return 0


# ---- the supervisor --------------------------------------------------------------------------------------------------
class Farm(turbo.Turbo):
    """The night turbo's supervisor with an eval worker instead of night school."""

    def __init__(self, home: Path, config: dict, **kwargs):
        super().__init__(home, config, sync=lambda: "", merge=lambda: "", **kwargs)
        self.worker_failed = False

    def log(self, text: str) -> None:
        with open(self.home / "farm.log", "a", encoding="utf-8") as handle:
            handle.write(time.strftime("%Y-%m-%d %H:%M:%S") + " " + text + "\n")

    def start_blocker(self) -> str:
        if not pending(self.home):
            return "nothing queued"
        return super().start_blocker()

    def stop_reason(self) -> str:
        if self.worker is not None and self.worker.poll() is not None:
            self.worker_failed = self.worker.returncode != 0
            return f"the eval worker exited (code {self.worker.returncode})"
        return super().stop_reason()

    def _begin(self) -> None:
        missing = [key for key in NEEDED if not self.config.get(key)]
        if missing:
            self.end("config.json lacks " + ", ".join(missing), failed=True)
            return
        self._say("loading", "loading star-fast on the graphics card")
        self.started = self._clock()
        self.gpu_hot = 0
        settings = SimpleNamespace(use_my_gpu=True, gpu_helper_server=self.config["llama_server"],
                                   gpu_helper_model=self.config["model"], gpu_idle_minutes=24 * 60, comfy_port=8188)
        self.helper.configure(settings, self.home, start=True)

    def _spawn_worker(self) -> None:
        base = self.helper.lease()            # held for the whole session: the helper's own idle/busy stops stay off
        if not base:
            self.end("the model server was not ready", failed=True)
            return
        python = self.config["python"] or sys.executable.replace("pythonw.exe", "python.exe")
        log = open(self.home / "worker.log", "ab")
        try:
            self.worker = self._popen([python, str(Path(__file__).resolve()), "--home", str(self.home), "work",
                                       "--base", base], cwd=str(REPO), stdin=subprocess.DEVNULL, stdout=log,
                                      stderr=subprocess.STDOUT, creationflags=turbo.NO_WINDOW)
        finally:
            log.close()
        self.worker_failed = False
        self._say("running", f"eval batch {pending(self.home)[0]['name']} on the graphics card")

    def end(self, why: str, *, failed: bool = False) -> None:
        """Stop the worker (the task in flight is dropped and repeated next session), then the model server."""
        worker, self.worker = self.worker, None
        if worker is not None and worker.poll() is None:
            turbo.kill_tree(worker)
        self.helper.shutdown()
        if failed or self.worker_failed:
            self.cool_until = self._clock() + turbo.COOL_DOWN_S
        self.worker_failed = False
        self._say("waiting", "stopped: " + why)


# ---- commands --------------------------------------------------------------------------------------------------------
def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="eval_farm", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--home", type=Path, default=default_home())
    sub = parser.add_subparsers(dest="command", required=True)
    q = sub.add_parser("queue", help="queue a paired A/B batch")
    q.add_argument("--name", required=True)
    q.add_argument("--suite", required=True, type=Path)
    q.add_argument("--tasks", default="", help="comma list of task ids (default: every automated task)")
    q.add_argument("--k", type=int, default=1, help="samples per arm (pairs per task)")
    q.add_argument("--baseline-set", action="append", default=[], metavar="NAME=VALUE")
    q.add_argument("--candidate-set", action="append", default=[], metavar="NAME=VALUE")
    q.add_argument("--model", default="star-fast")
    q.add_argument("--mode", default="auto", choices=["auto", "fast", "agent"])
    q.add_argument("--packs", default="off")
    g = sub.add_parser("gate", help="paired verdict of a batch (star.eval_gate)")
    g.add_argument("--name", required=True)
    w = sub.add_parser("work", help="(started by the supervisor) run the queue against the card's server")
    w.add_argument("--base", required=True, help="the card's llama-server, http://127.0.0.1:PORT/v1")
    for name in ("status", "run", "off", "on"):
        sub.add_parser(name)
    args = parser.parse_args(argv)
    home = args.home
    home.mkdir(parents=True, exist_ok=True)
    os.environ["APPDATA"] = str(home / "appdata")       # nothing here may read or write the owner's STAR profile
    config = load_config(home)
    if args.command == "queue":
        from star import eval_stats
        spec = make_batch(args.name, args.suite, baseline=args.baseline_set, candidate=args.candidate_set,
                          tasks=[t for t in args.tasks.split(",") if t], k=args.k, model=args.model, mode=args.mode,
                          packs=args.packs)
        print(f"queued {add_batch(home, spec)}: {len(spec['tasks'])} tasks x {spec['k']} x 2 arms")
        print(eval_stats.minimum_detectable_effect(len(spec["tasks"]), spec["k"]).text())
        return 0
    if args.command == "status":
        status = home / "STATUS.txt"
        print(status.read_text(encoding="utf-8").strip() if status.is_file() else "supervisor: no status yet")
        print("off switch: " + ("ON (sessions blocked)" if (home / "OFF").exists() else "not set"))
        for spec in batches(home):
            done = (queue_dir(home) / f"{spec['name']}.done").exists()
            print(f"{spec['name']}{' (done)' if done else ''}: {json.dumps(progress(home, spec))}")
        return 0
    if args.command == "gate":
        from star import eval_gate
        spec = json.loads((queue_dir(home) / f"{args.name}.json").read_text(encoding="utf-8"))
        verdict = eval_gate.evaluate_paired([str(p) for p in arm_files(home, spec, "baseline")],
                                            [str(p) for p in arm_files(home, spec, "candidate")])
        print(verdict.text())
        return verdict.code
    if args.command == "work":
        return work(home, args.base, config)
    if args.command == "off":
        (home / "OFF").write_text("off\n", encoding="utf-8")
        print("off: a running session stops within seconds; 'on' allows sessions again")
        return 0
    if args.command == "on":
        (home / "OFF").unlink(missing_ok=True)
        print("on")
        return 0
    if not turbo.single_instance(MUTEX):
        return 0
    Farm(home, config).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
