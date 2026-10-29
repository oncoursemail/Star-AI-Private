"""Adversarial, offline Studio inspection-coverage contract tests."""
from dataclasses import replace
import hashlib
import hmac

import pytest

from star.studio_inspection_coverage import (
    EditFootprint, StudioReadReceipt, StudioInspectionCoverageGate,
)

KEY = b"x" * 32
TARGET = ("Workspace", "Arena", "Checkpoint")
DEPENDENCY = ("ServerScriptService", "CheckpointService")
CHANGE = hashlib.sha256(b"proposed exact edit").hexdigest()


def plan(**kwargs):
    data = dict(
        project_id="test-game", studio_session="studio-a", scene_revision=3,
        change_sha256=CHANGE, targets=(TARGET,), dependencies=(DEPENDENCY,),
    )
    data.update(kwargs)
    return EditFootprint(**data)


def signed(ticket, *, path=TARGET, at=1010, **kwargs):
    data = dict(
        plan_nonce=ticket, project_id="test-game", studio_session="studio-a",
        scene_revision=3, path=path, class_name="Part",
        observation_sha256=hashlib.sha256(repr(path).encode()).hexdigest(),
        captured_ms=at, complete=True, unique_path=True, mac="0" * 64,
    )
    data.update(kwargs)
    unsigned = StudioReadReceipt(**data)
    return replace(unsigned, mac=hmac.new(KEY, unsigned.signed_bytes(), hashlib.sha256).hexdigest())


def opened():
    gate = StudioInspectionCoverageGate(host_key=KEY)
    gate.enable(owner_approved=True)
    ticket = gate.register(plan(), now_ms=1000, host_approved=True)
    return gate, ticket


def test_off_by_default_and_owner_gate():
    gate = StudioInspectionCoverageGate(host_key=KEY)
    assert gate.review(now_ms=0).status == "disabled"
    with pytest.raises(PermissionError):
        gate.enable()
    gate.enable(owner_approved=True)
    with pytest.raises(PermissionError):
        gate.register(plan(), now_ms=3)
    assert gate.review(now_ms=3).status == "unplanned"


def test_missing_dependency_fails_closed_and_complete_inspection_only_reviews():
    gate, ticket = opened()
    assert gate.review(now_ms=1000).missing_paths == (TARGET, DEPENDENCY)
    assert gate.accept(signed(ticket), now_ms=1010)
    review = gate.review(now_ms=1011)
    assert review.status == "incomplete" and review.inspected == 1
    assert review.missing_paths == (DEPENDENCY,)
    assert gate.accept(signed(ticket, path=DEPENDENCY, at=1012, class_name="ModuleScript"),
                       now_ms=1012)
    review = gate.review(now_ms=1013)
    assert review.status == "ready_for_review"
    assert review.change_sha256 == CHANGE
    assert review.authorized_to_mutate is False


@pytest.mark.parametrize("changes", [
    dict(plan_nonce="0" * 32), dict(project_id="other-game"),
    dict(studio_session="studio-b"), dict(scene_revision=4),
    dict(path=("Workspace", "Unrequested")), dict(complete=False),
    dict(unique_path=False), dict(captured_ms=990),
])
def test_mismatched_or_partial_observations_rejected(changes):
    gate, ticket = opened()
    assert not gate.accept(signed(ticket, **changes), now_ms=1010)
    assert gate.review(now_ms=1011).status == "incomplete"


def test_forgery_or_tampered_class_cannot_pass():
    gate, ticket = opened()
    legit = signed(ticket)
    tampered = replace(legit, class_name="Model")
    assert not gate.accept(tampered, now_ms=1010)
    assert not gate.accept(replace(legit, mac="f" * 64), now_ms=1010)
    assert gate.accept(legit, now_ms=1010)
    assert not gate.accept(legit, now_ms=1011)  # one-use, no replay


def test_stale_receipts_and_future_receipts_fail_closed():
    gate, ticket = opened()
    assert not gate.accept(signed(ticket, at=2000), now_ms=1010)
    assert gate.accept(signed(ticket), now_ms=1010)
    assert gate.accept(signed(ticket, path=DEPENDENCY, at=1010), now_ms=1010)
    assert gate.review(now_ms=30_900).status == "ready_for_review"
    assert gate.review(now_ms=31_011).status == "stale"


def test_mutation_and_new_plan_nonce_revoke_prior_evidence():
    gate, ticket = opened()
    receipt = signed(ticket)
    assert gate.accept(receipt, now_ms=1010)
    gate.invalidate_revision(now_ms=1011)
    assert gate.review(now_ms=1011).status == "unplanned"
    new = gate.register(plan(scene_revision=4), now_ms=1012, host_approved=True)
    assert new != ticket
    assert not gate.accept(receipt, now_ms=1013)
    assert gate.review(now_ms=1013).inspected == 0


def test_same_scene_but_modified_change_requires_new_reads():
    gate, ticket = opened()
    assert gate.accept(signed(ticket), now_ms=1010)
    alternative = plan(change_sha256=hashlib.sha256(b"different edit").hexdigest())
    new = gate.register(alternative, now_ms=1011, host_approved=True)
    assert new != ticket
    assert not gate.accept(signed(ticket, at=1012), now_ms=1012)
    assert gate.review(now_ms=1013).missing_paths == (TARGET, DEPENDENCY)


def test_disabling_erases_observations_and_old_receipts():
    gate, ticket = opened()
    gate.accept(signed(ticket), now_ms=1010)
    gate.disable()
    assert gate.review(now_ms=1011).status == "disabled"
    gate.enable(owner_approved=True)
    gate.register(plan(), now_ms=1012, host_approved=True)
    assert not gate.accept(signed(ticket, at=1013), now_ms=1013)


def test_clock_rollback_poisoning_requires_fresh_host_plan():
    gate, ticket = opened()
    assert gate.accept(signed(ticket), now_ms=1010)
    with pytest.raises(ValueError, match="reversed"):
        gate.review(now_ms=1009)
    assert gate.review(now_ms=1011).status == "invalid"
    gate.register(plan(), now_ms=1012, host_approved=True)
    assert gate.review(now_ms=1013).status == "incomplete"


@pytest.mark.parametrize("changes", [
    dict(targets=()), dict(targets=(TARGET, TARGET)),
    dict(dependencies=(TARGET,)), dict(targets=(("DataStoreService", "x"),)),
    dict(targets=(("Workspace", ".."),)), dict(change_sha256="x" * 64),
    dict(scene_revision=True), dict(project_id="../secrets"),
])
def test_invalid_plan_rejected(changes):
    with pytest.raises(ValueError):
        plan(**changes)


def test_validation_budgets_and_flags():
    with pytest.raises(ValueError):
        StudioInspectionCoverageGate(host_key=b"short")
    with pytest.raises(ValueError):
        StudioInspectionCoverageGate(host_key=KEY, freshness_ms=0)
    with pytest.raises(ValueError):
        plan(targets=tuple(("Workspace", f"Part{i}") for i in range(33)))
    gate, ticket = opened()
    with pytest.raises(ValueError):
        signed(ticket, complete=1)
    with pytest.raises(ValueError):
        signed(ticket, class_name="SomePluginSecret")
    with pytest.raises(ValueError):
        gate.review(now_ms=float("nan"))


def test_no_content_is_stored_and_counters_are_minimal():
    gate, ticket = opened()
    assert gate.accept(signed(ticket), now_ms=1010)
    counts = gate.counters()
    assert counts["accepted"] == 1 and counts["revisions"] == 0
    assert not hasattr(gate, "source")
    counts["accepted"] = 100
    assert gate.counters()["accepted"] == 1
