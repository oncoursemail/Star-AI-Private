"""Opt-in owner-only Discord DMs of externally verified Night School results.

Unlike the interactive Discord bot, this is a one-shot notifier: no model
requests, tools, DMs to guild members, or raw log/project transfers. A host
operator must enable a single, allowlisted user ID and explicitly run --send.
Run --dry-run for local testing without contacting Discord.
"""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
import io
import json
import os
from pathlib import Path
import re
import sqlite3
import sys

from .core import AccessPolicy
from .learning_reports import (
    ApprovedVisual, LearningSnapshot, format_learning_digest,
    read_night_school_report, significant_change,
)

MAX_SNOWFLAKE = 2**64 - 1
UNKNOWN_HOLD_HOURS = 24


@dataclass(frozen=True)
class DeliverySettings:
    owner_id: int
    report_path: Path
    state_path: Path
    cooldown_hours: int = 6
    token: str = ""
    visual_manifest: Path | None = None
    visual_directory: Path | None = None

    @classmethod
    def from_env(cls, values=None, *, sending: bool = False):
        env = os.environ if values is None else values
        if env.get("STAR_DISCORD_LEARNING_DM_OPT_IN") != "1":
            raise PermissionError("Learning DMs require explicit opt-in (STAR_DISCORD_LEARNING_DM_OPT_IN=1)")
        policy = AccessPolicy.from_env(env)
        raw = env.get("STAR_DISCORD_LEARNING_DM_OWNER_ID", "")
        if not re.fullmatch(r"[0-9]{1,20}", raw) or not 0 < int(raw) <= MAX_SNOWFLAKE:
            raise ValueError("Set one valid owner Discord ID")
        owner = int(raw)
        if owner not in policy.owners:
            raise PermissionError("Learning DM target is not an approved STAR owner")
        path = env.get("STAR_DISCORD_LEARNING_REPORT", "")
        state = env.get("STAR_DISCORD_LEARNING_STATE", "")
        if any(not value or not Path(value).is_absolute() for value in (path, state)):
            raise ValueError("Report and delivery state need host-selected absolute paths")
        token = env.get("STAR_DISCORD_BOT_TOKEN", "").strip()
        if sending and (not token or any(c.isspace() for c in token) or len(token) > 200):
            raise ValueError("A configured bot token is needed only for sending")
        raw_cooldown = env.get("STAR_DISCORD_LEARNING_DM_COOLDOWN_HOURS", "6")
        if not raw_cooldown.isdecimal() or not 1 <= int(raw_cooldown) <= 168:
            raise ValueError("Learning DM cooldown must be between 1 and 168 hours")
        manifest = env.get("STAR_DISCORD_LEARNING_VISUAL_MANIFEST", "")
        directory = env.get("STAR_DISCORD_LEARNING_VISUAL_DIRECTORY", "")
        if bool(manifest) != bool(directory):
            raise ValueError("Visual manifest and directory must be configured together")
        if manifest and (not Path(manifest).is_absolute() or not Path(directory).is_absolute()):
            raise ValueError("Visual source paths must be absolute")
        return cls(owner, Path(path), Path(state), int(raw_cooldown), token,
                   Path(manifest) if manifest else None, Path(directory) if directory else None)


def _snapshot_json(snapshot: LearningSnapshot) -> str:
    value = asdict(snapshot)
    value["written"] = snapshot.stamp
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _restore_snapshot(serialized: str) -> LearningSnapshot:
    parsed = json.loads(serialized)
    if not isinstance(parsed, dict) or set(parsed) != set(LearningSnapshot.__dataclass_fields__):
        raise ValueError("Invalid stored snapshot")
    parsed["written"] = datetime.fromisoformat(parsed["written"].replace("Z", "+00:00"))
    return LearningSnapshot(**parsed)


