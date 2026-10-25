"""Offline streamer rehearsal. Generates no audio, input, avatar movement or OBS action.

Run from repo root: python3 -m examples.streamer_rehearsal
"""
from __future__ import annotations

import json

from star.stream_director import StreamDirector, StreamSignal
from star.stream_persona import event_message


def main() -> None:
    director = StreamDirector()
    director.enable(owner_approved=True)
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
    print(json.dumps({
        "broadcasting": False,
        "generated_audio": False,
        "game_control": False,
        "selected": proposal.kind,
        "model_message": event_message(proposal),
        "metrics_before": director.metrics(),
    }, indent=2))
    # This is an offline demonstration. No speech was actually played.
    director.complete(proposal, now=now, spoken=False)
    director.disable()


if __name__ == "__main__":
    main()
