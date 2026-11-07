"""Offline adversarial tests of optional host-signed game moment provenance."""
from __future__ import annotations

from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor

import pytest

from star.stream_episode_journal import GameMoment, StreamEpisodeJournal
from star.stream_moment_receipts import SignedGameMoment, sign_game_moment


KEY = b"A" * 32
WRONG_KEY = b"B" * 32


def gm(moment_id="checkpoint_1", *, game="obby", kind="checkpoint", at=100.0, stage="bridge"):
    return GameMoment(moment_id, game, kind, at, stage)


def signed(journal, moment, sequence, key=KEY):
    return sign_game_moment(moment, session_id=journal.session_id, sequence=sequence, key=key)


def protected_journal(**kwargs):
    journal = StreamEpisodeJournal(receipt_key=KEY, **kwargs)
    journal.enable(owner_approved=True)
    assert len(journal.session_id) == 32
    return journal


def test_default_host_flag_remains_legacy_not_cryptographic():
    journal = StreamEpisodeJournal()
    journal.enable(owner_approved=True)
    assert journal.record(gm(), now_s=100.0, host_observed=True)
    assert journal.metrics()["signed_receipts_required"] is False


def test_signed_session_admits_only_exact_authenticated_moment():
    journal = protected_journal()
    first = gm()
    receipt = signed(journal, first, 1)
    assert "mac=" not in repr(receipt)
    assert journal.record(first, now_s=100, host_observed=True, receipt=receipt)
    assert journal.metrics()["signed_receipts_required"] is True
    assert journal.recall(now_s=101, game_scope="obby")[0].context.endswith("on stage bridge.")


@pytest.mark.parametrize("changed", [
    {"kind": "win"}, {"game_scope": "arena"}, {"moment_id": "other"},
    {"stage_id": "castle"}, {"at_s": 100.1},
])
def test_mac_binds_every_game_fact(changed):
    journal = protected_journal()
    first = gm()
    receipt = signed(journal, first, 1)
    forged = replace(first, **changed)
    assert not journal.record(forged, now_s=99999, host_observed=True, receipt=receipt)
    assert journal.record(first, now_s=100, host_observed=True, receipt=receipt)
    assert journal.metrics()["invalid_receipts"] == 1


def test_missing_wrong_key_or_foreign_session_cannot_claim_a_win():
    journal = protected_journal()
    first = gm(kind="win")
    assert not journal.record(first, now_s=100, host_observed=True)
    assert not journal.record(first, now_s=100, host_observed=True, receipt=signed(journal, first, 1, WRONG_KEY))
    prior = journal.session_id
    journal.disable()
    journal.enable(owner_approved=True)
    assert journal.session_id != prior
    old_proof = sign_game_moment(first, session_id=prior, sequence=1, key=KEY)
    assert not journal.record(first, now_s=100, host_observed=True, receipt=old_proof)
    assert journal.record(first, now_s=100, host_observed=True, receipt=signed(journal, first, 1))
    assert journal.metrics()["invalid_receipts"] == 3


def test_replay_and_reordered_sequence_fail_without_erasing_history():
    journal = protected_journal()
    first = gm("a", at=100)
    second = gm("b", kind="loss", at=101)
    assert journal.record(first, now_s=100, host_observed=True, receipt=signed(journal, first, 10))
    assert not journal.record(first, now_s=100, host_observed=True, receipt=signed(journal, first, 10))
    assert not journal.record(second, now_s=99999, host_observed=True, receipt=signed(journal, second, 9))
    assert journal.record(second, now_s=101, host_observed=True, receipt=signed(journal, second, 11))
    assert journal.metrics()["out_of_order_receipts"] == 2
    assert journal.metrics()["retained"] == 2


def test_scopes_have_separate_sequences_and_hmac_cannot_cross_scope():
    journal = protected_journal()
    a = gm("same", game="game_a")
    b = gm("same", game="game_b")
    assert journal.record(a, now_s=100, host_observed=True, receipt=signed(journal, a, 99))
    assert journal.record(b, now_s=100, host_observed=True, receipt=signed(journal, b, 1))
    assert not journal.record(gm("fake", game="game_b", kind="win"),
                              now_s=100, host_observed=True, receipt=signed(journal, a, 100))
    assert journal.metrics()["retained"] == 2


def test_unattested_claim_and_invalid_proof_do_not_move_time_or_consume_id():
    journal = protected_journal(max_age_s=60)
    legit = gm()
    proof = signed(journal, legit, 1)
    assert not journal.record(legit, now_s=100000, host_observed=False, receipt=proof)
    assert not journal.record(legit, now_s=100000, host_observed=True, receipt=signed(journal, legit, 1, WRONG_KEY))
    assert journal.record(legit, now_s=100, host_observed=True, receipt=proof)
    assert len(journal.recall(now_s=101, game_scope="obby")) == 1


def test_signed_receipts_are_rejected_by_legacy_mode():
    journal = StreamEpisodeJournal()
    journal.enable(owner_approved=True)
    first = gm()
    receipt = signed(journal, first, 1)
    assert not journal.record(first, now_s=100, host_observed=True, receipt=receipt)
    assert journal.record(first, now_s=100, host_observed=True)


def test_signature_rejects_invalid_secret_and_malformed_sequence():
    with pytest.raises(ValueError):
        StreamEpisodeJournal(receipt_key=b"123")
    with pytest.raises(ValueError):
        StreamEpisodeJournal(receipt_key=bytearray(KEY))
    journal = protected_journal()
    with pytest.raises(ValueError):
        signed(journal, gm(), 0)
    with pytest.raises(ValueError):
        SignedGameMoment(journal.session_id, True, "0" * 64)


def test_parallel_receipts_do_not_bypass_monotonic_sequence():
    journal = protected_journal()
    evt = gm()
    receipt = signed(journal, evt, 1)
    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(
            lambda _: journal.record(evt, now_s=100, host_observed=True, receipt=receipt),
            range(30),
        ))
    assert sum(results) == 1
    assert journal.metrics()["retained"] == 1


def test_disable_drops_old_receipts_and_memory():
    journal = protected_journal()
    first = gm(kind="win")
    proof = signed(journal, first, 7)
    assert journal.record(first, now_s=100, host_observed=True, receipt=proof)
    journal.disable()
    assert journal.session_id is None
    assert journal.recall(now_s=100, game_scope="obby") == ()
    journal.enable(owner_approved=True)
    assert not journal.record(first, now_s=100, host_observed=True, receipt=proof)
    assert journal.record(first, now_s=100, host_observed=True, receipt=signed(journal, first, 1))
