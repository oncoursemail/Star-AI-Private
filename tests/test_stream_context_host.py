"""Integration tests: real reviewed facts + signed practice -> governed stream speech."""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import hmac
from pathlib import Path
import threading

import pytest

from star.gameplay_skill_bank import GameTrial, GameplaySkillBank
from star.knowledge import KnowledgeStore
from star.stream_brain_governor import StreamBrainGovernor
from star.stream_context_host import StreamContextHost
from star.stream_director import StreamSignal
from star.stream_episode import StreamEpisode
from star.stream_hardware_telemetry import RealtimeTelemetryHost
from star.stream_qos import AdaptiveQoS, InferenceJob
from star.stream_stage import StarStage

NOW = 1_800_000_000
PRACTICE = b"host-only-practice-signer-0123456789012345678"
VALIDATION = b"independent-validation-signer-0123456789012"


class Rig:
    def __init__(self, tmp_path: Path):
        self.now = 100_000.0
        self.unix = NOW
        self.cpu = (300, 1000)
        self.memory = (32768, 16000)
        self.store = KnowledgeStore(tmp_path)
        self.bank = GameplaySkillBank(practice_key=PRACTICE, validation_key=VALIDATION)
        self.episode = StreamEpisode(
            self.bank, game_id="obby", game_version="v1",
            objective_id="checkpoint", situation_id="ledge",
        )
        self.hardware = RealtimeTelemetryHost(
            gpu_probe=lambda: {"vram_total_mib": 8192, "vram_used_mib": 2500},
            cpu_probe=lambda: self.cpu,
            memory_probe=lambda: self.memory,
            clock_ms=lambda: self.now,
        )
        self.stage = StarStage(clock=lambda: self.now / 1000)
        self.governor = StreamBrainGovernor(
            telemetry=self.hardware, qos=AdaptiveQoS(), stage=self.stage,
            clock_ms=lambda: self.now,
        )

    def warm(self):
        assert self.hardware.refresh_hardware()
        self.cpu = (310, 1100)
        self.now += 100
        assert self.hardware.refresh_hardware()
        for _ in range(24):
            self.now += 16
            assert self.hardware.presented_frame(self.now)
        assert self.hardware.report_audio_backlog(backlog_ms=20, at_ms=self.now)
        self.cpu = (320, 1200)
        assert self.hardware.refresh_hardware()

    def ready(self):
        self.governor.enable(owner_approved=True, live=True, game_active=True)
        self.warm()
        self.episode.start(owner_approved=True, now_unix_s=NOW)

    def note(self, text, *, reviewed=True, project="obby"):
        ident = self.store.add_note(
            project=project, kind="fact", text=text, source="manual://verified-owner",
            revision="v1",
        )
        if reviewed:
            self.store.review_note(
                project=project, note_id=ident, evidence="independent test evidence"
            )
        return ident

    def record(self, *, split="practice", outcome="success", action="jump_left"):
        self.unix += 1
        row = GameTrial(
            trial_id=f"trial_{self.unix}", game_id="obby", game_version="v1",
            objective_id="checkpoint", situation_id="ledge", action_id=action,
            run_id=f"trusted_run_{self.unix}", split=split, outcome=outcome,
            evidence_sha256=sha256(f"evidence_{self.unix}".encode()).hexdigest(),
            observed_unix_s=self.unix,
        )
        key = PRACTICE if split == "practice" else VALIDATION
        receipt = hmac.new(key, row.canonical_bytes(), "sha256").hexdigest()
        self.bank.ingest(row, receipt, now_unix_s=self.unix)
        return self.episode.append(row, now_unix_s=self.unix)

    def context(self, *, notes=frozenset(), actions=frozenset()):
        return StreamContextHost(
            governor=self.governor, knowledge=self.store, episode=self.episode,
            project="obby", public_note_ids=frozenset(notes),
            public_action_ids=frozenset(actions),
            utc_clock=lambda: datetime.now(timezone.utc),
            unix_clock=lambda: self.unix,
        )

    def signal(self, kind, message, *, ident="event1"):
        signal = StreamSignal(
            ident, kind, self.now / 1000, message,
            "viewer" if kind.startswith("viewer") else "",
            "unknown" if kind.startswith("viewer") else "observed",
        )
        return self.governor.offer(signal, moderated=kind.startswith("viewer"))

    def close(self):
        self.episode.disable()
        self.bank.close()
        self.store.close()


