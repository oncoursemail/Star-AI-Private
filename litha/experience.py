"""Litha's experience memory: every finished outcome of her work becomes a short lesson, and the few lessons that fit a
new task go into her prompt (docs/LITHA_AUTONOMY.md section 4s).

A lesson is one JSON line in ~/.star/litha/experience/lessons.jsonl:
  {"id", "ts", "lane", "repo", "kind", "sig", "text", "good", "evidence", "source", "case", "wins", "losses", "retired"}
  lane      resolve (merge conflicts) | fix-python | fix-rust | merge-review
  kind      the file kind (py, rs, ts, md, ...); sig the error/conflict signature (informative identifiers, codes)
  text      the lesson itself, at most TEXT_CHARS: what worked, or what failed and why
  good      True = something that worked (do this), False = something that failed (avoid this)
  evidence  links / ids that prove it (a PR, a fix PR, a replay case id)
Sources (backfill, `python -m litha.experience backfill`):
  fixes.jsonl          her fixed / failed PR repairs and conflict merges; with gh, whether her fix PR merged
  decisions.jsonl      her holds on review claims, settled by what a person did later (merged anyway = overturned,
                       closed = upheld); her own merges that a later "Revert" PR undid
  self_tune replay     tune-split conflict cases she got wrong or refused, against the committed resolution (the
                       hold-out split never becomes a lesson: it is what the nightly gate measures with)
Live: pr_fixer.log_row -> record_fix(row) adds the row's lesson and settles the lessons that were in her prompts for
that PR (win when the result is "fixed", loss otherwise). Review lessons are settled nightly from the PRs' fates.
A lesson with RETIRE_LOSSES or more losses and fewer than half as many wins is retired (kept, never shown again).

Retrieval is local and fast: idf-weighted overlap of the signature tokens, plus same repo / same file kind; nothing
is downloaded. Prompts get lessons only for lanes the nightly gate switched on (on.json, written by
litha.learn_nightly after a measured gain on held-out cases) or with LITHA_EXPERIENCE=1 (0 forces off).
"""
from __future__ import annotations

import argparse
import collections
import contextlib
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time

HOME = Path.home() / ".star" / "litha" / "experience"
STORE = HOME / "lessons.jsonl"
USES = HOME / "uses.jsonl"
SWITCH = HOME / "on.json"
FIXES = Path.home() / ".star" / "pr-fixer" / "fixes.jsonl"
DECISIONS = Path.home() / ".star" / "pr-merger" / "decisions.jsonl"
STAR_REPO = "oncoursemail/Star-AI-Project"
LANES = ("resolve", "fix-python", "fix-rust", "merge-review")
TEXT_CHARS = 240
RETIRE_LOSSES = 3
MIN_SCORE = 4.0                  # idf points a lesson needs to count as relevant (about two rare shared tokens)
ROOM = {"local": 220, "claude": 600}   # tokens of lessons at most: her 4096 window / Claude's
CHARS_PER_TOKEN = 3.5
TOKEN = re.compile(r"\b(?:E\d{4}|TS\d{4}|[A-Z]\d{3,4})\b|[A-Za-z_][A-Za-z0-9_]{2,}")
STOP = set("""the and for with from that this not are was were has have had but you your she her its into onto then
than when what which who why how all any can could should would will may might must one two use used using get got set
let var val def class self none true false null return import from pass else elif try except finally raise while
yield lambda async await pub mut impl struct enum trait mod crate super const static type fn match ref box new str
string int bool float list dict tuple test tests file files line lines code error failed fail fails passed pass ok
head base origin star next main merge merged merging conflict pull request litha she review diff http https www
github com org pull""".split())
_LOCAL = threading.local()       # lessons shown to this thread's prompts since its last settled outcome
_FORCED: dict | None = None      # replay: {"store": Store, "lanes": set} (self_tune; never written to)
_IO = threading.Lock()
_LAST_USE: dict[str, list[str]] = {}


def kind_of(path: str) -> str:
    name = path.rsplit("/", 1)[-1].lower()
    return name.rsplit(".", 1)[-1] if "." in name else name


