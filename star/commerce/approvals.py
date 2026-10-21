"""Owner approval queue for real-world commerce actions.

Anything that spends money, places or changes an order, lists or prices a product,
posts publicly, messages a customer or touches a third-party account is only ever
*proposed* by STAR (a draft row here). It runs after the owner approves it with an
explicit click in the desktop Business tab (or `python -m star.commerce approvals
approve ID --yes`). Model tools can propose; they cannot approve or execute.

This is a confirmation step, not a filter: any proposal the owner approves may run.
No connector ships in STAR. The owner adds one (with their own credentials) and
until then an approved action simply stays approved and nothing leaves the PC.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import re
import sqlite3
import uuid
from typing import Any, Callable, Mapping

APPROVAL_ACTIONS = frozenset({"commerceApprovals", "commerceApprovalDecide", "commerceApprovalExecute"})
KINDS = {
    "list_product": "List or update a product",
    "change_price": "Change a price",
    "place_order": "Place or change an order",
    "spend_money": "Spend money (ads, tools, stock)",
    "post_public": "Post publicly",
    "message_customer": "Message a customer",
    "account_change": "Change a third-party account",
}
PENDING, APPROVED, REJECTED, EXECUTING, EXECUTED, FAILED = (
    "pending", "approved", "rejected", "executing", "executed", "failed")
MAX_PAYLOAD = 20_000
MAX_LISTED = 200
_ID = re.compile(r"^[0-9a-f]{32}$")
Connector = Callable[[dict[str, Any]], Mapping[str, Any]]
# kind -> function(payload) -> result. Empty by default; the owner registers connectors.
CONNECTORS: dict[str, Connector] = {}


def register_connector(kind: str, connector: Connector) -> None:
    if kind not in KINDS:
        raise ValueError("Unknown action kind")
    CONNECTORS[kind] = connector


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ensure_approval_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS commerce_approvals (
          id TEXT PRIMARY KEY,
          project TEXT NOT NULL,
          business_id TEXT,
          kind TEXT NOT NULL,
          title TEXT NOT NULL,
          payload_json TEXT NOT NULL,
          amount_cents INTEGER,
          status TEXT NOT NULL DEFAULT 'pending',
          proposed_by TEXT NOT NULL,
          result_json TEXT NOT NULL DEFAULT '{}',
          created_at TEXT NOT NULL,
          decided_at TEXT,
          executed_at TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS commerce_approvals_project ON commerce_approvals(project, created_at DESC)")


def _row(record: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": record["id"], "kind": record["kind"], "kind_label": KINDS.get(record["kind"], record["kind"]),
        "business_id": record["business_id"], "title": record["title"],
        "payload": json.loads(record["payload_json"]), "amount_cents": record["amount_cents"],
        "status": record["status"], "proposed_by": record["proposed_by"],
        "result": json.loads(record["result_json"]),
        "created_at": record["created_at"], "decided_at": record["decided_at"],
        "executed_at": record["executed_at"],
    }


def list_approvals(conn: sqlite3.Connection, project: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM commerce_approvals WHERE project=? ORDER BY created_at DESC, id DESC LIMIT ?",
        (project, MAX_LISTED)).fetchall()
    return [_row(r) for r in rows]


def propose(conn: sqlite3.Connection, project: str, kind: str, title: str, payload: Any, *,
            business_id: str | None = None, amount_cents: int | None = None,
            proposed_by: str = "star") -> dict[str, Any]:
    """Record a draft of a real-world action. Nothing runs; the owner decides later."""
    if kind not in KINDS:
        raise ValueError("Unknown action kind: " + ", ".join(KINDS))
    if not isinstance(title, str) or not 1 <= len(title.strip()) <= 160:
        raise ValueError("Title must be 1-160 characters")
    if not isinstance(payload, dict):
        raise ValueError("The action details must be an object")
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    if len(text) > MAX_PAYLOAD:
        raise ValueError("The action details are too large")
    if amount_cents is not None and (type(amount_cents) is not int or amount_cents < 0):
        raise ValueError("amount_cents must be a whole number of cents, 0 or more")
    approval_id = uuid.uuid4().hex
    conn.execute(
        """INSERT INTO commerce_approvals
           (id,project,business_id,kind,title,payload_json,amount_cents,status,proposed_by,created_at)
           VALUES(?,?,?,?,?,?,?,'pending',?,?)""",
        (approval_id, project, business_id, kind, title.strip(), text, amount_cents, proposed_by, _now()))
    return _row(conn.execute("SELECT * FROM commerce_approvals WHERE id=?", (approval_id,)).fetchone())


def _existing(conn: sqlite3.Connection, project: str, body: Mapping[str, Any]) -> sqlite3.Row:
    approval_id = body.get("id")
    if not isinstance(approval_id, str) or not _ID.fullmatch(approval_id):
        raise ValueError("Choose a valid proposed action")
    record = conn.execute("SELECT * FROM commerce_approvals WHERE id=? AND project=?",
                          (approval_id, project)).fetchone()
    if record is None:
        raise ValueError("Proposed action not found in this workspace")
    return record


def decide(conn: sqlite3.Connection, project: str, body: Mapping[str, Any]) -> dict[str, Any]:
    """The owner's click: approve or reject one pending proposal."""
    record = _existing(conn, project, body)
    decision = body.get("decision")
    if decision not in ("approve", "reject"):
        raise ValueError("Choose approve or reject")
    if body.get("owner_confirmed") is not True:
        raise PermissionError("Owner confirmation is required to decide on a proposed action")
    status = APPROVED if decision == "approve" else REJECTED
    moved = conn.execute("UPDATE commerce_approvals SET status=?,decided_at=? WHERE id=? AND status='pending'",
                         (status, _now(), record["id"]))
    if moved.rowcount != 1:
        raise ValueError("This proposed action was already decided")
    return _row(conn.execute("SELECT * FROM commerce_approvals WHERE id=?", (record["id"],)).fetchone())


