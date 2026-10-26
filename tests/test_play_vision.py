"""star/play perception on fake frames: colour blobs, YOLO output decoding + NMS, chat OCR, and one end-to-end fast
tick from a synthetic obby frame to human-like key events."""
from __future__ import annotations

import random

import pytest

np = pytest.importorskip("numpy")

from star.play.bench import obby_frame  # noqa: E402
from star.play.capture import FakeFrames  # noqa: E402
from star.play.humanlike import Actuator, HumanInput, RecordingSink  # noqa: E402
from star.play.loop import FastLoop, InputActor  # noqa: E402
from star.play.perception import ChatOCR, ColorDetector, YoloDetector  # noqa: E402
from star.play.planner import Goal  # noqa: E402
from star.play.roblox import ObbyController, ScreenObserver  # noqa: E402


def test_color_detector_finds_separate_blobs_with_positions():
    image = np.zeros((360, 640, 3), dtype=np.uint8)
    image[40:100, 40:160] = (0, 220, 0)
    image[200:300, 400:600] = (0, 220, 0)
    image[300:340, 280:340] = (230, 20, 20)
    found = ColorDetector({"green": ((0, 200, 0), (40, 255, 40)), "red": ((200, 0, 0), (255, 50, 50))}).detect(image)
    greens = sorted((d for d in found if d.label == "green"), key=lambda d: d.x)
    assert len(greens) == 2 and len([d for d in found if d.label == "red"]) == 1
    assert abs(greens[0].cx - 100) < 25 and abs(greens[1].cx - 500) < 25
    assert greens[1].area_frac > greens[0].area_frac
    assert ColorDetector({"x": ((0, 0, 0), (1, 1, 1))}).detect(np.zeros((4, 4, 3), dtype=np.uint8)) == []


class FakeSession:
    def __init__(self, output):
        self.output = output

    def get_inputs(self):
        return [type("I", (), {"name": "images"})()]

    def run(self, _names, feeds):
        assert feeds["images"].shape == (1, 3, 640, 640) and feeds["images"].dtype == np.float32
        return [self.output]


def test_yolo_decode_scales_back_and_suppresses_duplicates():
    # 1280x720 frame -> scale 0.5, letterbox pad_y = (640 - 360) / 2 = 140
    cols = [[320, 140 + 180, 100, 50, 0.9, 0.0],     # player at frame (640, 360), 200 x 100
            [322, 140 + 181, 100, 50, 0.8, 0.0],     # duplicate of it
            [100, 140 + 50, 20, 20, 0.0, 0.7],       # coin
            [500, 300, 20, 20, 0.1, 0.2]]            # below confidence
    raw = np.array(cols, dtype=np.float32).T[None]   # (1, 4 + 2, N)
    det = YoloDetector(FakeSession(raw), ["player", "coin"])
    found = det.detect(np.zeros((720, 1280, 3), dtype=np.uint8))
    assert sorted(d.label for d in found) == ["coin", "player"]
    player = next(d for d in found if d.label == "player")
    assert abs(player.cx - 640) < 1 and abs(player.cy - 360) < 1 and abs(player.w - 200) < 1


def test_chat_ocr_returns_only_new_name_lines():
    rows = [[[[0, 30], [100, 30], [100, 40], [0, 40]], "Mia: wanna race?", 0.93],
            [[[0, 10], [100, 10], [100, 20], [0, 20]], "[Bob]: hi", 0.91],
            [[[0, 50], [100, 50], [100, 60], [0, 60]], "blurry", 0.3]]
    ocr = ChatOCR(lambda crop: rows)
    first = ocr.read(np.zeros((720, 1280, 3), dtype=np.uint8))
    assert [(c.author, c.text) for c in first] == [("Bob", "hi"), ("Mia", "wanna race?")]
    assert ocr.read(np.zeros((720, 1280, 3), dtype=np.uint8)) == []


def test_fake_frame_to_key_events_end_to_end():
    controller = ObbyController()
    sink = RecordingSink()
    actuator = Actuator(sink)
    observer = ScreenObserver(FakeFrames(lambda i: obby_frame(1)), controller.detector())
    fast = FastLoop(observer, controller, InputActor(HumanInput(rng=random.Random(1)), actuator))
    fast.tick()
    assert fast.goal == Goal("advance")
    actuator.pump(1e9)
    keys = {(c[1], c[2]) for c in sink.calls if c[0] == "key"}
    assert ("w", True) in keys                              # saw the platform ahead and walked toward it
    percept = fast.latest
    assert percept.of("platform") and percept.stage_ms["detect"] >= 0
    assert fast.stats.summary()["capture_to_action"]["n"] == 1
