"""What STAR learned this week: night school's reviewed bundle reaching the app, visibly, with expiry and undo.

W7 of docs/research/self-improving-star-claude-v2.md, with the owner's defaults (docs/agents/context/
CHATGPT_PLANS_20261013.md, owner decision O1):

* The nightly export is a REVIEWED BUNDLE (`star-learning-bundle-v1`), built from night school's outbox by
  `python -m star.learned_week bundle` and committed through a draft pull request. Nothing reaches the app silently and
  no weights change: a bundle is text (lessons) and checked practice answers (worked examples).
* A text-only lesson goes live automatically ("provisional") only when its evidence shows it won night school's paired
  gate (W1, decision PROMOTE) against the protected baseline on the held-out validation slice. Everything else (the
  old single-run rule, INCONCLUSIVE, no evidence) arrives as a candidate that waits for the owner, as before.
* Every item that goes live is listed in "What STAR learned this week" with its evidence, expires 14 days after it
  went live unless the owner presses Keep, and can be undone with one click. Undo, then Restore, gives back the
  byte-identical lesson row. The owner can turn automatic use off (`learning_auto_live`); then bundles only add
  candidates.
* A lesson is text only (star/lessons.py refuses keys, passwords and permission requests). Nothing here can edit an
  evaluation, a grader, the gate or a setting.

Storage: lesson rows stay in the knowledge database (`notes`), with `revision = "provisional:<expiry ISO time>"` so that
recall skips an expired lesson even before the next sweep; this module's own table `learned_items` keeps the evidence,
the dates and a snapshot of each row for undo. Worked examples go to `worked_examples.sqlite3` (star/worked_examples.py)
with their expiry in `example_expiry`; using them in answers stays behind the owner's `worked_examples_enabled`.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3

from .knowledge import _project, now
from .lessons import (LESSON_KINDS, LessonRefused, LessonStore, check_lesson_text, has_secret, redact,
                      subject_key, _normal)

FORMAT = "star-learning-bundle-v1"
EXPIRY_DAYS = 14
WEEK_DAYS = 7
PROVISIONAL = "provisional:"
MAX_BUNDLE_BYTES = 6 * 1024 * 1024
MAX_LESSONS = 200
GATE = re.compile(r"paired gate (PROMOTE|REJECT|INCONCLUSIVE|UNDERPOWERED|INCOMPLETE): (\d+) wins / (\d+) losses over (\d+) "
                  r"tasks x k=(\d+), sign test p=([0-9.eE+-]+|None)")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,99}\Z")
STATES = ("live", "undone", "expired", "kept")

_SCHEMA = """CREATE TABLE IF NOT EXISTS learned_items (
    id INTEGER PRIMARY KEY, project TEXT NOT NULL, kind TEXT NOT NULL, ref TEXT NOT NULL, title TEXT NOT NULL,
    evidence TEXT NOT NULL, gate TEXT NOT NULL, live_at TEXT NOT NULL, expires_at TEXT NOT NULL, state TEXT NOT NULL,
    snapshot TEXT NOT NULL, bundle TEXT NOT NULL, UNIQUE(project, kind, ref))"""
_NOTE_COLUMNS = ("kind", "text", "source", "revision", "reviewed", "created", "status", "source_type", "updated",
                 "subject", "evidence", "supersedes_id", "merged_into")


def _utc(stamp: str) -> datetime:
    value = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise ValueError("time without a zone")
    return value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def expired(revision: str, at: str) -> bool:
    """True for a provisional lesson whose 14 days are over (the same comparison recall makes in SQL)."""
    return str(revision).startswith(PROVISIONAL) and str(revision)[len(PROVISIONAL):] <= at


# --- the bundle ----------------------------------------------------------------------------------------------------

def gate_of(evidence: str) -> dict:
    """The paired-gate verdict written into a night-school lesson's evidence; {"decision": "NONE"} when absent."""
    found = GATE.search(evidence or "")
    if not found:
        return {"decision": "LEGACY" if "old single-run" in (evidence or "") else "NONE"}
    decision, wins, losses, tasks, k, p = found.groups()
    return {"decision": decision, "wins": int(wins), "losses": int(losses), "tasks": int(tasks), "k": int(k),
            "p_better": None if p == "None" else float(p)}


