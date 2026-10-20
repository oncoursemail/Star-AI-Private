"""Run a golden-task suite through STAR's real task path and score the answers deterministically.

    python -m star.evals run --suite evals/roblox/golden-tasks-v2.json --out evals/results/x.json

Every automatable task is sent through `desktop_core.run_task` (the function the app itself calls)
with the STAR Server provider and an isolated, throw-away APPDATA, so nothing of the owner's real
profile is read or written. The answer is then scored by `star.eval_checks`: fenced Luau extracted,
compiled and type-checked by the knowledge service, unit tests run on the server in the standalone
Luau VM as user `star` under time and memory limits (never on this PC), required API names and
forbidden patterns, and a citation for documentation questions.

Operating rules built in:
  * quality-only: one request at a time, no lock taken;
  * before each task the runner waits while /opt/star/lock exists ("quiet please" for timing runs);
  * the result file is rewritten after every task and a re-run resumes where it stopped;
  * a task whose infrastructure failed is `error`, never `fail`;
  * nothing private is written: server addresses, the SSH target and the key are scrubbed.

Configuration is by environment variable or option, never from the repository:
  STAR_EVAL_SERVER   STAR Server URL, for example http://<server-address>:8080/v1
  STAR_EVAL_SSH      user@host that reaches the server's LXD host (sandbox and lock probe)
  STAR_EVAL_KEY_FILE file holding the server key (default ~/.star/server_api_key)
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any

from . import eval_checks as checks
from .knowledge_checks import validate_key

SCHEMA = 1
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_KEY_FILE = Path.home() / ".star" / "server_api_key"
LOCK_POLL_SECONDS = 20
LOCK_WATCH_SECONDS = 15        # how often a running request checks whether someone asked for quiet
MAX_INTERRUPTIONS = 12
SERVER_TIMEOUT_SECONDS = 1800   # the largest value the app allows
MAX_TRUNCATION_RETRIES = 2     # an answer that stops inside a code block is asked for again
# run_task errors that are STAR's own answer to the prompt (the user would see them): a failed task, not an infrastructure error.
PRODUCT_FAILURES = ("Model-call limit exceeded", "streamed no visible answer", "gave no text or tool calls",
                    "Failed to parse tool call arguments")   # the server rejects the model's own malformed tool call: the user sees this error
LOCK_LIMIT_SECONDS = 3 * 3600
_PRIVATE_IP = re.compile(r"\b(?:10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2})\b")
_KEEP_EVENTS = {"route_selected", "knowledge_finished", "luau_check_finished", "skill_packs"}


def _lf(data):
    """Line endings as LF, for text or bytes: a CRLF checkout and a git archive must read the same."""
    return data.replace(b"\r\n", b"\n") if isinstance(data, bytes) else data.replace("\r\n", "\n")


class RunAborted(RuntimeError):
    """The run stopped on purpose (lock held too long, interrupted). The checkpoint is saved."""


# --- suite -----------------------------------------------------------------------------------------

@dataclass
class Suite:
    path: Path
    sha256: str
    tasks: list[dict]
    prelude: str

    @property
    def directory(self) -> Path:
        return self.path.parent

    def runnable(self) -> list[dict]:
        return [t for t in self.tasks if t.get("run_mode") == "automated"]

    def test_body(self, task: dict) -> str:
        unit = (task.get("auto") or {}).get("unit_test")
        if not unit:
            return ""
        return (self.directory / unit["file"]).read_text(encoding="utf-8").replace("\r\n", "\n")


def load_suite(path: Path) -> Suite:
    from .evals import load_catalog
    path = Path(path)
    raw = path.read_bytes()
    load_catalog(path)                                     # the existing loader's rules (ids, modes, fields)
    tasks = json.loads(raw.decode("utf-8"))
    prelude_file = path.parent / "prelude.luau"
    prelude = prelude_file.read_text(encoding="utf-8").replace("\r\n", "\n") if prelude_file.is_file() else ""
    problems = validate_tasks(tasks, path.parent)
    if problems:
        raise ValueError("suite is invalid: " + "; ".join(problems[:8]))
    # Hash with normalised line endings: a Windows checkout (CRLF) and a git archive (LF) must agree.
    return Suite(path, hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest(), tasks, prelude)


def validate_tasks(tasks: list[dict], directory: Path) -> list[str]:
    problems = []
    for task in tasks:
        tid = task["id"]
        if not isinstance(task.get("prompt"), str) or not task["prompt"].strip():
            problems.append(f"{tid}: prompt missing")
        if task["run_mode"] == "studio" and not task.get("studio_check"):
            if not task.get("grader"):
                problems.append(f"{tid}: studio task needs studio_check or grader")
        if task["run_mode"] != "automated":
            continue
        auto = task.get("auto")
        if not isinstance(auto, dict):
            problems.append(f"{tid}: automated task needs an auto block")
            continue
        unit = auto.get("unit_test")
        if unit and not (directory / unit.get("file", "")).is_file():
            problems.append(f"{tid}: unit test file missing")
        for key in ("require", "require_any", "forbid"):
            for item in auto.get(key, []):
                try:
                    for pattern in (item["any"] if "any" in item else [item["re"]]):
                        re.compile(pattern)
                except (re.error, KeyError):
                    problems.append(f"{tid}: bad {key} pattern {item.get('id')}")
        if "answer" in auto:
            problems.extend(f"{tid}: bad answer key: {p}" for p in validate_key(auto["answer"]))
    return problems


# --- result file -----------------------------------------------------------------------------------

def scrub(value, secrets=()):
    """Recursively remove private addresses and any given secret strings from a JSON-able value."""
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "<redacted>")
        return _PRIVATE_IP.sub("<private-address>", value)
    if isinstance(value, list):
        return [scrub(v, secrets) for v in value]
    if isinstance(value, dict):
        return {k: scrub(v, secrets) for k, v in value.items()}
    return value


def write_result(path: Path, result: dict, secrets=()) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(scrub(result, secrets), ensure_ascii=False, indent=1, sort_keys=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def summarize(tasks: dict) -> dict:
    counts = {"pass": 0, "fail": 0, "error": 0}
    seconds = []
    for record in tasks.values():
        if record["status"] in counts:
            counts[record["status"]] += 1
            seconds.append(record.get("seconds", 0.0))
    scored = counts["pass"] + counts["fail"]
    return {**counts, "scored": scored,
            "pass_rate": round(counts["pass"] / scored, 4) if scored else None,
            "median_seconds": round(statistics.median(seconds), 1) if seconds else None}


def grader_sha256(root: Path = ROOT) -> str:
    """Fingerprint code that computes grades, not just the answers being rescored."""
    digest = hashlib.sha256()
    for name in ("eval_checks.py", "eval_runner.py", "eval_sandbox.py"):
        path = root / "star" / name
        digest.update(name.encode("utf-8") + b"\\0")
        digest.update(_lf(path.read_bytes()))
    return digest.hexdigest()


def suite_identity(suite: Suite) -> str:
    """Include sidecar graders and the prelude, which the suite JSON hash omits."""
    digest = hashlib.sha256(suite.sha256.encode("ascii"))
    digest.update(suite.prelude.encode("utf-8"))
    for task in suite.tasks:
        unit = (task.get("auto") or {}).get("unit_test")
        if unit:
            digest.update(unit["file"].encode("utf-8") + b"\\0")
            digest.update(suite.test_body(task).encode("utf-8"))
    return digest.hexdigest()


def git_state(root: Path = ROOT) -> dict:
    try:
        head = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True,
                                        text=True, timeout=15).stdout.strip()
        dirty = bool(subprocess.run(["git", "-C", str(root), "status", "--porcelain", "--", "star", "evals"],
                                    capture_output=True, text=True, timeout=15).stdout.strip())
    except (OSError, subprocess.SubprocessError):
        head, dirty = "", False
    return {"app_commit": head or "unknown", "app_dirty": dirty}


# --- pause while the server lock exists ---------------------------------------------------------------

def wait_for_lock(probe, *, sleep=time.sleep, now=time.monotonic, log=print,
                  poll: float = LOCK_POLL_SECONDS, limit: float = LOCK_LIMIT_SECONDS) -> float:
    """Block while the server lock exists; returns the seconds waited. `probe()` -> True/False/None."""
    started = now()
    announced = False
    while probe() is True:
        if not announced:
            log("server lock present: pausing")
            announced = True
        if now() - started > limit:
            raise RunAborted(f"the server lock was held for more than {int(limit)} s")
        sleep(poll)
    if announced:
        log("server lock released: resuming")
    return now() - started


class LockWatcher:
    """While a request runs, ask every few seconds whether the server lock appeared; if it did, set `cancel`.

    The lock means "quiet please: a timing measurement is running". Waiting before each request is not
    enough when one request lasts minutes, so the request itself is stopped and repeated afterwards.
    """

    def __init__(self, probe, cancel: threading.Event, *, interval: float = LOCK_WATCH_SECONDS):
        self._probe, self._cancel, self._interval = probe, cancel, interval
        self._stop = threading.Event()
        self.fired = False
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                locked = self._probe()
            except Exception:
                locked = None
            if locked is True:
                self.fired = True
                self._cancel.set()
                return

    def __enter__(self):
        if self._probe is not None:
            self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=5)


# --- one run ---------------------------------------------------------------------------------------

@dataclass
class Asked:
    answer: str
    events: list
    seconds: float


def compact_events(events: list) -> list[dict]:
    keep = []
    for event in events:
        if isinstance(event, dict) and event.get("event") in _KEEP_EVENTS:
            keep.append({k: v for k, v in event.items() if isinstance(v, (str, int, float, bool, list))})
    return keep[:20]


def record_for(task: dict, asked: Asked | None, score: checks.TaskScore | None, error: str = "", product_failure: str = "") -> dict:
    if product_failure:
        return {"status": "fail", "passed": False, "reasons": ["STAR gave no answer: " + product_failure], "checks": [],
                "seconds": 0.0, "product_failure": product_failure}
    if error or score is None or asked is None:
        return {"status": "error", "passed": False, "reasons": [error or "no score"], "checks": [],
                "seconds": round(asked.seconds, 1) if asked else 0.0, "error": error}
    events = compact_events(asked.events)
    packs = next((e.get("names") for e in events if e.get("event") == "skill_packs"), [])
    return {
        "status": "pass" if score.passed else "fail", "passed": score.passed,
        "prompt_sha256": hashlib.sha256(task["prompt"].encode("utf-8")).hexdigest()[:16],
        "reasons": score.reasons, "checks": [c.record() for c in score.checks],
        "seconds": round(asked.seconds, 1), "timings": score.timings, "blocks": score.blocks,
        "answer_chars": len(asked.answer), "answer_sha256": hashlib.sha256(asked.answer.encode("utf-8")).hexdigest(),
        "packs": packs or [], "events": events, "answer": asked.answer,
    }


def _planner_job_id(task_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "-", str(task_id))[:60] or "task"


def run_suite(suite: Suite, *, out: Path, ask, scorer, lock_probe=None, run_info: dict, task_ids=None,
              resume: bool = True, retry_errors: bool = False, sleep=time.sleep, now=time.monotonic,
              log=print, secrets=(), watch_interval: float = LOCK_WATCH_SECONDS, planner: Any = None,
              planner_holder: str = "") -> dict:
    """Run the runnable tasks one at a time, checkpointing after each. Returns the result dict.

    `planner` (star.planner_client.PlannerClient, optional): before each request the runner asks STAR's resource
    planner for an "eval" lease (one star-fast slot; the planner keeps one slot free for chat and pauses evals for
    timing windows); during the request a "yield" stops it like the quiet lock does, and it is asked again later.
    Planner off or unreachable: exactly the old behaviour (the quiet lock only)."""
    holder = planner_holder or f"eval-{os.getpid()}"
    lease = {"grant": None}

    def quiet_probe():
        """True when the request must stop: the quiet lock appeared, or the planner wants the slot back."""
        locked = lock_probe() if lock_probe is not None else None
        grant = lease["grant"]
        if locked is not True and grant is not None and grant.planned:
            renewed = planner.renew(grant)
            lease["grant"] = renewed if renewed.action in ("run", "fallback") else None
            if renewed.action in ("yield", "refuse"):
                log(f"planner: eval yields ({renewed.reason})")
                return True
        return locked
    watch_probe = quiet_probe if (lock_probe is not None or planner is not None) else None
    selected = [t for t in suite.runnable() if not task_ids or t["id"] in set(task_ids)]
    unknown = set(task_ids or []) - {t["id"] for t in suite.tasks}
    if unknown:
        raise ValueError("unknown task ids: " + ", ".join(sorted(unknown)))
    result = {
        "schema": SCHEMA,
        "suite": {"file": suite.path.name, "sha256": suite.sha256, "tasks_total": len(suite.tasks),
                  "automated": len(suite.runnable()), "selected": [t["id"] for t in selected],
                  "identity_sha256": suite_identity(suite)},
        "run": {**run_info, "grader_sha256": grader_sha256(),
                "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds")},
        "complete": False, "tasks": {},
    }
    out = Path(out)
    if resume and out.is_file():
        previous = json.loads(out.read_text(encoding="utf-8"))
        same = (previous.get("suite", {}).get("sha256") == suite.sha256
                and previous.get("run", {}).get("fingerprint") == run_info.get("fingerprint")
                and previous.get("suite", {}).get("identity_sha256") == suite_identity(suite)
                and previous.get("run", {}).get("grader_sha256") == grader_sha256())
        if not same:
            raise ValueError(f"{out.name} exists from a different suite or configuration; use another --out or delete it")
        result["run"]["started_at"] = previous["run"].get("started_at", result["run"]["started_at"])
        # A run limited with --tasks adds to the file: records of tasks it did not select stay as they were
        # (rewriting the file with only the selected tasks used to drop every other result). Only errors of the
        # selected tasks are dropped, and only with --retry-errors.
        chosen = {t["id"] for t in selected}
        result["tasks"] = {tid: rec for tid, rec in previous.get("tasks", {}).items()
                           if tid not in chosen or rec["status"] != "error" or not retry_errors}
        before = previous.get("suite", {}).get("selected") or []
        result["suite"]["selected"] = list(dict.fromkeys([*before, *result["suite"]["selected"]]))
    for task in suite.tasks:
        if task.get("run_mode") != "automated" and (not task_ids or task["id"] in task_ids):
            result["tasks"].setdefault(task["id"], {"status": "skipped", "reasons": ["needs Roblox Studio or a human"]})
    todo = [t for t in selected if t["id"] not in result["tasks"]]
    log(f"{len(selected)} tasks selected, {len(selected) - len(todo)} already done, {len(todo)} to run")
    waited = 0.0
    try:
        for number, task in enumerate(todo, 1):
            asked, score, error, product_failure = None, None, "", ""
            truncations = 0
            for interruption in range(MAX_INTERRUPTIONS + MAX_TRUNCATION_RETRIES + 1):
                if lock_probe is not None:
                    waited += wait_for_lock(lock_probe, sleep=sleep, now=now, log=log)
                if planner is not None:
                    began = now()
                    lease["grant"] = planner.wait_for("eval", holder, _planner_job_id(task["id"]), sleep=sleep,
                                                      log=log)
                    waited += now() - began
                cancel = threading.Event()
                watcher = LockWatcher(watch_probe, cancel, interval=watch_interval)
                try:
                    with watcher:
                        asked = ask(task, cancel)
                    if planner is not None:              # scoring does not use the brain's slot
                        planner.release(lease["grant"])
                        lease["grant"] = None
                    if checks.looks_truncated(asked.answer) and truncations < MAX_TRUNCATION_RETRIES:
                        truncations += 1
                        log(f"{task['id']}: the answer stops inside a code block; asking again ({truncations}/{MAX_TRUNCATION_RETRIES})")
                        continue
                    score = scorer(task, asked.answer)
                except checks.InfraError as exc:
                    error = str(exc)
                except Exception as exc:                   # the task path failed: infrastructure, not a wrong answer
                    if watcher.fired:
                        log(f"{task['id']}: stopped because the server lock appeared or the planner needed the slot; "
                            "will repeat it")
                        asked, score, error = None, None, ""
                        continue
                    if any(text in str(exc) for text in PRODUCT_FAILURES):
                        product_failure = f"{type(exc).__name__}: {str(exc)[:160]}"
                    else:
                        error = f"{type(exc).__name__}: {str(exc)[:200]}"
                finally:
                    if planner is not None:
                        planner.release(lease["grant"])
                        lease["grant"] = None
                break
            else:
                error = f"stopped {MAX_INTERRUPTIONS} times by the server lock"
            result["tasks"][task["id"]] = record_for(task, asked, score, error, product_failure)
            record = result["tasks"][task["id"]]
            if truncations:
                record["truncation_retries"] = truncations
                if asked is not None and checks.looks_truncated(asked.answer):
                    record["truncated"] = True
            result["summary"] = summarize(result["tasks"])
            result["run"]["waited_for_lock_s"] = round(waited, 1)
            write_result(out, result, secrets)
            log(f"[{number}/{len(todo)}] {task['id']} {record['status']} {record.get('seconds', 0)}s"
                + (": " + "; ".join(record["reasons"])[:160] if record["status"] != "pass" else ""))
        # Complete = every task the file covers has a record (a --tasks run on top of a partial file is not).
        result["complete"] = all(tid in result["tasks"] for tid in result["suite"]["selected"])
        result["run"]["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    except (KeyboardInterrupt, RunAborted) as exc:
        log("stopped: " + (str(exc) or type(exc).__name__) + " (progress is saved; run again to resume)")
        result["run"]["stopped"] = str(exc) or type(exc).__name__
    result["summary"] = summarize(result["tasks"])
    write_result(out, result, secrets)
    return result


# --- real wiring --------------------------------------------------------------------------------------

@contextmanager
def isolated_appdata():
    """Point APPDATA (and XDG_DATA_HOME) at a new empty folder, then restore. Never the real profile."""
    names = ("APPDATA", "XDG_DATA_HOME")
    saved = {n: os.environ.get(n) for n in names}
    with tempfile.TemporaryDirectory(prefix="star-eval-") as folder:
        for n in names:
            os.environ[n] = folder
        try:
            yield Path(folder)
        finally:
            for n, v in saved.items():
                if v is None:
                    os.environ.pop(n, None)
                else:
                    os.environ[n] = v


def read_key(path: Path) -> str:
    key = os.environ.get("STAR_SERVER_API_KEY", "").strip()
    if not key and Path(path).is_file():
        key = Path(path).read_text(encoding="utf-8").strip()
    if not key:
        raise SystemExit("No server key: set STAR_SERVER_API_KEY or pass --key-file")
    return key


def served_models(server: str, key: str) -> list[str]:
    """Model ids the server lists; empty when it cannot be asked."""
    try:
        import httpx
        reply = httpx.get(server.rstrip("/") + "/models", headers={"Authorization": "Bearer " + key},
                          timeout=10, trust_env=False)
        return sorted(str(m.get("id")) for m in reply.json().get("data", []) if isinstance(m, dict))[:20]
    except Exception:
        return []


class PlannedSandbox:
    """Luau VM checks on whichever STAR container the resource planner picks for "cpu-work" (brain 2's CPU-worker
    pool first, brain 1 when brain 2 has no headroom). Planner off or unreachable: the default sandbox, as before."""

    def __init__(self, boxes: dict, planner, default, holder: str = ""):
        self.boxes, self.planner, self.default = boxes, planner, default
        self.holder = holder or f"eval-check-{os.getpid()}"
        self.limits = getattr(default, "limits", {})
        self.placed: dict[str, int] = {}

    def run(self, source: str):
        grant = self.planner.admit("cpu-work", self.holder, "luau-check")
        box = self.boxes.get(grant.machine) if grant.planned else None
        try:
            chosen = box or self.default
            name = grant.machine if box else "default"
            self.placed[name] = self.placed.get(name, 0) + 1
            return chosen.run(source)
        finally:
            self.planner.release(grant)

    def lock_present(self, *args, **kwargs):
        return self.default.lock_present(*args, **kwargs)


def build_real(args, log=print):
    """(run_info, ask, scorer, lock_probe, secrets) wired to the real server."""
    from .desktop_core import Settings, run_task
    from .doc_knowledge import client_for
    from .eval_sandbox import ContainerSandbox

    key = read_key(Path(args.key_file))
    os.environ["STAR_SERVER_API_KEY"] = key
    os.environ["STAR_SKILL_PACKS"] = args.packs
    os.environ["STAR_BACKGROUND_WORK"] = "1"     # star-fast requests name a background slot (star/background_cap.py)
    server = (args.server or os.environ.get("STAR_EVAL_SERVER", "")).rstrip("/")
    if not server:
        raise SystemExit("Give the STAR Server URL with --server or STAR_EVAL_SERVER")
    # A non-streamed answer of 1600 tokens takes 3 to 10 minutes on a busy CPU server; the app's default of 600 s
    # of silence would turn a slow server into a "timeout", which says nothing about the answer.
    # --pin-model: every role (quick chat, code/Roblox, vision) answers with --model. Without it a server that offers
    # star-fast fills the blank code role, so a "star-quick" run still answers Roblox tasks with star-fast.
    pinned = getattr(args, "pin_model", False)
    roles = {f: args.model for f in ("fast_model", "reasoning_model", "roblox_model", "vision_model")} if pinned else {}
    settings = Settings(provider="star_server", server_endpoint=server, model=args.model, project="STAR-eval",
                        server_timeout=SERVER_TIMEOUT_SECONDS, **roles)
    settings.validate()
    knowledge = client_for(settings)
    if knowledge is None:
        raise SystemExit("STAR Knowledge is not configured for this server address")
    ssh = args.ssh or os.environ.get("STAR_EVAL_SSH", "")
    # The Luau VM runs (sandbox) may go to another STAR container (brain 2: CPU work off the model machine); the
    # quiet-lock probe always asks brain 1.
    sandbox_ssh = getattr(args, "sandbox_ssh", "") or os.environ.get("STAR_EVAL_SANDBOX_SSH", "") or ssh
    sandbox = ContainerSandbox(sandbox_ssh) if sandbox_ssh else None
    lock_box = ContainerSandbox(ssh) if ssh else None
    if sandbox is not None and lock_box is not None and sandbox_ssh != ssh:
        from .planner_client import PlannerClient
        planner = PlannerClient(timeout=3.0)
        if planner.enabled:
            sandbox = PlannedSandbox({"brain2": sandbox, "brain1": lock_box}, planner, sandbox)

    def luau_check(code: str, strict: bool = False):
        last = None
        for attempt in range(3):
            try:
                return knowledge.luau_check(code, strict=strict)
            except OSError as exc:
                last = exc
                time.sleep(3 * (attempt + 1))
        raise last

    def ask(task: dict, cancel=None) -> Asked:
        events: list = []
        started = time.monotonic()
        with isolated_appdata():
            answer = run_task(Settings(**{**settings.__dict__, "project": "eval-" + task["id"].lower()}),
                              task["prompt"], mode=args.mode, on_event=events.append, cancel_event=cancel)
        return Asked(answer, events, time.monotonic() - started)

    suite = args._suite

    def scorer(task: dict, answer: str) -> checks.TaskScore:
        return checks.score_answer(task, answer, luau_check=luau_check, sandbox=sandbox,
                                   prelude=suite.prelude, test_body=suite.test_body(task))

    served = served_models(server, key)
    fingerprint_source = {"mode": args.mode, "model": args.model, "packs": args.packs, "provider": "star_server",
                          **({"pinned_roles": True} if roles else {})}
    run_info = {
        **git_state(),
        "runner": "star.eval_runner/" + str(SCHEMA),
        "provider": "star_server", "model": args.model, "models_served": served, "mode": args.mode,
        "skill_packs": args.packs, "knowledge": "on", "temperature": 0, "server_timeout_s": SERVER_TIMEOUT_SECONDS,
        "server": "<private-address>", "sandbox": "lxc container as user star (prlimit + timeout)" if sandbox else "none",
        "platform": sys.platform, **({"pinned_roles": True} if roles else {}),
        "fingerprint": hashlib.sha256(json.dumps(fingerprint_source, sort_keys=True).encode()).hexdigest()[:12],
    }
    probe = lock_box.lock_present if lock_box else None
    return run_info, ask, scorer, probe, [key, server, ssh, ssh.split("@")[-1] if ssh else "",
                                          sandbox_ssh, sandbox_ssh.split("@")[-1] if sandbox_ssh else ""]


def rescore(suite: Suite, result: dict, scorer, *, log=print) -> dict:
    """Score the recorded answers again with the suite's current checks. No model is called.

    Used when a grader was corrected after a run: the answers are the expensive part and do not change.
    Refuses a task whose prompt differs from the one that was asked.
    """
    by_id = {t["id"]: t for t in suite.tasks}
    changed = []
    for tid, record in result["tasks"].items():
        task = by_id.get(tid)
        # A run made before a message was classified as STAR's own failure: it errored for a reason the user would see.
        failure = next((text for text in PRODUCT_FAILURES if record.get("status") == "error" and text in str(record.get("error", ""))), "")
        if task is not None and failure:
            result["tasks"][tid] = record_for(task, None, None, product_failure=f"{failure} ({str(record['error'])[:120]})")
            changed.append(f"{tid}: error -> fail (STAR's own failure)")
            continue
        if task is None or "answer" not in record:
            continue
        if record.get("prompt_sha256") != hashlib.sha256(task["prompt"].encode("utf-8")).hexdigest()[:16]:
            raise ValueError(f"{tid}: the prompt changed since the run; its answer cannot be re-scored")
        score = scorer(task, record["answer"])
        status = "pass" if score.passed else "fail"
        if status != record["status"]:
            changed.append(f"{tid}: {record['status']} -> {status}")
        record.update({"status": status, "passed": score.passed, "reasons": score.reasons,
                       "checks": [c.record() for c in score.checks], "timings": {**record.get("timings", {}), **score.timings}})
    result["suite"].update({"sha256": suite.sha256, "tasks_total": len(suite.tasks), "automated": len(suite.runnable())})
    result["suite"]["identity_sha256"] = suite_identity(suite)
    result["run"]["grader_sha256"] = grader_sha256()
    result["run"]["rescored_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    result["summary"] = summarize(result["tasks"])
    log("rescored; changed: " + ("; ".join(changed) if changed else "none"))
    return result


def routing_report(suite: Suite, *, enabled=None) -> dict:
    """Which skill packs would be added to each runnable task's prompt. No model, no server.

    Per pack: the tasks it fires for, the tasks the suite says it should help (`helps`), and the
    tasks it should help but does not fire for (a routing miss: the pack cannot help them).
    """
    from . import skill_packs
    names = [p.name for p in skill_packs.available()]
    chosen = set(names) if enabled is None else set(enabled)
    fires = {task["id"]: skill_packs.matching_names(task["prompt"], enabled=chosen) for task in suite.runnable()}
    report = {}
    for name in names:
        # "alone" is how a pack is measured (it is the only one enabled); `fires` is what happens when all compete.
        fired = sorted(t["id"] for t in suite.runnable() if skill_packs.matching_names(t["prompt"], enabled={name}))
        helps = sorted(t["id"] for t in suite.runnable() if name in t.get("helps", []))
        report[name] = {"fires_for": fired, "should_help": helps,
                        "measurable": sorted(set(fired) & set(helps)),
                        "routing_misses": sorted(set(helps) - set(fired)),
                        "also_fires_for": sorted(set(fired) - set(helps)),
                        "wins_when_all_enabled": sorted(tid for tid, hit in fires.items() if name in hit)}
    return {"per_task": fires, "per_pack": report}


# --- self-test: reference answers must pass, bad ones must fail ------------------------------------------

def selftest(suite: Suite, scorer, *, log=print) -> int:
    """Score the shipped reference answers (must pass) and bad answers (must fail). Returns failures."""
    failures = 0
    ref_dir = suite.directory / "reference"
    for task in suite.runnable():
        auto = task.get("auto") or {}
        for kind, expect in (("", True), (".bad", False)):
            file = ref_dir / f"{task['id']}{kind}.md"
            if not file.is_file():
                continue
            try:
                score = scorer(task, file.read_text(encoding="utf-8"))
            except checks.InfraError as exc:
                log(f"{task['id']}{kind or ' reference'}: infrastructure: {exc}")
                failures += 1
                continue
            good = score.passed == expect
            failures += 0 if good else 1
            log(f"{'ok  ' if good else 'FAIL'} {task['id']}{kind or ' reference'} "
                f"(expected {'pass' if expect else 'fail'}, got {'pass' if score.passed else 'fail'})"
                + ("" if good else ": " + "; ".join(score.reasons)[:200]))
        if auto.get("code", True) and not (ref_dir / f"{task['id']}.md").is_file():
            log(f"note {task['id']}: no reference answer")
        empty = scorer(task, "")
        if empty.passed:
            failures += 1
            log(f"FAIL {task['id']}: an empty answer passed")
    return failures


# --- command line -------------------------------------------------------------------------------------

def add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--suite", required=True, type=Path)
    parser.add_argument("--server", default="", help="STAR Server URL (or STAR_EVAL_SERVER)")
    parser.add_argument("--ssh", default="", help="user@host of the server's LXD host (or STAR_EVAL_SSH)")
    parser.add_argument("--sandbox-ssh", default="", help="user@host whose STAR container runs the Luau VM checks "
                        "(or STAR_EVAL_SANDBOX_SSH; default: --ssh). Brain 2 takes this CPU work off the model machine")
    parser.add_argument("--key-file", default=str(DEFAULT_KEY_FILE))
    parser.add_argument("--model", default="star-fast")
    parser.add_argument("--mode", default="auto", choices=["auto", "fast", "agent"])
    parser.add_argument("--packs", default="off", help="skill packs: off, all, or a comma list of pack names")
    parser.add_argument("--pin-model", action="store_true",
                        help="every role answers with --model (a quick-model arm for python -m star.cascade_router)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m star.evals")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="run a suite and write a result file")
    add_common(run)
    run.add_argument("--out", required=True, type=Path)
    run.add_argument("--tasks", default="", help="comma list of task ids (default: every automated task)")
    run.add_argument("--no-resume", action="store_true")
    run.add_argument("--retry-errors", action="store_true")
    st = sub.add_parser("selftest", help="check that reference answers pass and bad ones fail")
    add_common(st)
    rs = sub.add_parser("rescore", help="re-score the answers stored in a result file with the current checks")
    add_common(rs)
    rs.add_argument("--result", required=True, type=Path)
    rs.add_argument("--out", required=True, type=Path)
    rt = sub.add_parser("routing", help="show which skill packs fire for which task (no server needed)")
    rt.add_argument("--suite", required=True, type=Path)
    rt.add_argument("--packs", default="all")
    ls = sub.add_parser("list", help="list the suite")
    ls.add_argument("--suite", required=True, type=Path)
    args = parser.parse_args(argv)

    suite = load_suite(args.suite)
    if args.command == "list":
        auto = suite.runnable()
        print(f"{len(suite.tasks)} tasks, {len(auto)} automated, {len(suite.tasks) - len(auto)} need Studio or a human")
        for t in suite.tasks:
            print(f"{t['id']:8} {t['run_mode']:9} {t['category']}")
        return 0
    if args.command == "routing":
        names = None if args.packs == "all" else [x for x in args.packs.split(",") if x]
        print(json.dumps(routing_report(suite, enabled=names), indent=1))
        return 0
    args._suite = suite
    run_info, ask, scorer, probe, secrets = build_real(args)
    if args.command == "selftest":
        failures = selftest(suite, scorer)
        print("selftest:", "all good" if not failures else f"{failures} problem(s)")
        return 1 if failures else 0
    if args.command == "rescore":
        done = rescore(suite, json.loads(args.result.read_text(encoding="utf-8")), scorer)
        write_result(args.out, done, secrets)
        print(json.dumps(done["summary"]))
        return 0
    ids = [x for x in args.tasks.split(",") if x] or None
    from .planner_client import PlannerClient
    planner = PlannerClient(timeout=3.0)         # $STAR_PLANNER_URL or ~/.star/planner_url; none = old behaviour
    result = run_suite(suite, out=args.out, ask=ask, scorer=scorer, lock_probe=probe, run_info=run_info,
                       task_ids=ids, resume=not args.no_resume, retry_errors=args.retry_errors, secrets=secrets,
                       planner=planner if planner.enabled else None)
    print(json.dumps(result["summary"]))
    return 0 if result.get("complete") else 2


if __name__ == "__main__":
    raise SystemExit(main())