def signature(*texts: str, limit: int = 40) -> list[str]:
    """The informative tokens of a task or an outcome: identifiers (whole, and the parts of snake_case / CamelCase
    ones), error codes; common words dropped; most frequent first."""
    count: collections.Counter = collections.Counter()
    for text in texts:
        for tok in TOKEN.findall(text or ""):
            parts = {tok.lower()} | {p.lower() for p in re.split(r"_|(?<=[a-z])(?=[A-Z])", tok) if len(p) >= 4}
            for p in parts:
                if p not in STOP and not p.isdigit():
                    count[p] += 1
    return [t for t, _ in count.most_common(limit)]


def make(lane: str, repo: str, path: str, sig_text: str, text: str, good: bool, evidence: list[str], source: str,
         key: str, case: str = "", ts: float | None = None) -> dict:
    """One lesson (its id is stable for the same lane/repo/key, so a backfill run twice adds nothing)."""
    return {"id": hashlib.sha1(f"{lane}|{repo}|{key}".encode()).hexdigest()[:16], "ts": int(ts or time.time()),
            "lane": lane, "repo": repo or STAR_REPO, "kind": kind_of(path) if path else "", "path": path,
            "sig": signature(sig_text, path), "text": " ".join(text.split())[:TEXT_CHARS], "good": bool(good),
            "evidence": [e for e in evidence if e][:4], "source": source, "case": case, "wins": 0, "losses": 0,
            "retired": False}


class Store:
    """The lessons of one file; reads are cheap (loaded once), writes are atomic rewrites."""

    def __init__(self, path: Path | None = STORE, lessons: list[dict] | None = None):
        self.path = path
        self.lessons: dict[str, dict] = {}
        if lessons is not None:
            self.lessons = {x["id"]: x for x in lessons}
        elif path and path.exists():
            for ln in path.read_text(encoding="utf-8").splitlines():
                with contextlib.suppress(ValueError, KeyError):
                    x = json.loads(ln)
                    self.lessons[x["id"]] = x
        self._idf: dict[str, float] | None = None
        self.same_path = False           # True: only lessons about one of the task's own files

    def add(self, lessons: list[dict]) -> int:
        """New lessons in (an id already known keeps its counts); returns how many were new."""
        n = 0
        for x in lessons:
            if x["id"] not in self.lessons:
                self.lessons[x["id"]] = x
                n += 1
        self._idf = None
        return n

    def save(self) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(f"{self.path.name}.{os.getpid()}.tmp")
        tmp.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in self.lessons.values()),
                       encoding="utf-8")
        os.replace(tmp, self.path)

    def active(self, lane: str | None = None) -> list[dict]:
        return [x for x in self.lessons.values() if not x.get("retired") and (lane is None or x["lane"] == lane)]

    def idf(self) -> dict[str, float]:
        if self._idf is None:
            df: collections.Counter = collections.Counter()
            live = self.active()
            for x in live:
                df.update(set(x["sig"]))
            n = len(live) + 1
            self._idf = {t: math.log(n / (1 + c)) + 1 for t, c in df.items()}
        return self._idf

    def retrieve(self, lane: str, repo: str = "", paths: list[str] | tuple = (), text: str = "", k: int = 3,
                 hide: str = "", before: float | None = None, sources=None,
                 same_path: bool | None = None) -> list[dict]:
        """The k most relevant active lessons of this lane for a task (repo + files + error / conflict text); a
        lesson made from the task itself (case == hide) or learnt after `before` (a replayed past task must not see
        what was learnt later) is never shown."""
        want = set(signature(text, *paths, limit=60))
        kinds = {kind_of(p) for p in paths}
        idf = self.idf()
        scored = []
        for x in self.active(lane):
            if sources is not None and x["source"] not in sources:
                continue
            if (self.same_path if same_path is None else same_path) and x.get("path") not in paths:
                continue
            if (hide and x.get("case") == hide) or (before is not None and x["ts"] > before):
                continue
            shared = want.intersection(x["sig"])
            s = sum(idf.get(t, 1.0) for t in shared)
            if not shared or s < MIN_SCORE:
                continue
            s += 2.0 * (x["repo"] == repo) + 1.5 * (x["kind"] in kinds) + 0.5 * (x["wins"] - x["losses"])
            scored.append((s, x["ts"], x))
        scored.sort(key=lambda t: (-t[0], -t[1]))
        out, seen = [], set()
        for _, _, x in scored:
            if x["text"] in seen:
                continue
            seen.add(x["text"])
            out.append(x)
            if len(out) == k:
                break
        return out

    def settle(self, ids: list[str], good: bool) -> list[str]:
        """Credit the lessons that were shown for a task with its outcome; returns the ids retired by it."""
        retired = []
        for i in dict.fromkeys(ids):
            x = self.lessons.get(i)
            if not x:
                continue
            x["wins" if good else "losses"] += 1
            if not x["retired"] and x["losses"] >= RETIRE_LOSSES and x["wins"] * 2 < x["losses"]:
                x["retired"] = True
                retired.append(i)
        self._idf = None
        return retired


