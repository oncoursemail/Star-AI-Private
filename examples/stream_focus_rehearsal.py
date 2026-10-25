"""Offline Star stream focus rehearsal; no capture, game inputs, TTS or OBS.

From repo root: PYTHONPATH=. python3 -m examples.stream_focus_rehearsal
Synthetic hash cues and latency audits only. Do not interpret admission
reduction as measured GPU/FPS/speech throughput improvement.
"""
from __future__ import annotations

import json

from star.stream_budget import StreamTelemetry
from star.stream_observe import FrameCue, ObservationGovernor
from star.stream_quality import StreamAuditTurn, compare_stream_profiles


def main() -> None:
    governor = ObservationGovernor()
    governor.enable(owner_approved=True)  # isolated demo toggle, NOT host consent
    metrics = StreamTelemetry(True, True, 3500, 8192, 60, 75)
    proposed = 0
    admitted = 0
    for index in range(180):
        now = index * 100.0 / 3  # synthetic 30 fps for six seconds
        cue = "new_scene" if index == 100 else "none"
        finger = 0 if index < 100 else (1 << 64) - 1
        request = governor.consider(FrameCue(now, finger, cue), metrics,
                                    now_ms=now, capture_authorized=True)
        proposed += 1
        if request.admitted:
            admitted += 1
            # Simulates a completed call only. NO actual vision request occurred.
            governor.complete(ticket=request.ticket, now_ms=now + 1, succeeded=True)
    counters = governor.stats()
    governor.disable()

    baseline = []
    candidate = []
    # Synthetic audit rows, not Star hardware recordings or independent judges.
    for index in range(20):
        ident = f"rehearsal_{index}"
        context = "b" * 64
        baseline.append(StreamAuditTurn(ident, context, "baseline", True, "spoken",
                                        "supported", 1100, 0, 0, True))
        candidate.append(StreamAuditTurn(ident, context, "candidate", True, "spoken",
                                         "supported", 750, 0, 0, True))
    evaluation = compare_stream_profiles(tuple(baseline + candidate))
    print(json.dumps({
        "broadcasting": False, "generated_audio": False,
        "game_control": False, "frame_capture": False,
        "synthetic_input_frames": proposed,
        "synthetic_vision_requests_admitted": admitted,
        "synthetic_requests_not_admitted": proposed - admitted,
        "observer_metrics": counters,
        "paired_synthetic_audit": {
            "decision": evaluation["decision"],
            "p95_relative_latency_gain": evaluation["p95_relative_latency_gain"],
            "automatic_promotion": evaluation["promoted"],
        },
    }, indent=2))


if __name__ == "__main__":
    main()
