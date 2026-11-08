"""STAR's fail-closed, cross-run holdout reservation tests."""

from __future__ import annotations

from dataclasses import replace
import sqlite3

import pytest

from star.game_holdout_once_ledger import HoldoutOnceLedger
from star.game_realtime_gap_audit import GameModeGapPair, GameModeGapProtocol
from star.game_skill_gate import GamePerformanceTrial

SECRET = b"independent-owner-test-secret-not-production"


def evidence(offset: int = 0, scope: str = "private_game"):
    cases = tuple((f"secret_scene_{i // 10}", offset + 2341 + i) for i in range(20))
    protocol = GameModeGapProtocol(scope, cases)
    pairs = []
    for index, (scene, seed) in enumerate(cases):
        shared = dict(game_scope=scope, scenario_id=scene, seed=seed, split="holdout", host_verified=True)
        pairs.append(
            GameModeGapPair(
                paused=GamePerformanceTrial(
                    case_id=f"p_{offset}_{index}",
                    mode="paused",
                    success=True,
                    progress=1.0,
                    action_delay_ms=80,
                    **shared,
                ),
                realtime=GamePerformanceTrial(
                    case_id=f"r_{offset}_{index}",
                    mode="realtime",
                    success=index >= 5,
                    progress=0.8,
                    action_delay_ms=130,
                    **shared,
                ),
                matching_start_verified=True,
                independent_outcome_verified=True,
                realtime_scene_deadline_ms=300,
            )
        )
    return protocol, pairs


@pytest.fixture
def ledger(tmp_path):
    l = HoldoutOnceLedger(tmp_path / "used.sqlite", hmac_secret=SECRET)
    yield l
    l.close()


def test_disabled_by_default(ledger):
    protocol, _ = evidence()
    with pytest.raises(PermissionError):
        ledger.reserve(protocol)
    assert ledger.counts() == {}


def test_single_owner_review_receipt(ledger):
    protocol, pairs = evidence()
    receipt = ledger.reserve(protocol, owner_approved=True)
    assert len(receipt.receipt) == 32
    assert receipt.case_count == 20
    assert receipt.protocol_sha256 == protocol.digest
    assert not receipt.authorizes_play
    assert not receipt.authorizes_streaming
    assert ledger.counts() == {"reserved": 1}
    outcome = ledger.finalize(protocol, pairs, receipt=receipt)
    assert outcome.atlas.paired_cases == 20
    assert outcome.status == "owner_review_only"
    assert not outcome.authorizes_training
    assert not outcome.authorizes_promotion
    assert ledger.counts() == {"finalized": 1}


def test_repeated_reservation_blocked_even_before_results(ledger):
    protocol, _ = evidence()
    ledger.reserve(protocol, owner_approved=True)
    with pytest.raises(ValueError, match="already reserved"):
        ledger.reserve(protocol, owner_approved=True)


def test_partial_cohort_overlap_blocked(ledger):
    original, _ = evidence()
    ledger.reserve(original, owner_approved=True)
    overlapping = GameModeGapProtocol(
        original.game_scope,
        original.cases[:10] + tuple(("secret_scene_1", 10000 + i) for i in range(10)),
    )
    with pytest.raises(ValueError, match="already reserved"):
        ledger.reserve(overlapping, owner_approved=True)
    fresh, _ = evidence(offset=9999)
    ledger.reserve(fresh, owner_approved=True)
    assert ledger.counts() == {"reserved": 2}


def test_finalize_cannot_repeat(ledger):
    protocol, pairs = evidence()
    token = ledger.reserve(protocol, owner_approved=True)
    ledger.finalize(protocol, pairs, receipt=token)
    with pytest.raises(ValueError, match="consumed"):
        ledger.finalize(protocol, pairs, receipt=token)


@pytest.mark.parametrize("bad", ["bad", None, (), [1], 34, {"x"}])
def test_malformed_results_seal_irrevocably(ledger, bad):
    protocol, pairs = evidence()
    token = ledger.reserve(protocol, owner_approved=True)
    with pytest.raises((ValueError, TypeError)):
        ledger.finalize(protocol, bad, receipt=token)
    assert ledger.counts() == {"invalid": 1}
    with pytest.raises(ValueError, match="consumed"):
        ledger.finalize(protocol, pairs, receipt=token)
    with pytest.raises(ValueError, match="already reserved"):
        ledger.reserve(protocol, owner_approved=True)


def test_invalid_protocol_deadline_seals_cohort(ledger):
    protocol, pairs = evidence()
    token = ledger.reserve(protocol, owner_approved=True)
    changed = [replace(pairs[0], realtime_scene_deadline_ms=500), *pairs[1:]]
    with pytest.raises((ValueError, TypeError)):
        ledger.finalize(protocol, changed, receipt=token)
    assert ledger.counts() == {"invalid": 1}


