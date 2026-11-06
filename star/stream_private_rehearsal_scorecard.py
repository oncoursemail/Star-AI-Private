"""Cross-system, read-only acceptance checklist for a PRIVATE Star gaming VTuber rehearsal.

Composes independently produced reports instead of inferring that separate
subsystems working in isolation imply an end-to-end success. No raw footage,
chat, player names, file paths, secret signing keys or sound are retained.

All objects and same-session assertions must originate from a trusted LOCAL
host. Python dataclasses, HMAC receipts, and booleans are not remote identity
or hardware attestation. Candidate means MANUAL review only, never broadcast,
game control, autonomous promotion, or proof of humanlike behavior.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import math

from .game_state_transition_witness import AttestedGameMoment
from .native_game_roundtrip_audit import NativeRoundtripReport
from .stream_av_recording_host import RecordingAVResult
from .stream_moment_receipts import verify_game_moment
from .stream_obs_readonly_evidence import ObsCounters
from .stream_obs_recording_artifact_probe import RecordingArtifactReport
from .stream_windows_private_rehearsal_cli import PrivateRehearsalReadiness


@dataclass(frozen=True)
class RehearsalScorecard:
    status: str  # deferred | candidate_for_owner_review
    missing: tuple[str, ...]
    native_actions_completed: int
    observed_native_frames: int
    obs_presented_frames: int
    obs_output_frames: int
    obs_render_drop_pct: float | None
    obs_output_drop_pct: float | None
    av_mouth_lag_ms: int | None
    game_state_receipt_valid: bool
    authorizes_gameplay: bool = False
    authorizes_broadcast: bool = False
    certifies_humanlike_behavior: bool = False
    certifies_game_mastery: bool = False

    def to_json(self) -> str:
        """Only bounded aggregate evidence and fixed non-sensitive reason codes."""
        return json.dumps(asdict(self), separators=(",", ":"), sort_keys=True)


def _obs_window(before: ObsCounters | None, after: ObsCounters | None,
                max_drop_pct: float) -> tuple[int, int, float | None, float | None, str | None]:
    if type(before) is not ObsCounters or type(after) is not ObsCounters:
        return 0, 0, None, None, "obs_counter_window_missing"
    for row in (before, after):
        values = (row.render_total_frames, row.render_skipped_frames,
                  row.output_total_frames, row.output_skipped_frames)
        if (any(type(value) is not int or not 0 <= value <= 10**12 for value in values)
                or type(row.at_monotonic_ms) not in (int, float)
                or not math.isfinite(row.at_monotonic_ms)
                or not 0 <= row.at_monotonic_ms <= 1e13
                or row.render_skipped_frames > row.render_total_frames
                or row.output_skipped_frames > row.output_total_frames):
            return 0, 0, None, None, "obs_counter_window_invalid"
    elapsed = after.at_monotonic_ms - before.at_monotonic_ms
    if not 6000 <= elapsed <= 120000:
        return 0, 0, None, None, "obs_counter_window_duration_invalid"
    changes = (
        after.render_total_frames - before.render_total_frames,
        after.render_skipped_frames - before.render_skipped_frames,
        after.output_total_frames - before.output_total_frames,
        after.output_skipped_frames - before.output_skipped_frames,
    )
    rendered, render_drops, output, output_drops = changes
    if (rendered < 120 or output < 120 or render_drops < 0 or output_drops < 0
            or render_drops > rendered or output_drops > output):
        return 0, 0, None, None, "obs_frame_continuity_missing"
    # The report is for a running, not paused, 8..240 FPS OBS pipeline.
    # Reject unrealistic counter deltas even if their drop percentage is tiny.
    seconds = elapsed / 1000
    if not all(8 <= frames / seconds <= 240 for frames in (rendered, output)):
        return rendered, output, None, None, "obs_frame_rate_outside_rehearsal_bounds"
    render_raw = 100 * render_drops / rendered
    output_raw = 100 * output_drops / output
    render_pct = round(render_raw, 3)
    output_pct = round(output_raw, 3)
    # Never round before making the go/no-go decision at the boundary.
    if render_raw > max_drop_pct or output_raw > max_drop_pct:
        return rendered, output, render_pct, output_pct, "obs_frame_drops_exceeded"
    return rendered, output, render_pct, output_pct, None


def score_private_vtuber_rehearsal(
    *,
    owner_approved: bool = False,
    host_confirms_same_session: bool = False,
    host_confirms_same_recording: bool = False,
    host_confirms_broadcast_inactive: bool = False,
    readiness: PrivateRehearsalReadiness | None = None,
    native: NativeRoundtripReport | None = None,
    game_moment: AttestedGameMoment | None = None,
    receipt_session_id: str | None = None,
    receipt_key: bytes | None = None,
    recording: RecordingArtifactReport | None = None,
    av: RecordingAVResult | None = None,
    obs_before: ObsCounters | None = None,
    obs_after: ObsCounters | None = None,
    minimum_gpu_free_mib: int = 1024,
    max_obs_drop_pct: float = 2.0,
    max_native_p95_ms: float = 1000.0,
) -> RehearsalScorecard:
    """Inspect correlated HOST reports for a private rehearsal, never deploy.

    Real host must separately verify file identity/origin and session scope,
    the trusted game telemetry source, stopped private recording, and that OBS
    never streamed. A model or viewer MUST NOT supply these inputs. Individual
    report constructors can be forged; even a positive result is advisory.
    """
    if owner_approved is not True:
        raise PermissionError("local owner-approved private review required")
    if any(type(flag) is not bool for flag in (
        host_confirms_same_session, host_confirms_same_recording,
        host_confirms_broadcast_inactive,
    )):
        raise ValueError("host witness flags must be explicit booleans")
    if type(minimum_gpu_free_mib) is not int or not 256 <= minimum_gpu_free_mib <= 32768:
        raise ValueError("invalid conservative GPU headroom threshold")
    if (type(max_obs_drop_pct) not in (int, float)
            or not math.isfinite(max_obs_drop_pct)
            or not 0 <= max_obs_drop_pct <= 10):
        raise ValueError("invalid OBS frame-drop threshold")
    if (type(max_native_p95_ms) not in (int, float)
            or not math.isfinite(max_native_p95_ms)
            or not 100 <= max_native_p95_ms <= 5000):
        raise ValueError("invalid native roundtrip threshold")

    missing: list[str] = []
    if not host_confirms_same_session:
        missing.append("host_session_correlation_missing")
    if not host_confirms_same_recording:
        missing.append("host_recording_identity_missing")
    if not host_confirms_broadcast_inactive:
        missing.append("host_private_broadcast_state_missing")

    if (type(readiness) is not PrivateRehearsalReadiness
            or readiness.status != "candidate" or readiness.samples < 3
            or not readiness.stable_processes or not readiness.game_process_pinned
            or type(readiness.min_free_gpu_mib) is not int
            or readiness.min_free_gpu_mib < minimum_gpu_free_mib):
        missing.append("sustained_game_gpu_readiness_missing")

    action_count = 0
    native_frames = 0
    if (type(native) is NativeRoundtripReport
            and native.status == "host_roundtrip_only"
            and native.host_frame_coverage_declared
            and type(native.attempted) is int and type(native.completed) is int
            and type(native.observed_frames) is int and type(native.no_action_frames) is int
            and 1 <= native.completed == native.attempted <= native.observed_frames
            and native.observed_frames == native.attempted + native.no_action_frames
            and native.inference_p95_ms is not None
            and native.native_call_p95_ms is not None
            and native.frame_to_release_p95_ms is not None
            and all(type(ms) in (int, float) and math.isfinite(ms) and 0 <= ms <= max_native_p95_ms
                    for ms in (
                        native.inference_p95_ms, native.native_call_p95_ms,
                        native.frame_to_release_p95_ms,
                    ))
            and native.frame_to_release_p95_ms >= max(
                native.inference_p95_ms, native.native_call_p95_ms
            )):
        action_count, native_frames = native.completed, native.observed_frames
    else:
        missing.append("native_gameplay_frame_and_release_audit_missing")

    game_valid = False
    if (type(game_moment) is AttestedGameMoment
            and type(receipt_session_id) is str
            and type(receipt_key) is bytes
            and game_moment.moment.kind in {"win", "loss", "checkpoint"}
            and type(game_moment.now_s) in (int, float)
            and math.isfinite(game_moment.now_s)
            and 0 <= game_moment.now_s - game_moment.moment.at_s <= 5):
        try:
            game_valid = verify_game_moment(
                game_moment.moment, game_moment.receipt,
                session_id=receipt_session_id, key=receipt_key,
            )
        except (TypeError, ValueError):
            game_valid = False
    if not game_valid:
        missing.append("corroborated_game_state_receipt_missing")

    if (type(recording) is not RecordingArtifactReport
            or recording.status != "candidate_for_owner_review"
            or recording.local_media_decoded is not True
            or recording.video_frames < 180 or recording.audio_streams < 1
            or recording.broadcast_authorized is not False):
        missing.append("decoded_private_obs_recording_missing")

    if (type(av) is not RecordingAVResult
            or av.report.verdict != "eligible_for_owner_review"
            or av.captured_output_attested is not True
            or av.isolated_star_audio_attested is not True
            or av.observed_frames < 180
            or type(recording) is not RecordingArtifactReport
            or av.audio_track != recording.selected_audio_track):
        missing.append("audible_star_avatar_alignment_missing")

    rendered, output, render_drop, output_drop, obs_gap = _obs_window(
        obs_before, obs_after, float(max_obs_drop_pct)
    )
    if obs_gap is not None:
        missing.append(obs_gap)

    return RehearsalScorecard(
        status="deferred" if missing else "candidate_for_owner_review",
        missing=tuple(missing),
        native_actions_completed=action_count,
        observed_native_frames=native_frames,
        obs_presented_frames=rendered,
        obs_output_frames=output,
        obs_render_drop_pct=render_drop,
        obs_output_drop_pct=output_drop,
        av_mouth_lag_ms=(av.report.estimated_mouth_lag_ms
                         if type(av) is RecordingAVResult else None),
        game_state_receipt_valid=game_valid,
    )


__all__ = ["RehearsalScorecard", "score_private_vtuber_rehearsal"]
