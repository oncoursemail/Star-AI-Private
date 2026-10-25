"""The gate: does a proposed change make STAR better, or at least no worse, on the golden tasks?

A change (a new skill pack, a routing rule, a prompt edit, a tool recipe) is first run through the
suite with `python -m star.evals run`; the gate then compares that result with the stored baseline:

    python -m star.evals gate --baseline evals/results/baseline-v2.json --candidate evals/results/change.json

Exit status:
    0  allowed: no previously passing task fails and the pass count did not drop
    1  blocked: the pass count dropped, or a previously passing task now fails
    2  unusable input: different suite, unreadable file, nothing to compare
    3  incomplete: tasks are missing or errored in the candidate run, so no verdict can be given
    4  inconclusive (paired mode only): powered for the smallest effect of interest and not significant ("no effect
       of that size"); never allowed
    5  underpowered (paired mode only): not significant and the design could not have detected the smallest effect
       of interest with 80 % power ("not enough power": more tasks or samples needed); never allowed

Paired-session mode (W1, `star/eval_stats.py`) is the honest gate: baseline and candidate are run in the SAME session,
interleaved, k times each (k >= 2 recommended), and compared pair by pair with an exact sign test; the minimum
detectable effect is printed next to the verdict. Only a significant improvement is ALLOWED (PROMOTE); a significant
loss or a reproducible canary failure is BLOCKED (REJECT); a non-significant result is UNDERPOWERED (exit 5) when the
design lacked power for `--smallest-effect` and INCONCLUSIVE (exit 4) when it had it; neither promotes:

    python -m star.evals gate --paired-session --baseline base-1.json base-2.json --candidate cand-1.json cand-2.json

Stored baselines from another day are refused in paired mode. The single-file mode below is kept for legacy files.

Comparing two models (e.g. a star-fast candidate preset against star-fast) needs `--allow-model-change` (paired mode
only): the two arms may then name different models, each arm must still be one model, and every other rule and the
statistics are unchanged.

Only tasks scored (`pass` or `fail`) in the baseline take part. Tasks that errored (server down) are
never counted as failures, but they also never count as passes: the gate says "incomplete" instead.

Self-improvement code calls `evaluate_change(...)` or `gate_change(...)` and must refuse to enable a
change whose `Verdict.allowed` is False. Nothing here runs a model; it only reads result files.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime
import json
from pathlib import Path

from . import eval_stats

ALLOWED, BLOCKED, UNUSABLE, INCOMPLETE, INCONCLUSIVE, UNDERPOWERED = 0, 1, 2, 3, 4, 5
_HEADS = {ALLOWED: "ALLOWED", BLOCKED: "BLOCKED", UNUSABLE: "UNUSABLE INPUT", INCOMPLETE: "INCOMPLETE",
          INCONCLUSIVE: "INCONCLUSIVE", UNDERPOWERED: "NOT ENOUGH POWER"}
_PAIRED_CODE = {eval_stats.PROMOTE: ALLOWED, eval_stats.REJECT: BLOCKED, eval_stats.INCONCLUSIVE: INCONCLUSIVE,
                eval_stats.INCOMPLETE: INCOMPLETE, eval_stats.UNDERPOWERED: UNDERPOWERED}
_LEGACY = {"baseline-v2.json", "baseline-creation-v1.json"}
_VALID_STATUS = {"pass", "fail", "error", "skipped"}
_SCORED = ("pass", "fail")


class _LoadedResult(dict):
    """Result read by this module; caller-provided dicts cannot assert legacy status."""


def _trusted_legacy(result: dict) -> bool:
    return isinstance(result, _LoadedResult) and result.get("_legacy") is True


@dataclass
class Verdict:
    code: int
    baseline_pass: int = 0
    candidate_pass: int = 0
    compared: int = 0
    regressions: list[str] = field(default_factory=list)
    improvements: list[str] = field(default_factory=list)
    incomplete: list[str] = field(default_factory=list)       # errored in the candidate run: no verdict possible
    not_covered: list[str] = field(default_factory=list)      # not run at all (allowed for a targeted run)
    flaky: list[str] = field(default_factory=list)            # failed once, passed on the confirming re-run
    notes: list[str] = field(default_factory=list)
    paired: dict = field(default_factory=dict)                # paired-session statistics (eval_stats.PairedReport)
    paired_text: str = ""

    @property
    def allowed(self) -> bool:
        return self.code == ALLOWED

    def to_dict(self) -> dict:
        return {"allowed": self.allowed, "exit_code": self.code, "baseline_pass": self.baseline_pass,
                "candidate_pass": self.candidate_pass, "compared": self.compared,
                "regressions": self.regressions, "improvements": self.improvements,
                "incomplete": self.incomplete, "not_covered": self.not_covered, "flaky": self.flaky,
                "notes": self.notes, **({"paired": self.paired} if self.paired else {})}

    def text(self) -> str:
        head = _HEADS[self.code]
        if self.paired_text:
            lines = [f"gate: {head} (paired session)", self.paired_text]
            lines.extend("  note: " + n for n in self.notes)
            return "\n".join(lines)
        lines = [f"gate: {head} - {self.candidate_pass}/{self.compared} pass vs baseline {self.baseline_pass}/{self.compared} "
                 f"on the {self.compared} tasks scored in both"]
        for label, ids in (("regressions (passed before, fail now)", self.regressions),
                           ("improvements", self.improvements),
                           ("errored in the candidate run", self.incomplete),
                           ("not covered by the candidate run", self.not_covered),
                           ("failed once but passed on re-run (flaky)", self.flaky)):
            if ids:
                lines.append(f"  {label}: {', '.join(sorted(ids))}")
        lines.extend("  note: " + n for n in self.notes)
        return "\n".join(lines)


def load_result(path) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} is not an evaluation result file")
    stored = Path(path).resolve()
    shipped = Path(__file__).resolve().parents[1] / "evals" / "results"
    data = {**data, "_legacy": stored.parent == shipped and stored.name in _LEGACY}
    return _LoadedResult(data)


def _trial_summary(result: dict) -> bool:
    """The frontier lab passes paired in-memory statuses, not persisted runner files."""
    return (isinstance(result, dict) and set(result) == {"suite", "tasks"}
            and isinstance(result["suite"], dict) and set(result["suite"]) == {"sha256"}
            and isinstance(result["suite"]["sha256"], str)
            and bool(result["suite"]["sha256"])
            and isinstance(result["tasks"], dict)
            and all(isinstance(tid, str) and bool(tid)
                    and isinstance(row, dict) and set(row) == {"status"}
                    and isinstance(row["status"], str) and row["status"] in _VALID_STATUS
                    for tid, row in result["tasks"].items()))


def _validate(result: dict, label: str) -> list[str]:
    if not isinstance(result, dict):
        return [f"{label}: expected a result object"]
    suite, run, tasks = result.get("suite"), result.get("run"), result.get("tasks")
    if not isinstance(suite, dict) or not isinstance(run, dict) or not isinstance(tasks, dict):
        return [f"{label}: suite, run and tasks must be objects"]
    problems = []
    if result.get("schema") != 1:
        problems.append(f"{label}: unsupported result schema")
    for key in ("sha256", "file"):
        if not isinstance(suite.get(key), str) or not suite[key].strip():
            problems.append(f"{label}: missing suite.{key}")
    if type(suite.get("tasks_total")) is not int or suite["tasks_total"] < 1:
        problems.append(f"{label}: invalid suite.tasks_total")
    if type(suite.get("automated")) is not int or suite["automated"] < 0:
        problems.append(f"{label}: invalid suite.automated")
    selected = suite.get("selected")
    if not isinstance(selected, list) or any(not isinstance(t, str) or not t for t in selected) or len(set(selected)) != len(selected):
        problems.append(f"{label}: invalid suite.selected")
    for key in ("model", "mode", "app_commit"):
        if not isinstance(run.get(key), str) or not run[key].strip():
            problems.append(f"{label}: missing run.{key}")
    for key in ("identity_sha256",):
        if not isinstance(suite.get(key), str) or not suite[key].strip():
            if _trusted_legacy(result):
                problems.append(f"{label}: legacy result missing suite.{key}; compatibility allowed")
            else:
                problems.append(f"{label}: missing suite.{key}")
    if not isinstance(run.get("grader_sha256"), str) or not run.get("grader_sha256"):
        if _trusted_legacy(result):
            problems.append(f"{label}: legacy result missing run.grader_sha256; compatibility allowed")
        else:
            problems.append(f"{label}: missing run.grader_sha256")
    if not tasks:
        problems.append(f"{label}: empty tasks")
    for tid, record in tasks.items():
        if not isinstance(tid, str) or not tid or not isinstance(record, dict):
            problems.append(f"{label}: invalid task row {tid!r}")
            continue
        status = record.get("status")
        if not isinstance(status, str) or status not in _VALID_STATUS:
            problems.append(f"{label}: {tid}: invalid status {status!r}")
        if "passed" in record and (not isinstance(record["passed"], bool)
                                    or (status == "pass" and not record["passed"])
                                    or (status == "fail" and record["passed"])):
            problems.append(f"{label}: {tid}: inconsistent passed flag")
        if status in _SCORED and not _trusted_legacy(result):
            for key in ("passed", "reasons", "checks"):
                if key not in record:
                    problems.append(f"{label}: {tid}: missing {key}")
        if status == "error" and record.get("passed") is True:
            problems.append(f"{label}: {tid}: errored task cannot pass")
        if status in _SCORED and isinstance(selected, list) and tid not in selected:
            problems.append(f"{label}: {tid}: scored task not in suite.selected")
        if "checks" in record and (not isinstance(record["checks"], list)
                                   or any(not isinstance(c, dict) or not isinstance(c.get("id"), str)
                                          or not isinstance(c.get("ok"), bool) for c in record["checks"])):
            problems.append(f"{label}: {tid}: malformed checks")
        if "reasons" in record and (not isinstance(record["reasons"], list)
                                    or any(not isinstance(x, str) for x in record["reasons"])):
            problems.append(f"{label}: {tid}: malformed reasons")
    return problems


def _errors(result: dict, label: str) -> tuple[list[str], list[str]]:
    problems = _validate(result, label)
    return ([p for p in problems if "legacy result" not in p],
            [p for p in problems if "legacy result" in p])


def _status(result: dict, task_id: str) -> str:
    record = result["tasks"].get(task_id)
    return record.get("status", "missing") if isinstance(record, dict) else "missing"


def compare(baseline: dict, candidate: dict, *, allow_partial: bool = False) -> Verdict:
    """Pure comparison of two result dicts."""
    summary = _trial_summary(baseline) and _trial_summary(candidate)
    if summary:
        if baseline["suite"]["sha256"] != candidate["suite"]["sha256"]:
            return Verdict(UNUSABLE, notes=["the paired trial suite differs"])
        base_errors, base_legacy, cand_errors, cand_legacy = [], [], [], []
    else:
        base_errors, base_legacy = _errors(baseline, "baseline")
        cand_errors, cand_legacy = _errors(candidate, "candidate")
    if base_errors or cand_errors:
        return Verdict(UNUSABLE, notes=base_errors + cand_errors)
    for key in (() if summary else ("sha256", "file", "tasks_total", "automated")):
        if baseline["suite"].get(key) != candidate["suite"].get(key):
            return Verdict(UNUSABLE, notes=[f"suite {key} differs: not a like-for-like comparison"])
    if not summary and not base_legacy and not cand_legacy and baseline["suite"]["identity_sha256"] != candidate["suite"]["identity_sha256"]:
        return Verdict(UNUSABLE, notes=["suite identity differs (including grader materials)"])
    for key in (() if summary else ("model", "mode")):
        if baseline["run"][key] != candidate["run"][key]:
            return Verdict(UNUSABLE, notes=[f"{key} differs: not a like-for-like comparison"])
    if not summary and not base_legacy and not cand_legacy and baseline["run"]["grader_sha256"] != candidate["run"]["grader_sha256"]:
        return Verdict(UNUSABLE, notes=["grader revision differs: re-score with matching graders first"])
    scored = [tid for tid in baseline["tasks"] if _status(baseline, tid) in _SCORED]
    if not scored:
        return Verdict(UNUSABLE, notes=["the baseline has no scored tasks"])
    verdict = Verdict(ALLOWED, notes=base_legacy + cand_legacy)
    for tid in scored:
        before, after = _status(baseline, tid), _status(candidate, tid)
        if after in _SCORED:
            verdict.compared += 1
            verdict.baseline_pass += before == "pass"
            verdict.candidate_pass += after == "pass"
            if before == "pass" and after == "fail":
                verdict.regressions.append(tid)
            elif before == "fail" and after == "pass":
                verdict.improvements.append(tid)
        elif after == "missing":
            verdict.not_covered.append(tid)
        else:
            verdict.incomplete.append(tid)
    if not verdict.compared:
        return Verdict(UNUSABLE, incomplete=verdict.incomplete, not_covered=verdict.not_covered,
                       notes=["the candidate run scored none of the baseline's tasks"])
    if verdict.not_covered and allow_partial:
        verdict.notes.append(f"targeted run: {len(verdict.not_covered)} baseline tasks were not run by the candidate")
    if verdict.regressions or verdict.candidate_pass < verdict.baseline_pass:
        verdict.code = BLOCKED
        if verdict.candidate_pass < verdict.baseline_pass:
            verdict.notes.append("the pass count dropped")
    elif verdict.incomplete or (verdict.not_covered and not allow_partial):
        verdict.code = INCOMPLETE
    return verdict


def evaluate_change(baseline, candidate, *, allow_partial: bool = False) -> Verdict:
    """Compare result files (paths) or dicts. Unreadable input gives code 2 instead of raising."""
    try:
        base = baseline if isinstance(baseline, dict) else load_result(baseline)
        cand = candidate if isinstance(candidate, dict) else load_result(candidate)
    except (OSError, ValueError, TypeError) as exc:
        return Verdict(UNUSABLE, notes=[f"cannot read results: {exc}"])
    return compare(base, cand, allow_partial=allow_partial)


def gate_change(baseline, run_candidate, *, rerun=None, allow_partial: bool = False) -> Verdict:
    """Run a proposed change through the gate end to end.

    `run_candidate()` returns the candidate result dict (the suite run with the change enabled).
    `rerun(task_ids)` optionally returns a result dict for just those tasks; a regression that passes
    on the re-run is reported as flaky and does not block. Without it every regression blocks.
    """
    try:
        base = baseline if isinstance(baseline, dict) else load_result(baseline)
        candidate = run_candidate()
    except (OSError, ValueError, TypeError) as exc:
        return Verdict(UNUSABLE, notes=[f"unusable input: {exc}"])
    verdict = compare(base, candidate, allow_partial=allow_partial)
    if verdict.regressions and rerun is not None:
        try:
            again = rerun(list(verdict.regressions))
        except (OSError, ValueError, TypeError) as exc:
            return Verdict(UNUSABLE, notes=[f"cannot read rerun: {exc}"])
        summary = _trial_summary(candidate) and _trial_summary(again)
        errors, legacy = ([], []) if summary else _errors(again, "rerun")
        if errors or legacy:
            return Verdict(UNUSABLE, notes=errors + legacy)
        for key in (("sha256",) if summary else ("sha256", "file", "tasks_total", "automated", "identity_sha256")):
            if again["suite"].get(key) != candidate["suite"].get(key):
                return Verdict(UNUSABLE, notes=[f"rerun suite {key} differs"])
        for key in (() if summary else ("model", "mode", "app_commit", "grader_sha256")):
            if again["run"].get(key) != candidate["run"].get(key):
                return Verdict(UNUSABLE, notes=[f"rerun {key} differs"])
        if any(t not in again["tasks"] for t in verdict.regressions):
            return Verdict(UNUSABLE, notes=["rerun omitted a regression task"])
        confirmed = [t for t in verdict.regressions if _status(again, t) != "pass"]
        flaky = [t for t in verdict.regressions if t not in confirmed]
        merged = {**candidate, "tasks": {**candidate["tasks"], **{t: again["tasks"][t] for t in flaky}}}
        verdict = compare(base, merged, allow_partial=allow_partial)
        verdict.flaky = flaky
        if flaky:
            verdict.notes.append("regressions that passed on the confirming re-run are treated as noise")
    return verdict


# --- paired-session mode (W1) ---------------------------------------------------------------------------------

_SAMPLE = {"pass": True, "fail": False}
MAX_SESSION_HOURS = 36.0


def _when(value) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else None


def compare_paired(baseline_runs: list, candidate_runs: list, *, alpha: float = eval_stats.DEFAULT_ALPHA,
                   method: str = "sign", canary=(), seed: int = 0, allow_partial: bool = False,
                   max_session_hours: float = MAX_SESSION_HOURS, allow_model_change: bool = False,
                   smallest_effect: float = eval_stats.DEFAULT_SMALLEST_EFFECT, pool=None,
                   noise_discordance: float = eval_stats.DEFAULT_NOISE_DISCORDANCE) -> Verdict:
    """Paired verdict from k result files per arm that were run in the same session.

    Sample j of the baseline (the j-th run by start time) is paired with sample j of the candidate. All runs must be
    the same suite, identity, grader, model and mode, carry `run.started_at`, and fall inside `max_session_hours`.
    Stored legacy baselines are refused: the point of this mode is a baseline measured next to the candidate.
    `allow_model_change` lets the candidate arm name another model than the baseline arm (model comparisons); the
    runs inside each arm must still agree, and nothing else changes."""
    if not isinstance(baseline_runs, list) or not isinstance(candidate_runs, list) or not baseline_runs or not candidate_runs:
        return Verdict(UNUSABLE, notes=["paired mode needs at least one run per arm"])
    problems: list[str] = []
    runs = ([("baseline", i, r) for i, r in enumerate(baseline_runs)]
            + [("candidate", i, r) for i, r in enumerate(candidate_runs)])
    for arm, index, run in runs:
        label = f"{arm} run {index + 1}"
        if _trusted_legacy(run):
            problems.append(f"{label}: a stored legacy baseline cannot be one arm of a paired session")
            continue
        errors, legacy = _errors(run, label)
        problems.extend(errors + legacy)
    if problems:
        return Verdict(UNUSABLE, notes=problems)
    first = baseline_runs[0]
    for arm, index, run in runs:
        for key in ("sha256", "file", "tasks_total", "automated", "identity_sha256"):
            if run["suite"].get(key) != first["suite"].get(key):
                return Verdict(UNUSABLE, notes=[f"{arm} run {index + 1}: suite {key} differs: not a like-for-like comparison"])
        for key in ("model", "mode", "grader_sha256"):
            # With allow_model_change the model is compared within each arm: the arm's first run is the reference.
            same_as = (candidate_runs[0] if allow_model_change and key == "model" and arm == "candidate" else first)
            if run["run"].get(key) != same_as["run"].get(key):
                return Verdict(UNUSABLE, notes=[f"{arm} run {index + 1}: {key} differs: not a like-for-like comparison"])
    starts = {}
    for arm, index, run in runs:
        when = _when(run["run"].get("started_at"))
        if when is None:
            return Verdict(UNUSABLE, notes=[f"{arm} run {index + 1}: paired mode needs run.started_at (with a time zone)"])
        starts[(arm, index)] = when
    ends = [(_when(run["run"].get("finished_at")) or starts[(arm, index)]) for arm, index, run in runs]
    span = (max(ends + list(starts.values())) - min(starts.values())).total_seconds() / 3600
    if span > max_session_hours:
        return Verdict(UNUSABLE, notes=[f"the runs span {span:.1f} h, more than one session ({max_session_hours:g} h): "
                                        "run both arms again, interleaved"])
    base_order = [baseline_runs[i] for i in sorted(range(len(baseline_runs)), key=lambda i: starts[("baseline", i)])]
    cand_order = [candidate_runs[i] for i in sorted(range(len(candidate_runs)), key=lambda i: starts[("candidate", i)])]
    notes = []
    if first["run"].get("model") != candidate_runs[0]["run"].get("model"):
        notes.append(f"model comparison (allow-model-change): baseline {first['run'].get('model')}, "
                     f"candidate {candidate_runs[0]['run'].get('model')}")
    arms_in_order = [arm for arm, _ in sorted(starts, key=lambda key: starts[key])]
    switches = sum(1 for a, b in zip(arms_in_order, arms_in_order[1:]) if a != b)
    if len(baseline_runs) >= 2 and len(candidate_runs) >= 2 and switches <= 1:
        notes.append("the arms were run in blocks, not interleaved: drift between the blocks is not cancelled")
    commits = {run["run"].get("app_commit") for run in base_order + cand_order}
    if len(commits) > 1:
        notes.append("app commits differ between the runs (expected when the change is code): "
                     + ", ".join(sorted(str(c) for c in commits)))
    scored = sorted({tid for run in base_order for tid, row in run["tasks"].items()
                     if isinstance(row, dict) and row.get("status") in _SCORED})
    if not scored:
        return Verdict(UNUSABLE, notes=["the baseline runs have no scored tasks"])
    if pool is not None:
        kept = [tid for tid in scored if tid in set(pool)]
        notes.append(f"sensitive task pool: {len(kept)} of {len(scored)} tasks (outcome varied in separate screening runs)")
        scored = kept
        if not scored:
            return Verdict(UNUSABLE, notes=notes + ["the sensitive pool has no task in common with these runs"])
    not_covered = [tid for tid in scored if all(_status(run, tid) == "missing" for run in cand_order)]
    if not_covered and allow_partial:
        notes.append(f"targeted run: {len(not_covered)} baseline tasks were not run by the candidate")
        scored = [tid for tid in scored if tid not in not_covered]
    base_samples = {tid: [_SAMPLE.get(_status(run, tid)) for run in base_order] for tid in scored}
    cand_samples = {tid: [_SAMPLE.get(_status(run, tid)) for run in cand_order] for tid in scored}
    report = eval_stats.paired_decision(base_samples, cand_samples, alpha=alpha, method=method, canary=canary, seed=seed,
                                        smallest_effect=smallest_effect, noise_discordance=noise_discordance)
    code = _PAIRED_CODE[report.decision]
    if not_covered and not allow_partial and code != BLOCKED:
        code = INCOMPLETE
        notes.append("tasks not run by the candidate: no verdict")
    return Verdict(code, baseline_pass=report.baseline_pass, candidate_pass=report.candidate_pass,
                   compared=report.n_tasks, regressions=list(report.regressions),
                   improvements=list(report.improvements), incomplete=list(report.incomplete),
                   not_covered=[] if allow_partial else not_covered, notes=notes, paired=report.to_dict(),
                   paired_text=report.text())


def evaluate_paired(baseline_files, candidate_files, **options) -> Verdict:
    """compare_paired on result files (paths) or dicts; unreadable input gives code 2 instead of raising."""
    try:
        base = [f if isinstance(f, dict) else load_result(f) for f in baseline_files]
        cand = [f if isinstance(f, dict) else load_result(f) for f in candidate_files]
    except (OSError, ValueError, TypeError) as exc:
        return Verdict(UNUSABLE, notes=[f"cannot read results: {exc}"])
    return compare_paired(base, cand, **options)


def gate_paired(run_baseline, run_candidate, *, samples: int = 2, **options) -> Verdict:
    """Run both arms in this session, interleaved, and decide with the paired statistics.

    `run_baseline(j)` / `run_candidate(j)` return the result dict of sample j (the suite run without / with the
    change). The order alternates (B C, C B, B C, ...) so slow drift of the server hits both arms alike.
    Self-improvement code must refuse to enable a change unless `Verdict.allowed` (PROMOTE)."""
    if samples < 1:
        return Verdict(UNUSABLE, notes=["samples must be at least 1"])
    base, cand = [], []
    try:
        for j in range(samples):
            if j % 2 == 0:
                base.append(run_baseline(j))
                cand.append(run_candidate(j))
            else:
                cand.append(run_candidate(j))
                base.append(run_baseline(j))
    except (OSError, ValueError, TypeError) as exc:
        return Verdict(UNUSABLE, notes=[f"unusable input: {exc}"])
    return compare_paired(base, cand, **options)


def screening_samples(runs: list[dict]) -> dict:
    """task id -> outcomes (True pass / False fail) across result files, for eval_stats.sensitive_tasks."""
    out: dict[str, list] = {}
    for run in runs:
        for tid, row in (run.get("tasks") or {}).items():
            if isinstance(row, dict) and row.get("status") in _SCORED:
                out.setdefault(tid, []).append(row["status"] == "pass")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m star.evals gate")
    parser.add_argument("--baseline", required=True, type=Path, nargs="+",
                        help="baseline result file (paired mode: one file per sample)")
    parser.add_argument("--candidate", required=True, type=Path, nargs="+",
                        help="result file of the run with the change enabled (paired mode: one per sample)")
    parser.add_argument("--allow-partial", action="store_true",
                        help="the candidate run covered only the tasks the change can affect")
    parser.add_argument("--paired-session", action="store_true",
                        help="both arms were run in this session, interleaved: decide with the paired sign test")
    parser.add_argument("--alpha", type=float, default=eval_stats.DEFAULT_ALPHA)
    parser.add_argument("--method", choices=["sign", "bootstrap"], default="sign")
    parser.add_argument("--canary", default="", help="comma list of canary task ids (a reproducible failure vetoes)")
    parser.add_argument("--seed", type=int, default=0, help="bootstrap seed (the verdict is deterministic for a seed)")
    parser.add_argument("--max-session-hours", type=float, default=MAX_SESSION_HOURS)
    parser.add_argument("--allow-model-change", action="store_true",
                        help="paired mode only: the candidate arm may use another model than the baseline arm")
    parser.add_argument("--smallest-effect", type=float, default=eval_stats.DEFAULT_SMALLEST_EFFECT,
                        help="smallest improvement worth deciding on, as a share of tasks (paired mode; default 0.10): "
                             "without 80%% power for it a non-significant result is NOT ENOUGH POWER (exit 5)")
    parser.add_argument("--pool-from", type=Path, nargs="+", default=None,
                        help="paired mode: screening result files (separate runs, not the compared ones); decide only "
                             "on tasks whose outcome varied across them (the sensitive task pool)")
    parser.add_argument("--noise-discordance", type=float, default=eval_stats.DEFAULT_NOISE_DISCORDANCE,
                        help="pair discordance with no real change, for the MDE (default 1/6; measured 0.12-0.15)")
    parser.add_argument("--json", action="store_true", help="print the verdict as JSON")
    args = parser.parse_args(argv)
    pool = None
    if args.pool_from:
        if set(map(str, args.pool_from)) & set(map(str, args.baseline + args.candidate)):
            parser.error("--pool-from must name separate screening runs, not the compared ones")
        pool = eval_stats.sensitive_tasks(screening_samples([load_result(p) for p in args.pool_from]))
    if args.paired_session:
        verdict = evaluate_paired(args.baseline, args.candidate, alpha=args.alpha, method=args.method,
                                  canary=[c.strip() for c in args.canary.split(",") if c.strip()], seed=args.seed,
                                  allow_partial=args.allow_partial, max_session_hours=args.max_session_hours,
                                  allow_model_change=args.allow_model_change, smallest_effect=args.smallest_effect,
                                  pool=pool, noise_discordance=args.noise_discordance)
    elif args.allow_model_change:
        parser.error("--allow-model-change needs --paired-session")
    elif len(args.baseline) != 1 or len(args.candidate) != 1:
        parser.error("several files per arm need --paired-session")
    else:
        verdict = evaluate_change(args.baseline[0], args.candidate[0], allow_partial=args.allow_partial)
        verdict.notes.append("legacy single-run gate (no statistics): use --paired-session for promotion decisions")
    print(json.dumps(verdict.to_dict()) if args.json else verdict.text())
    return verdict.code

if __name__ == "__main__":
    raise SystemExit(main())
