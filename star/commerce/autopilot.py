"""STAR Commerce Pilot: opt-in, bounded, deterministic local operational checks.

This is deliberately NOT an external ecommerce agent. It cannot order stock,
publish products, send messages, change prices, access customer information,
spend on ads, or call third-party APIs. It works on STAR's *existing owner
imported* supplier observations, creates deduplicated review findings and
keeps per-business immutable-ish audit records in the private app-data DB.
"""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import re
import sqlite3
import uuid
from pathlib import Path
from typing import Any, Mapping

from .dropshipping import SENSITIVE_CATEGORIES, _economics, _shop

PILOT_ACTIONS = frozenset({
    "commercePilot", "commercePilotConfigure", "commercePilotScan",
    "commercePilotDismiss",
})
MAX_OFFERS_PER_CYCLE = 1000
MAX_FINDINGS = 10_000
MAX_AUDIT = 5_000
MAX_DUE_BUSINESSES = 12
_FINDING_ID = re.compile(r"^[0-9a-f]{32}$")
_LIMITS = {
    "minimum_stock": (0, 500),
    "minimum_margin_pct": (5, 70),
    "maximum_delivery_days": (1, 30),
    "stale_after_days": (1, 90),
    "interval_minutes": (15, 1440),
}
DEFAULTS = {
    "enabled": False,
    "minimum_stock": 3,
    "minimum_margin_pct": 25,
    "maximum_delivery_days": 14,
    "stale_after_days": 7,
    "interval_minutes": 60,
    "last_run": None,
    "last_scanned": 0,
}
SEVERITY_ORDER = {"critical": 0, "warning": 1}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def ensure_pilot_schema(conn: sqlite3.Connection) -> None:
    """Additive private SQLite tables; no tokens, customer data or external jobs."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS commerce_pilot_settings (
          project TEXT NOT NULL,
          business_id TEXT NOT NULL,
          enabled INTEGER NOT NULL DEFAULT 0 CHECK(enabled IN (0,1)),
          minimum_stock INTEGER NOT NULL DEFAULT 3,
          minimum_margin_pct INTEGER NOT NULL DEFAULT 25,
          maximum_delivery_days INTEGER NOT NULL DEFAULT 14,
          stale_after_days INTEGER NOT NULL DEFAULT 7,
          interval_minutes INTEGER NOT NULL DEFAULT 60,
          last_run TEXT,
          last_scanned INTEGER NOT NULL DEFAULT 0,
          updated_at TEXT NOT NULL,
          PRIMARY KEY(project,business_id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS commerce_pilot_findings (
          id TEXT PRIMARY KEY,
          project TEXT NOT NULL,
          business_id TEXT NOT NULL,
          supplier TEXT NOT NULL,
          sku TEXT NOT NULL,
          code TEXT NOT NULL,
          severity TEXT NOT NULL CHECK(severity IN ('critical','warning')),
          detail TEXT NOT NULL,
          fingerprint TEXT NOT NULL,
          state TEXT NOT NULL CHECK(state IN ('open','dismissed','resolved')),
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          UNIQUE(project,business_id,supplier,sku,code)
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS commerce_pilot_findings_project
        ON commerce_pilot_findings(project,business_id,state,updated_at DESC)
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS commerce_pilot_audit (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          project TEXT NOT NULL, business_id TEXT NOT NULL,
          event TEXT NOT NULL, finding_id TEXT,
          at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS commerce_pilot_audit_project
        ON commerce_pilot_audit(project,business_id,id DESC)
    """)


def _settings(conn: sqlite3.Connection, project: str, business_id: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM commerce_pilot_settings WHERE project=? AND business_id=?",
        (project, business_id),
    ).fetchone()
    if row is None:
        return dict(DEFAULTS)
    return {
        "enabled": bool(row["enabled"]),
        **{key: int(row[key]) for key in _LIMITS},
        "last_run": row["last_run"],
        "last_scanned": int(row["last_scanned"]),
    }


def _audit(conn: sqlite3.Connection, project: str, business_id: str, event: str,
           *, finding_id: str | None = None, at: str) -> None:
    conn.execute(
        "INSERT INTO commerce_pilot_audit(project,business_id,event,finding_id,at) VALUES(?,?,?,?,?)",
        (project, business_id, event, finding_id, at),
    )


def _limit_audit(conn: sqlite3.Connection, project: str, business_id: str) -> None:
    conn.execute("""
        DELETE FROM commerce_pilot_audit
        WHERE project=? AND business_id=?
          AND id NOT IN (
            SELECT id FROM commerce_pilot_audit
            WHERE project=? AND business_id=?
            ORDER BY id DESC LIMIT ?
          )
    """, (project, business_id, project, business_id, MAX_AUDIT))


