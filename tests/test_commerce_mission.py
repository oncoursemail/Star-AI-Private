"""Integration tests for local Business Mission Control (no outside account needed)."""
from __future__ import annotations

import sqlite3
import uuid

import pytest

from star.commerce.workspace import handle_commerce


def request(home, action="commerceBoard", project="STAR", **kwargs):
    return handle_commerce(action, kwargs, project=project, home=home)


def make_business(home, name="Studio North", channel="etsy", project="STAR"):
    board = request(home, "commerceCreateBusiness", project=project, name=name,
                    channel=channel, niche="Original tools for independent creators")
    return next(b for b in board["businesses"] if b["name"] == name)


def make_candidate(home, business, title="Creator Kit", project="STAR"):
    board = request(home, "commerceCreate", project=project, channel=business["channel"],
                    title=title, concept="Editable original designs for a defined buyer need",
                    business_id=business["id"])
    return next(i for i in board["ideas"] if i["title"] == title)


def review_evidence(home, idea, project="STAR"):
    return request(
        home, "commerceEvidence", project=project, id=idea["id"],
        evidence={
            "rights_evidence": "The owner manually checked the source licenses and source files",
            "visual_qa_evidence": "The owner inspected thumbnails and all exported files",
            "ai_disclosed": True,
            "accurate_mockup_reviewed": True,
        },
    )


def test_mission_zero_state(tmp_path):
    board = request(tmp_path)
    assert board["businesses"] == []
    assert board["preflight_jobs"] == []
    assert board["recent_activity"] == []
    assert board["job_counts"]["queued"] == 0
    assert board["mission_control"]["auto_start"] is False
    assert board["mission_control"]["marketplace_write_access"] is False
    assert board["mission_control"]["real_sales_feed"] is False
    assert board["counts"]["verified_sales"] is None


def test_businesses_created_paused_and_name_deduplicated(tmp_path):
    b = make_business(tmp_path)
    assert b["paused"] is True
    assert b["candidate_count"] == 0
    assert b["channel"] == "etsy"
    with pytest.raises(ValueError, match="already exists"):
        make_business(tmp_path, name="studio north")
    assert len(request(tmp_path)["businesses"]) == 1


def test_100_record_capacity_is_enforced_without_inventing_connected_shops(tmp_path):
    for n in range(100):
        make_business(tmp_path, name=f"Brand {n:03d}")
    board = request(tmp_path)
    assert len(board["businesses"]) == 100
    assert all(b["paused"] for b in board["businesses"])
    assert board["mission_control"]["maximum_businesses"] == 100
    with pytest.raises(ValueError, match="capacity"):
        make_business(tmp_path, name="Brand 101")


def test_candidate_assignment_and_channel_guard(tmp_path):
    etsy = make_business(tmp_path, "Etsy Studio")
    fiverr = make_business(tmp_path, "Fiverr Studio", "fiverr")
    idea = make_candidate(tmp_path, etsy)
    assert idea["business_id"] == etsy["id"]
    with pytest.raises(ValueError, match="marketplace"):
        request(tmp_path, "commerceAssignBusiness", idea_id=idea["id"], business_id=fiverr["id"])
    assert request(tmp_path)["ideas"][0]["business_id"] == etsy["id"]
    free = request(tmp_path, "commerceCreate", title="Unassigned", concept="An original concept",
                   channel="etsy")["ideas"][0]
    assert free["business_id"] is None
    linked = request(tmp_path, "commerceAssignBusiness", business_id=etsy["id"], idea_id=free["id"])
    assert any(i["id"] == free["id"] and i["business_id"] == etsy["id"] for i in linked["ideas"])


def test_paused_shop_does_not_run_checks_and_resume_is_explicit(tmp_path):
    shop = make_business(tmp_path)
    idea = make_candidate(tmp_path, shop)
    board = request(tmp_path, "commerceQueuePreflight", idea_id=idea["id"])
    assert board["job_counts"]["queued"] == 1
    assert request(tmp_path, "commerceRunPreflight", limit=20)["job_counts"]["queued"] == 1
    unpaused = request(tmp_path, "commercePauseBusiness", id=shop["id"], paused=False)
    assert not unpaused["businesses"][0]["paused"]
    processed = request(tmp_path, "commerceRunPreflight", limit=20)
    assert processed["job_counts"]["queued"] == 0
    assert processed["job_counts"]["needs_evidence"] == 1
    assert processed["preflight_jobs"][0]["blockers"]
    assert processed["preflight_jobs"][0]["status"] == "needs_evidence"
    assert processed["mission_control"]["marketplace_write_access"] is False


def test_evidence_change_requeues_new_fingerprint_and_stales_old_job(tmp_path):
    shop = make_business(tmp_path)
    item = make_candidate(tmp_path, shop)
    request(tmp_path, "commerceQueuePreflight", idea_id=item["id"])
    review_evidence(tmp_path, item)
    request(tmp_path, "commercePauseBusiness", id=shop["id"], paused=False)
    stale = request(tmp_path, "commerceRunPreflight", limit=8)
    assert stale["job_counts"]["stale"] == 1
    assert stale["job_counts"]["review_ready"] == 0
    request(tmp_path, "commerceQueuePreflight", idea_id=item["id"])
    result = request(tmp_path, "commerceRunPreflight")
    assert result["job_counts"]["review_ready"] == 1
    assert result["counts"]["approved_for_export"] == 0
    assert result["preflight_jobs"][0]["status"] == "review_ready"


