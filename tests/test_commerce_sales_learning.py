"""STAR local real-world sales learning: strict daily aggregate import and safe hypotheses."""
from __future__ import annotations

import calendar
from datetime import date, timedelta
import sqlite3

import pytest

from star.commerce.sales_learning import (
    CSV_COLUMNS, SHOPIFY_SESSIONS_BREAK, _hypothesis, _parse_daily_csv,
    learning_report,
)
from star.commerce.workspace import handle_commerce


HEADER = ",".join(CSV_COLUMNS)


def run(home, action="commerceBoard", *, project="STAR", **data):
    return handle_commerce(action, data, project=project, home=home)


def business(home, name="A creator shop", channel="etsy", *, project="STAR"):
    return run(home, "commerceCreateBusiness", project=project, name=name, channel=channel,
               niche="Legally original small creator asset packs")["businesses"][0]


def row(day="2026-09-01", sessions="120", orders="8",
        gross="80.00", refunds="0.00", fees="12.00", production="2.00", ads="4.00"):
    return ",".join([day, sessions, orders, gross, refunds, fees, production, ads])


def owner_import(home, shop, daily_rows, *, project="STAR", **extra):
    options = dict(
        business_id=shop["id"], owner_confirmed=True, currency="USD",
        report_timezone="America/Chicago",
        source_label="Owner-reconciled daily totals",
        csv_text=HEADER + "\n" + "\n".join(daily_rows),
    )
    options.update(extra)
    return run(home, "commerceImportDailyMetrics", project=project, **options)


def test_empty_real_world_learning_never_fabricates_revenue(tmp_path):
    shop = business(tmp_path)
    data = run(tmp_path, "commerceLearning", business_id=shop["id"])
    assert data["imported_daily_rows"] == 0
    assert data["has_live_feed"] is False
    assert data["verified_revenue_cents"] is None
    assert data["last_365_days"]["net_contribution_cents"] is None
    assert data["signal"]["status"] == "insufficient_evidence"
    assert data["signal"]["auto_apply"] is False
    assert all(w["orders"] == 0 for w in data["time_of_month"])


def test_import_requires_explicit_permission_and_preserves_private_project_scope(tmp_path):
    shop = business(tmp_path)
    with pytest.raises(PermissionError, match="Explicitly confirm"):
        owner_import(tmp_path, shop, [row()], owner_confirmed=False)
    assert run(tmp_path, "commerceLearning", business_id=shop["id"])["imported_daily_rows"] == 0
    with pytest.raises(ValueError, match="current STAR project"):
        owner_import(tmp_path, shop, [row()], project="OTHER")
    assert run(tmp_path, "commerceLearning", business_id=shop["id"])["imported_daily_rows"] == 0


def test_safe_daily_import_and_idempotent_second_call(tmp_path):
    shop = business(tmp_path)
    figures = [row("2026-09-01", "120", "8"), row("2026-09-02", "0", "0", "0.00", "0.00", "0.00", "0.00", "0.00")]
    done = owner_import(tmp_path, shop, figures)
    assert done["import_status"] == "owner_aggregate_imported"
    assert done["added"] == 2 and done["replaced"] == 0
    assert done["imported_daily_rows"] == 2
    assert done["last_365_days"]["orders"] == 8
    assert done["last_365_days"]["sessions"] == 120
    assert done["last_365_days"]["net_contribution_cents"] == 6200
    assert done["verified_revenue_cents"] is None
    second = owner_import(tmp_path, shop, figures)
    assert second["import_status"] == "identical_no_changes"
    assert second["imported_daily_rows"] == 2
    with sqlite3.connect(tmp_path / "commerce" / "workspace.sqlite3") as db:
        assert db.execute("SELECT count(*) FROM commerce_daily_metrics").fetchone()[0] == 2
        assert db.execute("SELECT count(*) FROM commerce_metric_imports").fetchone()[0] == 1
        stored = db.execute("SELECT source_label FROM commerce_daily_metrics").fetchone()[0]
        assert "Owner-reconciled" in stored


def test_missing_financial_data_is_never_interpreted_as_zero_profit(tmp_path):
    shop = business(tmp_path)
    metrics = owner_import(tmp_path, shop, [
        row("2026-09-01", "300", "7", "70.00", "", "", "", ""),
        row("2026-09-02", "", "4", "", "", "", "", ""),
    ])
    assert metrics["last_365_days"]["orders"] == 11
    assert metrics["last_365_days"]["sessions"] is None
    assert metrics["last_365_days"]["net_contribution_cents"] is None
    assert metrics["time_of_month"][0]["orders_per_100_sessions"] is None
    assert metrics["signal"]["status"] == "insufficient_evidence"


def test_zero_session_day_with_orders_suppresses_comparable_rate(tmp_path):
    shop = business(tmp_path)
    figures = owner_import(tmp_path, shop, [
        row("2026-09-01", "0", "3", "30.00", "0.00", "0.00", "0.00", "0.00"),
        row("2026-09-02", "100", "4", "40.00", "0.00", "0.00", "0.00", "0.00"),
    ])
    assert figures["last_365_days"]["orders"] == 7
    assert figures["last_365_days"]["sessions"] == 100
    assert figures["last_365_days"]["orders_per_100_sessions"] is None
    assert figures["time_of_month"][0]["orders_per_100_sessions"] is None
    assert figures["signal"]["auto_apply"] is False


