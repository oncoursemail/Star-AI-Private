"""Offline, adversarial tests for the real Windows private rehearsal CLI."""
from __future__ import annotations

from contextlib import redirect_stdout
from dataclasses import replace
import io
import json
import unittest
from unittest.mock import patch

from star.stream_windows_private_rehearsal_cli import (
    PrivateRehearsalReadiness,
    check_private_rehearsal_readiness,
    main,
)
from star.stream_recording_disk_guard import RecordingDiskAdvice
from star.stream_windows_rehearsal_preflight import GpuHeadroom, ProcessWitness


GPU_UUID = "GPU-11111111-2222-3333-4444-555555555555"
PIN = 410
GAME = "RobloxPlayerBeta.exe"


def hosts() -> tuple[ProcessWitness, ...]:
    return (
        ProcessWitness("obs64.exe", 401, 101.0),
        ProcessWitness("VTube Studio.exe", 402, 102.0),
        ProcessWitness("llama-server.exe", 403, 103.0),
        ProcessWitness(GAME, PIN, 104.0),
    )


def gpu(index: int) -> GpuHeadroom:
    assert index == 0
    return GpuHeadroom(8192, 3200, 34, device_uuid=GPU_UUID)


class Clock:
    def __init__(self) -> None:
        self.value = 150.0

    def now(self) -> float:
        return self.value

    def sleep(self, n: float) -> None:
        self.value += n


def run(**kwargs) -> PrivateRehearsalReadiness:
    c = Clock()
    return check_private_rehearsal_readiness(
        owner_approved=True, game_pid=PIN, game_exe=GAME,
        process_reader=hosts, gpu_reader=gpu,
        system_name=lambda: "Windows", clock=c.now, sleeper=c.sleep,
        **kwargs,
    )


