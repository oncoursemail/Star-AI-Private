"""The learning cycle. It knows nothing about HTTP or the app: `solve` and `diagnose` are handed in, so the same
code runs with the real model on the server and with a fake model in the tests.

One cycle (one practice task):
  1. solve the task with the active lessons; a pass is stored as a verified worked example;
  2. on a failure, try a waiting candidate lesson for the same kind of failure; then ask the model for the cause and
     ONE short lesson and solve again with it; the lesson is kept as a candidate only if the task now passes;
  3. a candidate that fixed `promote_fixes` different tasks is compared with the active set on the validation slice
     (tasks that are never used to write lessons): both arms, k samples each, interleaved in this session, decided by
     the paired sign test of star/eval_stats.py (W1). PROMOTE makes it active, REJECT holds it back, INCONCLUSIVE
     keeps it a candidate (it never promotes) until it has fixed `promote_fixes` more tasks;
  4. every `recheck_every` tasks the newest active lesson is compared the same way (active set with and without it);
     it is retired only when it makes the slice significantly worse.
Every decision is written down with the numbers that justified it (state.json, attempts.jsonl, events.jsonl).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import threading

from .pool import is_validation

MAX_LESSON_CHARS = 240      # the app clips a lesson to 240 characters in a turn


class Yielded(Exception):
    """Another client appeared (or HOLD / the quiet lock): the item in flight is dropped, nothing is counted."""


@dataclass
class Result:
    passed: bool = False
    reasons: list = field(default_factory=list)
    checks: list = field(default_factory=list)
    answer: str = ""
    seconds: float = 0.0
    recalled: list = field(default_factory=list)   # ids of the lessons that were really placed in the turn
    error: str = ""                                # the check could not run (service, sandbox): not a failure


def in_share(task_id: str, share: str) -> bool:
    """True when the task belongs to this worker's share ("k/n" or "k1,k2/n"; "" = all tasks)."""
    if not share:
        return True
    picks, total = share.split("/", 1)
    bucket = int(hashlib.sha256(task_id.encode("utf-8")).hexdigest(), 16) % int(total)
    return bucket in {int(k) for k in picks.split(",")}


def read_skip(path: str) -> set[str]:
    """Task ids from a JSON list file (another worker's answered tasks); an absent or broken file skips nothing."""
    if not path:
        return set()
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    return {str(i) for i in data} if isinstance(data, list) else set()


def utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def classify(reasons: list[str]) -> str:
    """One plain cause label from the first failed check."""
    first = str(reasons[0]) if reasons else ""
    head = first.split(":", 1)[0].strip()
    if head == "answer" or any(str(reason).startswith(("STAR gave no answer", "answer:")) for reason in reasons):
        return "no answer"
    if head == "luau_block":
        return "no Luau code block in the answer"
    if head.startswith("luau_check"):
        return "code does not compile or type-check"
    if head == "unit_tests":
        if "did not load" in first:
            return "unit tests: the code did not load"
        if "timed out" in first:
            return "unit tests: timed out"
        return "unit tests fail (wrong logic)"
    if head == "typecheck_probe":
        return "types too loose (a wrong call is accepted)"
    if head == "citation":
        return "documentation source not cited"
    for prefix, label in (("require_any", "required element missing"), ("require", "required element missing"),
                          ("forbid", "forbidden pattern used")):
        if head == prefix or first.startswith(prefix + ":"):
            name = first.split(":", 2)[1].strip() if first.count(":") >= 1 else ""
            return f"{label} ({name[:40]})" if name else label
    return "other check failed (" + head[:40] + ")"


def clean_lesson(text, task: dict) -> str:
    """A usable lesson text or "". One short general rule: no code block, no task id, no line breaks."""
    if not isinstance(text, str):
        return ""
    text = " ".join(text.replace("```", " ").split()).strip(" \"'")
    if len(text) < 20 or len(text) > MAX_LESSON_CHARS:
        text = text[:MAX_LESSON_CHARS].rsplit(" ", 1)[0] if len(text) > MAX_LESSON_CHARS else ""
    if not text or str(task.get("id", "")).lower() in text.lower():
        return ""
    return text