def render(lessons: list[dict], room_tokens: float) -> str:
    """The lessons as a prompt block that fits room_tokens ("" when not even one fits)."""
    head = "Lessons from your own past work on similar tasks (use one only if it really applies here):\n"
    rows = []
    for x in lessons:
        row = f"- {'Worked' if x['good'] else 'Failed'}: {x['text']}\n"
        if (len(head) + sum(map(len, rows)) + len(row)) / CHARS_PER_TOKEN > room_tokens:
            break
        rows.append(row)
    return "\n" + head + "".join(rows) if rows else ""


# ---------------------------------------------------------------- prompts


_STORE_CACHE: dict[str, tuple[tuple[int, int], Store]] = {}


def _live_store() -> Store:
    """The store file, reloaded only when it changed (the fixer asks for lessons once per prompt). The size is part
    of the key: two writes inside one mtime tick kept the old store (CI: test_live_outcomes_settle_...)."""
    try:
        st = STORE.stat()
        mtime = (st.st_mtime_ns, st.st_size)
    except OSError:
        return Store(None, [])
    got = _STORE_CACHE.get(str(STORE))
    if not got or got[0] != mtime:
        got = (mtime, Store(STORE))
        _STORE_CACHE[str(STORE)] = got
    return got[1]


def switch_sources() -> set | None:
    """The lesson sources the nightly gate measured (on.json "sources"); None = all."""
    try:
        got = json.loads(SWITCH.read_text(encoding="utf-8")).get("sources")
        return set(got) if got else None
    except (OSError, ValueError, AttributeError):
        return None


def switch_same_path() -> bool:
    """Whether the measured variant only used lessons about the task's own files (on.json "same_path")."""
    try:
        return bool(json.loads(SWITCH.read_text(encoding="utf-8")).get("same_path"))
    except (OSError, ValueError, AttributeError):
        return False


def enabled(lane: str) -> bool:
    if _FORCED is not None:
        return lane in _FORCED["lanes"]
    env = os.environ.get("LITHA_EXPERIENCE", "")
    if env in ("0", "1"):
        return env == "1"
    try:
        return lane in json.loads(SWITCH.read_text(encoding="utf-8")).get("lanes", [])
    except (OSError, ValueError, AttributeError):
        return False


@contextlib.contextmanager
def forced(store: Store, lanes=LANES, hide: str = "", before: float | None = None):
    """Replay only: these lanes get lessons from this store, whatever on.json says, never the lessons made from case
    `hide` nor any learnt after `before` (the replayed case's own time); nothing is recorded."""
    global _FORCED
    old, _FORCED = _FORCED, {"store": store, "lanes": set(lanes), "hide": hide, "before": before}
    try:
        yield
    finally:
        _FORCED = old


def note(task: dict | None, room_tokens: float, who: str = "local") -> str:
    """The lessons block for a prompt of task {"lane", "repo", "paths", "text", "key"?, "hide"?} ("" when the lane is
    off, nothing relevant is known or nothing fits). Shown lessons are remembered for settling."""
    if not task or not enabled(task.get("lane", "")):
        return ""
    try:
        store = _FORCED["store"] if _FORCED is not None else _live_store()
        found = store.retrieve(task["lane"], task.get("repo", ""), task.get("paths") or (), task.get("text", ""),
                               hide=(_FORCED or {}).get("hide") or task.get("hide", ""),
                               before=(_FORCED or {}).get("before"),
                               sources=None if _FORCED is not None else switch_sources(),
                               same_path=None if _FORCED is not None else switch_same_path())
        text = render(found, min(room_tokens, ROOM[who]))
    except Exception:  # noqa: BLE001 - lessons are a help, never a reason to fail a task
        return ""
    shown = [x["id"] for x in found if f"{x['text']}\n" in text]
    if shown and _FORCED is None:
        if task.get("key"):
            if _LAST_USE.get(task["key"]) != shown:          # the merger reviews an open PR every 10 min: once
                _LAST_USE[task["key"]] = shown
                _append(USES, {"ts": int(time.time()), "lane": task["lane"], "key": task["key"], "ids": shown})
        else:
            _LOCAL.__dict__.setdefault("ids", []).extend(shown)
    return text


