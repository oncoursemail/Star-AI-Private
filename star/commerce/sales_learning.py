"""Offline, evidence-first retail learning from merchant-prepared daily aggregates.

This is a descriptive decision-support model, NOT automated revenue, a shop
connection, personal-data processing, a causal seasonal forecast, price setting,
a product publisher, or a trained foundation model. No network or job workers.
It never sees individual orders, names, emails, addresses or customer receipts.
"""
from __future__ import annotations

import calendar
import csv
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal
from hashlib import sha256
from io import StringIO
import json
import math
import re
import sqlite3
import uuid
from typing import Any, Mapping

LEARNING_ACTIONS = frozenset({"commerceLearning", "commerceImportDailyMetrics"})
CSV_COLUMNS = (
    "date", "sessions", "orders", "gross_sales", "refunds",
    "platform_fees", "fulfillment_costs", "ad_spend",
)
COST_COLUMNS = CSV_COLUMNS[3:]
MAX_CSV_CHARS = 80_000
MAX_IMPORT_DAYS = 200
MAX_BUSINESS_DAYS = 3000
_MIN_DATE = date(2017, 1, 1)
_CURRENCY = re.compile(r"^[A-Z]{3}$")
_TIMEZONE = re.compile(r"^[A-Za-z][A-Za-z0-9_+-]*(?:/[A-Za-z0-9_+-]+){0,3}$")
_MONEY = re.compile(r"^(?:0|[1-9][0-9]{0,9})(?:\.[0-9]{1,2})?$")
_WHOLE = re.compile(r"^(?:0|[1-9][0-9]{0,8})$")

# Shopify rolled out new online-store session accounting Sept 21-23, 2026.
# Never compare across this boundary as if visit measurement were stable.
SHOPIFY_SESSIONS_BREAK = date(2026, 9, 21)
_MONTH_WINDOWS = ("early", "middle", "late")
_WEEKDAY = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def ensure_learning_schema(conn: sqlite3.Connection) -> None:
    """Idempotent, additive tables in the same private STAR app-data DB."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS commerce_daily_metrics (
          project TEXT NOT NULL,
          business_id TEXT NOT NULL,
          report_date TEXT NOT NULL,
          sessions INTEGER,
          orders INTEGER NOT NULL,
          gross_cents INTEGER,
          refunds_cents INTEGER,
          fees_cents INTEGER,
          fulfillment_cents INTEGER,
          ads_cents INTEGER,
          currency TEXT NOT NULL,
          report_timezone TEXT NOT NULL,
          source_label TEXT NOT NULL,
          digest TEXT NOT NULL,
          changed_at TEXT NOT NULL,
          PRIMARY KEY(project,business_id,report_date)
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS commerce_daily_business
        ON commerce_daily_metrics(project,business_id,report_date)
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS commerce_metric_imports (
          id TEXT PRIMARY KEY,
          project TEXT NOT NULL,
          business_id TEXT NOT NULL,
          digest TEXT NOT NULL,
          source_label TEXT NOT NULL,
          rows_added INTEGER NOT NULL,
          rows_replaced INTEGER NOT NULL,
          inserted_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS commerce_metric_import_dedupe
        ON commerce_metric_imports(project,business_id,digest)
    """)


def _business(conn: sqlite3.Connection, project: str, value: Any) -> sqlite3.Row:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{32}", value):
        raise ValueError("Choose a valid business")
    found = conn.execute(
        "SELECT * FROM commerce_businesses WHERE id=? AND project=?", (value, project)
    ).fetchone()
    if found is None:
        raise ValueError("Business is not in your current STAR project")
    return found


def _money(value: str, name: str) -> int | None:
    if value == "":
        return None
    if not _MONEY.fullmatch(value):
        raise ValueError(f"{name} must contain a nonnegative amount with no more than two decimals")
    cents = Decimal(value) * 100
    return int(cents)


def _count(value: str, name: str, *, optional: bool = False) -> int | None:
    if value == "" and optional:
        return None
    if not _WHOLE.fullmatch(value):
        raise ValueError(f"{name} must be a nonnegative whole number")
    return int(value)


