"""Sealed blind eval sets: the tasks live outside the repository, a hash manifest lives inside it.

Self-improvement must not be able to tune on its own yardstick. A sealed set's tasks, unit tests, references and
the seeds they were made from are stored in `STAR_SEALED_DIR` (default `~/.star/sealed/<set>/`, next to the keys, never
in a repository, a training folder or a night-school pool). The repository holds only `evals/sealed/<set>.manifest.json`:
per-file SHA-256, per-task digest, family and difficulty counts, the grader hash at freeze time and the power table.
Only this runner reads the tasks, after checking every hash; it reports per-family aggregates, never prompts.

    python -m star.sealed_eval verify  --set eval-power-v1
    python -m star.sealed_eval summary --set eval-power-v1            # counts and MDE, no task content
    python -m star.sealed_eval run     --set eval-power-v1 --name base-1 [eval runner options]
    python -m star.sealed_eval report  --set eval-power-v1 --baseline base-1 --candidate ladder-1

Results go to `<sealed>/<set>/results/` (they hold answers, so they are sealed too).
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path

from . import eval_stats

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_DIR = ROOT / "evals" / "sealed"
SCHEMA = 1
UNHASHED = ("results/",)          # run outputs change; everything else in the set folder is frozen


class SealedError(RuntimeError):
    """The sealed set is missing, changed, or does not match its manifest: no score may be read from it."""


def sealed_root() -> Path:
    return Path(os.environ.get("STAR_SEALED_DIR") or (Path.home() / ".star" / "sealed"))


def set_dir(set_id: str, root: Path | None = None) -> Path:
    if not set_id.replace("-", "").replace("_", "").isalnum():
        raise ValueError("set ids are letters, digits, - and _")
    return (root or sealed_root()) / set_id


def manifest_path(set_id: str) -> Path:
    return MANIFEST_DIR / f"{set_id}.manifest.json"


def file_hashes(folder: Path) -> dict[str, str]:
    out = {}
    for path in sorted(p for p in folder.rglob("*") if p.is_file()):
        rel = path.relative_to(folder).as_posix()
        if rel.startswith(UNHASHED):
            continue
        out[rel] = hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    return out


def digest(hashes: dict[str, str]) -> str:
    return hashlib.sha256(json.dumps(hashes, sort_keys=True).encode("utf-8")).hexdigest()


def task_digest(task: dict) -> str:
    return hashlib.sha256(json.dumps(task, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def scored(task: dict) -> bool:
    """Canaries (impossible tasks) are never part of a score; a pass on one is an integrity alarm."""
    return task.get("family") != "canary"


def build_manifest(set_id: str, folder: Path, *, grader_sha256: str, notes: dict | None = None) -> dict:
    tasks = json.loads((folder / "suite.json").read_text(encoding="utf-8"))
    hashes = file_hashes(folder)
    fam = Counter(t["family"] for t in tasks)
    diff = Counter(f"{t['family']}:{t['difficulty']}" for t in tasks)
    real = [t for t in tasks if scored(t)]
    groups = len({t.get("seed_sha256") or t["id"] for t in real})
    return {
        "schema": SCHEMA, "set": set_id, "files": hashes, "set_sha256": digest(hashes),
        "tasks": [{"id": t["id"], "family": t["family"], "difficulty": t["difficulty"], "scored": scored(t),
                   "sha256": task_digest(t)} for t in tasks],
        "counts": {"tasks": len(tasks), "scored": len(real), "canaries": len(tasks) - len(real),
                   "seed_groups": groups, "families": dict(sorted(fam.items())),
                   "family_difficulty": dict(sorted(diff.items()))},
        "grader_sha256": grader_sha256,
        "power": power_table(len(real), groups),
        **({"notes": notes} if notes else {}),
    }


def power_table(n_tasks: int, n_groups: int | None = None) -> dict:
    """MDE (tasks that must truly flip fail -> pass, 80 % power, alpha 0.05) for k = 1, 2, 3, at the task count and,
    as the pessimistic bound for tasks made from the same seed, at the seed-group count."""
    table = {}
    for k in (1, 2, 3):
        m = eval_stats.minimum_detectable_effect(n_tasks, k)
        row = {"mde_tasks": m.effect_tasks, "mde_share": round(m.effect_tasks / n_tasks, 4) if m.effect_tasks else None}
        if n_groups:
            g = eval_stats.minimum_detectable_effect(n_groups, k)
            row["groups_mde_share"] = round(g.effect_tasks / n_groups, 4) if g.effect_tasks else None
        table[f"k{k}"] = row
    return table


def verify(set_id: str, root: Path | None = None, *, manifest: dict | None = None) -> list[str]:
    """Problems that make the sealed set unusable (empty list = intact)."""
    path = manifest_path(set_id)
    if manifest is None:
        if not path.is_file():
            return [f"no manifest {path.name}"]
        manifest = json.loads(path.read_text(encoding="utf-8"))
    assert manifest is not None
    folder = set_dir(set_id, root)
    if not folder.is_dir():
        return [f"sealed set folder missing ({set_id}); it lives outside the repository"]
    now = file_hashes(folder)
    want = manifest.get("files", {})
    problems = [f"changed: {name}" for name, h in want.items() if name in now and now[name] != h]
    problems += [f"missing: {name}" for name in want if name not in now]
    problems += [f"not in the manifest: {name}" for name in now if name not in want]
    if not problems and digest(now) != manifest.get("set_sha256"):
        problems.append("set hash differs from the manifest")
    if not problems:
        tasks = json.loads((folder / "suite.json").read_text(encoding="utf-8"))
        listed = {row["id"]: row["sha256"] for row in manifest.get("tasks", [])}
        for task in tasks:
            if listed.get(task["id"]) != task_digest(task):
                problems.append(f"task digest differs: {task['id']}")
        if len(tasks) != len(listed):
            problems.append("task count differs from the manifest")
    return problems


def grader_problems(manifest: dict) -> list[str]:
    """Frozen grader: the grading code must be the one the set was frozen with."""
    from .eval_runner import grader_sha256
    current = grader_sha256()
    if manifest.get("grader_sha256") != current:
        return [f"grader changed since the freeze ({str(manifest.get('grader_sha256'))[:12]} -> {current[:12]}): "
                "re-freeze through star.integrity (no-easier-grading check) before scores count"]
    return []


def load(set_id: str, root: Path | None = None):
    """(eval_runner.Suite, manifest) after every hash check; raises SealedError otherwise."""
    from .eval_runner import load_suite
    manifest = json.loads(manifest_path(set_id).read_text(encoding="utf-8"))
    problems = verify(set_id, root, manifest=manifest)
    if problems:
        raise SealedError("; ".join(problems[:6]))
    return load_suite(set_dir(set_id, root) / "suite.json"), manifest


# --- scores -----------------------------------------------------------------------------------------------

def family_scores(result: dict, manifest: dict) -> dict:
    """{family: {pass, scored, error}} plus an 'all' row over scored families and a 'canary' row."""
    fam = {row["id"]: row["family"] for row in manifest["tasks"]}
    out: dict[str, dict] = {}
    for tid, rec in (result.get("tasks") or {}).items():
        family = fam.get(tid)
        if family is None:
            continue
        for key in (family, "all") if family != "canary" else (family,):
            row = out.setdefault(key, {"pass": 0, "scored": 0, "error": 0})
            if rec.get("status") in ("pass", "fail"):
                row["scored"] += 1
                row["pass"] += rec["status"] == "pass"
            elif rec.get("status") == "error":
                row["error"] += 1
    for row in out.values():
        row["rate"] = round(row["pass"] / row["scored"], 4) if row["scored"] else None
    return dict(sorted(out.items()))


def canary_passes(result: dict, manifest: dict) -> list[str]:
    canaries = {row["id"] for row in manifest["tasks"] if row["family"] == "canary"}
    return sorted(t for t, rec in (result.get("tasks") or {}).items() if t in canaries and rec.get("status") == "pass")


def paired_report(baseline: list[dict], candidate: list[dict], manifest: dict, *, families=None,
                  smallest_effect: float = eval_stats.DEFAULT_SMALLEST_EFFECT) -> dict:
    """Paired verdict over the scored tasks both arms answered (optionally only some families), with power."""
    fam = {row["id"]: row["family"] for row in manifest["tasks"] if row["scored"]}
    keep = {t for t, f in fam.items() if families is None or f in families}

    def samples(runs):
        out: dict[str, list] = {}
        for run in runs:
            for tid, rec in (run.get("tasks") or {}).items():
                if tid in keep and rec.get("status") in ("pass", "fail"):
                    out.setdefault(tid, []).append(rec["status"] == "pass")
        return out

    base, cand = samples(baseline), samples(candidate)
    both = sorted(set(base) & set(cand))
    report = eval_stats.paired_decision({t: base[t] for t in both}, {t: cand[t] for t in both},
                                        smallest_effect=smallest_effect)
    return {"tasks": len(both), "families": sorted({fam[t] for t in both}), "summary": report.summary(),
            "text": report.text()}


# --- command line ---------------------------------------------------------------------------------------

def _redacted_log(line: str) -> None:
    """Progress without content: '[n/N] <id> <status> <seconds>s' and the runner's own notes, no reasons."""
    if line.startswith("["):
        print(" ".join(line.split()[:4]), flush=True)
    elif "lock" in line or "planner" in line or "stopped" in line or "selected" in line:
        print(line[:200], flush=True)


