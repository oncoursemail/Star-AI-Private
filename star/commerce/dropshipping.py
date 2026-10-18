"""STAR Business: local evidence-driven dropshipping research and support drafting.

All supplier, search-volume and policy information is owner-supplied and unverified.
No external API, Gmail mailbox, supplier, listing, order or advertising account
can be contacted from this module. In particular, an import NEVER buys stock.
"""
from __future__ import annotations

import csv
from datetime import date, datetime, timezone
from decimal import Decimal
from hashlib import sha256
from io import StringIO
import json
import re
import sqlite3
from typing import Any, Mapping
from urllib.parse import urlsplit

from .sales_learning import _business

DROPSHIP_ACTIONS = frozenset({
    "commerceDropship", "commerceDropshipImportOffers", "commerceDropshipImportSignals",
    "commerceDropshipSavePolicy", "commerceDropshipDraftReply",
})
OFFER_COLUMNS = (
    "supplier", "sku", "title", "category", "product_url", "unit_cost",
    "shipping_cost", "target_price", "stock", "delivery_days",
    "returns_supported", "sample_reviewed",
)
SIGNAL_COLUMNS = ("sku", "source", "metric", "value", "observed_on")
SIGNAL_METRICS = {
    "google_trends": ("trends_index", 100),
    "google_ads_keyword_planner": ("monthly_searches", 100000000),
    "merchant_center": ("merchant_clicks", 100000000),
}
SENSITIVE_CATEGORIES = (
    "weapon", "firearm", "medical", "supplement", "chemical", "battery",
    "infant", "baby", "cosmetic", "counterfeit", "drug", "food", "alcohol",
)
MAX_OFFERS = 1000
MAX_SIGNALS = 3000
MAX_IMPORT = 150
MONEY = re.compile(r"^(?:0|[1-9][0-9]{0,8})(?:\.[0-9]{1,2})?$")
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
NO_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def ensure_dropship_schema(conn: sqlite3.Connection) -> None:
    """Additive SQLite tables in STAR private app-data; no credentials or customer PII."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS commerce_supplier_offers (
          project TEXT NOT NULL, business_id TEXT NOT NULL,
          supplier TEXT NOT NULL, sku TEXT NOT NULL,
          title TEXT NOT NULL, category TEXT NOT NULL, product_url TEXT NOT NULL,
          unit_cents INTEGER NOT NULL, shipping_cents INTEGER NOT NULL,
          price_cents INTEGER NOT NULL, stock INTEGER NOT NULL,
          delivery_days INTEGER NOT NULL, returns_supported INTEGER NOT NULL,
          sample_reviewed INTEGER NOT NULL, source_label TEXT NOT NULL,
          digest TEXT NOT NULL, observed_at TEXT NOT NULL,
          PRIMARY KEY(project,business_id,supplier,sku)
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS commerce_supplier_lookup
        ON commerce_supplier_offers(project,business_id,observed_at DESC)
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS commerce_demand_signals (
          project TEXT NOT NULL, business_id TEXT NOT NULL, sku TEXT NOT NULL,
          source TEXT NOT NULL, metric TEXT NOT NULL, value INTEGER NOT NULL,
          observed_on TEXT NOT NULL, imported_at TEXT NOT NULL,
          PRIMARY KEY(project,business_id,sku,source,metric,observed_on)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS commerce_support_policy (
          project TEXT NOT NULL, business_id TEXT NOT NULL,
          shipping TEXT NOT NULL, returns TEXT NOT NULL, contact TEXT NOT NULL,
          approved_at TEXT NOT NULL,
          PRIMARY KEY(project,business_id)
        )
    """)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _text(value: Any, label: str, max_length: int, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be text")
    cleaned = value.strip()
    if (not allow_empty and not cleaned) or len(cleaned) > max_length or NO_CONTROL.search(cleaned):
        raise ValueError(f"Invalid {label}")
    if cleaned.startswith(("=", "+", "@")):
        raise ValueError(f"{label} cannot begin with a spreadsheet formula")
    return cleaned


def _money(value: str, name: str, *, positive: bool = False) -> int:
    if not MONEY.fullmatch(value):
        raise ValueError(f"{name} must be a nonnegative amount with 0–2 decimal places")
    amount = int(Decimal(value) * 100)
    if positive and amount == 0:
        raise ValueError(f"{name} must be greater than zero")
    return amount


def _integer(value: str, name: str, limit: int) -> int:
    if not isinstance(value, str) or not re.fullmatch(r"(?:0|[1-9]\d{0,8})", value):
        raise ValueError(f"Invalid {name}")
    number = int(value)
    if number > limit:
        raise ValueError(f"{name} exceeds the supported limit")
    return number


def _yes_no(value: str, name: str) -> int:
    if value not in ("yes", "no"):
        raise ValueError(f"{name} must be yes or no")
    return int(value == "yes")


def _url(value: str) -> str:
    url = _text(value, "Supplier product URL", 500)
    parts = urlsplit(url)
    if (parts.scheme != "https" or not parts.hostname or parts.username or parts.password
            or parts.hostname in ("localhost", "127.0.0.1", "::1")
            or "." not in parts.hostname):
        raise ValueError("Supplier product URLs must be public HTTPS links")
    return url


def _csv_rows(content: Any, columns: tuple[str, ...], label: str) -> list[dict[str, str]]:
    if not isinstance(content, str) or len(content) > 90000:
        raise ValueError(f"{label} CSV is too large")
    try:
        reader = csv.DictReader(StringIO(content, newline=""), strict=True)
        if tuple(reader.fieldnames or ()) != columns:
            raise ValueError(f"{label} must use exactly: {','.join(columns)}")
        rows = list(reader)
    except csv.Error as exc:
        raise ValueError(f"Malformed {label} CSV") from exc
    if not 1 <= len(rows) <= MAX_IMPORT:
        raise ValueError(f"Import between 1 and {MAX_IMPORT} {label} rows")
    for item in rows:
        if None in item or any(value is None for value in item.values()):
            raise ValueError(f"{label} rows must contain exactly the required columns")
    return rows


def _shop(conn: sqlite3.Connection, project: str, body: Mapping[str, Any]) -> sqlite3.Row:
    record = _business(conn, project, body.get("business_id"))
    if record["channel"] != "shopify":
        raise ValueError("Choose a Shopify business for the dropshipping workspace")
    return record


def _owner(body: Mapping[str, Any]) -> None:
    if body.get("owner_confirmed") is not True:
        raise PermissionError("Owner must confirm permission to use supplier or policy information")


def _import_offers(conn: sqlite3.Connection, project: str, shop: sqlite3.Row, body: Mapping[str, Any]) -> dict[str, int]:
    _owner(body)
    source_label = _text(body.get("source_label"), "Source label", 100)
    rows = _csv_rows(body.get("csv_text"), OFFER_COLUMNS, "Supplier offer")
    validated: list[tuple[Any, ...]] = []
    unique = set()
    for row in rows:
        supplier = _text(row["supplier"], "Supplier", 80)
        sku = _text(row["sku"], "SKU", 64)
        if not SAFE_ID.fullmatch(sku):
            raise ValueError("SKU must use letters, numbers, dots, dashes or underscores")
        key = (supplier.lower(), sku.lower())
        if key in unique:
            raise ValueError("Duplicate supplier and SKU within this upload")
        unique.add(key)
        title = _text(row["title"], "Title", 160)
        category = _text(row["category"], "Category", 80)
        product_url = _url(row["product_url"])
        unit = _money(row["unit_cost"], "Unit cost", positive=True)
        shipping = _money(row["shipping_cost"], "Shipping cost")
        price = _money(row["target_price"], "Target price", positive=True)
        if price > 100000000:
            raise ValueError("Target price exceeds the supported limit")
        stock = _integer(row["stock"], "Stock", 1000000)
        days = _integer(row["delivery_days"], "Delivery days", 90)
        returns = _yes_no(row["returns_supported"], "Returns supported")
        sample = _yes_no(row["sample_reviewed"], "Sample reviewed")
        values = (supplier, sku, title, category, product_url, unit, shipping, price,
                  stock, days, returns, sample)
        digest = sha256(json.dumps(values, ensure_ascii=False).encode()).hexdigest()
        validated.append((project, shop["id"], *values, source_label, digest, _now()))
    existing_count = conn.execute(
        "SELECT COUNT(*) FROM commerce_supplier_offers WHERE project=? AND business_id=?",
        (project, shop["id"]),
    ).fetchone()[0]
    new_keys = sum(1 for item in validated if not conn.execute(
        "SELECT 1 FROM commerce_supplier_offers WHERE project=? AND business_id=? AND supplier=? AND sku=?",
        (project, shop["id"], item[2], item[3]),
    ).fetchone())
    if existing_count + new_keys > MAX_OFFERS:
        raise ValueError("Supplier catalog exceeds 1000 offers for this business")
    added = updated = unchanged = 0
    for item in validated:
        old = conn.execute(
            "SELECT digest FROM commerce_supplier_offers WHERE project=? AND business_id=? AND supplier=? AND sku=?",
            (project, shop["id"], item[2], item[3]),
        ).fetchone()
        if old and old["digest"] == item[-2]:
            unchanged += 1
            continue
        conn.execute("""
            INSERT INTO commerce_supplier_offers
              (project,business_id,supplier,sku,title,category,product_url,unit_cents,
               shipping_cents,price_cents,stock,delivery_days,returns_supported,
               sample_reviewed,source_label,digest,observed_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(project,business_id,supplier,sku) DO UPDATE SET
              title=excluded.title, category=excluded.category, product_url=excluded.product_url,
              unit_cents=excluded.unit_cents, shipping_cents=excluded.shipping_cents,
              price_cents=excluded.price_cents, stock=excluded.stock,
              delivery_days=excluded.delivery_days, returns_supported=excluded.returns_supported,
              sample_reviewed=excluded.sample_reviewed, source_label=excluded.source_label,
              digest=excluded.digest, observed_at=excluded.observed_at
        """, item)
        if old:
            updated += 1
        else:
            added += 1
    return {"added": added, "updated": updated, "unchanged": unchanged}


def _import_signals(conn: sqlite3.Connection, project: str, shop: sqlite3.Row, body: Mapping[str, Any]) -> dict[str, int]:
    _owner(body)
    rows = _csv_rows(body.get("csv_text"), SIGNAL_COLUMNS, "Demand signal")
    entries: list[tuple[Any, ...]] = []
    keys = set()
    for row in rows:
        sku = _text(row["sku"], "SKU", 64)
        if not SAFE_ID.fullmatch(sku):
            raise ValueError("Invalid signal SKU")
        source = row["source"]
        metric = row["metric"]
        if source not in SIGNAL_METRICS or metric != SIGNAL_METRICS[source][0]:
            raise ValueError("Demand source and metric do not match")
        value = _integer(row["value"], "Signal value", SIGNAL_METRICS[source][1])
        try:
            observed = date.fromisoformat(row["observed_on"])
        except ValueError as exc:
            raise ValueError("Signal date must be YYYY-MM-DD") from exc
        if not date(2020, 1, 1) <= observed <= datetime.now(timezone.utc).date():
            raise ValueError("Signal date is outside supported range")
        if not conn.execute(
            "SELECT 1 FROM commerce_supplier_offers WHERE project=? AND business_id=? AND sku=?",
            (project, shop["id"], sku),
        ).fetchone():
            raise ValueError("Demand signal references an unknown supplier SKU")
        key = (sku, source, metric, str(observed))
        if key in keys:
            raise ValueError("Duplicate signal in upload")
        keys.add(key)
        entries.append((project, shop["id"], sku, source, metric, value, str(observed), _now()))
    existing_count = conn.execute(
        "SELECT COUNT(*) FROM commerce_demand_signals WHERE project=? AND business_id=?",
        (project, shop["id"]),
    ).fetchone()[0]
    new_count = sum(1 for item in entries if not conn.execute(
        """SELECT 1 FROM commerce_demand_signals
           WHERE project=? AND business_id=? AND sku=? AND source=? AND metric=? AND observed_on=?""",
        item[:5] + (item[6],),
    ).fetchone())
    if existing_count + new_count > MAX_SIGNALS:
        raise ValueError("Demand-signal limit reached")
    changed = 0
    for item in entries:
        old = conn.execute(
            """SELECT value FROM commerce_demand_signals
               WHERE project=? AND business_id=? AND sku=? AND source=? AND metric=? AND observed_on=?""",
            item[:5] + (item[6],),
        ).fetchone()
        if old and old["value"] == item[5]:
            continue
        conn.execute("""
            INSERT INTO commerce_demand_signals
            (project,business_id,sku,source,metric,value,observed_on,imported_at)
            VALUES (?,?,?,?,?,?,?,?)
            ON CONFLICT(project,business_id,sku,source,metric,observed_on)
            DO UPDATE SET value=excluded.value, imported_at=excluded.imported_at
        """, item)
        changed += 1
    return {"changed": changed, "unchanged": len(entries) - changed}


def _save_policy(conn: sqlite3.Connection, project: str, shop: sqlite3.Row, body: Mapping[str, Any]) -> None:
    _owner(body)
    values = tuple(_text(body.get(k), f"{k} policy", 1200) for k in ("shipping", "returns", "contact"))
    conn.execute("""
        INSERT INTO commerce_support_policy(project,business_id,shipping,returns,contact,approved_at)
        VALUES(?,?,?,?,?,?)
        ON CONFLICT(project,business_id) DO UPDATE SET
          shipping=excluded.shipping,returns=excluded.returns,contact=excluded.contact,
          approved_at=excluded.approved_at
    """, (project, shop["id"], *values, _now()))


def _economics(row: sqlite3.Row) -> dict[str, Any]:
    price = int(row["price_cents"])
    # These are hypothetical reserves, NOT the store's actual fees or real profit.
    processing = int((Decimal(price) * Decimal("0.029") + Decimal("30")).quantize(Decimal("1")))
    returns_reserve = int((Decimal(price) * Decimal("0.05")).quantize(Decimal("1")))
    contribution = price - row["unit_cents"] - row["shipping_cents"] - processing - returns_reserve
    fraction = round(contribution / price, 4)
    blockers = []
    if row["stock"] == 0:
        blockers.append("No supplier-reported stock")
    if not row["returns_supported"]:
        blockers.append("Supplier return support not confirmed")
    if not row["sample_reviewed"]:
        blockers.append("Physical sample not reviewed")
    if row["delivery_days"] > 14:
        blockers.append("Estimated delivery exceeds 14 days")
    if contribution <= 0 or fraction < 0.20:
        blockers.append("Estimated contribution before ads is below 20% of selling price")
    if any(term in row["category"].lower() for term in SENSITIVE_CATEGORIES):
        blockers.append("Regulated or sensitive product category requires specialist compliance review")
    if (datetime.now(timezone.utc) - datetime.fromisoformat(row["observed_at"])).days > 30:
        blockers.append("Supplier offer older than 30 days; refresh stock, price and shipping")
    return {
        "sku": row["sku"], "supplier": row["supplier"], "title": row["title"],
        "category": row["category"], "url": row["product_url"],
        "unit_cost_cents": row["unit_cents"], "shipping_cents": row["shipping_cents"],
        "price_cents": price, "stock": row["stock"], "delivery_days": row["delivery_days"],
        "contribution_before_ads_cents": contribution,
        "estimated_contribution_ratio": fraction,
        "hypothetical_fee_cents": processing,
        "hypothetical_returns_reserve_cents": returns_reserve,
        "break_even_cpa_cents": max(0, contribution),
        "break_even_roas": round(price / contribution, 2) if contribution > 0 else None,
        "status": "cost_preflight_candidate" if not blockers else "needs_evidence",
        "blockers": blockers, "source_label": row["source_label"], "observed_at": row["observed_at"],
    }


def _draft(message: Any, policy: sqlite3.Row | None) -> dict[str, Any]:
    raw = _text(message, "Customer inquiry", 2500)
    lower = raw.lower()
    if any(t in lower for t in ("chargeback", "attorney", "lawsuit", "fraud", "police", "bank dispute")):
        intent = "urgent_dispute"
        reply = "Thank you for contacting us. We have escalated your concern for priority review. We will respond once the relevant transaction details have been verified."
    elif any(t in lower for t in ("refund", "return", "exchange", "broken", "damaged", "cancel")):
        intent = "return_or_refund"
        reply = ("Thank you for contacting us. We can review the available options for your purchase after securely verifying the order details."
                 + (f" Our published return policy states: {policy['returns']}" if policy else " We will confirm the current return policy before advising on a resolution."))
    elif any(t in lower for t in ("track", "where is", "delivered", "package", "shipping", "ship", "arrive", "late")):
        intent = "shipping_or_tracking"
        reply = ("Thank you for reaching out. We can check the latest verified tracking and delivery estimate for your order."
                 + (f" Our published shipping policy states: {policy['shipping']}" if policy else " We will first confirm the current shipping policy."))
    else:
        intent = "general_question"
        reply = ("Thanks for getting in touch. We would be happy to help."
                 + (f" You can contact our support team using: {policy['contact']}" if policy else " Our team will review your question and follow up with verified details."))
    return {
        "intent": intent, "draft": reply,
        "confidence": "rule_based_routing_not_model_confidence",
        "review_required": True, "auto_send_allowed": False, "mailbox_connected": False,
        "order_or_identity_verified": False,
        "note": "Unverified inquiry is not an order record. Nothing was emailed, refunded or changed.",
    }


def _snapshot(conn: sqlite3.Connection, project: str, shop: sqlite3.Row) -> dict[str, Any]:
    records = conn.execute(
        """SELECT * FROM commerce_supplier_offers WHERE project=? AND business_id=?
           ORDER BY observed_at DESC,supplier,sku LIMIT ?""",
        (project, shop["id"], MAX_OFFERS),
    ).fetchall()
    offers = [_economics(row) for row in records]
    signal_rows = conn.execute(
        """SELECT sku,source,metric,value,observed_on FROM commerce_demand_signals
           WHERE project=? AND business_id=? ORDER BY observed_on DESC LIMIT 60""",
        (project, shop["id"]),
    ).fetchall()
    policy = conn.execute(
        "SELECT shipping,returns,contact,approved_at FROM commerce_support_policy WHERE project=? AND business_id=?",
        (project, shop["id"]),
    ).fetchone()
    return {
        "project": project, "business_id": shop["id"], "business_name": shop["name"],
        "mode": "local_analysis_only", "marketplace_connected": False,
        "supplier_connected": False, "ads_connected": False, "gmail_connected": False,
        "live_sales_connected": False, "live_spending_enabled": False,
        "metrics_origin": "owner_supplied_unverified_supplier_and_demand_inputs",
        "catalog_total": len(offers),
        "cost_preflight_candidates": sum(o["status"] == "cost_preflight_candidate" for o in offers),
        "offers": offers,
        "signals": [dict(row) for row in signal_rows],
        "policy": dict(policy) if policy else None,
        "marketing": [
            {"channel": "Google Merchant Center", "route": "Free product listings", "state": "not_connected"},
            {"channel": "Google Ads", "route": "Search and Shopping campaigns", "state": "not_connected"},
            {"channel": "Meta", "route": "Facebook and Instagram", "state": "not_connected"},
            {"channel": "TikTok", "route": "Organic creator content and approved ads", "state": "not_connected"},
            {"channel": "Pinterest", "route": "Product Pins and shopping discovery", "state": "not_connected"},
        ],
        "fee_assumption": "2.9% + 0.30 transaction estimate, 5% returns reserve, excluding sales tax, overhead and ad spend",
        "workflow": "Import authorized offers → automatic deterministic cost/risk preflight → review supplier proof → approval → later official account integration",
        "external_actions_performed": False,
    }


def handle_dropship(conn: sqlite3.Connection, project: str, action: str, body: Mapping[str, Any]) -> dict[str, Any]:
    """Run isolated, bounded local analyses; never network or send."""
    if action not in DROPSHIP_ACTIONS:
        raise PermissionError("Unsupported dropshipping action")
    shop = _shop(conn, project, body)
    result: dict[str, Any] = {}
    if action == "commerceDropshipImportOffers":
        result["import_result"] = _import_offers(conn, project, shop, body)
    elif action == "commerceDropshipImportSignals":
        result["import_result"] = _import_signals(conn, project, shop, body)
    elif action == "commerceDropshipSavePolicy":
        _save_policy(conn, project, shop, body)
    elif action == "commerceDropshipDraftReply":
        policy = conn.execute(
            "SELECT * FROM commerce_support_policy WHERE project=? AND business_id=?",
            (project, shop["id"]),
        ).fetchone()
        result["support_draft"] = _draft(body.get("message"), policy)
    return {**_snapshot(conn, project, shop), **result}
