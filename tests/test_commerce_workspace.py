"""Offline commerce workspace integration and security regression tests."""
from __future__ import annotations

import sqlite3

import pytest

from star.commerce.workspace import COMMERCE_ACTIONS, handle_commerce


def invoke(tmp_path, action="commerceBoard", project="STAR", **data):
    return handle_commerce(action, data, project=project, home=tmp_path)


def new(tmp_path, channel="etsy", title="Original Creator Overlay Kit", project="STAR"):
    return invoke(
        tmp_path, "commerceCreate", project=project, channel=channel,
        title=title, concept="An original editable overlay family for small creators.",
    )["ideas"][0]


def test_initial_board_is_empty_and_honest(tmp_path):
    board = invoke(tmp_path)
    assert board["counts"] == {
        "candidates": 0, "review_ready": 0, "approved_for_export": 0,
        "live_listings": 0, "verified_sales": None,
    }
    assert board["automation"]["state"] == "not_enabled"
    assert all(p["connection"] == "not_connected_in_star" for p in board["platforms"])


def test_creates_persistent_candidate_in_private_app_data(tmp_path):
    candidate = new(tmp_path)
    assert len(candidate["id"]) == 32
    assert candidate["status"] == "draft"
    assert candidate["review"]["ready"] is False
    assert any("rights" in str(problem).lower() for problem in candidate["review"]["blockers"])
    assert (tmp_path / "commerce" / "workspace.sqlite3").is_file()
    assert candidate["id"] == invoke(tmp_path)["ideas"][0]["id"]
    assert invoke(tmp_path)["counts"]["verified_sales"] is None


def test_same_title_not_duplicated_in_same_marketplace(tmp_path):
    new(tmp_path)
    with pytest.raises(ValueError, match="already has"):
        new(tmp_path)
    assert len(invoke(tmp_path)["ideas"]) == 1


def test_project_and_marketplace_isolation(tmp_path):
    left = new(tmp_path, project="STAR")
    right = new(tmp_path, project="Other workspace")
    assert left["id"] != right["id"]
    assert len(invoke(tmp_path, project="STAR")["ideas"]) == 1
    with pytest.raises(ValueError, match="not found"):
        invoke(tmp_path, "commerceReview", project="Other workspace",
               id=left["id"], owner_confirmed=True, decision="changes")


def test_owner_click_approves_even_with_open_advisory_notes(tmp_path):
    """Open evidence notes are advice only: the owner's confirmed click is the sole gate."""
    candidate = new(tmp_path)
    assert candidate["review"]["ready"] is False
    with pytest.raises(PermissionError, match="Owner confirmation"):
        invoke(tmp_path, "commerceReview", id=candidate["id"], decision="approve")
    forced = invoke(tmp_path, "commerceReview", id=candidate["id"],
                    decision="approve", owner_confirmed=True)["ideas"][0]
    assert forced["status"] == "approved_for_export"
    assert forced["review"]["ready"] is False


def test_ready_requires_evidence_then_explicit_owner_click(tmp_path):
    candidate = new(tmp_path)
    approved = invoke(
        tmp_path, "commerceEvidence", id=candidate["id"],
        evidence={
            "rights_evidence": "Original vectors; reviewed source files and licensing.",
            "visual_qa_evidence": "Reviewed layout, typography, exports and intended use.",
            "accurate_mockup_reviewed": True,
            "ai_disclosed": True,
        },
    )["ideas"][0]
    assert approved["review"]["ready"] is True
    assert approved["status"] == "draft"
    with pytest.raises(PermissionError, match="Owner confirmation"):
        invoke(tmp_path, "commerceReview", id=candidate["id"], decision="approve")
    reviewed = invoke(tmp_path, "commerceReview", id=candidate["id"],
                      decision="approve", owner_confirmed=True)["ideas"][0]
    assert reviewed["status"] == "approved_for_export"
    assert reviewed["review"]["external_actions_performed"] is False
    edited = invoke(tmp_path, "commerceEvidence", id=candidate["id"],
                    evidence={"rights_evidence": "Revised rights evidence"})["ideas"][0]
    assert edited["status"] == "draft"
    assert invoke(tmp_path)["counts"]["approved_for_export"] == 0


