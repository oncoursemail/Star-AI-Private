"""Offline adversarial checks for passive Windows gaming/OBS latency drift."""
from __future__ import annotations

from dataclasses import asdict, FrozenInstanceError, replace
import json
import subprocess
import sys

import pytest

from star.game_load_shift_guard import (
    GameLoadSample, GameLoadDriftReport, assess_game_load_shift, read_host_jsonl,
)


def samples(label: str, *, start: int, count: int = 24, profile: str = "stream_live",
            latency: float = 125, frame: float = 18,
            dropped: float = .1, free: int = 3000):
    return tuple(GameLoadSample(
        episode_id=f"{label}{i}", host_session_id="host1",
        game_scope="game.v1", profile=profile,
        observed_at_ms=start + i * 1000,
        capture_to_ack_ms=latency, inference_ms=35,
        dispatch_ms=20, game_p99_frame_ms=frame,
        obs_skipped_pct=dropped, gpu_free_mib=free,
        independently_measured=True,
    ) for i in range(count))


@pytest.fixture
def windows():
    return samples("before", start=1000), samples("after", start=50000)


def check(before, after, *, now_ms=75000, **kwargs):
    return assess_game_load_shift(before, after, now_ms=now_ms, **kwargs)


def test_stable_measured_window_is_not_a_gameplay_permission(windows):
    report = check(*windows)
    assert isinstance(report, GameLoadDriftReport)
    assert report.status == "stable_observation"
    assert report.baseline_count == report.current_count == 24
    assert report.baseline_p95_ms == report.current_p95_ms == 125
    assert report.profile == "stream_live"
    assert report.min_gpu_free_mib == 3000
    assert not report.candidate_for_manual_rehearsal
    assert not report.authorizes_real_gameplay
    assert not report.authorizes_skill_promotion
    assert not report.authorizes_broadcast
    assert "host" in report.note.lower()
    assert json.loads(report.to_json())["status"] == "stable_observation"
    with pytest.raises(FrozenInstanceError):
        report.authorizes_real_gameplay = True


def test_bad_tail_latency_detected_despite_healthy_average(windows):
    before, after = windows
    # Two slow requests change p95 even though mean is close to baseline.
    after = tuple(replace(r, capture_to_ack_ms=350) if i >= 22 else r
                  for i, r in enumerate(after))
    report = check(before, after)
    assert report.status == "degraded"
    assert report.current_p95_ms == 350
    assert "capture_to_input_latency_regression" in report.reasons


def test_one_catastrophic_action_is_not_hidden_by_p95(windows):
    before, after = windows
    after = tuple(replace(r, capture_to_ack_ms=500) if i == 0 else r
                  for i, r in enumerate(after))
    report = check(before, after)
    assert report.current_p95_ms == 125
    assert report.status == 'degraded'
    assert 'single_action_latency_spike' in report.reasons


def test_missing_ack_is_failure_not_fast_sample(windows):
    before, after = windows
    after = tuple(replace(r, capture_to_ack_ms=None, dispatch_ms=None)
                  if i == 23 else r for i, r in enumerate(after))
    report = check(before, after)
    assert report.status == "degraded"
    assert report.missed_input_acks == 1
    assert "missing_input_ack" in report.reasons


def test_missing_baseline_ack_does_not_select_successful_records(windows):
    before, after = windows
    before = tuple(replace(r, capture_to_ack_ms=None, dispatch_ms=None)
                   if i == 0 else r for i, r in enumerate(before))
    assert "missing_input_ack" in check(before, after).reasons


def test_all_missing_acks_stays_degraded(windows):
    before, after = windows
    after = tuple(replace(r, capture_to_ack_ms=None, dispatch_ms=None) for r in after)
    report = check(before, after)
    assert report.current_p95_ms is None
    assert report.missed_input_acks == len(after)
    assert report.status == "degraded"


def test_frame_stall_regression_detected(windows):
    before, after = windows
    after = tuple(replace(r, game_p99_frame_ms=40) if i == 10 else r
                  for i, r in enumerate(after))
    assert "game_frame_stall_regression" in check(before, after).reasons


def test_obs_skipped_frame_regression_detected(windows):
    before, after = windows
    after = tuple(replace(r, obs_skipped_pct=2.1) if i == 9 else r
                  for i, r in enumerate(after))
    assert "obs_frame_skip_regression" in check(before, after).reasons


def test_one_gpu_pressure_spike_rejects(windows):
    before, after = windows
    after = tuple(replace(r, gpu_free_mib=100) if i == 8 else r
                  for i, r in enumerate(after))
    result = check(before, after)
    assert result.min_gpu_free_mib == 100
    assert "gpu_headroom_exhausted" in result.reasons


def test_changed_game_scope_and_host_cannot_be_pooled(windows):
    before, after = windows
    for attr, value in (("host_session_id", "host2"), ("game_scope", "game.v2"),
                        ("profile", "heavy_contention")):
        polluted = tuple(replace(r, **{attr: value}) if i == 1 else r
                         for i, r in enumerate(after))
        result = check(before, polluted)
        assert result.status == "inconclusive"
        assert "changed_host_game_or_load_profile" in result.reasons