class DeliveryLedger:
    """Durable, conservative at-most-once claims per owner and report version.

    Pending/unknown deliveries are never silently resent after network timeouts
    or a process crash; a human must investigate before clearing that state.
    """

    def __init__(self, path: Path, owner_id: int):
        p = Path(path)
        if not p.is_absolute() or p.is_symlink() or not p.parent.is_dir():
            raise ValueError("Delivery state must be in an existing absolute directory")
        if type(owner_id) is not int or not 1 <= owner_id <= MAX_SNOWFLAKE:
            raise ValueError("Invalid delivery owner ID")
        self.owner = owner_id
        self.db = sqlite3.connect(p, timeout=10, isolation_level=None)
        self.db.execute("""CREATE TABLE IF NOT EXISTS learning_dms (
            owner_id INTEGER NOT NULL, report_stamp TEXT NOT NULL,
            snapshot TEXT NOT NULL, state TEXT NOT NULL,
            claimed_at TEXT NOT NULL, sent_at TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (owner_id, report_stamp)
        )""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS task_dms (
            owner_id INTEGER NOT NULL, event_id TEXT NOT NULL, state TEXT NOT NULL,
            claimed_at TEXT NOT NULL, sent_at TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (owner_id, event_id)
        )""")
        # service alerts (knowledge watchdog restarts): at most once each, outside the digest cooldown
        self.db.execute("""CREATE TABLE IF NOT EXISTS alert_dms (
            owner_id INTEGER NOT NULL, alert_id TEXT NOT NULL, state TEXT NOT NULL,
            claimed_at TEXT NOT NULL, PRIMARY KEY (owner_id, alert_id)
        )""")

    def close(self):
        self.db.close()

    def _last(self):
        row = self.db.execute(
            "SELECT snapshot, sent_at FROM learning_dms WHERE owner_id=? "
            "AND state='sent' ORDER BY sent_at DESC LIMIT 1", (self.owner,),
        ).fetchone()
        if row is None:
            return None, None
        snapshot, sent = row
        return _restore_snapshot(snapshot), datetime.fromisoformat(sent)

    def preview(self, snapshot: LearningSnapshot, *, now=None, cooldown_hours=6):
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Current clock must be timezone aware")
        if type(cooldown_hours) is not int or not 1 <= cooldown_hours <= 168:
            raise ValueError("Invalid cooldown")
        # A pending/unknown delivery blocks new DMs for a day (no retry storm after a network
        # error), but never forever: the bot must not go silent until someone edits SQLite.
        since = (now - timedelta(hours=UNKNOWN_HOLD_HOURS)).astimezone(timezone.utc).isoformat()
        if self.db.execute(
            "SELECT 1 FROM learning_dms WHERE owner_id=? AND state IN ('pending','unknown') "
            "AND claimed_at > ? LIMIT 1",
            (self.owner, since),
        ).fetchone():
            return "awaiting_review", None
        earlier, sent_at = self._last()
        if earlier is not None and not significant_change(earlier, snapshot):
            return "no_new_evidence", earlier
        if sent_at is not None and now < sent_at + timedelta(hours=cooldown_hours):
            return "cooldown", earlier
        hold = self.delivery_hold(now=now, cooldown_hours=cooldown_hours)
        if hold:
            return hold, earlier
        if self.db.execute(
            "SELECT 1 FROM learning_dms WHERE owner_id=? AND report_stamp=? LIMIT 1",
            (self.owner, snapshot.stamp),
        ).fetchone():
            return "already_processed", earlier
        return "ready", earlier

    def delivery_hold(self, *, now, cooldown_hours):
        """One cooldown/uncertain-send budget across aggregate and native task DMs."""
        for table in ("learning_dms", "task_dms"):
            rows = self.db.execute(
                f"SELECT state, claimed_at, sent_at FROM {table} WHERE owner_id=? "
                "AND state IN ('pending','unknown','sent')", (self.owner,)).fetchall()
            for state, claimed, sent in rows:
                if state in {"pending", "unknown"} and now < datetime.fromisoformat(claimed) + timedelta(hours=UNKNOWN_HOLD_HOURS):
                    return "awaiting_review"
                if state == "sent" and now < datetime.fromisoformat(sent) + timedelta(hours=cooldown_hours):
                    return "cooldown"
        return ""

    def reserve_task(self, event_id: str, *, now, cooldown_hours: int):
        if not re.fullmatch(r"[0-9a-f]{64}", event_id):
            raise ValueError("Invalid task event identity")
        if now.tzinfo is None or type(cooldown_hours) is not int or not 1 <= cooldown_hours <= 168:
            raise ValueError("Invalid task delivery clock or cooldown")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            if self.db.execute("SELECT 1 FROM task_dms WHERE owner_id=? AND event_id=?",
                               (self.owner, event_id)).fetchone():
                reason = "already_processed"
            else:
                reason = self.delivery_hold(now=now, cooldown_hours=cooldown_hours) or "ready"
            if reason == "ready":
                self.db.execute("INSERT INTO task_dms(owner_id,event_id,state,claimed_at) VALUES(?,?,'pending',?)",
                                (self.owner, event_id, now.astimezone(timezone.utc).isoformat()))
            self.db.commit()
            return reason
        except BaseException:
            self.db.rollback()
            raise

    def reserve_alert(self, alert_id: str, *, now) -> bool:
        """True once per alert: the caller sends it and calls mark_alert. A crash mid-send is never resent."""
        if not re.fullmatch(r"[0-9a-f]{64}", alert_id) or now.tzinfo is None:
            raise ValueError("Invalid alert identity or clock")
        return self.db.execute("INSERT OR IGNORE INTO alert_dms(owner_id,alert_id,state,claimed_at) VALUES(?,?,'pending',?)",
                               (self.owner, alert_id, now.astimezone(timezone.utc).isoformat())).rowcount == 1

    def mark_alert(self, alert_id: str, state: str):
        if state not in {"sent", "unknown"}:
            raise ValueError("Invalid alert delivery state")
        self.db.execute("UPDATE alert_dms SET state=? WHERE owner_id=? AND alert_id=? AND state='pending'",
                        (state, self.owner, alert_id))

    def mark_task(self, event_id: str, state: str, *, now):
        if state not in {"sent", "unknown"}:
            raise ValueError("Invalid task delivery state")
        updated = self.db.execute("UPDATE task_dms SET state=?, sent_at=? "
                                  "WHERE owner_id=? AND event_id=? AND state='pending'",
                                  (state, now.astimezone(timezone.utc).isoformat() if state == "sent" else "",
                                   self.owner, event_id)).rowcount
        if updated != 1:
            raise ValueError("No matching pending task delivery")

    def reserve(self, snapshot: LearningSnapshot, *, now=None, cooldown_hours=6):
        now = now or datetime.now(timezone.utc)
        self.db.execute("BEGIN IMMEDIATE")
        try:
            reason, earlier = self.preview(snapshot, now=now, cooldown_hours=cooldown_hours)
            if reason == "ready":
                self.db.execute(
                    "INSERT INTO learning_dms(owner_id,report_stamp,snapshot,state,claimed_at)"
                    " VALUES(?,?,?,'pending',?)",
                    (self.owner, snapshot.stamp, _snapshot_json(snapshot),
                     now.astimezone(timezone.utc).isoformat()),
                )
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise
        return reason, earlier

    def mark(self, snapshot: LearningSnapshot, state: str, *, now=None):
        if state not in {"sent", "unknown"}:
            raise ValueError("Unrecognized delivery state")
        now = now or datetime.now(timezone.utc)
        self.db.execute("BEGIN IMMEDIATE")
        try:
            updated = self.db.execute(
                "UPDATE learning_dms SET state=?, sent_at=? "
                "WHERE owner_id=? AND report_stamp=? AND state='pending'",
                (state, now.astimezone(timezone.utc).isoformat() if state == "sent" else "",
                 self.owner, snapshot.stamp),
            ).rowcount
            if updated != 1:
                raise ValueError("No matching pending delivery")
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise


