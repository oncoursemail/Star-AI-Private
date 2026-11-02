"""Cross-session verified STAR memory: trust, retention, consent and repair."""
from __future__ import annotations

from hashlib import sha256
import hmac
import sqlite3
import threading

import pytest

from star.gameplay_skill_bank import GameTrial, GameplaySkillBank
from star.stream_continuity import StreamContinuityVault

NOW = 1_800_000_000
PRACTICE = b"practice-host-only-signer-012345678901234567890"
VALIDATION = b"validation-independent-key-01234567890123456"
MEMORY = b"separate-persistent-integrity-key-01234567890"
SCOPE = ("obby", "v1", "checkpoint", "ledge")


def trial(bank, index, *, at=None, outcome="success", action="jump_left",
          split="practice", game="obby", situation="ledge", verified=True):
    when = NOW + index if at is None else at
    entry = GameTrial(
        trial_id=f"t_{index}", game_id=game, game_version="v1",
        objective_id="checkpoint", situation_id=situation,
        action_id=action, run_id=f"trusted_{index}",
        split=split, outcome=outcome,
        evidence_sha256=sha256(f"evidence_{index}".encode()).hexdigest(),
        observed_unix_s=when,
    )
    if verified:
        signer = PRACTICE if split == "practice" else VALIDATION
        tag = hmac.new(signer, entry.canonical_bytes(), "sha256").hexdigest()
        bank.ingest(entry, tag, now_unix_s=when)
    return entry


def vault(bank, path, *, key=MEMORY, actions=frozenset({"jump_left"})):
    return StreamContinuityVault(
        bank, path, integrity_key=key,
        game_id=SCOPE[0], game_version=SCOPE[1],
        objective_id=SCOPE[2], situation_id=SCOPE[3],
        recordable_action_ids=actions,
    )


@pytest.fixture
def bank():
    instance = GameplaySkillBank(
        practice_key=PRACTICE, validation_key=VALIDATION,
    )
    yield instance
    instance.close()


def test_consent_signed_attempts_and_past_episode_recall(bank, tmp_path):
    db = tmp_path / "memory.db"
    with vault(bank, db) as store:
        assert store.public_packet(
            now_unix_s=NOW, public_action_ids=frozenset({"jump_left"}),
            broadcast_approved=True,
        ) is None
        with pytest.raises(PermissionError):
            store.enable()
        store.enable(owner_approved=True)
        assert store.start_episode("live_1", now_unix_s=NOW)
        failure = trial(bank, 1, outcome="failure")
        success = trial(bank, 2)
        assert store.record(failure, now_unix_s=NOW+1)
        assert store.record(success, now_unix_s=NOW+2)
        assert not store.record(success, now_unix_s=NOW+2)
        # Still live: do not fabricate a completed previous session.
        assert store.public_packet(
            now_unix_s=NOW+3, public_action_ids=frozenset({"jump_left"}),
            broadcast_approved=True,
        ) is None
        assert store.finish_episode(now_unix_s=NOW+3)
        assert store.public_packet(
            now_unix_s=NOW+3, public_action_ids=frozenset({"jump_left"})
        ) is None
        packet = store.public_packet(
            now_unix_s=NOW+3, public_action_ids=frozenset({"jump_left"}),
            broadcast_approved=True,
        )
        assert packet is not None
        assert packet.action_ids == ("jump_left",)
        assert packet.game_scope == store.game_scope
        assert packet.game_scope.startswith("episode.")
        # Independent producers must use the *whole* game/version/objective/
        # situation identity, rather than just the shared game title.
        from star.stream_episode import StreamEpisode
        same = StreamEpisode(
            bank, game_id=SCOPE[0], game_version=SCOPE[1],
            objective_id=SCOPE[2], situation_id=SCOPE[3],
        )
        different = StreamEpisode(
            bank, game_id=SCOPE[0], game_version=SCOPE[1],
            objective_id=SCOPE[2], situation_id="different_level",
        )
        assert same.game_scope == store.game_scope
        assert different.game_scope != store.game_scope
        assert '"successes":1' in packet.context_record
        assert '"failures":1' in packet.context_record
        assert '"success_after_prior_failure":true' in packet.context_record
        assert "mastered skill" in packet.context_record
        assert packet.user_message()["role"] == "user"
        assert "trusted_1" not in packet.context_record
        assert "evidence_1" not in packet.context_record
        assert "live_1" not in packet.context_record
        assert "jump_left" not in str(store.status())
    # Exact durable facts survive restarting the process with the same key.
    with vault(bank, db) as store:
        store.enable(owner_approved=True)
        packet = store.public_packet(
            now_unix_s=NOW+4, public_action_ids=frozenset({"jump_left"}),
            broadcast_approved=True,
        )
        assert packet is not None and '"successes":1' in packet.context_record


