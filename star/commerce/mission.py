"""STAR Business Mission Control: local, bounded portfolio and QA work queue.

All writes go into STAR's *private* app-data SQLite database. No background
process, third-party connection, model, browser, purchase, or marketplace
publication can be started from this module. Work is a deterministic
evidence/checklist preflight only, NOT a copyright or aesthetic certification.
"""
from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timezone
from hashlib import sha256
import json
import re
import sqlite3
import uuid
from typing import Any, Callable, Mapping

ACTIONS = frozenset({
    "commerceCreateBusiness", "commercePauseBusiness", "commerceAssignBusiness",
    "commerceQueuePreflight", "commerceRunPreflight", "commerceCancelPreflight",
})
CHANNELS = frozenset({"etsy", "shopify", "fiverr", "payhip", "gumroad", "printify"})
MAX_BUSINESSES = 100
MAX_JOBS = 3000
MAX_BATCH = 20
_ID = re.compile(r"^[0-9a-f]{32}$")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _time() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _require_id(value: Any, label: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise ValueError(f"Invalid {label}")
    return value


def _text(value: Any, label: str, maximum: int) -> str:
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= maximum:
        raise ValueError(f"{label} must contain 1–{maximum} characters")
    cleaned = value.strip()
    if _CONTROL.search(cleaned):
        raise ValueError(f"{label} contains control characters")
    return cleaned


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Idempotent additive migration. Existing commerce ideas are preserved."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS commerce_businesses (
          id TEXT PRIMARY KEY,
          project TEXT NOT NULL,
          name TEXT NOT NULL,
          niche TEXT NOT NULL,
          channel TEXT NOT NULL,
          paused INTEGER NOT NULL DEFAULT 1 CHECK(paused IN (0,1)),
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS commerce_business_name
        ON commerce_businesses(project, lower(name))
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS commerce_preflight_jobs (
          id TEXT PRIMARY KEY,
          project TEXT NOT NULL,
          business_id TEXT NOT NULL,
          idea_id TEXT NOT NULL,
          fingerprint TEXT NOT NULL,
          status TEXT NOT NULL CHECK(status IN (
            'queued','review_ready','needs_evidence','stale','cancelled'
          )),
          blockers_json TEXT NOT NULL DEFAULT '[]',
          created_at TEXT NOT NULL,
          checked_at TEXT
        )
    """)
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS commerce_preflight_dedupe
        ON commerce_preflight_jobs(project, idea_id, fingerprint)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS commerce_preflight_queue
        ON commerce_preflight_jobs(project,status,created_at)
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS commerce_operation_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          project TEXT NOT NULL,
          business_id TEXT,
          job_id TEXT,
          action TEXT NOT NULL,
          at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS commerce_operation_project
        ON commerce_operation_events(project, id DESC)
    """)
    # PR #477 has already created commerce_ideas in this same connection.
    # SQLite ALTER TABLE preserves older records; a null business means
    # "not assigned", not a hidden or invented merchant store.
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(commerce_ideas)")}
    if "business_id" not in cols:
        conn.execute("ALTER TABLE commerce_ideas ADD COLUMN business_id TEXT")
    conn.execute("""
        CREATE INDEX IF NOT EXISTS commerce_ideas_business
        ON commerce_ideas(project,business_id)
    """)


def _event(conn: sqlite3.Connection, project: str, action: str,
           business_id: str | None = None, job_id: str | None = None) -> None:
    conn.execute("""
        INSERT INTO commerce_operation_events(project,business_id,job_id,action,at)
        VALUES(?,?,?,?,?)
    """, (project, business_id, job_id, action, _time()))


def _business(conn: sqlite3.Connection, project: str, identifier: Any) -> sqlite3.Row:
    identifier = _require_id(identifier, "business ID")
    record = conn.execute(
        "SELECT * FROM commerce_businesses WHERE project=? AND id=?",
        (project, identifier),
    ).fetchone()
    if record is None:
        raise ValueError("Business not found in the current STAR workspace")
    return record


def _idea(conn: sqlite3.Connection, project: str, identifier: Any) -> sqlite3.Row:
    identifier = _require_id(identifier, "candidate ID")
    record = conn.execute(
        "SELECT * FROM commerce_ideas WHERE project=? AND id=?",
        (project, identifier),
    ).fetchone()
    if record is None:
        raise ValueError("Candidate not found in the current STAR workspace")
    return record