@pytest.fixture
def rig(tmp_path):
    instance = Rig(tmp_path)
    try:
        yield instance
    finally:
        instance.close()


def test_requires_separate_owner_and_broadcast_approval(rig):
    c = rig.context()
    with pytest.raises(PermissionError):
        c.enable(owner_approved=True)
    with pytest.raises(PermissionError):
        c.enable(broadcast_approved=True)
    assert c.prepare() is None
    assert c.status()["enabled"] is False
    c.enable(owner_approved=True, broadcast_approved=True)
    with pytest.raises(RuntimeError):
        c.enable(owner_approved=True, broadcast_approved=True)
    assert c.prepare() is None
    c.disable()
    assert c.prepare() is None


def test_reviewed_and_approved_fact_reaches_moderated_viewer_question(rig):
    allowed = rig.note("The checkpoint is beside the gold gate.")
    rig.note("PRIVATE checkpoint code is unpublished.")
    rig.note("Unreviewed checkpoint is near the ocean.", reviewed=False)
    rig.ready()
    c = rig.context(notes={allowed})
    c.enable(owner_approved=True, broadcast_approved=True)
    assert rig.signal("viewer_question", "Where is the checkpoint?")
    plan = c.prepare(moderated_question="checkpoint")
    assert plan is not None
    assert "gold gate" in plan.context_record
    assert "PRIVATE checkpoint" not in plan.context_record
    assert "ocean" not in plan.context_record
    assert plan.user_message()["role"] == "user"
    assert c.status()["knowledge_candidates"] == 1
    assert "gold gate" not in str(c.status())


def test_signed_practice_memory_reaches_game_reaction_but_not_unrelated_notes(rig):
    public_id = rig.note("The secret access code is TEST-PRIVATE.")
    rig.ready()
    assert rig.record(outcome="success")
    c = rig.context(notes={public_id}, actions={"jump_left"})
    c.enable(owner_approved=True, broadcast_approved=True)
    assert rig.signal("game_success", "Star completed a ledge jump")
    plan = c.prepare(moderated_question="access code")
    assert plan is not None
    assert '"practice_successes":1' in plan.context_record
    assert "TEST-PRIVATE" not in plan.context_record
    assert "verified game episode data" in plan.context_record.lower()
    assert c.status()["episode_candidates"] == 1


def test_holdout_never_reaches_stream_and_private_actions_hidden(rig):
    rig.ready()
    assert not rig.record(split="validation")
    c = rig.context(actions={"jump_left"})
    c.enable(owner_approved=True, broadcast_approved=True)
    assert rig.signal("game_observation", "Star inspected the level")
    plan = c.prepare()
    assert plan is not None
    assert "practice_successes" not in plan.context_record
    rig.stage.finish(plan, now=rig.now / 1000)
    assert rig.record(action="hidden_route")
    assert rig.signal("game_success", "A practice attempt completed", ident="two")
    plan = c.prepare()
    assert plan is not None
    assert "hidden_route" not in plan.context_record


def test_no_public_ids_means_no_accidental_disclosure(rig):
    rig.note("checkpoint private server token is always private")
    rig.ready()
    assert rig.record()
    c = rig.context()
    c.enable(owner_approved=True, broadcast_approved=True)
    assert rig.signal("viewer_question", "Can you tell me about checkpoint?")
    plan = c.prepare(moderated_question="checkpoint")
    assert plan is not None
    assert "private server" not in plan.context_record
    assert "practice_successes" not in plan.context_record


def test_knowledge_is_not_injected_into_gameplay_even_with_query(rig):
    allowed = rig.note("The checkpoint is in the wizard tower.")
    rig.ready()
    c = rig.context(notes={allowed})
    c.enable(owner_approved=True, broadcast_approved=True)
    assert rig.signal("game_danger", "Slippery platform ahead")
    plan = c.prepare(moderated_question="checkpoint")
    assert plan is not None
    assert "wizard tower" not in plan.context_record


