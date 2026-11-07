"""Privacy-minimal, opt-in host measurement for Star's offline game/VTuber rehearsals.

An authorized host records *attested* timing boundaries; this class never
captures frames, audio, speech, player/chat text, worker output, or identity.
It does not verify operating-system attestation itself, launch workers, grant
game input, contact OBS/VTube Studio, or approve deployment.

A complete single-utterance rehearsal can be converted into the existing
paired `RealtimeRun` benchmark input. Only durations and bounded counters
leave the recorder; opaque intra-session correlators are never exported.
"""
from __future__ import annotations

from collections import Counter
import math
import re
from threading import RLock
from typing import cast

from .stream_realtime_benchmark import RealtimeRun

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z", re.ASCII)
_EVENT_FIELDS: dict[str, frozenset[str]] = {
    "scene_observed": frozenset({"scene_sequence"}),
    "worker_started": frozenset({"scene_sequence", "opaque_id"}),
    "worker_exited": frozenset({"scene_sequence", "opaque_id"}),
    "action_claimed": frozenset({"scene_sequence", "opaque_id"}),
    "action_released": frozenset({"scene_sequence", "opaque_id"}),
    "speech_queued": frozenset({"opaque_id"}),
    "pcm_first_audible": frozenset({"opaque_id"}),
    "pcm_stopped": frozenset({"opaque_id"}),
    "avatar_frame_rendered": frozenset({"opaque_id"}),
    "frame_presented": frozenset({"duration_ms"}),
    "gpu_peak_measured": frozenset({"gpu_peak_mib"}),
    "obs_stats_sampled": frozenset({"skipped_frames", "total_frames"}),
}


def _number(value: object, name: str, *, lower: float, upper: float) -> float:
    if type(value) not in (int, float):
        raise ValueError(f"{name} must be a host-measured number")
    try:
        number = float(cast(int | float, value))
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"{name} must be finite") from exc
    if not math.isfinite(number) or not lower <= number <= upper:
        raise ValueError(f"{name} out of range")
    return number


def _counter(value: object, name: str, *, minimum: int = 0) -> int:
    if type(value) is not int or not minimum <= value <= 10**12:
        raise ValueError(f"{name} must be a bounded integer")
    return value


def _token(value: object) -> str:
    if type(value) is not str or not _ID.fullmatch(value):
        raise ValueError("expected a short opaque correlator, never content")
    return value


def _percentile(samples: list[float], fraction: float) -> float | None:
    if not samples:
        return None
    ordered = sorted(samples)
    return round(ordered[max(0, math.ceil(fraction * len(ordered)) - 1)], 3)


