"""Offline regression and safety tests for STAR Business dropshipping planning."""
from __future__ import annotations

import sqlite3

import pytest

from star.commerce.dropshipping import OFFER_COLUMNS, SIGNAL_COLUMNS
from star.commerce.workspace import handle_commerce

HEADER = ",".join(OFFER_COLUMNS)
SIGNAL_HEADER = ",".join(SIGNAL_COLUMNS)


def call(home, action="commerceBoard", *, project="STAR", **body):
    return handle_commerce(action, body, project=project, home=home)


def make_shop(home, *, project="STAR", name="Test Shopify Shop"):
    return call(home, "commerceCreateBusiness", project=project,
                name=name, channel="shopify", niche="Original practical accessories")["businesses"][0]


def offer(*, sku="sku-1", price="35.00", stock="15", sample="yes", returns="yes",
          delivery="8", category="desk organizer", supplier="Verified Supplier",
          unit="10.00", shipping="4.00", url="https://supplier.example/products/1"):
    return ",".join([supplier, sku, "Desk organizer", category, url, unit, shipping,
                     price, stock, delivery, returns, sample])


def import_offers(home, shop, records, *, project="STAR", **extra):
    body = dict(business_id=shop["id"], source_label="Authorized supplier sheet",
                owner_confirmed=True, csv_text=HEADER + "\n" + "\n".join(records))
    body.update(extra)
    return call(home, "commerceDropshipImportOffers", project=project, **body)


def test_empty_workspace_never_invents_sales_or_connections(tmp_path):
    shop = make_shop(tmp_path)
    board = call(tmp_path, "commerceDropship", business_id=shop["id"])
    assert board["catalog_total"] == 0
    assert board["cost_preflight_candidates"] == 0
    assert board["offers"] == []
    assert board["signals"] == []
    assert board["mode"] == "local_analysis_only"
    assert board["marketplace_connected"] is False
    assert board["gmail_connected"] is False
    assert board["live_spending_enabled"] is False
    assert board["external_actions_performed"] is False
    assert len(board["marketing"]) == 5
    assert all(channel["state"] == "not_connected" for channel in board["marketing"])


def test_supplier_import_confirmation_atomicity_and_no_duplicate_churn(tmp_path):
    shop = make_shop(tmp_path)
    with pytest.raises(PermissionError, match="Owner must confirm"):
        import_offers(tmp_path, shop, [offer()], owner_confirmed=False)
    with pytest.raises(ValueError, match="Target price"):
        import_offers(tmp_path, shop, [offer(), offer(sku="sku-2", price="bad")])
    assert call(tmp_path, "commerceDropship", business_id=shop["id"])["catalog_total"] == 0
    result = import_offers(tmp_path, shop, [offer()])
    assert result["import_result"] == {"added": 1, "updated": 0, "unchanged": 0}
    result = import_offers(tmp_path, shop, [offer()])
    assert result["import_result"] == {"added": 0, "updated": 0, "unchanged": 1}
    assert result["catalog_total"] == 1
    updated = import_offers(tmp_path, shop, [offer(price="39.00")])
    assert updated["import_result"]["updated"] == 1
    assert updated["offers"][0]["price_cents"] == 3900


def test_margin_and_break_even_are_labeled_model_based_not_profits(tmp_path):
    shop = make_shop(tmp_path)
    board = import_offers(tmp_path, shop, [offer()])
    item = board["offers"][0]
    # $35 less $10 product, $4 ship, ($1.02+$0.30) processing,
    # and a hypothetical $1.75 returns reserve.
    assert item["hypothetical_fee_cents"] == 132
    assert item["hypothetical_returns_reserve_cents"] == 175
    assert item["contribution_before_ads_cents"] == 1968
    assert item["break_even_cpa_cents"] == 1968
    assert item["break_even_roas"] == round(3500 / 1968, 2)
    assert item["status"] == "cost_preflight_candidate"
    assert board["live_sales_connected"] is False


def test_bad_supplier_quality_blocks_shortlisting(tmp_path):
    shop = make_shop(tmp_path)
    rows = [
        offer(sku="cheap", price="12.00", returns="no", sample="no"),
        offer(sku="slow", delivery="45"),
        offer(sku="sensitive", category="baby medical devices"),
        offer(sku="empty", stock="0"),
    ]
    board = import_offers(tmp_path, shop, rows)
    assert board["catalog_total"] == 4
    assert board["cost_preflight_candidates"] == 0
    flagged = {o["sku"]: o for o in board["offers"]}
    assert "Supplier return support not confirmed" in flagged["cheap"]["blockers"]
    assert any("contribution" in reason for reason in flagged["cheap"]["blockers"])
    assert any("delivery" in reason.lower() for reason in flagged["slow"]["blockers"])
    assert any("sensitive" in reason for reason in flagged["sensitive"]["blockers"])
    assert any("stock" in reason.lower() for reason in flagged["empty"]["blockers"])


