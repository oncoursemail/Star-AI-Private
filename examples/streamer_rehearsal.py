"""Offline Star streamer rehearsal: synthetic speech/avatar/latency, NO live I/O.

Run from repo root: python3 -m examples.streamer_rehearsal
This does not generate audio, move a real rig, control a game or start OBS.
"""
from __future__ import annotations

import json

from star.stream_director import StreamDirector, StreamSignal
from star.stream_latency import LatencyWindow, LiveTurn
from star.stream_motion import AudioLevel, ExpressionCue, plan_motion
from star.stream_persona import event_message


def main() -> None:
    director = StreamDirector()
    director.enable(owner_approved=True)  # opt-in within this process only
    now = 100.0  # a deterministic monotonic clock for the rehearsal
    events = [
        StreamSignal("chat-1", "viewer_question", now, "How did you dodge?", "viewer-A", "reported"),
        StreamSignal("game-1", "game_success", now, "Win screen appeared", evidence="observed"),
        StreamSignal("chat-2", "viewer_comment", now, "GG!", "viewer-B", "reported"),
    ]
    for item in events:
        director.offer(item, now=now)
    proposal = director.propose(now=now)
    if proposal is None:
        raise RuntimeError("expected a speech proposal")

    # The host will supply real audio envelopes and approved emotion cues later.
    # These are deliberately FAKE samples for a reproducible, disconnected demo.
    frames = plan_motion(
        duration_s=0.9,
        audio_levels=(AudioLevel(0, 0), AudioLevel(0.2, 0.9),
                      AudioLevel(0.4, 0.7), AudioLevel(0.6, 0)),
        cues=(ExpressionCue(0.1, "joy", 0.8),),
        mode="cat",
        fps=30,
    )
    latency = LatencyWindow(minimum_samples=20)
    latency.add(LiveTurn(started_ms=0, perception_done_ms=120,
                         first_token_ms=300, tts_chunk_ms=540,
                         first_audible_ms=680))
    print(json.dumps({
        "broadcasting": False,
        "generated_audio": False,
        "game_control": False,
        "real_avatar_control": False,
        "simulated_audio_and_telemetry": True,
        "selected": proposal.kind,
        "model_message": event_message(proposal),
        "avatar_frames_planned": len(frames),
        "avatar_preview": {
            "at_s": frames[6].at_s,
            "mouth_open": round(frames[6].mouth_open, 3),
            "smile": round(frames[6].smile, 3),
            "tail_sway": round(frames[6].tail_sway, 3),
        },
        "latency_preview": latency.summary(),
        "metrics_before": director.metrics(),
    }, indent=2))
    # No utterance was actually played or broadcast.
    director.complete(proposal, now=now, spoken=False)
    director.disable()


if __name__ == "__main__":
    main()
