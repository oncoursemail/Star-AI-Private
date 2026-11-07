"""Privacy-minimizing, local-only latency measurements for PRIVATE game rehearsal.

The input timestamps MUST originate from one host's monotonic clock. They are
caller-provided observations, not independently authenticated evidence.
No gameplay frames, player names, prompts, audio, actions or raw timestamp
origins are emitted in a report. This module cannot control a game or OBS.

The resulting schedule is a conservative input to the synthetic signed maze
lab; it is NOT a benchmark of a neural model or a real game.
"""
from __future__ import annotations

from dataclasses import dataclass

_MAX_NS = (1 << 63) - 1
_MAX_DURATION_NS = 30_000_000_000  # Reject stuck/mixed-clock captures.


def _rank95(samples: tuple[int, ...]) -> int:
    return sorted(samples)[(95 * len(samples) + 99) // 100 - 1]


@dataclass(frozen=True)
class LocalFrameTiming:
    """One frame's ordered host events, all from the SAME monotonic_ns clock.

    decision_ready_ns: the proposed action exists, but has not passed the gate.
    action_submit_ns: the approved private action is passed to the host.
    action_ack_ns: the host acknowledges (not proof the game moved).
    """

    sequence: int
    capture_ns: int
    decision_ready_ns: int
    action_submit_ns: int
    action_ack_ns: int

    def __post_init__(self) -> None:
        if type(self.sequence) is not int or not 1 <= self.sequence <= 256:
            raise ValueError("sequence must be an integer in 1..256")
        stamps = (
            self.capture_ns, self.decision_ready_ns,
            self.action_submit_ns, self.action_ack_ns,
        )
        if any(type(ts) is not int or not 0 <= ts <= _MAX_NS for ts in stamps):
            raise ValueError("all stamps must be nonnegative int64 monotonic_ns")
        if tuple(sorted(stamps)) != stamps:
            raise ValueError("capture/decision/submit/ack order is invalid")
        if self.action_ack_ns - self.capture_ns > _MAX_DURATION_NS:
            raise ValueError("a frame cannot exceed 30 seconds")


@dataclass(frozen=True)
class PrivateLatencyReplay:
    """Duration-only diagnostic; intentionally excludes raw timestamps."""

    decision_delay_schedule: tuple[int, ...]
    tick_ns: int
    capture_count: int
    inference_p95_ns: int
    gate_p95_ns: int
    action_ack_p95_ns: int
    end_to_end_p95_ns: int
    end_to_end_max_ns: int
    end_to_end_total_ns: int

    def private_report(self) -> dict[str, int | bool]:
        """Only durations and counts; never raw monotonic origins or identities."""
        return {
            "schema_version": 1,
            "capture_count": self.capture_count,
            "tick_ns": self.tick_ns,
            "inference_p95_ns": self.inference_p95_ns,
            "gate_p95_ns": self.gate_p95_ns,
            "action_ack_p95_ns": self.action_ack_p95_ns,
            "end_to_end_p95_ns": self.end_to_end_p95_ns,
            "end_to_end_max_ns": self.end_to_end_max_ns,
            "end_to_end_total_ns": self.end_to_end_total_ns,
            "independent_gameplay_proof": False,
            "timing_attested": False,
        }


def prepare_private_latency_replay(
    captures: tuple[LocalFrameTiming, ...], *,
    owner_approved: bool = False,
    tick_ns: int = 100_000_000,
) -> PrivateLatencyReplay:
    """Convert real host clock intervals to conservative synthetic *tick counts*.

    The caller MUST explicitly calibrate a synthetic world tick to the real
    environment before interpreting game outcomes. The synthetic lab only
    accepts delays 0..24 ticks. Slow captures are REJECTED, never truncated
    to 24 ticks or silently dropped. Frame sequence and ACKs must be ordered;
    overlapping captures are allowed to support asynchronous perception.
    """
    if owner_approved is not True:
        raise PermissionError("owner approval required for private latency replay")
    if type(tick_ns) is not int or not 10_000_000 <= tick_ns <= 1_000_000_000:
        raise ValueError("tick_ns must be a calibrated integer 10ms..1s")
    if type(captures) is not tuple or not 1 <= len(captures) <= 256:
        raise ValueError("captures must be a tuple of 1..256 frames")
    if any(type(c) is not LocalFrameTiming for c in captures):
        raise TypeError("captures must contain LocalFrameTiming only")
    for index, capture in enumerate(captures):
        if capture.sequence != index + 1:
            raise ValueError("frames must be contiguous starting at sequence 1")
        if index:
            prev = captures[index - 1]
            if capture.capture_ns <= prev.capture_ns:
                raise ValueError("captures must strictly increase")
            if capture.action_ack_ns < prev.action_ack_ns:
                raise ValueError("out-of-order acknowledgments are not supported")

    inference = tuple(c.decision_ready_ns - c.capture_ns for c in captures)
    gate = tuple(c.action_submit_ns - c.decision_ready_ns for c in captures)
    ack = tuple(c.action_ack_ns - c.action_submit_ns for c in captures)
    total = tuple(c.action_ack_ns - c.capture_ns for c in captures)
    # Ceil: no optimistic truncation of partially elapsed simulation ticks.
    delay = tuple((ns + tick_ns - 1) // tick_ns for ns in total)
    if any(ticks > 24 for ticks in delay):
        raise ValueError("latency exceeds 24 synthetic ticks; recalibrate or fail")
    return PrivateLatencyReplay(
        decision_delay_schedule=delay, tick_ns=tick_ns,
        capture_count=len(captures), inference_p95_ns=_rank95(inference),
        gate_p95_ns=_rank95(gate), action_ack_p95_ns=_rank95(ack),
        end_to_end_p95_ns=_rank95(total), end_to_end_max_ns=max(total),
        end_to_end_total_ns=sum(total),
    )


__all__ = [
    "LocalFrameTiming", "PrivateLatencyReplay", "prepare_private_latency_replay",
]