def test_forbid_forged_unsigned_holdout_private_wrong_game_and_old_events(bank, tmp_path):
    with vault(bank, tmp_path/"x.sqlite") as store:
        store.enable(owner_approved=True)
        assert store.start_episode("session_A", now_unix_s=NOW)
        assert not store.record(trial(bank, 1, verified=False), now_unix_s=NOW+1)
        assert not store.record(trial(bank, 2, split="validation"),
                                now_unix_s=NOW+2)
        assert not store.record(trial(bank, 3, action="private_path"),
                                now_unix_s=NOW+3)
        assert not store.record(trial(bank, 4, game="other"),
                                now_unix_s=NOW+4)
        assert not store.record(trial(bank, 5, situation="hidden"),
                                now_unix_s=NOW+5)
        assert not store.record(trial(bank, 6), now_unix_s=NOW+40)
        assert store.status()["events"] == 0
        assert not store.start_episode("session_B", now_unix_s=NOW+40)


def test_no_cross_session_replay_and_explicit_forget(bank, tmp_path):
    with vault(bank, tmp_path/"x.sqlite") as store:
        store.enable(owner_approved=True)
        assert store.start_episode("first", now_unix_s=NOW)
        signed = trial(bank, 1)
        assert store.record(signed, now_unix_s=NOW+1)
        assert store.finish_episode(now_unix_s=NOW+2)
        assert store.start_episode("second", now_unix_s=NOW+3)
        assert not store.record(signed, now_unix_s=NOW+3)
        assert store.finish_episode(now_unix_s=NOW+3)
        assert not store.start_episode("first", now_unix_s=NOW+4)
        with pytest.raises(PermissionError):
            store.forget_all()
        store.forget_all(owner_approved=True)
        assert store.status()["events"] == 0
        assert store.public_packet(
            now_unix_s=NOW+4, public_action_ids=frozenset({"jump_left"}),
            broadcast_approved=True,
        ) is None
        store.enable(owner_approved=True)
        assert store.start_episode("first", now_unix_s=NOW+4)


def test_tampering_and_wrong_integrity_key_produce_silence(bank, tmp_path):
    path = tmp_path/"x.sqlite"
    with vault(bank, path) as store:
        store.enable(owner_approved=True)
        assert store.start_episode("one", now_unix_s=NOW)
        assert store.record(trial(bank, 1), now_unix_s=NOW+1)
        assert store.finish_episode(now_unix_s=NOW+2)
    with vault(bank, path, key=b"completely-wrong-integrity-key-0123456789012") as store:
        store.enable(owner_approved=True)
        assert store.public_packet(
            now_unix_s=NOW+3, public_action_ids=frozenset({"jump_left"}),
            broadcast_approved=True,
        ) is None
        assert store.status()["integrity_failures"] == 1
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE continuity_events SET outcome='failure'")
    with vault(bank, path) as store:
        store.enable(owner_approved=True)
        assert store.public_packet(
            now_unix_s=NOW+3, public_action_ids=frozenset({"jump_left"}),
            broadcast_approved=True,
        ) is None
        assert store.status()["integrity_failures"] == 1


def test_wrong_types_threads_backward_time_crash_and_expiry(bank, tmp_path):
    path = tmp_path/"x.sqlite"
    with pytest.raises(ValueError):
        vault(bank, path, actions=frozenset())
    with vault(bank, path) as store:
        with pytest.raises(ValueError):
            store.public_packet(now_unix_s=NOW,
                                public_action_ids={"jump_left"}, broadcast_approved=True)
        store.enable(owner_approved=True)
        assert store.start_episode("first", now_unix_s=NOW)
        assert store.record(trial(bank, 1), now_unix_s=NOW+1)
        with pytest.raises(ValueError):
            store.public_packet(
                now_unix_s=NOW, public_action_ids=frozenset({"jump_left"}),
                broadcast_approved=True,
            )
        errors = []
        def worker():
            try:
                store.status()
            except RuntimeError as exc:
                errors.append(str(exc))
        thread = threading.Thread(target=worker)
        thread.start()
        thread.join()
        assert len(errors) == 1 and "owner thread" in errors[0]
        store.disable()  # simulated shutdown without a finish acknowledgement
    with vault(bank, path) as store:
        store.enable(owner_approved=True)
        assert store.public_packet(
            now_unix_s=NOW+30, public_action_ids=frozenset({"jump_left"}),
            broadcast_approved=True,
        ) is None
        assert store.start_episode("second", now_unix_s=NOW+31)
        assert store.record(trial(bank, 32), now_unix_s=NOW+32)
        assert store.finish_episode(now_unix_s=NOW+33)
        assert store.public_packet(
            now_unix_s=NOW+91*86400,
            public_action_ids=frozenset({"jump_left"}), broadcast_approved=True,
        ) is None


