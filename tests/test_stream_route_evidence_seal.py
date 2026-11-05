"""Host-signed gaming/VTuber quality evaluation prevents forged promotion receipts."""
from dataclasses import replace

import pytest

from star.stream_host_model_catalog import HostInferenceCatalog, HostModelRoute
from star.stream_quality_route_selector import (
    QualityGatedRouteSelector, VerifiedPairedRouteCases, VerifiedRouteTrialSummary,
)
from star.stream_route_evidence_seal import (
    sign_route_evaluation, verify_route_evaluation,
)

KEY = b"star-host-test-only-never-deploy!" * 2
OTHER_KEY = b"untrusted-evaluator-key-32-bytes!" * 2
NOW = 1_800_000_000
SUITE = "a" * 64
COHORT = "b" * 64
BUILD = "c" * 64
MANIFEST = "d" * 64


def catalog():
    return HostInferenceCatalog((
        HostModelRoute("baseline", "speech", "cpu", "llamacpp",
                       "1" * 64, "2" * 64, 500, 0),
        HostModelRoute("candidate", "speech", "gpu", "llamacpp",
                       "3" * 64, "2" * 64, 500, 1500),
    ))


def evidence(c):
    baseline = VerifiedRouteTrialSummary(
        "baseline", c.profile_for("baseline"), "speech", "game_recording",
        SUITE, 30, 30, 550, 2400, NOW - 80, True, eval_cohort_sha256=COHORT,
    )
    candidate = VerifiedRouteTrialSummary(
        "candidate", c.profile_for("candidate"), "speech", "game_recording",
        SUITE, 30, 30, 200, 2900, NOW - 75, True, eval_cohort_sha256=COHORT,
    )
    cases = VerifiedPairedRouteCases(
        "baseline", "candidate", c.profile_for("baseline"), c.profile_for("candidate"),
        "speech", "game_recording", SUITE, (True,) * 30, (True,) * 30,
        (False,) * 30, NOW - 76, True, eval_cohort_sha256=COHORT,
    )
    return (baseline, candidate), (cases,)


def sign(summaries, pairs, **changes):
    arguments = dict(
        host_key=KEY, cohort_sha256=COHORT, evaluator_build_sha256=BUILD,
        artifact_manifest_sha256=MANIFEST, issued_unix_s=NOW - 10,
        summaries=summaries, paired_cases=pairs,
    )
    arguments.update(changes)
    return sign_route_evaluation(**arguments)


def decision(*, summaries, paired_cases, seal=None, key=None, required=True,
             now=NOW, owner_approved=True):
    c = catalog()
    selector = QualityGatedRouteSelector(
        catalog=c, summaries=summaries, paired_cases=paired_cases,
        require_signed_evidence=required, evidence_seal=seal,
        evidence_verification_key=key,
    )
    return selector.advise(
        owner_approved=owner_approved, baseline_alias="baseline",
        task_kind="speech", workload="game_recording", suite_sha256=SUITE,
        now_unix_s=now, max_p95_ms=1000, max_total_gpu_mib=8000,
    )


def test_trusted_host_signed_bundle_advises_faster_without_deploying():
    c = catalog()
    summaries, pairs = evidence(c)
    seal = sign(summaries, pairs)
    assert verify_route_evaluation(
        host_key=KEY, seal=seal, summaries=summaries, paired_cases=pairs,
    )
    result = decision(summaries=summaries, paired_cases=pairs, seal=seal, key=KEY)
    assert result.route_alias == "candidate"
    assert result.reason == "faster_verified_route_for_manual_pilot"
    assert not result.authorizes_model_launch
    assert not result.authorizes_game_action
    assert not hasattr(result, "signature_hmac_sha256")
    assert KEY.hex() not in repr(seal)


def test_strict_opt_in_requires_attestation_and_preserves_owner_gate():
    summaries, pairs = evidence(catalog())
    missing = decision(summaries=summaries, paired_cases=pairs)
    assert missing.route_alias is None
    assert missing.reason == "signed_evaluation_unverified"
    assert decision(
        summaries=summaries, paired_cases=pairs, owner_approved=False,
    ).reason == "owner_opt_in_missing"
    assert decision(
        summaries=summaries, paired_cases=pairs, required=False,
    ).route_alias == "candidate"


