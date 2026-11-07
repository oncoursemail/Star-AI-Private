"""Offline WASAPI-style process loopback: no data callback when voice is quiet.

These tests do not open audio devices or confer permission to stream.
"""

from __future__ import annotations

import math
import struct

import pytest

from star.stream_loopback_quiet_witness import IsolatedLoopbackQuietWitness


RATE = 24000


def audio(value: int, ms: int = 20) -> bytes:
    return struct.pack("<h", value) * (RATE * ms // 1000)


def setup_witness() -> IsolatedLoopbackQuietWitness:
    w = IsolatedLoopbackQuietWitness(sample_rate_hz=RATE, owner_approved=True)
    assert w.arm_reference(
        "turnA",
        route_generation=5,
        pcm16le=audio(1800),
        captured_at=9.95,
        observed_at=9.98,
        isolated_capture_running=True,
    )
    assert w.begin_stop("turnA", route_generation=5, stopped_at=10.0)
    return w


def poll(w: IsolatedLoopbackQuietWitness, t: float, seq: int, **changes: object) -> bool:
    fields = dict(
        route_generation=5,
        checked_at=t,
        poll_sequence=seq,
        packet_generation=100,
        isolated_capture_running=True,
        voice_process_identity_pinned=True,
        no_pending_capture_packet=True,
    )
    fields.update(changes)
    return w.observe_no_packet_poll("turnA", **fields)  # type: ignore[arg-type]


def ready(w: IsolatedLoopbackQuietWitness, at: float, **changes: object) -> bool:
    fields = dict(
        route_generation=5,
        now=at,
        capture_isolated_and_healthy=True,
        native_abort_confirmed=True,
        avatar_neutral_confirmed=True,
    )
    fields.update(changes)
    return w.ready("turnA", **fields)  # type: ignore[arg-type]


def test_process_loopback_silent_no_packets_can_complete_private_evidence() -> None:
    w = setup_witness()
    for seq, instant in enumerate([10.01, 10.06, 10.11, 10.16], 1):
        assert not poll(w, instant, seq)
    assert poll(w, 10.21, 5)
    assert ready(w, 10.215)
    assert w.metrics()["idle_checks"] == 5
    assert w.metrics()["observed_blocks"] == 0
    assert not ready(w, 10.245)  # last native poll already stale


def test_single_idle_report_does_not_certify_silence() -> None:
    w = setup_witness()
    assert not poll(w, 10.5, 1)
    assert not ready(w, 10.505)
    assert not poll(w, 10.55, 2)
    assert not ready(w, 10.555)


@pytest.mark.parametrize(
    "key",
    [
        "capture_isolated_and_healthy",
        "native_abort_confirmed",
        "avatar_neutral_confirmed",
    ],
)
def test_independent_output_proofs_remain_required(key: str) -> None:
    w = setup_witness()
    for seq, instant in enumerate([10.01, 10.06, 10.11, 10.16, 10.21], 1):
        poll(w, instant, seq)
    assert not ready(w, 10.215, **{key: False})
    assert ready(w, 10.215)


@pytest.mark.parametrize(
    "key,value",
    [
        ("isolated_capture_running", False),
        ("voice_process_identity_pinned", False),
        ("route_generation", 6),
        ("poll_sequence", -1),
        ("poll_sequence", True),
        ("packet_generation", -1),
        ("packet_generation", True),
        ("checked_at", math.nan),
        ("checked_at", math.inf),
        ("checked_at", True),
        ("checked_at", 9.999),
        ("no_pending_capture_packet", 1),
    ],
)
def test_invalid_native_poll_fails_closed(key: str, value: object) -> None:
    w = setup_witness()
    assert not poll(w, 10.01, 1, **{key: value})
    assert w.metrics()["faulted"]
    assert not poll(w, 10.06, 2)
    assert not ready(w, 10.25)


@pytest.mark.parametrize(
    "sequence,next_time",
    [
        (1, 10.06),  # duplicate poll sequence
        (0, 10.06),  # regression
        (2, 10.01),  # duplicate timestamp
        (2, 9.99),  # backwards before stop
    ],
)
def test_duplicate_or_backdated_poll_cannot_accumulate(
    sequence: int,
    next_time: float,
) -> None:
    w = setup_witness()
    assert not poll(w, 10.01, 1)
    assert not poll(w, next_time, sequence)
    assert w.metrics()["faulted"]


def test_packet_callback_generation_changes_restart_idle_window() -> None:
    w = setup_witness()
    for seq, instant in enumerate([10.01, 10.06, 10.11, 10.16], 1):
        assert not poll(w, instant, seq)
    assert not poll(w, 10.21, 5, packet_generation=101)
    assert not poll(w, 10.26, 6, packet_generation=101)
    assert not poll(w, 10.31, 7, packet_generation=101)
    assert not poll(w, 10.36, 8, packet_generation=101)
    assert poll(w, 10.41, 9, packet_generation=101)
    assert ready(w, 10.42)
    assert w.metrics()["idle_resets"] == 1


def test_pending_packet_interrupts_idle_evidence_even_with_same_generation() -> None:
    w = setup_witness()
    for seq, instant in enumerate([10.01, 10.06, 10.11, 10.16], 1):
        assert not poll(w, instant, seq)
    assert not poll(w, 10.21, 5, no_pending_capture_packet=False)
    assert not ready(w, 10.22)
    assert not poll(w, 10.26, 6)
    assert not poll(w, 10.31, 7)


def test_capture_poll_gap_breaks_continuous_idle_claim() -> None:
    w = setup_witness()
    assert not poll(w, 10.01, 1)
    assert not poll(w, 10.06, 2)
    assert not poll(w, 10.16, 3)  # >80ms without a native poll
    assert not poll(w, 10.21, 4)
    assert not poll(w, 10.26, 5)
    assert poll(w, 10.36, 6) is False  # gap again


def test_decreasing_callback_generation_is_fault() -> None:
    w = setup_witness()
    assert not poll(w, 10.01, 1, packet_generation=100)
    assert not poll(w, 10.06, 2, packet_generation=99)
    assert w.metrics()["faulted"]


def test_actual_pcm_callback_invalidates_idle_no_packet_evidence() -> None:
    w = setup_witness()
    for seq, instant in enumerate([10.01, 10.06, 10.11, 10.16], 1):
        assert not poll(w, instant, seq)
    assert not w.ingest(
        "turnA",
        route_generation=5,
        pcm16le=audio(2500),
        captured_at=10.16,
        observed_at=10.185,
        isolated_capture_running=True,
    )
    assert not poll(w, 10.21, 5, packet_generation=101)
    assert not ready(w, 10.22)


def test_reused_epoch_and_retirement_cannot_resume_speech() -> None:
    w = setup_witness()
    for seq, instant in enumerate([10.01, 10.06, 10.11, 10.16, 10.21], 1):
        poll(w, instant, seq)
    assert ready(w, 10.22)
    w.retire("turnA")
    assert not poll(w, 10.26, 6)
    assert not ready(w, 10.27)
    assert not w.arm_reference(
        "turnA",
        route_generation=5,
        pcm16le=audio(1800),
        captured_at=10.27,
        observed_at=10.30,
        isolated_capture_running=True,
    )


def test_metrics_contain_no_capture_identity_or_audio_samples() -> None:
    w = setup_witness()
    poll(w, 10.01, 1)
    result = str(w.metrics())
    for sensitive in ("turnA", "1800", "route", "process", "packet_generation"):
        assert sensitive not in result