def test_products_are_isolated_by_project_and_business(tmp_path):
    first = make_shop(tmp_path, name="Shop Alpha")
    other = make_shop(tmp_path, name="Shop Beta")
    import_offers(tmp_path, first, [offer()])
    assert call(tmp_path, "commerceDropship", business_id=other["id"])["catalog_total"] == 0
    with pytest.raises(ValueError, match="current STAR project"):
        call(tmp_path, "commerceDropship", project="OTHER", business_id=first["id"])
    etsy = call(tmp_path, "commerceCreateBusiness", name="Non Shopify", channel="etsy",
                niche="Original assets")["businesses"]
    other_platform = next(x for x in etsy if x["channel"] == "etsy")
    with pytest.raises(ValueError, match="Shopify business"):
        call(tmp_path, "commerceDropship", business_id=other_platform["id"])


def test_rejects_malformed_prices_duplicates_and_non_https_urls(tmp_path):
    shop = make_shop(tmp_path)
    with pytest.raises(ValueError, match="Duplicate supplier and SKU"):
        import_offers(tmp_path, shop, [offer(), offer()])
    with pytest.raises(ValueError, match="public HTTPS"):
        import_offers(tmp_path, shop, [offer(url="http://example.com/product")])
    with pytest.raises(ValueError, match="formula"):
        import_offers(tmp_path, shop, [offer(supplier="=IMPORTXML")])
    assert call(tmp_path, "commerceDropship", business_id=shop["id"])["catalog_total"] == 0


def test_demand_signal_is_research_not_verified_orders(tmp_path):
    shop = make_shop(tmp_path)
    import_offers(tmp_path, shop, [offer()])
    body = dict(business_id=shop["id"], owner_confirmed=True, csv_text=SIGNAL_HEADER +
                "\nsku-1,google_trends,trends_index,63,2026-10-15" +
                "\nsku-1,google_ads_keyword_planner,monthly_searches,900,2026-10-15")
    board = call(tmp_path, "commerceDropshipImportSignals", **body)
    assert board["import_result"]["changed"] == 2
    assert {r["metric"] for r in board["signals"]} == {"trends_index", "monthly_searches"}
    assert board["live_sales_connected"] is False
    same = call(tmp_path, "commerceDropshipImportSignals", **body)
    assert same["import_result"]["changed"] == 0
    with pytest.raises(ValueError, match="do not match"):
        call(tmp_path, "commerceDropshipImportSignals", business_id=shop["id"],
             owner_confirmed=True, csv_text=SIGNAL_HEADER +
             "\nsku-1,google_trends,merchant_clicks,90,2026-10-15")
    with pytest.raises(ValueError, match="unknown supplier SKU"):
        call(tmp_path, "commerceDropshipImportSignals", business_id=shop["id"],
             owner_confirmed=True, csv_text=SIGNAL_HEADER +
             "\nunknown,google_trends,trends_index,90,2026-10-15")


def test_support_drafts_are_policy_grounded_never_sent_or_stored(tmp_path):
    shop = make_shop(tmp_path)
    with pytest.raises(PermissionError):
        call(tmp_path, "commerceDropshipSavePolicy", business_id=shop["id"],
             shipping="5 business days", returns="14 days after delivery", contact="help center")
    call(tmp_path, "commerceDropshipSavePolicy", business_id=shop["id"],
         owner_confirmed=True, shipping="5 business days",
         returns="14 days after delivery", contact="support center")
    answer = call(tmp_path, "commerceDropshipDraftReply", business_id=shop["id"],
                  message="Where is my order? My private note reference is abcXYZ")
    draft = answer["support_draft"]
    assert draft["intent"] == "shipping_or_tracking"
    assert draft["auto_send_allowed"] is False
    assert draft["review_required"] is True
    assert draft["order_or_identity_verified"] is False
    assert "5 business days" in draft["draft"]
    assert "abcXYZ" not in draft["draft"]
    dispute = call(tmp_path, "commerceDropshipDraftReply", business_id=shop["id"],
                   message="I have started a chargeback")
    assert dispute["support_draft"]["intent"] == "urgent_dispute"
    assert dispute["support_draft"]["mailbox_connected"] is False
    with sqlite3.connect(tmp_path / "commerce" / "workspace.sqlite3") as db:
        tables = ("commerce_supplier_offers", "commerce_demand_signals", "commerce_support_policy")
        joined = " ".join(str(db.execute(f"SELECT * FROM {table}").fetchall()) for table in tables)
        assert "abcXYZ" not in joined
        assert "chargeback" not in joined


def test_validation_limits_prevent_unbounded_catalog_work(tmp_path):
    shop = make_shop(tmp_path)
    many = [offer(sku=f"sku-{i}") for i in range(151)]
    with pytest.raises(ValueError, match="between 1 and 150"):
        import_offers(tmp_path, shop, many)
    assert call(tmp_path, "commerceDropship", business_id=shop["id"])["catalog_total"] == 0
