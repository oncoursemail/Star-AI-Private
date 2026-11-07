"""Synthetic, offline network and gameplay QoS tests. No real stream is touched."""
from dataclasses import asdict, replace
import json

import pytest

from star.stream_network_qos_gate import (
    ObsStreamStatus, ObsTransportWindow, compare_realtime_obs_transport,
    read_transport_jsonl,
)
from star.stream_obs_qos_gate import ObsFrameWindow, ObsStatsCounters
from star.stream_realtime_benchmark import RealtimeRun


def run(pair, variant, *, ttfa=None):
    return RealtimeRun(
        pair, variant, "obby", "v3", 650.0 if variant == "baseline" else
        400.0 if ttfa is None else ttfa,
        (16.7,) * 150, 4800.0, True,
    )


def frame(pair, variant, *, drops=0):
    return ObsFrameWindow(
        pair, variant, "obby", "v3", f"session_{variant}",
        1000, 11000,
        ObsStatsCounters(1000, 0, 1000, 0),
        ObsStatsCounters(1600, drops, 1600, 0),
        True, False,
    )


def snapshot(duration, bytes_sent, total, skipped=0, *,
             active=True, reconnect=False, congestion=0):
    return ObsStreamStatus(
        active, reconnect, duration, bytes_sent, skipped, total, congestion
    )


def transport(pair, variant, *, dropped=0, reconnect=False,
              active=True, sent=1000000, duration=10000):
    return ObsTransportWindow(
        pair, variant, "obby", "v3", f"session_{variant}",
        1000, 11000,
        snapshot(30000, 1000000, 1000),
        snapshot(30000 + duration, 1000000 + sent, 1600, dropped,
                 active=active),
        reconnect,
    )


def cohort(n=24, *, dropped=0):
    runs, frames, network = [], [], []
    for number in range(n):
        pair = f"p{number:02d}"
        for variant in ("baseline", "candidate"):
            runs.append(run(pair, variant))
            frames.append(frame(pair, variant))
            network.append(transport(pair, variant,
                                     dropped=dropped if variant == "candidate" else 0))
    return runs, frames, network


def check(runs, frames, network, **kwargs):
    return compare_realtime_obs_transport(runs, frames, network, **kwargs)


def test_healthy_network_and_faster_speech_only_allow_supervised_pilot():
    runs, frames, network = cohort()
    result = check(runs, frames, network)
    assert result.verdict == "eligible_for_manual_pilot"
    assert result.frame_and_game_verdict == "eligible_for_manual_pilot"
    assert result.matched_windows == 24
    assert result.missing_windows == 0
    assert result.candidate_network_skipped_pct == 0
    assert "network packet loss" in result.note
    assert "p00" not in str(result)
    assert check(list(reversed(runs)), list(reversed(frames)),
                 list(reversed(network))) == result


def test_candidate_transport_stalls_or_reconnects_reject_faster_model():
    runs, frames, network = cohort()
    network[-1] = replace(network[-1], reconnect_observed=True)
    assert check(runs, frames, network).verdict == "regressed"
    assert check(runs, frames, network).candidate_disrupted_windows == 1
    network[-1] = replace(network[-1], reconnect_observed=False,
                          after=replace(network[-1].after, reconnecting=True))
    assert check(runs, frames, network).verdict == "regressed"
    network[-1] = replace(network[-1],
                          after=replace(network[-1].after, reconnecting=False,
                                        active=False))
    assert check(runs, frames, network).verdict == "regressed"


def test_network_frames_reject_config_despite_healthy_obs_rendering():
    runs, frames, network = cohort(dropped=7)
    report = check(runs, frames, network)
    assert report.frame_and_game_verdict == "eligible_for_manual_pilot"
    assert report.candidate_network_skipped_pct > 0.5
    assert report.verdict == "regressed"


def test_single_bad_transport_window_cannot_hide_in_average():
    runs, frames, network = cohort()
    network[-1] = transport("p23", "candidate", dropped=9)
    assert check(runs, frames, network).verdict == "regressed"
    assert check(runs, frames, network).worst_candidate_network_skipped_pct > 1


def test_persistent_small_drift_and_manually_tunable_limits():
    runs, frames, network = cohort(dropped=2)
    result = check(runs, frames, network)
    assert result.candidate_network_skipped_pct < 0.5
    assert result.network_skip_increase_pp > 0.2
    assert result.verdict == "regressed"
    assert check(runs, frames, network, max_increase_pp=0.5).verdict == (
        "eligible_for_manual_pilot"
    )


def test_baseline_disconnect_is_not_falsely_a_candidate_regression():
    runs, frames, network = cohort()
    network[0] = replace(network[0], reconnect_observed=True)
    assert check(runs, frames, network).verdict == "inconclusive"
    network[0] = replace(network[0], reconnect_observed=False,
                         after=replace(network[0].after, bytes_sent=1000000))
    assert check(runs, frames, network).verdict == "inconclusive"


def test_zero_bytes_and_partial_stream_duration_fail_even_with_valid_frames():
    runs, frames, network = cohort()
    network[-1] = replace(network[-1], after=replace(
        network[-1].after, bytes_sent=network[-1].before.bytes_sent,
    ))
    assert check(runs, frames, network).verdict == "regressed"
    network[-1] = transport("p23", "candidate", duration=7000)
    assert check(runs, frames, network).verdict == "regressed"