def _append(path: Path, row: dict) -> None:
    with _IO, contextlib.suppress(OSError):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------- lessons from outcomes


FIX_LANES = {"merge": "resolve", "rust": "fix-rust", "types": "fix-python", "frontend": "fix-python", None: "fix-python"}
NOISE = re.compile(r"^(the failing tests pass locally|reran|no pytest failure|failed logs expired|fetch failed|"
                   r"another|push failed|commit (refused|failed)|her own fix branch|her proof test)", re.I)


def lessons_from_fix(row: dict, fate: dict | None = None) -> list[dict]:
    """A fixes.jsonl row -> lessons (none for reruns, skips and infrastructure failures). fate = the state of her fix
    PR {"state": MERGED/CLOSED/OPEN} when known."""
    result, why = row.get("result"), " ".join(str(row.get("why") or "").split())
    if result not in ("fixed", "failed") or not why or NOISE.search(why):
        return []
    repo, kind = row.get("repo") or STAR_REPO, row.get("kind")
    lane = FIX_LANES.get(kind, "fix-python")
    tests = ", ".join(row.get("tests") or [])[:120]
    files = row.get("files") or []
    pr = f"https://github.com/{repo}/pull/{row['pr']}"
    evidence = [pr, row.get("fix_pr") if str(row.get("fix_pr", "")).startswith("http") else ""]
    good = result == "fixed"
    if good and fate and fate.get("state") == "CLOSED":
        good, why = False, f"{why} -- her fix PR was closed without merging"
    elif good and fate and fate.get("state") == "MERGED":
        why = f"{why} (her fix PR merged)"
    out = []
    if lane == "resolve":
        hit = re.match(r"([\w./-]+\.\w+): (.*)", why)
        if not good and hit:                       # a failed conflict: the lesson is about that file
            out.append(make("resolve", repo, hit.group(1), hit.group(2), f"{hit.group(1)}: {hit.group(2)}", False,
                            evidence, "fixes", f"fix|{row['pr']}|{row.get('ts')}|{hit.group(1)}", ts=row.get("ts")))
        elif not good:
            out.append(make("resolve", repo, files[0] if files else "", why, f"merging #{row['pr']}: {why}", False,
                            evidence, "fixes", f"fix|{row['pr']}|{row.get('ts')}", ts=row.get("ts")))
        return out
    what = (f"{tests} failed; the fix that worked: {why}" + (f" (edited {', '.join(files[:3])})" if files else "")
            if good else f"fixing {tests or kind or 'the checks'} failed: {why}")
    out.append(make(lane, repo, files[0] if files else (row.get("tests") or [""])[0], f"{tests} {why}", what, good,
                    evidence, "fixes", f"fix|{row['pr']}|{row.get('ts')}", ts=row.get("ts")))
    return out


LITHA_CLAIM = re.compile(r"^Litha: ([\w./-]+\.\w+):(\d+) (.*)$")