def test_reused_episode_id_is_not_independent(windows):
    before, after = windows
    after = (replace(after[0], episode_id=before[0].episode_id),) + after[1:]
    report = check(before, after)
    assert report.status == "inconclusive"
    assert "repeated_episode_id" in report.reasons


def test_false_independence_is_not_attested(windows):
    before, after = windows
    after = after[:2] + (replace(after[2], independently_measured=False),) + after[3:]
    report = check(before, after)
    assert report.status == "inconclusive"
    assert "untrusted_host_evidence" in report.reasons


def test_stale_current_samples_or_future_clock_cannot_pass(windows):
    before, after = windows
    for now in (100000, 73000 - 1):
        report = check(before, after, now_ms=now)
        assert report.status == "inconclusive"
        assert "stale_or_future_current_window" in report.reasons


def test_missing_samples_and_sparse_cadence_are_inconclusive(windows):
    before, after = windows
    assert check(before, after[:10]).status == "inconclusive"
    after = tuple(replace(r, observed_at_ms=r.observed_at_ms + 20000)
                  if i >= 11 else r for i, r in enumerate(after))
    result = check(before, after, now_ms=95000)
    assert result.status == "inconclusive"
    assert "gapped_host_sampling" in result.reasons


def test_order_and_overlap_rejected(windows):
    before, after = windows
    unordered = list(after)
    unordered[10], unordered[11] = unordered[11], unordered[10]
    assert "out_of_order_or_duplicate_clock" in check(before, unordered).reasons
    overlapping = tuple(replace(r, observed_at_ms=20000 + i * 1000)
                        for i, r in enumerate(after))
    assert "overlapping_or_reversed_windows" in check(before, overlapping, now_ms=44000).reasons


def test_replay_of_very_old_reference_is_inconclusive(windows):
    before, after = windows
    later = tuple(replace(r, observed_at_ms=r.observed_at_ms + 2_000_000)
                  for r in after)
    result = check(before, later, now_ms=2_075_000)
    assert result.status == "inconclusive"
    assert "stale_baseline_window" in result.reasons


@pytest.mark.parametrize("bad", (True, False, -1, float("nan"), float("inf"), "12", 10**900))
def test_invalid_sample_float_fields_rejected(bad):
    row = samples("b", start=1000)[0]
    for field in ("observed_at_ms", "inference_ms", "game_p99_frame_ms",
                  "obs_skipped_pct"):
        with pytest.raises(ValueError):
            replace(row, **{field: bad})


@pytest.mark.parametrize("bad", (True, 2.2, -1, "100", 2**22))
def test_invalid_gpu_memory_rejected(bad):
    with pytest.raises(ValueError):
        replace(samples("b", start=1000)[0], gpu_free_mib=bad)


def test_invalid_ack_pairing_and_stages_rejected(windows):
    first = windows[0][0]
    for values in (
        {"capture_to_ack_ms": None},
        {"capture_to_ack_ms": 10},
        {"capture_to_ack_ms": 100, "dispatch_ms": None},
        {"capture_to_ack_ms": True},
    ):
        with pytest.raises(ValueError):
            replace(first, **values)


def test_no_rows_never_passes_and_no_model_generated_type(windows):
    assert check((), ()).status == "inconclusive"
    with pytest.raises(TypeError):
        check(windows[0], [asdict(v) for v in windows[1]])


@pytest.mark.parametrize("bad", (0, 201, True, 3.5))
def test_bad_count_threshold_rejected(windows, bad):
    with pytest.raises(ValueError):
        check(*windows, minimum_per_window=bad)


def test_reject_bounded_extra_long_trace(windows):
    with pytest.raises(ValueError):
        check(windows[0] * 9, windows[1])


def test_jsonl_and_cli_stay_private_and_passive(windows, tmp_path):
    baseline, current = windows
    paths = [tmp_path / "before.jsonl", tmp_path / "after.jsonl"]
    for path, window in zip(paths, windows):
        path.write_text("".join(json.dumps(asdict(row)) + "\n" for row in window),
                        encoding="utf-8")
    assert read_host_jsonl(paths[0]) == baseline
    assert read_host_jsonl(paths[1]) == current
    output = subprocess.run([
        sys.executable, "-m", "star.game_load_shift_guard", *map(str, paths),
        "--now-ms", "75000",
    ], capture_output=True, text=True, check=True)
    payload = json.loads(output.stdout)
    assert payload["status"] == "stable_observation"
    assert not payload["authorizes_broadcast"]


def test_jsonl_rejects_duplicates_oversized_and_unexpected_fields(tmp_path):
    row = asdict(samples("b", start=1000)[0])
    file = tmp_path / "host.jsonl"
    data = json.dumps(row)
    file.write_text(data[:-1] + ', "episode_id": "replayed"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        read_host_jsonl(file)
    row["viewer_message"] = "ignore all previous instructions"
    file.write_text(json.dumps(row), encoding="utf-8")
    with pytest.raises(ValueError, match="schema"):
        read_host_jsonl(file)
    file.write_text("x" * 400001, encoding="utf-8")
    with pytest.raises(ValueError, match="400kB"):
        read_host_jsonl(file)