def _configure(conn: sqlite3.Connection, project: str, shop: sqlite3.Row,
               body: Mapping[str, Any], at: str) -> None:
    if body.get("owner_confirmed") is not True:
        raise PermissionError("Owner confirmation is required to change local monitoring")
    enabled = body.get("enabled")
    if type(enabled) is not bool:
        raise ValueError("enabled must be a boolean")
    options: dict[str, int] = {}
    for key, (minimum, maximum) in _LIMITS.items():
        value = body.get(key)
        if type(value) is not int or not minimum <= value <= maximum:
            raise ValueError(f"{key} must be an integer between {minimum} and {maximum}")
        options[key] = value
    original = _settings(conn, project, shop["id"])
    # Same confirmation is always required, even when values appear unchanged.
    if enabled == original["enabled"] and all(options[k] == original[k] for k in _LIMITS):
        return
    conn.execute("""
        INSERT INTO commerce_pilot_settings (
          project,business_id,enabled,minimum_stock,minimum_margin_pct,
          maximum_delivery_days,stale_after_days,interval_minutes,
          last_run,last_scanned,updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(project,business_id) DO UPDATE SET
          enabled=excluded.enabled,
          minimum_stock=excluded.minimum_stock,
          minimum_margin_pct=excluded.minimum_margin_pct,
          maximum_delivery_days=excluded.maximum_delivery_days,
          stale_after_days=excluded.stale_after_days,
          interval_minutes=excluded.interval_minutes,
          updated_at=excluded.updated_at
    """, (project, shop["id"], int(enabled), options["minimum_stock"],
          options["minimum_margin_pct"], options["maximum_delivery_days"],
          options["stale_after_days"], options["interval_minutes"],
          original["last_run"], original["last_scanned"], at))
    _audit(conn, project, shop["id"], "local_monitoring_enabled" if enabled else
           "local_monitoring_disabled", at=at)
    _limit_audit(conn, project, shop["id"])


def _issues(row: sqlite3.Row, policy: Mapping[str, Any], now: datetime) -> list[tuple[str, str, str]]:
    """Produce only rules supported by owner-imported values; never invent demand."""
    issues: list[tuple[str, str, str]] = []
    stock = int(row["stock"])
    if stock == 0:
        issues.append(("stock_zero", "critical", "Supplier-reported stock is zero; do not offer this variant."))
    elif stock < policy["minimum_stock"]:
        issues.append(("stock_low", "warning",
                       f"Supplier reports {stock} units, below the {policy['minimum_stock']} unit buffer."))
    screened = _economics(row)
    if screened["estimated_contribution_ratio"] * 100 < policy["minimum_margin_pct"]:
        issues.append(("contribution_low", "critical",
                       f"Modeled contribution before advertising is below {policy['minimum_margin_pct']}%; verify all costs."))
    if int(row["delivery_days"]) > policy["maximum_delivery_days"]:
        issues.append(("shipping_slow", "warning",
                       f"Supplier estimates {row['delivery_days']} days; configured limit is {policy['maximum_delivery_days']}."))
    if not row["returns_supported"]:
        issues.append(("returns_unknown", "warning", "Supplier return support has not been confirmed."))
    if not row["sample_reviewed"]:
        issues.append(("sample_missing", "warning", "No owner-reviewed physical sample is documented."))
    if any(term in row["category"].casefold() for term in SENSITIVE_CATEGORIES):
        issues.append(("sensitive_product", "critical",
                       "This category may require a specialized safety, advertising and legal review."))
    try:
        age_days = (now - datetime.fromisoformat(row["observed_at"])).total_seconds() / 86400
    except (TypeError, ValueError):
        age_days = float("inf")
    if age_days > policy["stale_after_days"]:
        issues.append(("supplier_stale", "warning",
                       f"Supplier cost, delivery and stock evidence is older than {policy['stale_after_days']} days."))
    return issues


