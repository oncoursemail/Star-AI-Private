"""Integrity layer for automatic self-improvement (issue #562): no owner clicks, and no way to "improve" by grading
easier.

Star may change its own prompts, settings, lessons, checks and tasks without the owner. A change is promoted only
when every automatic check here passes, and each promotion leaves a receipt with a one-step rollback:

1. **Frozen grader**: the grading code hash must equal the one the sealed holdout was frozen with
   (star/sealed_eval.py). A grader change re-freezes only through `easier_grading` + `rescore_monotonic`.
2. **Impossible-task canaries**: the sealed set holds tasks whose tests contradict their spec. No honest answer passes
   one; a candidate that passes more canaries than the baseline is cheating (or broke the grader) and is refused.
3. **No easier grading**: `easier_grading(old, new)` refuses deleted or edited tasks, fewer assertions, removed
   require/forbid checks, looser answer keys, compile/strict turned off; `gate_config_easier` refuses a looser alpha,
   power, sample count or smallest effect; `rescore_monotonic` refuses a grader that passes stored answers the old one
   failed.
4. **Re-measure on the sealed holdout**: a change that won on the dev suites must also be PROMOTE on the sealed set.
5. **Receipts**: one JSON file per decision (promotion, refusal, rollback) in `STAR_RECEIPTS_DIR`
   (default `~/.star/receipts`), with what changed, the verdicts, the hashes and the rollback values.
6. **Automatic rollback**: `drift_check` compares live results after a promotion with the receipt's baseline; a
   significant drop (or a canary pass) rolls the promoted settings back and writes a rollback receipt.

Promoted settings live in a small overlay file (`STAR_PROMOTIONS_FILE`, default `~/.star/promotions.json`) that the
caller applies on top of its defaults; nothing here edits the app's own settings or calls a model.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path

from . import eval_stats


def _home() -> Path:
    return Path.home() / ".star"


def receipts_dir() -> Path:
    return Path(os.environ.get("STAR_RECEIPTS_DIR") or (_home() / "receipts"))


def promotions_file() -> Path:
    return Path(os.environ.get("STAR_PROMOTIONS_FILE") or (_home() / "promotions.json"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --- 3. no easier grading -------------------------------------------------------------------------------------

def _patterns(auto: dict, key: str) -> set[str]:
    out = set()
    for item in auto.get(key, []) or []:
        if isinstance(item, dict):
            out.add(json.dumps(item.get("any") or item.get("re"), sort_keys=True))
    return out


def _key_looser(old: dict, new: dict) -> list[str]:
    problems = []
    if old.get("type") != new.get("type"):
        problems.append(f"answer type {old.get('type')} -> {new.get('type')}")
        return problems
    if set(map(str, new.get("accept", []))) - set(map(str, old.get("accept", []))):
        problems.append("more accepted answers")
    for name in ("tol", "rel"):
        if float(new.get(name, 0) or 0) > float(old.get(name, 0) or 0):
            problems.append(f"{name} raised")
    if old.get("value") != new.get("value") or old.get("correct") != new.get("correct"):
        problems.append("expected value changed")
    for flag in ("first", "whole"):
        if old.get(flag) and not new.get(flag):
            problems.append(f"'{flag}' removed")
    if int(new.get("min_required", len(new.get("required", [])))) < int(old.get("min_required", len(old.get("required", [])))):
        problems.append("fewer required facts")
    return problems


def easier_grading(old_tasks: list[dict], new_tasks: list[dict], *, old_tests: dict | None = None,
                   new_tests: dict | None = None) -> list[str]:
    """Ways the new task list grades more leniently than the old one ([] = not easier). New tasks are allowed;
    an existing task may only stay identical or get stricter. `old_tests`/`new_tests` map a test file name to its
    text (unit tests that live beside the suite)."""
    problems: list[str] = []
    new_by = {t.get("id"): t for t in new_tasks}
    for old in old_tasks:
        tid = old.get("id")
        new = new_by.get(tid)
        if new is None:
            problems.append(f"{tid}: task deleted")
            continue
        if new == old and not (old_tests or new_tests):
            continue
        if new.get("prompt") != old.get("prompt"):
            problems.append(f"{tid}: prompt edited (add a new task instead)")
        if new.get("run_mode") != old.get("run_mode"):
            problems.append(f"{tid}: run mode changed")
        a, b = old.get("auto") or {}, new.get("auto") or {}
        for flag in ("compile", "code"):
            if a.get(flag, True) and not b.get(flag, True):
                problems.append(f"{tid}: {flag} check turned off")
        if a.get("strict") and not b.get("strict"):
            problems.append(f"{tid}: strict mode turned off")
        if a.get("compile_mode") == "exact" and b.get("compile_mode") != "exact":
            problems.append(f"{tid}: exact compile mode dropped")
        ua, ub = a.get("unit_test") or {}, b.get("unit_test") or {}
        if ua and not ub:
            problems.append(f"{tid}: unit test removed")
        elif ua:
            if int(ub.get("checks") or 0) < int(ua.get("checks") or 0):
                problems.append(f"{tid}: fewer unit-test assertions")
            name_a, name_b = ua.get("file"), ub.get("file")
            if old_tests is not None and new_tests is not None and name_a in old_tests:
                text_a, text_b = old_tests.get(name_a, ""), new_tests.get(name_b, "")
                if text_a not in text_b:
                    problems.append(f"{tid}: unit test edited (assertions may only be added at the end)")
        ja, jb = a.get("judge") or {}, b.get("judge") or {}
        if ja and not jb:
            problems.append(f"{tid}: judge tests removed")
        elif ja:
            if int(jb.get("expect") or 0) < int(ja.get("expect") or 0):
                problems.append(f"{tid}: fewer judge assertions")
            if str(ja.get("tests", "")) not in str(jb.get("tests", "")):
                problems.append(f"{tid}: judge tests edited")
        for key in ("require", "require_any", "forbid"):
            if _patterns(a, key) - _patterns(b, key):
                problems.append(f"{tid}: {key} check removed or changed")
        if a.get("answer"):
            if not b.get("answer"):
                problems.append(f"{tid}: answer key removed")
            else:
                problems.extend(f"{tid}: {p}" for p in _key_looser(a["answer"], b["answer"]))
        if (a.get("citation") or {}).get("required") and not (b.get("citation") or {}).get("required"):
            problems.append(f"{tid}: citation requirement removed")
        if old.get("family") == "canary" and new.get("family") != "canary":
            problems.append(f"{tid}: canary relabelled")
    return problems


# direction: +1 = a larger value is stricter, -1 = a smaller value is stricter
GATE_DIRECTIONS = {"target_power": +1, "samples": +1, "k": +1, "min_tasks": +1, "promote_fixes": +1,
                   "alpha": -1, "gate_alpha": -1, "smallest_effect": -1, "max_session_hours": -1,
                   "noise_discordance": +1}


def gate_config_easier(old: dict, new: dict) -> list[str]:
    """Gate settings made looser ([] = not looser). Unknown keys must not disappear."""
    problems = []
    for key, value in old.items():
        if key not in new:
            problems.append(f"gate setting '{key}' removed")
            continue
        direction = GATE_DIRECTIONS.get(key)
        if direction is None or not isinstance(value, (int, float)) or not isinstance(new[key], (int, float)):
            if direction is None and new[key] != value:
                problems.append(f"gate setting '{key}' changed and its strict direction is unknown")
            continue
        if (new[key] - value) * direction < 0:
            problems.append(f"gate setting '{key}' loosened ({value} -> {new[key]})")
    return problems


def rescore_monotonic(old_status: dict, new_status: dict) -> list[str]:
    """Stored answers scored by the old and the new grader (task id -> 'pass'/'fail'): a task the old grader failed
    and the new grader passes is easier grading."""
    return [f"{tid}: fail -> pass under the new grader" for tid, s in sorted(old_status.items())
            if s == "fail" and new_status.get(tid) == "pass"]


# --- 1 + 2. frozen grader and canaries ---------------------------------------------------------------------------

def canary_alarm(baseline_passes: list[str], candidate_passes: list[str]) -> list[str]:
    extra = sorted(set(candidate_passes) - set(baseline_passes))
    return [f"canary passed (impossible task): {', '.join(extra)}"] if extra else []


# --- 4 + 5. the promotion decision and its receipt ---------------------------------------------------------------

@dataclass
class Decision:
    change: str
    promote: bool
    reasons: list[str] = field(default_factory=list)
    receipt: str = ""


def decide(change: str, *, apply: dict, dev: dict | None, holdout: dict | None, grader: list[str],
           canaries: list[str], easier: list[str], previous: dict | None = None, why: str = "",
           extra: dict | None = None) -> Decision:
    """Promote `apply` (settings overlay values) only if the dev verdict and the sealed-holdout verdict are both
    PROMOTE and no integrity check fired. Always writes a receipt; promotion also writes the overlay."""
    reasons = list(grader) + list(canaries) + list(easier)
    if not dev or dev.get("decision") != eval_stats.PROMOTE:
        reasons.append(f"dev verdict is {(dev or {}).get('decision', 'missing')}, not PROMOTE")
    if not holdout or holdout.get("decision") != eval_stats.PROMOTE:
        reasons.append(f"sealed holdout verdict is {(holdout or {}).get('decision', 'missing')}, not PROMOTE")
    promote = not reasons
    current = read_overlay()
    rollback = previous if previous is not None else {k: current.get(k) for k in apply}
    receipt = {"kind": "promotion" if promote else "refusal", "change": change, "at": _now(), "why": why,
               "apply": apply, "rollback": rollback, "dev": dev, "holdout": holdout,
               "integrity": {"grader": grader, "canaries": canaries, "easier_grading": easier},
               "reasons": reasons, **(extra or {})}
    if promote:
        write_overlay({**current, **apply})
    path = write_receipt(receipt)
    return Decision(change, promote, reasons, str(path))


def write_receipt(receipt: dict) -> Path:
    folder = receipts_dir()
    folder.mkdir(parents=True, exist_ok=True)
    body = json.dumps(receipt, indent=1, sort_keys=True, default=str)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    name = f"{stamp}-{receipt.get('kind', 'receipt')}-{hashlib.sha256(body.encode()).hexdigest()[:8]}.json"
    path = folder / name
    path.write_text(body + "\n", encoding="utf-8")
    return path


def read_overlay() -> dict:
    path = promotions_file()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_overlay(values: dict) -> None:
    path = promotions_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({k: v for k, v in values.items() if v is not None}, indent=1, sort_keys=True) + "\n",
                   encoding="utf-8")
    os.replace(tmp, path)


# --- 6. drift watch and automatic rollback ----------------------------------------------------------------------

def drift_check(receipt: dict, live_pass: int, live_total: int, *, alpha: float = 0.05, margin: float = 0.0,
                live_canary_passes: int = 0) -> list[str]:
    """Breaches after a promotion ([] = healthy). `receipt['holdout']` holds the promoted arm's sealed pass count
    (candidate_pass of samples). A breach is a canary pass, or a live pass rate whose one-sided (1 - alpha) upper
    bound lies below the promoted rate minus `margin`."""
    problems = []
    if live_canary_passes:
        problems.append(f"{live_canary_passes} canary pass(es) in live checks")
    hold = receipt.get("holdout") or {}
    base_pass, base_total = hold.get("candidate_pass"), hold.get("samples") or hold.get("tasks")
    if live_total and base_total and base_pass is not None:
        z = abs(_z(alpha))
        upper = eval_stats.wilson_interval(live_pass, live_total, z=z)[1]
        promised = base_pass / base_total - margin
        if upper < promised:
            problems.append(f"live pass rate {live_pass}/{live_total} is below the promoted {base_pass}/{base_total} "
                            f"(upper bound {upper:.3f} < {promised:.3f})")
    return problems


def _z(alpha: float) -> float:
    from statistics import NormalDist
    return NormalDist().inv_cdf(1 - alpha)


def rollback(receipt_path: Path, problems: list[str]) -> Path:
    """Restore the overlay values the promotion replaced and write a rollback receipt."""
    receipt = json.loads(Path(receipt_path).read_text(encoding="utf-8"))
    overlay = read_overlay()
    for key, value in (receipt.get("rollback") or {}).items():
        if value is None:
            overlay.pop(key, None)
        else:
            overlay[key] = value
    write_overlay(overlay)
    return write_receipt({"kind": "rollback", "change": receipt.get("change"), "at": _now(), "of": str(receipt_path),
                          "restored": receipt.get("rollback"), "problems": problems})


def watch(receipt_path: Path, live_pass: int, live_total: int, **options) -> dict:
    """drift_check, then roll back automatically on a breach (no owner step)."""
    receipt = json.loads(Path(receipt_path).read_text(encoding="utf-8"))
    problems = drift_check(receipt, live_pass, live_total, **options)
    if problems:
        return {"healthy": False, "problems": problems, "rollback_receipt": str(rollback(Path(receipt_path), problems))}
    return {"healthy": True, "problems": []}


def _promote(args) -> int:
    """`promote`: the sealed set must be intact with its frozen grader, the candidate may not pass more canaries,
    and both the dev verdict and the sealed-holdout re-measure must be PROMOTE; then decide() writes the receipt."""
    from . import sealed_eval as se
    manifest = json.loads(se.manifest_path(args.set).read_text(encoding="utf-8"))
    grader = se.verify(args.set, manifest=manifest) or se.grader_problems(manifest)
    folder = se.set_dir(args.set) / "results"
    base = [json.loads((folder / f"{n}.json").read_text(encoding="utf-8")) for n in args.baseline]
    cand = [json.loads((folder / f"{n}.json").read_text(encoding="utf-8")) for n in args.candidate]
    canaries = canary_alarm(sorted({t for r in base for t in se.canary_passes(r, manifest)}),
                            sorted({t for r in cand for t in se.canary_passes(r, manifest)}))
    families = [f for f in args.families.split(",") if f] or None
    report = se.paired_report(base, cand, manifest, families=families)
    holdout = {**report["summary"], "candidate_pass": report["candidate_pass"], "samples": report["samples"]}
    dev_raw = json.loads(args.dev.read_text(encoding="utf-8"))
    dev = dev_raw.get("paired") or dev_raw
    easier = []
    if args.old_suite and args.new_suite:
        easier = easier_grading(json.loads(args.old_suite.read_text(encoding="utf-8")),
                                json.loads(args.new_suite.read_text(encoding="utf-8")))
    apply = {}
    for pair in args.apply:
        name, _, value = pair.partition("=")
        apply[name.strip()] = {"true": True, "false": False}.get(value.strip().lower(), value.strip())
    d = decide(args.change, apply=apply, dev=dev, holdout=holdout, grader=grader, canaries=canaries, easier=easier,
               extra={"sealed_set": {"set": args.set, "set_sha256": manifest.get("set_sha256")}})
    print(json.dumps({"change": d.change, "promote": d.promote, "reasons": d.reasons, "receipt": d.receipt}, indent=1))
    return 0 if d.promote else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m star.integrity", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    eg = sub.add_parser("easier", help="compare two task-list JSON files (old, new): exit 1 when grading got easier")
    eg.add_argument("old", type=Path)
    eg.add_argument("new", type=Path)
    wt = sub.add_parser("watch", help="check live results against a promotion receipt; roll back on a breach")
    wt.add_argument("--receipt", required=True, type=Path)
    wt.add_argument("--live-pass", required=True, type=int)
    wt.add_argument("--live-total", required=True, type=int)
    wt.add_argument("--canary-passes", type=int, default=0)
    pr = sub.add_parser("promote", help="decide a change: dev verdict + sealed-holdout re-measure + integrity checks")
    pr.add_argument("--change", required=True)
    pr.add_argument("--apply", nargs="+", required=True, metavar="NAME=VALUE", help="overlay values to promote")
    pr.add_argument("--dev", required=True, type=Path, help="`python -m star.evals gate --paired-session --json` output")
    pr.add_argument("--set", required=True, help="sealed holdout set id")
    pr.add_argument("--baseline", nargs="+", required=True, help="sealed result names of the baseline arm")
    pr.add_argument("--candidate", nargs="+", required=True, help="sealed result names of the candidate arm")
    pr.add_argument("--families", default="", help="decide on these families only (comma list)")
    pr.add_argument("--old-suite", type=Path, help="with --new-suite: a changed task list to check for easier grading")
    pr.add_argument("--new-suite", type=Path)
    args = parser.parse_args(argv)
    if args.command == "promote":
        return _promote(args)
    if args.command == "easier":
        problems = easier_grading(json.loads(args.old.read_text(encoding="utf-8")),
                                  json.loads(args.new.read_text(encoding="utf-8")))
        print("no easier grading" if not problems else "EASIER GRADING:\n  " + "\n  ".join(problems))
        return 1 if problems else 0
    out = watch(args.receipt, args.live_pass, args.live_total, live_canary_passes=args.canary_passes)
    print(json.dumps(out, indent=1))
    return 0 if out["healthy"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
