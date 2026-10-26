"""Offline tests: synthetic CSV is never proof of physical GPU testing."""
import io
import pytest
from star.presentmon_frame_bridge import PresentMonCaptureWorker, PresentMonFrameBridge
from star.stream_hardware_telemetry import RealtimeTelemetryHost

HEADER = "Application,ProcessID,SwapChainAddress,TimeInSeconds,msBetweenPresents,Dropped\n"

class Clock:
    def __init__(self):
        self.now = 2000.0
        self.cpu = (100, 1000)

    def step(self, ms=16):
        self.now += ms

def host(c):
    h = RealtimeTelemetryHost(
        gpu_probe=lambda: {"vram_total_mib": 8192, "vram_used_mib": 2000},
        memory_probe=lambda: (32768, 24000),
        cpu_probe=lambda: c.cpu,
        clock_ms=lambda: c.now,
    )
    h.set_context(owner_approved=True, live=True, game_active=True)
    assert h.refresh_hardware()
    c.cpu = (110, 1100)
    assert h.refresh_hardware()
    return h

def row(t, *, pid=4321, app="RobloxPlayerBeta.exe", chain="0xABCD", drop=0, ms=16):
    return f"{app},{pid},{chain},{t:.6f},{ms},{drop}\n"

def feed(h, c, *, chain=None):
    p = PresentMonFrameBridge(
        h, game_pid=4321, application="RobloxPlayerBeta.exe",
        swap_chain=chain, clock_ms=lambda: c.now,
    )
    assert not p.feed_line(HEADER)
    return p

def populate(p, c, *, count=16, chain="0xABCD", start=.100):
    for i in range(count):
        c.step()
        assert p.feed_line(row(start + .016 * i, chain=chain))

def fps(h, c):
    assert h.report_audio_backlog(backlog_ms=20, at_ms=c.now)
    c.cpu = (c.cpu[0] + 10, c.cpu[1] + 100)
    assert h.refresh_hardware()
    sample = h.snapshot()
    assert sample is not None
    return sample.telemetry.game_fps

def test_frames_feed_measured_host_qos():
    c = Clock()
    h = host(c)
    p = feed(h, c)
    populate(p, c)
    assert fps(h, c) == pytest.approx(62.5)
    assert h.snapshot().qos is not None
    assert p.status()["accepted"] == 16
    assert p.status()["healthy"]
    assert "4321" not in str(p.status())

def test_hardware_does_not_imply_game_frame_success():
    c = Clock()
    h = host(c)
    assert h.report_audio_backlog(backlog_ms=10, at_ms=c.now)
    assert h.snapshot() is None

def test_stream_preamble_and_missing_header_failure():
    c = Clock()
    h = host(c)
    p = feed(h, c)
    populate(p, c)
    assert fps(h, c) > 50
    other = PresentMonFrameBridge(h, game_pid=4321, clock_ms=lambda: c.now)
    for _ in range(32):
        assert not other.feed_line("starting capture\n")
    assert other.status()["error"] == "missing_header"

@pytest.mark.parametrize("bad_header", [
    "Application,ProcessID,SwapChainAddress,TimeInSeconds,Dropped\n",
    "Application,ProcessID,ProcessID,SwapChainAddress,TimeInSeconds,msBetweenPresents,Dropped\n",
    "Application,ProcessID,SwapChainAddress,TimeInSeconds,msBetweenPresents,Dropped,ProcessId\n",
])
def test_schema_strict(bad_header):
    c = Clock()
    p = PresentMonFrameBridge(host(c), game_pid=4321, clock_ms=lambda: c.now)
    assert not p.feed_line(bad_header)
    assert not p.status()["healthy"]

def test_pid_and_application_scoped():
    c = Clock()
    h = host(c)
    p = feed(h, c)
    assert not p.feed_line(row(.10, pid=1))
    assert p.status()["healthy"]
    assert not p.feed_line(row(.10, app="AnotherGame.exe"))
    assert p.status()["error"] == "application_mismatch"

def test_explicit_chain_ignores_other_chains():
    c = Clock()
    h = host(c)
    p = feed(h, c, chain="abcd")
    assert not p.feed_line(row(.10, chain="0xF00"))
    populate(p, c)
    assert not p.feed_line(row(.40, chain="0xF00"))
    assert p.status()["healthy"]
    assert fps(h, c) > 50

def test_unselected_extra_swapchain_invalidates_fps():
    c = Clock()
    h = host(c)
    p = feed(h, c)
    populate(p, c)
    assert fps(h, c) > 50
    assert not p.feed_line(row(.4, chain="0xF00"))
    assert p.status()["error"] == "multiple_swapchains"
    assert h.snapshot() is None

def test_dropped_frames_ignored():
    c = Clock()
    h = host(c)
    p = feed(h, c)
    assert not p.feed_line(row(.08, drop=1))
    populate(p, c)
    assert p.status()["accepted"] == 16
    assert fps(h, c) == pytest.approx(62.5)

