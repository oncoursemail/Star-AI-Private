"""Bounded, privacy-minimal trusted-host timing collector for Star's offline A/B tests.

This is an *instrumentation contract*, not an audio/game/OBS/OS observer.
A separate authorized host must connect real game frame-presentation callbacks,
GPU memory sampling, and the first PCM buffer *confirmed audible by the sound
device*. The AI model and viewer messages must never call these methods.
Host-supplied timestamps use ONE monotonic millisecond clock.

The output is exactly a RealtimeRun for the independent, advisory benchmark.
No dialogue, voices, media, player names, key codes, GPU processes, or tokens
are accepted or retained. A failed/aborted utterance is NEVER silently dropped.
"""
from __future__ import annotations

from dataclasses import asdict
import json
import math
import re
from threading import RLock
from typing import cast

from .stream_realtime_benchmark import RealtimeRun

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_MAX_CLOCK = 1e13
_NO_AUDIBLE_SENTINEL_MS = 120_000.0


def _clock(value: object) -> float:
    if type(value) not in (int, float):
        raise ValueError("timestamps must be same-clock monotonic milliseconds")
    try:
        number = float(cast(float, value))
    except (OverflowError, ValueError) as exc:
        raise ValueError("timestamp must be finite") from exc
    if not math.isfinite(number) or not 0 <= number <= _MAX_CLOCK:
        raise ValueError("timestamp must be finite, nonnegative and bounded")
    return number


def _gpu_memory(value: object) -> float:
    if type(value) not in (int, float):
        raise ValueError("GPU memory sample must be numeric MiB")
    try:
        number = float(cast(float, value))
    except (OverflowError, ValueError) as exc:
        raise ValueError("GPU memory sample must be finite") from exc
    if not math.isfinite(number) or not 0 <= number <= 262_144:
        raise ValueError("GPU memory sample outside supported MiB range")
    return number


