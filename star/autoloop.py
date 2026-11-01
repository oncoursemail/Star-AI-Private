"""The self-improvement loop closed end to end, with no owner clicks (#562, #555 B6).

star/integrity.py decides a change (sealed set intact, frozen grader, canaries, dev + sealed-holdout PROMOTE), writes
a receipt and the promotions overlay, and rolls the overlay back on drift. Until now nothing read the overlay, and
nothing ran the decision or the drift watch by itself. This module adds both ends:

* live: `apply_promotions(settings)` (called by desktop_core.Settings.load) puts the overlay's values on top of the
  saved settings, for LIVE_KEYS only: answer-path tuning switches the eval runner can A/B (`--set`) and the owner's
  settings page does not show, so no owner choice is overridden and no permission can change. A value of the wrong
  type, or one Settings.validate refuses, is ignored. `unpromoted()` (Settings.save) writes the code default instead
  of a promoted value, so a rollback takes effect at the next load. STAR_AUTO_PROMOTIONS=0 turns live use off.
* cycle: safe to run after every sealed run (the eval driver calls it; repeated calls do nothing new):

      python -m star.autoloop cycle --set eval-power-v1 [--arm base-1 --arm ladder-1 --dev gate.json --families f1,f2]

  1. decide (when two arms are given): two finished sealed runs that differ only in LIVE_KEYS. The arm that matches
     the live values is the baseline, the other is the candidate change. integrity.decide checks it and writes one
     receipt per experiment (the same arms, dev file and families are never decided twice).
  2. watch (always): each active promotion is re-measured on later sealed runs made with the promoted values; a drop
     below the promoted rate, or a canary pass, rolls it back (integrity.watch) and writes a rollback receipt.
"""
from __future__ import annotations

import argparse
from dataclasses import fields, replace
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path

# Tunable answer-path switches: a subset of eval_runner._SETTABLE (measurable) that is not in
# react_shell.PERMITTED_SETTINGS (owner-facing). tests/test_autoloop.py keeps both true.
LIVE_KEYS = frozenset({"verify_ladder", "verify_rounds", "verify_budget_s", "verify_retry", "mistake_memory",
                       "thinking_budget", "api_hints_enabled", "slop_check"})
MIN_LIVE = 20                    # scored tasks a later run must have before the watch judges a promotion
SAME_CONDITIONS = ("provider", "model", "mode", "skill_packs", "knowledge", "temperature")


def _enabled() -> bool:
    return os.environ.get("STAR_AUTO_PROMOTIONS", "1").strip().lower() not in ("0", "off", "false", "no")


def _defaults(cls) -> dict:
    return {f.name: f.default for f in fields(cls) if f.name in LIVE_KEYS}


def promoted_values(cls) -> dict:
    """Overlay entries that may go live for this Settings class: a live key, the field's type, a valid value."""
    from .integrity import read_overlay
    defaults = _defaults(cls)
    values = {k: v for k, v in read_overlay().items() if k in defaults and type(v) is type(defaults[k])}
    good = {}
    for key, value in values.items():
        try:
            replace(cls(), **{key: value}).validate()
        except (ValueError, TypeError):
            continue
        good[key] = value
    return good


def apply_promotions(settings):
    """`settings` with the promoted values on top (the same object when nothing is promoted or live use is off)."""
    if not _enabled():
        return settings
    values = promoted_values(type(settings))
    return replace(settings, **values) if values else settings


def unpromoted(data: dict, cls) -> dict:
    """Settings.save: a value equal to its promotion is stored as the code default, so a rollback is not undone by a
    saved copy of the promoted value."""
    if not _enabled():
        return data
    defaults = _defaults(cls)
    return {**data, **{k: defaults[k] for k, v in promoted_values(cls).items() if data.get(k) == v}}


# --- the cycle -----------------------------------------------------------------------------------------------

def _arm_values(run: dict, defaults: dict) -> dict:
    settings = (run.get("run") or {}).get("settings") or {}
    return {k: settings.get(k, defaults[k]) for k in defaults}


def _other_settings(run: dict) -> dict:
    info = run.get("run") or {}
    return {"settings": {k: v for k, v in (info.get("settings") or {}).items() if k not in LIVE_KEYS},
            **{k: info.get(k) for k in SAME_CONDITIONS}}