def lessons_from_decisions(rows: list[dict], fates: dict[tuple[str, int], dict]) -> list[dict]:
    """Her review holds settled by what happened to the PR later, and her merges that were reverted.
    fates[(repo, pr)] = {"state": MERGED/CLOSED/OPEN, "reverted": bool}."""
    last: dict[tuple[str, int], dict] = {}
    for r in rows:
        if r.get("action") in ("hold", "ready", "merge"):
            last[(r.get("repo") or STAR_REPO, r["pr"])] = r
    out = []
    for (repo, pr), r in last.items():
        fate = fates.get((repo, pr))
        if not fate or fate.get("state") == "OPEN":
            continue
        link = f"https://github.com/{repo}/pull/{pr}"
        if r.get("action") == "merge" or r.get("merged"):
            if fate.get("reverted"):
                out.append(make("merge-review", repo, (r.get("files") or [""])[0] if isinstance(r.get("files"), list)
                                else "", r.get("title", ""), f"her merge of #{pr} ({r.get('title', '')[:80]}) was "
                                "reverted later: what looked safe in review was not", False, [link], "decisions",
                                f"merge|{pr}", ts=r.get("ts")))
            continue
        if r.get("action") != "hold":
            continue
        for reason in r.get("reasons") or []:
            m = LITHA_CLAIM.match(reason)
            if not m:
                continue
            path, claim = m.group(1), m.group(3)
            if fate.get("state") == "MERGED":
                text, good = (f"a hold on \"{claim[:150]}\" ({kind_of(path)}) was overturned: a person merged #{pr} "
                              "anyway; this kind of claim was wrong"), False
            else:
                text, good = f"a hold on \"{claim[:150]}\" ({kind_of(path)}) stood: #{pr} was closed unmerged", True
            out.append(make("merge-review", repo, path, claim, text, good, [link], "decisions",
                            f"hold|{pr}|{path}|{claim[:60]}", ts=r.get("ts")))
    return out


def _norm(text: str) -> list[str]:
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def merge_shape(ours: str, base: str, theirs: str, good: str) -> str:
    """What the accepted resolution of one conflict block did, in words."""
    o, b, t, g = _norm(ours), _norm(base), _norm(theirs), _norm(good)
    if g == t and o != t:
        return "took only the base branch's side; the PR's lines were dropped (already there in another form)"
    if g == o and o != t:
        return "took only the PR's side; the base branch's lines were dropped"
    new_o = [ln for ln in o if ln not in b]
    new_t = [ln for ln in t if ln not in b]
    if new_o and new_t and all(ln in g for ln in new_o + new_t):
        first = next((ln for ln in g if ln in new_o or ln in new_t), "")
        return ("kept both sides' new lines, the PR's first" if first in new_o else
                "kept both sides' new lines, the base branch's first")
    if not g:
        return "removed the whole block (both sides' lines)"
    return "combined them line by line (neither side was kept whole)"


def lessons_from_replay(cases: list[dict], result: dict) -> list[dict]:
    """Tune-split conflict cases she got wrong or refused, with a known committed resolution: what the accepted merge
    did per block. Hold-out cases are never used (they measure the lessons)."""
    from litha import pr_fixer as pf
    from litha import self_tune as st
    out = []
    by = {c["id"]: c for c in cases}
    for cid, r in result.get("cases", {}).items():
        c = by.get(cid)
        if (not c or c.get("split") != "tune" or c["kind"] != "merge" or not c.get("good")
                or r["outcome"] in st.GOOD or r["outcome"] == "error"):
            continue
        segs, blocks = pf.CONFLICT.split(c["raw"]), pf.CONFLICT.findall(c["raw"])
        for k, block in enumerate(blocks[:3]):
            i, j = st._anchor(c["good"], segs[k], segs[k + 1])
            if i is None:
                continue
            ours, base, theirs = pf.sides(block)
            shape = merge_shape(ours, base, theirs, c["good"][i:j])
            names = sorted(pf.keys(block))[:3]
            about = f" ({'; '.join(names)})" if names else ""
            her = "she refused it" if r["outcome"] == "refused" else "her merge differed"
            out.append(make("resolve", c["repo"], c["path"], block, f"{c['path']}{about}: the accepted merge {shape}; "
                            f"{her}", True, [c["id"]], "replay", f"replay|{cid}|{k}", case=cid, ts=c.get("at")))
    return out


DISTILL = """You teach Litha, a local 12B model that resolves git merge conflicts (diff3 blocks: PR side, ancestor,
base side). Below are conflicts from a repository's history that she got wrong or refused, each with her answer (if
any) and the resolution a person committed. For EACH case write one lesson she can apply to FUTURE conflicts of the
same kind in this repository: a concrete rule (what to keep, drop, order or combine, and how to recognise the
situation), naming the file or code area when that is what makes it recognisable. Do not restate the specific code;
do not write generic advice such as "keep both sides" unless the case shows a specific way to do it. At most 200
characters each. Skip a case (no lesson) when the committed resolution is not explainable from the block alone.
{cases}
Answer only JSON: {{"lessons": [{{"case": "<case id>", "lesson": "<the rule>"}}]}}"""


