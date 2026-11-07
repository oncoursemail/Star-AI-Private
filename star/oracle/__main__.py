"""`python -m star.oracle ...` (see star/oracle/__init__.py)."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from . import calibrate, cascade, config, irt, probe

ROOT = Path(__file__).resolve().parents[2]


def _probe(args) -> int:
    from ..roblox_api_confusions import load_confusions
    from ..slop import bundled_api_dump, score_answer
    dump = bundled_api_dump()
    slop_score = (lambda text: score_answer(text, api_dump=dump).score)
    evals = probe.build(probe.eval_sources(args.eval_results, args.suite_dir), dump=dump,
                        confusions=load_confusions(), slop_score=slop_score)
    gold = probe.build(probe.gold_sources(args.gold), dump=dump, confusions=load_confusions(), slop_score=slop_score)
    pairs = evals + probe.spread(gold, max(0, args.size - len(evals)))
    probe.write(pairs, args.out)
    kinds: dict[str, int] = {}
    for p in pairs:
        for b in p.bads:
            kinds[b["kind"]] = kinds.get(b["kind"], 0) + 1
    print(json.dumps({"answers": len(pairs), "from_evals": len(evals), "twins": kinds}))
    return 0


def _compare(args) -> int:
    base, cand = config.load(args.base), config.load(args.cand)
    report = cascade.compare(base, cand, probe_file=args.probe, workdir=args.workdir, max_layer=args.max_layer,
                             calibration=calibrate.load(args.calibration), l0_prompts=args.l0_prompts,
                             suites=args.suite, history=args.history)
    args.workdir.mkdir(parents=True, exist_ok=True)
    (args.workdir / "verdict.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    text = cascade.markdown(report)
    (args.workdir / "verdict.md").write_text(text, encoding="utf-8")
    print(text)
    return 0 if report["verdict"] in ("SAME", "BETTER", "WORSE") else 4


def _calibrate(args) -> int:
    registry = json.loads(Path(args.registry).read_text(encoding="utf-8"))
    result = calibrate.run(registry, base_dir=Path(args.registry).parent)
    Path(args.out).write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(calibrate.markdown(result))
    return 0


def _replay(args) -> int:
    registry = json.loads(Path(args.registry).read_text(encoding="utf-8"))
    result = irt.replay_registry(registry, base_dir=Path(args.registry).parent, history=args.history)
    Path(args.out).write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(irt.replay_markdown(result))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m star.oracle")
    sub = ap.add_subparsers(dest="command", required=True)
    pr = sub.add_parser("probe", help="build the L2 probe corpus (GOOD answers + planted BAD twins)")
    pr.add_argument("--gold", type=Path, default=ROOT / "data" / "gold_bank" / "bank.jsonl")
    pr.add_argument("--eval-results", nargs="*", default=[], help="eval result files whose passing answers are GOOD")
    pr.add_argument("--suite-dir", type=Path, default=ROOT / "evals" / "roblox")
    pr.add_argument("--size", type=int, default=100, help="answers in the corpus (eval passes first, then gold)")
    pr.add_argument("--out", type=Path, required=True)
    cp = sub.add_parser("compare", help="predict whether --cand is better than --base")
    cp.add_argument("--base", type=Path, required=True)
    cp.add_argument("--cand", type=Path, required=True)
    cp.add_argument("--max-layer", type=int, default=2, choices=[0, 1, 2, 3])
    cp.add_argument("--probe", type=Path, help="probe corpus (python -m star.oracle probe)")
    cp.add_argument("--calibration", type=Path, default=ROOT / "data" / "oracle" / "calibration.json")
    cp.add_argument("--l0-prompts", type=int, default=50)
    cp.add_argument("--suite", nargs="*", default=[str(ROOT / "evals" / "roblox" / "golden-tasks-v2.json"),
                                                     str(ROOT / "evals" / "roblox" / "golden-tasks-creation-v1.json")])
    cp.add_argument("--history", nargs="*", default=[], help="eval result files for the L3 item model")
    cp.add_argument("--workdir", type=Path, required=True)
    ca = sub.add_parser("calibrate", help="fit L2 -> pass-rate mapping on past A/Bs and back-test it")
    ca.add_argument("--registry", required=True)
    ca.add_argument("--out", required=True)
    rp = sub.add_parser("replay", help="replay past A/Bs through the L3 adaptive order + sequential stop")
    rp.add_argument("--registry", required=True)
    rp.add_argument("--history", nargs="*", default=[])
    rp.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    return {"probe": _probe, "compare": _compare, "calibrate": _calibrate, "replay": _replay}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
