"""Offline no-audio verification of the native voice JSONL boundary."""

import json

import pytest

from star.process_loopback_activity import ProcessLoopbackActivityVerifier


def row(
    state="capture_started",
    *,
    elapsed_ms=0,
    callbacks=0,
    frames=0,
    window_callbacks=0,
    window_frames=0,
    peak=None,
    rms=None,
    max_peak=0,
    last_age=-1,
    bad=0,
    **extra,
):
    record = dict(
        schema="star.process_loopback.diagnostic.v1",
        state=state,
        elapsed_ms=elapsed_ms,
        callback_generation=callbacks,
        sample_frames=frames,
        bad_packets=bad,
        max_peak_milli=max_peak,
        last_callback_age_ms=last_age,
        activity_window_ms=50,
        activity_callbacks=window_callbacks,
        activity_sample_frames=window_frames,
        activity_peak_milli=peak,
        activity_rms_milli=rms,
        activity_is_audio_observation_only=True,
        verified_silence=False,
        gameplay_authorized=False,
        broadcast_authorized=False,
    )
    record.update(extra)
    return record


def line(**kwargs):
    return json.dumps(row(**kwargs))


def started():
    v = ProcessLoopbackActivityVerifier(owner_approved=True)
    v.feed_line(line())
    return v


def nonempty(*, state="observing_no_silence_claim", elapsed_ms=50):
    return line(
        state=state,
        elapsed_ms=elapsed_ms,
        callbacks=1,
        frames=2,
        window_callbacks=1,
        window_frames=2,
        peak=750,
        rms=468,
        max_peak=750,
        last_age=1,
    )


def test_default_off_and_integer_parameter_validation():
    with pytest.raises(PermissionError):
        ProcessLoopbackActivityVerifier()
    for x in (True, 0, 1001, 2.0, "100"):
        with pytest.raises(ValueError):
            ProcessLoopbackActivityVerifier(owner_approved=True, possible_audio_peak_milli=x)


def test_valid_observed_audio_missing_pcm_and_completion_cannot_authorize():
    v = started()
    one = v.feed_line(nonempty())
    assert one.possible_audio_activity is True
    assert not one.verified_silence
    unknown = v.feed_line(
        line(
            state="observing_no_silence_claim",
            elapsed_ms=100,
            callbacks=1,
            frames=2,
            window_callbacks=0,
            window_frames=0,
            max_peak=750,
            last_age=51,
        )
    )
    assert unknown.possible_audio_activity is None
    assert unknown.activity_peak_milli is None
    completed = v.feed_line(
        line(
            state="capture_complete_no_silence_claim", elapsed_ms=150, callbacks=1, frames=2, max_peak=750, last_age=101
        )
    )
    assert completed.possible_audio_activity is None
    report = v.summary()
    assert report.state == "completed"
    assert report.windows == 3
    assert report.pcm_windows == 1
    assert report.missing_pcm_windows == 2
    assert report.audio_activity_hint_windows == 1
    assert report.callbacks == 1
    assert report.sample_frames == 2
    assert report.maximum_peak_milli == 750
    assert not report.verified_silence
    assert not report.authorizes_gameplay
    assert not report.authorizes_broadcast


def test_first_window_may_contain_pcm_before_capture_started_emit():
    v = ProcessLoopbackActivityVerifier(owner_approved=True)
    first = v.feed_line(
        line(callbacks=1, frames=2, window_callbacks=1, window_frames=2, peak=100, rms=80, max_peak=100, last_age=0)
    )
    assert first.possible_audio_activity is False
    final = v.feed_line(
        line(
            state="capture_complete_no_silence_claim",
            elapsed_ms=350,
            callbacks=1,
            frames=2,
            max_peak=100,
            last_age=350,
        )
    )
    assert final.possible_audio_activity is None
    assert v.summary().state == "completed"


@pytest.mark.parametrize(
    "badrow",
    [
        dict(state="capture_started", elapsed_ms=1),  # native starts at zero
        dict(state="capture_complete_no_silence_claim"),
        dict(state="hijack"),
        dict(schema="malicious"),
        dict(verified_silence=True),
        dict(broadcast_authorized=True),
        dict(gameplay_authorized=True),
        dict(activity_is_audio_observation_only=False),
        dict(sample_frames=1),  # frames without any callback
        dict(callback_generation=True),
        dict(activity_callbacks=True),
        dict(activity_window_ms=-1),
        dict(activity_peak_milli=0),
        dict(activity_rms_milli=0),
        dict(last_callback_age_ms=1),
        dict(bad_packets=1),
    ],
)
def test_invalid_initial_line_poisoned(badrow):
    v = ProcessLoopbackActivityVerifier(owner_approved=True)
    record = row()
    record.update(badrow)
    with pytest.raises(ValueError):
        v.feed_line(json.dumps(record))
    assert v.summary().state == "invalid"
    with pytest.raises(ValueError):
        v.feed_line(line())