def _shown_case(c: dict, r: dict) -> str:
    from litha import pr_fixer as pf
    from litha import self_tune as st
    segs, blocks = pf.CONFLICT.split(c["raw"]), pf.CONFLICT.findall(c["raw"])
    i, j = st._anchor(c["good"], segs[0], segs[1])
    mine = ((r.get("blocks") or [{}])[0].get("mine") or "") if r["outcome"] == "wrong" else ""
    head = f"### case {c['id']} ({c['path']}): she " + ("answered wrongly" if mine else "refused: " + r.get("why", "")[:150])
    good = (c["good"][i:j] if i is not None else "(not found)")[:900]
    return "\n".join([head, "Conflict block:", blocks[0][:1400]] + (["Her answer:", mine[:700]] if mine else [])
                     + ["Committed resolution:", good, ""])


def distill(cases: list[dict], result: dict, asker, batch: int = 8, limit: int = 160) -> list[dict]:
    """Claude's one-line lessons from the TUNE split's failures with a known committed resolution (source
    "distilled"; their time is the case's, so a replayed earlier case never sees them)."""
    from litha import pr_fixer as pf
    from litha import self_tune as st
    by = {c["id"]: c for c in cases}
    todo = [(by[cid], r) for cid, r in result.get("cases", {}).items()
            if cid in by and by[cid].get("split") == "tune" and by[cid]["kind"] == "merge" and by[cid].get("good")
            and r["outcome"] not in st.GOOD and r["outcome"] != "error"][:limit]
    out = []
    for k in range(0, len(todo), batch):
        part = todo[k:k + batch]
        text = asker(DISTILL.format(cases="\n".join(_shown_case(c, r) for c, r in part)))
        try:
            rows = json.loads(text[text.find("{"):text.rfind("}") + 1])["lessons"]
        except (ValueError, KeyError, TypeError):
            continue
        for row in rows if isinstance(rows, list) else []:
            c = by.get(str(row.get("case", ""))) if isinstance(row, dict) else None
            if c is None or c not in [p[0] for p in part] or not str(row.get("lesson", "")).strip():
                continue
            out.append(make("resolve", c["repo"], c["path"], "\n".join(pf.CONFLICT.findall(c["raw"])),
                            str(row["lesson"]), True, [c["id"]],
                            "distilled", f"distill|{c['id']}", case=c["id"], ts=c.get("at")))
    return out


# ---------------------------------------------------------------- fates (gh) and backfill


def gh_fates(repos: list[str], run=subprocess.run) -> dict[tuple[str, int], dict]:
    """{(repo, pr): {"state", "reverted"}} from one `gh pr list` per repo (read only)."""
    out = {}
    for repo in repos:
        try:
            r = run(["gh", "pr", "list", "--repo", repo, "--state", "all", "--limit", "2000", "--json",
                     "number,state,title"], capture_output=True, text=True, encoding="utf-8", errors="replace",
                    timeout=300)
            prs = json.loads(r.stdout) if r.returncode == 0 else []
        except (OSError, ValueError, subprocess.SubprocessError):
            prs = []
        reverts = " ".join(p["title"] for p in prs if p["title"].startswith("Revert"))
        for p in prs:
            out[(repo, p["number"])] = {"state": p["state"],
                                        "reverted": f"#{p['number']}" in reverts or f'"{p["title"]}"' in reverts}
    return out


def _rows(path: Path) -> list[dict]:
    out = []
    if path.exists():
        for ln in path.read_text(encoding="utf-8").splitlines():
            with contextlib.suppress(ValueError):
                out.append(json.loads(ln))
    return out


def fix_pr_number(link: str) -> tuple[str, int] | None:
    m = re.search(r"github\.com/([\w.-]+/[\w.-]+)/pull/(\d+)", link or "")
    if not m:
        return None
    repo = m.group(1).replace("Star-AI-Private", "Star-AI-Project")      # the repo was renamed (2026-10-31)
    return repo, int(m.group(2))


