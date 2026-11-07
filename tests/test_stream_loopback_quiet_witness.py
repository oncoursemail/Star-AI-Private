"""Deterministic loopback witness tests; no microphone, WASAPI or game access."""

from __future__ import annotations

import math
import struct

import pytest

from star.stream_loopback_quiet_witness import IsolatedLoopbackQuietWitness

RATE = 24000


def pcm(value: int, milliseconds: int = 60) -> bytes:
    return struct.pack("<h", value) * (RATE * milliseconds // 1000)


def witness() -> IsolatedLoopbackQuietWitness:
    return IsolatedLoopbackQuietWitness(sample_rate_hz=RATE, owner_approved=True)


def arm(w: IsolatedLoopbackQuietWitness, epoch: str = "first") -> bool:
    return w.arm_reference(
        epoch,
        route_generation=7,
        pcm16le=pcm(1500, 20),
        captured_at=9.95,
        observed_at=9.98,
        isolated_capture_running=True,
    )


def stop(w: IsolatedLoopbackQuietWitness, epoch: str = "first") -> bool:
    return w.begin_stop(epoch, route_generation=7, stopped_at=10.0)


def feed(
    w: IsolatedLoopbackQuietWitness,
    start: float,
    *,
    peak: int = 0,
    epoch: str = "first",
    route: int = 7,
    duration_ms: int = 60,
    healthy: bool = True,
    observed_at: float | None = None,
) -> bool:
    end = start + duration_ms / 1000
    return w.ingest(
        epoch,
        route_generation=route,
        pcm16le=pcm(peak, duration_ms),
        captured_at=start,
        observed_at=end + 0.01 if observed_at is None else observed_at,
        isolated_capture_running=healthy,
    )


def ready(w: IsolatedLoopbackQuietWitness, **kwargs: object) -> bool:
    args: dict[str, object] = {
        "route_generation": 7,
        "now": 10.2,
        "capture_isolated_and_healthy": True,
        "native_abort_confirmed": True,
        "avatar_neutral_confirmed": True,
    }
    args.update(kwargs)
    return w.ready("first", **args)  # type: ignore[arg-type]


def test_valid_reference_then_180ms_loopback_window() -> None:
    w = witness()
    assert arm(w) and stop(w)
    assert not feed(w, 10.0)
    assert not feed(w, 10.06)
    assert feed(w, 10.12)
    assert ready(w)
    assert w.metrics()["observed_blocks"] == 3


@pytest.mark.parametrize("gate", ["capture_isolated_and_healthy", "native_abort_confirmed", "avatar_neutral_confirmed"])
def test_all_independent_host_conditions_required(gate: str) -> None:
    w = witness()
    assert arm(w) and stop(w)
    for start in (10.0, 10.06, 10.12):
        feed(w, start)
    assert not ready(w, **{gate: False})
    assert ready(w)


@pytest.mark.parametrize("now", [10.34, 9.0, -1, math.nan, math.inf, True, 10**1000])
def test_missing_or_stale_observations_fail(now: object) -> None:
    w = witness()
    assert arm(w) and stop(w)
    for start in (10.0, 10.06, 10.12):
        feed(w, start)
    assert not ready(w, now=now)


@pytest.mark.parametrize("value", [250, 32767, -32768, -100])
def test_nonquiet_capture_resets_window(value: int) -> None:
    w = witness()
    assert arm(w) and stop(w)
    assert not feed(w, 10.0)
    assert not feed(w, 10.06, peak=value)
    assert not feed(w, 10.12)
    assert not feed(w, 10.18)
    assert feed(w, 10.24)
    assert ready(w, now=10.31)


def test_missing_capture_gap_does_not_accumulate_false_quiet() -> None:
    w = witness()
    assert arm(w) and stop(w)
    assert not feed(w, 10.0)
    assert not feed(w, 10.1)  # lost 40 ms; window restarts
    assert not feed(w, 10.16)
    assert feed(w, 10.22)
    assert ready(w, now=10.29)


@pytest.mark.parametrize("route", [6, 8])
def test_capture_route_swap_latches_failure(route: int) -> None:
    w = witness()
    assert arm(w) and stop(w)
    assert not feed(w, 10.0, route=route)
    assert w.metrics()["faulted"] is True
    assert not feed(w, 10.06)
    assert not ready(w)


def test_capture_health_loss_latches_failure() -> None:
    w = witness()
    assert arm(w) and stop(w)
    assert not feed(w, 10.0, healthy=False)
    assert w.metrics()["faulted"] is True


def test_repeated_or_older_capture_block_latches_failure() -> None:
    w = witness()
    assert arm(w) and stop(w)
    assert not feed(w, 10.0)
    assert not feed(w, 10.0)
    assert w.metrics()["faulted"] is True


@pytest.mark.parametrize("start", [9.95, 9.99])
def test_capture_overlapping_stop_rejected(start: float) -> None:
    w = witness()
    assert arm(w) and stop(w)
    assert not feed(w, start)
    assert w.metrics()["faulted"] is True


def test_reference_must_be_audibly_nonzero_and_isolated() -> None:
    w = witness()
    assert not w.arm_reference(
        "first",
        route_generation=7,
        pcm16le=pcm(0, 20),
        captured_at=9.95,
        observed_at=9.98,
        isolated_capture_running=True,
    )
    assert not w.arm_reference(
        "first",
        route_generation=7,
        pcm16le=pcm(2000, 20),
        captured_at=9.95,
        observed_at=9.98,
        isolated_capture_running=False,
    )
    assert arm(w)


@pytest.mark.parametrize("epoch", ["", "bad space", "x" * 65, "../path", "\n"])
def test_unsafe_epoch_names_not_armed(epoch: str) -> None:
    w = witness()
    assert not w.arm_reference(
        epoch,
        route_generation=7,
        pcm16le=pcm(1500, 20),
        captured_at=9.95,
        observed_at=9.98,
        isolated_capture_running=True,
    )


@pytest.mark.parametrize("invalid", [b"", b"\x00", b"\x00" * (RATE // 2 + 4), "abc", None])
def test_invalid_pcm_blocks_fail_closed(invalid: object) -> None:
    w = witness()
    assert arm(w) and stop(w)
    assert not w.ingest(
        "first",
        route_generation=7,
        pcm16le=invalid,  # type: ignore[arg-type]
        captured_at=10.0,
        observed_at=10.01,
        isolated_capture_running=True,
    )
    assert w.metrics()["faulted"] is True


def test_bad_clock_and_reference_staleness() -> None:
    w = witness()
    assert arm(w)
    assert not w.begin_stop("first", route_generation=7, stopped_at=12.0)
    assert not w.begin_stop("first", route_generation=7, stopped_at=float("nan"))
    assert stop(w)
    assert not feed(w, 10.0, observed_at=10.9)
    assert w.metrics()["faulted"] is True


def test_stale_epoch_cannot_contaminate_new_turn() -> None:
    w = witness()
    assert arm(w) and stop(w)
    w.retire("first")
    assert not feed(w, 10.0)
    assert not arm(w)  # never reuse a retired identity
    assert arm(w, "second") and stop(w, "second")
    for start in (10.0, 10.06, 10.12):
        assert not feed(w, start, epoch="first")
    for start in (10.0, 10.06, 10.12):
        feed(w, start, epoch="second")
    assert not ready(w)
    assert w.ready(
        "second",
        route_generation=7,
        now=10.2,
        capture_isolated_and_healthy=True,
        native_abort_confirmed=True,
        avatar_neutral_confirmed=True,
    )


def test_metrics_never_include_pcm_or_route() -> None:
    w = witness()
    assert arm(w)
    report = str(w.metrics())
    assert "first" not in report and "1500" not in report and "route" not in report


@pytest.mark.parametrize("rate", [0, 7999, 96001, True, 24000.0])
def test_sample_rate_is_strict(rate: object) -> None:
    with pytest.raises(ValueError):
        IsolatedLoopbackQuietWitness(sample_rate_hz=rate, owner_approved=True)  # type: ignore[arg-type]


def test_owner_opt_in_required() -> None:
    with pytest.raises(PermissionError):
        IsolatedLoopbackQuietWitness(sample_rate_hz=RATE)


def test_simulated_native_sink_handoff_only_after_independent_capture() -> None:
    """The new witness can guard the existing last-mile native output bridge."""
    from star.stream_epoch_pcm_sink import LocalEpochPCMSink

    class FakeNative:
        sample_rate = RATE
        stopped = False

        def play(self, pcm: bytes, sample_rate: int) -> None:
            assert not self.stopped and sample_rate == RATE

        def stop(self) -> None:
            self.stopped = True

        def pending_seconds(self) -> float:
            return 0.0

    device = FakeNative()
    sink = LocalEpochPCMSink(device)
    sink.enable(owner_approved=True)
    assert sink.bind("first", independently_quiet=True).status == "ready"
    assert sink.request_stop("first")
    assert sink.observe_quiet("first").status == "held"

    probe = witness()
    assert arm(probe) and stop(probe)
    for offset in (10.0, 10.06, 10.12):
        feed(probe, offset)

    # Queue drain alone is not a quiet witness; the new gate demands
    # separate native-stop and avatar-neutral observations.
    assert not ready(probe, avatar_neutral_confirmed=False)
    assert (
        sink.observe_quiet(
            "first",
            native_output_flushed=ready(probe),
        ).status
        == "quiet"
    )
    assert sink.bind("first", independently_quiet=True).status == "held"
    assert sink.bind("second", independently_quiet=ready(probe)).status == "ready"