def test_incomplete_evidence_is_never_accepted_and_gates_compose():
    runs, frames, network = cohort()
    assert check(runs, frames, network[:-1]).verdict == "inconclusive"
    assert check(runs, frames, network[:-1]).missing_windows == 1
    assert check([], [], []).verdict == "inconclusive"
    frames[-1] = frame("p23", "candidate", drops=7)
    assert check(runs, frames, network).verdict == "regressed"
    frames[-1] = frame("p23", "candidate")
    runs[-1] = replace(runs[-1], audio_finished=False)
    assert check(runs, frames, network).verdict == "regressed"


def test_no_pilot_without_sufficient_paired_trials():
    runs, frames, network = cohort(n=8)
    assert check(runs, frames, network).verdict == "inconclusive"


def test_observer_session_and_interval_must_match_exact_game():
    runs, frames, network = cohort()
    network[-1] = replace(network[-1], session_id="other")
    with pytest.raises(ValueError, match="session"):
        check(runs, frames, network)
    network[-1] = replace(network[-1], session_id="session_candidate",
                          start_ms=4000, end_ms=14000)
    with pytest.raises(ValueError, match="intervals"):
        check(runs, frames, network)
    network[-1] = replace(network[-1], start_ms=1000, end_ms=11000,
                          game_version="v9")
    with pytest.raises(ValueError, match="scopes"):
        check(runs, frames, network)


def test_unexpected_or_duplicate_rows_and_unfair_pairs_rejected():
    runs, frames, network = cohort()
    with pytest.raises(ValueError, match="duplicate"):
        check(runs, frames, network + [network[-1]])
    with pytest.raises(ValueError, match="precommitted"):
        check(runs, frames, network + [transport("alien", "candidate")])
    network[-1] = replace(network[-1], end_ms=7000)
    with pytest.raises(ValueError, match="intervals"):
        check(runs, frames, network)


@pytest.mark.parametrize("bad", [True, -1, float("nan"), float("inf"),
                                  1e100, 2.5, "100", None])
def test_malformed_network_counters_are_not_silently_zeroed(bad):
    with pytest.raises(ValueError):
        snapshot(1000, bad, 1000)
    with pytest.raises(ValueError):
        snapshot(1000, 1000, bad)


def test_bad_duration_counter_reset_and_skips_rejected():
    value = transport("p", "baseline")
    with pytest.raises(ValueError, match="reset"):
        replace(value, after=replace(value.after, duration_ms=100))
    with pytest.raises(ValueError, match="too few"):
        replace(value, after=replace(value.after, total_frames=1100))
    with pytest.raises(ValueError, match="exceed"):
        replace(value, after=replace(value.after, skipped_frames=650))
    with pytest.raises(ValueError, match="range"):
        replace(value, after=replace(value.after, congestion=-0.1))


def test_getstreamstatus_extracts_only_public_bounded_fields():
    raw = {
        "outputActive": True, "outputReconnecting": False,
        "outputDuration": 5000.0, "outputBytes": 90000,
        "outputSkippedFrames": 1, "outputTotalFrames": 500,
        "outputCongestion": 0.01,
        "outputTimecode": "00:00:05.000", "privateToken": "DO_NOT_STORE",
    }
    result = ObsStreamStatus.from_getstreamstatus(raw)
    assert result.total_frames == 500
    assert "DO_NOT_STORE" not in str(result)
    assert "outputTimecode" not in str(result)
    raw["outputCongestion"] = None
    with pytest.raises(ValueError, match="finite"):
        ObsStreamStatus.from_getstreamstatus(raw)
    del raw["outputTotalFrames"]
    with pytest.raises(ValueError, match="missing"):
        ObsStreamStatus.from_getstreamstatus(raw)


def test_jsonl_rejects_private_fields_and_does_not_retain_timecode(tmp_path):
    w = transport("p", "candidate")
    def raw(status):
        return {
            "outputActive": status.active,
            "outputReconnecting": status.reconnecting,
            "outputDuration": status.duration_ms,
            "outputBytes": status.bytes_sent,
            "outputSkippedFrames": status.skipped_frames,
            "outputTotalFrames": status.total_frames,
            "outputCongestion": status.congestion,
            "outputTimecode": "00:00:10",
        }
    row = asdict(w)
    row["before"] = raw(w.before)
    row["after"] = raw(w.after)
    path = tmp_path / "network.jsonl"
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    got = read_transport_jsonl(path)
    assert got == [w]
    assert "outputTimecode" not in str(got)
    row["private_chat"] = "REDACT_ME"
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="allowlisted"):
        read_transport_jsonl(path)
    path.write_text("x" * 2_000_001, encoding="utf-8")
    with pytest.raises(ValueError, match="2 MB"):
        read_transport_jsonl(path)


@pytest.mark.parametrize("bad", [True, "1.0", None, float("nan"), 1e100, -0.2])
def test_invalid_limits_fail_closed(bad):
    runs, frames, network = cohort()
    with pytest.raises(ValueError):
        check(runs, frames, network, max_skipped_pct=bad)


def test_transport_parser_requires_host_reconnect_attestation():
    w = transport("p", "candidate")
    args = asdict(w)
    args["reconnect_observed"] = 0
    args["before"] = w.before
    args["after"] = w.after
    with pytest.raises(ValueError, match="host boolean"):
        ObsTransportWindow(**args)
