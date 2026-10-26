"""Transactional, gate-checked promotion of bounded STAR self-improvements.

Only built-in skill-pack switches, existing model-role routing choices, and project
lessons are mutable. A promotion never edits a file or broadens a permission.
Lessons and the audit live in the same SQLite database so both commit together.
"""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3

from . import eval_gate
from .knowledge import KnowledgeStore, LESSON_KINDS, _project
from .lessons import INFERRED, check_lesson_text, subject_key

LESSON_LIFETIME = timedelta(days=14)
_ROUTABLE = frozenset({"roblox", "reasoning", "research", "agent"})
_ROLES = frozenset({"roblox", "reasoning"})
_REFERENCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/#-]{0,199}$")


def _json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def change_digest(change: dict) -> str:
    """Fingerprint the exact proposal, including all its fields and values."""
    return hashlib.sha256(_json(change).encode("utf-8")).hexdigest()


def _stamp(value=None) -> str:
    if value is None:
        value = datetime.now(timezone.utc)
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Time must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat()


def _home(home) -> Path:
    if home is None:
        from .desktop_core import app_data
        home = app_data()
    return Path(home)


def _readonly_setting(home, key: str):
    """Existing promotion overrides, without creating data files during a turn."""
    db_file = _home(home) / "knowledge" / "knowledge.sqlite3"
    if not db_file.is_file():
        return None
    try:
        with closing(sqlite3.connect(f"file:{db_file.as_posix()}?mode=ro", uri=True, timeout=1)) as db:
            row = db.execute("SELECT value_json FROM promoter_settings WHERE key=?", (key,)).fetchone()
            return json.loads(row[0]) if row is not None else None
    except (sqlite3.Error, OSError, ValueError):
        return None  # missing table, locked DB or corrupt override: retain built-in behavior


def enabled_skill_packs(home, defaults) -> frozenset[str]:
    """Apply persisted switches to the existing enabled names; never add unknown packs."""
    from .skill_packs import available
    names = set(defaults)
    known = {pack.name for pack in available()}
    db_file = _home(home) / "knowledge" / "knowledge.sqlite3"
    if not db_file.is_file():
        return frozenset(names & known)
    try:
        with closing(sqlite3.connect(f"file:{db_file.as_posix()}?mode=ro", uri=True, timeout=1)) as db:
            for key, value in db.execute(
                    "SELECT key,value_json FROM promoter_settings WHERE key LIKE 'skill_pack:%'"):
                name = key.removeprefix("skill_pack:")
                if name not in known:
                    continue
                enabled = json.loads(value)
                if type(enabled) is bool:
                    (names.add if enabled else names.discard)(name)
    except (sqlite3.Error, OSError, ValueError):
        return frozenset(set(defaults) & known)
    return frozenset(names & known)


def routing_role(home, profile: str) -> str | None:
    """Only safe configured-model aliases are returned, never a model ID or endpoint."""
    if profile not in _ROUTABLE:
        return None
    role = _readonly_setting(home, f"routing_rule:{profile}")
    return role if isinstance(role, str) and role in _ROLES else None


def expire_due(home, now=None) -> list[int]:
    """Retire due self-derived lessons before a turn recalls trusted notes.

    No new SQLite file, migration, or write transaction is opened on the usual
    (no promotion / nothing due) path.
    """
    stamp = _stamp(now)
    db_file = _home(home) / "knowledge" / "knowledge.sqlite3"
    if not db_file.is_file():
        return []
    try:
        with closing(sqlite3.connect(f"file:{db_file.as_posix()}?mode=ro", uri=True, timeout=1)) as db:
            due = db.execute(
                """SELECT 1 FROM promoter_audit a
                   JOIN promoter_changes c ON c.id=a.promotion_id
                   WHERE c.state='applied' AND a.kept_at IS NULL
                   AND a.expires_at IS NOT NULL AND a.expires_at<=? LIMIT 1""", (stamp,)).fetchone()
    except (sqlite3.Error, OSError):
        return []  # pre-promotion installations have no tables yet
    if due is None:
        return []
    with Promoter(home) as store:
        return store.expire(stamp)


class PromotionConflict(RuntimeError):
    """A newer or owner-edited target cannot safely be restored by an expiry."""


