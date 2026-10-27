"""Offline integration tests: verified final STT enables fast but never early speech."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from star.stream_brain_governor import StreamBrainGovernor
from star.stream_director import StreamSignal
from star.stream_hardware_telemetry import RealtimeTelemetryHost
from star.stream_preemptive_host import (
    PreviewTicket, StreamPreemptiveHost, prompt_fingerprint,
)
from star.stream_qos import AdaptiveQoS, InferenceJob
from star.stream_stage import StarStage


class Rig:
    def __init__(self, *, live=False):
        self.now = 100_000.0
        self.cpu = (300, 1000)
        self.telemetry = RealtimeTelemetryHost(
            gpu_probe=lambda: {"vram_total_mib": 8192, "vram_used_mib": 2500},
            cpu_probe=lambda: self.cpu,
            memory_probe=lambda: (32768, 18000),
            clock_ms=lambda: self.now,
        )
        self.stage = StarStage(clock=lambda: self.now / 1000)
        self.governor = StreamBrainGovernor(
            telemetry=self.telemetry, qos=AdaptiveQoS(), stage=self.stage,
            clock_ms=lambda: self.now,
        )
        self.governor.enable(owner_approved=True, live=live, game_active=True)
        assert self.telemetry.refresh_hardware()
        self.cpu = (310, 1100)
        self.now += 100
        assert self.telemetry.refresh_hardware()
        for _ in range(24):
            self.now += 16
            assert self.telemetry.presented_frame(self.now)
        assert self.telemetry.report_audio_backlog(
            backlog_ms=20, at_ms=self.now
        )
        self.cpu = (320, 1200)
        assert self.telemetry.refresh_hardware()
        self.preview = StreamPreemptiveHost(
            governor=self.governor, clock_ms=lambda: self.now,
        )
        self.prompt = prompt_fingerprint(
            "STAR STREAM PROMPT v2 | guest: where is the gold checkpoint?"
        )

    def job(self, ident="preempt"):
        return InferenceJob(
            ident, "commentary", self.now, self.now + 3000, 120, 0, "cpu"
        )

    def begin(self, *, signal_id="q1", transcript="Where is the gold checkpoint?",
              prompt=None, ident="preempt", approved=True):
        return self.preview.begin(
            signal_id=signal_id, revision=3,
            provisional_transcript=transcript,
            prompt_digest=self.prompt if prompt is None else prompt,
            job=self.job(ident), moderated_by_host=approved,
        )

    def final(self, ticket, *, transcript="Where is the gold checkpoint?",
              prompt=None, approved=True, revision=3):
        return self.preview.confirm_final(
            ticket, final_transcript=transcript,
            final_prompt_digest=self.prompt if prompt is None else prompt,
            final_revision=revision,
            finalized_by_host=approved, moderated_by_host=approved,
        )

    def finish(self, ticket, *, text="It's beside the golden gate.",
               moderated=True, stopped=True, succeeded=True):
        return self.preview.finish_worker(
            ticket, worker_stopped=stopped, succeeded=succeeded,
            moderated_answer=text, output_moderated=moderated,
        )

    def plan(self, *, signal_id="q1", kind="viewer_question"):
        event = StreamSignal(
            signal_id, kind, self.now / 1000,
            "Where is the gold checkpoint?", speaker_id="viewer",
        )
        assert self.governor.offer(
            event, moderated=kind.startswith("viewer")
        )
        plan = self.governor.prepare()
        assert plan is not None
        return plan


@pytest.fixture
def rig():
    return Rig()


def test_owner_consent_and_default_off(rig):
    with pytest.raises(PermissionError):
        rig.preview.enable()
    assert rig.begin() is None
    assert rig.preview.status()["previews"] == 0
    rig.preview.enable(owner_approved=True)
    assert rig.begin(approved=False) is None
    assert rig.preview.status()["denied"] == 2
    assert rig.governor.status()["reserved_workers"] == 0


def test_use_preemptive_llm_only_after_exact_final_and_prepared_plan(rig):
    rig.preview.enable(owner_approved=True)
    ticket = rig.begin()
    assert isinstance(ticket, PreviewTicket)
    assert rig.governor.status()["reserved_workers"] == 1
    assert rig.finish(ticket)
    assert rig.governor.status()["reserved_workers"] == 0
    assert rig.final(ticket)
    plan = rig.plan()
    assert rig.preview.claim(
        ticket, prepared_plan=plan, final_prompt_digest=rig.prompt
    ) == "It's beside the golden gate."
    assert rig.preview.claim(
        ticket, prepared_plan=plan, final_prompt_digest=rig.prompt
    ) is None
    # Does not queue audio or run TTS on its own.
    assert rig.stage.prepared(plan)
    assert rig.preview.status()["reused"] == 1


def test_final_may_arrive_before_model_completion(rig):
    rig.preview.enable(owner_approved=True)
    t = rig.begin()
    assert rig.final(t)
    p = rig.plan()
    assert rig.preview.claim(t, prepared_plan=p, final_prompt_digest=rig.prompt) is None
    assert rig.finish(t)
    assert rig.preview.claim(t, prepared_plan=p, final_prompt_digest=rig.prompt)


@pytest.mark.parametrize("final", [
    "Where is the gold checkpoint",            # missing punctuation
    "Where is the blue checkpoint?",          # STT correction
    "Where is the gold checkpoint? Also jump",  # unexpected extra words
])
def test_changed_final_drops_speech_and_requires_worker_stop(rig, final):
    rig.preview.enable(owner_approved=True)
    t = rig.begin()
    assert not rig.final(t, transcript=final)
    assert rig.governor.status()["reserved_workers"] == 1
    assert not rig.finish(t)
    assert rig.governor.status()["reserved_workers"] == 0
    p = rig.plan()
    assert rig.preview.claim(t, prepared_plan=p, final_prompt_digest=rig.prompt) is None
    assert rig.preview.status()["mismatched"] == 1


def test_whitespace_only_is_allowed_but_prompt_changed_is_not(rig):
    rig.preview.enable(owner_approved=True)
    t = rig.begin()
    assert rig.final(t, transcript=" Where  is the gold \ncheckpoint? ")
    assert rig.finish(t)
    p = rig.plan()
    assert rig.preview.claim(
        t, prepared_plan=p, final_prompt_digest=prompt_fingerprint("other context")
    ) is None
    assert rig.preview.claim(t, prepared_plan=p, final_prompt_digest=rig.prompt)

    # Different model instructions/public facts are never safe to reuse.
    rig2 = Rig()
    rig2.preview.enable(owner_approved=True)
    t2 = rig2.begin()
    assert not rig2.final(t2, prompt=prompt_fingerprint("newly supplied fact"))
    assert not rig2.finish(t2)


def test_moderation_and_unconfirmed_worker_stop_never_speak(rig):
    rig.preview.enable(owner_approved=True)
    t = rig.begin()
    assert not rig.finish(t, stopped=False)
    assert rig.governor.status()["reserved_workers"] == 1
    assert not rig.final(t, approved=False)
    assert not rig.finish(t, moderated=False)
    p = rig.plan()
    assert rig.preview.claim(t, prepared_plan=p, final_prompt_digest=rig.prompt) is None


def test_abort_old_worker_prevents_concurrent_unbounded_previews(rig):
    rig.preview.enable(owner_approved=True)
    t = rig.begin()
    rig.preview.revoke(t)
    assert rig.begin(ident="second") is None
    assert rig.governor.status()["reserved_workers"] == 1
    assert not rig.finish(t)
    assert rig.governor.status()["reserved_workers"] == 0
    assert rig.begin(ident="second") is not None
    assert rig.preview.status()["cancelled"] == 1


def test_disabling_does_not_release_running_gpu_or_cpu_job(rig):
    rig.preview.enable(owner_approved=True)
    t = rig.begin()
    rig.preview.disable()
    assert rig.governor.status()["reserved_workers"] == 1
    with pytest.raises(RuntimeError):
        rig.preview.enable(owner_approved=True)
    assert not rig.finish(t)
    assert rig.governor.status()["reserved_workers"] == 0
    assert not rig.preview.status()["enabled"]


def test_preview_expiry_rejects_speech_and_releases_only_on_worker_ack(rig):
    rig.preview.enable(owner_approved=True)
    t = rig.begin()
    rig.now += 3100
    assert not rig.finish(t)
    assert rig.governor.status()["reserved_workers"] == 0
    assert rig.preview.status()["expired"] == 1
    assert rig.preview.claim(
        t, prepared_plan=None, final_prompt_digest=rig.prompt
    ) is None


def test_stale_plan_copy_and_wrong_event_never_consumes(rig):
    rig.preview.enable(owner_approved=True)
    t = rig.begin()
    assert rig.finish(t)
    assert rig.final(t)
    p = rig.plan()
    assert rig.preview.claim(
        t, prepared_plan=replace(p), final_prompt_digest=rig.prompt
    ) is None
    assert rig.preview.claim(
        t, prepared_plan=replace(p, signal_id="q2"),
        final_prompt_digest=rig.prompt,
    ) is None
    assert rig.preview.claim(t, prepared_plan=p, final_prompt_digest=rig.prompt)


def test_previous_governor_session_invalidates_unspoken_draft(rig):
    rig.preview.enable(owner_approved=True)
    t = rig.begin()
    assert rig.finish(t)
    assert rig.final(t)
    rig.governor.disable()
    rig.governor.enable(owner_approved=True, live=False, game_active=True)
    # No new physical stream controls are issued on an old session ticket.
    assert not rig.preview.confirm_final(
        t, final_transcript="Where is the gold checkpoint?",
        final_prompt_digest=rig.prompt, final_revision=3,
        finalized_by_host=True, moderated_by_host=True,
    )
    assert not rig.preview.status()["ready_unspoken"]


def test_live_uncalibrated_commentary_refused_before_gameplay(rig):
    live = Rig(live=True)
    live.preview.enable(owner_approved=True)
    assert live.begin() is None
    assert live.governor.status()["reserved_workers"] == 0


def test_parallel_claim_uses_answer_once(rig):
    rig.preview.enable(owner_approved=True)
    t = rig.begin()
    assert rig.finish(t)
    assert rig.final(t)
    p = rig.plan()
    with ThreadPoolExecutor(max_workers=8) as pool:
        answers = list(pool.map(
            lambda _: rig.preview.claim(
                t, prepared_plan=p, final_prompt_digest=rig.prompt
            ), range(24),
        ))
    assert answers.count("It's beside the golden gate.") == 1
    assert answers.count(None) == 23


@pytest.mark.parametrize("bad", [
    None, "", "x" * 301, "hello\x00", "hello\rbye", 1, True,
])
def test_invalid_provisional_input_rejected_without_job(rig, bad):
    rig.preview.enable(owner_approved=True)
    with pytest.raises(ValueError):
        rig.preview.begin(
            signal_id="q1", revision=3, provisional_transcript=bad,
            prompt_digest=rig.prompt, job=rig.job(), moderated_by_host=True,
        )
    assert rig.governor.status()["reserved_workers"] == 0


def test_no_content_in_metrics_and_clock_backwards_rejected(rig):
    rig.preview.enable(owner_approved=True)
    t = rig.begin()
    assert t is not None
    status = str(rig.preview.status())
    assert "checkpoint" not in status
    assert "gold" not in status
    assert rig.prompt not in status
    rig.now -= 1
    with pytest.raises(ValueError):
        rig.preview.confirm_final(
            t, final_transcript="Where is the gold checkpoint?",
            final_prompt_digest=rig.prompt, final_revision=3,
            finalized_by_host=True,
            moderated_by_host=True,
        )


def test_different_transcript_revision_discards_even_same_words(rig):
    rig.preview.enable(owner_approved=True)
    t = rig.begin()
    assert not rig.final(t, revision=4)
    assert not rig.finish(t)
    assert rig.preview.status()["mismatched"] == 1


def test_cannot_restart_gate_without_disabling_or_double_spend(rig):
    rig.preview.enable(owner_approved=True)
    with pytest.raises(RuntimeError):
        rig.preview.enable(owner_approved=True)
    t = rig.begin()
    rig.preview.revoke(t)
    assert not rig.finish(t)
    rig.preview.disable()
    rig.preview.enable(owner_approved=True)
    assert rig.begin(ident="newjob")
