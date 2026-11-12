from __future__ import annotations

import hashlib
import hmac

import pytest

from star.gameplay_skill_bank import GameTrial, GameplaySkillBank
from star.stream_continuity import StreamContinuityStore

PRACTICE_KEY = b"p" * 32
VALIDATION_KEY = b"v" * 32
NOW = 1_800_000_000


def make_bank() -> GameplaySkillBank:
    return GameplaySkillBank(
        ":memory:", practice_key=PRACTICE_KEY, validation_key=VALIDATION_KEY
    )


def add_trial(
    bank: GameplaySkillBank,
    *,
    trial_id: str,
    run_id: str,
    action_id: str = "jump",
    game_id: str = "obby",
    game_version: str = "v1",
    outcome: str = "success",
    split: str = "practice",
    observed_unix_s: int = NOW - 60,
) -> GameTrial:
    trial = GameTrial(
        trial_id=trial_id,
        game_id=game_id,
        game_version=game_version,
        objective_id="checkpoint",
        situation_id="gap-a",
        action_id=action_id,
        run_id=run_id,
        split=split,
        outcome=outcome,
        evidence_sha256=hashlib.sha256(trial_id.encode("ascii")).hexdigest(),
        observed_unix_s=observed_unix_s,
    )
    key = PRACTICE_KEY if split == "practice" else VALIDATION_KEY
    receipt = hmac.new(key, trial.canonical_bytes(), hashlib.sha256).hexdigest()
    bank.ingest(trial, receipt, now_unix_s=NOW)
    return trial


def enabled_store(
    bank: GameplaySkillBank,
    database: str = ":memory:",
    *,
    max_records: int = 5_000,
    retention_seconds: int = 30 * 86400,
) -> StreamContinuityStore:
    store = StreamContinuityStore(
        database, bank, max_records=max_records, retention_seconds=retention_seconds
    )
    store.enable(owner_approved=True)
    return store


def packet(
    store: StreamContinuityStore,
    *,
    now: int = NOW,
    stream_session_id: str = "current-stream",
):
    return store.packet(
        game_id="obby",
        game_version="v1",
        stream_session_id=stream_session_id,
        now_unix_s=now,
        public_action_labels={"jump": "Gap jump"},
        broadcast_approved=True,
    )


def test_store_is_off_by_default_and_each_write_needs_owner_approval():
    bank = make_bank()
    trial = add_trial(bank, trial_id="trial-1", run_id="run-1")
    store = StreamContinuityStore(":memory:", bank)
    with pytest.raises(PermissionError):
        store.remember(trial, session_id="session-1", now_unix_s=NOW, owner_approved=True)
    with pytest.raises(PermissionError):
        store.enable()
    store.enable(owner_approved=True)
    with pytest.raises(PermissionError):
        store.remember(trial, session_id="session-1", now_unix_s=NOW)
    assert store.remember(
        trial, session_id="session-1", now_unix_s=NOW, owner_approved=True
    )


def test_cross_session_recall_aggregates_only_signed_practice():
    bank = make_bank()
    first = add_trial(bank, trial_id="trial-1", run_id="run-1", outcome="failure")
    second = add_trial(
        bank, trial_id="trial-2", run_id="run-2", outcome="success",
        observed_unix_s=NOW - 30,
    )
    store = enabled_store(bank)
    assert store.remember(first, session_id="session-1", now_unix_s=NOW, owner_approved=True)
    assert store.remember(second, session_id="session-2", now_unix_s=NOW, owner_approved=True)
    result = packet(store)
    assert result is not None
    assert result.facts[0].label == "Gap jump"
    assert result.facts[0].attempts == 2
    assert result.facts[0].successes == 1
    assert result.facts[0].failures == 1
    assert result.facts[0].most_recent_outcome == "success"
    assert result.user_message()["role"] == "user"
    for private_id in ("trial-1", "trial-2", "run-1", "run-2", "session-1", "session-2", '"jump"'):
        assert private_id not in result.context_record


def test_validation_trials_never_enter_stream_continuity():
    bank = make_bank()
    trial = add_trial(
        bank, trial_id="trial-validation", run_id="run-validation", split="validation"
    )
    store = enabled_store(bank)
    with pytest.raises(PermissionError):
        store.remember(
            trial, session_id="session-1", now_unix_s=NOW, owner_approved=True
        )
    assert packet(store) is None


def test_unrecorded_or_unsigned_trial_is_rejected():
    bank = make_bank()
    trial = GameTrial(
        trial_id="trial-unrecorded",
        game_id="obby",
        game_version="v1",
        objective_id="checkpoint",
        situation_id="gap-a",
        action_id="jump",
        run_id="run-unrecorded",
        split="practice",
        outcome="success",
        evidence_sha256="a" * 64,
        observed_unix_s=NOW - 60,
    )
    store = enabled_store(bank)
    with pytest.raises(PermissionError):
        store.remember(
            trial, session_id="session-1", now_unix_s=NOW, owner_approved=True
        )