def execute(conn: sqlite3.Connection, project: str, body: Mapping[str, Any],
            connectors: Mapping[str, Connector] | None = None) -> dict[str, Any]:
    """Run one approved action, once. Refuses anything that is not approved."""
    record = _existing(conn, project, body)
    connector = (CONNECTORS if connectors is None else connectors).get(record["kind"])
    if connector is None:
        if record["status"] != APPROVED:
            raise PermissionError("Only an owner-approved action can run")
        out = _row(record)
        out["result"] = {"executed": False, "reason": "No connector is set up for this kind of action yet. Nothing was sent."}
        return out
    claimed = conn.execute("UPDATE commerce_approvals SET status='executing' WHERE id=? AND status='approved'",
                           (record["id"],))
    if claimed.rowcount != 1:
        raise PermissionError("Only an owner-approved action can run, and only once")
    try:
        result = dict(connector(json.loads(record["payload_json"])))
        status, stored = EXECUTED, result
    except Exception as exc:  # the connector is owner-supplied code; keep the failure on the record
        status, stored = FAILED, {"error": str(exc)[:300]}
    conn.execute("UPDATE commerce_approvals SET status=?,result_json=?,executed_at=? WHERE id=?",
                 (status, json.dumps(stored, ensure_ascii=False), _now(), record["id"]))
    return _row(conn.execute("SELECT * FROM commerce_approvals WHERE id=?", (record["id"],)).fetchone())


def handle_approvals(conn: sqlite3.Connection, project: str, action: str, body: Mapping[str, Any]) -> None:
    if action == "commerceApprovalDecide":
        decide(conn, project, body)
    elif action == "commerceApprovalExecute":
        execute(conn, project, body)
    elif action != "commerceApprovals":
        raise PermissionError("Unsupported approval action")