class StreamRehearsalRecorder:
    """Bounded in-memory observer: one independent trusted-host rehearsal.

    `host_verified=True` MUST only be supplied by the authorized sensor host
    after checking the actual OS/game/audio/OBS boundary. LLM output must
    never be allowed to set the flag. All calls use one host-monotonic clock.

    Invalid events raise before changing the clock or session state.
    """

    def __init__(
        self, *, episode_id: str, max_events: int = 20000,
        max_duration_ms: float = 2 * 60 * 60 * 1000,
        owner_approved: bool = False,
        max_avatar_frame_gap_ms: float = 550,
    ) -> None:
        if owner_approved is not True:
            raise PermissionError("owner approval required for rehearsal measurement")
        self._episode = _token(episode_id)
        if type(max_events) is not int or not 120 <= max_events <= 100000:
            raise ValueError("max_events must be 120..100000")
        self._limit = _number(max_duration_ms, "max_duration_ms",
                              lower=1000, upper=24 * 60 * 60 * 1000)
        self._max_events = max_events
        self._avatar_gap_limit = _number(
            max_avatar_frame_gap_ms, "max_avatar_frame_gap_ms",
            lower=50, upper=3000,
        )
        self._lock = RLock()
        self._first_ms: float | None = None
        self._last_ms: float | None = None
        self._finished = False
        self._counts: Counter[str] = Counter()
        self._last_scene = 0
        self._scene_at: float | None = None
        self._used_workers: set[str] = set()
        self._worker: tuple[str, int] | None = None
        self._used_permits: set[str] = set()
        self._permit: tuple[str, int] | None = None
        self._used_speech: set[str] = set()
        self._speech: tuple[str, str, float] | None = None
        self._speech_first_avatar = False
        self._avatar_last_ms: float | None = None
        self._avatar_max_gap_ms: float | None = None
        self._avatar_frames_by_speech: list[int] = []
        self._avatar_current_count = 0
        self._gpu_peak_mib: float | None = None
        self._scene_to_action: list[float] = []
        self._speech_to_pcm: list[float] = []
        self._pcm_to_avatar: list[float] = []
        self._frame_times: list[float] = []
        self._last_presented_ms: float | None = None
        self._last_audible_presented_ms: float | None = None
        self._audible_presentation_gap_max_ms: float | None = None
        self._audible_frame_times: list[float] = []
        self._obs_previous: tuple[int, int] | None = None
        self._obs_skipped = 0
        self._obs_total = 0

    def record(
        self, event: str, *, at_ms: float, host_verified: bool = False,
        scene_sequence: int | None = None, opaque_id: str | None = None,
        duration_ms: float | None = None,
        skipped_frames: int | None = None, total_frames: int | None = None,
        gpu_peak_mib: float | None = None,
    ) -> None:
        """Record exactly the numeric fields permitted for one known event.

        No arbitrary event payload is accepted, even if it appears harmless.
        A stale scene cannot claim a game action, and a worker cannot be
        reused or silently replaced. Unknown/invalid samples poison nothing.
        """
        if type(event) is not str or event not in _EVENT_FIELDS:
            raise ValueError("unsupported rehearsal event")
        if type(host_verified) is not bool or not host_verified:
            raise PermissionError("independently verified host evidence required")
        provided = {
            name for name, value in (
                ("scene_sequence", scene_sequence), ("opaque_id", opaque_id),
                ("duration_ms", duration_ms), ("skipped_frames", skipped_frames),
                ("total_frames", total_frames), ("gpu_peak_mib", gpu_peak_mib),
            ) if value is not None
        }
        if provided != _EVENT_FIELDS[event]:
            raise ValueError("event fields do not match the strict schema")
        when = _number(at_ms, "at_ms", lower=0, upper=1e13)
        if scene_sequence is not None:
            _counter(scene_sequence, "scene_sequence", minimum=1)
        if opaque_id is not None:
            _token(opaque_id)
        if duration_ms is not None:
            _number(duration_ms, "duration_ms", lower=0.01, upper=10000)
        if skipped_frames is not None:
            _counter(skipped_frames, "skipped_frames")
        if total_frames is not None:
            _counter(total_frames, "total_frames")
        if gpu_peak_mib is not None:
            _number(gpu_peak_mib, "gpu_peak_mib", lower=1, upper=262144)

        with self._lock:
            if self._finished:
                raise RuntimeError("rehearsal has ended")
            if sum(self._counts.values()) >= self._max_events:
                raise RuntimeError("bounded recorder is full")
            if self._last_ms is not None and when < self._last_ms:
                raise ValueError("host monotonic clock reversed")
            if self._first_ms is not None and when - self._first_ms > self._limit:
                raise ValueError("host episode duration exceeded")

            if event == "scene_observed":
                assert scene_sequence is not None
                if scene_sequence <= self._last_scene:
                    raise ValueError("replayed or out-of-order scene")
                if self._permit is not None:
                    raise ValueError("cannot advance scene with held input")
                self._last_scene = scene_sequence
                self._scene_at = when
            elif event == "worker_started":
                assert scene_sequence is not None and opaque_id is not None
                if (self._worker is not None or scene_sequence != self._last_scene
                        or opaque_id in self._used_workers):
                    raise ValueError("worker overlap, replay or stale scene")
                self._worker = (opaque_id, scene_sequence)
                self._used_workers.add(opaque_id)
            elif event == "worker_exited":
                if self._worker != (opaque_id, scene_sequence):
                    raise ValueError("worker exit was not matched to its start")
                self._worker = None
            elif event == "action_claimed":
                assert scene_sequence is not None and opaque_id is not None
                if (self._permit is not None or self._worker is not None
                        or scene_sequence != self._last_scene
                        or self._scene_at is None
                        or opaque_id in self._used_permits):
                    raise ValueError("stale scene, concurrent worker or held input")
                self._permit = (opaque_id, scene_sequence)
                self._used_permits.add(opaque_id)
                self._scene_to_action.append(when - self._scene_at)
            elif event == "action_released":
                if self._permit != (opaque_id, scene_sequence):
                    raise ValueError("input release was not matched to its claim")
                self._permit = None
            elif event == "speech_queued":
                assert opaque_id is not None
                if self._speech is not None or opaque_id in self._used_speech:
                    raise ValueError("speech overlap or replay")
                self._speech = (opaque_id, "queued", when)
                self._speech_first_avatar = False
                self._avatar_last_ms = None
                self._avatar_current_count = 0
                self._used_speech.add(opaque_id)
            elif event == "pcm_first_audible":
                if self._speech is None or self._speech[:2] != (opaque_id, "queued"):
                    raise ValueError("no queued utterance for audible PCM")
                self._speech_to_pcm.append(when - self._speech[2])
                self._speech = (self._speech[0], "audible", when)
                self._avatar_last_ms = when
                self._last_audible_presented_ms = None
            elif event == "avatar_frame_rendered":
                if self._speech is None or self._speech[:2] != (opaque_id, "audible"):
                    raise ValueError("avatar cannot claim unsounded speech")
                if self._avatar_last_ms is None:
                    raise RuntimeError("audio interval not initialized")
                gap = when - self._avatar_last_ms
                self._avatar_max_gap_ms = max(self._avatar_max_gap_ms or 0, gap)
                self._avatar_last_ms = when
                self._avatar_current_count += 1
                if not self._speech_first_avatar:
                    self._pcm_to_avatar.append(when - self._speech[2])
                    self._speech_first_avatar = True
            elif event == "pcm_stopped":
                if self._speech is None or self._speech[:2] != (opaque_id, "audible"):
                    raise ValueError("audio stop lacks audible beginning")
                if self._avatar_last_ms is None:
                    raise RuntimeError("audio interval not initialized")
                gap = when - self._avatar_last_ms
                self._avatar_max_gap_ms = max(self._avatar_max_gap_ms or 0, gap)
                self._avatar_frames_by_speech.append(self._avatar_current_count)
                # Do not hide a frozen game presentation at the END of speech:
                # no more host frame callbacks is still a visible stall.
                if self._last_audible_presented_ms is not None:
                    tail_ms = when - self._last_audible_presented_ms
                    self._audible_presentation_gap_max_ms = max(
                        self._audible_presentation_gap_max_ms or 0, tail_ms,
                    )
                    self._audible_frame_times[-1] = max(
                        self._audible_frame_times[-1], tail_ms,
                    )
                self._avatar_last_ms = None
                self._speech = None
            elif event == "gpu_peak_measured":
                assert gpu_peak_mib is not None
                if self._gpu_peak_mib is not None or not self._frame_times:
                    raise ValueError("GPU peak must be measured once after game frames")
                if self._speech is not None or self._counts["pcm_stopped"] != 1:
                    raise ValueError("GPU peak measured before completed audible speech")
                self._gpu_peak_mib = float(gpu_peak_mib)
            elif event == "frame_presented":
                assert duration_ms is not None
                if self._gpu_peak_mib is not None:
                    raise ValueError("cannot measure more frames after final GPU peak")
                if (self._last_presented_ms is not None
                        and when <= self._last_presented_ms):
                    raise ValueError("duplicate or non-increasing frame presentation timestamp")
                self._last_presented_ms = when
                self._frame_times.append(float(duration_ms))
                if self._speech is not None and self._speech[1] == "audible":
                    # A reported 16 ms render duration is not evidence of
                    # 60 FPS when the actual host presentation callbacks
                    # arrive only once per 100 ms. Conservatively use the
                    # larger of the duration and monotonic presentation gap.
                    anchor_ms = (self._last_audible_presented_ms
                                 if self._last_audible_presented_ms is not None
                                 else self._speech[2])
                    gap_ms = when - anchor_ms
                    self._audible_presentation_gap_max_ms = max(
                        self._audible_presentation_gap_max_ms or 0, gap_ms,
                    )
                    self._audible_frame_times.append(
                        max(float(duration_ms), gap_ms)
                    )
                    self._last_audible_presented_ms = when
            elif event == "obs_stats_sampled":
                assert skipped_frames is not None and total_frames is not None
                if skipped_frames > total_frames:
                    raise ValueError("OBS skipped frames cannot exceed total")
                if self._obs_previous is not None:
                    previous_skipped, previous_total = self._obs_previous
                    delta_skipped = skipped_frames - previous_skipped
                    delta_total = total_frames - previous_total
                    if delta_total <= 0 or not 0 <= delta_skipped <= delta_total:
                        raise ValueError("OBS counter replay/reset or impossible delta")
                    self._obs_skipped += delta_skipped
                    self._obs_total += delta_total
                self._obs_previous = (skipped_frames, total_frames)
            else:
                raise AssertionError("event schema branch missing")
            self._counts[event] += 1
            self._last_ms = when
            if self._first_ms is None:
                self._first_ms = when

    def end(self, *, at_ms: float, host_verified: bool = False) -> None:
        """Finish even after a crashed session; incomplete resources stay visible."""
        if type(host_verified) is not bool or not host_verified:
            raise PermissionError("host end attestation required")
        when = _number(at_ms, "at_ms", lower=0, upper=1e13)
        with self._lock:
            if self._finished:
                raise RuntimeError("already finished")
            if self._last_ms is not None and when < self._last_ms:
                raise ValueError("host monotonic clock reversed")
            if self._first_ms is not None and when - self._first_ms > self._limit:
                raise ValueError("host episode duration exceeded")
            self._last_ms = when
            self._finished = True

    def report(self) -> dict[str, object]:
        """Privacy-minimal numeric report, never raw observations or correlators."""
        with self._lock:
            complete = (self._finished and self._worker is None
                        and self._permit is None and self._speech is None)
            return {
                "finished": self._finished,
                "clean_shutdown": complete,
                "events": sum(self._counts.values()),
                "scenes": self._counts["scene_observed"],
                "workers_started": self._counts["worker_started"],
                "workers_exited": self._counts["worker_exited"],
                "actions_claimed": self._counts["action_claimed"],
                "actions_released": self._counts["action_released"],
                "utterances_audible": self._counts["pcm_first_audible"],
                "utterances_stopped": self._counts["pcm_stopped"],
                "frame_samples": len(self._frame_times),
                "audible_frame_samples": len(self._audible_frame_times),
                "audible_presentation_gap_max_ms": (
                    round(self._audible_presentation_gap_max_ms, 3)
                    if self._audible_presentation_gap_max_ms is not None
                    else None
                ),
                "audible_effective_frame_time_p99_ms": _percentile(
                    self._audible_frame_times, 0.99,
                ),
                "avatar_frame_samples": self._counts["avatar_frame_rendered"],
                "avatar_frame_gap_max_ms": (
                    round(self._avatar_max_gap_ms, 3)
                    if self._avatar_max_gap_ms is not None else None
                ),
                "gpu_peak_measured": self._gpu_peak_mib is not None,
                "gpu_peak_mib": self._gpu_peak_mib,
                "obs_samples": self._counts["obs_stats_sampled"],
                "obs_skipped_fraction": (
                    round(self._obs_skipped / self._obs_total, 6)
                    if self._obs_total else None
                ),
                "scene_to_action_p50_ms": _percentile(self._scene_to_action, 0.50),
                "scene_to_action_p95_ms": _percentile(self._scene_to_action, 0.95),
                "scene_to_action_p99_ms": _percentile(self._scene_to_action, 0.99),
                "speech_to_audible_p50_ms": _percentile(self._speech_to_pcm, 0.50),
                "speech_to_audible_p95_ms": _percentile(self._speech_to_pcm, 0.95),
                "speech_to_audible_p99_ms": _percentile(self._speech_to_pcm, 0.99),
                "pcm_to_avatar_p95_ms": _percentile(self._pcm_to_avatar, 0.95),
                "frame_time_p95_ms": _percentile(self._frame_times, 0.95),
                "frame_time_p99_ms": _percentile(self._frame_times, 0.99),
                "max_frame_time_ms": max(self._frame_times, default=None),
                "note": "host-attested inputs only; not a deployment or model-performance claim",
            }

    def to_realtime_run(
        self, *, pair_id: str, variant: str, game_id: str,
        game_version: str,
    ) -> RealtimeRun:
        """Bridge a complete one-utterance rehearsal to existing paired QoS tests.

        GPU high-water-mark must be recorded as a *host-verified event* after
        the frames, never supplied by the caller as an unverified argument.
        The frame cadence check prevents a frozen/missing avatar renderer from
        qualifying as a high-quality real-time speech rehearsal. Renderer
        frames do not themselves prove natural motion or lip-sync accuracy.
        Export uses conservative host presentation gaps (including the
        beginning/end of audible PCM), never optimistic duration claims
        alone. Non-increasing presentation timestamps are invalid.
        """
        with self._lock:
            if (not self.report()["clean_shutdown"]
                    or len(self._speech_to_pcm) != 1
                    or self._counts["pcm_stopped"] != 1
                    or len(self._frame_times) > 5000
                    or not 120 <= len(self._audible_frame_times) <= 5000):
                raise ValueError("complete one-speech, 120..5000 audible-game frames required")
            if self._gpu_peak_mib is None:
                raise ValueError("host-verified GPU peak required for benchmark")
            if (self._avatar_frames_by_speech != [self._counts["avatar_frame_rendered"]]
                    or not self._avatar_frames_by_speech[0]
                    or self._avatar_max_gap_ms is None
                    or self._avatar_max_gap_ms > self._avatar_gap_limit):
                raise ValueError("missing or frozen avatar frames during audible speech")
            return RealtimeRun(
                pair_id=pair_id, variant=variant, game_id=game_id,
                game_version=game_version, first_audio_ms=self._speech_to_pcm[0],
                frame_times_ms=tuple(self._audible_frame_times),
                gpu_peak_mib=self._gpu_peak_mib, audio_finished=True,
            )
