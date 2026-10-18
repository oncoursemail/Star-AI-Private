"""Offline quality policies; synthetic test receipts do NOT mean native QA ran."""
from __future__ import annotations

import hashlib
import json

import pytest

from star.human_quality import CheckReceipt, Criterion, main, review, template

REVISION = "a" * 64


def proof(criterion_id: str, *, kind: str, outcome="pass", origin="trusted_host",
          environment="native", artifact=REVISION, evidence="proof-1") -> CheckReceipt:
    return CheckReceipt(
        criterion_id, artifact, hashlib.sha256(evidence.encode()).hexdigest(),
        kind, outcome, origin, environment,
    )


def test_unchecked_templates_fail_closed_and_dont_self_approve():
    assert len(template("game")) >= 5
    for kind in ("software", "interface", "animation", "research", "music", "game"):
        result = review(REVISION, template(kind))
        assert result["state"] == "needs_evidence"
        assert result["checks_passed"] == 0
        assert result["model_quality_proven"] is False
        assert result["eligible_for_learning_proposal"] is False
    with pytest.raises(ValueError, match="Unknown"):
        template("generic-agents")


def test_native_requirements_reject_faked_static_and_agent_receipts():
    c = (Criterion("studio_test", "animation", ("native_playtest",), require_native=True),)
    wrong = proof("studio_test", kind="native_playtest", environment="simulation")
    agent = proof("studio_test", kind="native_playtest", origin="agent")
    stale = proof("studio_test", kind="native_playtest", artifact="b" * 64)
    result = review(REVISION, c, (wrong, agent, stale))
    assert result["state"] == "needs_evidence" and result["checks_passed"] == 0
    done = review(REVISION, c, (proof("studio_test", kind="native_playtest"),))
    assert done["state"] == "qualified" and done["checks_passed"] == 1
    assert done["model_quality_proven"] is False


def test_duplicate_receipts_cannot_fake_independent_verification():
    criterion = Criterion("code_review", "software", ("unit_test", "integration_test"), min_independent=2)
    one = proof("code_review", kind="unit_test")
    assert review(REVISION, (criterion,), (one, one))["state"] == "needs_evidence"
    second = proof("code_review", kind="integration_test", evidence="different-check")
    assert review(REVISION, (criterion,), (one, second))["state"] == "qualified"


def test_owner_review_required_and_immune_to_agent_approval():
    c = (Criterion("visual_signoff", "interface", ("visual_capture",),
                   require_native=True, require_owner_review=True),)
    visual = proof("visual_signoff", kind="visual_capture")
    result = review(REVISION, c, (visual,))
    assert result["state"] == "needs_owner"
    assert result["next_actions"][0]["action"] == "request_owner_review"
    with pytest.raises(ValueError, match="authenticated owner"):
        proof("visual_signoff", kind="human_review", origin="agent")
    owner = proof("visual_signoff", kind="human_review", origin="owner", environment="static", evidence="human-review")
    ready = review(REVISION, c, (visual, owner))
    assert ready["state"] == "qualified"
    assert ready["eligible_for_learning_proposal"] is False
    assert review(REVISION, c, (visual, owner), owner_approved_learning=True)["eligible_for_learning_proposal"]
    assert review("b" * 64, c, (visual, owner))["state"] == "needs_evidence"


def test_failure_triggers_bounded_repair_then_escalation():
    c = (Criterion("checks", "software", ("unit_test",)),)
    bad = proof("checks", kind="unit_test", outcome="fail")
    r1 = review(REVISION, c, (bad,), repair_attempts={"checks": 2})
    assert r1["state"] == "blocked"
    assert r1["next_actions"] == [{"criterion_id": "checks", "action": "repair_then_retest", "next_attempt": 3}]
    r2 = review(REVISION, c, (bad,), repair_attempts={"checks": 3})
    assert r2["next_actions"][0]["action"] == "escalate_to_owner"
    with pytest.raises(ValueError, match="bounded"):
        review(REVISION, c, (bad,), repair_attempts={"checks": 99})


def test_failed_check_is_not_overruled_by_new_pass_at_same_revision():
    c = (Criterion("check1", "software", ("unit_test",)),)
    report = review(REVISION, c, (
        proof("check1", kind="unit_test", outcome="fail", evidence="bad"),
        proof("check1", kind="unit_test", outcome="pass", evidence="good"),
    ))
    assert report["state"] == "blocked"


def test_invalid_receipts_rejected_before_any_automation():
    with pytest.raises(ValueError, match="content hashes"):
        proof("check1", kind="unit_test", artifact="broken")
    with pytest.raises(ValueError, match="Owner approvals"):
        proof("check1", kind="unit_test", origin="owner")
    with pytest.raises(ValueError, match="criterion"):
        review(REVISION, (Criterion("check1", "software", ("unit_test",)),),
               (proof("different", kind="unit_test"),))
    with pytest.raises(ValueError, match="Independent"):
        Criterion("check1", "software", ("unit_test",), min_independent=0)


def test_cli_reports_manifest_but_cannot_authorize_learning(tmp_path, capsys):
    checks = template("research")
    file = tmp_path / "quality.json"
    file.write_text(json.dumps({"artifact_sha256": REVISION, "receipts": [
        proof("source_grounding", kind="source_check").__dict__,
        proof("factual_check", kind="source_check", evidence="2").__dict__,
        proof("owner_requirements", kind="human_review", origin="owner", evidence="3").__dict__,
    ], "owner_approved_learning": True}), encoding="utf-8")
    assert main(["--template", "research", "--manifest", str(file)]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["state"] == "qualified"
    assert output["eligible_for_learning_proposal"] is False
    assert len(checks) == output["checks_passed"]