def _parse_daily_csv(raw: Any, today: date) -> list[dict[str, Any]]:
    if not isinstance(raw, str) or not 1 <= len(raw) <= MAX_CSV_CHARS or "\x00" in raw:
        raise ValueError("Paste up to 80,000 characters of daily aggregate CSV")
    if raw.startswith("\ufeff"):
        raw = raw[1:]
    try:
        reader = csv.DictReader(StringIO(raw, newline=""), restkey="_unexpected", strict=True)
        if reader.fieldnames != list(CSV_COLUMNS):
            raise ValueError("CSV columns must exactly match the documented daily aggregate template")
        rows: list[dict[str, Any]] = []
        seen: set[date] = set()
        for row in reader:
            if len(rows) >= MAX_IMPORT_DAYS:
                raise ValueError("Import a maximum of 200 dates at a time")
            if None in row or "_unexpected" in row:
                raise ValueError("Extra columns or missing fields in daily aggregate CSV")
            if any(not isinstance(value, str) for value in row.values()):
                raise ValueError("Missing CSV field")
            values = {k: v.strip() for k, v in row.items()}
            if any(len(v) > 80 for v in values.values()):
                raise ValueError("CSV cell is too long; never paste customer data")
            raw_date = values["date"]
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw_date):
                raise ValueError("Use YYYY-MM-DD daily dates")
            try:
                when = date.fromisoformat(raw_date)
            except ValueError as exc:
                raise ValueError("Invalid calendar date in CSV") from exc
            if when < _MIN_DATE or when > today + timedelta(days=1):
                raise ValueError("Dates are outside the allowed historical reporting range")
            if when in seen:
                raise ValueError("Every date must appear only once per import")
            seen.add(when)
            row_data: dict[str, Any] = {
                "report_date": when.isoformat(),
                "sessions": _count(values["sessions"], "sessions", optional=True),
                "orders": _count(values["orders"], "orders"),
            }
            for key in COST_COLUMNS:
                row_data[key] = _money(values[key], key)
            rows.append(row_data)
    except csv.Error as exc:
        raise ValueError("Invalid CSV quoting or field structure") from exc
    if not rows:
        raise ValueError("Include at least one daily aggregate after the header")
    return rows