async def send_one_dm(settings: DeliverySettings, text: str, *, visual=None):
    """One explicit REST send, never starts a Gateway listener or runs a model."""
    import discord

    client = discord.Client(intents=discord.Intents.none())
    try:
        await client.login(settings.token)
        target = await client.fetch_user(settings.owner_id)
        options = {"allowed_mentions": discord.AllowedMentions.none()}
        if visual is not None:
            filename, blob = visual
            options["file"] = discord.File(io.BytesIO(blob), filename=filename)
        await target.send(content=text, **options)
    finally:
        await client.close()


async def run_delivery(settings: DeliverySettings, *, dry_run: bool = True, now=None,
                       snapshot: LearningSnapshot | None = None, send=None):
    """``snapshot``/``send`` let the running bot reuse its own connection and report source."""
    now = now or datetime.now(timezone.utc)
    if snapshot is None:
        snapshot = read_night_school_report(settings.report_path)
    ledger = DeliveryLedger(settings.state_path, settings.owner_id)
    try:
        if dry_run:
            reason, previous = ledger.preview(
                snapshot, now=now, cooldown_hours=settings.cooldown_hours)
            result = {"state": reason, "report_stamp": snapshot.stamp, "sent": False}
            if reason == "ready":
                result["preview"] = format_learning_digest(
                    snapshot, previous=previous, now=now)
            return result
        # A stale report must never produce "I just learned" claims.
        reason, previous = ledger.preview(
            snapshot, now=now, cooldown_hours=settings.cooldown_hours)
        if reason != "ready":
            return {"state": reason, "sent": False}
        body = format_learning_digest(snapshot, previous=previous, now=now)
        visual = None
        if settings.visual_manifest is not None:
            approved = ApprovedVisual.load(settings.visual_manifest)
            visual = (approved.filename, approved.verified_bytes(
                report=snapshot, directory=settings.visual_directory))
        reason, previous_after_claim = ledger.reserve(
            snapshot, now=now, cooldown_hours=settings.cooldown_hours)
        if reason != "ready":
            return {"state": reason, "sent": False}
        try:
            if send is None:
                await send_one_dm(settings, body, visual=visual)
            else:
                await send(body, visual)
        except BaseException:
            ledger.mark(snapshot, "unknown", now=now)
            raise
        ledger.mark(snapshot, "sent", now=now)
        return {"state": "sent", "sent": True, "report_stamp": snapshot.stamp}
    finally:
        ledger.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Send one opt-in STAR learning DM")
    flag = parser.add_mutually_exclusive_group(required=True)
    flag.add_argument("--dry-run", action="store_true")
    flag.add_argument("--send", action="store_true")
    args = parser.parse_args(argv)
    try:
        config = DeliverySettings.from_env(sending=args.send)
        result = asyncio.run(run_delivery(config, dry_run=args.dry_run))
        # A report never prints the bot token or configured owner ID.
        print(json.dumps(result, sort_keys=True))
        return 0
    except (ValueError, PermissionError, OSError, sqlite3.Error) as exc:
        print(f"STAR learning DM not delivered: {type(exc).__name__}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"STAR learning DM delivery failed: {type(exc).__name__}; review unknown state", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
