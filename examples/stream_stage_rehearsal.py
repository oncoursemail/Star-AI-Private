"""Deterministic, no-I/O Star VTuber rehearsal (NOT a live broadcast)."""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from star.knowledge import KnowledgeStore
from star.stream_director import StreamSignal
from star.stream_knowledge import public_knowledge_packet
from star.stream_motion import AudioLevel
from star.stream_stage import StarStage


def main() -> None:
    stage = StarStage(clock=lambda: 100.0)
    stage.enable(owner_approved=True, mode="cat")
    success = StreamSignal(
        "replay-win", "game_success", 100.0, "The replay shows a round win.",
        evidence="observed",
    )
    assert stage.offer(success, now=100)
    plan = stage.prepare(now=100)
    assert plan is not None
    assert plan.expression == "joy"
    assert stage.queue_audio(plan, now=100)
    assert stage.motion(plan, duration_s=0.25, audio_levels=[]) == ()
    assert stage.acknowledge_audible(plan, now=100)
    frames = stage.motion(plan, duration_s=1.0,
                          audio_levels=[AudioLevel(0, 0.6)])
    assert any(frame.smile > 0 for frame in frames)
    assert any(frame.tail_sway != 0 for frame in frames)
    stage.finish(plan, now=100.25, played_to_end=True)

    with TemporaryDirectory() as folder:
        knowledge = KnowledgeStore(Path(folder))
        try:
            note = knowledge.add_note(
                project="demo", kind="fact",
                text="The sandbox checkpoint is located beside the gold gate.",
                source="owner-approved:demo-only", revision="sandbox-v1",
            )
            knowledge.review_note(project="demo", note_id=note,
                                  evidence="sandbox-test-evidence")
            packet = public_knowledge_packet(
                knowledge, project="demo", query="checkpoint",
                public_note_ids=frozenset({note}),
            )
            assert packet is not None
            question = StreamSignal(
                "viewer-checkpoint", "viewer_question", 104.0,
                "Where is the checkpoint?", speaker_id="demo-viewer",
                evidence="reported",
            )
            assert stage.offer(question, now=104, moderated=True)
            plan2 = stage.prepare(now=104, knowledge=packet)
            assert plan2 is not None
            assert "gold gate" in plan2.context_record
            assert plan2.expression == "nod"
            assert stage.queue_audio(plan2, now=104)
            # A deliberate cancellation before playback must NOT be counted
            # as audible, nor retain motion from the previous turn.
            neutral = stage.interrupt(now=104)
            assert neutral.mouth_open == 0
            assert not stage.current(plan2)
            assert stage.metrics()["director"]["completed"] == 1
        finally:
            knowledge.db.close()
    metrics = stage.metrics()
    print("Offline Star stage rehearsal: PASS")
    print("Confirmed audible demo turns:", metrics["audible"])
    print("Cancelled before playback:", metrics["abandoned"])
    print("Normal/cat/puppy movement supported via existing motion sampler.")
    print("No network, streaming, game controls or live user data used.")


if __name__ == "__main__":
    main()
