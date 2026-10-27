"""Purely SYNTHETIC game-action trace; no screen capture, keys or models.

Run from repository root:
  python -m examples.game_action_gate_rehearsal

The owner-consent booleans below are fixtures for testing, NOT real grants.
"""
from __future__ import annotations

from hashlib import sha256
import json

from star.game_action_gate import (
    GameActionGate, GameActionHint, GameFrame, GameScope,
)
from star.stream_budget import StreamTelemetry


def rehearsal() -> dict:
    scope = GameScope("fake_obstacle_course", "simulated_v1", "training_demo")
    gate = GameActionGate()
    gate.start(scope, ("jump", "move_left"), owner_approved=True)

    digest = sha256(b"NOT A REAL FRAME: sample obstacle at x=5").hexdigest()
    frame = GameFrame(
        scope, sequence=1, captured_ms=1000, evidence_sha256=digest,
        focus_confirmed=True, playable=True, perception_confidence=0.93,
    )
    hint = GameActionHint("jump", frame.sequence, digest, 1010, hold_ms=60)
    metrics = StreamTelemetry(False, True, 5000, 8192, 60, 0)
    proposal = gate.request(frame, hint, now_ms=1020,
                            host_verified=True, telemetry=metrics)
    assert proposal.offered
    # A real host would independently check OS foreground focus, permission,
    # its fixed action map, and its key-up watchdog before actual dispatch.
    claimed = gate.claim(proposal.ticket, now_ms=1025,
                         host_focus_and_permission=True)
    released = gate.release(proposal.ticket, now_ms=1100,
                            host_confirmed_released=True)
    stale = gate.request(frame, hint, now_ms=1210,
                         host_verified=True, telemetry=metrics)

    return {
        "synthetic_only": True,
        "did_control_any_game": False,
        "did_capture_any_frame": False,
        "did_train_a_model": False,
        "model_symbolic_action": proposal.action_id,
        "advisory_offer": proposal.offered,
        "advisory_one_time_claim": claimed,
        "synthetic_host_release_ack": released,
        "replayed_observation_rejected": not stale.offered,
        "control_authorized_by_advisory": proposal.authorized_to_press_keys,
        "metrics": gate.metrics(),
    }


if __name__ == "__main__":
    print(json.dumps(rehearsal(), sort_keys=True, indent=2))