def _receipts() -> list[tuple[Path, dict]]:
    from .integrity import receipts_dir
    out = []
    for path in sorted(receipts_dir().glob("*.json")):
        try:
            out.append((path, json.loads(path.read_text(encoding="utf-8"))))
        except (OSError, ValueError):
            continue
    return out


def decide_experiment(set_id: str, arm_a: list[str], arm_b: list[str], *, dev_file: Path | None,
                      families: list[str] | None, settings_cls) -> dict:
    from . import integrity, sealed_eval as se
    manifest = json.loads(se.manifest_path(set_id).read_text(encoding="utf-8"))
    folder = se.set_dir(set_id) / "results"
    runs = {name: json.loads((folder / f"{name}.json").read_text(encoding="utf-8")) for name in arm_a + arm_b}
    if not all(run.get("complete") for run in runs.values()):
        return {"decided": False, "why": "a run has not finished"}
    defaults = _defaults(settings_cls)
    values = []
    for arm in (arm_a, arm_b):
        seen = {json.dumps(_arm_values(runs[n], defaults), sort_keys=True) for n in arm}
        if len(seen) != 1:
            return {"decided": False, "why": "the runs of one arm used different settings"}
        values.append(json.loads(seen.pop()))
    if len({json.dumps(_other_settings(r), sort_keys=True, default=str) for r in runs.values()}) != 1:
        return {"decided": False, "why": "the arms differ outside the live tuning switches (model, packs, settings)"}
    changed = sorted(k for k in defaults if values[0][k] != values[1][k])
    if not changed:
        return {"decided": False, "why": "the arms do not differ in a live tuning switch"}
    dev_text = dev_file.read_text(encoding="utf-8") if dev_file else ""
    # The key ignores which arm is live (after a promotion the same A/B must not be decided again the other way round)
    # and includes the answered tasks: a run file can be read while its driver still appends to it, so a refusal on
    # the first part never blocks the decision on the whole run. Call it when the runs have ended (no peeking).
    answered = sorted(f"{n}:{t}" for n, r in runs.items() for t in r.get("tasks") or {})
    key = hashlib.sha256(json.dumps({"set": set_id, "arms": sorted([sorted(arm_a), sorted(arm_b)]), "families": families,
                                     "dev_sha256": hashlib.sha256(dev_text.encode()).hexdigest(),
                                     "answered": answered}, sort_keys=True).encode()).hexdigest()
    for path, receipt in _receipts():
        if (receipt.get("experiment") or {}).get("key") == key:
            return {"decided": False, "why": "already decided", "receipt": str(path)}
    live = {**defaults, **promoted_values(settings_cls)}
    if all(values[0][k] == live[k] for k in changed):
        (base_names, base_vals), (cand_names, cand_vals) = (arm_a, values[0]), (arm_b, values[1])
    elif all(values[1][k] == live[k] for k in changed):
        (base_names, base_vals), (cand_names, cand_vals) = (arm_b, values[1]), (arm_a, values[0])
    else:
        return {"decided": False, "why": "neither arm runs the live values"}
    apply = {k: cand_vals[k] for k in changed}
    experiment = {"set": set_id, "baseline": base_names, "candidate": cand_names, "apply": apply,
                  "families": families, "dev_sha256": hashlib.sha256(dev_text.encode()).hexdigest()}
    grader = se.verify(set_id, manifest=manifest) or se.grader_problems(manifest)
    base, cand = [runs[n] for n in base_names], [runs[n] for n in cand_names]
    canaries = integrity.canary_alarm(sorted({t for r in base for t in se.canary_passes(r, manifest)}),
                                      sorted({t for r in cand for t in se.canary_passes(r, manifest)}))
    report = se.paired_report(base, cand, manifest, families=families)
    holdout = {**report["summary"], "candidate_pass": report["candidate_pass"], "samples": report["samples"]}
    dev = None
    if dev_text:
        raw = json.loads(dev_text)
        dev = raw.get("paired") or raw
    change = ", ".join(f"{k}={v}" for k, v in apply.items())
    d = integrity.decide(f"autoloop: {change}", apply=apply, dev=dev, holdout=holdout, grader=grader,
                         canaries=canaries, easier=[], previous=None,
                         why=f"sealed {set_id}: {'+'.join(cand_names)} vs live {'+'.join(base_names)} "
                             f"({', '.join(f'{k}={base_vals[k]}' for k in changed)})",
                         extra={"experiment": {**experiment, "key": key},
                                "watch": {"set": set_id, "families": families, "exclude": base_names + cand_names},
                                "sealed_set": {"set": set_id, "set_sha256": manifest.get("set_sha256")}})
    return {"decided": True, "promote": d.promote, "apply": apply, "reasons": d.reasons, "receipt": d.receipt}