def test_duplicate_trial_is_idempotently_rejected():
    bank = make_bank()
    trial = add_trial(bank, trial_id="trial-1", run_id="run-1")
    store = enabled_store(bank)
    assert store.remember(trial, session_id="session-1", now_unix_s=NOW, owner_approved=True)
    assert not store.remember(
        trial, session_id="session-2", now_unix_s=NOW, owner_approved=True
    )
    assert store.metrics()["retained"] == 1
    assert store.metrics()["duplicate_rejected"] == 1


def test_broadcast_approval_is_required_for_a_public_packet():
    bank = make_bank()
    trial = add_trial(bank, trial_id="trial-1", run_id="run-1")
    store = enabled_store(bank)
    store.remember(trial, session_id="session-1", now_unix_s=NOW, owner_approved=True)
    assert store.packet(
        game_id="obby", game_version="v1", stream_session_id="stream-1", now_unix_s=NOW,
        public_action_labels={"jump": "Gap jump"},
    ) is None


def test_exact_game_and_version_scope_prevents_stale_callbacks():
    bank = make_bank()
    trial = add_trial(bank, trial_id="trial-1", run_id="run-1")
    store = enabled_store(bank)
    store.remember(trial, session_id="session-1", now_unix_s=NOW, owner_approved=True)
    assert store.packet(
        game_id="different-game", game_version="v1", stream_session_id="stream-1", now_unix_s=NOW,
        public_action_labels={"jump": "Gap jump"}, broadcast_approved=True,
    ) is None
    assert store.packet(
        game_id="obby", game_version="v2", stream_session_id="stream-1", now_unix_s=NOW,
        public_action_labels={"jump": "Gap jump"}, broadcast_approved=True,
    ) is None


def test_expired_memory_is_purged_before_retrieval():
    bank = make_bank()
    trial = add_trial(bank, trial_id="trial-1", run_id="run-1")
    store = enabled_store(bank, retention_seconds=3_600)
    store.remember(trial, session_id="session-1", now_unix_s=NOW, owner_approved=True)
    assert packet(store, now=NOW + 3_601) is None
    assert store.metrics()["retained"] == 0
    assert store.metrics()["expired"] == 1


def test_store_capacity_fails_closed_without_evicting_old_rows():
    bank = make_bank()
    first = add_trial(bank, trial_id="trial-1", run_id="run-1")
    second = add_trial(bank, trial_id="trial-2", run_id="run-2")
    store = enabled_store(bank, max_records=1)
    assert store.remember(first, session_id="session-1", now_unix_s=NOW, owner_approved=True)
    with pytest.raises(OverflowError):
        store.remember(second, session_id="session-2", now_unix_s=NOW, owner_approved=True)
    assert store.metrics()["retained"] == 1


def test_clock_regression_is_rejected():
    bank = make_bank()
    trial = add_trial(bank, trial_id="trial-1", run_id="run-1")
    store = enabled_store(bank)
    store.remember(trial, session_id="session-1", now_unix_s=NOW, owner_approved=True)
    with pytest.raises(ValueError):
        packet(store, now=NOW - 1)


def test_public_labels_are_strict_curated_plain_text():
    bank = make_bank()
    trial = add_trial(bank, trial_id="trial-1", run_id="run-1")
    store = enabled_store(bank)
    store.remember(trial, session_id="session-1", now_unix_s=NOW, owner_approved=True)
    with pytest.raises(ValueError):
        store.packet(
            game_id="obby", game_version="v1", stream_session_id="stream-1", now_unix_s=NOW,
            public_action_labels={"jump": "<script>alert(1)</script>"},
            broadcast_approved=True,
        )


def test_disable_blocks_both_retention_and_retrieval():
    bank = make_bank()
    trial = add_trial(bank, trial_id="trial-1", run_id="run-1")
    store = enabled_store(bank)
    store.remember(trial, session_id="session-1", now_unix_s=NOW, owner_approved=True)
    store.disable()
    with pytest.raises(PermissionError):
        store.remember(
            trial, session_id="session-2", now_unix_s=NOW, owner_approved=True
        )
    assert packet(store) is None
    assert store.metrics()["retained"] == 1


def test_clear_requires_explicit_owner_approval_and_only_clears_this_store():
    bank = make_bank()
    trial = add_trial(bank, trial_id="trial-1", run_id="run-1")
    store = enabled_store(bank)
    store.remember(trial, session_id="session-1", now_unix_s=NOW, owner_approved=True)
    with pytest.raises(PermissionError):
        store.clear()
    assert store.clear(owner_approved=True) == 1
    assert store.metrics()["retained"] == 0
    assert bank.verify_practice_trial(trial, now_unix_s=NOW)


def test_sqlite_persistence_survives_reopening(tmp_path):
    bank = make_bank()
    trial = add_trial(bank, trial_id="trial-1", run_id="run-1")
    database = tmp_path / "continuity.sqlite"
    first = enabled_store(bank, str(database))
    first.remember(trial, session_id="session-1", now_unix_s=NOW, owner_approved=True)
    first.close()
    second = enabled_store(bank, str(database))
    result = packet(second)
    assert result is not None
    assert result.facts[0].attempts == 1
    second.close()