def _fingerprint(record: sqlite3.Row) -> str:
    """A change to the brief, evidence, assignment or review state invalidates QA."""
    original = {key: record[key] for key in
                ("id", "business_id", "title", "concept", "evidence_json")}
    return sha256(json.dumps(original, sort_keys=True).encode("utf-8")).hexdigest()



def invalidate_preflights(conn: sqlite3.Connection, project: str, idea_id: str) -> None:
    """Changes to actual source evidence invalidate both pending and completed QA."""
    current = _idea(conn, project, idea_id)
    updated = conn.execute("""
        UPDATE commerce_preflight_jobs
        SET status='stale',
            blockers_json=?,
            checked_at=?
        WHERE project=? AND idea_id=? AND fingerprint<>?
          AND status IN ('queued','review_ready','needs_evidence')
    """, (
        json.dumps(["Creative brief, rights evidence or business assignment changed"]),
        _time(), project, idea_id, _fingerprint(current),
    ))
    if updated.rowcount:
        _event(conn, project, "candidate_changed_preflights_stale", current["business_id"])



def validate_assignment(conn: sqlite3.Connection, project: str,
                        business_id: Any, channel: str) -> str:
    business = _business(conn, project, business_id)
    if business["channel"] != channel:
        raise ValueError("Candidate marketplace must match the business channel")
    return business["id"]


def create_business(conn: sqlite3.Connection, project: str, body: Mapping[str, Any]) -> None:
    channel = body.get("channel")
    if not isinstance(channel, str) or channel not in CHANNELS:
        raise ValueError("Choose a supported business marketplace")
    name = _text(body.get("name"), "Business name", 90)
    niche = _text(body.get("niche"), "Customer niche", 300)
    count = conn.execute(
        "SELECT count(*) FROM commerce_businesses WHERE project=?", (project,)
    ).fetchone()[0]
    if count >= MAX_BUSINESSES:
        raise ValueError("Portfolio capacity reached (100 local business records)")
    if conn.execute(
        "SELECT 1 FROM commerce_businesses WHERE project=? AND lower(name)=lower(?)",
        (project, name),
    ).fetchone():
        raise ValueError("A business with this name already exists")
    identifier, now = uuid.uuid4().hex, _time()
    conn.execute("""
        INSERT INTO commerce_businesses
        (id,project,name,niche,channel,paused,created_at,updated_at)
        VALUES(?,?,?,?,?,1,?,?)
    """, (identifier, project, name, niche, channel, now, now))
    _event(conn, project, "business_created_paused", identifier)


def pause_business(conn: sqlite3.Connection, project: str, body: Mapping[str, Any]) -> None:
    item = _business(conn, project, body.get("id"))
    paused = body.get("paused")
    if type(paused) is not bool:
        raise ValueError("The paused setting must be true or false")
    if bool(item["paused"]) == paused:
        return
    conn.execute(
        "UPDATE commerce_businesses SET paused=?,updated_at=? WHERE project=? AND id=?",
        (int(paused), _time(), project, item["id"]),
    )
    _event(conn, project, "business_paused" if paused else "local_checks_resumed", item["id"])


def assign_business(conn: sqlite3.Connection, project: str, body: Mapping[str, Any]) -> None:
    item = _idea(conn, project, body.get("idea_id"))
    business_id = validate_assignment(conn, project, body.get("business_id"), item["channel"])
    if item["business_id"] == business_id:
        return
    conn.execute("""
        UPDATE commerce_ideas
        SET business_id=?,status='draft',updated_at=?
        WHERE project=? AND id=?
    """, (business_id, _time(), project, item["id"]))
    invalidate_preflights(conn, project, item["id"])
    _event(conn, project, "candidate_assigned_approval_reset", business_id)


