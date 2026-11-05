"""Offline proof that one signed gaming/VTuber evaluation can be claimed once."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from hashlib import sha256
import os
from pathlib import Path
import sqlite3

import pytest

from star.stream_host_model_catalog import HostInferenceCatalog, HostModelRoute
from star.stream_route_cohort_ledger import claim_verified_fast_route
from star.stream_route_measured_evaluator import (
    IndependentlyScoredAttempt, IndependentlyScoredRouteRun,
    RegisteredRouteCase, RegisteredRouteSuite, assemble_measured_route_evidence,
)

NOW = 1_800_000_000
KEY = b"test-key-only-signed-host-data-32-bytes!!"
BUILD = "e" * 64


def h(value: str) -> str:
    return sha256(value.encode()).hexdigest()


def fixture():
    catalog = HostInferenceCatalog((
        HostModelRoute("base", "speech", "cpu", "llamacpp", "1" * 64, "2" * 64, 500, 0),
        HostModelRoute("fast", "speech", "gpu", "llamacpp", "3" * 64, "2" * 64, 500, 1500),
    ))
    suite = RegisteredRouteSuite(
        task_kind="speech", workload="game_recording",
        rubric_sha256="a" * 64, preregistered_unix_s=NOW - 400,
        cases=tuple(RegisteredRouteCase(h(f"case-{i}"), i == 2) for i in range(30)),
    )

    def run(alias: str, ms: float) -> IndependentlyScoredRouteRun:
        return IndependentlyScoredRouteRun(
            route_alias=alias, route_profile=catalog.profile_for(alias),
            completed_unix_s=NOW - 50,
            attempts=tuple(IndependentlyScoredAttempt(
                case_sha256=c.case_sha256,
                scoring_artifact_sha256=h(f"{alias}-{i}"),
                passed=True, end_to_end_ms=ms,
                total_gpu_peak_mib=2900,
            ) for i, c in enumerate(suite.cases)),
        )
    bundle = assemble_measured_route_evidence(
        host_key=KEY, catalog=catalog, suite=suite,
        expected_suite_sha256=suite.suite_sha256,
        baseline=run("base", 600), candidate=run("fast", 200),
        evaluator_build_sha256=BUILD, issued_unix_s=NOW - 10,
    )
    return catalog, bundle, suite


def claim(path: Path, *, c=None, bundle=None, suite=None, **updates):
    if c is None or bundle is None or suite is None:
        c, bundle, suite = fixture()
    arguments = dict(
        ledger_path=path, catalog=c, bundle=bundle,
        host_verification_key=KEY, expected_evaluator_build_sha256=BUILD,
        owner_approved=True, baseline_alias="base", task_kind="speech",
        workload="game_recording", suite_sha256=suite.suite_sha256,
        now_unix_s=NOW, max_p95_ms=1000, max_total_gpu_mib=8000,
    )
    arguments.update(updates)
    return claim_verified_fast_route(**arguments)


def test_signed_candidate_is_claimed_once_and_persisted(tmp_path):
    c, bundle, suite = fixture()
    db = tmp_path / "claims.sqlite3"
    first = claim(db, c=c, bundle=bundle, suite=suite)
    assert first.recorded and first.route_alias == "fast"
    assert first.reason == "owner_pilot_receipt_recorded"
    assert not first.authorizes_model_launch
    assert not first.authorizes_game_action
    assert not first.authorizes_broadcast
    assert db.stat().st_mode & 0o777 == 0o600
    second = claim(db, c=c, bundle=bundle, suite=suite)
    assert not second.recorded and second.route_alias is None
    assert second.reason == "evaluation_cohort_already_consumed"
    with sqlite3.connect(db) as conn:
        row = conn.execute(
            "SELECT cohort_sha256, candidate_alias, signature_hmac_sha256 FROM route_pilot_claims"
        ).fetchone()
    assert row == (bundle.seal.cohort_sha256, "fast", bundle.seal.signature_hmac_sha256)


def test_cross_process_style_contention_serialized_to_one_success(tmp_path):
    c, bundle, suite = fixture()
    db = tmp_path / "claims.sqlite3"
    # Every thread creates its own connection; no per-object Python lock helps.
    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(lambda _: claim(db, c=c, bundle=bundle, suite=suite), range(12)))
    assert sum(r.recorded for r in results) == 1
    assert sum(r.reason == "evaluation_cohort_already_consumed" for r in results) == 11


def test_distinct_cohort_can_be_verified_on_same_ledger(tmp_path):
    c, bundle, suite = fixture()
    newer = fixture()[1]  # independently signed cohort with same suite and route aliases
    db = tmp_path / "claims.sqlite3"
    assert bundle.seal.cohort_sha256 != newer.seal.cohort_sha256
    assert claim(db, c=c, bundle=bundle, suite=suite).recorded
    assert claim(db, c=c, bundle=newer, suite=suite).recorded
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT count(*) FROM route_pilot_claims").fetchone()[0] == 2


@pytest.mark.parametrize("edit,expected", [
    ({"owner_approved": False}, "owner_opt_in_missing"),
    ({"expected_evaluator_build_sha256": "b" * 64}, "evaluator_build_not_pinned"),
    ({"host_verification_key": b"different-but-valid-host-key-for-tests"}, "signed_evaluation_unverified"),
    ({"now_unix_s": NOW - 100}, "signed_evaluation_stale_or_future"),
    ({"max_p95_ms": 100}, "no_quality_and_resource_qualified_route"),
    ({"max_total_gpu_mib": 1000}, "no_quality_and_resource_qualified_route"),
])
def test_no_eligible_trusted_candidate_does_not_touch_ledger(tmp_path, edit, expected):
    db = tmp_path / "claims.sqlite3"
    c, bundle, suite = fixture()
    result = claim(db, c=c, bundle=bundle, suite=suite, **edit)
    assert not result.recorded
    assert result.reason == expected
    assert not db.exists()


def test_tampered_signed_evidence_cannot_consume_cohort(tmp_path):
    c, bundle, suite = fixture()
    forged = replace(bundle, summaries=(bundle.summaries[0], replace(
        bundle.summaries[1], p95_end_to_end_ms=1,
    )))
    db = tmp_path / "claims.sqlite3"
    result = claim(db, c=c, bundle=forged, suite=suite)
    assert not result.recorded and result.reason == "signed_evaluation_unverified"
    assert not db.exists()


def test_faster_route_regresses_critical_case_and_is_rejected(tmp_path):
    c, bundle, suite = fixture()
    # Correctly rescored and re-signed in the trusted host; no forged signature.
    from star.stream_route_measured_evaluator import IndependentlyScoredRouteRun
    base_run = IndependentlyScoredRouteRun(
        "base", c.profile_for("base"), NOW - 50, tuple(
            IndependentlyScoredAttempt(case.case_sha256, h(f"base-{i}"), True, 600, 2900)
            for i, case in enumerate(suite.cases)
        ),
    )
    fast_run = IndependentlyScoredRouteRun(
        "fast", c.profile_for("fast"), NOW - 50, tuple(
            IndependentlyScoredAttempt(case.case_sha256, h(f"fast-{i}"), i != 2, 200, 2900)
            for i, case in enumerate(suite.cases)
        ),
    )
    regressed = assemble_measured_route_evidence(
        host_key=KEY, catalog=c, suite=suite,
        expected_suite_sha256=suite.suite_sha256, baseline=base_run,
        candidate=fast_run, evaluator_build_sha256=BUILD,
        issued_unix_s=NOW - 10,
    )
    db = tmp_path / "claims.sqlite3"
    result = claim(db, c=c, bundle=regressed, suite=suite)
    assert not result.recorded and result.reason == "no_faster_verified_candidate"
    assert not db.exists()


def test_prior_claim_cannot_be_updated_or_deleted_via_sql(tmp_path):
    c, bundle, suite = fixture()
    db = tmp_path / "claims.sqlite3"
    assert claim(db, c=c, bundle=bundle, suite=suite).recorded
    with sqlite3.connect(db) as conn:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute("UPDATE route_pilot_claims SET candidate_alias='other'")
        with pytest.raises(sqlite3.IntegrityError, match="cannot be deleted"):
            conn.execute("DELETE FROM route_pilot_claims")


def test_symlink_and_insecure_preexisting_database_rejected(tmp_path):
    c, bundle, suite = fixture()
    db = tmp_path / "claims.sqlite3"
    target = tmp_path / "target.sqlite3"
    target.write_bytes(b"")
    db.symlink_to(target)
    with pytest.raises(ValueError, match="private regular"):
        claim(db, c=c, bundle=bundle, suite=suite)
    db.unlink()
    db.touch(mode=0o644)
    os.chmod(db, 0o644)
    with pytest.raises(ValueError, match="private regular"):
        claim(db, c=c, bundle=bundle, suite=suite)


def test_corrupt_ledger_fails_closed_without_recreation(tmp_path):
    c, bundle, suite = fixture()
    db = tmp_path / "claims.sqlite3"
    db.write_bytes(b"not a sqlite database")
    os.chmod(db, 0o600)
    with pytest.raises(sqlite3.DatabaseError):
        claim(db, c=c, bundle=bundle, suite=suite)
    assert db.read_bytes() == b"not a sqlite database"


def test_untrusted_parent_directory_cannot_hold_claims(tmp_path):
    c, bundle, suite = fixture()
    shared = tmp_path / "shared"
    shared.mkdir()
    os.chmod(shared, 0o777)
    with pytest.raises(ValueError, match="parent directory"):
        claim(shared / "claims.sqlite3", c=c, bundle=bundle, suite=suite)
    assert not (shared / "claims.sqlite3").exists()