class ReadinessTests(unittest.TestCase):
    def test_success_is_candidate_never_live_proof_or_authorization(self) -> None:
        result = run()
        self.assertEqual(result.status, "candidate")
        self.assertTrue(result.game_process_pinned)
        self.assertTrue(result.stable_processes)
        self.assertEqual(result.samples, 5)
        self.assertEqual(result.window_ms, 2000)
        self.assertEqual(result.min_free_gpu_mib, 3200)
        for flag in (
            "game_frames_verified", "voice_audible_verified",
            "avatar_frames_verified", "obs_recording_verified",
            "authorizes_gameplay", "authorizes_broadcast",
        ):
            self.assertFalse(getattr(result, flag))

    def test_output_never_discloses_processes_or_gpu_uuid(self) -> None:
        blob = run().to_json()
        payload = json.loads(blob)
        self.assertFalse(payload["authorizes_broadcast"])
        for secret in (GPU_UUID, "RobloxPlayerBeta", "obs64", "104.0", "410"):
            self.assertNotIn(secret, blob)

    def test_no_game_pin_is_read_only_deferred_not_a_false_ready(self) -> None:
        c = Clock()
        report = check_private_rehearsal_readiness(
            owner_approved=True, process_reader=hosts, gpu_reader=gpu,
            system_name=lambda: "Windows", clock=c.now, sleeper=c.sleep,
        )
        self.assertEqual(report.status, "deferred")
        self.assertIn("pinned_game_process_missing_or_restarted", report.reasons)
        self.assertFalse(report.game_process_pinned)
        self.assertEqual(report.samples, 5)

    def test_missing_or_mismatched_game_returns_unavailable_without_gpu_query(self) -> None:
        touched: list[int] = []
        c = Clock()
        result = check_private_rehearsal_readiness(
            owner_approved=True, game_pid=PIN, game_exe="AnotherGame.exe",
            process_reader=hosts,
            gpu_reader=lambda i: (touched.append(i) or gpu(i)),
            system_name=lambda: "Windows", clock=c.now, sleeper=c.sleep,
        )
        self.assertEqual(result.status, "unavailable")
        self.assertEqual(result.reasons, ("game_pid_or_basename_not_running",))
        self.assertFalse(touched)

    def test_game_pid_reused_between_snapshots_fails_closed(self) -> None:
        c = Clock()
        calls = 0

        def process_reader():
            nonlocal calls
            calls += 1
            if calls >= 3:
                return hosts()[:-1] + (ProcessWitness(GAME, PIN, 200.0),)
            return hosts()

        report = check_private_rehearsal_readiness(
            owner_approved=True, game_pid=PIN, game_exe=GAME,
            process_reader=process_reader, gpu_reader=gpu,
            system_name=lambda: "Windows", clock=c.now, sleeper=c.sleep,
        )
        self.assertEqual(report.status, "unavailable")
        self.assertIn("local_process_snapshot_unavailable", report.reasons)

    def test_game_basename_changes_between_snapshots_fails_closed(self) -> None:
        c = Clock()
        calls = 0

        def process_reader():
            nonlocal calls
            calls += 1
            if calls > 2:
                return hosts()[:-1] + (ProcessWitness("renamed.exe", PIN, 104.0),)
            return hosts()

        report = check_private_rehearsal_readiness(
            owner_approved=True, game_pid=PIN, game_exe=GAME,
            process_reader=process_reader, gpu_reader=gpu,
            system_name=lambda: "Windows", clock=c.now, sleeper=c.sleep,
        )
        self.assertEqual(report.status, "unavailable")
        self.assertIn("local_process_snapshot_unavailable", report.reasons)

    def test_transient_low_vram_is_a_defer(self) -> None:
        calls = 0

        def pressure(index: int) -> GpuHeadroom:
            nonlocal calls
            calls += 1
            return replace(gpu(index), free_mib=(128 if calls == 3 else 3200))

        c = Clock()
        report = check_private_rehearsal_readiness(
            owner_approved=True, game_pid=PIN, game_exe=GAME,
            process_reader=hosts, gpu_reader=pressure,
            system_name=lambda: "Windows", clock=c.now, sleeper=c.sleep,
        )
        self.assertEqual(report.status, "deferred")
        self.assertIn("insufficient_free_gpu_memory", report.reasons)
        self.assertEqual(report.min_free_gpu_mib, 128)

    def test_process_identity_change_prevents_candidate(self) -> None:
        calls = 0

        def processes():
            nonlocal calls
            calls += 1
            if calls == 4:
                return hosts()[:2] + (
                    ProcessWitness("llama-server.exe", 999, 999.0),
                    hosts()[3],
                )
            return hosts()

        c = Clock()
        report = check_private_rehearsal_readiness(
            owner_approved=True, game_pid=PIN, game_exe=GAME,
            process_reader=processes, gpu_reader=gpu,
            system_name=lambda: "Windows", clock=c.now, sleeper=c.sleep,
        )
        self.assertEqual(report.status, "deferred")
        self.assertIn("process_identity_changed_during_window", report.reasons)

    def test_permission_check_runs_before_host_readers(self) -> None:
        with self.assertRaises(PermissionError):
            check_private_rehearsal_readiness(
                process_reader=lambda: self.fail("process read forbidden"),
                gpu_reader=lambda _: self.fail("GPU read forbidden"),
                system_name=lambda: self.fail("system read forbidden"),
            )

    def test_non_windows_never_probes_hardware(self) -> None:
        report = check_private_rehearsal_readiness(
            owner_approved=True,
            process_reader=lambda: self.fail("no process query"),
            gpu_reader=lambda _: self.fail("no GPU query"),
            system_name=lambda: "Linux",
        )
        self.assertEqual(report.status, "unavailable")
        self.assertEqual(report.reasons, ("windows_host_required",))

    def test_invalid_game_pin_options_never_probe(self) -> None:
        bad_options = [
            dict(game_pid=PIN, game_exe=None),
            dict(game_pid=None, game_exe=GAME),
            dict(game_pid=0, game_exe=GAME),
            dict(game_pid=True, game_exe=GAME),
            dict(game_pid=PIN, game_exe="..\\secret.exe"),
            dict(game_pid=PIN, game_exe="python.exe"),
            dict(game_pid=PIN, game_exe="obs64.exe"),
            dict(game_pid=PIN, game_exe="explorer.exe"),
            dict(game_pid=PIN, game_exe="n" * 120 + ".exe"),
        ]
        for opts in bad_options:
            with self.subTest(options=opts), self.assertRaises(ValueError):
                check_private_rehearsal_readiness(
                    owner_approved=True, **opts,
                    system_name=lambda: self.fail("validate before any system query"),
                )

    def test_invalid_probe_configuration_rejected_before_io(self) -> None:
        for options in (
            dict(samples=2), dict(interval_s=0.1),
            dict(interval_s=float("nan")), dict(gpu_index=-1),
            dict(samples=True), dict(interval_s=True),
        ):
            with self.subTest(options=options), self.assertRaises(ValueError):
                check_private_rehearsal_readiness(
                    owner_approved=True, **options,
                    system_name=lambda: self.fail("invalid request read system"),
                )

    def test_cli_default_requires_explicit_observe(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = main([])
        self.assertEqual(exit_code, 2)
        parsed = json.loads(output.getvalue())
        self.assertEqual(parsed["reasons"], ["explicit_observe_flag_required"])
        self.assertFalse(parsed["authorizes_broadcast"])

    def test_cli_invalid_args_are_sanitized(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = main(["--observe", "--samples", "1"])
        self.assertEqual(exit_code, 1)
        # The underlying checker rejects bad config, so no system reads occur.
        self.assertEqual(json.loads(output.getvalue())["reasons"], ["invalid_probe_configuration"])

    def test_cli_success_contract_and_exit_code(self) -> None:
        c = Clock()

        def fake_runner(**kwargs):
            return check_private_rehearsal_readiness(
                owner_approved=True, game_pid=PIN, game_exe=GAME,
                process_reader=hosts, gpu_reader=gpu,
                system_name=lambda: "Windows", clock=c.now, sleeper=c.sleep,
            )

        output = io.StringIO()
        with patch("star.stream_windows_private_rehearsal_cli.check_private_rehearsal_readiness", fake_runner):
            with redirect_stdout(output):
                exit_code = main(["--observe"])
        self.assertEqual(exit_code, 0)
        self.assertEqual(json.loads(output.getvalue())["status"], "candidate")


    def test_cli_recording_guard_defers_low_disk_without_exposing_path(self) -> None:
        ready = replace(run(), status="candidate")
        class FakeGuard:
            def __init__(self, directory: str):
                self.directory = directory
            def check(self, *, owner_approved: bool = False) -> RecordingDiskAdvice:
                self_status = "deferred" if owner_approved else "unavailable"
                return RecordingDiskAdvice(self_status, "insufficient_recording_disk_headroom",
                                           1650, 10768)
        output = io.StringIO()
        with patch("star.stream_windows_private_rehearsal_cli.check_private_rehearsal_readiness",
                   return_value=ready), patch(
                       "star.stream_windows_private_rehearsal_cli.RecordingDiskGuard", FakeGuard):
            with redirect_stdout(output):
                exit_code = main(["--observe", "--recording-dir", "C:\\private\\recordings"])
        self.assertEqual(exit_code, 1)
        data = json.loads(output.getvalue())
        self.assertEqual(data["status"], "deferred")
        self.assertTrue(data["recording_storage_checked"])
        self.assertFalse(data["recording_storage_ready"])
        self.assertEqual(data["recording_free_mib"], 1650)
        self.assertIn("insufficient_recording_disk_headroom", data["reasons"])
        self.assertNotIn("private", output.getvalue())

    def test_cli_recording_guard_advisory_is_not_recording_permission(self) -> None:
        ready = replace(run(), status="candidate")
        class FakeGuard:
            def __init__(self, directory: str):
                pass
            def check(self, *, owner_approved: bool = False) -> RecordingDiskAdvice:
                return RecordingDiskAdvice("candidate", "recording_storage_headroom_observed",
                                           20000, 10768)
        output = io.StringIO()
        with patch("star.stream_windows_private_rehearsal_cli.check_private_rehearsal_readiness",
                   return_value=ready), patch(
                       "star.stream_windows_private_rehearsal_cli.RecordingDiskGuard", FakeGuard):
            with redirect_stdout(output):
                code = main(["--observe", "--recording-dir", "C:\\recordings"])
        self.assertEqual(code, 0)
        result = json.loads(output.getvalue())
        self.assertTrue(result["recording_storage_ready"])
        self.assertFalse(result["obs_recording_verified"])
        self.assertFalse(result["authorizes_broadcast"])
        self.assertFalse(result["authorizes_gameplay"])

    def test_cli_requires_observe_before_recording_disk_access(self) -> None:
        output = io.StringIO()
        with patch("star.stream_windows_private_rehearsal_cli.RecordingDiskGuard",
                   side_effect=AssertionError("disk must not be touched")):
            with redirect_stdout(output):
                code = main(["--recording-dir", "C:\\recordings"])
        self.assertEqual(code, 2)
        self.assertFalse(json.loads(output.getvalue())["recording_storage_checked"])

    def test_cli_disk_guard_configuration_error_does_not_leak(self) -> None:
        ready = replace(run(), status="candidate")
        output = io.StringIO()
        with patch("star.stream_windows_private_rehearsal_cli.check_private_rehearsal_readiness",
                   return_value=ready):
            with redirect_stdout(output):
                code = main(["--observe", "--recording-dir", "relative/secret"])
        self.assertEqual(code, 1)
        data = json.loads(output.getvalue())
        self.assertEqual(data["status"], "unavailable")
        self.assertIn("recording_disk_probe_invalid", data["reasons"])
        self.assertNotIn("secret", output.getvalue())


if __name__ == "__main__":
    unittest.main()