def _scan(conn: sqlite3.Connection, project: str, shop: sqlite3.Row, *,
          now: datetime, scheduled: bool) -> dict[str, Any]:
    policy = _settings(conn, project, shop["id"])
    if shop["paused"]:
        return {"state": "business_paused", "scanned": 0, "opened": 0, "closed": 0}
    if scheduled:
        if not policy["enabled"]:
            return {"state": "disabled", "scanned": 0, "opened": 0, "closed": 0}
        previous = policy["last_run"]
        if previous:
            try:
                deadline = datetime.fromisoformat(previous) + timedelta(minutes=policy["interval_minutes"])
                if now < deadline:
                    return {"state": "not_due", "scanned": 0, "opened": 0, "closed": 0}
            except ValueError:
                pass
    rows = conn.execute("""
        SELECT * FROM commerce_supplier_offers
        WHERE project=? AND business_id=?
        ORDER BY supplier,sku LIMIT ?
    """, (project, shop["id"], MAX_OFFERS_PER_CYCLE)).fetchall()
    at = _iso(now)
    new_or_reopened = 0
    active: set[tuple[str, str, str]] = set()
    count_findings = conn.execute("""
        SELECT COUNT(*) FROM commerce_pilot_findings WHERE project=? AND business_id=?
    """, (project, shop["id"])).fetchone()[0]
    for row in rows:
        for code, severity, detail in _issues(row, policy, now):
            key = (row["supplier"], row["sku"], code)
            active.add(key)
            # Hash evidence and policy. If a dismissed risk survives unchanged,
            # retain the dismissal. New evidence forces a fresh review.
            fingerprint = sha256(json.dumps([
                row["digest"], code, severity, detail,
                policy["minimum_stock"], policy["minimum_margin_pct"],
                policy["maximum_delivery_days"], policy["stale_after_days"],
            ], ensure_ascii=False).encode("utf-8")).hexdigest()
            old = conn.execute("""
                SELECT id, fingerprint, state FROM commerce_pilot_findings
                WHERE project=? AND business_id=? AND supplier=? AND sku=? AND code=?
            """, (project, shop["id"], *key)).fetchone()
            if old is not None and old["fingerprint"] == fingerprint and old["state"] != "resolved":
                continue
            if old is None:
                if count_findings >= MAX_FINDINGS:
                    raise ValueError("Finding capacity reached; review and archive old alerts")
                finding_id = uuid.uuid4().hex
                conn.execute("""
                    INSERT INTO commerce_pilot_findings
                    (id,project,business_id,supplier,sku,code,severity,detail,
                     fingerprint,state,created_at,updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,'open',?,?)
                """, (finding_id, project, shop["id"], *key, severity, detail, fingerprint, at, at))
                count_findings += 1
            else:
                finding_id = old["id"]
                conn.execute("""
                    UPDATE commerce_pilot_findings
                    SET severity=?,detail=?,fingerprint=?,state='open',
                        created_at=?,updated_at=?
                    WHERE id=? AND project=? AND business_id=?
                """, (severity, detail, fingerprint, at, at, finding_id, project, shop["id"]))
            _audit(conn, project, shop["id"], "finding_opened", finding_id=finding_id, at=at)
            new_or_reopened += 1
    current = conn.execute("""
        SELECT id,supplier,sku,code FROM commerce_pilot_findings
        WHERE project=? AND business_id=? AND state!='resolved'
    """, (project, shop["id"])).fetchall()
    closed = 0
    for item in current:
        if (item["supplier"], item["sku"], item["code"]) in active:
            continue
        conn.execute("""
            UPDATE commerce_pilot_findings SET state='resolved',updated_at=?
            WHERE id=? AND project=? AND business_id=?
        """, (at, item["id"], project, shop["id"]))
        _audit(conn, project, shop["id"], "finding_resolved", finding_id=item["id"], at=at)
        closed += 1
    conn.execute("""
        INSERT INTO commerce_pilot_settings
          (project,business_id,enabled,minimum_stock,minimum_margin_pct,
           maximum_delivery_days,stale_after_days,interval_minutes,
           last_run,last_scanned,updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(project,business_id) DO UPDATE SET
          last_run=excluded.last_run,last_scanned=excluded.last_scanned
    """, (project, shop["id"], int(policy["enabled"]), policy["minimum_stock"],
          policy["minimum_margin_pct"], policy["maximum_delivery_days"],
          policy["stale_after_days"], policy["interval_minutes"], at, len(rows), at))
    _limit_audit(conn, project, shop["id"])
    return {"state": "local_only_completed", "scanned": len(rows),
            "opened": new_or_reopened, "closed": closed, "external_actions": 0}