@pytest.mark.parametrize(
    "badline",
    [
        "",
        "[]",
        "NaN",
        "{}",
        '{"a":1,"a":2}',
        "x" * 4097,
        '{"schema":null}',
        "true",
    ],
)
def test_malformed_initial_line_poisoned(badline):
    v = ProcessLoopbackActivityVerifier(owner_approved=True)
    with pytest.raises(ValueError):
        v.feed_line(badline)
    assert v.summary().state == "invalid"


def test_duplicate_real_key_and_extra_field_rejected():
    v = ProcessLoopbackActivityVerifier(owner_approved=True)
    duplicate = line()[:-1] + ',"state":"capture_started"}'
    with pytest.raises(ValueError):
        v.feed_line(duplicate)
    v = ProcessLoopbackActivityVerifier(owner_approved=True)
    with pytest.raises(ValueError):
        v.feed_line(line(unexpected="transcript data"))


@pytest.mark.parametrize(
    "badrow",
    [
        dict(
            elapsed_ms=50,
            callback_generation=1,
            sample_frames=2,
            activity_callbacks=0,
            activity_sample_frames=0,
            activity_peak_milli=750,
            activity_rms_milli=468,
            max_peak_milli=750,
            last_callback_age_ms=0,
        ),  # mismatched delta
        dict(
            elapsed_ms=50,
            callback_generation=1,
            sample_frames=2,
            activity_callbacks=1,
            activity_sample_frames=2,
            activity_peak_milli=None,
            activity_rms_milli=None,
            max_peak_milli=750,
            last_callback_age_ms=0,
        ),  # missing PCM stats
        dict(
            elapsed_ms=50,
            callback_generation=1,
            sample_frames=2,
            activity_callbacks=1,
            activity_sample_frames=2,
            activity_peak_milli=800,
            activity_rms_milli=300,
            max_peak_milli=100,
            last_callback_age_ms=0,
        ),  # peak exceeds max
        dict(
            elapsed_ms=50,
            callback_generation=1,
            sample_frames=2,
            activity_callbacks=1,
            activity_sample_frames=2,
            activity_peak_milli=300,
            activity_rms_milli=400,
            max_peak_milli=300,
            last_callback_age_ms=0,
        ),  # rms exceeds peak
        dict(
            elapsed_ms=50,
            callback_generation=1,
            sample_frames=2,
            activity_callbacks=1,
            activity_sample_frames=2,
            activity_peak_milli=750,
            activity_rms_milli=468,
            max_peak_milli=750,
            last_callback_age_ms=-1,
        ),  # impossible last age
        dict(
            elapsed_ms=50,
            callback_generation=1,
            sample_frames=2,
            activity_callbacks=1,
            activity_sample_frames=2,
            activity_peak_milli=750,
            activity_rms_milli=468,
            max_peak_milli=750,
            last_callback_age_ms=0,
            bad_packets=1,
        ),
    ],
)
def test_mismatched_counters_or_packet_errors_invalidate(badrow):
    v = started()
    record = row(state="observing_no_silence_claim")
    record.update(badrow)
    with pytest.raises(ValueError):
        v.feed_line(json.dumps(record))
    assert v.summary().state == "invalid"


def test_progress_requires_strictly_advancing_timestamp_and_no_restart():
    v = started()
    v.feed_line(nonempty())
    with pytest.raises(ValueError):
        v.feed_line(nonempty(elapsed_ms=50))
    assert v.summary().state == "invalid"
    v = started()
    with pytest.raises(ValueError):
        v.feed_line(line(state="capture_started", elapsed_ms=0))


def test_packets_do_not_reuse_previous_window_amplitude_as_new_evidence():
    v = started()
    v.feed_line(nonempty())
    with pytest.raises(ValueError):
        v.feed_line(
            line(
                state="observing_no_silence_claim",
                elapsed_ms=100,
                callbacks=1,
                frames=2,
                max_peak=750,
                last_age=51,
                peak=750,
            )
        )
    assert v.summary().state == "invalid"


def test_no_input_accepted_after_terminal_state():
    v = started()
    v.feed_line(line(state="capture_complete_no_silence_claim", elapsed_ms=300))
    with pytest.raises(ValueError):
        v.feed_line(line(state="capture_started"))


def test_capture_invalid_poisoned_not_a_valid_completion():
    v = started()
    with pytest.raises(ValueError):
        v.feed_line(line(state="capture_invalid", elapsed_ms=300))
    assert v.summary().state == "invalid"


def test_line_bound_prevents_unbounded_memory_growth():
    v = started()
    for i in range(1, 512):
        v.feed_line(line(state="observing_no_silence_claim", elapsed_ms=i))
    with pytest.raises(ValueError):
        v.feed_line(line(state="observing_no_silence_claim", elapsed_ms=512))
    assert v.summary().state == "invalid"


def test_truncated_stream_is_collecting_not_completed():
    v = started()
    v.feed_line(nonempty())
    report = v.summary()
    assert report.state == "collecting"
    assert report.authorizes_broadcast is False


def test_healthy_empty_pcm_window_is_unknown_not_silence():
    v = started()
    reading = v.feed_line(line(state="observing_no_silence_claim", elapsed_ms=50))
    assert reading.possible_audio_activity is None
    assert reading.verified_silence is False
    assert v.summary().missing_pcm_windows == 1
