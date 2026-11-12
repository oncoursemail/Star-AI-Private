"""Bounded, epoch-aware measurements for STAR's private stream rehearsals.

This is the missing host-side aggregation boundary between trusted local
observers and stream_rehearsal_eval. It performs no device I/O, network calls,
audio capture, OBS control, game input, model inference, or authorization.

Callers must supply observations from trusted host components on one monotonic
clock. Cumulative counters are differenced only inside the same source epoch.
High-rate samples use deterministic reservoir sampling so a long rehearsal
stays bounded while representing the whole session.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
import random
import re
from threading import RLock
from typing import Any

from .stream_rehearsal_eval import RehearsalLimits, evaluate_rehearsal

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}\Z")
_RUN_ID = _ID
_MAX_MS = 300_000.0
_MAX_COUNTER = 1_000_000_000
_MAX_SAMPLES = 100_000
_MAX_EVENT_IDS = 100_000
_MAX_EPOCHS_PER_SOURCE = 64
_MAX_FRAME_GAP_MS = 10_000.0
_SOURCES = frozenset({"inference", "audio", "game", "avatar", "obs"})
_SERIES = (
    "first_content_latency_ms",
    "first_audible_latency_ms",
    "game_frame_time_ms",
    "avatar_sync_error_ms",
)
_COUNTS = (
    "audio_underrun_chunks",
    "audio_playback_chunks",
    "obs_render_skipped_frames",
    "obs_render_total_frames",
    "obs_output_skipped_frames",
    "obs_output_total_frames",
    "turn_true_positives",
    "turn_false_positives",
    "turn_false_negatives",
    "task_recovery_attempts",
    "task_recovery_successes",
    "stale_task_resumes",
    "duplicate_speech_replays",
    "held_out_skill_trials",
    "held_out_skill_successes",
)


def _identifier(value: object, label: str) -> str:
    if type(value) is not str or not _ID.fullmatch(value):
        raise ValueError(f"{label} must be a bounded opaque identifier")
    return value


def _milliseconds(value: object, label: str) -> float:
    if type(value) not in (int, float):
        raise ValueError(f"{label} must be a finite nonnegative number")
    result = float(value)
    if not math.isfinite(result) or not 0 <= result <= 1e13:
        raise ValueError(f"{label} is outside the supported range")
    return result


def _counter(value: object, label: str) -> int:
    if type(value) is not int or not 0 <= value <= _MAX_COUNTER:
        raise ValueError(f"{label} must be a bounded nonnegative integer")
    return value


@dataclass
class _Reservoir:
    """Deterministic Algorithm-R reservoir for one numeric measurement series."""

    capacity: int
    seed: int

    def __post_init__(self) -> None:
        self.values: list[float] = []
        self.seen = 0
        self._random = random.Random(self.seed)

    def add(self, value: float) -> None:
        self.seen += 1
        if len(self.values) < self.capacity:
            self.values.append(value)
            return
        slot = self._random.randrange(self.seen)
        if slot < self.capacity:
            self.values[slot] = value

    def health(self) -> dict[str, int | float]:
        return {
            "observed": self.seen,
            "retained": len(self.values),
            "sampling_fraction": (
                round(len(self.values) / self.seen, 6) if self.seen else 0.0
            ),
        }


class StreamRehearsalRecorder:
    """Thread-safe, one-run recorder that feeds STAR's rehearsal evaluator.

    The recorder accepts only bounded measurements, opaque event IDs, and
    source epochs. It never accepts chat, transcripts, prompts, audio, images,
    viewer identities, process names, device names, or arbitrary metadata.

    Epoch values must be freshly generated opaque IDs whenever a producer
    restarts. Reusing an earlier epoch is rejected. This prevents cumulative
    OBS/audio counters or frame timestamps from being differenced across a
    process restart or clock discontinuity.
    """

    def __init__(
        self,
        run_id: str,
        *,
        max_samples: int = 100_000,
        max_event_ids: int = 100_000,
    ) -> None:
        self._run_id = _identifier(run_id, "run_id")
        if type(max_samples) is not int or not 1 <= max_samples <= _MAX_SAMPLES:
            raise ValueError("max_samples must be in 1..100000")
        if type(max_event_ids) is not int or not 1 <= max_event_ids <= _MAX_EVENT_IDS:
            raise ValueError("max_event_ids must be in 1..100000")
        self._max_event_ids = max_event_ids
        self._lock = RLock()
        self._series: dict[str, _Reservoir] = {}
        for name in _SERIES:
            seed_bytes = hashlib.sha256(
                b"star.stream-rehearsal-reservoir.v1\x00"
                + self._run_id.encode("ascii")
                + b"\x00"
                + name.encode("ascii")
            ).digest()
            self._series[name] = _Reservoir(
                max_samples, int.from_bytes(seed_bytes[:8], "big")
            )
        self._counts = {name: 0 for name in _COUNTS}
        self._event_ids: set[str] = set()
        self._epochs: dict[str, str] = {}
        self._epoch_history: dict[str, set[str]] = {
            source: set() for source in _SOURCES
        }
        self._source_restarts = {source: 0 for source in _SOURCES}
        self._counter_baselines: dict[str, tuple[int, ...]] = {}
        self._last_frame_ms: float | None = None
        self._rejected_observations = 0
        self._duplicate_events = 0
        self._counter_regressions = 0
        self._frame_discontinuities = 0
        self._baseline_observations = {"audio": 0, "obs": 0}

    def _reject(self) -> bool:
        self._rejected_observations += 1
        return False

    def _add_count(self, name: str, amount: int) -> None:
        value = self._counts[name] + amount
        if value > _MAX_COUNTER:
            raise OverflowError(f"{name} exceeded the bounded counter limit")
        self._counts[name] = value

    def _use_epoch(self, source: str, epoch: str) -> bool:
        if source not in _SOURCES:
            raise ValueError("unsupported telemetry source")
        epoch = _identifier(epoch, "source epoch")
        digest = hashlib.sha256(
            b"star.stream-rehearsal-epoch.v1\x00"
            + source.encode("ascii")
            + b"\x00"
            + epoch.encode("ascii")
        ).hexdigest()
        current = self._epochs.get(source)
        if current == digest:
            return True
        history = self._epoch_history[source]
        if digest in history:
            return self._reject()
        if len(history) >= _MAX_EPOCHS_PER_SOURCE:
            raise RuntimeError("source epoch history is full; start a new rehearsal")
        if current is not None:
            self._source_restarts[source] += 1
            if source == "game":
                self._last_frame_ms = None
            if source in {"audio", "obs"}:
                self._counter_baselines.pop(source, None)
        history.add(digest)
        self._epochs[source] = digest
        return True

    def _remember_event(self, category: str, event_id: str) -> bool:
        event_id = _identifier(event_id, "event_id")
        digest = hashlib.sha256(
            b"star.stream-rehearsal-event.v1\x00"
            + category.encode("ascii")
            + b"\x00"
            + event_id.encode("ascii")
        ).hexdigest()
        if digest in self._event_ids:
            self._duplicate_events += 1
            return False
        if len(self._event_ids) >= self._max_event_ids:
            raise RuntimeError("event replay ledger is full; start a new rehearsal")
        self._event_ids.add(digest)
        return True

    def record_latency(
        self,
        kind: str,
        *,
        event_id: str,
        epoch: str,
        started_ms: float,
        first_ms: float,
    ) -> bool:
        """Record first-content or first-audible latency from host timestamps.

        Both timestamps must use the same monotonic clock and source epoch.
        First audible should be acknowledged by the local playback boundary,
        not inferred from text generation or TTS completion.
        """
        if kind not in {"first_content", "first_audible"}:
            raise ValueError("kind must be first_content or first_audible")
        event_id = _identifier(event_id, "event_id")
        start = _milliseconds(started_ms, "started_ms")
        first = _milliseconds(first_ms, "first_ms")
        latency = first - start
        if latency < 0 or latency > _MAX_MS:
            raise ValueError("latency must be nonnegative and at most 300000 ms")
        source = "inference" if kind == "first_content" else "audio"
        series = f"{kind}_latency_ms"
        with self._lock:
            if not self._use_epoch(source, epoch):
                return False
            if not self._remember_event(kind, event_id):
                return False
            self._series[series].add(latency)
            return True

    def record_frame_present(self, *, epoch: str, at_ms: float) -> bool:
        """Record an actual frame-present callback, never model-estimated FPS."""
        at = _milliseconds(at_ms, "at_ms")
        with self._lock:
            if not self._use_epoch("game", epoch):
                return False
            previous = self._last_frame_ms
            if previous is None:
                self._last_frame_ms = at
                return True
            if at <= previous:
                return self._reject()
            self._last_frame_ms = at
            gap = at - previous
            if gap > _MAX_FRAME_GAP_MS:
                # Treat a long pause/focus loss as a discontinuity, not a
                # fabricated multi-second rendered frame.
                self._frame_discontinuities += 1
                return False
            self._series["game_frame_time_ms"].add(gap)
            return True

    def record_avatar_sync(
        self,
        *,
        event_id: str,
        audio_epoch: str,
        avatar_epoch: str,
        playback_at_ms: float,
        avatar_update_at_ms: float,
    ) -> bool:
        """Record absolute playback-clock to avatar-update timing error."""
        event_id = _identifier(event_id, "event_id")
        playback = _milliseconds(playback_at_ms, "playback_at_ms")
        avatar = _milliseconds(avatar_update_at_ms, "avatar_update_at_ms")
        error = abs(avatar - playback)
        if error > _MAX_MS:
            raise ValueError("avatar synchronization error exceeds supported range")
        with self._lock:
            if not self._use_epoch("audio", audio_epoch):
                return False
            if not self._use_epoch("avatar", avatar_epoch):
                return False
            if not self._remember_event("avatar_sync", event_id):
                return False
            self._series["avatar_sync_error_ms"].add(error)
            return True

    def observe_audio_counters(
        self,
        *,
        epoch: str,
        underruns_total: int,
        playback_chunks_total: int,
    ) -> bool:
        """Accumulate counter deltas only within one audio-device epoch."""
        underruns = _counter(underruns_total, "underruns_total")
        playback = _counter(playback_chunks_total, "playback_chunks_total")
        if underruns > playback:
            raise ValueError("audio underruns cannot exceed playback chunks")
        with self._lock:
            if not self._use_epoch("audio", epoch):
                return False
            previous = self._counter_baselines.get("audio")
            current = (underruns, playback)
            if previous is None:
                self._counter_baselines["audio"] = current
                self._baseline_observations["audio"] += 1
                return False
            if any(new < old for new, old in zip(current, previous)):
                self._counter_regressions += 1
                return self._reject()
            delta_underruns = underruns - previous[0]
            delta_playback = playback - previous[1]
            if delta_underruns > delta_playback:
                return self._reject()
            self._add_count("audio_underrun_chunks", delta_underruns)
            self._add_count("audio_playback_chunks", delta_playback)
            self._counter_baselines["audio"] = current
            return True

    def observe_obs_counters(
        self,
        *,
        epoch: str,
        render_skipped_total: int,
        render_total: int,
        output_skipped_total: int,
        output_total: int,
    ) -> bool:
        """Accumulate OBS render and output counters as separate measurements.

        OBS process restarts require a new epoch. A counter decrease in the same
        epoch is rejected and does not silently establish a new baseline.
        """
        render_skipped = _counter(render_skipped_total, "render_skipped_total")
        render = _counter(render_total, "render_total")
        output_skipped = _counter(output_skipped_total, "output_skipped_total")
        output = _counter(output_total, "output_total")
        if render_skipped > render or output_skipped > output:
            raise ValueError("OBS skipped frames cannot exceed their total frames")
        with self._lock:
            if not self._use_epoch("obs", epoch):
                return False
            current = (render_skipped, render, output_skipped, output)
            previous = self._counter_baselines.get("obs")
            if previous is None:
                self._counter_baselines["obs"] = current
                self._baseline_observations["obs"] += 1
                return False
            if any(new < old for new, old in zip(current, previous)):
                self._counter_regressions += 1
                return self._reject()
            delta = tuple(new - old for new, old in zip(current, previous))
            if delta[0] > delta[1] or delta[2] > delta[3]:
                return self._reject()
            self._add_count("obs_render_skipped_frames", delta[0])
            self._add_count("obs_render_total_frames", delta[1])
            self._add_count("obs_output_skipped_frames", delta[2])
            self._add_count("obs_output_total_frames", delta[3])
            self._counter_baselines["obs"] = current
            return True

    def record_turn_outcome(
        self,
        *,
        event_id: str,
        true_positives: int,
        false_positives: int,
        false_negatives: int,
        independently_labeled: bool,
    ) -> bool:
        """Add externally labeled turn-taking counts; no transcript is accepted."""
        if type(independently_labeled) is not bool or not independently_labeled:
            raise PermissionError("turn outcomes require independent labels")
        tp = _counter(true_positives, "true_positives")
        fp = _counter(false_positives, "false_positives")
        fn = _counter(false_negatives, "false_negatives")
        event_id = _identifier(event_id, "event_id")
        with self._lock:
            if not self._remember_event("turn_outcome", event_id):
                return False
            self._add_count("turn_true_positives", tp)
            self._add_count("turn_false_positives", fp)
            self._add_count("turn_false_negatives", fn)
            return True

    def record_task_recovery(
        self,
        *,
        event_id: str,
        succeeded: bool,
        stale_resume: bool = False,
    ) -> bool:
        """Record one host-observed resume attempt without task content."""
        if type(succeeded) is not bool or type(stale_resume) is not bool:
            raise ValueError("succeeded and stale_resume must be explicit booleans")
        if succeeded and stale_resume:
            raise ValueError("a stale resume cannot count as a successful recovery")
        event_id = _identifier(event_id, "event_id")
        with self._lock:
            if not self._remember_event("task_recovery", event_id):
                return False
            self._add_count("task_recovery_attempts", 1)
            if succeeded:
                self._add_count("task_recovery_successes", 1)
            if stale_resume:
                self._add_count("stale_task_resumes", 1)
            return True

    def record_speech_replay(self, *, event_id: str, duplicate: bool) -> bool:
        """Record whether a playback acknowledgement exposed duplicate speech."""
        if type(duplicate) is not bool:
            raise ValueError("duplicate must be an explicit boolean")
        event_id = _identifier(event_id, "event_id")
        with self._lock:
            if not self._remember_event("speech_replay", event_id):
                return False
            if duplicate:
                self._add_count("duplicate_speech_replays", 1)
            return True

    def record_held_out_skill_trial(
        self,
        *,
        event_id: str,
        succeeded: bool,
        independently_scored: bool,
    ) -> bool:
        """Record only a held-out result from a trusted independent game scorer."""
        if type(succeeded) is not bool:
            raise ValueError("succeeded must be an explicit boolean")
        if type(independently_scored) is not bool or not independently_scored:
            raise PermissionError("held-out skill outcomes require independent scoring")
        event_id = _identifier(event_id, "event_id")
        with self._lock:
            if not self._remember_event("held_out_skill", event_id):
                return False
            self._add_count("held_out_skill_trials", 1)
            if succeeded:
                self._add_count("held_out_skill_successes", 1)
            return True

    def snapshot(self) -> dict[str, Any]:
        """Return exactly the aggregate schema consumed by evaluate_rehearsal."""
        with self._lock:
            result: dict[str, Any] = {
                "schema_version": 1,
                "run_id": self._run_id,
            }
            for name in _SERIES:
                result[name] = list(self._series[name].values)
            result.update(self._counts)
            return result

    def evaluate(self, limits: RehearsalLimits) -> dict[str, Any]:
        """Evaluate this run with the existing fail-closed rehearsal gates."""
        return evaluate_rehearsal(self.snapshot(), limits)

    def health(self) -> dict[str, Any]:
        """Return aggregate recorder health without source IDs or private content."""
        with self._lock:
            return {
                "run_id": self._run_id,
                "sample_series": {
                    name: self._series[name].health() for name in _SERIES
                },
                "source_restarts": dict(self._source_restarts),
                "source_epoch_counts": {
                    source: len(self._epoch_history[source]) for source in _SOURCES
                },
                "counter_baselines": {
                    source: source in self._counter_baselines
                    for source in ("audio", "obs")
                },
                "baseline_observations": dict(self._baseline_observations),
                "rejected_observations": self._rejected_observations,
                "duplicate_events": self._duplicate_events,
                "counter_regressions": self._counter_regressions,
                "frame_discontinuities": self._frame_discontinuities,
                "event_ids_retained": len(self._event_ids),
            }


__all__ = ["StreamRehearsalRecorder"]