def _when(text) -> datetime | None:
    try:
        return datetime.fromisoformat(str(text))
    except ValueError:
        return None


def watch_promotions(settings_cls) -> list[dict]:
    """Re-measure every active promotion on later sealed runs that used the promoted values; roll back on a breach."""
    from . import integrity, sealed_eval as se
    receipts = _receipts()
    rolled = {Path(str(r.get("of", ""))).name for _, r in receipts if r.get("kind") == "rollback"}
    overlay = integrity.read_overlay()
    defaults = _defaults(settings_cls)
    out = []
    for path, receipt in receipts:
        watch = receipt.get("watch")
        if receipt.get("kind") != "promotion" or not watch or path.name in rolled:
            continue
        apply = receipt.get("apply") or {}
        row = {"receipt": str(path), "change": receipt.get("change")}
        if any(overlay.get(k) != v for k, v in apply.items()):
            out.append({**row, "status": "superseded"})
            continue
        set_id = watch["set"]
        manifest = json.loads(se.manifest_path(set_id).read_text(encoding="utf-8"))
        problems = se.verify(set_id, manifest=manifest) or se.grader_problems(manifest)
        if problems:
            out.append({**row, "status": "sealed set unusable, not judged", "problems": problems[:3]})
            continue
        since, families = _when(receipt.get("at")), watch.get("families") or ["all"]
        passed = total = canaries = 0
        used = []
        for result in sorted((se.set_dir(set_id) / "results").glob("*.json")):
            if result.stem in (watch.get("exclude") or []):
                continue
            run = json.loads(result.read_text(encoding="utf-8"))
            started = _when((run.get("run") or {}).get("started_at"))
            if not run.get("complete") or since is None or started is None or started <= since:
                continue
            if any(_arm_values(run, defaults)[k] != v for k, v in apply.items() if k in defaults):
                continue
            scores = se.family_scores(run, manifest)
            passed += sum(scores.get(f, {}).get("pass", 0) for f in families)
            total += sum(scores.get(f, {}).get("scored", 0) for f in families)
            canaries += len(se.canary_passes(run, manifest))
            used.append(result.stem)
        if total < MIN_LIVE and not canaries:
            out.append({**row, "status": "waiting for data", "live": f"{passed}/{total}", "runs": used})
            continue
        verdict = integrity.watch(path, passed, total, live_canary_passes=canaries)
        out.append({**row, "status": "healthy" if verdict["healthy"] else "rolled back", "live": f"{passed}/{total}",
                    "runs": used, **verdict})
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m star.autoloop", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    cy = sub.add_parser("cycle", help="decide a finished A/B (two --arm), then watch every active promotion")
    cy.add_argument("--set", required=True, help="sealed set id")
    cy.add_argument("--arm", action="append", default=[], metavar="NAME[,NAME]",
                    help="sealed result names of one arm (give exactly two --arm to decide)")
    cy.add_argument("--dev", type=Path, help="`python -m star.evals gate --paired-session --json` output")
    cy.add_argument("--families", default="", help="decide on these families only (comma list)")
    args = parser.parse_args(argv)
    from .desktop_core import Settings
    if len(args.arm) not in (0, 2):
        parser.error("give two --arm options (or none to only watch)")
    out: dict = {}
    if args.arm:
        arms = [[n for n in a.split(",") if n] for a in args.arm]
        out["decision"] = decide_experiment(args.set, arms[0], arms[1], dev_file=args.dev,
                                            families=[f for f in args.families.split(",") if f] or None,
                                            settings_cls=Settings)
    out["watch"] = watch_promotions(Settings)
    print(json.dumps(out, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
