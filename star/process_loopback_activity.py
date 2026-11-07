"""Fail-closed local parser for Star's isolated Windows voice activity diagnostic.

This converts untrusted JSONL text emitted by the *separately launched* native
diagnostic into bounded, session-scoped, non-authorizing observations. It
never starts capture, plays audio, controls a game, accesses OBS, publishes,
or stores PCM/transcripts/process identifiers.

An authenticated, owner-controlled Windows host must independently pin the
diagnostic binary, target voice process, capture route, and private recording.
Even a completed report is NOT evidence of physical silence, speech identity,
a successful interruption, or permission to broadcast.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from threading import RLock
from typing import Any

_SCHEMA = "star.process_loopback.diagnostic.v1"
_FIELDS = frozenset(
    {
        "schema",
        "state",
        "elapsed_ms",
        "callback_generation",
        "sample_frames",
        "bad_packets",
        "max_peak_milli",
        "last_callback_age_ms",
        "activity_window_ms",
        "activity_callbacks",
        "activity_sample_frames",
        "activity_peak_milli",
        "activity_rms_milli",
        "activity_is_audio_observation_only",
        "verified_silence",
        "gameplay_authorized",
        "broadcast_authorized",
    }
)
_PROGRESS = "observing_no_silence_claim"
_END = frozenset({"capture_invalid", "capture_complete_no_silence_claim"})
_MAX_LINES = 512
_MAX_FRAMES = 2**48


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("repeated diagnostic field")
        result[name] = value
    return result


def _int(payload: dict[str, Any], name: str, low: int, high: int) -> int:
    value = payload[name]
    if type(value) is not int or not low <= value <= high:
        raise ValueError("invalid diagnostic counter: " + name)
    return value


@dataclass(frozen=True)
class ActivityReading:
    state: str
    elapsed_ms: int
    activity_callbacks: int
    activity_sample_frames: int
    activity_peak_milli: int | None
    activity_rms_milli: int | None
    # This is only a PCM amplitude hint, NOT a speech/VAD classification.
    possible_audio_activity: bool | None
    verified_silence: bool = False
    authorizes_gameplay: bool = False
    authorizes_broadcast: bool = False


@dataclass(frozen=True)
class ActivityDiagnosticSummary:
    state: str  # not_started | collecting | completed | invalid
    windows: int
    pcm_windows: int
    missing_pcm_windows: int
    audio_activity_hint_windows: int
    callbacks: int
    sample_frames: int
    maximum_peak_milli: int
    # A host may review this *private diagnostic*, not promote to a witness.
    verified_silence: bool = False
    authorizes_gameplay: bool = False
    authorizes_broadcast: bool = False


class ProcessLoopbackActivityVerifier:
    """One-shot parser; no public-audio or gameplay authority.

    Only feed JSONL from a trusted, owner-started, PINNED instance of the
    self-contained diagnostic. Do not accept text supplied by a viewer, model,
    stream chat, or an unauthenticated tool. The source process's identity is
    not proved by this class.

    Window totals must match cumulative deltas at each Emit() snapshot.
    This relies on the native producer atomically snapshotting its counters;
    it catches missing, duplicated, reordered and internally contradictory
    diagnostic lines before their numbers can enter a private scorecard.
    """

    def __init__(self, *, owner_approved: bool = False, possible_audio_peak_milli: int = 140) -> None:
        if owner_approved is not True:
            raise PermissionError("local owner consent required")
        if type(possible_audio_peak_milli) is not int or not 1 <= possible_audio_peak_milli <= 1000:
            raise ValueError("invalid advisory audio activity threshold")
        self._threshold = possible_audio_peak_milli
        self._lock = RLock()
        self._state = "not_started"
        self._lines = 0
        self._last_elapsed: int | None = None
        self._callbacks = 0
        self._frames = 0
        self._max_peak = 0
        self._windows = 0
        self._pcm_windows = 0
        self._unknown_windows = 0
        self._activity_windows = 0

    def _check(self, row: dict[str, Any]) -> ActivityReading:
        if row.keys() != _FIELDS:
            raise ValueError("unexpected diagnostic shape")
        state = row["state"]
        if type(state) is not str or state not in (
            "capture_started",
            _PROGRESS,
            *_END,
        ):
            raise ValueError("unsupported diagnostic state")
        if row["schema"] != _SCHEMA or type(row["schema"]) is not str:
            raise ValueError("unexpected diagnostic version")
        if (
            row["activity_is_audio_observation_only"] is not True
            or row["verified_silence"] is not False
            or row["gameplay_authorized"] is not False
            or row["broadcast_authorized"] is not False
        ):
            raise ValueError("diagnostic tried to assert authority")
        elapsed = _int(row, "elapsed_ms", 0, 10_000)
        callbacks = _int(row, "callback_generation", 0, _MAX_FRAMES)
        frames = _int(row, "sample_frames", 0, _MAX_FRAMES)
        bad_packets = _int(row, "bad_packets", 0, _MAX_FRAMES)
        maximum = _int(row, "max_peak_milli", 0, 1000)
        age = _int(row, "last_callback_age_ms", -1, 10_000)
        _int(row, "activity_window_ms", 0, 10_000)
        window_callbacks = _int(row, "activity_callbacks", 0, _MAX_FRAMES)
        window_frames = _int(row, "activity_sample_frames", 0, _MAX_FRAMES)
        peak = row["activity_peak_milli"]
        rms = row["activity_rms_milli"]
        if state == "capture_started":
            if self._state != "not_started" or elapsed != 0:
                raise ValueError("capture must start once from zero elapsed")
        elif self._state != "collecting" or (self._last_elapsed is not None and elapsed <= self._last_elapsed):
            raise ValueError("out-of-order or restarted native observation")
        if (
            callbacks < self._callbacks
            or frames < self._frames
            or maximum < self._max_peak
            or callbacks - self._callbacks != window_callbacks
            or frames - self._frames != window_frames
        ):
            raise ValueError("non-atomic, repeated or missing activity window")
        if window_callbacks == 0:
            if window_frames != 0 or peak is not None or rms is not None:
                raise ValueError("fabricated PCM during zero-callback interval")
        else:
            if (
                window_frames < window_callbacks
                or age == -1
                or type(peak) is not int
                or not 0 <= peak <= 1000
                or type(rms) is not int
                or not 0 <= rms <= peak
                or maximum < peak
            ):
                raise ValueError("invalid nonempty PCM activity window")
        if callbacks == 0 and (frames != 0 or age != -1 or maximum != 0):
            raise ValueError("audio reference reported without callbacks")
        # A native audio callback can arrive during capture teardown.
        # Any packet error or explicit invalid result poisons the whole run.
        if bad_packets != 0 or state == "capture_invalid":
            raise ValueError("native capture reported invalid evidence")
        if state == "capture_started":
            self._state = "collecting"
        elif state == "capture_complete_no_silence_claim":
            self._state = "completed"
        if state != "capture_started":
            self._windows += 1
            if window_callbacks:
                self._pcm_windows += 1
                if peak >= self._threshold:
                    self._activity_windows += 1
            else:
                self._unknown_windows += 1
        self._last_elapsed = elapsed
        self._callbacks = callbacks
        self._frames = frames
        self._max_peak = maximum
        return ActivityReading(
            state=state,
            elapsed_ms=elapsed,
            activity_callbacks=window_callbacks,
            activity_sample_frames=window_frames,
            activity_peak_milli=peak,
            activity_rms_milli=rms,
            possible_audio_activity=(peak >= self._threshold) if peak is not None else None,
        )

    def feed_line(self, line: str) -> ActivityReading:
        with self._lock:
            if self._state in ("completed", "invalid"):
                raise ValueError("diagnostic has already ended")
            try:
                if type(line) is not str or not 2 <= len(line) <= 4096:
                    raise ValueError("invalid bounded diagnostic line")
                row = json.loads(
                    line,
                    object_pairs_hook=_no_duplicate_keys,
                    parse_constant=lambda _: (_ for _ in ()).throw(ValueError("non-finite diagnostic value")),
                )
                if type(row) is not dict:
                    raise ValueError("expected one JSON object")
                self._lines += 1
                if self._lines > _MAX_LINES:
                    raise ValueError("diagnostic exceeded bounded line count")
                return self._check(row)
            except (ValueError, KeyError, TypeError, OverflowError) as exc:
                self._state = "invalid"
                raise ValueError("invalid local process-loopback diagnostic") from exc

    def summary(self) -> ActivityDiagnosticSummary:
        with self._lock:
            return ActivityDiagnosticSummary(
                state=self._state,
                windows=self._windows,
                pcm_windows=self._pcm_windows,
                missing_pcm_windows=self._unknown_windows,
                audio_activity_hint_windows=self._activity_windows,
                callbacks=self._callbacks,
                sample_frames=self._frames,
                maximum_peak_milli=self._max_peak,
            )


__all__ = [
    "ActivityDiagnosticSummary",
    "ActivityReading",
    "ProcessLoopbackActivityVerifier",
]