def backfill(store: Store, fixes: Path = FIXES, decisions: Path = DECISIONS, fates: dict | None = None,
             replay: tuple[list[dict], dict] | None = None) -> dict:
    """Every lesson her logs hold (repos in self_tune.EXCLUDED left out); returns {source: new lessons}. Also settles
    review lessons' uses."""
    from litha.self_tune import EXCLUDED
    fates = fates or {}
    got: dict[str, int] = {}
    fix_rows = [r for r in _rows(fixes) if r.get("repo") not in EXCLUDED]
    new = []
    for row in fix_rows:
        key = fix_pr_number(str(row.get("fix_pr") or ""))
        new += lessons_from_fix(row, fates.get(key) if key else None)
    got["fixes"] = store.add(new)
    got["decisions"] = store.add(lessons_from_decisions(
        [r for r in _rows(decisions) if r.get("repo") not in EXCLUDED], fates))
    if replay:
        got["replay"] = store.add(lessons_from_replay(*replay))
    got["settled"] = settle_reviews(store, fates, _rows(decisions))
    return got


def settle_reviews(store: Store, fates: dict, decisions: list[dict], uses: Path | None = None) -> int:
    """Review lessons shown for a PR whose fate is now known: a win when her last verdict matched it (hold and closed,
    ready/merge and merged), a loss when it did not. Settled rows are dropped from uses.jsonl."""
    uses = uses or USES
    last = {}
    for r in decisions:
        if r.get("action") in ("hold", "ready", "merge"):
            last[f"{r.get('repo') or STAR_REPO}#{r['pr']}"] = r["action"]
    rows, keep, n = _rows(uses), [], 0
    for u in rows:
        repo, _, pr = u.get("key", "").rpartition("#")
        fate = fates.get((repo, int(pr))) if pr.isdigit() else None
        verdict = last.get(u.get("key", ""))
        if not fate or fate.get("state") == "OPEN" or not verdict:
            keep.append(u)
            continue
        store.settle(u["ids"], (verdict == "hold") == (fate["state"] == "CLOSED"))
        n += 1
    if n and uses.exists():
        uses.write_text("".join(json.dumps(u) + "\n" for u in keep), encoding="utf-8")
    return n


def record_fix(row: dict, store_path: Path | None = None) -> None:
    """Live (pr_fixer.log_row): the row's lesson in, the lessons this thread showed settled by its result."""
    shown = getattr(_LOCAL, "ids", [])
    _LOCAL.ids = []
    new = lessons_from_fix(row)
    if not new and not shown:
        return
    with _IO:
        store = Store(store_path or STORE)
        store.add(new)
        if shown and row.get("result") in ("fixed", "failed"):
            store.settle(shown, row["result"] == "fixed")
        store.save()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m litha.experience")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("backfill", help="lessons from fixes.jsonl, decisions.jsonl (+ gh fates) and the replay")
    b.add_argument("--no-gh", action="store_true", help="skip the PR fates (no gh call)")
    b.add_argument("--replay", action="store_true", help="also the tune-split replay failures (scores from cache)")
    s = sub.add_parser("show", help="counts per lane / source, and the newest lessons")
    s.add_argument("--lane", default="")
    q = sub.add_parser("query", help="the lessons a task would get")
    q.add_argument("--lane", required=True)
    q.add_argument("--repo", default=STAR_REPO)
    q.add_argument("--path", action="append", default=[])
    q.add_argument("--text", default="")
    a = ap.parse_args(argv)
    store = Store()
    if a.cmd == "backfill":
        from litha.self_tune import EXCLUDED
        repos = sorted({r.get("repo") or STAR_REPO for r in _rows(DECISIONS) + _rows(FIXES)} - set(EXCLUDED))
        fates = {} if a.no_gh else gh_fates(repos)
        replay = None
        if a.replay:
            from litha import self_tune as st
            cases_ = st.cases()
            replay = (cases_, st.score({}, cases_, model=st.cached_only, log=None))
        print(json.dumps(backfill(store, fates=fates, replay=replay)))
        store.save()
    lessons = store.active(getattr(a, "lane", "") or None) if a.cmd != "query" else []
    if a.cmd in ("backfill", "show"):
        c = collections.Counter((x["lane"], x["source"], x["good"]) for x in lessons)
        for (lane, src, good), n in sorted(c.items()):
            print(f"  {lane:<13} {src:<10} {'worked' if good else 'failed':<7} {n}")
        print(f"  active {len(lessons)}, retired {sum(x['retired'] for x in store.lessons.values())}")
    if a.cmd == "query":
        for x in store.retrieve(a.lane, a.repo, a.path, a.text):
            print(f"- [{x['id']}] {'Worked' if x['good'] else 'Failed'}: {x['text']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
