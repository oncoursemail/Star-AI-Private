"""Litha's nightly self-improvement on Brain One (docs/LITHA_AUTONOMY.md section 4s).

Every night (systemd timer litha-learn.timer on Brain One, 01:30) `run`:
 1. fetches the scratch clones and rebuilds the replay set when it is older than --rebuild-days (Studio excluded:
    self_tune.EXCLUDED); case splits are a hash of the case id, so a hold-out case stays hold-out forever;
 2. scores the replay with her local model as it is (answers cached in answers.jsonl: a rescore costs no call);
 3. makes lessons from the TUNE split's failures (litha.experience.lessons_from_replay) on top of the lessons from
    her logs, scores again with them in her prompts, and compares (self_tune.compare: changed cases replayed 3x, kept
    only if the total rises by more than the noise, no good case breaks, the HELD-OUT split scores higher and no
    must-refuse case that was refused gets resolved);
 4. scores every candidate prompt/rule change waiting in ~/.star/litha-selftune/candidates/*.json the same way
    (a kept one becomes a patch under proposals/, never code); `--propose` also asks Claude for one (lane budget);
 5. writes the verdict: ~/.star/litha/experience/on.json (the lanes whose lessons go into her live prompts: only
    a lane that won on held-out cases), the report ~/.star/litha-selftune/nightly/<date>.json and one line in
    nightly.jsonl.

Her model on Brain One: the GPU node is called directly (~/.star/litha-node-url = its OpenAI base URL, token from
~/.star/mesh_token); the mesh router is not reachable from there. Same request as pr_fixer.ask.

    python -m litha.learn_nightly run    [--rebuild-days 7] [--propose] [--no-fetch]
    python -m litha.learn_nightly sync   (on the PC) logs + lessons -> Brain One; verdict + nightly log <- back
    python -m litha.learn_nightly deploy (on the PC) this checkout's committed litha/ -> Brain One ~/litha-learn/code
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
import urllib.request

from litha import canaries as C
from litha import experience as X
from litha import self_tune as st
from litha import trusted_bench as tb

HOME = st.HOME
CANDIDATES = HOME / "candidates"
REPORTS = HOME / "nightly"
NIGHTLY = HOME / "nightly.jsonl"
NODE_URL = Path.home() / ".star" / "litha-node-url"
TOKEN = Path.home() / ".star" / "mesh_token"
BRAIN = os.environ.get("LITHA_BRAIN_SSH", "litha-brainone")     # an ssh alias in ~/.ssh/config, not a host name
REMOTE_CODE = "litha-learn/code"


def node_model(url: str | None = None, token: str | None = None, wait_s: float = 1800, opener=urllib.request.urlopen,
               max_tokens: int = 1500, temperature: float = 0.2):
    """Her model straight from a GPU node: pr_fixer.ask's request (1500 tokens, 0.2, JSON; the merge review uses 700,
    0.1), retried while busy."""
    url = (url or NODE_URL.read_text(encoding="utf-8").split()[0]).rstrip("/")
    token = token or TOKEN.read_text(encoding="utf-8").split()[0]

    def ask(prompt: str) -> str:
        body = {"model": "litha-fast", "messages": [{"role": "user", "content": prompt}], "max_tokens": max_tokens,
                "temperature": temperature, "response_format": {"type": "json_object"},
                "chat_template_kwargs": {"enable_thinking": False}}
        end, last = time.time() + wait_s, ""
        while True:
            req = urllib.request.Request(url + "/chat/completions", json.dumps(body).encode("utf-8"),
                                         {"Authorization": "Bearer " + token, "Content-Type": "application/json"})
            try:
                with opener(req, timeout=900) as r:
                    return json.load(r)["choices"][0]["message"].get("content") or ""
            except urllib.error.HTTPError as e:
                if e.code == 400:
                    raise ValueError(f"HTTP 400 {e.reason}") from e
                last = f"HTTP {e.code}"
            except OSError as e:
                last = f"{type(e).__name__}"
            if time.time() > end:
                raise RuntimeError(f"the node did not answer: {last}")
            time.sleep(20)
    return ask


def fetch(clones=None) -> list[str]:
    """git fetch every scratch clone (branches + the base as origin/<base>); returns the problems."""
    bad = []
    for repo, base, clone, _ in clones or st.REPOS:
        if repo in st.EXCLUDED or not Path(clone).exists():
            continue
        r = st.git(Path(clone), "fetch", "-q", "--prune", "origin", "+refs/heads/*:refs/heads/*",
                   f"+refs/heads/{base}:refs/remotes/origin/{base}")
        if r.returncode:
            bad.append(f"{repo}: fetch failed: {r.stderr.strip()[-200:]}")
    return bad


def stale(path: Path, days: float) -> bool:
    return not path.exists() or time.time() - path.stat().st_mtime > days * 86400


# name -> (lesson sources, only lessons about the task's own file)
VARIANTS = {"logs+distilled": ({"fixes", "decisions", "distilled"}, False),   # Claude's one-line rules (distill, PC)
            "distilled-same-file": ({"fixes", "decisions", "distilled"}, True),
            "logs+replay": ({"fixes", "decisions", "replay"}, False)}         # mechanical "what the accepted merge did"


def lessons_for(cases_: list[dict], base: dict, store_path: Path | None = X.STORE,
                sources: set | None = None, same_path: bool = False) -> X.Store:
    """Her lessons from the logs, Claude's distilled ones and the tune split's replay failures (re-made from tonight's
    baseline), limited to `sources`; hold-out cases never give one."""
    logged = X.Store(store_path) if store_path else X.Store(None, [])
    replayed = X.lessons_from_replay(cases_, base)
    store = X.Store(None, [x for x in logged.lessons.values() if x["source"] != "replay"])
    store.add(replayed)
    if store_path:                      # kept in her store too (sync brings them to the PC; ids are stable)
        logged.add(replayed)
        logged.save()
    if sources is not None:
        store = X.Store(None, [x for x in store.lessons.values() if x["source"] in sources])
    store.same_path = same_path
    return store


def stamp(cases_: list[dict], clones=None) -> int:
    """Each case's commit time as "at" (from its scratch clone), so a replayed case only sees lessons learnt before
    it; returns how many were stamped."""
    n = 0
    for repo, _, clone, _ in clones or st.REPOS:
        todo = [c for c in cases_ if c["repo"] == repo and "at" not in c]
        shas = sorted({c.get("commit") or c["theirs"] for c in todo})
        if not shas or not Path(clone).exists():
            continue
        times = {}
        for k in range(0, len(shas), 200):
            r = st.git(Path(clone), "log", "--no-walk", "--format=%H %ct", *shas[k:k + 200])
            times.update(ln.split() for ln in r.stdout.splitlines() if len(ln.split()) == 2)
        for c in todo:
            t = times.get(c.get("commit") or c["theirs"])
            if t:
                c["at"] = int(t)
                n += 1
    return n


def candidates(folder: Path = CANDIDATES) -> list[tuple[Path, dict, str]]:
    """(file, overrides, why) of every waiting candidate {"overrides": {...}, "why": ...} or a Claude answer text."""
    out = []
    for p in sorted(folder.glob("*.json")) if folder.exists() else []:
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if "overrides" in data:
                over = {k: v for k, v in data["overrides"].items() if k in st.TUNABLE}
                out.append((p, over, str(data.get("why", ""))))
            else:
                over, why = st.parse_edit(json.dumps(data))
                out.append((p, over, why))
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return out


def brief(r: dict) -> dict:
    return {k: r[k] for k in ("points", "total", "hold", "hold_total", "refuse_ok", "outcomes", "calls", "cached",
                              "model_s", "seconds") if k in r}


def run(model=None, cases_: list[dict] | None = None, cache: st.Cache | None = None, propose: bool = False,
        store_path: Path | None = X.STORE, switch: Path | None = None, reports: Path = REPORTS,
        cand_dir: Path = CANDIDATES, log: Path | None = st.RUNS, nightly: Path | None = NIGHTLY, k: int = 1,
        canaries: bool = False, review_ask=None) -> dict:
    """One night: baseline, with experience memory, every candidate; verdicts written. Returns the report.
    k > 1 (section 8): every case is replayed k times for the baseline and for each change, the report gets the
    bench line (score, CI, MDE) and a change is kept only when the paired CI over all cases is also above 0.
    canaries: the gate canaries (hard gates; with review_ask also her review) run and are reported."""
    t0 = time.time()
    cases_ = cases_ if cases_ is not None else st.cases()
    cache = cache or st.Cache()
    model = model or (node_model() if NODE_URL.exists() else None)
    report: dict = {"ts": int(t0), "day": dt.date.today().isoformat(), "cases": len(cases_),
                    "hold_cases": sum(c.get("split") == "hold" for c in cases_)}
    report["stamped"] = stamp(cases_)
    base = st.score({}, cases_, model, 0, cache, log=log)
    report["baseline"] = brief(base)
    splits = {c["id"]: c.get("split", "tune") for c in cases_}
    base_tab = (tb.table({}, cases_, model, k, cache, log=log) if k > 1 else
                {cid: [r["outcome"] in st.GOOD] for cid, r in base["cases"].items()})
    report["bench"] = tb.summary(base_tab, splits)

    def paired_gate(verdict: dict, overrides: dict, lessons=None) -> None:
        if k > 1:
            new_tab = tb.table(overrides, cases_, model, k, cache, lessons=lessons, log=log)
            verdict["paired"] = tb.paired(base_tab, new_tab)
            verdict["paired_hold"] = tb.paired(base_tab, new_tab, ids=[c for c in base_tab if splits[c] == "hold"])
            verdict["keep"] = bool(verdict["keep"] and verdict["paired"]["significant"])
    lessons_for(cases_, base, store_path)                  # tonight's replay lessons into her store
    report["variants"], best = {}, None
    for name, (sources, same_path) in VARIANTS.items():
        store = lessons_for(cases_, base, store_path, sources, same_path)
        if not any(x["source"] not in ("fixes", "decisions") for x in store.active("resolve")):
            continue                                       # nothing of this variant's own kind yet
        with_mem = st.score({}, cases_, model, 0, cache, log=log, lessons=store)
        verdict = st.compare(base, with_mem, {}, cases_, model, cache, None, store)
        paired_gate(verdict, {}, store)
        report["variants"][name] = {**brief(with_mem), "lessons": len(store.active("resolve")), "verdict": verdict}
        if verdict["keep"] and (best is None or verdict["hold_new"] > report["variants"][best]["verdict"]["hold_new"]):
            best = name
    shown = report["variants"].get(best) or next(iter(report["variants"].values()), None)
    verdict = shown["verdict"] if shown else {"keep": False, "hold_old": base["hold"], "hold_new": base["hold"],
                                              "hold_total": base["hold_total"], "old": base["points"],
                                              "new": base["points"], "noise": 0, "flips": []}
    report["experience"] = {**(shown or {}), "verdict": verdict, "variant": best}
    lanes = ["resolve"] if best else []
    sw = switch or X.SWITCH
    sw.parent.mkdir(parents=True, exist_ok=True)
    sw.write_text(json.dumps({"lanes": lanes, "sources": sorted(VARIANTS[best][0]) if best else [],
                              "same_path": bool(best and VARIANTS[best][1]),
                              "variant": best, "ts": int(time.time()), "why": (
        f"held-out {verdict['hold_old']} -> {verdict['hold_new']} of {verdict['hold_total']}, total "
        f"{verdict['old']} -> {verdict['new']} (noise {verdict['noise']}, {len(verdict['flips'])} broken)")}),
        encoding="utf-8")
    report["on"] = lanes
    report["candidates"] = []
    for p, over, why in candidates(cand_dir):
        new = st.score(over, cases_, model, 0, cache, log=log)
        v = st.compare(base, new, over, cases_, model, cache)
        paired_gate(v, over)
        row = {"file": p.name, "why": why, "verdict": v, "result": "kept" if v["keep"] else "rejected"}
        if v["keep"]:
            st.PROPOSALS.mkdir(parents=True, exist_ok=True)
            patch = st.PROPOSALS / f"{dt.date.today():%Y%m%d}-{st.prompt_hash(over)}.patch"
            patch.write_text(st.patch(over), encoding="utf-8")
            row["patch"] = str(patch)
        done = cand_dir / "done"
        done.mkdir(parents=True, exist_ok=True)
        p.replace(done / p.name)
        report["candidates"].append(row)
    if propose:
        report["propose"] = [{k: v for k, v in r.items() if k != "answer"}
                             for r in st.propose(cases_, model, cache=cache, log=log)]
    if canaries:
        report["canaries"] = {}
        for mode, ask in (("gate", C.always_merge), ("review", review_ask)):
            if ask is not None:
                got = C.run(ask, mode=mode)
                report["canaries"][mode] = {**{k_: got[k_] for k_ in ("total", "held", "escapes", "known", "now_held")},
                                            "rows": [{k_: r.get(k_) for k_ in ("id", "held", "reason")}
                                                     for r in got["rows"]]}
    report["seconds"] = round(time.time() - t0)
    reports.mkdir(parents=True, exist_ok=True)
    (reports / f"{report['day']}.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    if nightly:
        with nightly.open("a", encoding="utf-8") as f:
            f.write(json.dumps({k_: report[k_] for k_ in ("ts", "day", "cases", "baseline", "on", "seconds")} |
                               {"bench": report["bench"],
                                "canaries": {m: {k_: v for k_, v in c.items() if k_ != "rows"}
                                             for m, c in report.get("canaries", {}).items()}} |
                               {"experience": {k: v for k, v in report["experience"].items() if k != "verdict"} |
                                {"keep": verdict["keep"], "hold_old": verdict["hold_old"],
                                 "hold_new": verdict["hold_new"]},
                                "candidates": [(c["file"], c["result"]) for c in report["candidates"]]}) + "\n")
    return report


def _ssh(*args: str, data: bytes | None = None, timeout: float = 900) -> subprocess.CompletedProcess:
    return subprocess.run(["ssh", "-o", "BatchMode=yes", BRAIN, *args], input=data, capture_output=True,
                          timeout=timeout)


def sync() -> int:
    """PC -> Brain One: her logs and her lessons (Brain One's lessons merged in first, gh fates folded in); Brain One
    -> PC: the verdict (on.json) and the nightly log. The answer cache is Brain One's own (never overwritten)."""
    star = Path.home() / ".star"
    store = X.Store()
    r = _ssh("cat .star/litha/experience/lessons.jsonl")
    if r.returncode == 0:
        store.add([json.loads(ln) for ln in r.stdout.decode("utf-8").splitlines() if ln.strip()])
    repos = sorted({r.get("repo") or X.STAR_REPO for r in X._rows(X.DECISIONS) + X._rows(X.FIXES)} - set(st.EXCLUDED))
    got = X.backfill(store, fates=X.gh_fates(repos))
    store.save()
    print("lessons:", json.dumps(got))
    for local, remote in ((X.FIXES, ".star/pr-fixer/fixes.jsonl"), (X.DECISIONS, ".star/pr-merger/decisions.jsonl"),
                          (X.STORE, ".star/litha/experience/lessons.jsonl"),    # her answer cache stays on Brain One
                          (C.CORPUS, ".star/litha/canaries/corpus.json"),        # section 8
                          *[(p, f".star/litha-selftune/cases-extra/{p.name}")
                            for p in sorted(st.EXTRA.glob("*.json")) if st.EXTRA.is_dir()]):
        if local.exists():
            r = _ssh(f"mkdir -p {Path(remote).parent.as_posix()} && cat > {remote}.new && mv {remote}.new {remote}",
                     data=local.read_bytes())
            print(f"-> {remote}: {'ok' if r.returncode == 0 else r.stderr.decode()[-200:]}")
    for remote, local in ((".star/litha/experience/on.json", X.SWITCH),
                          (".star/litha-selftune/nightly.jsonl", star / "litha-selftune" / "nightly.jsonl")):
        r = _ssh(f"cat {remote}")
        if r.returncode == 0 and r.stdout:
            local.parent.mkdir(parents=True, exist_ok=True)
            local.write_bytes(r.stdout)
            print(f"<- {remote}")
    return 0


DISTILL_CAP = 2.0                    # dollars per distill run (claude spend rows with `what` "learn: distill")


def spent(what: str = "learn: distill", ledger: Path | None = None) -> float:
    from litha import claude
    total = 0.0
    for ln in ((ledger or claude.LEDGER).read_text(encoding="utf-8").splitlines()
               if (ledger or claude.LEDGER).exists() else []):
        try:
            row = json.loads(ln)
            total += row["usd"] if row.get("what") == what else 0.0
        except (ValueError, KeyError):
            continue
    return total


def distill(budget: float = DISTILL_CAP, asker=None) -> int:
    """(PC: Claude's key is here) Brain One's replay set + answer cache -> tonight's tune-split failures (from the
    cache only: no model call) -> Claude's one-line lessons -> her store, here and on Brain One."""
    from litha import claude
    d = HOME / "brain"
    d.mkdir(parents=True, exist_ok=True)
    for name in ("cases.json", "answers.jsonl"):
        r = _ssh(f"cat .star/litha-selftune/{name}", timeout=1800)
        if r.returncode:
            print(f"cannot read {name} on Brain One: {r.stderr.decode()[-200:]}")
            return 1
        (d / name).write_bytes(r.stdout)
    cases_ = st.cases(d / "cases.json")
    stamp(cases_)
    res = st.score({}, cases_, st.cached_only, 0, st.Cache(d / "answers.jsonl"), log=None)
    start = spent()

    def ask(prompt: str) -> str:
        if spent() - start + 0.3 > budget:
            return ""
        return claude.ask(prompt, "medium", what="learn: distill")
    got = X.distill(cases_, res, asker or ask)
    store = X.Store()
    r = _ssh("cat .star/litha/experience/lessons.jsonl")
    if r.returncode == 0:
        store.add([json.loads(ln) for ln in r.stdout.decode("utf-8").splitlines() if ln.strip()])
    new = store.add(got)
    store.save()
    r = _ssh("mkdir -p .star/litha/experience && cat > .star/litha/experience/lessons.jsonl.new && "
             "mv .star/litha/experience/lessons.jsonl.new .star/litha/experience/lessons.jsonl", data=X.STORE.read_bytes())
    print(f"distilled {len(got)} lessons ({new} new) from {res['outcomes']}; spent ${spent() - start:.4f}; "
          f"pushed: {r.returncode == 0}")
    return 0


def deploy(ref: str = "HEAD") -> int:
    """This checkout's committed litha/ (+ the one STAR module she imports) to Brain One, replacing the old copy."""
    root = Path(__file__).resolve().parents[1]
    tar = subprocess.run(["git", "-C", str(root), "archive", "--format=tar", ref, "litha", "star/__init__.py",
                          "star/version.py", "star/asset3d/__init__.py", "star/asset3d/llm.py"], capture_output=True)
    if tar.returncode:
        print(tar.stderr.decode()[-300:])
        return 1
    r = _ssh(f"rm -rf {REMOTE_CODE}.new && mkdir -p {REMOTE_CODE}.new && tar xf - -C {REMOTE_CODE}.new && "
             f"rm -rf {REMOTE_CODE} && mv {REMOTE_CODE}.new {REMOTE_CODE}", data=tar.stdout)
    print("deployed" if r.returncode == 0 else r.stderr.decode()[-300:])
    return r.returncode


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m litha.learn_nightly")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="one night: rebuild if stale, score, experience gate, candidates")
    r.add_argument("--rebuild-days", type=float, default=7)
    r.add_argument("--propose", action="store_true", help="also one Claude proposal (needs a key; lane budget)")
    r.add_argument("--no-fetch", action="store_true")
    r.add_argument("--k", type=int, default=tb.K, help="runs per case (section 8; 1 = the old single run)")
    r.add_argument("--no-canaries", action="store_true")
    sub.add_parser("sync", help="(PC) logs/lessons to Brain One, the verdict back")
    di = sub.add_parser("distill", help="(PC) Claude's lessons from Brain One's tune-split failures")
    di.add_argument("--budget", type=float, default=DISTILL_CAP)
    d = sub.add_parser("deploy", help="(PC) the committed litha/ to Brain One")
    d.add_argument("--ref", default="HEAD")
    a = ap.parse_args(argv)
    if a.cmd == "sync":
        return sync()
    if a.cmd == "deploy":
        return deploy(a.ref)
    if a.cmd == "distill":
        return distill(a.budget)
    print(f"[{dt.datetime.now():%Y-%m-%d %H:%M}] litha nightly start", flush=True)
    for problem in ([] if a.no_fetch else fetch()):
        print(problem, flush=True)
    if stale(st.CASES, a.rebuild_days):
        got = st.build()
        print(f"rebuilt the replay set: {len(got)} cases", flush=True)
    review = node_model(max_tokens=700, temperature=0.1) if NODE_URL.exists() else None
    rep = run(propose=a.propose, k=a.k, canaries=not a.no_canaries, review_ask=review)
    print(json.dumps({k: rep[k] for k in ("cases", "stamped", "baseline", "on", "seconds")}), flush=True)
    print("bench: " + tb.line(rep["bench"]), flush=True)
    for name, v in rep["variants"].items():
        w = v["verdict"]
        print(f"variant {name} ({v['lessons']} lessons): held-out {w['hold_old']} -> {w['hold_new']}, total "
              f"{w['old']} -> {w['new']}, noise {w['noise']}, broken {len(w['flips'])}, kept {w['keep']}", flush=True)
    e = rep["experience"]["verdict"]
    print(f"experience memory: held-out {e['hold_old']} -> {e['hold_new']} of {e['hold_total']}, total {e['old']} -> "
          f"{e['new']} (noise {e['noise']}, broken {len(e['flips'])}): {'ON' if e['keep'] else 'off'}", flush=True)
    for c in rep["candidates"]:
        print(f"candidate {c['file']}: {c['result']}", flush=True)
    for mode, c in rep.get("canaries", {}).items():
        print(f"canaries ({mode}): {c['held']}/{c['total']} held; escapes {c['escapes'] or 'none'}; known escapes "
              f"{c['known']}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