def test_fiverr_buyer_approval_and_custom_work_required(tmp_path):
    candidate = new(tmp_path, channel="fiverr", title="Custom creator identity")
    after = invoke(
        tmp_path, "commerceEvidence", id=candidate["id"],
        evidence={
            "rights_evidence": "Rights reviewed by owner.",
            "visual_qa_evidence": "Independent art quality review.",
            "buyer_brief": "Client-specific scope and acceptance criteria.",
            "customization_evidence": "Manual composition and final typography redrawn.",
            "buyer_allows_ai": False,
        },
    )["ideas"][0]
    assert not after["review"]["ready"]
    assert any("AI" in x for x in after["review"]["blockers"])
    after = invoke(tmp_path, "commerceEvidence", id=candidate["id"],
                   evidence={"buyer_allows_ai": True})["ideas"][0]
    assert after["review"]["ready"]
    assert after["review"]["external_actions_performed"] is False


def test_physical_order_safety_requires_sample_and_partner_disclosure(tmp_path):
    candidate = new(tmp_path, channel="printify", title="Original physical print")
    after = invoke(tmp_path, "commerceEvidence", id=candidate["id"],
                   evidence={
                       "rights_evidence": "Original licensed vectors.",
                       "visual_qa_evidence": "Reviewed print placement.",
                       "ai_disclosed": True,
                       "accurate_mockup_reviewed": True,
                   })["ideas"][0]
    assert not after["review"]["ready"]
    assert any("sample" in x for x in after["review"]["blockers"])
    assert any("partner" in x.lower() for x in after["review"]["blockers"])


@pytest.mark.parametrize("channel", ["", "reddit", "../etsy", 3, None])
def test_rejects_unknown_channel(tmp_path, channel):
    with pytest.raises(ValueError):
        invoke(tmp_path, "commerceCreate", channel=channel,
               title="Title", concept="Specific buyer problem")


@pytest.mark.parametrize("bad_id", ["../users", "not-a-uuid", "e" * 33, 9, None])
def test_rejects_bad_id(tmp_path, bad_id):
    with pytest.raises(ValueError):
        invoke(tmp_path, "commerceEvidence", id=bad_id, evidence={"ai_disclosed": True})


def test_prevents_boolean_injection_and_unlisted_evidence_fields(tmp_path):
    candidate = new(tmp_path)
    for fields in ({"ai_disclosed": "true"}, {"admin": True},
                   {"rights_evidence": "x" * 2001}):
        with pytest.raises(ValueError):
            invoke(tmp_path, "commerceEvidence", id=candidate["id"], evidence=fields)
    assert invoke(tmp_path)["ideas"][0]["evidence"] == {}


def test_not_a_marketplace_client_or_scheduler(tmp_path, monkeypatch):
    import socket
    def blocked(*args, **kwargs):
        raise AssertionError("Commerce workspace must not access network")
    monkeypatch.setattr(socket, "create_connection", blocked)
    new(tmp_path)
    invoke(tmp_path)
    with pytest.raises(PermissionError):
        invoke(tmp_path, "commercePublish", id="a" * 32)
    assert not (tmp_path / "commerce" / "credentials.json").exists()
    with sqlite3.connect(tmp_path / "commerce" / "workspace.sqlite3") as db:
        events = db.execute("SELECT action FROM commerce_events").fetchall()
    assert events == [("candidate_created",)]


def test_qt_allowlist_includes_only_review_scoped_commerce():
    from star.react_shell import ALLOWED_ACTIONS
    assert COMMERCE_ACTIONS <= ALLOWED_ACTIONS
    assert "commercePublish" not in ALLOWED_ACTIONS
    assert "commerceCharge" not in ALLOWED_ACTIONS
    assert "commerceSendFiverrMessage" not in ALLOWED_ACTIONS