def test_bad_query_types_and_untrusted_packets_fail_closed(rig):
    c = rig.context()
    with pytest.raises(ValueError):
        c.prepare(moderated_question=" ")
    with pytest.raises(ValueError):
        c.prepare(moderated_question="a" * 301)
    with pytest.raises(ValueError):
        c.prepare(moderated_question=4)
    with pytest.raises(TypeError):
        rig.governor.prepare(knowledge={"text": "fake"})
    with pytest.raises(TypeError):
        rig.governor.prepare(episode={"text": "fake"})
    with pytest.raises(ValueError):
        rig.context(notes={True})
    with pytest.raises(ValueError):
        rig.context(actions={"x" * 65})


def test_missing_trusted_hardware_sample_still_prevents_speech(rig):
    allowed = rig.note("This checkpoint exists.")
    rig.governor.enable(owner_approved=True, live=True, game_active=True)
    c = rig.context(notes={allowed})
    c.enable(owner_approved=True, broadcast_approved=True)
    assert rig.signal("viewer_question", "Where is the checkpoint?")
    assert c.prepare(moderated_question="checkpoint") is None
    assert rig.governor.status()["missing_sensor"] >= 1


def test_context_database_failure_results_in_silence_not_invented_facts(rig, monkeypatch):
    allowed = rig.note("The checkpoint is next to the gold archway.")
    rig.ready()
    c = rig.context(notes={allowed})
    c.enable(owner_approved=True, broadcast_approved=True)
    assert rig.signal("viewer_question", "checkpoint?")
    def broken(*_args, **_kwargs):
        raise OSError("private database path SHOULD NOT APPEAR IN COUNTERS")
    monkeypatch.setattr(rig.store, "find", broken)
    assert c.prepare(moderated_question="checkpoint") is None
    assert c.status()["retrieval_faults"] == 1
    assert "SHOULD NOT APPEAR" not in str(c.status())


def test_busy_stage_never_doubles_prepares_or_retrievals(rig, monkeypatch):
    allowed = rig.note("checkpoint at a bridge")
    rig.ready()
    c = rig.context(notes={allowed})
    c.enable(owner_approved=True, broadcast_approved=True)
    assert rig.signal("viewer_question", "checkpoint?")
    plan = c.prepare(moderated_question="checkpoint")
    assert plan is not None
    def fail_if_read(*args, **kwargs):
        raise AssertionError("busy stage performed redundant database lookup")
    monkeypatch.setattr(rig.store, "find", fail_if_read)
    assert c.prepare(moderated_question="checkpoint") is None
    assert rig.stage.current(plan) is False
    assert c.status()["retrieval_faults"] == 0


def test_context_host_thread_affinity(rig):
    c = rig.context()
    c.enable(owner_approved=True, broadcast_approved=True)
    errors = []
    def worker():
        try:
            c.prepare()
        except RuntimeError as exc:
            errors.append(str(exc))
    thread = threading.Thread(target=worker)
    thread.start()
    thread.join()
    assert len(errors) == 1
    assert "SQLite owner thread" in errors[0]


def test_genuine_speech_lease_and_audible_ack_still_required(rig):
    rig.note("checkpoint near the blue river")
    rig.ready()
    c = rig.context()
    c.enable(owner_approved=True, broadcast_approved=True)
    assert rig.signal("game_success", "Star crossed the ledge")
    plan = c.prepare()
    assert plan is not None
    assert rig.governor.acknowledge_audible(plan, sound_device_confirmed=True) is False
    work = InferenceJob(
        "speech_job", "speech", rig.now, rig.now + 1500, 120, 100, "auto"
    )
    grant = rig.governor.admit(work)
    assert grant.admitted and grant.lease is not None
    assert rig.governor.queue_audio(plan, speech_lease=grant.lease)
    assert not rig.governor.acknowledge_audible(plan)
    assert rig.governor.acknowledge_audible(
        plan, sound_device_confirmed=True
    )
    assert rig.governor.finish_audio(plan, device_playback_finished=True)
    assert rig.governor.acknowledge_worker_stopped(
        grant.lease, worker_stopped=True, succeeded=True
    )
    assert rig.governor.status()["pending_audio_stop"] is False