def _other_game_vault(bank, path):
    """Second game intentionally reuses the owner's independent vault key."""
    return StreamContinuityVault(
        bank, path, integrity_key=MEMORY,
        game_id="boss", game_version="v1", objective_id="checkpoint",
        situation_id="ledge", recordable_action_ids=frozenset({"jump_left"}),
    )


def test_shared_database_scopes_session_ids_recall_and_forget(bank, tmp_path):
    path = tmp_path / "shared.sqlite"
    with vault(bank, path) as obby, _other_game_vault(bank, path) as boss:
        obby.enable(owner_approved=True)
        boss.enable(owner_approved=True)
        assert obby.start_episode("session_same", now_unix_s=NOW)
        assert boss.start_episode("session_same", now_unix_s=NOW)
        assert obby.record(trial(bank, 1, game="obby"), now_unix_s=NOW + 1)
        assert boss.record(trial(bank, 2, game="boss"), now_unix_s=NOW + 2)
        assert obby.finish_episode(now_unix_s=NOW + 3)
        assert boss.finish_episode(now_unix_s=NOW + 3)

        a = obby.public_packet(
            now_unix_s=NOW + 4, public_action_ids=frozenset({"jump_left"}),
            broadcast_approved=True,
        )
        b = boss.public_packet(
            now_unix_s=NOW + 4, public_action_ids=frozenset({"jump_left"}),
            broadcast_approved=True,
        )
        assert a is not None and '"game_id":"obby"' in a.context_record
        assert b is not None and '"game_id":"boss"' in b.context_record
        assert '"game_id":"boss"' not in a.context_record
        assert '"game_id":"obby"' not in b.context_record
        assert obby.status()["events"] == boss.status()["events"] == 1

        # An owner choosing to forget one game must not erase a second game.
        obby.forget_all(owner_approved=True)
        assert obby.status()["events"] == 0
        assert boss.status()["events"] == 1
        assert boss.public_packet(
            now_unix_s=NOW + 5, public_action_ids=frozenset({"jump_left"}),
            broadcast_approved=True,
        ) is not None
    # Reopening the other scope with the same key retains its fact.
    with _other_game_vault(bank, path) as boss:
        boss.enable(owner_approved=True)
        assert boss.public_packet(
            now_unix_s=NOW + 6, public_action_ids=frozenset({"jump_left"}),
            broadcast_approved=True,
        ) is not None


def test_other_game_recent_episodes_cannot_starve_own_memory(bank, tmp_path):
    path = tmp_path / "shared.sqlite"
    with vault(bank, path) as obby, _other_game_vault(bank, path) as boss:
        obby.enable(owner_approved=True)
        boss.enable(owner_approved=True)
        assert obby.start_episode("good_obby", now_unix_s=NOW)
        assert obby.record(trial(bank, 1), now_unix_s=NOW + 1)
        assert obby.finish_episode(now_unix_s=NOW + 2)
        for idx in range(70):
            at = NOW + 10 + idx
            assert boss.start_episode(f"quiet_{idx}", now_unix_s=at)
            assert boss.finish_episode(now_unix_s=at)
        # The 64 most recent episodes in the *database* belong to boss.
        # Selection must be scoped *before* its bounded LIMIT.
        packet = obby.public_packet(
            now_unix_s=NOW + 90, public_action_ids=frozenset({"jump_left"}),
            broadcast_approved=True,
        )
        assert packet is not None and '"game_id":"obby"' in packet.context_record
        assert obby.status()["integrity_failures"] == 0


def test_corrupt_foreign_game_does_not_silence_valid_game(bank, tmp_path):
    path = tmp_path / "shared.sqlite"
    with vault(bank, path) as obby, _other_game_vault(bank, path) as boss:
        obby.enable(owner_approved=True)
        boss.enable(owner_approved=True)
        assert obby.start_episode("one", now_unix_s=NOW)
        assert obby.record(trial(bank, 1), now_unix_s=NOW + 1)
        assert obby.finish_episode(now_unix_s=NOW + 2)
        assert boss.start_episode("two", now_unix_s=NOW + 3)
        assert boss.record(trial(bank, 4, game="boss"), now_unix_s=NOW + 4)
        assert boss.finish_episode(now_unix_s=NOW + 5)
        with sqlite3.connect(path) as direct:
            direct.execute(
                "UPDATE continuity_events SET outcome='failure' "
                "WHERE episode_key IN (SELECT episode_key FROM continuity_episodes "
                "WHERE game_id='boss')"
            )
        assert obby.public_packet(
            now_unix_s=NOW + 6, public_action_ids=frozenset({"jump_left"}),
            broadcast_approved=True,
        ) is not None
        assert obby.status()["integrity_failures"] == 0
        assert boss.public_packet(
            now_unix_s=NOW + 6, public_action_ids=frozenset({"jump_left"}),
            broadcast_approved=True,
        ) is None
        assert boss.status()["integrity_failures"] == 1
