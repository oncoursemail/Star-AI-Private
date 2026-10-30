"""python -m mesh.flaws <command>   (PYTHONPATH=server on a checkout, /opt/star-mesh/app in the star-mesh container)

  mine   [--journal FILE] [--since "24 hours ago"] [--report]      clusters by cause (+ self-model report)
  items  --samples FILE --out FILE                                  live flaw samples -> regression items
  route  --items FILE... [--fix ID ...]                             offline route accuracy before/after
  gate   --fix ID --items FILE... [--ship] [--report]               A/B through the router, ship on a win
  watch  [--report]                                                 rollback check of shipped fixes
  loop   [--report] [--ship]                                        watch, mine, items, gate every unshipped fix

Settings (flags or /etc/star-mesh/flaws.json): router_url, key_file, self_url, flaws_dir, items (list of item files),
system_prompt (file with Litha's launcher system prompt), max_tokens.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time
import urllib.request

from . import gate, hook, items as items_mod, mine, route

DEFAULTS = {
    "router_url": "http://127.0.0.1:8100",
    "key_file": "/etc/star-mesh/api_keys",
    "self_url": "http://127.0.0.1:8103",
    "flaws_dir": hook.DEFAULTS["flaws_dir"],
    "items": ["/opt/star-mesh/app/evals/flaws/*.jsonl"],
    "system_prompt": "/opt/star-mesh/app/evals/flaws/system_prompt.txt",
    "max_tokens": 900,
    "limit": 20,
    "since": "7 days ago",
}


def settings(args) -> dict:
    cfg = dict(DEFAULTS)
    path = getattr(args, "config", None) or "/etc/star-mesh/flaws.json"
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            cfg.update(json.load(fh))
    for k in ("router_url", "key_file", "self_url", "flaws_dir", "system_prompt", "since", "limit", "max_tokens"):
        if getattr(args, k, None):
            cfg[k] = getattr(args, k)
    if getattr(args, "items", None):
        cfg["items"] = args.items
    return cfg


def key(cfg) -> str:
    with open(cfg["key_file"], encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith("#"):
                return line.split()[0]
    raise SystemExit("no key in key_file")


def post_report(cfg, rep: dict) -> str:
    req = urllib.request.Request(cfg["self_url"].rstrip("/") + "/mesh/self/report", data=json.dumps(rep).encode(),
                                 method="POST", headers={"Content-Type": "application/json",
                                                         "Authorization": f"Bearer {key(cfg)}"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return f"self-model {r.status}"
    except OSError as e:
        return f"self-model report failed: {e}"


def item_sets(cfg) -> dict[str, list[dict]]:
    out = {}
    for pattern in cfg["items"]:
        for path in sorted(glob.glob(pattern)):
            out[os.path.basename(path)] = items_mod.load(path)
    live = os.path.join(cfg["flaws_dir"], "items-live.jsonl")
    if os.path.isfile(live):
        out["items-live.jsonl"] = items_mod.load(live)
    return out


def rows_for(cfg, args) -> list[dict]:
    if getattr(args, "journal", None):
        with open(args.journal, encoding="utf-8") as fh:
            return mine.parse(fh)
    return mine.parse(mine.read_journal(cfg["since"]))


def client(cfg) -> gate.Client:
    system = ""
    if cfg.get("system_prompt") and os.path.isfile(cfg["system_prompt"]):
        with open(cfg["system_prompt"], encoding="utf-8") as fh:
            system = fh.read().strip()
    return gate.Client(cfg["router_url"], key(cfg), system)


def run_gate(cfg, fix: str, sets: dict, rows: list[dict], do_ship: bool, do_report: bool) -> dict:
    shipped = frozenset(gate.read_shipped(cfg["flaws_dir"])["fixes"])
    ok_off, offline = gate.offline_ok(fix, sets, shipped)
    result = {"fix": fix, "offline": offline, "offline_ok": ok_off}
    if not ok_off:
        result.update(decision="reject", why="offline route accuracy drops on a set")
    else:
        its = [it for s in sets.values() for it in s]
        rows_ab = gate.ab(client(cfg), fix, its, shipped, int(cfg["max_tokens"]), int(cfg["limit"]))
        ok, tally = gate.decide(fix, rows_ab)
        result.update(ab=tally, rows=rows_ab, decision="ship" if ok else "reject",
                      why="won its cluster with no control loss" if ok else "no clear win (or a control loss)")
        if ok and do_ship:
            gate.ship(cfg["flaws_dir"], fix, {"offline": offline, "ab": tally}, gate.live_rates(rows, fix, "would"))
    if do_report:
        result["report"] = post_report(cfg, {
            "kind": "upgrade", "component": f"flaw-fix:{fix}", "current": "off",
            "latest": "on" if result["decision"] == "ship" and do_ship else "off",
            "decision": "promote" if result["decision"] == "ship" and do_ship else "reject",
            "why": (result["why"] + "; " + json.dumps(result.get("ab") or result["offline"]))[:400]})
    return result


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m mesh.flaws")
    ap.add_argument("command", choices=["mine", "items", "route", "gate", "watch", "loop"])
    ap.add_argument("--config")
    ap.add_argument("--journal")
    ap.add_argument("--since")
    ap.add_argument("--router-url", dest="router_url")
    ap.add_argument("--key-file", dest="key_file")
    ap.add_argument("--self-url", dest="self_url")
    ap.add_argument("--flaws-dir", dest="flaws_dir")
    ap.add_argument("--system-prompt", dest="system_prompt")
    ap.add_argument("--items", nargs="+")
    ap.add_argument("--samples")
    ap.add_argument("--out")
    ap.add_argument("--fix", nargs="+")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--max-tokens", dest="max_tokens", type=int)
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--ship", action="store_true")
    args = ap.parse_args(argv)
    cfg = settings(args)
    out: dict = {"ts": round(time.time())}

    if args.command == "mine":
        res = mine.clusters(rows_for(cfg, args))
        out.update(res)
        if args.report:
            out["report"] = post_report(cfg, mine.report(res))
    elif args.command == "items":
        samples = items_mod.load(args.samples or os.path.join(cfg["flaws_dir"], "samples.jsonl"))
        its = items_mod.clusters_to_items(samples)
        items_mod.save(args.out or os.path.join(cfg["flaws_dir"], "items-live.jsonl"), its)
        out.update(items=len(its), by_cluster=dict(__import__("collections").Counter(i["cluster"] for i in its)))
    elif args.command == "route":
        sets = item_sets(cfg)
        fixes = args.fix or sorted(hook.FIXES)
        out["sets"] = {name: {k: v for k, v in route.compare(its, fixes).items() if k != "changed"}
                       for name, its in sets.items()}
    elif args.command == "gate":
        rows = rows_for(cfg, args)
        out["gates"] = [run_gate(cfg, f, item_sets(cfg), rows, args.ship, args.report) for f in args.fix or []]
    elif args.command == "watch":
        res = gate.watch(cfg["flaws_dir"], rows_for(cfg, args))
        out["watch"] = res
        for r in res:
            if r["rollback"] and args.report:
                post_report(cfg, {"kind": "upgrade", "component": f"flaw-fix:{r['fix']}", "current": "on",
                                  "latest": "off", "decision": "rollback", "why": r["why"][:300]})
    elif args.command == "loop":
        rows = rows_for(cfg, args)
        out["watch"] = gate.watch(cfg["flaws_dir"], rows)
        for r in out["watch"]:
            if r["rollback"] and args.report:
                post_report(cfg, {"kind": "upgrade", "component": f"flaw-fix:{r['fix']}", "current": "on",
                                  "latest": "off", "decision": "rollback", "why": r["why"][:300]})
        res = mine.clusters(rows)
        out["mine"] = res
        if args.report:
            out["mine_report"] = post_report(cfg, mine.report(res))
        samples_path = os.path.join(cfg["flaws_dir"], "samples.jsonl")
        if os.path.isfile(samples_path):
            its = items_mod.clusters_to_items(items_mod.load(samples_path))
            items_mod.save(os.path.join(cfg["flaws_dir"], "items-live.jsonl"), its)
            out["live_items"] = len(its)
        shipped = gate.read_shipped(cfg["flaws_dir"])["fixes"]
        sets = item_sets(cfg)
        out["gates"] = [run_gate(cfg, f, sets, rows, args.ship, args.report) for f in sorted(hook.FIXES)
                        if f not in shipped]
    json.dump(out, sys.stdout, indent=1, default=str)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