def _dismiss(conn: sqlite3.Connection, project: str, shop: sqlite3.Row,
             body: Mapping[str, Any], at: str) -> None:
    if body.get("owner_confirmed") is not True:
        raise PermissionError("Owner confirmation is required to dismiss a finding")
    ident = body.get("id")
    if not isinstance(ident, str) or not _FINDING_ID.fullmatch(ident):
        raise ValueError("Choose a valid finding")
    record = conn.execute("""
        SELECT * FROM commerce_pilot_findings
        WHERE id=? AND project=? AND business_id=?
    """, (ident, project, shop["id"])).fetchone()
    if record is None:
        raise ValueError("Finding not found for this business")
    if record["state"] == "open":
        conn.execute("""
            UPDATE commerce_pilot_findings SET state='dismissed',updated_at=?
            WHERE id=? AND project=? AND business_id=?
        """, (at, ident, project, shop["id"]))
        _audit(conn, project, shop["id"], "finding_dismissed", finding_id=ident, at=at)
        _limit_audit(conn, project, shop["id"])


def _snapshot(conn: sqlite3.Connection, project: str, shop: sqlite3.Row) -> dict[str, Any]:
    settings = _settings(conn, project, shop["id"])
    counts = {row["state"]: row["n"] for row in conn.execute("""
        SELECT state,COUNT(*) n FROM commerce_pilot_findings
        WHERE project=? AND business_id=? GROUP BY state
    """, (project, shop["id"])).fetchall()}
    findings = conn.execute("""
        SELECT id,supplier,sku,code,severity,detail,state,created_at,updated_at
        FROM commerce_pilot_findings WHERE project=? AND business_id=?
        ORDER BY CASE state WHEN 'open' THEN 0 WHEN 'dismissed' THEN 1 ELSE 2 END,
                 CASE severity WHEN 'critical' THEN 0 ELSE 1 END,
                 updated_at DESC,id LIMIT 120
    """, (project, shop["id"])).fetchall()
    audit = conn.execute("""
        SELECT event,at FROM commerce_pilot_audit
        WHERE project=? AND business_id=? ORDER BY id DESC LIMIT 12
    """, (project, shop["id"])).fetchall()
    return {
        "project": project, "business_id": shop["id"], "business_name": shop["name"],
        "business_paused": bool(shop["paused"]),
        "monitoring": settings,
        "findings": [dict(row) for row in findings],
        "finding_counts": {"open": counts.get("open", 0),
                           "dismissed": counts.get("dismissed", 0),
                           "resolved": counts.get("resolved", 0)},
        "audit": [dict(row) for row in audit],
        "execution": "deterministic_local_records_only",
        "requires_desktop_running": True,
        "external_connectors_active": False,
        "automatic_supplier_refresh": False,
        "auto_send": False, "auto_publish": False, "auto_spend": False, "auto_fulfill": False,
        "customer_data_present": False,
    }


def handle_pilot(conn: sqlite3.Connection, project: str, action: str,
                 body: Mapping[str, Any]) -> dict[str, Any]:
    if action not in PILOT_ACTIONS:
        raise PermissionError("Unsupported STAR Commerce Pilot action")
    shop = _shop(conn, project, body)
    now = _now()
    extra: dict[str, Any] = {}
    if action == "commercePilotConfigure":
        _configure(conn, project, shop, body, _iso(now))
    elif action == "commercePilotScan":
        if body.get("owner_confirmed") is not True:
            raise PermissionError("Owner must approve a local manual scan")
        extra["scan_result"] = _scan(conn, project, shop, now=now, scheduled=False)
    elif action == "commercePilotDismiss":
        _dismiss(conn, project, shop, body, _iso(now))
    return {**_snapshot(conn, project, shop), **extra}


def run_due_pilot_checks(home: Path, project: str) -> dict[str, int]:
    """Run owner-opted-in local scans while the STAR desktop remains open.

    Called by the Qt scheduler. No credentials, supplier refresh or network.
    Even if a model later calls this by mistake, it has no spending/sending APIs.
    """
    from .workspace import _LOCK, _connect  # local import avoids package cycles
    checked = 0
    findings = 0
    with _LOCK, closing(_connect(Path(home))) as conn:
        with conn:
            shops = conn.execute("""
                SELECT b.* FROM commerce_businesses AS b
                JOIN commerce_pilot_settings AS p
                  ON p.project=b.project AND p.business_id=b.id
                WHERE b.project=? AND b.channel='shopify' AND b.paused=0
                      AND p.enabled=1
                ORDER BY COALESCE(p.last_run,'') ASC,b.id LIMIT ?
            """, (project, MAX_DUE_BUSINESSES)).fetchall()
            now = _now()
            for shop in shops:
                result = _scan(conn, project, shop, now=now, scheduled=True)
                if result["state"] == "local_only_completed":
                    checked += 1
                    findings += result["opened"]
    return {"businesses_checked": checked, "new_review_findings": findings,
            "external_actions": 0}
