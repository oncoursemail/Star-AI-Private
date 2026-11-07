"""Opt-in, offline-testable *evidence gate* for interrupted Star voice audio.

The source MUST be an independent, owner-controlled PCM16 loopback capture of
Star's ISOLATED voice process or dedicated voice device (not a speaker queue).
Windows process loopback may deliver NO PCM while the voice is quiet, so the
trusted host can alternatively report fresh OS capture polls and callback
generation. An absent callback *alone* never establishes silence.
This module NEVER opens audio devices or trusts model/viewer-supplied samples.

A valid result means a trusted digital capture was quiet for a window; it
cannot prove physical DAC, an OBS monitor, or an external viewer heard silence.
The host must still check the native abort and neutral avatar independently.
"""

from __future__ import annotations

import math
import re
import struct
from threading import RLock

_EPOCH = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z", re.ASCII)


def _finite(value: object) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value) and value >= 0
    except OverflowError:  # huge integer timestamp from a faulty host
        return False


class IsolatedLoopbackQuietWitness:
    """Bounded, fail-closed witness; never stores PCM, identities or transcripts.

    All timestamps are start-of-captured-block CLOCK_MONOTONIC seconds, not
    wall time, enqueue time or a TTS generation estimate. The external capture
    adapter attests that capture is isolated and running with a stable route
    generation. It must NOT feed zero-filled buffers on device failure.

    This is deliberately a separate witness, not a method on SoundSpeaker:
    playback buffers or PortAudio 'stopped' flags cannot prove capture quiet.
    """

    def __init__(
        self,
        *,
        sample_rate_hz: int,
        owner_approved: bool = False,
        quiet_window_ms: int = 180,
        peak_limit: int = 96,
    ) -> None:
        if owner_approved is not True:
            raise PermissionError("local owner opt-in required")
        if type(sample_rate_hz) is not int or not 8000 <= sample_rate_hz <= 96000:
            raise ValueError("unsupported mono PCM16 capture rate")
        if type(quiet_window_ms) is not int or not 100 <= quiet_window_ms <= 500:
            raise ValueError("quiet observation must span 100..500 ms")
        if type(peak_limit) is not int or not 0 <= peak_limit <= 512:
            raise ValueError("invalid conservative PCM16 peak threshold")
        self._rate = sample_rate_hz
        self._quiet_s = quiet_window_ms / 1000
        self._peak_limit = peak_limit
        self._lock = RLock()
        self._epoch: str | None = None
        self._route: int | None = None
        self._reference_end: float | None = None
        self._stop_at: float | None = None
        self._last_end: float | None = None
        self._last_quiet_end: float | None = None
        self._continuous_quiet = 0.0
        # WASAPI process-loopback commonly emits NO PCM buffers while silent.
        # A native host may separately poll its capture packet state; never
        # mistake missing callbacks by themselves for proof of quiet.
        self._idle_checked_at: float | None = None
        self._idle_start_at: float | None = None
        self._idle_poll_sequence: int | None = None
        self._idle_packet_generation: int | None = None
        self._idle_checks = 0
        self._idle_resets = 0
        self._faulted = False
        self._seen: set[str] = set()
        self._observed = 0
        self._rejected = 0

    def _block(self, pcm: bytes) -> tuple[float, int] | None:
        if type(pcm) is not bytes or not 0 < len(pcm) <= self._rate * 2 // 4 or len(pcm) % 2:
            return None
        peak = max(abs(value) for (value,) in struct.iter_unpack("<h", pcm))
        return len(pcm) / (2 * self._rate), peak

    def arm_reference(
        self,
        epoch: str,
        *,
        route_generation: int,
        pcm16le: bytes,
        captured_at: float,
        observed_at: float,
        isolated_capture_running: bool,
    ) -> bool:
        """Confirm an audible pre-stop reference from the SAME trusted capture.

        A whole-endpoint loopback containing game audio must NOT be marked
        'isolated'. Without a nonzero reference the gate cannot distinguish
        an unplugged/disabled capture from a quiet stream.
        """
        block = self._block(pcm16le)
        if (
            type(epoch) is not str
            or _EPOCH.fullmatch(epoch) is None
            or type(route_generation) is not int
            or route_generation < 0
            or not _finite(captured_at)
            or not _finite(observed_at)
            or isolated_capture_running is not True
            or block is None
        ):
            return False
        duration, peak = block
        end = captured_at + duration
        if peak <= max(512, self._peak_limit * 4) or not end <= observed_at + 0.005 or observed_at - end > 0.25:
            return False
        with self._lock:
            if self._faulted or self._epoch is not None or epoch in self._seen or len(self._seen) >= 4096:
                return False
            self._epoch = epoch
            self._route = route_generation
            self._reference_end = end
            self._seen.add(epoch)
            return True

    def begin_stop(self, epoch: str, *, route_generation: int, stopped_at: float) -> bool:
        """Start verifying AFTER the host has revoked the epoch and aborted PCM."""
        if not _finite(stopped_at):
            return False
        with self._lock:
            if (
                self._faulted
                or self._epoch != epoch
                or self._stop_at is not None
                or self._route != route_generation
                or self._reference_end is None
                or not 0 <= stopped_at - self._reference_end <= 0.6
            ):
                return False
            self._stop_at = float(stopped_at)
            return True

    def ingest(
        self,
        epoch: str,
        *,
        route_generation: int,
        pcm16le: bytes,
        captured_at: float,
        observed_at: float,
        isolated_capture_running: bool,
    ) -> bool:
        """Measure consecutive post-stop PCM blocks; missing frames break proof.

        Returns True only when a full window of observed audio is quiet, but
        the final host handoff still requires ready() and independent gates.
        """
        block = self._block(pcm16le)
        with self._lock:
            if epoch != self._epoch or self._stop_at is None or self._faulted:
                return False
            if (
                route_generation != self._route
                or isolated_capture_running is not True
                or block is None
                or not _finite(captured_at)
                or not _finite(observed_at)
            ):
                self._faulted = True
                self._rejected += 1
                return False
            duration, peak = block
            end = captured_at + duration
            if (
                captured_at < self._stop_at
                or end > observed_at + 0.005
                or observed_at - end > 0.25
                or (self._last_end is not None and captured_at < self._last_end - 0.002)
            ):
                self._faulted = True
                self._rejected += 1
                return False
            if self._last_end is not None and captured_at - self._last_end > 0.002:
                self._continuous_quiet = 0.0  # missing capture must not count
                self._last_quiet_end = None
            # Any PCM callback invalidates a previously quiet no-packet poll
            # window. The next poll must begin a fresh uninterrupted interval.
            if self._idle_checked_at is not None:
                self._idle_resets += 1
            self._idle_checked_at = None
            self._idle_start_at = None
            self._idle_poll_sequence = None
            self._idle_packet_generation = None
            previous_end = self._last_end
            self._last_end = end
            self._observed += 1
            if peak > self._peak_limit:
                self._continuous_quiet = 0.0
                self._last_quiet_end = None
                return False
            overlap = max(0.0, (previous_end or captured_at) - captured_at)
            self._continuous_quiet += duration - overlap
            self._last_quiet_end = end
            return self._continuous_quiet + 1e-9 >= self._quiet_s

    def observe_no_packet_poll(
        self,
        epoch: str,
        *,
        route_generation: int,
        checked_at: float,
        poll_sequence: int,
        packet_generation: int,
        isolated_capture_running: bool,
        voice_process_identity_pinned: bool,
        no_pending_capture_packet: bool,
    ) -> bool:
        """Observe trusted native capture polling when WASAPI emits no silence.

        The host MUST poll the native capture client and a lifetime-pinned,
        isolated voice process (not whole-endpoint audio). packet_generation
        must count *all* native PCM callbacks, including packets already read.
        Polls spaced >80ms break the observation window. No callback alone is
        NOT proof: health, fresh polling, exact route/identity, prior audible
        reference and native-abort/avatar gates are all mandatory.

        This is a digital best-effort witness, never physical-silence proof.
        """
        with self._lock:
            if epoch != self._epoch or self._stop_at is None or self._faulted:
                return False
            if (
                type(route_generation) is not int
                or route_generation != self._route
                or not _finite(checked_at)
                or checked_at < self._stop_at
                or type(poll_sequence) is not int
                or not 0 <= poll_sequence < 2**63
                or type(packet_generation) is not int
                or not 0 <= packet_generation < 2**63
                or isolated_capture_running is not True
                or voice_process_identity_pinned is not True
                or type(no_pending_capture_packet) is not bool
            ):
                self._faulted = True
                self._rejected += 1
                return False
            if self._idle_poll_sequence is not None and (
                poll_sequence <= self._idle_poll_sequence
                or checked_at <= (self._idle_checked_at or 0)
                or packet_generation < (self._idle_packet_generation or 0)
            ):
                self._faulted = True
                self._rejected += 1
                return False
            # A pending packet or a new callback since the previous native
            # query breaks the idle window even if the packet is now consumed.
            changed = self._idle_packet_generation is not None and packet_generation != self._idle_packet_generation
            gap = self._idle_checked_at is not None and checked_at - self._idle_checked_at > 0.08
            if no_pending_capture_packet is False or changed or gap:
                self._idle_start_at = None
                self._idle_resets += 1
                # A known packet or fresh callback invalidates a quiet PCM
                # window as well, even when the native host consumed it before
                # this Python witness received an ingest() call.
                if no_pending_capture_packet is False or changed:
                    self._continuous_quiet = 0.0
                    self._last_quiet_end = None
            self._idle_checked_at = float(checked_at)
            self._idle_poll_sequence = poll_sequence
            self._idle_packet_generation = packet_generation
            self._idle_checks += 1
            if no_pending_capture_packet is False:
                return False
            if self._idle_start_at is None:
                self._idle_start_at = float(checked_at)
                return False
            return checked_at - self._idle_start_at + 1e-9 >= self._quiet_s

    def ready(
        self,
        epoch: str,
        *,
        route_generation: int,
        now: float,
        capture_isolated_and_healthy: bool,
        native_abort_confirmed: bool,
        avatar_neutral_confirmed: bool,
    ) -> bool:
        """True only for a fresh captured window AND separate host checks.

        Do not derive the three host booleans from model text, output queue
        counters, or assumptions about playback.
        """
        with self._lock:
            return bool(
                not self._faulted
                and epoch == self._epoch
                and self._stop_at is not None
                and route_generation == self._route
                and _finite(now)
                and (
                    (
                        self._last_quiet_end is not None
                        and self._continuous_quiet + 1e-9 >= self._quiet_s
                        and 0 <= now - self._last_quiet_end <= 0.15
                    )
                    or (
                        self._idle_start_at is not None
                        and self._idle_checked_at is not None
                        and self._idle_checked_at - self._idle_start_at + 1e-9 >= self._quiet_s
                        and 0 <= now - self._idle_checked_at <= 0.03
                    )
                )
                and capture_isolated_and_healthy is True
                and native_abort_confirmed is True
                and avatar_neutral_confirmed is True
            )

    def retire(self, epoch: str) -> None:
        """One-way epoch expiry; stale samples cannot authorize new speech."""
        with self._lock:
            if epoch == self._epoch:
                self._epoch = None
                self._route = None
                self._reference_end = None
                self._stop_at = None
                self._last_end = None
                self._last_quiet_end = None
                self._continuous_quiet = 0.0
                self._idle_checked_at = None
                self._idle_start_at = None
                self._idle_poll_sequence = None
                self._idle_packet_generation = None

    def metrics(self) -> dict[str, bool | int]:
        """Privacy-preserving: no epoch strings, routes, raw PCM or timestamps."""
        with self._lock:
            return {
                "active": self._epoch is not None,
                "faulted": self._faulted,
                "observed_blocks": self._observed,
                "rejected_blocks": self._rejected,
                "used_epochs": len(self._seen),
                "idle_checks": self._idle_checks,
                "idle_resets": self._idle_resets,
            }


__all__ = ["IsolatedLoopbackQuietWitness"]
