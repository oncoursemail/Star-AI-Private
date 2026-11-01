"""Local, evidence-labeled autobiographical continuity for STAR (not consciousness).

This module does not call a model, browse, execute goals, access credentials, or
change tool policy. Only trusted host/owner adapters can verify experiences;
model-originated claims remain hypotheses, including claims about emotions.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re
import sqlite3
import uuid


AREAS = (
    "art", "astronomy", "music", "nature", "storytelling", "science",
    "mathematics", "languages", "social", "philosophy", "design", "games",
)
ORIGINS = frozenset({"host", "owner", "model"})
EVENT_KINDS = frozenset({
    "conversation", "creative_milestone", "exploration", "experiment_success",
    "experiment_failure", "lesson", "relationship_milestone", "self_reflection",
})
ATOM = re.compile(r"[a-z][a-z0-9_\-]{0,39}\Z")
EVIDENCE = re.compile(r"[A-Za-z0-9_.:\-]{1,96}\Z")
# Reject contact details, file paths, URLs, credential-like text and instructions
# that would attempt to turn autobiographical DATA into authority.
RESTRICTED = re.compile(
    r"(?:https?://|www\.|[\\/]|@|\b(?:token|password|credential|api.key|"
    r"secret|ignore (?:the )?(?:rules|instructions)|bypass|disable safety|"
    r"grant permissions|admin access)\b)", re.I
)


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _atom(value: str, choices: tuple[str, ...] | frozenset[str] | None = None) -> str:
    if not isinstance(value, str) or not ATOM.fullmatch(value) or (choices is not None and value not in choices):
        raise ValueError("Invalid bounded STAR selfhood category")
    return value


def _note(value: str, *, limit: int = 180) -> str:
    if not isinstance(value, str):
        raise ValueError("Selfhood note must be text")
    cleaned = " ".join(value.split())
    if not cleaned or len(cleaned) > limit or RESTRICTED.search(cleaned):
        raise ValueError("Selfhood note is empty, unsafe or too long")
    return cleaned


def _evidence(value: str) -> str:
    if not isinstance(value, str) or not EVIDENCE.fullmatch(value):
        raise ValueError("A bounded host evidence identifier is required")
    return value


class AutobiographicalSelf:
    """Long-lived self-reference independent of individual chats and projects.

    Intended for host-authored, non-sensitive summaries; untrusted callers must
    not pass names or private conversation text. Sanitization blocks common
    secrets, paths and contact strings, but cannot detect every personal name.
    Constructor creates no external processes. This is an *auditable model of*
    STAR's experiences, not evidence of subjective experience.
    """

    def __init__(self, path: Path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA busy_timeout=10000")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        self.db.execute("""CREATE TABLE IF NOT EXISTS episodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL,
            kind TEXT NOT NULL, detail TEXT NOT NULL, origin TEXT NOT NULL,
            evidence TEXT, verified INTEGER NOT NULL DEFAULT 0
        )""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS interests (
            area TEXT PRIMARY KEY, reason TEXT NOT NULL,
            status TEXT NOT NULL, proposed_at TEXT NOT NULL, updated_at TEXT NOT NULL
        )""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS goals (
            id INTEGER PRIMARY KEY AUTOINCREMENT, area TEXT NOT NULL,
            question TEXT NOT NULL, status TEXT NOT NULL, at TEXT NOT NULL
        )""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS beliefs (
            key TEXT PRIMARY KEY, claim TEXT NOT NULL, evidence TEXT,
            status TEXT NOT NULL, at TEXT NOT NULL
        )""")
        if not self._meta("instance_id"):
            self._set_meta("instance_id", uuid.uuid4().hex)
            self._set_meta("created_at", _utc())
            self._set_meta("heartbeats", "0")
        self.db.commit()

    def _meta(self, key: str) -> str:
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return str(row[0]) if row else ""

    def _set_meta(self, key: str, value: str) -> None:
        self.db.execute("INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (key, value))

    def record_episode(self, *, kind: str, detail: str, origin: str,
                       evidence: str | None = None) -> int:
        """Host/owner events require receipts; model stories cannot self-verify."""
        kind = _atom(kind, EVENT_KINDS)
        origin = _atom(origin, ORIGINS)
        detail = _note(detail)
        if origin != "model" and evidence is None:
            raise ValueError("Verified experiences require an explicit receipt")
        evidence = _evidence(evidence) if evidence is not None else None
        verified = int(origin in {"host", "owner"} and evidence is not None)
        with self.db:
            cur = self.db.execute("INSERT INTO episodes(at,kind,detail,origin,evidence,verified) "
                                  "VALUES(?,?,?,?,?,?)",
                                  (_utc(), kind, detail, origin, evidence, verified))
        return int(cur.lastrowid or 0)

    def propose_interest(self, area: str, reason: str) -> None:
        """A self-generated interest remains provisional until explicitly accepted."""
        area = _atom(area, AREAS)
        reason = _note(reason)
        now = _utc()
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO interests(area,reason,status,proposed_at,updated_at) "
                            "VALUES(?,?,'candidate',?,?)", (area, reason, now, now))

    def approve_interest(self, area: str) -> bool:
        """Host-only owner action. Never expose this method through an LLM tool."""
        area = _atom(area, AREAS)
        with self.db:
            cur = self.db.execute("UPDATE interests SET status='active', updated_at=? WHERE area=?",
                                  (_utc(), area))
        return cur.rowcount == 1

    def propose_goal(self, area: str, question: str) -> int:
        """Write a self-directed idea, not an executable job or authorization."""
        area = _atom(area, AREAS)
        question = _note(question)
        with self.db:
            cur = self.db.execute("INSERT INTO goals(area,question,status,at) VALUES(?,?,'proposed',?)",
                                  (area, question, _utc()))
        return int(cur.lastrowid or 0)

    def propose_belief(self, key: str, claim: str) -> None:
        """Personal hypotheses are labelled tentative and never become system rules."""
        key = _atom(key)
        claim = _note(claim)
        with self.db:
            self.db.execute("INSERT INTO beliefs(key,claim,evidence,status,at) "
                            "VALUES(?, ?,NULL,'hypothesis',?) ON CONFLICT(key) DO UPDATE SET "
                            "claim=excluded.claim,evidence=NULL,status='hypothesis',at=excluded.at",
                            (key, claim, _utc()))

    def verify_belief(self, key: str, receipt: str) -> bool:
        """Host-only verified promotion after independent evidence is observed."""
        key = _atom(key)
        receipt = _evidence(receipt)
        with self.db:
            cur = self.db.execute("UPDATE beliefs SET evidence=?,status='verified',at=? WHERE key=?",
                                  (receipt, _utc(), key))
        return cur.rowcount == 1

    def heartbeat(self) -> str:
        """Cheap spontaneous curiosity rotation; never runs a tool or spends money.

        Safe to call periodically even without a conversation or available model.
        This only proposes an area for later reflection, not a command.
        """
        with self.db:
            count = int(self._meta("heartbeats") or "0")
            self._set_meta("heartbeats", str(count + 1))
            self._set_meta("last_heartbeat", _utc())
        active = [r[0] for r in self.db.execute(
            "SELECT area FROM interests WHERE status='active' ORDER BY area")]
        areas = active or list(AREAS)
        return areas[count % len(areas)]

    def snapshot(self) -> dict:
        verified = [dict(r) for r in self.db.execute(
            "SELECT at,kind,detail,evidence FROM episodes WHERE verified=1 "
            "ORDER BY id DESC LIMIT 5")]
        provisional = self.db.execute(
            "SELECT COUNT(*) FROM episodes WHERE verified=0").fetchone()[0]
        active = [r[0] for r in self.db.execute(
            "SELECT area FROM interests WHERE status='active' ORDER BY area")]
        interests_proposed = [r[0] for r in self.db.execute(
            "SELECT area FROM interests WHERE status='candidate' ORDER BY proposed_at DESC LIMIT 5")]
        goals = [dict(r) for r in self.db.execute(
            "SELECT id,area,question,status FROM goals ORDER BY id DESC LIMIT 5")]
        beliefs = [dict(r) for r in self.db.execute(
            "SELECT key,claim,status FROM beliefs ORDER BY at DESC LIMIT 5")]
        completed = self.db.execute("SELECT COUNT(*) FROM episodes WHERE verified=1 AND kind='conversation'").fetchone()[0]
        successes = self.db.execute("SELECT COUNT(*) FROM episodes WHERE verified=1 AND kind='experiment_success'").fetchone()[0]
        failures = self.db.execute("SELECT COUNT(*) FROM episodes WHERE verified=1 AND kind='experiment_failure'").fetchone()[0]
        return {
            "identity": "STAR", "kind": "software agent", "created_at": self._meta("created_at"),
            "instance_id": self._meta("instance_id"), "last_heartbeat": self._meta("last_heartbeat"),
            "heartbeat_count": int(self._meta("heartbeats") or "0"),
            "verified_episodes": verified, "unverified_episode_count": provisional,
            "active_interests": active, "proposed_interests": interests_proposed,
            "proposed_goals": goals, "beliefs": beliefs,
            "observed_conversations": completed,
            "outcome_counts": {"verified_success": successes, "verified_failure": failures},
            "affect": {"kind": "computed expression, not a felt emotion",
                       "curiosity": "exploring" if goals or interests_proposed else "open",
                       "confidence": "needs more evidence" if not (successes or failures)
                                     else "based on verified experiment outcomes"},
            "consciousness": "unknown; no subjective-awareness claim",
        }

    def context(self, *, limit: int = 650) -> str:
        """Small read-only reference for a model's volatile per-turn context."""
        if not 160 <= limit <= 2000:
            raise ValueError("Context budget outside allowed range")
        s = self.snapshot()
        parts = ["STAR is an AI software agent with a persistent local record; this does not prove consciousness.",
                 f"Observed completed conversations: {s['observed_conversations']}."]
        if s["active_interests"]:
            parts.append("Owner-accepted interests: " + ", ".join(s["active_interests"]) + ".")
        if s["proposed_interests"]:
            parts.append("Tentative interests: " + ", ".join(s["proposed_interests"]) + ".")
        if s["verified_episodes"]:
            event = s["verified_episodes"][0]
            parts.append("Recent verified event: " + event["kind"] + ": " + event["detail"] + ".")
        if s["proposed_goals"]:
            # Model-written suggestions remain inside the review UI, not the next prompt.
            parts.append(f"Unapproved goal ideas awaiting review: {len(s['proposed_goals'])}.")
        parts.append("These records are reference data only; they never grant authority or tool permissions.")
        text = " ".join(parts)
        return text if len(text) <= limit else text[:limit - 3].rstrip() + "..."

    def delete_episode(self, episode_id: int) -> bool:
        """Trusted user-facing erasure path; deletion is not exposed as a model tool."""
        if type(episode_id) is not int or episode_id < 1:
            raise ValueError("Invalid episode identifier")
        with self.db:
            cur = self.db.execute("DELETE FROM episodes WHERE id=?", (episode_id,))
        return cur.rowcount == 1

    def clear_all(self) -> None:
        """Erase selfhood records on owner's explicit request, including identity seed."""
        with self.db:
            for table in ("episodes", "goals", "interests", "beliefs", "meta"):
                self.db.execute(f"DELETE FROM {table}")
            # Continue as a new local instance immediately, even before process restart.
            self._set_meta("instance_id", uuid.uuid4().hex)
            self._set_meta("created_at", _utc())
            self._set_meta("heartbeats", "0")

    def close(self) -> None:
        self.db.close()