def test_collector_shutdown_invalidates_fps():
    c = Clock()
    h = host(c)
    p = feed(h, c)
    populate(p, c)
    assert fps(h, c) > 50
    p.invalidate()
    assert h.snapshot() is None

def test_delayed_or_batched_output_cannot_invent_live_fps():
    c = Clock()
    h = host(c)
    p = feed(h, c)
    c.step()
    assert p.feed_line(row(.10))
    c.step(180)
    assert not p.feed_line(row(.116))
    assert p.status()["error"] == "nonlive_capture"
    assert h.snapshot() is None

    p2 = feed(h, c)
    c.step()
    assert p2.feed_line(row(.10))
    assert not p2.feed_line(row(.20))
    assert p2.status()["error"] == "nonlive_capture"

def test_duplicate_frames_and_epoch_reuse_rejected():
    c = Clock()
    h = host(c)
    p = feed(h, c)
    populate(p, c)
    assert fps(h, c) > 50
    assert not p.feed_line(row(.10))
    assert p.status()["error"] == "nonmonotonic_source"
    assert h.snapshot() is None

    p2 = feed(h, c)
    c.step()
    assert p2.feed_line(row(.25))
    h.set_context(owner_approved=True, live=True, game_active=True)
    c.step()
    assert not p2.feed_line(row(.266))
    assert p2.status()["error"] == "context_changed"

@pytest.mark.parametrize("source", [
    "RobloxPlayerBeta.exe,4321,0xABCD,abc,16,0\n",
    "RobloxPlayerBeta.exe,4321,0xABCD,nan,16,0\n",
    "RobloxPlayerBeta.exe,4321,0xABCD,.1,-1,0\n",
    "RobloxPlayerBeta.exe,4321,0xABCD,.1,16,2\n",
    "RobloxPlayerBeta.exe,4321,0x0,.1,16,0\n",
    "RobloxPlayerBeta.exe,4321,0xABCD,.1,16\n",
    "RobloxPlayerBeta.exe,4321,0xABCD,.1,16,0,extra\n",
])
def test_malformed_event_fails_conservatively(source):
    c = Clock()
    h = host(c)
    p = feed(h, c)
    assert not p.feed_line(source)
    assert not p.status()["healthy"]
    assert h.snapshot() is None

def test_input_limits_and_constructor_validation():
    c = Clock()
    h = host(c)
    p = feed(h, c)
    assert not p.feed_line("x" * 5000)
    assert p.status()["error"] == "oversized_line"
    for options in [
        {"game_pid": 0},
        {"game_pid": True},
        {"game_pid": 4321, "swap_chain": "0"},
        {"game_pid": 4321, "application": "../bad.exe"},
    ]:
        with pytest.raises((ValueError, TypeError)):
            PresentMonFrameBridge(h, **options)

def test_opt_in_worker_does_not_run_without_owner_approval():
    c = Clock()
    h = host(c)
    worker = PresentMonCaptureWorker(h, executable="/no/such/PresentMon.exe", game_pid=4321)
    with pytest.raises(PermissionError):
        worker.start()
    worker.stop()

def test_epoch_fence_prevents_old_source_wiping_new_game():
    c = Clock()
    h = host(c)
    old = h.context_epoch()
    h.set_context(owner_approved=True, live=True, game_active=True)
    assert not h.presented_frame(c.now, expected_epoch=old)
    active = feed(h, c)
    populate(active, c)
    assert fps(h, c) > 50
    h.invalidate_game_frames(expected_epoch=old)
    assert h.snapshot() is not None

class StubCapture:
    def __init__(self):
        self.stdout = io.StringIO(HEADER + row(.100))
        self.exit = None

    def poll(self):
        return self.exit

    def terminate(self):
        self.exit = 0

    def wait(self, timeout=None):
        self.exit = 0
        return self.exit

    def kill(self):
        self.exit = -9

def test_windows_capture_scoped_arguments_and_no_elevation(tmp_path):
    c = Clock()
    h = host(c)
    exe = tmp_path / "PresentMon.exe"
    exe.write_bytes(b"test fixture")
    calls = []

    def subprocess_factory(args, **options):
        calls.append((args, options))
        return StubCapture()

    worker = PresentMonCaptureWorker(
        h, executable=str(exe), game_pid=4321,
        clock_ms=lambda: c.now, platform_name="nt",
        popen_factory=subprocess_factory,
    )
    worker.start(owner_approved=True)
    worker._thread.join(timeout=2)
    assert len(calls) == 1
    args, options = calls[0]
    assert args[1:3] == ["--process_id", "4321"]
    assert "--output_stdout" in args
    assert "--v1_metrics" in args
    assert "--exclude_dropped" in args
    assert "--restart_as_admin" not in args
    assert options["shell"] is False
    assert worker.status()["running"] is False
    assert worker.status()["error"] == "collector_stopped"
    with pytest.raises(RuntimeError):
        worker.start(owner_approved=True)
    worker.stop()
