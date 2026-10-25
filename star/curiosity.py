"""Curiosity queue (issue #555 B4): what STAR did not know or got wrong, kept so night school can study it.

One JSON line per event in `<STAR data folder>/curiosity.jsonl` (override: STAR_CURIOSITY_FILE; STAR_CURIOSITY=off
switches recording off). Recording is a local file append with no model and no network call, so it adds nothing
measurable to a chat turn. The five kinds:

  tool_failure         a tool call returned an error (topic: the tool name; counted, not studied)
  unknown_answer       the answer said it did not know (topic: the question)
  weak_retrieval       documentation search returned nothing, or an exact API name was not found
  failed_verification  the check-fix ladder could not clear a rung (topic: rung and error signature)
  api_change           the Roblox API dump gained or deprecated a member (star/api_dump_diff.py)

The queue is event-sourced: nothing is rewritten, `load()` folds the lines into one item per (kind, topic) with a
count. Night school (server/night_school/nightschool/conductor.py) takes `ranked()` items, turns them into practice
tasks and appends a resolution line (`taught`, or `tried` when no task survived its validators). Text is passed
through star.redact before it is stored. Developer tool: `python -m star.curiosity show`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import time

from .redact import redact_text

WEIGHTS = {"failed_verification": 3.0, "api_change": 3.0, "unknown_answer": 2.0, "weak_retrieval": 2.0,
           "tool_failure": 1.0}
PRACTICE_KINDS = ("failed_verification", "api_change", "unknown_answer", "weak_retrieval")   # kinds night school studies
RESOLUTIONS = ("taught", "answered", "tried")
MAX_BYTES = 1_000_000          # a queue file above this is compacted, and refused new lines if still above it
HALF_LIFE_DAYS = 14.0
EXPIRE_DAYS = 45.0
MAX_TRIES = 3                  # `tried` lines after which an item nobody could teach stops being offered
TOPIC_CHARS = 160
DETAIL_CHARS = 240
_STAMP = "%Y-%m-%dT%H:%M:%SZ"
_OFF = ("0", "off", "no", "false")
_FENCE = re.compile(r"```.*?(?:```|\Z)", re.S)
_UNKNOWN = re.compile(
    r"\b(?:i (?:do not|don't|dont) (?:know|have (?:enough |any |reliable )?(?:information|info|data|record))"
    r"|i(?:'m| am) not (?:sure|certain|aware)"
    r"|i (?:could not|couldn't|can't|cannot|was unable to|am unable to) (?:find|verify|confirm|locate)"
    r"|i have no (?:information|record|data|idea)"
    r"|(?:not enough|insufficient) (?:information|documentation)"
    r"|no (?:reliable |official )?(?:documentation|information) (?:on|about|for))\b", re.I)


def enabled() -> bool:
    return os.environ.get("STAR_CURIOSITY", "on").strip().lower() not in _OFF


def queue_path() -> Path:
    override = os.environ.get("STAR_CURIOSITY_FILE")
    if override:
        return Path(override)
    from .desktop_core import app_data
    return app_data() / "curiosity.jsonl"


def _now() -> str:
    return time.strftime(_STAMP, time.gmtime())


def _clean(text: object, limit: int) -> str:
    return " ".join(redact_text(str(text or "")).split())[:limit]


def make_key(kind: str, topic: str) -> str:
    """Stable id of one (kind, topic): case, spacing and digits do not split an item."""
    words = re.sub(r"\d+", "#", " ".join(str(topic).lower().split()))
    return hashlib.sha256(f"{kind}\0{words}".encode("utf-8")).hexdigest()[:16]


def record(kind: str, topic: str, detail: str = "", *, path: Path | None = None) -> bool:
    """Append one event. Never raises; False when it was not recorded (off, unknown kind, empty topic, file full)."""
    try:
        if kind not in WEIGHTS or not enabled():
            return False
        topic, detail = _clean(topic, TOPIC_CHARS), _clean(detail, DETAIL_CHARS)
        if len(topic) < 4:
            return False
        target = Path(path) if path else queue_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and target.stat().st_size > MAX_BYTES:
            compact(target)
            if target.stat().st_size > MAX_BYTES:
                return False
        row = {"ts": _now(), "kind": kind, "key": make_key(kind, topic), "topic": topic, "detail": detail}
        with target.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        return True
    except Exception:
        return False


def note_answer(question: str, answer: str, *, path: Path | None = None) -> bool:
    """Record the question when the answer (outside code blocks) says STAR did not know. Never raises."""
    try:
        found = _UNKNOWN.search(_FENCE.sub(" ", str(answer or ""))[:600])
        if not found or len(str(question or "").strip()) < 8:
            return False
        return record("unknown_answer", question, found.group(0), path=path)
    except Exception:
        return False


@dataclass
class Item:
    key: str
    kind: str
    topic: str
    detail: str = ""
    count: int = 0
    first: str = ""
    last: str = ""
    taught: str = ""          # timestamp of the latest `taught` / `answered` line
    tried: int = 0
    tried_last: str = ""
    by: list = field(default_factory=list)

    def is_open(self) -> bool:
        if self.taught and self.taught >= self.last:
            return False                         # studied since it last happened; a new event reopens it
        return not (self.tried >= MAX_TRIES and self.tried_last >= self.last)

    def score(self, now: float | None = None) -> float:
        age = max(0.0, ((now if now is not None else time.time()) - _epoch(self.last)) / 86400)
        return WEIGHTS.get(self.kind, 1.0) * math.log2(1 + self.count) * 0.5 ** (age / HALF_LIFE_DAYS)


def _epoch(stamp: str) -> float:
    try:
        return datetime.strptime(stamp, _STAMP).replace(tzinfo=timezone.utc).timestamp()
    except (TypeError, ValueError):
        return 0.0


def _rows(path: Path):
    try:
        with Path(path).open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict) and isinstance(row.get("key"), str) and isinstance(row.get("ts"), str):
                    yield row
    except OSError:
        return


def load(*paths: Path) -> dict[str, Item]:
    """Fold the lines of one or more queue files into items by key. A line with `count` is an aggregate (a pushed
    snapshot or a compacted file); a line with `resolved` closes or counts a study attempt."""
    items: dict[str, Item] = {}
    done: list[dict] = []
    for path in paths or (queue_path(),):
        for row in _rows(Path(path)):
            if row.get("resolved") is not None:
                done.append(row)
                continue
            kind, topic = row.get("kind"), row.get("topic")
            if kind not in WEIGHTS or not isinstance(topic, str) or not topic:
                continue
            item = items.get(row["key"])
            if item is None:
                item = items[row["key"]] = Item(row["key"], kind, topic[:TOPIC_CHARS], first=str(row.get("first") or row["ts"]))
            count = row.get("count")
            item.count += min(count, 10_000) if type(count) is int and count > 0 else 1
            item.first = min(item.first, str(row.get("first") or row["ts"]))
            if row["ts"] >= item.last:
                item.last, item.topic = row["ts"], topic[:TOPIC_CHARS]
                item.detail = str(row.get("detail") or "")[:DETAIL_CHARS]
    for row in done:
        item = items.get(row["key"])
        if item is None or row["resolved"] not in RESOLUTIONS:
            continue
        if row["resolved"] == "tried":
            item.tried += 1
            item.tried_last = max(item.tried_last, row["ts"])
        else:
            item.taught = max(item.taught, row["ts"])
        if row.get("by") and len(item.by) < 5:
            item.by.append(str(row["by"])[:60])
    return items


def ranked(limit: int = 8, *, kinds: tuple = PRACTICE_KINDS, paths: tuple = (), now: float | None = None) -> list[Item]:
    """The open items worth studying, best first: weight x log(count) x recency (two-week half-life)."""
    at = now if now is not None else time.time()
    live = [i for i in load(*paths).values()
            if i.kind in kinds and i.is_open() and at - _epoch(i.last) < EXPIRE_DAYS * 86400]
    return sorted(live, key=lambda i: (-i.score(at), i.key))[:max(0, limit)]


def resolve(keys: list[str], how: str, by: str = "", *, path: Path | None = None) -> int:
    """Append a resolution line per key (`taught`/`answered` close the item, `tried` counts an attempt)."""
    if how not in RESOLUTIONS:
        raise ValueError("how must be one of " + ", ".join(RESOLUTIONS))
    target = Path(path) if path else queue_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    stamp = _now()
    with target.open("a", encoding="utf-8", newline="\n") as handle:
        for key in keys:
            handle.write(json.dumps({"ts": stamp, "key": key, "resolved": how, "by": by[:60]}) + "\n")
    return len(keys)


def snapshot(limit: int = 200, *, path: Path | None = None, now: float | None = None) -> bytes:
    """The open practice items as aggregate lines (what the PC pushes to server 1), best first."""
    lines = [json.dumps({"ts": i.last, "first": i.first, "kind": i.kind, "key": i.key, "topic": i.topic,
                         "detail": i.detail, "count": i.count}, ensure_ascii=False)
             for i in ranked(limit, paths=(path,) if path else (), now=now)]
    return ("\n".join(lines) + "\n").encode("utf-8") if lines else b""


def merge_resolutions(text: str, *, path: Path | None = None) -> int:
    """Append the resolution lines of another machine's queue (server 1's `curiosity-done.jsonl`) that this file
    does not have yet, so a studied item stops being pushed and shows as studied. Returns lines added."""
    target = Path(path) if path else queue_path()
    have = {(r["key"], r["ts"], r["resolved"]) for r in _rows(target) if r.get("resolved") is not None}
    added = []
    for line in text.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if (isinstance(row, dict) and isinstance(row.get("key"), str) and re.fullmatch(r"[0-9a-f]{16}", row["key"])
                and isinstance(row.get("ts"), str) and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", row["ts"])
                and row.get("resolved") in RESOLUTIONS and (row["key"], row["ts"], row["resolved"]) not in have):
            have.add((row["key"], row["ts"], row["resolved"]))
            added.append({"ts": row["ts"], "key": row["key"], "resolved": row["resolved"],
                          "by": str(row.get("by") or "")[:60]})
    if added:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8", newline="\n") as handle:
            for row in added:
                handle.write(json.dumps(row) + "\n")
    return len(added)


def compact(path: Path) -> None:
    """Rewrite the file as one aggregate line per recent item plus its resolution lines (atomic replace)."""
    path = Path(path)
    items = load(path)
    keep = [i for i in items.values() if time.time() - _epoch(i.last) < EXPIRE_DAYS * 86400]
    resolutions = [r for r in _rows(path) if r.get("resolved") is not None and r["key"] in {i.key for i in keep}]
    out = [json.dumps({"ts": i.last, "first": i.first, "kind": i.kind, "key": i.key, "topic": i.topic,
                       "detail": i.detail, "count": i.count}, ensure_ascii=False) for i in keep]
    out += [json.dumps({k: r[k] for k in ("ts", "key", "resolved", "by") if k in r}) for r in resolutions[-2000:]]
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("\n".join(out) + ("\n" if out else ""), encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def main(argv: list[str] | None = None) -> int:
    import sys
    args = sys.argv[1:] if argv is None else argv
    if args[:1] == ["show"]:
        for item in ranked(int(args[1]) if len(args) > 1 else 10):
            print(f"{item.score():6.2f}  {item.kind:20s} x{item.count:<3d} {item.topic}")
        return 0
    print("usage: python -m star.curiosity show [N]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
