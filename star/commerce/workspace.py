"""STAR Business workspace: durable, local-only draft and review queue.

This module NEVER connects to a seller account, publishes a listing, charges
a card, emails a buyer, or runs model-generated code. The Qt bridge supplies
the active project; web content and model tool calls have no access to actions.
"""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import re
import sqlite3
import threading
import uuid
from typing import Any, Mapping

from .planning import assess_etsy, assess_fiverr
from .sales_learning import LEARNING_ACTIONS, ensure_learning_schema, handle_learning
from .dropshipping import DROPSHIP_ACTIONS, ensure_dropship_schema, handle_dropship
from .mission import ACTIONS as MISSION_ACTIONS, ensure_schema, invalidate_preflights, mission_action, mission_snapshot, validate_assignment

COMMERCE_ACTIONS = frozenset({
    "commerceBoard", "commerceCreate", "commerceEvidence", "commerceReview",
}) | MISSION_ACTIONS | LEARNING_ACTIONS | DROPSHIP_ACTIONS
CHANNELS = {
    "etsy": ("Etsy", "Seller OAuth and approved API app required"),
    "shopify": ("Shopify", "Merchant connection and digital delivery app required"),
    "fiverr": ("Fiverr", "Customer-specific seller delivery remains manual"),
    "payhip": ("Payhip", "Merchant account required; no general product publishing API assumed"),
    "gumroad": ("Gumroad", "Merchant account and supported integrations required"),
    "printify": ("Printify", "Supplier account, cost and production approvals required"),
}
MAX_IDEAS = 250
_LOCK = threading.RLock()
_VALID_ID = re.compile(r"^[0-9a-f]{32}$")
_EVIDENCE = {
    "rights_evidence": 2000,
    "visual_qa_evidence": 2000,
    "buyer_brief": 2000,
    "customization_evidence": 2000,
    "sample_evidence": 2000,
    "ai_disclosed": bool,
    "accurate_mockup_reviewed": bool,
    "buyer_allows_ai": bool,
    "partner_disclosed": bool,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _string(value: Any, label: str, maximum: int) -> str:
    if not isinstance(value, str) or not (1 <= len(value.strip()) <= maximum):
        raise ValueError(f"{label} must be 1–{maximum} characters")
    result = value.strip()
    if any(ord(character) < 32 and character not in "\n\t" for character in result):
        raise ValueError(f"{label} contains invalid control characters")
    return result


def _db_path(home: Path) -> Path:
    # Data belongs to the private STAR app-data profile, NEVER the source tree.
    destination = Path(home) / "commerce"
    destination.mkdir(parents=True, exist_ok=True)
    return destination / "workspace.sqlite3"


def _connect(home: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(_db_path(home), timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("""
        CREATE TABLE IF NOT EXISTS commerce_ideas (
          id TEXT PRIMARY KEY,
          project TEXT NOT NULL,
          channel TEXT NOT NULL,
          title TEXT NOT NULL,
          concept TEXT NOT NULL,
          evidence_json TEXT NOT NULL DEFAULT '{}',
          status TEXT NOT NULL DEFAULT 'draft',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        )
    """)
    connection.execute("""
        CREATE INDEX IF NOT EXISTS commerce_project
          ON commerce_ideas(project, updated_at DESC)
    """)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS commerce_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          project TEXT NOT NULL,
          idea_id TEXT NOT NULL,
          action TEXT NOT NULL,
          at TEXT NOT NULL
        )
    """)
    ensure_schema(connection)
    ensure_learning_schema(connection)
    ensure_dropship_schema(connection)
    connection.commit()
    return connection


def _assessment(channel: str, title: str, concept: str, evidence: Mapping[str, Any]) -> dict[str, Any]:
    if channel == "fiverr":
        assessment = assess_fiverr({
            "title": title,
            "buyer_brief": evidence.get("buyer_brief", ""),
            "rights_evidence": evidence.get("rights_evidence", ""),
            "customization_evidence": evidence.get("customization_evidence", ""),
            "quality_qa_evidence": evidence.get("visual_qa_evidence", ""),
            "ai_used": True,
            "buyer_allows_ai": evidence.get("buyer_allows_ai") is True,
        })
    else:
        assessment = assess_etsy({
            "title": title,
            "product_concept": concept,
            "rights_evidence": evidence.get("rights_evidence", ""),
            "visual_qa_evidence": evidence.get("visual_qa_evidence", ""),
            "accurate_mockup_reviewed": evidence.get("accurate_mockup_reviewed") is True,
            "ai_used": True,
            "ai_disclosed": evidence.get("ai_disclosed") is True,
            "product_type": "physical" if channel == "printify" else "digital",
            "production_partner_used": channel == "printify",
            "partner_disclosed": evidence.get("partner_disclosed") is True,
        })
        if channel == "printify" and not evidence.get("sample_evidence"):
            assessment["blockers"].append("Record a reviewed physical sample and supplier economics.")
            assessment["ready_for_owner_review"] = False
    return {
        "ready": bool(assessment["ready_for_owner_review"]),
        "blockers": assessment["blockers"],
        "owner_approval_required": True,
        "external_actions_performed": False,
    }


def _row(record: sqlite3.Row) -> dict[str, Any]:
    import json
    evidence = json.loads(record["evidence_json"])
    review = _assessment(record["channel"], record["title"], record["concept"], evidence)
    return {
        "id": record["id"],
        "channel": record["channel"],
        "title": record["title"],
        "concept": record["concept"],
        "status": record["status"],
        "business_id": record["business_id"],
        "evidence": evidence,
        "review": review,
        "created_at": record["created_at"],
        "updated_at": record["updated_at"],
    }


def _overview(conn: sqlite3.Connection, project: str) -> dict[str, Any]:
    ideas = [_row(x) for x in conn.execute(
        "SELECT * FROM commerce_ideas WHERE project = ? ORDER BY updated_at DESC, id DESC LIMIT ?",
        (project, MAX_IDEAS),
    ).fetchall()]
    return {
        "project": project,
        "data_source": "local_app_data_only",
        "automation": {
            "state": "not_enabled",
            "description": "Only draft preparation and review. No background selling or marketplace access.",
        },
        "platforms": [
            {"id": key, "label": label, "connection": "not_connected_in_star",
             "note": requirement}
            for key, (label, requirement) in CHANNELS.items()
        ],
        "ideas": ideas,
        **mission_snapshot(conn, project),
        "counts": {
            "candidates": len(ideas),
            "review_ready": sum(1 for x in ideas if x["review"]["ready"] and x["status"] == "draft"),
            "approved_for_export": sum(1 for x in ideas if x["status"] == "approved_for_export"),
            "live_listings": 0,
            "verified_sales": None,
        },
    }


def _new(conn: sqlite3.Connection, project: str, body: Mapping[str, Any]) -> str:
    channel = body.get("channel")
    if not isinstance(channel, str) or channel not in CHANNELS:
        raise ValueError("Choose a supported marketplace")
    title = _string(body.get("title"), "Product title", 120)
    concept = _string(body.get("concept"), "Original creative brief", 3000)
    if conn.execute(
        "SELECT 1 FROM commerce_ideas WHERE project=? AND channel=? AND lower(title)=lower(?)",
        (project, channel, title),
    ).fetchone():
        raise ValueError("This marketplace already has a candidate with that title")
    number = conn.execute("SELECT COUNT(*) FROM commerce_ideas WHERE project=?", (project,)).fetchone()[0]
    if number >= MAX_IDEAS:
        raise ValueError("Workspace limit reached; review or archive existing candidates first")
    business_id = body.get("business_id")
    if business_id is not None:
        business_id = validate_assignment(conn, project, business_id, channel)
    idea_id = uuid.uuid4().hex
    now = _now()
    conn.execute(
        """INSERT INTO commerce_ideas
           (id,project,channel,title,concept,evidence_json,status,created_at,updated_at,business_id)
           VALUES(?,?,?,?,?,'{}','draft',?,?,?)""",
        (idea_id, project, channel, title, concept, now, now, business_id),
    )
    conn.execute(
        "INSERT INTO commerce_events(project,idea_id,action,at) VALUES(?,?,?,?)",
        (project, idea_id, "candidate_created", now),
    )
    return idea_id


def _existing(conn: sqlite3.Connection, project: str, body: Mapping[str, Any]) -> sqlite3.Row:
    idea_id = body.get("id")
    if not isinstance(idea_id, str) or not _VALID_ID.fullmatch(idea_id):
        raise ValueError("Select a valid candidate")
    record = conn.execute(
        "SELECT * FROM commerce_ideas WHERE id=? AND project=?", (idea_id, project)
    ).fetchone()
    if record is None:
        raise ValueError("Candidate not found in this workspace")
    return record


def _evidence(conn: sqlite3.Connection, project: str, body: Mapping[str, Any]) -> None:
    import json
    record = _existing(conn, project, body)
    changes = body.get("evidence")
    if not isinstance(changes, dict) or not changes:
        raise ValueError("Provide evidence fields to update")
    if any(key not in _EVIDENCE for key in changes):
        raise ValueError("Unrecognized evidence field")
    current = json.loads(record["evidence_json"])
    for key, value in changes.items():
        kind = _EVIDENCE[key]
        if kind is bool:
            if type(value) is not bool:
                raise ValueError(f"{key} must be a true/false review")
        else:
            if not isinstance(value, str) or len(value) > kind:
                raise ValueError(f"{key} is too long or invalid")
            value = value.strip()
        current[key] = value
    now = _now()
    conn.execute(
        "UPDATE commerce_ideas SET evidence_json=?,status='draft',updated_at=? WHERE id=? AND project=?",
        (json.dumps(current, ensure_ascii=False), now, record["id"], project),
    )
    invalidate_preflights(conn, project, record["id"])
    conn.execute(
        "INSERT INTO commerce_events(project,idea_id,action,at) VALUES(?,?,?,?)",
        (project, record["id"], "evidence_updated_approval_reset", now),
    )


def _review(conn: sqlite3.Connection, project: str, body: Mapping[str, Any]) -> None:
    record = _existing(conn, project, body)
    decision = body.get("decision")
    if decision not in ("approve", "changes"):
        raise ValueError("Choose approve or request changes")
    if body.get("owner_confirmed") is not True:
        raise PermissionError("Owner confirmation is required for a review decision")
    report = _row(record)["review"]
    if decision == "approve" and not report["ready"]:
        raise ValueError("Resolve all rights, quality and disclosure blockers before approval")
    new_status = "approved_for_export" if decision == "approve" else "changes_requested"
    now = _now()
    conn.execute(
        "UPDATE commerce_ideas SET status=?,updated_at=? WHERE project=? AND id=?",
        (new_status, now, project, record["id"]),
    )
    conn.execute(
        "INSERT INTO commerce_events(project,idea_id,action,at) VALUES(?,?,?,?)",
        (project, record["id"], new_status, now),
    )


def handle_commerce(action: str, body: Mapping[str, Any], *, project: str, home: Path) -> dict[str, Any]:
    """Handle one explicit desktop request. No network, tokens, publishing or buyers."""
    if action not in COMMERCE_ACTIONS:
        raise PermissionError("Unsupported commerce action")
    if not isinstance(body, dict):
        raise ValueError("Invalid commerce request")
    project = _string(project, "Workspace name", 60)
    with _LOCK, closing(_connect(home)) as conn:
        with conn:
            if action == "commerceCreate":
                _new(conn, project, body)
            elif action == "commerceEvidence":
                _evidence(conn, project, body)
            elif action == "commerceReview":
                _review(conn, project, body)
            elif action in MISSION_ACTIONS:
                mission_action(conn, project, action, body, _assessment)
            elif action in LEARNING_ACTIONS:
                return handle_learning(conn, project, action, body)
            elif action in DROPSHIP_ACTIONS:
                return handle_dropship(conn, project, action, body)
        return _overview(conn, project)