class HostStreamTrace:
    """Single-use, threadsafe measurement ledger for one baseline or candidate.

    Call: speech_requested -> presented_frame/gpu_memory_observed ->
    first_audio_audible (optional) -> audio_ended -> collect >=120 frame
    intervals -> finalize. Host must keep a failed run, including a no-audio
    timeout, and also retain incomplete pairs for benchmark rejection.

    A 'trusted' flag alone is NOT an authentication boundary. The upstream
    host has to own the callback sources, opt-in, and prevent model access.
    """

    def __init__(self, *, pair_id: str, variant: str, game_id: str,
                 game_version: str, playback_epoch: str,
                 owner_approved: bool = False) -> None:
        if owner_approved is not True:
            raise PermissionError("authorized host and owner approval required")
        for label, value in (("pair_id", pair_id), ("game_id", game_id),
                             ("game_version", game_version)):
            if type(value) is not str or not _ID.fullmatch(value):
                raise ValueError(f"{label} must be a bounded opaque identifier")
        if variant not in ("baseline", "candidate"):
            raise ValueError("variant must be baseline or candidate")
        if type(playback_epoch) is not str or not _ID.fullmatch(playback_epoch):
            raise ValueError("playback_epoch must be a bounded opaque identifier")
        self._playback_epoch = playback_epoch
        self._pair_id = pair_id
        self._variant = variant
        self._game_id = game_id
        self._game_version = game_version
        self._lock = RLock()
        self._started_ms: float | None = None
        self._clock_ms: float | None = None
        self._last_presented_ms: float | None = None
        self._first_audio_ms: float | None = None
        self._frame_times: list[float] = []
        self._gpu_peak_mib: float | None = None
        self._finished: bool | None = None
        self._result: RealtimeRun | None = None

    def _advance(self, at_ms: object) -> float:
        now = _clock(at_ms)
        if self._clock_ms is not None and now < self._clock_ms:
            raise ValueError("callback timestamp moved backward")
        self._clock_ms = now
        return now

    def _running(self) -> None:
        if self._started_ms is None:
            raise RuntimeError("speech request must start measurement first")
        if self._result is not None:
            raise RuntimeError("measurement is finalized and immutable")

    def speech_requested(self, at_ms: float) -> None:
        """Trusted queue admission/request, not completion of text generation."""
        with self._lock:
            if self._started_ms is not None:
                raise RuntimeError("one speech request per capture")
            self._started_ms = self._advance(at_ms)

    def presented_frame(self, at_ms: float) -> None:
        """Observe real frame-present timestamps, deriving durations ourselves."""
        with self._lock:
            self._running()
            now = self._advance(at_ms)
            if self._last_presented_ms is not None:
                if len(self._frame_times) >= 5000:
                    raise ValueError("frame capture exceeds 5000 intervals")
                interval = now - self._last_presented_ms
                if not 0.01 <= interval <= 10_000:
                    raise ValueError("invalid game frame-present interval")
                self._frame_times.append(interval)
            self._last_presented_ms = now

    def gpu_memory_observed(self, at_ms: float, *, used_mib: float) -> None:
        """Trusted device-used/allocated MiB, sampled during game+speech run."""
        with self._lock:
            self._running()
            memory = _gpu_memory(used_mib)
            self._advance(at_ms)
            self._gpu_peak_mib = max(
                memory, self._gpu_peak_mib if self._gpu_peak_mib is not None else 0.0
            )

    def first_audio_audible(self, at_ms: float, *, playback_epoch: str,
                            sound_device_confirmed: bool = False) -> None:
        """Only the audio host may call after a genuine device playback ACK."""
        with self._lock:
            self._running()
            if playback_epoch != self._playback_epoch:
                raise PermissionError("stale or foreign audio playback epoch")
            if sound_device_confirmed is not True:
                raise PermissionError("audio generation is not audible playback")
            if self._finished is not None or self._first_audio_ms is not None:
                raise RuntimeError("cannot acknowledge duplicate/ended audio")
            now = self._advance(at_ms)
            latency = now - cast(float, self._started_ms)
            if latency > _NO_AUDIBLE_SENTINEL_MS:
                raise ValueError("first audible response exceeded 120 seconds")
            self._first_audio_ms = now

    def audio_ended(self, at_ms: float, *, playback_epoch: str,
                    playback_finished: bool) -> None:
        """Explicitly record success *or failure*; future frame samples allowed."""
        with self._lock:
            self._running()
            if playback_epoch != self._playback_epoch:
                raise PermissionError("stale or foreign audio playback epoch")
            if type(playback_finished) is not bool:
                raise ValueError("playback_finished must be trusted boolean")
            if self._finished is not None:
                raise RuntimeError("audio already ended")
            if playback_finished and self._first_audio_ms is None:
                raise ValueError("cannot claim finished speech without audible ACK")
            self._advance(at_ms)
            self._finished = playback_finished

    def finalize(self) -> RealtimeRun:
        """Return an immutable sample for Star's pre-existing paired evaluator."""
        with self._lock:
            self._running()
            if self._finished is None:
                raise RuntimeError("missing explicit audio end/abort")
            if len(self._frame_times) < 120:
                raise RuntimeError("need at least 120 observed game-frame intervals")
            if self._gpu_peak_mib is None:
                raise RuntimeError("need a real host GPU memory sample")
            first_audio_ms = (
                self._first_audio_ms - cast(float, self._started_ms)
                if self._first_audio_ms is not None else _NO_AUDIBLE_SENTINEL_MS
            )
            self._result = RealtimeRun(
                self._pair_id, self._variant, self._game_id, self._game_version,
                first_audio_ms, tuple(self._frame_times), self._gpu_peak_mib,
                self._finished,
            )
            return self._result

    def to_jsonl(self) -> str:
        """Privacy-minimal JSONL line, matching read_jsonl()'s exact schema."""
        with self._lock:
            if self._result is None:
                raise RuntimeError("finalize before exporting")
            return json.dumps(asdict(self._result), separators=(",", ":"),
                              allow_nan=False, ensure_ascii=True) + "\n"