def queue_preflight(conn: sqlite3.Connection, project: str, body: Mapping[str, Any]) -> None:
    item = _idea(conn, project, body.get("idea_id"))
    if item["business_id"] is None:
        raise ValueError("Assign the candidate to a business before queueing checks")
    business = _business(conn, project, item["business_id"])
    if business["channel"] != item["channel"]:
        raise ValueError("Business and candidate marketplace do not match")
    finger = _fingerprint(item)
    existing = conn.execute("""
        SELECT id,status FROM commerce_preflight_jobs
        WHERE project=? AND idea_id=? AND fingerprint=?
    """, (project, item["id"], finger)).fetchone()
    if existing is not None:
        # Unchanged live or completed work remains deduplicated. If the owner
        # cancelled it or the source later reverted to an older fingerprint,
        # an explicit new queue action may re-open the original record.
        if existing["status"] in ("stale", "cancelled"):
            conn.execute("""
                UPDATE commerce_preflight_jobs
                SET status='queued',blockers_json='[]',checked_at=NULL,created_at=?
                WHERE project=? AND id=?
            """, (_time(), project, existing["id"]))
            _event(conn, project, "preflight_requeued", business["id"], existing["id"])
        return
    jobs = conn.execute(
        "SELECT count(*) FROM commerce_preflight_jobs WHERE project=?", (project,)
    ).fetchone()[0]
    if jobs >= MAX_JOBS:
        raise ValueError("Local job history limit reached; archive via a reviewed migration")
    identifier = uuid.uuid4().hex
    conn.execute("""
        INSERT INTO commerce_preflight_jobs
        (id,project,business_id,idea_id,fingerprint,status,created_at)
        VALUES(?,?,?,?,?,'queued',?)
    """, (identifier, project, business["id"], item["id"], finger, _time()))
    _event(conn, project, "preflight_queued", business["id"], identifier)


def cancel_preflight(conn: sqlite3.Connection, project: str, body: Mapping[str, Any]) -> None:
    job_id = _require_id(body.get("id"), "job ID")
    job = conn.execute("""
        SELECT * FROM commerce_preflight_jobs WHERE project=? AND id=?
    """, (project, job_id)).fetchone()
    if job is None:
        raise ValueError("Job not found in the current STAR workspace")
    if job["status"] != "queued":
        raise ValueError("Only pending checks may be cancelled")
    conn.execute("""
        UPDATE commerce_preflight_jobs SET status='cancelled',checked_at=?
        WHERE project=? AND id=? AND status='queued'
    """, (_time(), project, job_id))
    _event(conn, project, "preflight_cancelled", job["business_id"], job_id)


def _fair_batch(jobs: list[sqlite3.Row], limit: int) -> list[sqlite3.Row]:
    """Round-robin across local businesses, oldest first within each one."""
    groups: dict[str, deque[sqlite3.Row]] = defaultdict(deque)
    for job in jobs:
        groups[job["business_id"]].append(job)
    picked: list[sqlite3.Row] = []
    active = deque(groups)
    while active and len(picked) < limit:
        business_id = active.popleft()
        picked.append(groups[business_id].popleft())
        if groups[business_id]:
            active.append(business_id)
    return picked


def run_preflight(conn: sqlite3.Connection, project: str, body: Mapping[str, Any],
                  assess: Callable[[str, str, str, Mapping[str, Any]], dict[str, Any]]) -> int:
    """Run a bounded manual batch of deterministic *checklist* checks only."""
    limit = body.get("limit", 8)
    if type(limit) is not int or not 1 <= limit <= MAX_BATCH:
        raise ValueError(f"Batch size must be an integer from 1 to {MAX_BATCH}")
    # Even for 100 shops there is no infinite loop or network retry.
    waiting = conn.execute("""
        WITH eligible AS (
          SELECT j.*, ROW_NUMBER() OVER (
              PARTITION BY j.business_id ORDER BY j.created_at ASC,j.id ASC
          ) AS position_in_business
          FROM commerce_preflight_jobs AS j
          JOIN commerce_businesses AS b ON b.id=j.business_id
          WHERE j.project=? AND j.status='queued' AND b.paused=0 AND b.project=j.project
        )
        SELECT * FROM eligible WHERE position_in_business <= ?
        ORDER BY created_at ASC,id ASC
    """, (project, MAX_BATCH)).fetchall()
    selected = _fair_batch(waiting, limit)
    for job in selected:
        item = _idea(conn, project, job["idea_id"])
        if _fingerprint(item) != job["fingerprint"]:
            status, blockers = "stale", ["Product or review evidence changed; queue fresh checks"]
        else:
            report = assess(item["channel"], item["title"], item["concept"],
                            json.loads(item["evidence_json"]))
            status = "review_ready" if report["ready"] else "needs_evidence"
            blockers = report["blockers"]
        conn.execute("""
            UPDATE commerce_preflight_jobs
            SET status=?,blockers_json=?,checked_at=? WHERE project=? AND id=? AND status='queued'
        """, (status, json.dumps(blockers), _time(), project, job["id"]))
        _event(conn, project, "preflight_" + status, job["business_id"], job["id"])
    return len(selected)


