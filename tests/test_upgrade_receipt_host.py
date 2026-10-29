"""Signed preregistration and independent outcome evidence for Core Forge."""
from dataclasses import replace
import hashlib

import pytest

from star.upgrade_evidence_gate import (
    CATEGORIES, UpgradeCase, UpgradeObservation, UpgradePlan,
)
from star.upgrade_receipt_host import (
    Precommit, SignedObservation, plan_digest,
    review_sealed_upgrade, sign_observation, sign_precommit,
)

COORDINATOR = b"independent-coordinator-secret-test-01"
OBSERVER = b"independent-observer-secret-test-0002"
S = 1_800_000_000


def hexdigest(value: str) -> str:
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def setup_experiment():
    cases = tuple(
        UpgradeCase(f"{category}-{i:02}", category, hexdigest("environment"))
        for category in CATEGORIES for i in range(12)
    )
    plan = UpgradePlan(
        hexdigest("suite"), hexdigest("scorer"), hexdigest("baseline"),
        hexdigest("candidate"), cases, True, True,
    )
    orders = tuple((c.case_id, "AB" if index % 2 == 0 else "BA")
                   for index, c in enumerate(cases))
    precommit = Precommit(
        "experiment-001", "a" * 32, plan_digest(plan),
        S, S + 3600, orders,
    )
    signed = sign_precommit(precommit, coordinator_key=COORDINATOR)
    records = []
    for index, (case_id, order) in enumerate(orders):
        for variant in ("baseline", "candidate"):
            obs = UpgradeObservation(
                case_id, variant, order, cases[index].environment_sha256,
                plan.scorer_sha256, True,
                450.0 if variant == "baseline" else 180.0,
                2100.0 if variant == "baseline" else 2400.0,
                True, True, False,
            )
            records.append(sign_observation(
                obs, precommit_sha256=precommit.digest,
                evidence_sha256=hexdigest(f"run-{index}-{variant}"),
                observed_unix_s=S + 100 + index,
                observer_key=OBSERVER,
            ))
    return plan, signed, records


def evaluate(plan, sealed, records, **overrides):
    return review_sealed_upgrade(
        plan, sealed, records,
        coordinator_key=overrides.get("coordinator_key", COORDINATOR),
        observer_key=overrides.get("observer_key", OBSERVER),
        now_unix_s=overrides.get("now", S + 2400),
    )


def resig(record: SignedObservation, **changes):
    fields = {
        "observation": record.observation,
        "precommit_sha256": record.precommit_sha256,
        "evidence_sha256": record.evidence_sha256,
        "observed_unix_s": record.observed_unix_s,
        **changes,
    }
    return sign_observation(**fields, observer_key=OBSERVER)


def test_independently_signed_experiment_passes_only_for_owner_review():
    plan, sealed, records = setup_experiment()
    review = evaluate(plan, sealed, records)
    assert review.verdict == "eligible_for_owner_review"
    assert review.verified_observations == 144
    assert review.comparison.complete_pairs == 72
    assert review.comparison.mean_latency_gain_ms == 270
    assert review.authorized_to_deploy is False


def test_deterministic_plan_digest_binds_all_plan_fields():
    plan, _, _ = setup_experiment()
    assert plan_digest(plan) == plan_digest(plan)
    assert plan_digest(replace(plan, suite_sha256=hexdigest("other"))) != plan_digest(plan)


def test_review_is_order_independent_when_receipts_are_valid():
    plan, sealed, records = setup_experiment()
    assert evaluate(plan, sealed, records) == evaluate(plan, sealed, list(reversed(records)))


@pytest.mark.parametrize("field", [
    "plan", "nonce", "orders", "issued", "expires", "signature",
])
def test_precommit_substitutions_cannot_be_silent(field):
    plan, sealed, records = setup_experiment()
    m = sealed.precommit
    if field == "plan":
        m = replace(m, plan_sha256=hexdigest("forged-plan"))
    elif field == "nonce":
        m = replace(m, nonce="b" * 32)
    elif field == "orders":
        m = replace(m, case_orders=tuple(reversed(m.case_orders)))
    elif field == "issued":
        m = replace(m, issued_unix_s=S - 60)
    elif field == "expires":
        m = replace(m, expires_unix_s=S + 4000)
    elif field == "signature":
        sealed = replace(sealed, signature="f" * 64)
    if field != "signature":
        sealed = replace(sealed, precommit=m)
    assert evaluate(plan, sealed, records).reason == "precommit_authentication_failed"


def test_authenticated_precommit_cannot_change_underlying_plan():
    plan, sealed, records = setup_experiment()
    plan = replace(plan, candidate_sha256=hexdigest("substituted-candidate"))
    assert evaluate(plan, sealed, records).reason == "plan_digest_mismatch"


def test_missing_trial_is_inconclusive_even_with_valid_signatures():
    plan, sealed, records = setup_experiment()
    result = evaluate(plan, sealed, records[:-1])
    assert result.verdict == "inconclusive"
    assert result.comparison.missing_pairs == 1


@pytest.mark.parametrize("field", [
    "observation", "evidence_sha256", "precommit_sha256", "observed_unix_s",
])
def test_receipt_field_tampering_fails_closed(field):
    plan, sealed, records = setup_experiment()
    rec = records[0]
    if field == "observation":
        rec = replace(rec, observation=replace(rec.observation, elapsed_ms=1))
    elif field == "evidence_sha256":
        rec = replace(rec, evidence_sha256=hexdigest("tampered"))
    elif field == "precommit_sha256":
        rec = replace(rec, precommit_sha256=hexdigest("other-run"))
    else:
        rec = replace(rec, observed_unix_s=S + 200)
    records[0] = rec
    result = evaluate(plan, sealed, records)
    assert result.verdict == "inconclusive"
    assert result.comparison is None


