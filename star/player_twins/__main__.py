"""CLI: ``python -m star.player_twins run <game_dir> --sessions 1000 --personas all``."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import analysis, runner
from .personas import PERSONAS, parse_personas


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m star.player_twins",
                                     description="Simulated human players that playtest a Roblox game's server logic.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="play a game folder and write report.md + report.json")
    run.add_argument("game_dir", type=Path, help="folder with twin.json (e.g. star/player_twins/games/twin_tycoon)")
    run.add_argument("--sessions", type=int, default=1000, help="number of twins; each plays day 1, more if it returns")
    run.add_argument("--days", type=int, default=2, help="max sessions per twin (returning players)")
    run.add_argument("--personas", default="all", help=f"all, or a list/weights of: {', '.join(PERSONAS)}")
    run.add_argument("--seed", type=int, default=1)
    run.add_argument("--workers", type=int, default=None, help="parallel processes (default: from PC load, 1-4)")
    run.add_argument("--runtime", choices=("auto", "lune", "luau"), default="auto")
    run.add_argument("--tick", type=float, default=runner.DEFAULT_SETTINGS["tickDt"], help="Heartbeat step, seconds")
    run.add_argument("--cap-min", type=float, default=runner.DEFAULT_SETTINGS["capMin"])
    run.add_argument("--ds-fail-rate", type=float, default=runner.DEFAULT_SETTINGS["dsFailRate"])
    run.add_argument("--out", type=Path, default=Path("player-twins-out"))
    run.add_argument("--keep-sessions", action="store_true", help="also write sessions.jsonl (large)")
    run.add_argument("--fail-on-findings", action="store_true", help="exit 1 when a high-severity finding exists")
    shard = sub.add_parser("shard", help="write bundles to run on other machines (brain 2, the new server)")
    shard.add_argument("game_dir", type=Path)
    shard.add_argument("--sessions", type=int, default=1000)
    shard.add_argument("--days", type=int, default=2)
    shard.add_argument("--personas", default="all")
    shard.add_argument("--seed", type=int, default=1)
    shard.add_argument("--shards", type=int, default=4)
    shard.add_argument("--tick", type=float, default=runner.DEFAULT_SETTINGS["tickDt"])
    shard.add_argument("--cap-min", type=float, default=runner.DEFAULT_SETTINGS["capMin"])
    shard.add_argument("--ds-fail-rate", type=float, default=runner.DEFAULT_SETTINGS["dsFailRate"])
    shard.add_argument("--out", type=Path, required=True)
    rep = sub.add_parser("report", help="build the report from shard outputs (twins_bundle_<i>.luau.out)")
    rep.add_argument("shard_dir", type=Path)
    rep.add_argument("--out", type=Path, default=None, help="default: the shard folder")
    sub.add_parser("personas", help="list personas")
    args = parser.parse_args(argv)

    if args.cmd == "personas":
        for name, p in PERSONAS.items():
            print(f"{name:20} {p['label']}")
        return 0

    if args.cmd == "report":
        return _report(runner.collect(args.shard_dir), args.out or args.shard_dir, keep=False, fail_on=False)

    if args.sessions < 1 or args.days < 1:
        parser.error("--sessions and --days must be at least 1")
    mix = parse_personas(args.personas)
    settings = {"tickDt": args.tick, "capMin": args.cap_min, "dsFailRate": args.ds_fail_rate}
    if args.cmd == "shard":
        paths = runner.write_shards(args.out, args.game_dir, twins=args.sessions, mix=mix, days=args.days,
                                    seed=args.seed, shards=args.shards, settings=settings)
        print(f"wrote {len(paths)} bundles to {args.out}. On each machine: lune run twins_bundle_<i>.luau > "
              f"twins_bundle_<i>.luau.out (or luau twins_bundle_<i>.luau), copy the .out files back, then: "
              f"python -m star.player_twins report {args.out}")
        return 0
    result = runner.run(args.game_dir, twins=args.sessions, mix=mix, days=args.days, seed=args.seed,
                        workers=args.workers, runtime=args.runtime, settings=settings)
    return _report(result, args.out, keep=args.keep_sessions, fail_on=args.fail_on_findings)


def _report(result: runner.RunResult, out: Path, *, keep: bool, fail_on: bool) -> int:
    for err in result.errors:
        print(f"worker error: {err}", file=sys.stderr)
    if not result.sessions:
        print("no sessions were played", file=sys.stderr)
        return 2
    report = analysis.analyze(result.sessions, result.meta)
    report["worker_errors"] = result.errors
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    (out / "report.md").write_text(analysis.render_markdown(report), encoding="utf-8")
    if keep:
        with (out / "sessions.jsonl").open("w", encoding="utf-8") as fh:
            for s in result.sessions:
                fh.write(json.dumps(s) + "\n")
    m = result.meta
    speed = (f"in {m['elapsed_s']} s ({m['sessions_per_min']}/min, {m['workers']} workers, {m['runtime']})"
             if m.get("elapsed_s") else f"from {m['workers']} shards ({m['sessions_per_cpu_min']} per CPU-minute)")
    print(f"{m['sessions']} sessions {speed}; report: {out / 'report.md'}")
    for f in report["findings"]:
        print(f"- [{f['severity']}] {f['kind']}: {f['text']}")
    if fail_on and any(f["severity"] == "high" for f in report["findings"]):
        return 1
    return 0 if not result.errors else 3


if __name__ == "__main__":
    sys.exit(main())
