"""Simulated STAR speech/game scheduling; absolutely no real model or capture.

Run from the repository root:
    python -m examples.stream_qos_rehearsal

Numbers are synthetic fixtures, NOT an actual GPU/voice speed measurement.
"""
from __future__ import annotations

import json

from star.stream_budget import StreamTelemetry
from star.stream_qos import AdaptiveQoS, InferenceJob, QoSSnapshot


def snapshot(now: float, *, live: bool, game: bool, fps: float,
             vram: float, backlog: float = 0) -> QoSSnapshot:
    return QoSSnapshot(
        now, StreamTelemetry(live, game, vram, 8192, fps, backlog),
        free_ram_mib=12000, cpu_busy_percent=30,
        cpu_slots=2, gpu_slots=1,
    )


def rehearsal() -> dict:
    scheduler = AdaptiveQoS()
    scheduler.enable(owner_approved=True)

    # Simulate five completed CPU TTS jobs with a GAME ACTIVE but not live.
    # Idle *no-game* measurements must never certify a realtime game workload.
    for i in range(5):
        at = 500 + 2200 * i
        speech = InferenceJob(f"voice-cal-{i}", "speech", at, at + 1500,
                              ram_mib=100, vram_mib=250, device="cpu")
        result = scheduler.admit(
            speech, snapshot(at, live=False, game=True, fps=60, vram=6000),
            now_ms=at,
        )
        assert result.admitted and result.device == "cpu"
        assert scheduler.finish(result.ticket, now_ms=at + 240, succeeded=True)

    now = 12_000
    live = snapshot(now, live=True, game=True, fps=37, vram=1100, backlog=370)
    optional = scheduler.admit(
        InferenceJob("research-scene", "research", now, now + 2000, 300, 800),
        live, now_ms=now,
    )
    voice = scheduler.admit(
        InferenceJob("critical-speech", "speech", now, now + 1100, 100, 250),
        live, now_ms=now,
    )
    assert not optional.admitted and optional.reason == (
        "protect_live_stream_from_background_work"
    )
    assert voice.admitted and voice.device == "cpu"
    assert voice.predicted_p95_ms == 240

    # No speech is counted "heard": there is no actual audio in this rehearsal.
    return {
        "synthetic_research_deferred": not optional.admitted,
        "synthetic_speech_recommended_on_cpu": voice.device == "cpu",
        "synthetic_cpu_speech_p95_ms": voice.predicted_p95_ms,
        "measured_real_hardware": False,
        "stream_running": False,
        "governor": scheduler.status(),
    }


if __name__ == "__main__":
    print(json.dumps(rehearsal(), sort_keys=True, indent=2))