class Store:
    """Files in the data folder. state.json is rewritten atomically; the .jsonl files only grow."""

    def __init__(self, data: Path):
        self.data = Path(data)
        self.data.mkdir(parents=True, exist_ok=True)
        self.path = self.data / "state.json"
        self.state = {"version": 1, "started": utc(), "tasks": {}, "lessons": {}, "validation": [], "runs": {},
                      "counters": {}, "causes": {}, "next_lesson": 1, "items_since_recheck": 0, "pool": ""}
        if self.path.is_file():
            self.state.update(json.loads(self.path.read_text(encoding="utf-8")))

    def save(self) -> None:
        temporary = self.path.with_name("state.json.tmp")
        with open(temporary, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(self.state, handle, ensure_ascii=False, indent=1)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self.path)

    def append(self, name: str, row: dict) -> None:
        with open(self.data / (name + ".jsonl"), "a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    def count(self, name: str, by: int = 1) -> None:
        self.state["counters"][name] = self.state["counters"].get(name, 0) + by

    def lessons(self, status: str) -> list[dict]:
        return [l for l in self.state["lessons"].values() if l["status"] == status]


class Engine:
    def __init__(self, settings, pool, store: Store, *, solve, diagnose, check_lesson=None, log=print):
        self.settings, self.pool, self.store = settings, pool, store
        self._solve, self._diagnose, self._check_lesson, self._log = solve, diagnose, check_lesson, log
        # Parallel lanes (run_batch(lanes=N)): one lock guards the state; it is let go only while a lane waits for
        # the model (solve / diagnose), so every state change stays one-at-a-time and in the same order as before.
        self._lock = threading.Lock()
        self._parallel = False
        self._in_flight: set[str] = set()
        self.set_pool(pool)

    def _unlocked(self, call, *args):
        """Call the model with the state lock let go (parallel lanes only)."""
        if not self._parallel:
            return call(*args)
        self._lock.release()
        try:
            return call(*args)
        finally:
            self._lock.acquire()

    def set_pool(self, pool) -> None:
        self.pool = pool
        ids = sorted(t["id"] for t in pool.tasks if is_validation(t["id"], self.settings.validation_percent))
        ids.sort(key=lambda i: hashlib.sha256(i.encode("utf-8")).hexdigest())
        frozen = self.store.state.setdefault("validation_ids", [])
        present = {t["id"] for t in pool.tasks}
        # Set aside at the start and never changed: later pool additions do not move a task in or out.
        for task_id in ids:
            if len(frozen) >= self.settings.validation_max:
                break
            if task_id not in frozen and task_id not in self.store.state["tasks"]:
                frozen.append(task_id)
        self.validation = [t for t in pool.tasks if t["id"] in frozen]
        share = getattr(self.settings, "share", "")
        skip = read_skip(getattr(self.settings, "skip_file", ""))
        self.training = [t for t in pool.tasks
                         if t["id"] not in frozen and in_share(t["id"], share) and t["id"] not in skip]
        self.store.state["pool"] = pool.summary() + f"; {len(self.validation)} set aside for validation" + (
            f"; share {share}: {len(self.training)} practice tasks" if share else "")
        self.store.state["validation_missing"] = len([i for i in frozen if i not in present])

    # --- helpers ------------------------------------------------------------------------------------------
    def active(self) -> list[dict]:
        return sorted(self.store.lessons("active"), key=lambda l: l.get("promoted", ""))

    def _attempt(self, task: dict, lessons: list[dict], purpose: str) -> Result:
        result = self._unlocked(self._solve, task, lessons)
        self.store.append("attempts", {
            "ts": utc(), "task": task["id"], "purpose": purpose, "lessons": [l["id"] for l in lessons],
            "recalled": result.recalled, "passed": result.passed, "error": result.error, "reasons": result.reasons[:6],
            "checks": result.checks[:20], "seconds": round(result.seconds, 1),
            "answer_sha256": hashlib.sha256(result.answer.encode("utf-8")).hexdigest() if result.answer else ""})
        self.store.count("answers")
        self.store.state["answer_seconds"] = round(self.store.state.get("answer_seconds", 0.0) + result.seconds, 1)
        bucket = "validation_seconds" if purpose.startswith("validation") else "practice_seconds"
        self.store.state[bucket] = round(self.store.state.get(bucket, 0.0) + result.seconds, 1)
        return result

    def validation_allowed(self) -> bool:
        """The validation budget (settings.validation_share): True while validation answers have taken less than
        that share of the answer time counted since the budget exists. 0 or 1 = no limit (the old behaviour)."""
        share = float(getattr(self.settings, "validation_share", 0) or 0)
        if not 0 < share < 1:
            return True
        state = self.store.state
        return state.get("validation_seconds", 0.0) < share / (1 - share) * state.get("practice_seconds", 0.0)

    def _example(self, task: dict, result: Result, lessons: list[dict], kind: str) -> None:
        self.store.append("examples", {
            "ts": utc(), "task": task["id"], "category": task.get("category", ""), "kind": kind,
            "prompt": task["prompt"], "answer": result.answer, "checks": [c.get("id") for c in result.checks],
            "lessons": [l["id"] for l in lessons], "seconds": round(result.seconds, 1),
            "verified": "automated checks of the practice task (static Luau check, unit tests in the Luau VM with "
                        "stand-ins for Roblox classes, required and forbidden patterns); not run in Roblox Studio"})
        self.store.count("examples")

    def next_task(self) -> dict | None:
        tasks = self.store.state["tasks"]

        def priority(item):
            index, task = item
            seen = tasks.get(task["id"])
            if not seen:
                return (0, index)
            waiting = self.store.state["lessons"].get(seen.get("fixed_by") or "", {}).get("status") == "candidate"
            if seen["status"] == "fixed" and waiting:
                return (seen["tries"] + 50, index)      # its lesson still needs proof from OTHER tasks first
            return (seen["tries"] + (2 if seen["status"] in ("passed_first", "fixed") else 0), index)
        ordered = [x for x in sorted(enumerate(self.training), key=priority) if x[1]["id"] not in self._in_flight]
        return ordered[0][1] if ordered else None

    # --- one practice task --------------------------------------------------------------------------------
    def run_item(self, task: dict) -> str:
        """Returns the outcome: passed_first, fixed, failed or error. Raises Yielded when interrupted."""
        state = self.store.state
        active = self.active()
        first = self._attempt(task, active, "first")
        seen = state["tasks"].setdefault(task["id"], {"tries": 0, "status": "", "first_seen": utc()})
        if first.error:
            self.store.count("infrastructure_errors")
            seen.update(last=utc(), last_error=first.error[:160])
            seen["errors"] = seen.get("errors", 0) + 1
            if seen["errors"] >= 3:          # a task whose checks cannot run must not block the queue
                seen["tries"] += 1
                seen["status"] = seen["status"] or "error"
            self.store.save()
            return "error"
        seen["tries"] += 1
        seen["last"] = utc()
        self.store.count("tasks_tried")
        if first.passed:
            seen["status"] = "passed_first"
            self.store.count("passed_first")
            self._example(task, first, active, "first")
            self.store.save()
            return "passed_first"
        cause = classify(first.reasons)
        entry = state["causes"].setdefault(cause, {"count": 0, "example": ""})
        entry["count"] += 1
        entry["example"] = f"{task['id']}: {str(first.reasons[0])[:150] if first.reasons else ''}"
        seen["cause"] = cause
        outcome = "failed"

        def retry_unavailable(result: Result) -> str:
            # The initial answer failed, but an unavailable checker cannot judge a lesson's effect.
            self.store.count("infrastructure_errors")
            seen["last_error"] = result.error[:160]
            seen["errors"] = seen.get("errors", 0) + 1
            seen["status"] = seen["status"] or "error"
            self.store.save()
            return "error"

        # (a) a waiting candidate for the same kind of failure, best fix rate first. The rate is smoothed
        # ((fixed + 1) / (tried + 2)), so a new candidate is tried on other tasks until its rate falls below the
        # leader's; ranking by the raw fix count let one leader take every retry (10-25: 64 of 92 candidates were
        # never tried on a second task, so they could never reach the gate).
        waiting = [l for l in self.store.lessons("candidate")
                   if l["cause"] == cause and task["id"] not in l["tried"]]
        waiting.sort(key=lambda l: (-(len(l["fixed"]) + 1) / (len(l["tried"]) + 2), l["id"]))
        for lesson in waiting[:self.settings.retry_candidates]:
            again = self._attempt(task, active + [lesson], "candidate " + lesson["id"])
            if again.error:
                return retry_unavailable(again)
            lesson["tried"].append(task["id"])
            if again.passed:
                lesson["fixed"].append(task["id"])
                lesson["evidence"].append({"ts": utc(), "fixed": task["id"], "failed_before": first.reasons[:2]})
                self._example(task, again, active + [lesson], "lesson")
                seen["fixed_by"] = lesson["id"]
                outcome = "fixed"
                break
        # (b) a new lesson from the model's own diagnosis
        if outcome == "failed":
            diagnosis = self._unlocked(self._diagnose, task, first) or {}
            self.store.count("diagnoses")
            said = " ".join(str(diagnosis.get("cause") or "").split())[:200]
            if said:
                entry["model_says"] = said
            text = clean_lesson(diagnosis.get("lesson"), task)
            if text and self._check_lesson is not None:
                text = self._check_lesson(text) or ""
            duplicate = any(l["text"].lower() == text.lower() for l in state["lessons"].values()) if text else False
            if text and not duplicate:
                lesson = {"id": f"L{state['next_lesson']}", "text": text, "cause": cause, "status": "trial",
                          "created": utc(), "from_task": task["id"], "model_cause": said, "tried": [task["id"]],
                          "fixed": [], "evidence": []}
                state["next_lesson"] += 1
                again = self._attempt(task, active + [lesson], "new lesson " + lesson["id"])
                self.store.count("lessons_proposed")
                if again.error:
                    return retry_unavailable(again)
                if again.passed:
                    lesson["status"] = "candidate"
                    lesson["fixed"].append(task["id"])
                    lesson["evidence"].append({"ts": utc(), "fixed": task["id"], "failed_before": first.reasons[:2]})
                    state["lessons"][lesson["id"]] = lesson
                    self._example(task, again, active + [lesson], "lesson")
                    self.store.count("candidates_kept")
                    seen["fixed_by"] = lesson["id"]
                    outcome = "fixed"
                else:
                    self.store.count("lessons_discarded")
                    self.store.append("events", {"ts": utc(), "event": "lesson discarded", "lesson": lesson,
                                                 "why": "the task still failed with it", "reasons": again.reasons[:3]})
            else:
                self.store.count("lessons_unusable")
        seen["status"] = outcome
        self.store.count("fixed_by_lesson" if outcome == "fixed" else "still_failing")
        self.store.save()
        return outcome

    # --- validation, promotion, retirement ----------------------------------------------------------------
    def measure(self, lessons: list[dict], why: str, *, fresh: bool = False) -> dict | None:
        """Pass count of the validation slice with `lessons`. Resumable: finished tasks of an interrupted run are
        kept. None when a check could not run (no decision is taken on an incomplete measurement)."""
        if not self.validation:
            return None
        runs = self.store.state["runs"]
        key = hashlib.sha256(json.dumps(sorted((l["id"], l["text"]) for l in lessons)).encode()).hexdigest()[:16]
        if fresh and runs.get(key, {}).get("done"):
            runs.pop(key)
        run = runs.setdefault(key, {"results": {}, "lessons": [l["id"] for l in lessons], "done": False})
        if not run["done"]:
            for task in self.validation:
                if task["id"] in run["results"]:
                    continue
                result = self._attempt(task, lessons, "validation")
                if result.error:
                    self.store.count("infrastructure_errors")
                    self.store.save()
                    return None
                run["results"][task["id"]] = bool(result.passed)
                self.store.save()
            run["done"] = True
            run.update(passed=sum(run["results"].values()), total=len(run["results"]), ts=utc())
            self.store.state["validation"].append({"ts": run["ts"], "passed": run["passed"], "total": run["total"],
                                                   "active_lessons": run["lessons"], "why": why})
            self.store.state["validation"] = self.store.state["validation"][-200:]
            self.store.save()
        return run

    def _stats(self):
        """star.eval_stats from the application copy (the same module the evaluation gate uses)."""
        try:
            from star import eval_stats
        except ImportError:
            app = str(self.settings.app)
            if app not in sys.path:
                sys.path.insert(0, app)
            from star import eval_stats
        return eval_stats

    def measure_paired(self, base: list[dict], trial: list[dict], why: str, *, samples: int, tag: str = "",
                       fresh: bool = False) -> dict | None:
        """Both lesson sets on every validation task, k samples each, interleaved in this session: for sample j the
        order alternates per task and per sample (base first, then trial first), so drift hits both arms alike.
        Resumable like `measure`; None when a check could not run (no decision on an incomplete measurement)."""
        if not self.validation:
            return None
        runs = self.store.state.setdefault("paired_runs", {})
        ident = json.dumps([sorted((l["id"], l["text"]) for l in base), sorted((l["id"], l["text"]) for l in trial),
                            samples, tag])
        key = hashlib.sha256(ident.encode()).hexdigest()[:16]
        if fresh and runs.get(key, {}).get("done"):
            runs.pop(key)
        run = runs.setdefault(key, {"base": {}, "trial": {}, "base_lessons": [l["id"] for l in base],
                                    "trial_lessons": [l["id"] for l in trial], "samples": samples, "why": why,
                                    "done": False})
        arms = {"base": base, "trial": trial}
        if not run["done"]:
            for j in range(samples):
                for index, task in enumerate(self.validation):
                    order = ("base", "trial") if (index + j) % 2 == 0 else ("trial", "base")
                    if any(len(run[arm].get(task["id"], [])) <= j for arm in order) and not self.validation_allowed():
                        self.store.count("validation_budget_waits")     # both arms of a task stay side by side
                        self.store.save()
                        return None
                    for arm in order:
                        got = run[arm].setdefault(task["id"], [])
                        if len(got) > j:
                            continue
                        result = self._attempt(task, arms[arm], f"validation {arm} {j + 1}/{samples}")
                        if result.error:
                            self.store.count("infrastructure_errors")
                            self.store.save()
                            return None
                        got.append(bool(result.passed))
                        self.store.save()
            report = self._stats().paired_decision(run["base"], run["trial"], alpha=self.settings.gate_alpha,
                                                   seed=int(key[:8], 16))
            run.update(done=True, ts=utc(), decision=report.decision, gate=report.summary(),
                       base_passed=report.baseline_pass, trial_passed=report.candidate_pass, total=report.samples)
            for arm, lessons, passed in (("base", base, report.baseline_pass), ("trial", trial, report.candidate_pass)):
                self.store.state["validation"].append({"ts": run["ts"], "passed": passed, "total": report.samples,
                                                       "active_lessons": [l["id"] for l in lessons],
                                                       "why": f"{why} ({arm} arm, k={samples})"})
            self.store.state["validation"] = self.store.state["validation"][-200:]
            finished = [k for k, r in runs.items() if r.get("done")]
            for old_key in finished[:-50]:                  # keep the newest 50 finished paired runs
                runs.pop(old_key, None)
            self.store.save()
        return run

    def consider_promotions(self) -> None:
        """A candidate that fixed `promote_fixes` tasks is compared with the active set on the validation slice,
        paired and interleaved (W1). PROMOTE -> active; REJECT -> held; INCONCLUSIVE stays a candidate and is measured
        again only after it fixed `promote_fixes` more tasks. INCONCLUSIVE never promotes."""
        for lesson in sorted(self.store.lessons("candidate"), key=lambda l: l["id"]):
            fixed = len(set(lesson["fixed"]))
            if fixed < self.settings.promote_fixes + lesson.get("gated_at_fixes", 0):
                continue
            active = self.active()
            # The run's name is fixed when the gate starts and kept until it decides: a paused gate (validation
            # budget, back-off) resumes even when the candidate fixes more tasks meanwhile. Naming it by the live fix
            # count restarted it from zero on every new fix (10-25: 8 unfinished restarts for L226).
            tag = lesson.setdefault("gate_tag", f"promote {lesson['id']} at {fixed}")
            run = self.measure_paired(active, active + [lesson], "gate " + lesson["id"], samples=self.settings.samples,
                                      tag=tag)
            if not run:
                return
            lesson.pop("gate_tag", None)
            proof = {"fixed_tasks": sorted(set(lesson["fixed"])),
                     "validation_before": f"{run['base_passed']}/{run['total']}",
                     "validation_with": f"{run['trial_passed']}/{run['total']}",
                     "before_passed": run["base_passed"], "gate": run["gate"]}
            decision = run["decision"]
            if decision == "PROMOTE":
                lesson.update(status="active", promoted=utc(), promotion=proof)
                self.store.count("lessons_promoted")
            elif decision == "REJECT":
                lesson.update(status="held", held=utc(), promotion=proof)
                self.store.count("lessons_held_back")
            else:
                lesson["gated_at_fixes"] = fixed
                lesson.setdefault("gates", []).append({"ts": utc(), **proof})
                self.store.count("lessons_inconclusive")
            self._log(f"lesson {lesson['id']} gate {decision} ({proof['validation_before']} -> "
                      f"{proof['validation_with']}, p(better)={run['gate']['p_better']}, MDE "
                      f"+{run['gate']['mde_tasks']} tasks)")
            self.store.append("events", {"ts": utc(), "event": f"lesson gate {decision}", "lesson": lesson})
            self.store.save()

    def recheck(self) -> None:
        """Retire the newest active lesson only when a paired comparison (active set with and without it, run
        interleaved now) says it makes the slice significantly worse (REJECT). A drop below the noise floor retires
        nothing: that was the old rule's coin flip (L14: promoted at 6/12, retired at 5/12)."""
        active = self.active()
        if not active:
            return
        newest = active[-1]
        number = self.store.state.get("recheck_count", 0) + 1      # counted when finished: an interrupted one resumes
        run = self.measure_paired(active[:-1], active, "recheck " + newest["id"], samples=self.settings.recheck_samples,
                                  tag=f"recheck {number}")
        if not run:
            return
        self.store.state["recheck_count"] = number
        check = {"ts": utc(), "decision": run["decision"], "validation_without": f"{run['base_passed']}/{run['total']}",
                 "validation_with": f"{run['trial_passed']}/{run['total']}", "gate": run["gate"]}
        newest.setdefault("rechecks", []).append(check)
        newest["rechecks"] = newest["rechecks"][-10:]
        if run["decision"] == "REJECT":
            newest.update(status="retired", retired=utc(),
                          retirement={"validation_now": check["validation_with"],
                                      "validation_without": check["validation_without"],
                                      "validation_before_promotion": newest.get("promotion", {}).get("validation_before", "?"),
                                      "gate": run["gate"]})
            self.store.count("lessons_retired")
            self.store.append("events", {"ts": utc(), "event": "lesson retired", "lesson": newest})
            self._log(f"lesson {newest['id']} retired (with {check['validation_with']}, without "
                      f"{check['validation_without']}, p(worse)={run['gate']['p_worse']})")
        self.store.save()

    def _run_lanes(self, size: int, lanes, outcomes: dict) -> None:
        """`size` practice tasks over parallel lanes. `lanes` = one callable per lane, `lane(work)` runs `work()` in
        that lane's context (its slot, its gate) and returns False when the lane may not work now. The first
        exception (e.g. Yielded) ends the batch after the other lanes finish their current task."""
        left = {"n": size}
        errors: list[BaseException] = []

        def worker(lane):
            while True:
                with self._lock:
                    if errors or left["n"] <= 0:
                        return
                    task = self.next_task()
                    if task is None:
                        return
                    left["n"] -= 1
                    self._in_flight.add(task["id"])

                def work(task=task):
                    with self._lock:
                        try:
                            outcome = self.run_item(task)
                            outcomes[outcome] = outcomes.get(outcome, 0) + 1
                            self.store.state["items_since_recheck"] = self.store.state.get("items_since_recheck", 0) + 1
                        finally:
                            self._in_flight.discard(task["id"])
                try:
                    if not lane(work):
                        with self._lock:
                            self._in_flight.discard(task["id"])
                            left["n"] += 1
                        return
                except BaseException as exc:          # noqa: BLE001 - handed to the caller below
                    with self._lock:
                        self._in_flight.discard(task["id"])
                        errors.append(exc)
                    return
        self._parallel = True
        try:
            threads = [threading.Thread(target=worker, args=(lane,), daemon=True) for lane in lanes]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
        finally:
            self._parallel = False
        if errors:
            raise errors[0]

    def run_batch(self, size: int | None = None, *, before_item=lambda: True, lanes=None) -> dict:
        """`size` practice tasks, then promotions and (when due) the recheck. `before_item()` is the idle check:
        it is asked before every task and may block; False stops the batch. `lanes` (two or more callables, see
        _run_lanes) practise several tasks at once; promotions and rechecks stay single-lane."""
        outcomes: dict[str, int] = {}
        state = self.store.state
        if lanes and len(lanes) > 1:
            self._run_lanes(size or self.settings.batch, lanes, outcomes)
        else:
            for _ in range(size or self.settings.batch):
                task = self.next_task()
                if task is None or not before_item():
                    break
                outcome = self.run_item(task)
                outcomes[outcome] = outcomes.get(outcome, 0) + 1
                state["items_since_recheck"] = state.get("items_since_recheck", 0) + 1
        if before_item():
            if not state["validation"] and self.validation and state["counters"].get("tasks_tried", 0):
                self.measure(self.active(), "first baseline")
            self.consider_promotions()
            if state.get("items_since_recheck", 0) >= self.settings.recheck_every:
                state["items_since_recheck"] = 0
                self.recheck()
        state["batches"] = state.get("batches", 0) + 1
        state["last_batch"] = utc()
        self.store.save()
        return outcomes


_PRIVATE = re.compile(r"\b(?:10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2}"
                      r"|127(?:\.\d{1,3}){3})\b")
_KEYLIKE = re.compile(r"\b(?:sk-|ghp_|github_pat_|Bearer\s+)[A-Za-z0-9_\-.]{8,}|\b[A-Fa-f0-9]{40,}\b|\b[A-Za-z0-9_\-]{48,}\b")


def scrub(text: str) -> str:
    """No private address and nothing that looks like a key in a file that leaves the server."""
    return _KEYLIKE.sub("<removed>", _PRIVATE.sub("<address>", text))
