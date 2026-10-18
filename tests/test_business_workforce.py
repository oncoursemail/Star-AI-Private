"""Hermetic regression tests; never call a real marketplace or AI provider."""
import hashlib
import json
from pathlib import Path
import sqlite3
import threading
import urllib.error
import urllib.request

import pytest

from star.business.console import create_handler
from star.business.workforce import (artifact_path, init_db, queue_pipeline,
    record_expense, review_offer, run_all, run_next, snapshot, verify_asset)


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.delenv("STAR_COMMERCE_LLM_URL",raising=False)
    conn=init_db(tmp_path / "commerce.db")
    yield conn
    conn.close()


def test_initial_state_has_zero_revenue_and_three_businesses(db):
    state=snapshot(db)
    assert state["mode"]=="local_draft_only"
    assert state["marketplaces_connected"]==0
    assert state["verified_orders"]==0
    assert state["verified_gross_cents"]==0
    assert state["cleared_payouts_cents"]==0
    assert len(state["businesses"])==3
    assert len(state["offers"])==3
    assert not state["jobs"]


def test_real_digital_asset_pipeline_and_qa(db):
    jobs=queue_pipeline(db,"hud-kit")
    assert len(jobs)==3
    steps=run_all(db)
    assert [x["step"] for x in steps]==["produce","listing","qa"]
    assert all(x["state"]=="completed" for x in steps)
    state=snapshot(db)
    offer=next(o for o in state["offers"] if o["id"]=="hud-kit")
    assert offer["state"]=="awaiting_owner_review"
    assert offer["artifact_ready"] is True
    assert offer["qa"]["checks"]=="passed_mechanical_tests"
    assert offer["qa"]["commercial_ready"] is False
    assert "approved" in offer["listing"] and not offer["listing"]["approved"]
    file=artifact_path(db,"hud-kit")
    assert file.suffix==".zip"
    assert len(file.read_bytes())>1000
    assert offer["qa"]["sha256"]==hashlib.sha256(file.read_bytes()).hexdigest()


def test_service_creates_draft_not_fake_delivered_work(db):
    queue_pipeline(db,"thumbnail-service")
    run_all(db)
    offer=next(o for o in snapshot(db)["offers"] if o["id"]=="thumbnail-service")
    assert offer["state"]=="awaiting_owner_review"
    assert offer["qa"]["buyer_customization_review"] is False
    assert "buyer" in offer["listing"]["description"].lower()


def test_no_double_queue_and_unknown_offer(db):
    queue_pipeline(db,"hud-kit")
    with pytest.raises(ValueError,match="active pipeline"):
        queue_pipeline(db,"hud-kit")
    with pytest.raises(ValueError,match="Unknown offer"):
        queue_pipeline(db,"not-an-offer")


def test_stages_run_in_order(db):
    queue_pipeline(db,"hud-kit")
    assert run_next(db)["step"]=="produce"
    assert run_next(db)["step"]=="listing"
    assert run_next(db)["step"]=="qa"
    assert run_next(db) is None


def test_repeat_run_does_not_replay_old_jobs(db):
    queue_pipeline(db,"hud-kit")
    run_all(db)
    queue_pipeline(db,"hud-kit")
    assert len(run_all(db))==3
    assert db.execute("SELECT COUNT(*) FROM job WHERE state='completed'").fetchone()[0]==6


def test_human_review_requires_explicit_evidence(db):
    with pytest.raises(ValueError,match="not ready"):
        review_offer(db,"hud-kit","rights checked")
    queue_pipeline(db,"hud-kit");run_all(db)
    for evidence in (""," ","X"*301):
        with pytest.raises(ValueError): review_offer(db,"hud-kit",evidence)
    review_offer(db,"hud-kit","Reviewed SVG assets against internal requirements; original handmade geometries.")
    offer=next(o for o in snapshot(db)["offers"] if o["id"]=="hud-kit")
    assert offer["state"]=="internally_approved"
    assert snapshot(db)["verified_orders"]==0


def test_checksum_tamper_blocks_integrity(db):
    queue_pipeline(db,"hud-kit")
    assert run_next(db)["state"]=="completed"
    path=artifact_path(db,"hud-kit")
    path.write_bytes(path.read_bytes()+b"modified")
    row=dict(db.execute("SELECT * FROM offer WHERE id='hud-kit'").fetchone())
    with pytest.raises(ValueError,match="checksum mismatch"):
        verify_asset(db,row)
    assert run_all(db)[-1]["state"]=="failed"
    assert next(o for o in snapshot(db)["offers"] if o["id"]=="hud-kit")["state"]=="blocked"


def test_cost_validation_and_separate_from_sales(db):
    with pytest.raises(ValueError):record_expense(db,"creator-assets","Hosting",True)
    with pytest.raises(ValueError):record_expense(db,"creator-assets","Hosting",-1)
    with pytest.raises(ValueError):record_expense(db,"invalid","Hosting",300)
    record_expense(db,"creator-assets","Hosting",1299,"October host")
    state=snapshot(db)
    assert state["owner_entered_expenses_cents"]==1299
    assert state["verified_gross_cents"]==0


def test_no_webhook_sales_or_publish_code_paths(db):
    state=snapshot(db)
    assert not any(k in state for k in ("bank","customer","stripe_key"))
    from star.business import console
    # Explicit permit list: queue, run, review, expense only.
    code=Path(console.__file__).read_text()
    assert 'route=="/api/publish"' not in code
    assert 'route=="/api/send"' not in code
    assert '"127.0.0.1"' in code


def test_invalid_local_model_endpoint_fails_safe(db, monkeypatch):
    monkeypatch.setenv("STAR_COMMERCE_LLM_URL","http://example.com/v1/chat/completions")
    queue_pipeline(db,"hud-kit")
    steps=run_all(db)
    assert steps[0]["state"]=="completed"
    assert steps[1]["state"]=="failed"
    assert db.execute("SELECT state FROM offer WHERE id='hud-kit'").fetchone()[0]=="blocked"
