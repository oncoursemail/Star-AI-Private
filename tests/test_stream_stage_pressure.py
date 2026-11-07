"""Measured-pressure rehearsal: Star should not chatter over stressful gameplay."""
import unittest

from star.stream_budget import StreamTelemetry
from star.stream_director import StreamSignal
from star.stream_stage import StarStage

NOW = 100.0


def telem(*, live=True, game=True, fps=60., vram=4000., backlog=0.):
    return StreamTelemetry(live, game, vram, 8192., fps, backlog)


def event(kind, i="a", *, evidence="observed"):
    return StreamSignal(i, kind, NOW, "A verified game signal" if kind.startswith("game_")
                        else "Moderated chat input",
                        speaker_id="viewer-test" if kind.startswith("viewer_") else "",
                        evidence=evidence)


def ready(kind="viewer_question", *, evidence="observed"):
    stage = StarStage(clock=lambda: NOW)
    stage.enable(owner_approved=True)
    assert stage.offer(event(kind, evidence=evidence), now=NOW, moderated=True)
    return stage


class StreamStagePressureTests(unittest.TestCase):
    def test_low_fps_defers_viewer_chat_until_recovered(self):
        s = ready()
        self.assertIsNone(s.prepare(now=NOW, telemetry=telem(fps=39)))
        self.assertIsNone(s.prepare(now=NOW, telemetry=telem(fps=49.9)))
        p = s.prepare(now=NOW, telemetry=telem(fps=50))
        self.assertIsNotNone(p)
        self.assertEqual(p.kind, "viewer_question")

    def test_voice_backlog_reduces_interruptions(self):
        s = ready(kind="ambient")
        self.assertIsNone(s.prepare(now=NOW, telemetry=telem(backlog=300)))
        p = s.prepare(now=NOW, telemetry=telem(backlog=250))
        self.assertEqual(p.kind, "ambient")

    def test_live_vram_pressure_suppresses_optional_chatter(self):
        s = ready(kind="viewer_comment")
        self.assertIsNone(s.prepare(now=NOW, telemetry=telem(vram=1200)))
        self.assertIsNotNone(s.prepare(now=NOW, telemetry=telem(vram=2000)))

    def test_game_danger_still_eligible_in_pressure(self):
        s = ready(kind="game_danger")
        p = s.prepare(now=NOW, telemetry=telem(fps=1, vram=300, backlog=999))
        self.assertIsNotNone(p)
        self.assertEqual(p.expression, "surprise")
        self.assertFalse(s.current(p))  # no mouth/animation until audible

    def test_unverified_game_danger_does_not_animate(self):
        s = ready(kind="game_danger", evidence="reported")
        p = s.prepare(now=NOW, telemetry=telem(fps=30))
        self.assertIsNone(p.expression)

    def test_owner_interrupt_preempts_voice_under_pressure(self):
        s = ready(kind="owner_interrupt")
        p = s.prepare(now=NOW, telemetry=telem(fps=3),
                      voice_speaking=True, viewer_speaking=False)
        self.assertIsNotNone(p)
        self.assertEqual(p.kind, "owner_interrupt")

    def test_no_telemetry_is_backward_compatible_and_bad_type_rejected(self):
        s = ready()
        with self.assertRaises(TypeError):
            s.prepare(now=NOW, telemetry={"game_fps": 10})
        self.assertIsNotNone(s.prepare(now=NOW))

    def test_gameplay_pressure_applies_even_in_offline_rehearsal(self):
        s = ready(kind="game_success")
        self.assertIsNone(s.prepare(now=NOW, telemetry=telem(live=False, fps=20)))
        self.assertEqual(s.prepare(now=NOW, telemetry=telem(live=False, fps=55)).kind,
                         "game_success")


if __name__ == "__main__":
    unittest.main()