def test_cancelled_cohort_remains_consumed(ledger):
    protocol, pairs = evidence()
    token = ledger.reserve(protocol, owner_approved=True)
    ledger.abandon(protocol, receipt=token)
    assert ledger.counts() == {"abandoned": 1}
    with pytest.raises(ValueError):
        ledger.finalize(protocol, pairs, receipt=token)
    with pytest.raises(ValueError):
        ledger.reserve(protocol, owner_approved=True)


def test_receipt_cannot_switch_protocol_or_be_forged(ledger):
    protocol, pairs = evidence()
    token = ledger.reserve(protocol, owner_approved=True)
    changed, _ = evidence(offset=100)
    with pytest.raises(ValueError):
        ledger.finalize(changed, pairs, receipt=token)
    with pytest.raises(ValueError):
        ledger.finalize(protocol, pairs, receipt=replace(token, receipt="f" * 32))
    assert ledger.counts() == {"reserved": 1}
    assert ledger.finalize(protocol, pairs, receipt=token).atlas.paired_cases == 20


def test_new_seeds_are_eligible(ledger):
    protocol, _ = evidence()
    ledger.reserve(protocol, owner_approved=True)
    fresh, pairs = evidence(offset=1000)
    token = ledger.reserve(fresh, owner_approved=True)
    assert ledger.finalize(fresh, pairs, receipt=token).atlas.paired_cases == 20


def test_reverse_order_results_still_valid(ledger):
    protocol, pairs = evidence()
    token = ledger.reserve(protocol, owner_approved=True)
    assert ledger.finalize(protocol, list(reversed(pairs)), receipt=token).atlas.paired_cases == 20


def test_registry_reopens_with_same_secret(tmp_path):
    path = tmp_path / "once.sqlite"
    protocol, _ = evidence()
    one = HoldoutOnceLedger(path, hmac_secret=SECRET)
    one.reserve(protocol, owner_approved=True)
    one.close()
    two = HoldoutOnceLedger(path, hmac_secret=SECRET)
    with pytest.raises(ValueError, match="already reserved"):
        two.reserve(protocol, owner_approved=True)
    assert two.counts() == {"reserved": 1}
    two.close()


def test_second_connection_cannot_reassign(tmp_path):
    path = tmp_path / "race.sqlite"
    a = HoldoutOnceLedger(path, hmac_secret=SECRET)
    b = HoldoutOnceLedger(path, hmac_secret=SECRET)
    protocol, _ = evidence()
    a.reserve(protocol, owner_approved=True)
    with pytest.raises(ValueError):
        b.reserve(protocol, owner_approved=True)
    a.close()
    b.close()


def test_wrong_key_cannot_open_existing_registry(tmp_path):
    path = tmp_path / "once.sqlite"
    first = HoldoutOnceLedger(path, hmac_secret=SECRET)
    first.close()
    with pytest.raises(ValueError, match="different HMAC"):
        HoldoutOnceLedger(path, hmac_secret=b"c" * 32)


@pytest.mark.parametrize("secret", ["string", b"", b"x" * 31, b"x" * 129, b"\0" * 32])
def test_reject_fake_or_too_short_secret(tmp_path, secret):
    with pytest.raises(ValueError):
        HoldoutOnceLedger(tmp_path / "wrong.sqlite", hmac_secret=secret)


def test_unsafe_paths_rejected(tmp_path):
    for path in ("relative.db", tmp_path / "missing" / "db.sqlite"):
        with pytest.raises(ValueError):
            HoldoutOnceLedger(path, hmac_secret=SECRET)
    link = tmp_path / "link.sqlite"
    link.symlink_to(tmp_path / "actual.sqlite")
    with pytest.raises(ValueError):
        HoldoutOnceLedger(link, hmac_secret=SECRET)


def test_hardlinks_rejected(tmp_path):
    path = tmp_path / "once.sqlite"
    l = HoldoutOnceLedger(path, hmac_secret=SECRET)
    l.close()
    duplicate = tmp_path / "duplicate.sqlite"
    duplicate.hardlink_to(path)
    with pytest.raises(ValueError):
        HoldoutOnceLedger(duplicate, hmac_secret=SECRET)


def test_database_contains_only_opaque_tokens(tmp_path):
    path = tmp_path / "private.sqlite"
    l = HoldoutOnceLedger(path, hmac_secret=SECRET)
    protocol, pairs = evidence(scope="secret_scope")
    ticket = l.reserve(protocol, owner_approved=True)
    l.finalize(protocol, pairs, receipt=ticket)
    l.close()
    con = sqlite3.connect(path)
    rows = repr(con.execute("SELECT * FROM holdout_cases").fetchall())
    rows += repr(con.execute("SELECT * FROM holdout_runs").fetchall())
    con.close()
    assert "secret_scene" not in rows and "secret_scope" not in rows
    assert "2341" not in rows