def import_daily_metrics(conn: sqlite3.Connection, project: str,
                         payload: Mapping[str, Any], *, today: date | None = None) -> dict[str, Any]:
    """Import owner-affirmed aggregated seller data; never infer verification."""
    business = _business(conn, project, payload.get("business_id"))
    if payload.get("owner_confirmed") is not True:
        raise PermissionError("Explicitly confirm you own the seller report and removed customer data")
    currency = payload.get("currency")
    if not isinstance(currency, str) or not _CURRENCY.fullmatch(currency):
        raise ValueError("Use a three-letter ISO currency such as USD")
    tz = payload.get("report_timezone")
    if not isinstance(tz, str) or not 1 <= len(tz) <= 64 or not _TIMEZONE.fullmatch(tz):
        raise ValueError("Provide the seller account's reporting timezone, e.g. America/Chicago")
    source = payload.get("source_label")
    if not isinstance(source, str) or not 4 <= len(source.strip()) <= 100:
        raise ValueError("Describe the source report without entering customer information")
    source = source.strip()
    if re.search(r"[\x00-\x1f\x7f]", source):
        raise ValueError("Invalid source label")
    replace = payload.get("replace_existing", False)
    if type(replace) is not bool:
        raise ValueError("Replace existing must be true or false")
    rows = _parse_daily_csv(payload.get("csv_text"), today or datetime.now(timezone.utc).date())
    for row in rows:
        row["currency"] = currency
        row["report_timezone"] = tz
    current = conn.execute(
        "SELECT DISTINCT currency,report_timezone FROM commerce_daily_metrics WHERE project=? AND business_id=?",
        (project, business["id"]),
    ).fetchall()
    if any(r["currency"] != currency or r["report_timezone"] != tz for r in current):
        raise ValueError("Do not combine different currencies or shop reporting timezones")
    prior = {r["report_date"]: r for r in conn.execute(
        "SELECT report_date,digest FROM commerce_daily_metrics WHERE project=? AND business_id=?",
        (project, business["id"]),
    ).fetchall()}
    added, replaced = 0, 0
    changes: list[tuple[dict[str, Any], str]] = []
    for row in rows:
        digest = sha256(json.dumps(row, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        earlier = prior.get(row["report_date"])
        if earlier and earlier["digest"] == digest:
            continue
        if earlier and not replace:
            raise ValueError("Existing report date differs: confirm Replace existing days to correct it")
        if earlier:
            replaced += 1
        else:
            added += 1
        changes.append((row, digest))
    if len(prior) + added > MAX_BUSINESS_DAYS:
        raise ValueError("Too much daily data for this local business (3,000 day limit)")
    batch = sha256(json.dumps(
        {"currency": currency, "timezone": tz, "rows": rows}, sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    if not changes:
        return {"import_status": "identical_no_changes", "added": 0, "replaced": 0}
    # No raw CSV or customer-level data are persisted, even if an import fails.
    stamp = datetime.now(timezone.utc).isoformat(timespec="microseconds")
    for row, digest in changes:
        conn.execute("""
            INSERT INTO commerce_daily_metrics(
              project,business_id,report_date,sessions,orders,
              gross_cents,refunds_cents,fees_cents,fulfillment_cents,ads_cents,
              currency,report_timezone,source_label,digest,changed_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(project,business_id,report_date) DO UPDATE SET
              sessions=excluded.sessions,orders=excluded.orders,
              gross_cents=excluded.gross_cents,refunds_cents=excluded.refunds_cents,
              fees_cents=excluded.fees_cents,fulfillment_cents=excluded.fulfillment_cents,
              ads_cents=excluded.ads_cents,currency=excluded.currency,
              report_timezone=excluded.report_timezone,source_label=excluded.source_label,
              digest=excluded.digest,changed_at=excluded.changed_at
        """, (
            project, business["id"], row["report_date"], row["sessions"], row["orders"],
            row["gross_sales"], row["refunds"], row["platform_fees"],
            row["fulfillment_costs"], row["ad_spend"], currency, tz, source, digest, stamp,
        ))
    conn.execute("""
        INSERT OR IGNORE INTO commerce_metric_imports
        (id,project,business_id,digest,source_label,rows_added,rows_replaced,inserted_at)
        VALUES(?,?,?,?,?,?,?,?)
    """, (uuid.uuid4().hex, project, business["id"], batch, source, added, replaced, stamp))
    return {"import_status": "owner_aggregate_imported", "added": added, "replaced": replaced}


def _window(day: date) -> str:
    return "early" if day.day <= 10 else ("middle" if day.day <= 20 else "late")


def _bucket(rows: list[dict[str, Any]]) -> dict[str, Any]:
    session_known = sum(r["sessions"] is not None for r in rows)
    orders = sum(int(r["orders"]) for r in rows)
    sessions = sum(int(r["sessions"]) for r in rows if r["sessions"] is not None)
    money_known = all(all(r[field] is not None for field in
                          ("gross_cents", "refunds_cents", "fees_cents", "fulfillment_cents", "ads_cents"))
                      for r in rows) and bool(rows)
    contribution = sum(
        int(r["gross_cents"]) - int(r["refunds_cents"]) - int(r["fees_cents"])
        - int(r["fulfillment_cents"]) - int(r["ads_cents"])
        for r in rows
    ) if money_known else None
    return {
        "days": len(rows), "months": len({r["report_date"][:7] for r in rows}),
        "orders": orders,
        "sessions": sessions if session_known == len(rows) and rows else None,
        "orders_per_100_sessions": round(100 * orders / sessions, 2)
        if session_known == len(rows) and sessions > 0 else None,
        "net_contribution_cents": contribution,
        "session_days": session_known,
        "complete_cost_data": money_known,
    }


def _month_segments(rows: list[dict[str, Any]], dimension: str) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    names = _MONTH_WINDOWS if dimension == "third" else _WEEKDAY
    for name in names:
        groups[name] = []
    for r in rows:
        day = date.fromisoformat(r["report_date"])
        group = _window(day) if dimension == "third" else _WEEKDAY[day.weekday()]
        groups[group].append(r)
    return [{"label": name, **_bucket(groups[name])} for name in names]


def _poisson_ratio_lower(orders_a: int, exposure_a: int,
                         orders_b: int, exposure_b: int) -> float:
    """Conservative approximate log-rate ratio limit, never causal evidence."""
    if min(orders_a, exposure_a, orders_b, exposure_b) <= 0:
        return 0.0
    ratio = (orders_a / exposure_a) / (orders_b / exposure_b)
    return ratio * math.exp(-1.96 * math.sqrt(1 / orders_a + 1 / orders_b))


def _coverage(rows: list[dict[str, Any]]) -> float:
    if not rows:
        return 0.0
    first, last = date.fromisoformat(rows[0]["report_date"]), date.fromisoformat(rows[-1]["report_date"])
    return len(rows) / ((last - first).days + 1)


def _hypothesis(rows: list[dict[str, Any]], *, shopify_break: bool) -> dict[str, Any]:
    """Require real repeat observations; return a test hypothesis, never action."""
    weak = {
        "status": "insufficient_evidence", "window": None, "recommendation": None,
        "auto_apply": False, "reason": "",
    }
    months = sorted({r["report_date"][:7] for r in rows})
    if shopify_break:
        return {**weak, "reason":
                "Shopify session-counting method changed in September 2026; split cohorts before inferring a pattern."}
    if (len(rows) < 120 or len(months) < 5 or _coverage(rows) < 0.90
            or any(r["sessions"] is None for r in rows)):
        return {**weak, "reason":
                "Need at least 120 well-covered dates across five months with a consistent session denominator."}
    if sum(int(r["orders"]) for r in rows) < 50:
        return {**weak, "reason": "Fewer than 50 recorded orders; calendar patterns could be random."}
    # Train on early months, require the direction to repeat across two held-out months.
    holdout = set(months[-2:])
    early = [r for r in rows if r["report_date"][:7] not in holdout]
    late = [r for r in rows if r["report_date"][:7] in holdout]
    if not early or not late:
        return {**weak, "reason": "Need separate historical and later months to test consistency."}

    def win_stats(data: list[dict[str, Any]], target: str) -> tuple[int, int, int, int]:
        wanted = [r for r in data if _window(date.fromisoformat(r["report_date"])) == target]
        other = [r for r in data if _window(date.fromisoformat(r["report_date"])) != target]
        return (
            sum(int(r["orders"]) for r in wanted), sum(int(r["sessions"]) for r in wanted),
            sum(int(r["orders"]) for r in other), sum(int(r["sessions"]) for r in other),
        )

    candidates: list[tuple[float, str, tuple[int, int, int, int]]] = []
    for part in _MONTH_WINDOWS:
        stats = win_stats(early, part)
        a, x, b, y = stats
        if x >= 300 and y >= 600 and a >= 10 and b >= 10 and y > 0:
            candidates.append(((a / x) / (b / y), part, stats))
    if not candidates:
        return {**weak, "reason": "Not enough comparable sessions and purchases in earlier periods."}
    ratio, best, stats = max(candidates)
    if ratio < 1.20 or _poisson_ratio_lower(*stats) <= 1.0:
        return {**weak, "reason": "No strong consistent time-of-month signal in historical observations."}
    recent = win_stats(late, best)
    a, x, b, y = recent
    if min(x, y) < 150 or a < 5 or b < 5 or y == 0 or (a / x) <= (b / y):
        return {**weak, "reason":
                "The apparent earlier-month advantage did not repeat in a sufficiently observed later period."}
    return {
        "status": "candidate_for_controlled_experiment",
        "window": best,
        "recommendation": (
            "Test whether scheduling an original product launch during the "
            + {"early":"1st–10th", "middle":"11th–20th", "late":"21st–month-end"}[best]
            + " improves outcomes. Compare against a control with the same offer, traffic source and budget."
        ),
        "reason": "Historical order-to-session rate was higher and direction repeated in two later months; "
                  "this is observational, not proof that the calendar caused sales.",
        "auto_apply": False,
    }


def learning_report(conn: sqlite3.Connection, project: str,
                    business_id: Any, *, today: date | None = None) -> dict[str, Any]:
    """Project-isolated summary; metric denominators and provenance stay explicit."""
    business = _business(conn, project, business_id)
    records = [dict(r) for r in conn.execute("""
        SELECT report_date,sessions,orders,gross_cents,refunds_cents,
               fees_cents,fulfillment_cents,ads_cents,currency,report_timezone,source_label
        FROM commerce_daily_metrics
        WHERE project=? AND business_id=? ORDER BY report_date
    """, (project, business["id"]))]
    now = today or datetime.now(timezone.utc).date()
    recent = [r for r in records if date.fromisoformat(r["report_date"]) >= now - timedelta(days=365)]
    breaks = bool(business["channel"] == "shopify" and recent
                  and date.fromisoformat(recent[0]["report_date"]) < SHOPIFY_SESSIONS_BREAK
                  <= date.fromisoformat(recent[-1]["report_date"]))
    yearly: dict[int, list[dict[str, Any]]] = {m: [] for m in range(1, 13)}
    for row in records:
        if date.fromisoformat(row["report_date"]) >= now - timedelta(days=365 * 3):
            yearly[date.fromisoformat(row["report_date"]).month].append(row)
    year_patterns = [
        {"month": calendar.month_abbr[month],
         "years_seen": len({r["report_date"][:4] for r in yearly[month]}),
         **_bucket(yearly[month])} for month in range(1, 13)
    ]
    source = sorted({r["source_label"] for r in records})
    latest = conn.execute("""
        SELECT rows_added,rows_replaced,source_label,inserted_at
        FROM commerce_metric_imports WHERE project=? AND business_id=?
        ORDER BY inserted_at DESC LIMIT 1
    """, (project, business["id"])).fetchone()
    return {
        "project": project,
        "business_id": business["id"],
        "business_name": business["name"],
        "channel": business["channel"],
        "data_quality": "owner_supplied_aggregates_unverified_by_platform",
        "has_live_feed": False,
        "verified_revenue_cents": None,
        "currency": records[0]["currency"] if records else None,
        "report_timezone": records[0]["report_timezone"] if records else None,
        "imported_daily_rows": len(records),
        "last_import": dict(latest) if latest else None,
        "source_labels": source[:12],
        "date_span": ([records[0]["report_date"], records[-1]["report_date"]] if records else None),
        "recent_coverage": round(_coverage(recent), 3),
        "sessions_all_reported": bool(recent) and all(r["sessions"] is not None for r in recent),
        "shopify_measurement_break": breaks,
        "last_365_days": _bucket(recent),
        "time_of_month": _month_segments(recent, "third"),
        "weekday": _month_segments(recent, "weekday"),
        "month_of_year": year_patterns,
        "signal": _hypothesis(recent, shopify_break=breaks),
        "safeguards": [
            "Only owner-supplied daily aggregate records are stored; no customer data.",
            "Do not pool different shops, currencies, timezones or visit definitions.",
            "Seasonal rates describe correlation; controlled experiments are still needed.",
            "No automated price changes, posting, paid advertising or customer messaging.",
            "Contribution estimates exclude tax, owner's labor and additional overhead.",
        ],
    }


def handle_learning(conn: sqlite3.Connection, project: str,
                    action: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    if action == "commerceLearning":
        return learning_report(conn, project, payload.get("business_id"))
    if action == "commerceImportDailyMetrics":
        result = import_daily_metrics(conn, project, payload)
        return {**learning_report(conn, project, payload.get("business_id")), **result}
    raise PermissionError("Unsupported sales learning action")