def build_bundle(outbox: Path, *, project: str = "STAR", created: str | None = None, scoreboard: str = "",
                 report: dict | None = None) -> dict:
    """Package night school's outbox (`star-lessons-night-school.json`, `worked-examples.jsonl`) for review.
    Every row is validated with the app's own importers first; the bundle is plain data for a pull request."""
    from .lesson_import import read_export
    from .worked_examples import validate_row
    outbox = Path(outbox)
    lessons, examples = [], []
    lesson_file = outbox / "star-lessons-night-school.json"
    if lesson_file.is_file():
        data = read_export(lesson_file)
        for row in data["lessons"]:
            if row["status"] not in ("candidate", "accepted"):
                continue
            ident = str(row["source"]).removeprefix("night-school:")
            if not _ID.fullmatch(ident) or row["kind"] not in LESSON_KINDS:
                continue
            lessons.append({"id": ident, "kind": row["kind"], "text": row["text"], "evidence": row["evidence"],
                            "gate": gate_of(row["evidence"])})
    example_file = outbox / "worked-examples.jsonl"
    skipped: dict[str, int] = {}
    if example_file.is_file():
        for line in example_file.read_text(encoding="utf-8").splitlines()[:500]:
            try:
                row = json.loads(line)
                validate_row(row)                                  # the app's own importer rules, row by row
            except (ValueError, RecursionError) as exc:
                reason = str(exc)[:60]
                skipped[reason] = skipped.get(reason, 0) + 1       # e.g. an answer longer than the import limit
                continue
            examples.append(row)
    if not lessons and not examples:
        raise ValueError("the outbox holds no lessons and no usable worked examples")
    bundle = {"format": FORMAT, "created": created or now(), "project": _project(project), "source": "night-school",
              "scoreboard": scoreboard[:2000], "lessons": lessons, "examples": examples}
    parse_bundle(bundle)
    if report is not None:
        report["skipped_examples"] = skipped
    return bundle


def parse_bundle(data: object) -> dict:
    """Validate a whole bundle before any write. Imported statuses are never trusted: only the gate verdict in the
    lesson's own evidence decides whether it may go live automatically."""
    from .worked_examples import validate_row
    if not isinstance(data, dict) or set(data) != {"format", "created", "project", "source", "scoreboard", "lessons",
                                                    "examples"}:
        raise ValueError("Invalid learning bundle fields")
    if data["format"] != FORMAT or data["source"] != "night-school":
        raise ValueError("Unsupported learning bundle")
    _utc(data["created"])
    project = _project(data["project"])
    if not isinstance(data["scoreboard"], str) or len(data["scoreboard"]) > 2000 or has_secret(data["scoreboard"]):
        raise ValueError("Invalid scoreboard")
    if not isinstance(data["lessons"], list) or len(data["lessons"]) > MAX_LESSONS:
        raise ValueError("Invalid lesson list")
    if not isinstance(data["examples"], list) or len(data["examples"]) > 500:
        raise ValueError("Invalid example list")
    seen = set()
    for row in data["lessons"]:
        if not isinstance(row, dict) or set(row) != {"id", "kind", "text", "evidence", "gate"}:
            raise ValueError("Invalid bundle lesson fields")
        if not isinstance(row["id"], str) or not _ID.fullmatch(row["id"]) or row["id"] in seen:
            raise ValueError("Invalid or repeated bundle lesson id")
        seen.add(row["id"])
        if row["kind"] not in LESSON_KINDS:
            raise ValueError("Invalid bundle lesson kind")
        check_lesson_text(row["text"])
        if not isinstance(row["evidence"], str) or len(row["evidence"]) > 1200 or has_secret(row["evidence"]):
            raise ValueError("Invalid bundle lesson evidence")
        if row["gate"] != gate_of(row["evidence"]):
            raise ValueError("The gate verdict must be the one written in the lesson's evidence")
    ids = set()
    for row in data["examples"]:
        example = validate_row(row)
        if example.id in ids:
            raise ValueError("Repeated worked example")
        ids.add(example.id)
    return {"project": project, "digest": hashlib.sha256(json.dumps(data, sort_keys=True).encode("utf-8")).hexdigest()}


def bundle_error(data: object) -> str | None:
    """None when `data` is a well-formed bundle, otherwise one plain sentence saying what is wrong (never raises)."""
    try:
        parse_bundle(data)
    except (ValueError, TypeError, RecursionError, LessonRefused) as exc:
        return str(exc) or type(exc).__name__
    return None