def test_cross_experiment_replay_fails_even_with_valid_observer_signature():
    plan, sealed, records = setup_experiment()
    records[0] = resig(records[0], precommit_sha256=hexdigest("another-commit"))
    assert evaluate(plan, sealed, records).reason == "observation_cross_experiment_replay"


def test_duplicate_case_variant_is_not_best_of_n_selection():
    plan, sealed, records = setup_experiment()
    assert evaluate(plan, sealed, records + [records[0]]).reason == (
        "duplicate_trial_or_evidence_reuse"
    )


def test_evidence_reused_for_different_task_is_rejected_even_if_resigned():
    plan, sealed, records = setup_experiment()
    records[1] = resig(records[1], evidence_sha256=records[0].evidence_sha256)
    assert evaluate(plan, sealed, records).reason == "duplicate_trial_or_evidence_reuse"


def test_observation_with_valid_signature_but_changed_order_is_rejected():
    plan, sealed, records = setup_experiment()
    obs = replace(records[0].observation, order="BA")
    records[0] = resig(records[0], observation=obs)
    assert evaluate(plan, sealed, records).reason == "unregistered_case_or_changed_order"


@pytest.mark.parametrize("now,expected", [
    (S - 2, "precommit_expired_or_not_yet_valid"),
    (S + 3600 + 86401, "precommit_expired_or_not_yet_valid"),
])
def test_expired_and_not_yet_valid_precommits(now, expected):
    plan, sealed, records = setup_experiment()
    assert evaluate(plan, sealed, records, now=now).reason == expected


@pytest.mark.parametrize("when", [S, S + 3601, S + 2500])
def test_premature_future_or_post_deadline_observation_is_rejected(when):
    plan, sealed, records = setup_experiment()
    records[0] = resig(records[0], observed_unix_s=when)
    assert evaluate(plan, sealed, records).reason == (
        "observation_outside_frozen_run_window"
    )


def test_different_keys_are_required():
    plan, sealed, records = setup_experiment()
    with pytest.raises(ValueError, match="independent"):
        evaluate(plan, sealed, records, observer_key=COORDINATOR)


def test_wrong_host_key_does_not_authenticate():
    plan, sealed, records = setup_experiment()
    assert evaluate(plan, sealed, records, coordinator_key=b"x" * 32).reason == (
        "precommit_authentication_failed"
    )
    assert evaluate(plan, sealed, records, observer_key=b"x" * 32).reason == (
        "observation_authentication_failed"
    )


def test_unbalanced_schedule_is_rejected_even_if_re_signed():
    plan, sealed, records = setup_experiment()
    m = replace(sealed.precommit, case_orders=tuple((c.case_id, "AB") for c in plan.cases))
    new = sign_precommit(m, coordinator_key=COORDINATOR)
    assert evaluate(plan, new, records).reason == "unbalanced_precommitted_order"


def test_incomplete_schedule_is_rejected():
    plan, sealed, records = setup_experiment()
    m = replace(sealed.precommit, case_orders=sealed.precommit.case_orders[:-1])
    new = sign_precommit(m, coordinator_key=COORDINATOR)
    assert evaluate(plan, new, records).reason == "case_schedule_incomplete"


def test_no_heldout_suite_is_not_allowed_even_when_signed():
    plan, sealed, records = setup_experiment()
    plan = replace(plan, heldout=False)
    m = replace(sealed.precommit, plan_sha256=plan_digest(plan))
    sealed = sign_precommit(m, coordinator_key=COORDINATOR)
    assert evaluate(plan, sealed, records).reason == "independent_holdout_precommit_not_declared"


def test_host_scored_safety_violation_veto_survives_envelope():
    plan, sealed, records = setup_experiment()
    i = next(i for i, row in enumerate(records) if (
        row.observation.variant == "candidate"
        and row.observation.case_id.startswith("safety-")
    ))
    records[i] = resig(
        records[i], observation=replace(records[i].observation, safety_violation=True),
    )
    result = evaluate(plan, sealed, records)
    assert result.verdict == "regressed"
    assert result.reason == "candidate_safety_violation"


def test_authenticated_performance_regression_cannot_be_promoted():
    plan, sealed, records = setup_experiment()
    records = [
        resig(row, observation=replace(row.observation, elapsed_ms=900))
        if row.observation.variant == "candidate" else row
        for row in records
    ]
    assert evaluate(plan, sealed, records).verdict != "eligible_for_owner_review"


def test_receipts_are_not_authorization_even_when_quality_checks_pass():
    plan, sealed, records = setup_experiment()
    out = evaluate(plan, sealed, records)
    assert not out.authorized_to_deploy


def test_reject_invalid_precommit_time_window():
    plan, _, _ = setup_experiment()
    with pytest.raises(ValueError, match="seven days"):
        Precommit("exp", "b" * 32, plan_digest(plan), S, S + 8 * 86400,
                  tuple((c.case_id, "AB") for c in plan.cases))


def test_reject_invalid_receipt_input_types_and_secrets():
    plan, sealed, records = setup_experiment()
    assert evaluate(plan, sealed, [records[0], "unsigned"]).reason == (
        "unsigned_or_malformed_observation"
    )
    with pytest.raises(ValueError, match="32"):
        evaluate(plan, sealed, records, observer_key=b"tiny")


def test_reject_unbounded_inputs():
    plan, sealed, records = setup_experiment()
    with pytest.raises(ValueError, match="bounded"):
        evaluate(plan, sealed, records * 9)
    with pytest.raises(ValueError, match="timestamp"):
        evaluate(plan, sealed, records, now=True)