def test_session_ids_are_hashed_and_metrics_are_aggregate_only():
    bank = make_bank()
    trial = add_trial(bank, trial_id="trial-1", run_id="run-1")
    store = enabled_store(bank)
    store.remember(trial, session_id="private-session-id", now_unix_s=NOW, owner_approved=True)
    metrics = store.metrics()
    assert metrics["distinct_sessions"] == 1
    assert "private-session-id" not in repr(metrics)
    assert "trial-1" not in repr(metrics)


def test_bad_session_identifiers_are_rejected():
    bank = make_bank()
    trial = add_trial(bank, trial_id="trial-1", run_id="run-1")
    store = enabled_store(bank)
    with pytest.raises(ValueError):
        store.remember(
            trial, session_id="contains spaces", now_unix_s=NOW, owner_approved=True
        )


def test_old_evidence_cannot_be_retained():
    bank = make_bank()
    old = add_trial(
        bank, trial_id="trial-old", run_id="run-old",
        observed_unix_s=NOW - 31 * 86400,
    )
    store = enabled_store(bank, retention_seconds=30 * 86400)
    with pytest.raises(ValueError):
        store.remember(
            old, session_id="session-old", now_unix_s=NOW, owner_approved=True
        )


def test_future_evidence_cannot_be_retained():
    bank = make_bank()
    future = add_trial(
        bank, trial_id="trial-future", run_id="run-future",
        observed_unix_s=NOW + 5,
    )
    store = enabled_store(bank)
    with pytest.raises(ValueError):
        store.remember(
            future, session_id="session-future", now_unix_s=NOW, owner_approved=True
        )


def test_empty_or_oversized_public_label_map_is_rejected():
    bank = make_bank()
    store = enabled_store(bank)
    with pytest.raises(ValueError):
        store.packet(
            game_id="obby", game_version="v1", stream_session_id="stream-1", now_unix_s=NOW,
            public_action_labels={}, broadcast_approved=True,
        )
    with pytest.raises(ValueError):
        store.packet(
            game_id="obby", game_version="v1", stream_session_id="stream-1", now_unix_s=NOW,
            public_action_labels={f"a{i}": "Action" for i in range(33)},
            broadcast_approved=True,
        )



def test_callback_ticket_is_host_only_and_prevents_repetition_after_audible_ack():
    bank = make_bank()
    trial = add_trial(bank, trial_id="trial-1", run_id="run-1")
    store = enabled_store(bank)
    store.remember(trial, session_id="practice-session", now_unix_s=NOW, owner_approved=True)

    first = packet(store, stream_session_id="broadcast-1")
    assert first is not None
    assert first.ticket not in first.context_record
    assert packet(store, stream_session_id="broadcast-1") is None
    assert not store.complete_callback(
        first.ticket, now_unix_s=NOW, playback_confirmed=False
    )

    second = packet(store, stream_session_id="broadcast-1")
    assert second is not None
    assert store.complete_callback(
        second.ticket, now_unix_s=NOW, playback_confirmed=True
    )
    assert packet(store, stream_session_id="broadcast-1") is None
    assert packet(store, stream_session_id="broadcast-2") is not None


def test_pending_callback_expiry_releases_the_offer():
    bank = make_bank()
    trial = add_trial(bank, trial_id="trial-1", run_id="run-1")
    store = enabled_store(bank)
    store.remember(trial, session_id="practice-session", now_unix_s=NOW, owner_approved=True)
    first = packet(store, stream_session_id="broadcast-1")
    assert first is not None
    second = packet(store, now=NOW + 901, stream_session_id="broadcast-1")
    assert second is not None
    assert second.ticket != first.ticket
    assert store.metrics()["callbacks_expired"] == 1
    assert not store.complete_callback(
        first.ticket, now_unix_s=NOW + 901, playback_confirmed=True
    )


def test_callback_completion_requires_valid_host_receipt_shape():
    bank = make_bank()
    trial = add_trial(bank, trial_id="trial-1", run_id="run-1")
    store = enabled_store(bank)
    store.remember(trial, session_id="practice-session", now_unix_s=NOW, owner_approved=True)
    offer = packet(store)
    assert offer is not None
    with pytest.raises(ValueError):
        store.complete_callback("not-a-ticket", now_unix_s=NOW, playback_confirmed=True)
    with pytest.raises(ValueError):
        store.complete_callback(offer.ticket, now_unix_s=NOW, playback_confirmed=1)  # type: ignore[arg-type]


def test_multiple_pending_callbacks_are_bounded_and_disable_cancels_them():
    bank = make_bank()
    trial = add_trial(bank, trial_id="trial-1", run_id="run-1")
    store = enabled_store(bank)
    store.remember(trial, session_id="practice-session", now_unix_s=NOW, owner_approved=True)
    offer = packet(store)
    assert offer is not None
    assert store.metrics()["pending_callbacks"] == 1
    store.disable()
    assert store.metrics()["pending_callbacks"] == 0
    assert store.metrics()["callbacks_cancelled"] == 1
    assert not store.complete_callback(
        offer.ticket, now_unix_s=NOW, playback_confirmed=True
    )