def mission_snapshot(conn: sqlite3.Connection, project: str) -> dict[str, Any]:
    businesses = conn.execute("""
        SELECT * FROM commerce_businesses WHERE project=?
        ORDER BY updated_at DESC,id DESC LIMIT ?
    """, (project, MAX_BUSINESSES)).fetchall()
    idea_counts = {str(row[0]): row[1] for row in conn.execute("""
        SELECT business_id,count(*) FROM commerce_ideas
        WHERE project=? AND business_id IS NOT NULL GROUP BY business_id
    """, (project,))}
    queued = {str(row[0]): row[1] for row in conn.execute("""
        SELECT business_id,count(*) FROM commerce_preflight_jobs
        WHERE project=? AND status='queued' GROUP BY business_id
    """, (project,))}
    jobs = conn.execute("""
        SELECT j.id,j.business_id,j.idea_id,j.status,j.blockers_json,
               j.created_at,j.checked_at,i.title AS title
        FROM commerce_preflight_jobs AS j
        JOIN commerce_ideas AS i ON i.id=j.idea_id AND i.project=j.project
        WHERE j.project=? ORDER BY j.created_at DESC,j.id DESC LIMIT 60
    """, (project,)).fetchall()
    counts = dict(conn.execute("""
        SELECT status,count(*) AS count FROM commerce_preflight_jobs
        WHERE project=? GROUP BY status
    """, (project,)).fetchall())
    events = conn.execute("""
        SELECT action,at,business_id,job_id FROM commerce_operation_events
        WHERE project=? ORDER BY id DESC LIMIT 20
    """, (project,)).fetchall()
    return {
        "businesses": [
            {"id": b["id"], "name": b["name"], "niche": b["niche"],
             "channel": b["channel"], "paused": bool(b["paused"]),
             "candidate_count": idea_counts.get(b["id"], 0),
             "queued_checks": queued.get(b["id"], 0),
             "created_at": b["created_at"]}
            for b in businesses
        ],
        "preflight_jobs": [
            {"id": j["id"], "business_id": j["business_id"], "idea_id": j["idea_id"],
             "title": j["title"], "status": j["status"],
             "blockers": json.loads(j["blockers_json"]),
             "created_at": j["created_at"], "checked_at": j["checked_at"]}
            for j in jobs
        ],
        "job_counts": {
            "queued": counts.get("queued", 0), "review_ready": counts.get("review_ready", 0),
            "needs_evidence": counts.get("needs_evidence", 0),
            "stale": counts.get("stale", 0), "cancelled": counts.get("cancelled", 0),
        },
        "recent_activity": [dict(event) for event in events],
        "mission_control": {
            "scope": "private_local_project",
            "execution_mode": "manual_batch_deterministic_preflight_only",
            "auto_start": False,
            "marketplace_write_access": False,
            "real_sales_feed": False,
            "maximum_businesses": MAX_BUSINESSES,
            "maximum_checks_per_batch": MAX_BATCH,
        },
    }


def mission_action(conn: sqlite3.Connection, project: str, action: str,
                   body: Mapping[str, Any],
                   assess: Callable[[str, str, str, Mapping[str, Any]], dict[str, Any]]) -> None:
    if action == "commerceCreateBusiness":
        create_business(conn, project, body)
    elif action == "commercePauseBusiness":
        pause_business(conn, project, body)
    elif action == "commerceAssignBusiness":
        assign_business(conn, project, body)
    elif action == "commerceQueuePreflight":
        queue_preflight(conn, project, body)
    elif action == "commerceCancelPreflight":
        cancel_preflight(conn, project, body)
    elif action == "commerceRunPreflight":
        run_preflight(conn, project, body, assess)
    else:
        raise PermissionError("Unsupported business operation")