@pytest.mark.parametrize("which", [
    "baseline_speed", "candidate_speed", "baseline_success", "candidate_profile",
    "paired_success", "paired_critical", "paired_timestamp",
    "baseline_timestamp", "candidate_timestamp", "baseline_host",
    "candidate_cohort", "pair_cohort",
])
def test_evidence_tamper_fails_signature_and_selector_closed(which):
    c = catalog()
    summaries, pairs = evidence(c)
    seal = sign(summaries, pairs)
    base, candidate = summaries
    pair = pairs[0]
    if which == "baseline_speed":
        base = replace(base, p95_end_to_end_ms=999)
    elif which == "candidate_speed":
        candidate = replace(candidate, p95_end_to_end_ms=30)
    elif which == "baseline_success":
        base = replace(base, verified_successes=29)
    elif which == "candidate_profile":
        candidate = replace(candidate, route_profile="wrong")
    elif which == "paired_success":
        pair = replace(pair, candidate_outcomes=(False,) + (True,) * 29)
    elif which == "paired_critical":
        pair = replace(pair, critical_cases=(True,) + (False,) * 29)
    elif which == "paired_timestamp":
        pair = replace(pair, measured_unix_s=NOW - 75)
    elif which == "baseline_timestamp":
        base = replace(base, measured_unix_s=NOW - 79)
    elif which == "candidate_timestamp":
        candidate = replace(candidate, measured_unix_s=NOW - 74)
    elif which == "baseline_host":
        base = replace(base, host_verified=False)
    elif which == "candidate_cohort":
        candidate = replace(candidate, eval_cohort_sha256="e" * 64)
    else:
        pair = replace(pair, eval_cohort_sha256="e" * 64)
    altered_summaries, altered_pairs = (base, candidate), (pair,)
    assert not verify_route_evaluation(
        host_key=KEY, seal=seal, summaries=altered_summaries,
        paired_cases=altered_pairs,
    )
    if which != "candidate_profile":  # catalog catches profile spoof before seal gate
        result = decision(
            summaries=altered_summaries, paired_cases=altered_pairs,
            seal=seal, key=KEY,
        )
        assert result.route_alias is None
        assert result.reason == "signed_evaluation_unverified"


@pytest.mark.parametrize("which", [
    "cohort", "build", "manifest", "issued", "signature",
])
def test_metadata_tamper_rejected(which):
    summaries, pairs = evidence(catalog())
    seal = sign(summaries, pairs)
    edits = {
        "cohort": {"cohort_sha256": "e" * 64},
        "build": {"evaluator_build_sha256": "e" * 64},
        "manifest": {"artifact_manifest_sha256": "e" * 64},
        "issued": {"issued_unix_s": NOW - 11},
        "signature": {"signature_hmac_sha256": "f" * 64},
    }
    forged = replace(seal, **edits[which])
    assert not verify_route_evaluation(
        host_key=KEY, seal=forged, summaries=summaries, paired_cases=pairs,
    )
    assert decision(
        summaries=summaries, paired_cases=pairs, seal=forged, key=KEY,
    ).reason == "signed_evaluation_unverified"


def test_key_substitution_is_not_host_authentication():
    summaries, pairs = evidence(catalog())
    seal = sign(summaries, pairs)
    assert not verify_route_evaluation(
        host_key=OTHER_KEY, seal=seal, summaries=summaries, paired_cases=pairs,
    )
    assert decision(
        summaries=summaries, paired_cases=pairs, seal=seal, key=OTHER_KEY,
    ).route_alias is None


@pytest.mark.parametrize("diff", [-1, 8 * 86400])
def test_future_or_stale_seal_rejected_even_when_outcomes_valid(diff):
    summaries, pairs = evidence(catalog())
    seal = sign(summaries, pairs)
    result = decision(
        summaries=summaries, paired_cases=pairs, seal=seal, key=KEY,
        now=seal.issued_unix_s + diff,
    )
    assert result.route_alias is None
    assert result.reason == "signed_evaluation_stale_or_future"


@pytest.mark.parametrize("bad", [None, b"tiny", "string", bytearray(b"a" * 32)])
def test_weak_or_invalid_key_rejected(bad):
    summaries, pairs = evidence(catalog())
    with pytest.raises(ValueError, match="key"):
        sign(summaries, pairs, host_key=bad)


def test_incoherent_host_run_is_not_signable():
    summaries, pairs = evidence(catalog())
    with pytest.raises(ValueError, match="cohort"):
        sign((summaries[0], replace(summaries[1], eval_cohort_sha256="e" * 64)), pairs)
    with pytest.raises(ValueError, match="issuance"):
        sign(summaries, pairs, issued_unix_s=NOW - 90)
    with pytest.raises(ValueError, match="issuance"):
        sign(summaries, pairs, issued_unix_s=NOW + 1000)
    with pytest.raises(ValueError, match="host-approved"):
        sign((replace(summaries[0], host_verified=False), summaries[1]), pairs)


def test_deterministic_canonical_order_and_untrusted_inputs():
    summaries, pairs = evidence(catalog())
    seal = sign(summaries, pairs)
    assert verify_route_evaluation(
        host_key=KEY, seal=seal, summaries=tuple(reversed(summaries)), paired_cases=pairs,
    )
    assert not verify_route_evaluation(
        host_key=KEY, seal=seal, summaries=(1,), paired_cases=pairs,
    )
    assert not verify_route_evaluation(
        host_key=KEY, seal="fake", summaries=summaries, paired_cases=pairs,
    )


def test_verify_only_accepts_paired_key_and_seal_configuration():
    summaries, pairs = evidence(catalog())
    seal = sign(summaries, pairs)
    for key, signed in ((KEY, None), (None, seal)):
        with pytest.raises(ValueError, match="seal and private"):
            decision(summaries=summaries, paired_cases=pairs, seal=signed, key=key)


def test_timestamp_and_wrong_signer_digest_validated():
    summaries, pairs = evidence(catalog())
    seal = sign(summaries, pairs)
    with pytest.raises(ValueError, match="signature"):
        replace(seal, signature_hmac_sha256="D" * 64)
    with pytest.raises(ValueError, match="bounded"):
        replace(seal, issued_unix_s=True)
    with pytest.raises(ValueError, match="require_signed_evidence"):
        QualityGatedRouteSelector(
            catalog=catalog(), summaries=summaries, paired_cases=pairs,
            require_signed_evidence=1,
        )
