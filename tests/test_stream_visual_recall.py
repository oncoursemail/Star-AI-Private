"""Offline visual-recall tests: synthesized windows only, no GPU/game/network."""
from __future__ import annotations

from io import BytesIO
from threading import Event, Thread

from PIL import Image, ImageDraw
import pytest

from star.stream_visual_recall import VisualRecallHost
from star.stream_windows_game_capture import CapturedVisionFrame, WorkerReport


def frame(at: float, *, variant: int = 0, size=(320, 240)) -> CapturedVisionFrame:
    image = Image.new("RGB", size, (31, 41, 51))
    painter = ImageDraw.Draw(image)
    if variant == 1:
        painter.rectangle((10, 20, 105, 110), fill=(20, 225, 30))
    elif variant == 2:
        painter.rectangle((195, 20, 300, 110), fill=(240, 28, 28))
    elif variant == 3:
        painter.rectangle((10, 20, 105, 110), fill=(30, 30, 235))
    return CapturedVisionFrame(memoryview(image.tobytes()), *size, at)


def recall(**options) -> VisualRecallHost:
    host = VisualRecallHost(lambda _frame: WorkerReport(True, True), **options)
    host.enable(owner_approved=True, game_capture_approved=True)
    return host


def test_disabled_by_default_preserves_underlying_worker_semantics():
    seen = []
    def worker(value):
        seen.append(value)
        return WorkerReport(True, True)
    host = VisualRecallHost(worker)
    sample = frame(1000)
    assert host(sample) == WorkerReport(True, True)
    assert seen == [sample]
    assert host.recent(now_ms=1000) == ()
    assert host.metrics()["frames_cached"] == 0
    assert host.metrics()["recorded"] == 0


def test_explicit_opt_in_and_bounded_configuration():
    host = VisualRecallHost(lambda _: WorkerReport(True, True))
    with pytest.raises(PermissionError):
        host.enable(owner_approved=True)
    with pytest.raises(PermissionError):
        host.enable(game_capture_approved=True)
    host.enable(owner_approved=True, game_capture_approved=True)
    with pytest.raises(RuntimeError):
        host.enable(owner_approved=True, game_capture_approved=True)
    host.disable()
    for option, invalid in (
        ("max_frames", 9), ("max_frames", True),
        ("ttl_ms", 30001), ("max_bytes", 10),
        ("storage_side", 900), ("inspection_side", 20),
        ("min_spacing_ms", 0),
    ):
        with pytest.raises(ValueError):
            VisualRecallHost(lambda _: WorkerReport(True, True), **{option: invalid})
    with pytest.raises(TypeError):
        VisualRecallHost(None)


def test_revisit_prior_frame_in_host_selected_crop_without_model_call():
    calls = []
    def worker(value):
        calls.append(value.captured_ms)
        return WorkerReport(True, True)
    host = VisualRecallHost(worker, max_frames=3)
    host.enable(owner_approved=True, game_capture_approved=True)
    host(frame(1000, variant=1))
    host(frame(1500, variant=2))
    marks = host.recent(now_ms=1600)
    assert len(marks) == 2 and marks[0].captured_ms == 1000
    assert marks[0].frame_id != marks[1].frame_id
    with pytest.raises(PermissionError):
        host.inspect(marks[0].frame_id, focus_box=(0, 0, 500, 1000),
                     now_ms=1600, owner_approved=True)
    inspected = host.inspect(marks[0].frame_id, focus_box=(0, 0, 500, 1000),
                             now_ms=1600, owner_approved=True,
                             inspection_approved=True)
    assert inspected is not None
    assert inspected.frame_id == marks[0].frame_id
    assert inspected.width < 256 and inspected.height <= 256
    with Image.open(BytesIO(inspected.jpeg)) as image:
        color = image.getpixel((35, 45))
        assert color[1] > color[0] * 2
    assert calls == [1000, 1500]  # replay did not call VLM a third time
    assert set(host.metrics()) >= {"frames_cached", "bytes_cached", "inspected"}
    assert "jpeg" not in host.metrics()
    inspected.erase()
    assert not any(inspected.jpeg)


def test_unchanged_frames_are_not_repeatedly_stored():
    host = recall()
    host(frame(1000))
    host(frame(1500))
    host(frame(2000))
    assert host.metrics()["recorded"] == 1
    assert host.metrics()["duplicate"] == 2
    assert len(host.recent(now_ms=2000)) == 1


def test_throttled_history_does_not_throttle_underlying_worker():
    seen = []
    host = VisualRecallHost(
        lambda value: (seen.append(value.captured_ms) or WorkerReport(True, True)),
        min_spacing_ms=300,
    )
    host.enable(owner_approved=True, game_capture_approved=True)
    host(frame(1000))
    host(frame(1100, variant=1))
    host(frame(1200, variant=2))
    assert seen == [1000, 1100, 1200]
    assert host.metrics()["throttled"] == 2
    assert host.metrics()["frames_cached"] == 1


def test_eviction_and_ttl_zeroize_cached_images():
    host = recall(max_frames=2, ttl_ms=2000)
    host(frame(1000))
    old = host._entries[0].jpeg
    host(frame(1500, variant=1))
    host(frame(2000, variant=2))
    assert all(x == 0 for x in old)
    assert host.metrics()["frames_cached"] == 2
    assert host.metrics()["evicted"] == 1
    previous = host._entries[0].jpeg
    assert host.recent(now_ms=4100) == ()
    assert not any(previous)
    assert host.metrics()["expired"] == 2
    assert host.metrics()["bytes_cached"] == 0


