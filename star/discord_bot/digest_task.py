"""Night School digest DMs from inside the running bot (owner opt-in).

The bot checks STAR's Night School report on a timer and DMs the owner only when the
verified counters really changed (see learning_reports.significant_change), with the
durable at-most-once ledger and cooldown from learning_sender. The report comes from a
local file or, read-only, over the owner's existing ssh key login to the brain server.
Only fixed counters are parsed; model-written lesson text never reaches Discord.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import logging
import os
from pathlib import Path
import re
import shutil
import subprocess

from .core import AccessPolicy
from .learning_reports import (LearningSnapshot, MAX_REPORT_BYTES, format_learning_digest,
                               parse_night_school_report, read_night_school_report)
from .learning_sender import DeliveryLedger, DeliverySettings, MAX_SNOWFLAKE, run_delivery

_LOG = logging.getLogger(__name__)
# Fixed, read-only remote command; the target login comes from the owner's local settings.
REMOTE_REPORT_COMMAND = "lxc exec starai -- cat /opt/star/learning/report/latest.md"
# The knowledge service watchdog's state (server/knowledge/starkb/watchdog.py), same login, also read-only.
REMOTE_WATCHDOG_COMMAND = "lxc exec starai -- cat /opt/star/knowledge/data/watchdog.json"
MAX_WATCHDOG_BYTES = 16_000
WATCHDOG_ALERT_HOURS = 24        # restarts older than this are history, not news
_SSH_TARGET = re.compile(r"^[A-Za-z0-9._-]{1,64}@[A-Za-z0-9.:_-]{1,253}$")


@dataclass(frozen=True)
class DigestConfig:
    enabled: bool
    owner_id: int = 0
    report_path: Path | None = None
    ssh_target: str = ""
    state_path: Path | None = None
    cooldown_hours: int = 6
    check_minutes: int = 30
    evidence_directory: Path | None = None
    evidence_reviews: Path | None = None

    @classmethod
    def from_env(cls, env=None, *, policy: AccessPolicy | None = None) -> "DigestConfig":
        source = os.environ if env is None else env
        flag = str(source.get("STAR_DISCORD_LEARNING_DM_OPT_IN", "0")).strip() or "0"
        if flag not in {"0", "1"}:
            raise ValueError("STAR_DISCORD_LEARNING_DM_OPT_IN must be 0 or 1")
        if flag == "0":
            return cls(False)
        policy = policy or AccessPolicy.from_env(source)
        raw = str(source.get("STAR_DISCORD_LEARNING_DM_OWNER_ID", "")).strip()
        if raw:
            if not re.fullmatch(r"[0-9]{1,20}", raw) or not 0 < int(raw) <= MAX_SNOWFLAKE:
                raise ValueError("STAR_DISCORD_LEARNING_DM_OWNER_ID must be a Discord user ID")
            owner = int(raw)
        elif len(policy.owners) == 1:
            owner = next(iter(policy.owners))
        else:
            raise ValueError("Several owners are configured: set STAR_DISCORD_LEARNING_DM_OWNER_ID")
        if owner not in policy.owners:
            raise PermissionError("Learning DM target is not an approved STAR owner")
        path = str(source.get("STAR_DISCORD_LEARNING_REPORT", "")).strip()
        target = str(source.get("STAR_DISCORD_LEARNING_REPORT_SSH", "")).strip()
        evidence = str(source.get("STAR_DISCORD_EVIDENCE_DIRECTORY", "")).strip()
        reviews = str(source.get("STAR_DISCORD_EVIDENCE_REVIEWS", "")).strip()
        if (path and target) or not (path or target or evidence):
            raise ValueError("Set exactly one Night School report source: "
                             "STAR_DISCORD_LEARNING_REPORT (file) or STAR_DISCORD_LEARNING_REPORT_SSH")
        from .native_evidence import trusted_path
        if evidence:
            trusted_path(Path(evidence))
        if reviews:
            trusted_path(Path(reviews))
            if not evidence or Path(reviews).resolve().is_relative_to(Path(evidence).resolve()):
                raise ValueError("Native reviews need a separate operator-only directory")
        if path and not Path(path).is_absolute():
            raise ValueError("STAR_DISCORD_LEARNING_REPORT must be an absolute path")
        if target and not _SSH_TARGET.fullmatch(target):
            raise ValueError("STAR_DISCORD_LEARNING_REPORT_SSH must look like user@host")
        state = str(source.get("STAR_DISCORD_LEARNING_STATE", "")).strip()
        state_path = Path(state) if state else Path.home() / ".star" / "discord-state" / "learning_dms.sqlite3"
        if not state_path.is_absolute():
            raise ValueError("STAR_DISCORD_LEARNING_STATE must be an absolute path")
        cooldown = str(source.get("STAR_DISCORD_LEARNING_DM_COOLDOWN_HOURS", "6")).strip() or "6"
        minutes = str(source.get("STAR_DISCORD_LEARNING_CHECK_MINUTES", "30")).strip() or "30"
        if not cooldown.isdecimal() or not 1 <= int(cooldown) <= 168:
            raise ValueError("Learning DM cooldown must be between 1 and 168 hours")
        if not minutes.isdecimal() or not 10 <= int(minutes) <= 1440:
            raise ValueError("STAR_DISCORD_LEARNING_CHECK_MINUTES must be between 10 and 1440")
        return cls(True, owner, Path(path) if path else None, target, state_path,
                   int(cooldown), int(minutes), Path(evidence) if evidence else None,
                   Path(reviews) if reviews else None)

    def delivery_settings(self) -> DeliverySettings:
        # report_path is unused when the snapshot is supplied (ssh source).
        return DeliverySettings(self.owner_id, self.report_path or self.state_path, self.state_path,
                                self.cooldown_hours)

    def describe(self) -> str:
        if not self.enabled:
            return "off (set STAR_DISCORD_LEARNING_DM_OPT_IN=1 to opt in)"
        source = "local file" if self.report_path else "brain server over ssh" if self.ssh_target else "native task events"
        if self.evidence_directory is not None and (self.report_path or self.ssh_target):
            source += " + native task events"
        return f"on: checks every {self.check_minutes} min ({source}), at most one DM per {self.cooldown_hours} h"


def _ssh_fetch(target: str, runner=subprocess.run) -> str:
    ssh = shutil.which("ssh")
    if not ssh:
        raise ValueError("ssh is not installed on this PC")
    result = runner([ssh, "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", target, REMOTE_REPORT_COMMAND],
                    capture_output=True, timeout=40, stdin=subprocess.DEVNULL, check=False)
    if result.returncode != 0:
        raise ValueError("Could not read the Night School report from the brain server")
    data = result.stdout[:MAX_REPORT_BYTES + 1]
    if len(data) > MAX_REPORT_BYTES:
        raise ValueError("Night School report is unexpectedly large")
    return data.decode("utf-8", errors="replace")


def watchdog_alerts(state: object, *, now: datetime) -> list[tuple[str, str]]:
    """(alert id, DM text) for each knowledge-service restart in the last WATCHDOG_ALERT_HOURS."""
    restarts = state.get("restarts") if isinstance(state, dict) else None
    alerts = []
    for row in restarts if isinstance(restarts, list) else []:
        if not isinstance(row, dict) or not isinstance(row.get("at"), str):
            continue
        try:
            at = datetime.strptime(row["at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if not now - timedelta(hours=WATCHDOG_ALERT_HOURS) <= at <= now + timedelta(minutes=5):
            continue
        reason = re.sub(r"[^A-Za-z0-9 :._-]", "", str(row.get("reason", "")))[:80] or "unknown"
        text = (f"**STAR Knowledge was restarted by its watchdog** at {row['at']} after {int(row.get('failures') or 0)} "
                f"failed searches in a row ({reason}).")
        if row.get("done") is not True:
            text += " The restart command FAILED: the docs search may still be down."
        alerts.append((sha256(("knowledge-watchdog:" + row["at"]).encode()).hexdigest(), text))
    return alerts


async def send_watchdog_alerts(config: DigestConfig, send, *, runner=subprocess.run, now=None) -> int:
    """DM each new knowledge-service restart once (own ledger table, outside the digest cooldown)."""
    state_path = config.state_path
    if not config.ssh_target or state_path is None:
        return 0
    now = now or datetime.now(timezone.utc)
    ssh = shutil.which("ssh")
    if not ssh:
        return 0
    result = await asyncio.to_thread(
        runner, [ssh, "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", config.ssh_target, REMOTE_WATCHDOG_COMMAND],
        capture_output=True, timeout=40, stdin=subprocess.DEVNULL, check=False)
    if result.returncode != 0 or len(result.stdout) > MAX_WATCHDOG_BYTES:
        return 0          # no watchdog installed yet, or the server is unreachable: the digest path reports that
    try:
        alerts = watchdog_alerts(json.loads(result.stdout.decode("utf-8", errors="replace")), now=now)
    except ValueError:
        return 0
    state_path.parent.mkdir(parents=True, exist_ok=True)
    ledger = DeliveryLedger(state_path, config.owner_id)
    sent = 0
    try:
        for alert_id, text in alerts:
            if not ledger.reserve_alert(alert_id, now=now):
                continue
            try:
                await send(text, None)
            except BaseException:
                ledger.mark_alert(alert_id, "unknown")
                raise
            ledger.mark_alert(alert_id, "sent")
            sent += 1
    finally:
        ledger.close()
    return sent


async def load_snapshot(config: DigestConfig, *, runner=subprocess.run) -> LearningSnapshot:
    if config.report_path is not None:
        return await asyncio.to_thread(read_night_school_report, config.report_path)
    text = await asyncio.to_thread(_ssh_fetch, config.ssh_target, runner)
    return parse_night_school_report(text)


async def current_digest(config: DigestConfig, *, runner=subprocess.run, now=None) -> str:
    """On-demand /digest text; changes no delivery state."""
    if not config.report_path and not config.ssh_target:
        return "Native task notifications are enabled. Use /star lab for the latest producer receipt."
    snapshot = await load_snapshot(config, runner=runner)
    return format_learning_digest(snapshot, now=now or datetime.now(timezone.utc))


async def check_and_send(config: DigestConfig, send, *, runner=subprocess.run, now=None) -> dict:
    """One timer tick: DM only on real, fresh, non-duplicate progress."""
    if not config.enabled:
        return {"state": "disabled", "sent": False}
    try:
        alerts = await send_watchdog_alerts(config, send, runner=runner, now=now)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        _LOG.warning("Knowledge watchdog check failed: %s", type(exc).__name__)
        alerts = 0
    if alerts:
        _LOG.info("Knowledge watchdog: %d restart alert(s) sent", alerts)
    if config.evidence_directory is not None:
        from .task_events import check_task_events
        result = await check_task_events(config, send, now=now)
        if result["sent"] or not (config.report_path or config.ssh_target):
            return result
    config.state_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot = await load_snapshot(config, runner=runner)
    return await run_delivery(config.delivery_settings(), dry_run=False, now=now,
                              snapshot=snapshot, send=send)


def ledger_state(config: DigestConfig) -> str:
    if not config.enabled or config.state_path is None or not config.state_path.is_file():
        return "no digest sent yet"
    ledger = DeliveryLedger(config.state_path, config.owner_id)
    try:
        row = ledger.db.execute(
            "SELECT state, report_stamp, claimed_at, 'digest' FROM learning_dms WHERE owner_id=? "
            "UNION ALL SELECT state, event_id, claimed_at, 'task' FROM task_dms WHERE owner_id=? "
            "ORDER BY claimed_at DESC LIMIT 1", (config.owner_id, config.owner_id)).fetchone()
    finally:
        ledger.close()
    if row and row[3] == "task":
        return f"last native task: {row[0]} (event {row[1][:12]})"
    return f"last digest: {row[0]} (report {row[1]})" if row else "no digest sent yet"