def test_explicit_disable_stops_retrieval_without_interrupting_device(rig):
    rig.ready()
    c = rig.context()
    c.enable(owner_approved=True, broadcast_approved=True)
    assert rig.signal("game_danger", "the edge is near")
    c.disable()
    assert c.prepare() is None
    assert rig.governor.status()["enabled"] is True


def test_context_packets_not_retained_in_anonymous_stats(rig):
    allowed = rig.note("My favorite bridge checkpoint is near the rock.")
    rig.ready()
    c = rig.context(notes={allowed})
    c.enable(owner_approved=True, broadcast_approved=True)
    assert rig.signal("viewer_question", "bridge checkpoint")
    assert c.prepare(moderated_question="bridge checkpoint")
    status = str(c.status())
    assert "bridge" not in status
    assert "checkpoint" not in status
    assert "favorite" not in status

from star.stream_continuity import StreamContinuityVault


def test_cross_session_game_memory_reaches_only_real_viewer_question(rig, tmp_path):
    rig.ready()
    continuity = StreamContinuityVault(
        rig.bank, tmp_path / "past_games.sqlite",
        integrity_key=b"separate-stream-memory-integrity-key-01234567",
        game_id="obby", game_version="v1", objective_id="checkpoint",
        situation_id="ledge", recordable_action_ids=frozenset({"jump_left"}),
    )
    try:
        continuity.enable(owner_approved=True)
        assert continuity.start_episode("first_episode", now_unix_s=rig.unix)
        rig.unix += 1
        row = GameTrial(
            trial_id="first_ledge_attempt", game_id="obby", game_version="v1",
            objective_id="checkpoint", situation_id="ledge", action_id="jump_left",
            run_id="trusted_ledge_attempt", split="practice", outcome="failure",
            evidence_sha256=sha256(b"first_ledge_frame").hexdigest(),
            observed_unix_s=rig.unix,
        )
        receipt = hmac.new(PRACTICE, row.canonical_bytes(), "sha256").hexdigest()
        rig.bank.ingest(row, receipt, now_unix_s=rig.unix)
        assert continuity.record(row, now_unix_s=rig.unix)
        rig.unix += 1
        assert continuity.finish_episode(now_unix_s=rig.unix)

        host = StreamContextHost(
            governor=rig.governor, knowledge=rig.store, episode=rig.episode,
            project="obby", public_note_ids=frozenset(),
            public_action_ids=frozenset(),
            continuity=continuity,
            public_continuity_action_ids=frozenset({"jump_left"}),
            utc_clock=lambda: datetime.now(timezone.utc),
            unix_clock=lambda: rig.unix,
        )
        host.enable(owner_approved=True, broadcast_approved=True)
        assert rig.signal("viewer_question", "What happened last time?")
        plan = host.prepare(moderated_question="earlier jump attempts",
                            include_past_experience=True)
        assert plan is not None
        assert "STAR VERIFIED PAST GAME PRACTICE" in plan.context_record
        assert '"failures":1' in plan.context_record
        assert host.status()["continuity_candidates"] == 1
        assert "first_episode" not in plan.context_record
        assert rig.stage.finish(plan)

        assert rig.signal("game_danger", "There is a ledge", ident="danger")
        danger = host.prepare(moderated_question="previous ledge?",
                              include_past_experience=True)
        assert danger is not None and "STAR VERIFIED PAST GAME PRACTICE" not in danger.context_record
        assert rig.stage.finish(danger)
        host.disable()
        assert host.prepare(moderated_question="earlier ledge") is None
    finally:
        continuity.close()


def test_wrong_project_rejected_at_host_boundary(rig, tmp_path):
    continuity = StreamContinuityVault(
        rig.bank, tmp_path / "other.sqlite",
        integrity_key=b"independent-private-continuity-key-01234567",
        game_id="unrelated", game_version="v1", objective_id="checkpoint",
        situation_id="ledge", recordable_action_ids=frozenset({"jump_left"}),
    )
    try:
        with pytest.raises(ValueError, match="cross-project"):
            StreamContextHost(
                governor=rig.governor, knowledge=rig.store, episode=rig.episode,
                project="obby", public_note_ids=frozenset(),
                public_action_ids=frozenset(), continuity=continuity,
                public_continuity_action_ids=frozenset({"jump_left"}),
            )
    finally:
        continuity.close()
