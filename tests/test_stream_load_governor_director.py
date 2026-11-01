"""Offline cross-module pressure-aware speech arbitration regressions.

No game controls, OBS, online chat, TTS/audio playback, or devices are used.
"""
import unittest

from star.stream_director import StreamDirector, StreamSignal
from star.stream_load_governor import StreamLoadGovernor, StreamLoadSample


def input_sample(number: int, *, render_loss: float = 0.0,
                 vram_used: float = 3000.0) -> StreamLoadSample:
    return StreamLoadSample(
        sample_id=f"obs-{number}", measured_at_s=float(number),
        game_p95_frame_ms=12.0, game_target_fps=60.0,
        obs_render_missed_pct=render_loss, obs_encode_skipped_pct=0.0,
        obs_network_dropped_pct=0.0, gpu_vram_used_mb=vram_used,
        gpu_vram_total_mb=8192.0, tts_first_audio_p95_ms=150.0,
    )


def live() -> tuple[StreamDirector, StreamLoadGovernor]:
    director = StreamDirector(gap_seconds=0)
    director.enable(owner_approved=True)
    governor = StreamLoadGovernor()
    governor.enable(owner_approved=True)
    return director, governor


def event(ident: str, kind: str, when: float) -> StreamSignal:
    return StreamSignal(
        signal_id=ident, kind=kind, timestamp=when,
        detail=f"Host-supplied context for {ident}",
        speaker_id="viewerA" if kind.startswith("viewer") else "",
        evidence="observed" if kind.startswith("game") else "reported",
    )


class StreamPressureSpeechIntegrationTests(unittest.TestCase):
    def test_healthy_telemetry_allows_a_normal_viewer_question(self) -> None:
        director, governor = live()
        for i in range(10, 13):
            self.assertTrue(governor.ingest(input_sample(i), now_s=i,
                                            host_verified=True))
        advice = governor.recommend(now_s=12)
        self.assertEqual(advice.profile, "normal")
        self.assertTrue(director.offer(event("question", "viewer_question", 12),
                                       now=12))
        intent = director.propose(now=12, load_advice=advice)
        self.assertIsNotNone(intent)
        self.assertEqual(intent.kind, "viewer_question")

    def test_constrained_mode_silences_small_talk_but_not_questions(self) -> None:
        director, governor = live()
        governor.ingest(input_sample(10, vram_used=7300), now_s=10,
                        host_verified=True)
        advice = governor.recommend(now_s=10)
        self.assertEqual(advice.profile, "constrained")
        for ident, kind in (
            ("comment", "viewer_comment"),
            ("ambient", "ambient"),
            ("observation", "game_observation"),
            ("question", "viewer_question"),
        ):
            self.assertTrue(director.offer(event(ident, kind, 10), now=10))
        intent = director.propose(now=10, load_advice=advice)
        self.assertIsNotNone(intent)
        self.assertEqual(intent.kind, "viewer_question")

    def test_critical_mode_keeps_game_danger_and_owner_priority(self) -> None:
        director, governor = live()
        governor.ingest(input_sample(10, render_loss=6), now_s=10,
                        host_verified=True)
        advice = governor.recommend(now_s=10)
        self.assertEqual(advice.profile, "critical")
        self.assertTrue(director.offer(event("question", "viewer_question", 10),
                                       now=10))
        self.assertIsNone(director.propose(now=10, load_advice=advice))
        self.assertTrue(director.offer(event("danger", "game_danger", 10),
                                       now=10))
        self.assertEqual(director.propose(now=10, load_advice=advice).kind,
                         "game_danger")
        self.assertTrue(director.offer(event("owner", "owner_interrupt", 10),
                                       now=10))
        self.assertEqual(director.propose(now=10, load_advice=advice).kind,
                         "owner_interrupt")

    def test_no_or_stale_telemetry_fails_quiet_and_preserves_events(self) -> None:
        director, governor = live()
        self.assertTrue(director.offer(event("question", "viewer_question", 10),
                                       now=10))
        before = director.metrics()["queued"]
        advice = governor.recommend(now_s=10)
        self.assertEqual(advice.profile, "telemetry_stale")
        self.assertIsNone(director.propose(now=10, load_advice=advice))
        self.assertEqual(director.metrics()["queued"], before)
        self.assertIsNotNone(director.propose(now=10))
        for i in range(11, 14):
            governor.ingest(input_sample(i), now_s=i, host_verified=True)
        self.assertEqual(governor.recommend(now_s=17).profile, "telemetry_stale")
        # The old chat line expires naturally in the director by its own TTL.

    def test_invalid_advice_cannot_be_used_as_a_speech_override(self) -> None:
        director, _ = live()
        director.offer(event("question", "viewer_question", 10), now=10)
        with self.assertRaises(TypeError):
            director.propose(now=10, load_advice="normal")

    def test_legacy_propose_remains_backward_compatible(self) -> None:
        director, _ = live()
        director.offer(event("question", "viewer_question", 10), now=10)
        self.assertEqual(director.propose(now=10).kind, "viewer_question")


if __name__ == "__main__":
    unittest.main()