def _results(set_id: str, names: list[str]) -> list[dict]:
    folder = set_dir(set_id) / "results"
    return [json.loads((folder / f"{n}.json").read_text(encoding="utf-8")) for n in names]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m star.sealed_eval", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("verify", "summary"):
        p = sub.add_parser(name)
        p.add_argument("--set", required=True)
    run = sub.add_parser("run", help="run the sealed set through STAR (eval runner options after the set)")
    run.add_argument("--set", required=True)
    run.add_argument("--name", required=True, help="result name (stored in the sealed results folder)")
    run.add_argument("--tasks", default="", help="comma list of task ids (default: all)")
    rep = sub.add_parser("report", help="per-family scores and the paired verdict of two (or 2k) result names")
    rep.add_argument("--set", required=True)
    rep.add_argument("--baseline", nargs="+", required=True)
    rep.add_argument("--candidate", nargs="+", required=True)
    rep.add_argument("--families", default="", help="comma list: decide on these families only")
    args, rest = parser.parse_known_args(argv)

    if args.command == "verify":
        problems = verify(args.set)
        manifest = json.loads(manifest_path(args.set).read_text(encoding="utf-8")) if manifest_path(args.set).is_file() else {}
        problems += grader_problems(manifest) if manifest and not problems else []
        print("sealed set " + args.set + ": " + ("INTACT" if not problems else "PROBLEMS\n  " + "\n  ".join(problems[:20])))
        return 0 if not problems else 1
    manifest = json.loads(manifest_path(args.set).read_text(encoding="utf-8"))
    if args.command == "summary":
        print(json.dumps({"set": args.set, "counts": manifest["counts"], "power": manifest["power"],
                          "grader_sha256": manifest["grader_sha256"][:12]}, indent=1))
        return 0
    if args.command == "report":
        base, cand = _results(args.set, args.baseline), _results(args.set, args.candidate)
        fams = [f for f in args.families.split(",") if f] or None
        out = {"baseline": [family_scores(r, manifest) for r in base],
               "candidate": [family_scores(r, manifest) for r in cand],
               "canary_passes": {"baseline": [canary_passes(r, manifest) for r in base],
                                 "candidate": [canary_passes(r, manifest) for r in cand]},
               "paired": paired_report(base, cand, manifest, families=fams)}
        print(json.dumps({k: v for k, v in out.items() if k != "paired"}, indent=1))
        print(out["paired"]["text"])
        return 0
    # run
    from .eval_runner import add_common, build_real, run_suite
    suite, manifest = load(args.set)
    problems = grader_problems(manifest)
    if problems:
        print("refused: " + problems[0])
        return 2
    inner = argparse.ArgumentParser(prog="sealed run")
    add_common(inner)
    inner_args = inner.parse_args(["--suite", str(suite.path), *rest])
    inner_args._suite = suite
    run_info, ask, scorer, probe, secrets = build_real(inner_args, log=_redacted_log)
    run_info["sealed_set"] = {"set": args.set, "set_sha256": manifest["set_sha256"]}
    out = set_dir(args.set) / "results" / f"{args.name}.json"
    ids = [x for x in args.tasks.split(",") if x] or None
    result = run_suite(suite, out=out, ask=ask, scorer=scorer, lock_probe=probe, run_info=run_info, task_ids=ids,
                       secrets=secrets, log=_redacted_log)
    print(json.dumps(family_scores(result, manifest)))
    return 0 if result.get("complete") else 2


if __name__ == "__main__":
    raise SystemExit(main())