class Promoter:
    """One writer of audited, reversible promotion state.

    Evidence consists of a short reference and baseline/candidate eval-result
    dictionaries. The candidate run must carry run.change_sha256 for this
    proposal; a caller-supplied verdict flag is ignored. The verdict is
    recomputed by star.eval_gate, then stored with the pending proposal.
    """

    def __init__(self, home: Path | None = None):
        self.home = _home(home)
        self.knowledge = KnowledgeStore(self.home / "knowledge")
        self.db = self.knowledge.db
        self.db.execute("""CREATE TABLE IF NOT EXISTS promoter_changes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            change_json TEXT NOT NULL, change_sha256 TEXT NOT NULL,
            evidence_ref TEXT NOT NULL, gate_verdict TEXT NOT NULL,
            gate_json TEXT NOT NULL, created_at TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'pending'
        )""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS promoter_settings (
            key TEXT PRIMARY KEY, value_json TEXT NOT NULL
        )""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS promoter_audit (
            promotion_id INTEGER PRIMARY KEY REFERENCES promoter_changes(id),
            target TEXT NOT NULL, before_json TEXT NOT NULL,
            after_json TEXT NOT NULL, applied_at TEXT NOT NULL,
            evidence_ref TEXT NOT NULL, expires_at TEXT,
            kept_at TEXT, undone_at TEXT, undo_reason TEXT
        )""")
        self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_promoter_expiry ON promoter_audit(expires_at)")
        self.db.commit()

    def close(self) -> None:
        self.knowledge.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def propose(self, change: dict, evidence: dict) -> int:
        if not isinstance(change, dict) or not isinstance(change.get("type"), str):
            raise ValueError("A structured change is required")
        if not isinstance(evidence, dict):
            raise ValueError("Evaluation evidence is required")
        reference = evidence.get("reference")
        if (not isinstance(reference, str) or not _REFERENCE.fullmatch(reference)
                or ".." in reference or "://" in reference):
            raise ValueError("Use a short, non-sensitive evidence reference")
        encoded = _json(change)
        if len(encoded) > 4096:
            raise ValueError("Change is too large")
        digest = change_digest(change)
        gate_data: dict = {}
        gate_verdict = "missing"
        baseline, candidate = evidence.get("baseline"), evidence.get("candidate")
        if (isinstance(baseline, dict) and isinstance(candidate, dict)
                and isinstance(baseline.get("suite"), dict)
                and isinstance(candidate.get("suite"), dict)
                and isinstance(baseline.get("tasks"), dict)
                and isinstance(candidate.get("tasks"), dict)
                and isinstance(candidate.get("run"), dict)
                and candidate["run"].get("change_sha256") == digest):
            verdict = eval_gate.evaluate_change(baseline, candidate)
            gate_data = {**verdict.to_dict(), "change_sha256": digest}
            gate_verdict = {eval_gate.ALLOWED: "allowed", eval_gate.BLOCKED: "blocked",
                            eval_gate.UNUSABLE: "unusable", eval_gate.INCOMPLETE: "incomplete"}[verdict.code]
        row = self.db.execute(
            """INSERT INTO promoter_changes(change_json,change_sha256,evidence_ref,
                   gate_verdict,gate_json,created_at,state)
               VALUES(?,?,?,?,?,?,'pending')""",
            (encoded, digest, reference, gate_verdict, _json(gate_data), _stamp()))
        self.db.commit()
        return int(row.lastrowid)

    @staticmethod
    def _target(change: dict) -> str:
        """Fixed allow-list: no paths, executable code, permissions or settings IDs."""
        kind = change.get("type")
        if kind == "skill_pack":
            if set(change) != {"type", "name", "enabled"} or type(change["enabled"]) is not bool:
                raise PermissionError("Only a named built-in skill-pack switch is allowed")
            from .skill_packs import available
            if change["name"] not in {pack.name for pack in available()}:
                raise PermissionError("Unknown skill pack")
            return "skill_pack:" + change["name"]
        if kind == "routing_rule":
            if (set(change) != {"type", "profile", "role"}
                    or change["profile"] not in _ROUTABLE
                    or change["role"] not in (*_ROLES, None)):
                raise PermissionError("Only an existing model-role choice is allowed")
            return "routing_rule:" + change["profile"]
        if kind == "lesson":
            if change.get("action") == "add":
                if set(change) != {"type", "action", "project", "kind", "text"}:
                    raise PermissionError("Unexpected lesson fields")
                _project(change["project"])
                if change["kind"] not in LESSON_KINDS:
                    raise PermissionError("Only a lesson kind is allowed")
                check_lesson_text(change["text"])
                return "lesson:new:" + change["project"]
            if change.get("action") == "retire":
                if set(change) != {"type", "action", "project", "lesson_id"}:
                    raise PermissionError("Unexpected lesson fields")
                _project(change["project"])
                if type(change["lesson_id"]) is not int or change["lesson_id"] < 1:
                    raise ValueError("Invalid lesson ID")
                return f"lesson:{change['project']}:{change['lesson_id']}"
        raise PermissionError("Target is outside the promotion allow-list")

    def _setting(self, key: str) -> dict:
        row = self.db.execute("SELECT value_json FROM promoter_settings WHERE key=?", (key,)).fetchone()
        return {"present": True, "value": json.loads(row[0])} if row else {"present": False}

    def _lesson(self, project: str, lesson_id: int) -> dict:
        row = self.db.execute(
            "SELECT * FROM notes WHERE project=? AND id=?", (project, lesson_id)).fetchone()
        return {"present": True, "row": dict(row)} if row else {"present": False}

    def _write_setting(self, key: str, value) -> None:
        if value is None:
            self.db.execute("DELETE FROM promoter_settings WHERE key=?", (key,))
        else:
            self.db.execute(
                "INSERT INTO promoter_settings(key,value_json) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json", (key, _json(value)))

    def _write_lesson(self, change: dict, promotion_id: int, stamp: str):
        project = change["project"]
        if change["action"] == "add":
            duplicate = self.db.execute(
                "SELECT 1 FROM notes WHERE project=? AND lower(text)=lower(?) AND status='accepted'",
                (project, change["text"])).fetchone()
            if duplicate:
                raise ValueError("An accepted lesson already says this")
            created = self.db.execute(
                """INSERT INTO notes(project,kind,text,source,revision,reviewed,created,
                                     status,source_type,updated,subject,evidence)
                   VALUES(?,?,?,?,?,1,?,'accepted','summary',?,?,?)""",
                (project, change["kind"], check_lesson_text(change["text"]),
                 f"promoter:{promotion_id}", "gate-allowed", stamp, stamp,
                 subject_key(change["text"]), f"promotion:{promotion_id}"))
            return int(created.lastrowid)
        row = self.db.execute(
            "SELECT source_type,status,reviewed FROM notes WHERE project=? AND id=?",
            (project, change["lesson_id"])).fetchone()
        if row is None or row["status"] != "accepted" or row["reviewed"] != 1:
            raise ValueError("Only an accepted project lesson can be retired")
        if row["source_type"] not in INFERRED:
            raise PermissionError("Gate decisions cannot retire owner-authored lessons")
        self.db.execute(
            "UPDATE notes SET reviewed=0,status='superseded',updated=? WHERE project=? AND id=?",
            (stamp, project, change["lesson_id"]))
        return change["lesson_id"]

    def _after_change(self) -> None:
        """Test seam: an interruption here must roll back the change itself."""

    def apply(self, promotion_id: int) -> dict:
        if type(promotion_id) is not int or promotion_id < 1:
            raise ValueError("Invalid promotion ID")
        try:
            self.db.execute("BEGIN IMMEDIATE")
            row = self.db.execute("SELECT * FROM promoter_changes WHERE id=?", (promotion_id,)).fetchone()
            if row is None or row["state"] != "pending":
                raise ValueError("Only a pending promotion can be applied")
            change = json.loads(row["change_json"])
            if (row["gate_verdict"] != "allowed" or row["change_sha256"] != change_digest(change)
                    or not json.loads(row["gate_json"]).get("allowed")
                    or json.loads(row["gate_json"]).get("exit_code") != eval_gate.ALLOWED
                    or json.loads(row["gate_json"]).get("change_sha256") != change_digest(change)):
                raise PermissionError("The exact change needs an allowed star.eval_gate verdict")
            target = self._target(change)
            stamp = _stamp()
            if change["type"] == "lesson":
                if change["action"] == "add":
                    before = {"present": False}
                    lesson_id = self._write_lesson(change, promotion_id, stamp)
                    target = f"lesson:{change['project']}:{lesson_id}"
                else:
                    before = self._lesson(change["project"], change["lesson_id"])
                    self._write_lesson(change, promotion_id, stamp)
                    lesson_id = change["lesson_id"]
                after = self._lesson(change["project"], lesson_id)
            else:
                before = self._setting(target)
                self._write_setting(target, change["enabled"] if change["type"] == "skill_pack"
                                    else change["role"])
                after = self._setting(target)
            self._after_change()
            expires = (_stamp(datetime.fromisoformat(stamp) + LESSON_LIFETIME)
                       if change["type"] == "lesson" and change["action"] == "add" else None)
            self.db.execute(
                """INSERT INTO promoter_audit(promotion_id,target,before_json,after_json,
                                              applied_at,evidence_ref,expires_at)
                   VALUES(?,?,?,?,?,?,?)""",
                (promotion_id, target, _json(before), _json(after), stamp, row["evidence_ref"], expires))
            self.db.execute("UPDATE promoter_changes SET state='applied' WHERE id=?", (promotion_id,))
            self.db.commit()
            return self.record(promotion_id)
        except BaseException:
            if self.db.in_transaction:
                self.db.rollback()
            raise

    def record(self, promotion_id: int) -> dict:
        row = self.db.execute(
            """SELECT c.*,a.target,a.before_json,a.after_json,a.applied_at,a.expires_at,
                      a.kept_at,a.undone_at,a.undo_reason
               FROM promoter_changes c LEFT JOIN promoter_audit a ON a.promotion_id=c.id
               WHERE c.id=?""", (promotion_id,)).fetchone()
        if row is None:
            raise ValueError("Unknown promotion")
        result = dict(row)
        result["change"] = json.loads(result.pop("change_json"))
        result["gate"] = json.loads(result.pop("gate_json"))
        for key in ("before_json", "after_json"):
            result[key.removesuffix("_json")] = json.loads(result.pop(key)) if result[key] else None
        return result

    def _restore(self, target: str, before: dict) -> None:
        if not target.startswith("lesson:"):
            if before["present"]:
                self.db.execute(
                    "INSERT INTO promoter_settings(key,value_json) VALUES(?,?) "
                    "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
                    (target, _json(before["value"])))
            else:
                self.db.execute("DELETE FROM promoter_settings WHERE key=?", (target,))
            return
        if not before["present"]:
            lesson_id = int(target.rsplit(":", 1)[1])
            self.db.execute("DELETE FROM lesson_use WHERE note_id=?", (lesson_id,))
            self.db.execute("DELETE FROM notes WHERE id=?", (lesson_id,))
            return
        fields = before["row"]
        assignments = ", ".join(f"{field}=?" for field in fields if field != "id")
        values = [value for field, value in fields.items() if field != "id"]
        self.db.execute(f"UPDATE notes SET {assignments} WHERE id=?", (*values, fields["id"]))

    def _undo_locked(self, promotion_id: int, stamp: str, reason: str) -> bool:
        row = self.db.execute(
            """SELECT c.state,a.target,a.before_json,a.after_json
               FROM promoter_changes c JOIN promoter_audit a ON a.promotion_id=c.id
               WHERE c.id=?""", (promotion_id,)).fetchone()
        if row is None:
            pending = self.db.execute(
                "SELECT 1 FROM promoter_changes WHERE id=?", (promotion_id,)).fetchone()
            raise ValueError("Promotion was not applied" if pending else "Unknown promotion")
        if row["state"] in ("undone", "expired"):
            return False
        if row["state"] != "applied":
            raise ValueError("Promotion is not active")
        latest = self.db.execute(
            """SELECT a.promotion_id FROM promoter_audit a
               JOIN promoter_changes c ON c.id=a.promotion_id
               WHERE a.target=? AND c.state='applied'
               ORDER BY a.promotion_id DESC LIMIT 1""", (row["target"],)).fetchone()
        if latest[0] != promotion_id:
            raise PromotionConflict("A newer promotion must be undone first")
        target = row["target"]
        if target.startswith("lesson:"):
            _, project, lesson_id = target.split(":", 2)
            current = self._lesson(project, int(lesson_id))
        else:
            current = self._setting(target)
        if current != json.loads(row["after_json"]):
            raise PromotionConflict("Target changed since promotion; refusing to overwrite it")
        self._restore(target, json.loads(row["before_json"]))
        self.db.execute("UPDATE promoter_changes SET state=? WHERE id=?", (reason, promotion_id))
        self.db.execute(
            "UPDATE promoter_audit SET undone_at=?,undo_reason=? WHERE promotion_id=?",
            (stamp, reason, promotion_id))
        return True

    def undo(self, promotion_id: int) -> bool:
        try:
            self.db.execute("BEGIN IMMEDIATE")
            changed = self._undo_locked(promotion_id, _stamp(), "undone")
            self.db.commit()
            return changed
        except BaseException:
            if self.db.in_transaction:
                self.db.rollback()
            raise

    def keep(self, promotion_id: int, *, human_approved: bool = False) -> bool:
        if human_approved is not True:
            raise PermissionError("Only the owner can keep a promoted lesson")
        try:
            self.db.execute("BEGIN IMMEDIATE")
            row = self.db.execute(
                """SELECT c.state,a.target,a.expires_at,a.kept_at FROM promoter_changes c
                   JOIN promoter_audit a ON a.promotion_id=c.id WHERE c.id=?""",
                (promotion_id,)).fetchone()
            if row is None or row["state"] != "applied" or not row["target"].startswith("lesson:"):
                raise ValueError("Only a live promoted lesson can be kept")
            if row["kept_at"] is not None:
                self.db.commit()
                return False
            if row["expires_at"] is None or row["expires_at"] <= _stamp():
                raise ValueError("This lesson is not eligible to be kept")
            self.db.execute("UPDATE promoter_audit SET kept_at=?,expires_at=NULL WHERE promotion_id=?",
                            (_stamp(), promotion_id))
            self.db.commit()
            return True
        except BaseException:
            if self.db.in_transaction:
                self.db.rollback()
            raise

    def expire(self, now=None) -> list[int]:
        stamp = _stamp(now)
        expired = []
        try:
            self.db.execute("BEGIN IMMEDIATE")
            rows = self.db.execute(
                """SELECT a.promotion_id FROM promoter_audit a
                   JOIN promoter_changes c ON c.id=a.promotion_id
                   WHERE c.state='applied' AND a.kept_at IS NULL
                   AND a.expires_at IS NOT NULL AND a.expires_at<=?
                   ORDER BY a.promotion_id DESC""", (stamp,)).fetchall()
            for row in rows:
                try:
                    if self._undo_locked(int(row[0]), stamp, "expired"):
                        expired.append(int(row[0]))
                except PromotionConflict:
                    # A changed lesson belongs to its current owner state. Never
                    # overwrite it or abort unrelated turn-start expiry checks.
                    continue
            self.db.commit()
            return expired
        except BaseException:
            if self.db.in_transaction:
                self.db.rollback()
            raise


def propose(change: dict, evidence: dict, *, home=None) -> int:
    with Promoter(home) as store:
        return store.propose(change, evidence)


def apply(promotion_id: int, *, home=None) -> dict:
    with Promoter(home) as store:
        record = store.apply(promotion_id)
    from . import emotion        # a night school promotion that went live is something to be pleased about
    emotion.on_event("promotion", home=home, only_if_enabled=True, detail=f"promotion {promotion_id}")
    return record


def undo(promotion_id: int, *, home=None) -> bool:
    with Promoter(home) as store:
        return store.undo(promotion_id)


def expire(now=None, *, home=None) -> list[int]:
    with Promoter(home) as store:
        return store.expire(now)


def keep(promotion_id: int, *, home=None, human_approved: bool = False) -> bool:
    with Promoter(home) as store:
        return store.keep(promotion_id, human_approved=human_approved)