def test_queue_is_idempotent_even_when_clicked_multiple_times(tmp_path):
    shop = make_business(tmp_path)
    item = make_candidate(tmp_path, shop)
    first = request(tmp_path, "commerceQueuePreflight", idea_id=item["id"])
    second = request(tmp_path, "commerceQueuePreflight", idea_id=item["id"])
    assert first["preflight_jobs"][0]["id"] == second["preflight_jobs"][0]["id"]
    assert second["job_counts"]["queued"] == 1


def test_batch_is_round_robin_across_busy_businesses(tmp_path):
    a = make_business(tmp_path, "Alpha")
    b = make_business(tmp_path, "Bravo")
    request(tmp_path, "commercePauseBusiness", id=a["id"], paused=False)
    request(tmp_path, "commercePauseBusiness", id=b["id"], paused=False)
    for n in range(8):
        ia = make_candidate(tmp_path, a, title=f"A design {n}")
        request(tmp_path, "commerceQueuePreflight", idea_id=ia["id"])
    ib = make_candidate(tmp_path, b, title="B design")
    request(tmp_path, "commerceQueuePreflight", idea_id=ib["id"])
    board = request(tmp_path, "commerceRunPreflight", limit=2)
    checked = {j["business_id"] for j in board["preflight_jobs"]
               if j["status"] != "queued"}
    assert checked == {a["id"], b["id"]}
    assert board["job_counts"]["queued"] == 7


def test_cancel_is_final_and_cross_project_ids_are_rejected(tmp_path):
    business = make_business(tmp_path)
    item = make_candidate(tmp_path, business)
    board = request(tmp_path, "commerceQueuePreflight", idea_id=item["id"])
    job_id = board["preflight_jobs"][0]["id"]
    with pytest.raises(ValueError, match="current STAR workspace"):
        request(tmp_path, "commerceCancelPreflight", project="OTHER", id=job_id)
    canceled = request(tmp_path, "commerceCancelPreflight", id=job_id)
    assert canceled["job_counts"]["cancelled"] == 1
    with pytest.raises(ValueError, match="Only pending"):
        request(tmp_path, "commerceCancelPreflight", id=job_id)
    assert request(tmp_path, "commerceRunPreflight")["job_counts"]["cancelled"] == 1


def test_owner_review_still_required_even_for_passed_local_checklist(tmp_path):
    shop = make_business(tmp_path)
    item = make_candidate(tmp_path, shop)
    review_evidence(tmp_path, item)
    request(tmp_path, "commercePauseBusiness", id=shop["id"], paused=False)
    request(tmp_path, "commerceQueuePreflight", idea_id=item["id"])
    result = request(tmp_path, "commerceRunPreflight")
    assert result["job_counts"]["review_ready"] == 1
    assert item["id"] in [i["id"] for i in result["ideas"]]
    assert all(i["status"] != "approved_for_export" for i in result["ideas"])
    with pytest.raises(PermissionError, match="Owner confirmation"):
        request(tmp_path, "commerceReview", id=item["id"], decision="approve")


@pytest.mark.parametrize("bad", [0, 21, -1, 1.0, True, None, "10"])
def test_rejects_invalid_execution_limits(tmp_path, bad):
    with pytest.raises(ValueError, match="Batch size"):
        request(tmp_path, "commerceRunPreflight", limit=bad)


def test_rejects_unknown_job_types_and_no_marketplace_network(tmp_path, monkeypatch):
    import socket
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k:
                        (_ for _ in ()).throw(AssertionError("Network use forbidden")))
    make_business(tmp_path)
    with pytest.raises(PermissionError, match="Unsupported"):
        request(tmp_path, "commercePublish")
    from star.react_shell import ALLOWED_ACTIONS
    assert "commerceRunPreflight" in ALLOWED_ACTIONS
    for action in ("commercePublish", "commerceBuyAds", "commerceContactCustomer",
                   "commerceCollectPayments", "commerceAutoApprove"):
        assert action not in ALLOWED_ACTIONS


def test_previous_workspace_is_migrated_without_dropping_legacy_ideas(tmp_path):
    path = tmp_path / "commerce"
    path.mkdir()
    db = path / "workspace.sqlite3"
    with sqlite3.connect(db) as c:
        c.execute("""CREATE TABLE commerce_ideas (
            id TEXT PRIMARY KEY,project TEXT,channel TEXT,title TEXT,concept TEXT,
            evidence_json TEXT,status TEXT,created_at TEXT,updated_at TEXT)""")
        c.execute("INSERT INTO commerce_ideas VALUES(?,?,?,?,?,?,?,?,?)",
                  (uuid.uuid4().hex, "STAR", "etsy", "Existing candidate", "Original brief",
                   "{}", "draft", "2026-10-18", "2026-10-18"))
    first = request(tmp_path)
    second = request(tmp_path)
    assert first["ideas"][0]["title"] == "Existing candidate"
    assert first["ideas"][0]["business_id"] is None
    assert first["counts"] == second["counts"]
    with sqlite3.connect(db) as c:
        fields = {row[1] for row in c.execute("PRAGMA table_info(commerce_ideas)")}
        assert "business_id" in fields
