"""STAR commerce pilot: bounded, opt-in local automation and business isolation."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import sqlite3

import pytest

from star.commerce.autopilot import run_due_pilot_checks
from star.commerce.dropshipping import OFFER_COLUMNS
from star.commerce.workspace import handle_commerce

HEADER = ",".join(OFFER_COLUMNS)


def call(home, action="commerceBoard", *, project="STAR", **body):
    return handle_commerce(action, body, project=project, home=home)


def shop(home, name="Commerce Store", *, project="STAR"):
    result = call(home, "commerceCreateBusiness", project=project, name=name,
                  channel="shopify", niche="Verified everyday accessories")
    return next(x for x in result["businesses"] if x["name"] == name)


def offer(*, sku="SKU-1", stock="2", sample="no", returns="no",
          delivery="21", unit="12.00", price="25.00", category="office organizer"):
    return ",".join((
        "Example Approved Supplier", sku, "Original desk shelf", category,
        "https://catalog.example/items/"+sku,
        unit, "3.00", price, stock, delivery, returns, sample,
    ))


def imported(home, business, *rows, project="STAR"):
    return call(home, "commerceDropshipImportOffers", project=project,
                business_id=business["id"], owner_confirmed=True,
                source_label="Authorized source catalog", csv_text=HEADER+"\n"+"\n".join(rows))


def config(home, business, *, project="STAR", enabled=True, **override):
    arguments = dict(
        business_id=business["id"], owner_confirmed=True, enabled=enabled,
        minimum_stock=3, minimum_margin_pct=25,
        maximum_delivery_days=14, stale_after_days=7, interval_minutes=60,
    )
    arguments.update(override)
    return call(home, "commercePilotConfigure", project=project, **arguments)


def pilot(home, business, *, project="STAR"):
    return call(home, "commercePilot", project=project, business_id=business["id"])


def scan(home, business, *, project="STAR"):
    return call(home, "commercePilotScan", project=project,
                business_id=business["id"], owner_confirmed=True)


def test_zero_state_is_disabled_and_has_no_external_access(tmp_path):
    b = shop(tmp_path)
    r = pilot(tmp_path, b)
    assert r["monitoring"]["enabled"] is False
    assert r["monitoring"]["last_run"] is None
    assert r["finding_counts"] == {"open": 0, "dismissed": 0, "resolved": 0}
    assert r["findings"] == []
    assert r["external_connectors_active"] is False
    assert r["automatic_supplier_refresh"] is False
    assert r["auto_send"] is False and r["auto_publish"] is False
    assert r["auto_spend"] is False and r["auto_fulfill"] is False
    assert run_due_pilot_checks(tmp_path, "STAR") == {
        "businesses_checked": 0, "new_review_findings": 0, "external_actions": 0,
    }


def test_configuration_owner_confirmation_and_strict_limits(tmp_path):
    b = shop(tmp_path)
    with pytest.raises(PermissionError, match="Owner confirmation"):
        call(tmp_path, "commercePilotConfigure", business_id=b["id"],
             enabled=True, minimum_stock=3, minimum_margin_pct=25,
             maximum_delivery_days=14, stale_after_days=7, interval_minutes=60)
    with pytest.raises(ValueError, match="minimum_margin_pct"):
        config(tmp_path, b, minimum_margin_pct=True)
    with pytest.raises(ValueError, match="interval_minutes"):
        config(tmp_path, b, interval_minutes=1)
    assert pilot(tmp_path, b)["monitoring"]["enabled"] is False
    result = config(tmp_path, b, enabled=True, minimum_margin_pct=31)
    assert result["monitoring"]["minimum_margin_pct"] == 31
    assert result["monitoring"]["enabled"] is True
    assert result["external_connectors_active"] is False
    assert config(tmp_path, b, enabled=False)["monitoring"]["enabled"] is False


def test_scan_checks_imported_supplier_data_creates_idempotent_reviews(tmp_path):
    b = shop(tmp_path)
    imported(tmp_path, b, offer())
    config(tmp_path, b)
    # Shops start paused: enabling the local policy never resumes the business.
    assert scan(tmp_path, b)["scan_result"]["state"] == "business_paused"
    call(tmp_path, "commercePauseBusiness", id=b["id"], paused=False)
    first = scan(tmp_path, b)
    assert first["scan_result"]["state"] == "local_only_completed"
    assert first["scan_result"]["scanned"] == 1
    assert first["scan_result"]["opened"] >= 4
    assert first["scan_result"]["external_actions"] == 0
    codes = {x["code"] for x in first["findings"]}
    assert {"stock_low", "shipping_slow", "returns_unknown", "sample_missing"}.issubset(codes)
    second = scan(tmp_path, b)
    assert second["scan_result"]["opened"] == 0
    assert len(second["findings"]) == len(first["findings"])
    assert second["monitoring"]["last_scanned"] == 1
    with sqlite3.connect(tmp_path/"commerce"/"workspace.sqlite3") as db:
        count = db.execute("SELECT COUNT(*) FROM commerce_pilot_audit").fetchone()[0]
        assert count == len(first["findings"]) + 1  # one configure event


def test_dismiss_same_evidence_stays_dismissed_new_evidence_reopens(tmp_path):
    b = shop(tmp_path)
    imported(tmp_path, b, offer(stock="2", sample="yes", returns="yes", delivery="8"))
    call(tmp_path, "commercePauseBusiness", id=b["id"], paused=False)
    scanned = scan(tmp_path, b)
    low = next(x for x in scanned["findings"] if x["code"] == "stock_low")
    with pytest.raises(PermissionError):
        call(tmp_path, "commercePilotDismiss", business_id=b["id"], id=low["id"])
    dismissed = call(tmp_path, "commercePilotDismiss", business_id=b["id"],
                     id=low["id"], owner_confirmed=True)
    assert dismissed["finding_counts"]["dismissed"] == 1
    same = scan(tmp_path, b)
    assert same["finding_counts"]["dismissed"] == 1
    # Vendor source update changes the evidence fingerprint but still has low stock.
    imported(tmp_path, b, offer(stock="1", sample="yes", returns="yes", delivery="8"))
    reopened = scan(tmp_path, b)
    assert reopened["scan_result"]["opened"] == 1
    assert reopened["finding_counts"]["open"] == 1
    assert reopened["findings"][0]["id"] == low["id"]
    # Once changed evidence clears stock risk, finding automatically resolves.
    imported(tmp_path, b, offer(stock="35", sample="yes", returns="yes", delivery="8"))
    cleared = scan(tmp_path, b)
    assert cleared["finding_counts"]["open"] == 0
    assert cleared["finding_counts"]["resolved"] == 1
    assert cleared["scan_result"]["closed"] == 1


def test_scheduled_checks_skip_undue_and_paused_businesses(tmp_path):
    b = shop(tmp_path)
    imported(tmp_path, b, offer(stock="0", sample="yes", returns="yes", delivery="8"))
    config(tmp_path, b)
    assert run_due_pilot_checks(tmp_path, "STAR")["businesses_checked"] == 0
    call(tmp_path, "commercePauseBusiness", id=b["id"], paused=False)
    first = run_due_pilot_checks(tmp_path, "STAR")
    assert first["businesses_checked"] == 1
    assert first["new_review_findings"] >= 1
    assert run_due_pilot_checks(tmp_path, "STAR")["businesses_checked"] == 0
    with sqlite3.connect(tmp_path/"commerce"/"workspace.sqlite3") as conn:
        old = (datetime.now(timezone.utc)-timedelta(days=2)).isoformat()
        conn.execute("UPDATE commerce_pilot_settings SET last_run=? WHERE business_id=?", (old, b["id"]))
        conn.commit()
    assert run_due_pilot_checks(tmp_path, "STAR")["businesses_checked"] == 1
    call(tmp_path, "commercePauseBusiness", id=b["id"], paused=True)
    with sqlite3.connect(tmp_path/"commerce"/"workspace.sqlite3") as conn:
        conn.execute("UPDATE commerce_pilot_settings SET last_run=NULL WHERE business_id=?", (b["id"],))
        conn.commit()
    assert run_due_pilot_checks(tmp_path, "STAR")["businesses_checked"] == 0


def test_business_project_permissions_and_missing_shop_refuse_writes(tmp_path):
    a = shop(tmp_path, name="Alpha")
    b = shop(tmp_path, name="Beta")
    imported(tmp_path, a, offer(stock="0", sample="yes", returns="yes", delivery="8"))
    call(tmp_path, "commercePauseBusiness", id=a["id"], paused=False)
    scan(tmp_path, a)
    assert pilot(tmp_path, b)["finding_counts"]["open"] == 0
    with pytest.raises(ValueError, match="current STAR project"):
        pilot(tmp_path, a, project="OTHER")
    with pytest.raises(ValueError, match="current STAR project"):
        config(tmp_path, a, project="OTHER")
    with pytest.raises(ValueError, match="Finding not found"):
        call(tmp_path, "commercePilotDismiss", business_id=b["id"],
             id=pilot(tmp_path, a)["findings"][0]["id"], owner_confirmed=True)


def test_stale_vendor_information_is_flagged_and_product_topic_is_not(tmp_path):
    b = shop(tmp_path)
    imported(tmp_path, b, offer(stock="15", sample="yes", returns="yes", delivery="8"),
             offer(sku="SKU-2", stock="15", sample="yes", returns="yes", delivery="8",
                   category="baby supplement alcohol"))
    call(tmp_path, "commercePauseBusiness", id=b["id"], paused=False)
    with sqlite3.connect(tmp_path/"commerce"/"workspace.sqlite3") as conn:
        conn.execute("UPDATE commerce_supplier_offers SET observed_at=? WHERE business_id=?",
                     ((datetime.now(timezone.utc)-timedelta(days=40)).isoformat(), b["id"]))
        conn.commit()
    config(tmp_path, b)
    flagged = scan(tmp_path, b)
    assert {f["code"] for f in flagged["findings"]} == {"supplier_stale"}  # topic words raise nothing
    # No fake merchant connection/status/financial activity is ever created.
    assert flagged["auto_spend"] is False
    assert flagged["auto_fulfill"] is False