def test_conflicting_daily_date_needs_explicit_replace_and_import_is_atomic(tmp_path):
    shop = business(tmp_path)
    owner_import(tmp_path, shop, [row()])
    revised = [row("2026-09-01", orders="10"), row("2026-09-03", orders="3")]
    with pytest.raises(ValueError, match="Replace existing"):
        owner_import(tmp_path, shop, revised)
    assert run(tmp_path, "commerceLearning", business_id=shop["id"])["imported_daily_rows"] == 1
    updated = owner_import(tmp_path, shop, revised, replace_existing=True)
    assert updated["added"] == 1 and updated["replaced"] == 1
    assert updated["last_365_days"]["orders"] == 13
    assert updated["last_365_days"]["net_contribution_cents"] is not None


def test_shop_currency_and_reporting_timezone_cannot_be_silently_mixed(tmp_path):
    shop = business(tmp_path)
    owner_import(tmp_path, shop, [row()])
    with pytest.raises(ValueError, match="currencies or shop"):
        owner_import(tmp_path, shop, [row("2026-09-03")], currency="EUR")
    with pytest.raises(ValueError, match="currencies or shop"):
        owner_import(tmp_path, shop, [row("2026-09-03")], report_timezone="UTC")
    assert run(tmp_path, "commerceLearning", business_id=shop["id"])["imported_daily_rows"] == 1


@pytest.mark.parametrize("text,reason", [
    ("", "daily aggregate"),
    ("wrong,columns\n1,2", "columns must exactly"),
    (HEADER+"\n2026-09-01,3,2,2.00,0.00,0.00,0.00,0.00,PERSONAL_EMAIL@example.org", "Extra columns"),
    (HEADER+"\n"+row()+"\n"+row(), "Every date"),
    (HEADER+"\n"+row("2026-02-30"), "Invalid calendar"),
    (HEADER+"\n"+row("2999-01-01"), "historical reporting range"),
    (HEADER+"\n"+row("2026-09-01", sessions="-9"), "nonnegative whole"),
    (HEADER+"\n"+row("2026-09-01", orders="3.2"), "nonnegative whole"),
    (HEADER+"\n"+row("2026-09-01", gross="=SUM(A1:B2)"), "nonnegative amount"),
    (HEADER+"\n"+row("2026-09-01", fees="1.999"), "nonnegative amount"),
    (HEADER+"\n"+row("2026-09-01", ads="4."), "nonnegative amount"),
    (HEADER+"\n"+row().rsplit(",", 1)[0], "Missing CSV field"),
])
def test_refuses_invalid_or_customer_level_csv(text, reason):
    with pytest.raises(ValueError, match=reason):
        _parse_daily_csv(text, date(2026, 10, 18))


def test_calendar_includes_month_end_and_leap_day():
    assert _parse_daily_csv(HEADER+"\n"+row("2024-02-29"), date(2026, 10, 18))[0]["report_date"] == "2024-02-29"
    with pytest.raises(ValueError):
        _parse_daily_csv(HEADER+"\n"+row("2025-02-29"), date(2026, 10, 18))


def test_blank_session_denominator_never_produces_a_false_conversion_signal():
    early = [
        {"report_date": (date(2026, 1, 1)+timedelta(days=k)).isoformat(),
         "sessions": None, "orders": 100} for k in range(160)
    ]
    signal = _hypothesis(early, shopify_break=False)
    assert signal["status"] == "insufficient_evidence"
    assert signal["recommendation"] is None


def test_month_thirds_historical_pattern_must_repeat_out_of_sample(tmp_path):
    shop = business(tmp_path)
    samples = []
    first = date(2026, 3, 1)
    days = sum(calendar.monthrange(2026, month)[1] for month in range(3, 9))
    for offset in range(days):
        day = first + timedelta(days=offset)
        n = 24 if day.day <= 10 else 5
        samples.append(row(day.isoformat(), "100", str(n), gross="", refunds="", fees="", production="", ads=""))
    assert len(samples) <= 200
    outcome = owner_import(tmp_path, shop, samples)
    assert outcome["last_365_days"]["orders"] > 50
    assert outcome["signal"]["status"] == "candidate_for_controlled_experiment"
    assert outcome["signal"]["window"] == "early"
    assert "controlled" not in (outcome["signal"]["recommendation"] or "").lower() or outcome["signal"]["auto_apply"] is False
    assert outcome["verified_revenue_cents"] is None


def test_only_session_measurement_break_blocks_shopify_cross_period_inference(tmp_path):
    shop = business(tmp_path, "Shopify owner", "shopify")
    samples = [
        row((date(2026, 8, 1)+timedelta(days=i)).isoformat(),
            "110", "9", gross="", refunds="", fees="", production="", ads="")
        for i in range(78)
    ]
    outcome = owner_import(tmp_path, shop, samples)
    assert outcome["shopify_measurement_break"] is True
    assert outcome["signal"]["status"] == "insufficient_evidence"
    assert "September 2026" in outcome["signal"]["reason"]


def test_manual_import_never_grants_platform_writes_or_verified_revenue(tmp_path):
    shop = business(tmp_path)
    outcome = owner_import(tmp_path, shop, [row()])
    assert outcome["has_live_feed"] is False and outcome["verified_revenue_cents"] is None
    from star.react_shell import ALLOWED_ACTIONS
    assert "commerceLearning" in ALLOWED_ACTIONS
    assert "commerceImportDailyMetrics" in ALLOWED_ACTIONS
    for disallowed in ("commercePublish", "commerceBuyAds", "commerceSetPrice",
                       "commerceAutoFulfill", "commerceModelTrainOnCustomers"):
        assert disallowed not in ALLOWED_ACTIONS