def test_inspect_crop_geometry_and_stale_bookmarks_fail_closed():
    host = recall()
    host(frame(1000))
    mark = host.recent(now_ms=1000)[0]
    for invalid in (
        [], "0,0,1000,1000", (0, 0, 4, 1000),
        (900, 900, 100, 100), (0, 0, True, 1000),
        (0, 0, 1001, 1000), (0, 1, 2),
    ):
        with pytest.raises(ValueError):
            host.inspect(mark.frame_id, focus_box=invalid, now_ms=1000,
                         owner_approved=True, inspection_approved=True)
    with pytest.raises(ValueError):
        host.inspect(mark.frame_id, focus_box=(0, 0, 1000, 1000),
                     now_ms=float("nan"), owner_approved=True,
                     inspection_approved=True)
    assert host.inspect("other-epoch:1", focus_box=(0, 0, 1000, 1000),
                        now_ms=1000, owner_approved=True,
                        inspection_approved=True) is None
    host.disable()
    assert host.inspect(mark.frame_id, focus_box=(0, 0, 1000, 1000),
                        now_ms=2000, owner_approved=True,
                        inspection_approved=True) is None
    host.enable(owner_approved=True, game_capture_approved=True)
    host(frame(3000, variant=1))
    assert host.recent(now_ms=3000)[0].frame_id != mark.frame_id


def test_disable_zeroizes_outstanding_inspection_buffers():
    host = recall()
    host(frame(1000))
    mark = host.recent(now_ms=1000)[0]
    crop = host.inspect(mark.frame_id, focus_box=(0, 0, 1000, 1000),
                        now_ms=1000, owner_approved=True,
                        inspection_approved=True)
    snapshot = host._entries[0].jpeg
    assert any(crop.jpeg) and any(snapshot)
    host.disable()
    assert not any(crop.jpeg) and not any(snapshot)
    assert host.metrics()["inspection_handles"] == 0
    assert host.metrics()["frames_cached"] == 0


def test_ambiguous_worker_stop_erases_history_and_preserves_safety_result():
    reports = iter([WorkerReport(True, True), WorkerReport(False, False)])
    host = VisualRecallHost(lambda _: next(reports))
    host.enable(owner_approved=True, game_capture_approved=True)
    host(frame(1000))
    encoded = host._entries[0].jpeg
    assert host(frame(1500, variant=1)) == WorkerReport(False, False)
    assert not any(encoded)
    assert host.metrics()["worker_uncertain"] == 1
    assert host.recent(now_ms=1600) == ()


def test_worker_exception_erases_history_and_propagates_to_capture_host():
    def worker(value):
        if value.captured_ms > 1100:
            raise TimeoutError("underlying worker state unknown")
        return WorkerReport(True, True)
    host = VisualRecallHost(worker)
    host.enable(owner_approved=True, game_capture_approved=True)
    host(frame(1000))
    prior = host._entries[0].jpeg
    with pytest.raises(TimeoutError):
        host(frame(1500, variant=2))
    assert not any(prior)
    assert host.metrics()["frames_cached"] == 0


def test_stale_or_malformed_frames_never_poison_recall():
    host = recall()
    host(frame(1000))
    before = host.recent(now_ms=1000)
    assert host(frame(800, variant=1)) == WorkerReport(True, True)
    assert host.metrics()["rejected"] == 1
    malformed = CapturedVisionFrame(memoryview(b"short"), 320, 240, 1500)
    assert host(malformed) == WorkerReport(True, True)
    assert host.metrics()["rejected"] == 2
    assert host.recent(now_ms=1500) == before
    with pytest.raises(ValueError):
        host.recent(now_ms=1400)


def test_late_response_after_disable_cannot_repopulate_old_or_new_session():
    entered, released = Event(), Event()
    result = []
    def slow_worker(_):
        entered.set()
        assert released.wait(5)
        return WorkerReport(True, True)
    host = VisualRecallHost(slow_worker)
    host.enable(owner_approved=True, game_capture_approved=True)
    thread = Thread(target=lambda: result.append(host(frame(1000))), daemon=True)
    thread.start()
    assert entered.wait(5)
    host.disable()
    host.enable(owner_approved=True, game_capture_approved=True)
    released.set()
    thread.join(5)
    assert not thread.is_alive()
    assert result == [WorkerReport(True, True)]
    assert host.recent(now_ms=1100) == ()


def test_outstanding_crop_handles_are_bounded_and_wiped():
    host = recall()
    host(frame(1000, variant=1))
    mark = host.recent(now_ms=1000)[0]
    results = [host.inspect(
        mark.frame_id, focus_box=(0, 0, 1000, 1000), now_ms=1000,
        owner_approved=True, inspection_approved=True,
    ) for _ in range(6)]
    assert host.metrics()["inspection_handles"] == 4
    assert not any(results[0].jpeg) and not any(results[1].jpeg)
    assert any(results[-1].jpeg)
    host.disable()
    assert not any(results[-1].jpeg)


def test_expired_inspection_handles_are_wiped_on_host_clock_progress():
    host = recall(ttl_ms=2000)
    host(frame(1000, variant=1))
    mark = host.recent(now_ms=1000)[0]
    crop = host.inspect(mark.frame_id, focus_box=(0, 0, 1000, 1000),
                        now_ms=1100, owner_approved=True,
                        inspection_approved=True)
    assert crop is not None and any(crop.jpeg)
    assert host.recent(now_ms=3001) == ()
    assert not any(crop.jpeg)
    assert host.metrics()["inspection_handles"] == 0