def read_bundle(path: Path) -> dict:
    with Path(path).open("rb") as handle:
        raw = handle.read(MAX_BUNDLE_BYTES + 1)
    if len(raw) > MAX_BUNDLE_BYTES:
        raise ValueError("Learning bundle exceeds 6 MiB")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise ValueError("Learning bundle is not UTF-8 JSON") from exc
    parse_bundle(data)
    return data


# --- the registry ----------------------------------------------------------------------------------------------------

class Registry:
    """Lessons (in the knowledge database) and worked examples that arrived from a bundle, with their dates."""

    def __init__(self, home: Path, *, clock=now):
        self.home = Path(home)
        self.clock = clock
        self.lessons = LessonStore(self.home)
        self.db = self.lessons.db
        self.db.execute(_SCHEMA)
        self.db.commit()

    def close(self) -> None:
        self.lessons.close()

    # -- worked examples -------------------------------------------------------------------------------------------
    def _examples(self) -> sqlite3.Connection:
        self.home.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.home / "worked_examples.sqlite3")
        db.execute("""CREATE TABLE IF NOT EXISTS worked_examples (
            project TEXT NOT NULL, id TEXT NOT NULL, group_id TEXT NOT NULL,
            category TEXT NOT NULL, instruction TEXT NOT NULL, response TEXT NOT NULL,
            PRIMARY KEY (project, id))""")
        db.execute("CREATE TABLE IF NOT EXISTS example_expiry (project TEXT NOT NULL, id TEXT NOT NULL, "
                   "expires_at TEXT NOT NULL, PRIMARY KEY (project, id))")
        return db

    # -- applying a bundle -----------------------------------------------------------------------------------------
    def apply(self, data: dict, *, auto_live: bool = True, project: str | None = None) -> dict:
        """Lessons with a PROMOTE verdict go live for 14 days (when `auto_live`); other lessons become candidates;
        worked examples are stored with a 14-day expiry. Idempotent: an item seen before is skipped. `project`
        (the app's current project) replaces the bundle's own project name."""
        info = parse_bundle(data)
        project, stamp = _project(project) if project else info["project"], self.clock()
        expires = _iso(_utc(stamp) + timedelta(days=EXPIRY_DAYS))
        receipt = {"project": project, "live": 0, "candidates": 0, "examples": 0, "skipped": 0,
                   "bundle": info["digest"][:12]}
        try:
            self.lessons._begin()
            texts = {_normal(r["text"]) for r in self.db.execute(
                "SELECT text FROM notes WHERE project=? AND status IS NOT NULL", (project,))}
            for row in data["lessons"]:
                source = "night-school:" + row["id"]
                known = self.db.execute("SELECT 1 FROM notes WHERE project=? AND source=? AND status IS NOT NULL",
                                        (project, source)).fetchone()
                if known or _normal(row["text"]) in texts:
                    receipt["skipped"] += 1
                    continue
                live = auto_live is True and row["gate"].get("decision") == "PROMOTE"
                evidence = redact(row["evidence"])
                note_id = int(self.db.execute(
                    """INSERT INTO notes(project,kind,text,source,revision,reviewed,created,status,source_type,updated,
                                         subject,evidence) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (project, row["kind"], check_lesson_text(row["text"]), source,
                     PROVISIONAL + expires if live else "candidate-imported", 1 if live else 0, stamp,
                     "accepted" if live else "candidate", "practice", stamp, subject_key(row["text"]),
                     evidence)).lastrowid)
                texts.add(_normal(row["text"]))
                if live:
                    self.db.execute(
                        "INSERT INTO learned_items(project,kind,ref,title,evidence,gate,live_at,expires_at,state,"
                        "snapshot,bundle) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                        (project, "lesson", str(note_id), row["text"][:300], evidence, json.dumps(row["gate"]),
                         stamp, expires, "live", json.dumps(self._note_row(note_id)), info["digest"][:12]))
                    receipt["live"] += 1
                else:
                    receipt["candidates"] += 1
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise
        if data["examples"]:
            from .worked_examples import MAX_ROWS
            examples = self._examples()
            try:
                with examples:
                    # The same per-project cap as worked_examples.import_file: retrieval refuses a
                    # corpus over MAX_ROWS usable (unexpired) rows, so a full corpus takes no more.
                    usable = examples.execute(
                        "SELECT COUNT(*) FROM worked_examples WHERE project=? AND id NOT IN "
                        "(SELECT id FROM example_expiry WHERE project=? AND expires_at<=?)",
                        (project, project, stamp)).fetchone()[0]
                    for row in data["examples"]:
                        if self.db.execute("SELECT 1 FROM learned_items WHERE project=? AND kind='example' AND ref=?",
                                           (project, row["id"])).fetchone():
                            receipt["skipped"] += 1
                            continue
                        if usable >= MAX_ROWS:
                            receipt["skipped"] += 1
                            continue
                        values = (project, row["id"], row["group_id"], row["task_category"], row["instruction"],
                                  row["response"])
                        if examples.execute("INSERT OR IGNORE INTO worked_examples VALUES (?,?,?,?,?,?)",
                                            values).rowcount == 0:
                            receipt["skipped"] += 1
                            continue
                        examples.execute("INSERT OR REPLACE INTO example_expiry VALUES (?,?,?)",
                                         (project, row["id"], expires))
                        self.db.execute(
                            "INSERT INTO learned_items(project,kind,ref,title,evidence,gate,live_at,expires_at,state,"
                            "snapshot,bundle) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                            (project, "example", row["id"], row["instruction"][:300],
                             "; ".join(row["evidence"])[:1200], "{}", stamp, expires, "live",
                             json.dumps(list(values)), info["digest"][:12]))
                        usable += 1
                        receipt["examples"] += 1
                self.db.commit()
            finally:
                examples.close()
        return receipt

    # -- reading ---------------------------------------------------------------------------------------------------
    def _note_row(self, note_id: int) -> dict:
        row = self.db.execute(f"SELECT {','.join(_NOTE_COLUMNS)} FROM notes WHERE id=?", (note_id,)).fetchone()
        return {k: row[k] for k in _NOTE_COLUMNS}

    def _item(self, project: str, item_id: int):
        if isinstance(item_id, bool) or not isinstance(item_id, int) or item_id < 1:
            raise ValueError("Invalid item identifier")
        row = self.db.execute("SELECT * FROM learned_items WHERE id=? AND project=?",
                              (item_id, _project(project))).fetchone()
        if row is None:
            raise ValueError("Item not found in this project")
        return row

    def sweep(self, project: str) -> int:
        """Retire every live item whose 14 days are over. Returns how many."""
        project, stamp = _project(project), self.clock()
        due = self.db.execute("SELECT * FROM learned_items WHERE project=? AND state='live' AND expires_at<=?",
                              (project, stamp)).fetchall()
        retired = 0
        for row in due:
            if row["kind"] == "lesson":
                note = self.db.execute("SELECT revision FROM notes WHERE id=?", (int(row["ref"]),)).fetchone()
                if note is None or not str(note["revision"]).startswith(PROVISIONAL):
                    # The owner approved, edited or removed it on the review page meanwhile: their decision stands.
                    self.db.execute("UPDATE learned_items SET state=?,expires_at='' WHERE id=?",
                                    ("kept" if note is not None else "undone", row["id"]))
                    self.db.commit()
                    continue
            self._switch_off(row, "provisional-expired", "expired", stamp)
            retired += 1
        return retired

    def week(self, project: str) -> dict:
        """Items that went live or expired in the last 7 days, plus every item still on its 14-day trial, newest
        first."""
        project = _project(project)
        self.sweep(project)
        stamp = self.clock()
        since = _iso(_utc(stamp) - timedelta(days=WEEK_DAYS))
        rows = self.db.execute(
            "SELECT * FROM learned_items WHERE project=? AND (live_at>=? OR state='live' OR "
            "(state='expired' AND expires_at>=?)) ORDER BY live_at DESC, id DESC LIMIT 200",
            (project, since, since)).fetchall()
        items = []
        for row in rows:
            uses = 0
            if row["kind"] == "lesson":
                found = self.db.execute("SELECT uses FROM lesson_use WHERE note_id=?", (int(row["ref"]),)).fetchone()
                uses = int(found["uses"]) if found else 0
            left = (_utc(row["expires_at"]) - _utc(stamp)).total_seconds() / 86400 if row["expires_at"] else None
            items.append({"id": row["id"], "kind": row["kind"], "title": row["title"], "evidence": row["evidence"],
                          "gate": json.loads(row["gate"] or "{}"), "live_at": row["live_at"],
                          "expires_at": row["expires_at"], "days_left": None if left is None else max(0, int(left + 0.999)),
                          "state": row["state"], "uses": uses})
        counts = {state: 0 for state in STATES}
        for state, total in self.db.execute("SELECT state,COUNT(*) FROM learned_items WHERE project=? GROUP BY state",
                                            (project,)):
            counts[state] = int(total)
        return {"project": project, "items": items, "counts": counts}

    # -- owner actions ---------------------------------------------------------------------------------------------
    def _switch_off(self, row, revision: str, state: str, stamp: str) -> None:
        if row["kind"] == "lesson":
            self.db.execute("UPDATE notes SET reviewed=0,status='rejected',revision=?,updated=? WHERE id=? AND project=?",
                            (revision, stamp, int(row["ref"]), row["project"]))
        else:
            examples = self._examples()
            try:
                with examples:
                    examples.execute("DELETE FROM worked_examples WHERE project=? AND id=?", (row["project"], row["ref"]))
                    examples.execute("DELETE FROM example_expiry WHERE project=? AND id=?", (row["project"], row["ref"]))
            finally:
                examples.close()
        self.db.execute("UPDATE learned_items SET state=? WHERE id=?", (state, row["id"]))
        self.db.commit()

    def undo(self, project: str, item_id: int, *, human_approved: bool = False) -> dict:
        """One click: STAR stops using this item now. The record stays so Restore can bring it back."""
        if human_approved is not True:
            raise PermissionError("Only the owner can undo a learned item")
        row = self._item(project, item_id)
        if row["state"] != "live":
            raise ValueError("Only an item that is in use can be undone")
        self._switch_off(row, "provisional-undone", "undone", self.clock())
        return self.week(project)

    def restore(self, project: str, item_id: int, *, human_approved: bool = False) -> dict:
        """Undo the undo: the lesson row comes back byte for byte (same text, status, revision and dates)."""
        if human_approved is not True:
            raise PermissionError("Only the owner can restore a learned item")
        row = self._item(project, item_id)
        if row["state"] != "undone":
            raise ValueError("Only an undone item can be restored")
        if row["expires_at"] <= self.clock():
            raise ValueError("Its 14 days are over; press Keep to keep it for good")
        snapshot = json.loads(row["snapshot"])
        if row["kind"] == "lesson":
            if self.db.execute("SELECT 1 FROM notes WHERE id=?", (int(row["ref"]),)).fetchone() is None:
                raise ValueError("This lesson was deleted on the review page")
            self.db.execute(f"UPDATE notes SET {','.join(k + '=?' for k in _NOTE_COLUMNS)} WHERE id=? AND project=?",
                            (*[snapshot[k] for k in _NOTE_COLUMNS], int(row["ref"]), row["project"]))
        else:
            examples = self._examples()
            try:
                with examples:
                    examples.execute("INSERT OR IGNORE INTO worked_examples VALUES (?,?,?,?,?,?)", tuple(snapshot))
                    examples.execute("INSERT OR REPLACE INTO example_expiry VALUES (?,?,?)",
                                     (row["project"], row["ref"], row["expires_at"]))
            finally:
                examples.close()
        self.db.execute("UPDATE learned_items SET state='live' WHERE id=?", (row["id"],))
        self.db.commit()
        return self.week(project)

    def keep(self, project: str, item_id: int, *, human_approved: bool = False) -> dict:
        """The owner keeps an item for good: a lesson becomes an owner-approved lesson, an example loses its expiry."""
        if human_approved is not True:
            raise PermissionError("Only the owner can keep a learned item")
        row = self._item(project, item_id)
        if row["state"] == "kept":
            return self.week(project)
        if row["kind"] == "lesson":
            self.lessons.approve(row["project"], int(row["ref"]), human_approved=True, keep_both=True)
        else:
            examples = self._examples()
            try:
                with examples:
                    if row["state"] != "live":
                        examples.execute("INSERT OR IGNORE INTO worked_examples VALUES (?,?,?,?,?,?)",
                                         tuple(json.loads(row["snapshot"])))
                    examples.execute("DELETE FROM example_expiry WHERE project=? AND id=?", (row["project"], row["ref"]))
            finally:
                examples.close()
        self.db.execute("UPDATE learned_items SET state='kept',expires_at='' WHERE id=?", (row["id"],))
        self.db.commit()
        return self.week(project)


# --- app bridge --------------------------------------------------------------------------------------------------

LEARNED_ACTIONS = frozenset({"learnedThisWeek", "learnedItem"})


def handle_action(home: Path, project: str, action: str, body: dict) -> dict:
    """`learnedThisWeek` lists; `learnedItem` {op: undo|restore|keep, id, approved: true} is an owner click."""
    if action not in LEARNED_ACTIONS:
        raise PermissionError("Action not permitted")
    if not isinstance(body, dict):
        raise ValueError("Invalid request")
    registry = Registry(home)
    try:
        if action == "learnedThisWeek":
            return registry.week(project)
        op = body.get("op")
        approved = body.get("approved") is True
        if op == "undo":
            return registry.undo(project, body.get("id"), human_approved=approved)
        if op == "restore":
            return registry.restore(project, body.get("id"), human_approved=approved)
        if op == "keep":
            return registry.keep(project, body.get("id"), human_approved=approved)
        raise ValueError("Unknown operation")
    finally:
        registry.close()


def import_bundled(home: Path, version: str, *, auto_live: bool = True, bundle: Path | None = None,
                   project: str | None = None) -> dict:
    """Apply the bundle shipped with this app version once (star/skill_packs/learning_bundle.json, when present)."""
    path = bundle or Path(__file__).parent / "skill_packs" / "learning_bundle.json"
    if not path.is_file():
        return {"status": "none"}
    if not isinstance(version, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,39}", version):
        raise ValueError("Invalid app version")
    registry = Registry(home)
    try:
        registry.db.execute("CREATE TABLE IF NOT EXISTS learning_bundle_imports (version TEXT PRIMARY KEY, "
                            "imported_at TEXT NOT NULL)")
        if registry.db.execute("SELECT 1 FROM learning_bundle_imports WHERE version=?", (version,)).fetchone():
            return {"status": "already"}
        receipt = registry.apply(read_bundle(path), auto_live=auto_live, project=project)
        registry.db.execute("INSERT INTO learning_bundle_imports VALUES(?,?)", (version, now()))
        registry.db.commit()
        return {"status": "imported", **receipt}
    finally:
        registry.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m star.learned_week", description=(__doc__ or "").split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    make = sub.add_parser("bundle", help="package night school's outbox as a reviewed bundle (for a draft PR)")
    make.add_argument("--outbox", required=True, type=Path)
    make.add_argument("--out", required=True, type=Path)
    make.add_argument("--project", default="STAR")
    make.add_argument("--scoreboard", type=Path, default=None, help="a text file (night school's report) to attach")
    take = sub.add_parser("import", help="apply a bundle to a STAR data folder (text lessons go live for 14 days)")
    take.add_argument("file", type=Path)
    take.add_argument("--home", type=Path, default=None)
    take.add_argument("--candidates-only", action="store_true", help="never go live automatically")
    take.add_argument("--project", default=None, help="the STAR project to add them to (default: the bundle's)")
    args = parser.parse_args(argv)
    try:
        if args.command == "bundle":
            board = args.scoreboard.read_text(encoding="utf-8")[:2000] if args.scoreboard else ""
            report: dict = {}
            data = build_bundle(args.outbox, project=args.project, scoreboard=board, report=report)
            if args.out.exists():
                raise FileExistsError(f"refusing to replace {args.out}")
            args.out.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
            live = sum(1 for l in data["lessons"] if l["gate"].get("decision") == "PROMOTE")
            print(f"Bundle: {len(data['lessons'])} lessons ({live} with a PROMOTE verdict), "
                  f"{len(data['examples'])} worked examples -> {args.out}")
            for reason, count in report["skipped_examples"].items():
                print(f"  skipped {count} worked examples: {reason}")
            return 0
        if args.home is None:
            from .desktop_core import app_data
            home = app_data()
        else:
            home = args.home
        registry = Registry(home)
        try:
            receipt = registry.apply(read_bundle(args.file), auto_live=not args.candidates_only, project=args.project)
        finally:
            registry.close()
        print(f"Live for 14 days: {receipt['live']} lessons, {receipt['examples']} worked examples; "
              f"waiting for review: {receipt['candidates']}; skipped: {receipt['skipped']}")
        return 0
    except (ValueError, OSError, LessonRefused) as exc:
        print(f"learned_week: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
