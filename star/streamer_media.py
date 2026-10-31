"""Local-only voice-motion envelopes and non-destructive highlight edit plans.

No audio capture, TTS generation, video decoding, FFmpeg invocation, uploads,
accounts or broadcasting. These functions accept already-authorized data from
a trusted host and never infer wins, consent, laughter or rights from a filename.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from struct import iter_unpack
import re

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,119}\Z")
MAX_PCM_SECONDS = 30
ALLOWED_SAMPLE_RATES = frozenset({16000, 24000, 48000})


@dataclass(frozen=True)
class VocalRegion:
    """An externally verified vocal category; audio RMS alone cannot classify laughter."""
    kind: str   # speech | laugh | purr | meow | woof
    start_ms: int
    end_ms: int


@dataclass(frozen=True)
class AudioMotionFrame:
    at_ms: int
    amplitude: float
    speech: float
    laughter: float
    animal_sound: str = ""


def audio_motion_frames(
    pcm16_mono: bytes, sample_rate: int, regions: tuple[VocalRegion, ...] = (),
    *, hop_ms: int = 20,
) -> list[AudioMotionFrame]:
    """Convert PCM16LE into time-aligned motion envelopes.

    PCM must come from a permission-checked, known play-out path. VocalRegion
    labels come from that trusted host, not chat prompts or text-to-speech tags.
    Audio times refer to the returned audio buffer, not the wall clock; the
    renderer aligns them with actual playout timestamps, and drops stale frames.
    """
    if type(sample_rate) is not int or sample_rate not in ALLOWED_SAMPLE_RATES:
        raise ValueError("Unsupported PCM sampling rate")
    if type(hop_ms) is not int or not 10 <= hop_ms <= 50 or 1000 % hop_ms:
        raise ValueError("Unsupported envelope interval")
    if not isinstance(pcm16_mono, bytes) or len(pcm16_mono) % 2 != 0 \
            or not pcm16_mono or len(pcm16_mono) > MAX_PCM_SECONDS * sample_rate * 2:
        raise ValueError("Expected bounded, nonempty mono PCM16LE bytes")
    duration_ms = len(pcm16_mono) * 500 // sample_rate
    ordered: list[VocalRegion] = []
    for region in regions:
        if not isinstance(region, VocalRegion) or not isinstance(region.kind, str) or region.kind not in {
            "speech", "laugh", "purr", "meow", "woof"
        } or type(region.start_ms) is not int or type(region.end_ms) is not int \
                or not 0 <= region.start_ms < region.end_ms <= duration_ms + 1:
            raise ValueError("Invalid verified vocal region")
        ordered.append(region)
    samples_per_hop = sample_rate * hop_ms // 1000
    samples = len(pcm16_mono) // 2
    out: list[AudioMotionFrame] = []
    # RMS window is calculated from ACTUAL encoded audio, not from letters.
    for begin in range(0, samples, samples_per_hop):
        end = min(samples, begin + samples_per_hop)
        window = pcm16_mono[begin * 2:end * 2]
        squares = sum((v[0] / 32768.0) ** 2 for v in iter_unpack("<h", window))
        amplitude = min(1.0, sqrt(squares / (end - begin)) * 3.0)
        timestamp = begin * 1000 // sample_rate
        active = [r.kind for r in ordered if r.start_ms <= timestamp < r.end_ms]
        out.append(AudioMotionFrame(
            at_ms=timestamp,
            amplitude=round(amplitude, 5),
            speech=round(amplitude, 5) if "speech" in active else 0.0,
            laughter=round(amplitude, 5) if "laugh" in active else 0.0,
            animal_sound=next((kind for kind in ("purr", "meow", "woof") if kind in active), ""),
        ))
    return out


@dataclass(frozen=True)
class VerifiedRecording:
    recording_id: str
    duration_ms: int
    host_verified: bool
    # A host must verify the real playable file and audio track independently.


@dataclass(frozen=True)
class VerifiedMoment:
    moment_id: str
    start_ms: int
    end_ms: int
    evidence_id: str
    score: float
    category: str  # discovery | funny | achievement | setback | conversation
    rights_cleared: bool = False
    privacy_cleared: bool = False


@dataclass(frozen=True)
class TimelineCut:
    recording_id: str
    moment_id: str
    evidence_id: str
    source_start_ms: int
    source_end_ms: int
    category: str


@dataclass(frozen=True)
class EditDecisionList:
    aspect: str
    cuts: tuple[TimelineCut, ...]
    output_duration_ms: int
    # A non-destructive sequence of source intervals, NOT a rendered export.


def plan_highlights(
    recording: VerifiedRecording, moments: tuple[VerifiedMoment, ...], *,
    aspect: str = "landscape", budget_ms: int = 90_000, min_score: float = 0.5,
    context_ms: int = 1000,
) -> EditDecisionList:
    """Rank evidenced, reviewed moments and make an ordered non-overlapping EDL.

    A valid plan can still make a bad video. It must be manually reviewed for
    story/editing quality, private information, captions and music rights before
    any FFmpeg assembly or public post. source times always refer to one
    separately verified recording.
    """
    if not isinstance(recording, VerifiedRecording) or recording.host_verified is not True \
            or not isinstance(recording.recording_id, str) \
            or not _ID.fullmatch(recording.recording_id) \
            or type(recording.duration_ms) is not int or not 1000 <= recording.duration_ms <= 86_400_000:
        raise ValueError("A real verified source recording is required")
    if not isinstance(aspect, str) or aspect not in {"landscape", "portrait"}:
        raise ValueError("Unknown output aspect")
    if type(budget_ms) is not int or not 1000 <= budget_ms <= 3_600_000:
        raise ValueError("Invalid output duration budget")
    if type(context_ms) is not int or not 0 <= context_ms <= 10000:
        raise ValueError("Invalid edit context")
    if not isinstance(min_score, (int, float)) or not 0 <= min_score <= 1:
        raise ValueError("Invalid minimum quality score")
    valid: list[VerifiedMoment] = []
    seen: set[str] = set()
    for m in moments:
        if not isinstance(m, VerifiedMoment) or not isinstance(m.moment_id, str) \
                or not _ID.fullmatch(m.moment_id) or not isinstance(m.evidence_id, str) \
                or not _ID.fullmatch(m.evidence_id) or m.moment_id in seen \
                or type(m.start_ms) is not int or type(m.end_ms) is not int \
                or not 0 <= m.start_ms < m.end_ms <= recording.duration_ms \
                or not isinstance(m.category, str) or m.category not in {"discovery", "funny", "achievement", "setback", "conversation"} \
                or not isinstance(m.score, (int, float)) or not 0 <= m.score <= 1:
            raise ValueError("Invalid, duplicate or out-of-range moment")
        seen.add(m.moment_id)
        if m.rights_cleared is True and m.privacy_cleared is True and m.score >= min_score:
            valid.append(m)
    selected: list[TimelineCut] = []
    used = 0
    for m in sorted(valid, key=lambda item: (-item.score, item.start_ms)):
        start = max(0, m.start_ms - context_ms)
        end = min(recording.duration_ms, m.end_ms + context_ms)
        if any(start < cut.source_end_ms and end > cut.source_start_ms for cut in selected):
            continue
        if used + (end - start) > budget_ms:
            start, end = m.start_ms, m.end_ms  # drop optional context first
            if used + (end - start) > budget_ms \
                    or any(start < c.source_end_ms and end > c.source_start_ms for c in selected):
                continue
        selected.append(TimelineCut(recording.recording_id, m.moment_id, m.evidence_id,
                                    start, end, m.category))
        used += end - start
    selected.sort(key=lambda cut: cut.source_start_ms)
    return EditDecisionList(aspect, tuple(selected), used)
