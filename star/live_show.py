"""Bounded offline episode planning; no generation, moderation, or broadcasting.

PASS/APPROVED records are caller-supplied evidence, not authenticated reviewers,
permission grants, or proof of subjective quality. Asset/voice IDs are references;
this module does not inspect media, licenses, or the referenced asset contents.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from enum import Enum
import hashlib
import json
import math
from pathlib import Path
import re
import time


MAX_BYTES = 524_288
MAX_DURATION = 1800
REQUIRED_CHECKS = frozenset({"canon", "visual_identity", "voice_identity", "timing", "editorial"})
ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}\Z")
EVIDENCE_NOTE = "Provided evidence only; no reviewer authentication, permission grant, or quality guarantee."


class ValidationError(ValueError):
    """Input cannot be represented by the bounded planning schema."""


def _fields(value: object, required: set[str]) -> dict:
    if not isinstance(value, dict) or set(value) != required:
        raise ValidationError(f"Expected exactly these fields: {', '.join(sorted(required))}")
    return value


def _items(value: object, name: str, maximum: int, minimum: int = 0) -> list:
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise ValidationError(f"{name} must contain {minimum} to {maximum} items")
    return value


def _text(value: object, name: str, maximum: int = 2000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValidationError(f"Invalid {name}")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValidationError(f"Invalid UTF-8 in {name}") from exc
    return value


def _identifier(value: object) -> str:
    if not isinstance(value, str) or ID_PATTERN.fullmatch(value) is None:
        raise ValidationError("IDs must be 1-64 lowercase letters, digits, dots, underscores, or hyphens")
    return value


def _number(value: object, name: str, maximum: float = 1e12) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(f"{name} must be a finite nonnegative number")
    try:
        result = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValidationError(f"Invalid {name}") from exc
    if not math.isfinite(result) or not 0 <= result <= maximum:
        raise ValidationError(f"{name} must be finite and between 0 and {maximum}")
    return result


def _unique(values: list[str], name: str) -> None:
    if len(values) != len(set(values)):
        raise ValidationError(f"Duplicate {name}")


def _object(pairs: list[tuple[str, object]]) -> dict:
    result: dict = {}
    for key, value in pairs:
        if key in result:
            raise ValidationError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _constant(value: str) -> None:
    raise ValidationError(f"Non-finite JSON constant: {value}")


def _json(raw: bytes) -> object:
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_BYTES:
        raise ValidationError(f"Input must be 1-{MAX_BYTES} bytes")
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_object, parse_constant=_constant)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise ValidationError(f"Invalid JSON: {exc}") from exc


def _read_bounded(path: Path) -> bytes:
    with path.open("rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValidationError(f"Input exceeds {MAX_BYTES} bytes")
    return raw


@dataclass(frozen=True)
class CastMember:
    character_id: str
    asset_id: str
    voice_id: str


@dataclass(frozen=True)
class Line:
    line_id: str
    speaker_id: str
    text: str
    offset_seconds: float
    duration_seconds: float


@dataclass(frozen=True)
class Shot:
    shot_id: str
    set_asset_id: str
    start_seconds: float
    duration_seconds: float
    cast_ids: tuple[str, ...]
    dialogue: tuple[Line, ...]


@dataclass(frozen=True)
class Episode:
    sha256: str
    show_id: str
    episode_id: str
    canon_version: str
    title: str
    cast: tuple[CastMember, ...]
    shots: tuple[Shot, ...]
    duration_seconds: float


def parse_manifest(raw: bytes) -> Episode:
    """Validate strict JSON and hash its exact bytes, including whitespace."""
    data = _fields(_json(raw), {"schema_version", "show_id", "episode_id", "canon_version", "title", "cast", "shots"})
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise ValidationError("Only schema_version 1 is supported")
    identifiers = [_identifier(data[key]) for key in ("show_id", "episode_id", "canon_version")]
    cast = []
    for member in _items(data["cast"], "cast", 16, 1):
        member = _fields(member, {"character_id", "asset_id", "voice_id"})
        cast.append(CastMember(*(_identifier(member[key]) for key in ("character_id", "asset_id", "voice_id"))))
    _unique([member.character_id for member in cast], "character IDs")
    known = {member.character_id for member in cast}
    shots, line_ids = [], []
    cursor = 0.0
    for row in _items(data["shots"], "shots", 120, 1):
        row = _fields(row, {"shot_id", "set_asset_id", "start_seconds", "duration_seconds", "cast_ids", "dialogue"})
        start = _number(row["start_seconds"], "shot start", MAX_DURATION)
        duration = _number(row["duration_seconds"], "shot duration", MAX_DURATION)
        if not math.isclose(start, cursor, rel_tol=0, abs_tol=1e-6) or start + duration > MAX_DURATION:
            raise ValidationError("Shots must form a contiguous, ordered timeline of at most 1800 seconds")
        present = [_identifier(item) for item in _items(row["cast_ids"], "shot cast", 16)]
        _unique(present, "shot cast IDs")
        if not set(present) <= known:
            raise ValidationError("Shot references an unknown character")
        lines, last_offset = [], 0.0
        for row_line in _items(row["dialogue"], "dialogue", 100):
            row_line = _fields(row_line, {"line_id", "speaker_id", "text", "offset_seconds", "duration_seconds"})
            speaker = _identifier(row_line["speaker_id"])
            offset = _number(row_line["offset_seconds"], "line offset", MAX_DURATION)
            length = _number(row_line["duration_seconds"], "line duration", MAX_DURATION)
            if speaker not in present or offset < last_offset or offset + length > duration:
                raise ValidationError("Dialogue speaker must be present and lines must be ordered within the shot")
            line_id = _identifier(row_line["line_id"])
            line_ids.append(line_id)
            if len(line_ids) > 500:
                raise ValidationError("Episode exceeds 500 dialogue lines")
            lines.append(Line(line_id, speaker, _text(row_line["text"], "dialogue"), offset, length))
            last_offset = offset
        shots.append(Shot(_identifier(row["shot_id"]), _identifier(row["set_asset_id"]), start, duration,
                          tuple(present), tuple(lines)))
        cursor = start + duration
    _unique([shot.shot_id for shot in shots], "shot IDs")
    _unique(line_ids, "line IDs")
    return Episode(hashlib.sha256(raw).hexdigest(), *identifiers, _text(data["title"], "title", 200),
                   tuple(cast), tuple(shots), cursor)


def assess_readiness(episode: Episode, reviews: object) -> dict:
    """HOLD on missing, duplicate, unknown, rejected, or stale supplied evidence."""
    reasons, seen = [], set()
    try:
        for review in _items(reviews, "reviews", len(REQUIRED_CHECKS)):
            review = _fields(review, {"check", "manifest_sha256", "result"})
            check = _text(review["check"], "check", 64)
            if check not in REQUIRED_CHECKS or check in seen:
                reasons.append("Unknown or duplicate check")
            seen.add(check)
            if review["result"] != "PASS" or review["manifest_sha256"] != episode.sha256:
                reasons.append(f"Non-PASS or stale evidence for {check}")
    except ValidationError as exc:
        reasons.append(str(exc))
    missing = REQUIRED_CHECKS - seen
    if missing:
        reasons.append("Missing checks: " + ", ".join(sorted(missing)))
    if episode.duration_seconds == 0:
        reasons.append("Episode has no playout duration")
    return {"status": "HOLD" if reasons else "READY", "reasons": reasons, "evidence_note": EVIDENCE_NOTE}


def assess_throughput(accepted_seconds: float, wall_seconds: float, buffer_seconds: float = 0,
                      new_content_duty_cycle: float = 1, headroom: float = 0.25) -> dict:
    """Caller must supply actually accepted media seconds, not attempts or frames."""
    accepted = _number(accepted_seconds, "accepted seconds")
    wall = _number(wall_seconds, "wall seconds")
    buffer = _number(buffer_seconds, "buffer seconds")
    duty = _number(new_content_duty_cycle, "new-content duty cycle", 1)
    reserve = _number(headroom, "headroom", 10)
    if wall == 0:
        raise ValidationError("Wall seconds must be positive")
    rate = accepted / wall
    if not math.isfinite(rate):
        raise ValidationError("Throughput overflow")
    drain = buffer / (duty - rate) if rate < duty else None
    if drain is not None and not math.isfinite(drain):
        raise ValidationError("Buffer estimate overflow")
    return {"accepted_seconds_per_wall_second": rate, "target_with_headroom": duty * (1 + reserve),
            "meets_target": rate >= duty * (1 + reserve), "buffer_drain_seconds": drain,
            "basis": "Caller-supplied measurements; not independently verified; constant-rate projection."}


def estimate_cost(price_per_second: float, new_seconds: float, paid_take_multiplier: float = 1) -> float:
    """Generation-only USD estimate; paid rejected takes count in the multiplier."""
    price = _number(price_per_second, "price per second")
    seconds = _number(new_seconds, "new seconds")
    takes = _number(paid_take_multiplier, "paid take multiplier", 1000)
    if takes < 1:
        raise ValidationError("Paid take multiplier must be at least 1")
    return price * seconds * takes


def text_digest(text: str) -> str:
    return hashlib.sha256(_text(text, "question", 500).encode("utf-8")).hexdigest()


def select_questions(episode: Episode, records: object, now: float, limit: int = 3) -> list[dict]:
    """Select from supplied external moderation records; never execute question text.

    Approval evidence is neither authenticated nor a moderation classifier.
    A record is scoped to the episode bytes and expires after at most one hour.
    Conflicting or invalid versions invalidate that question ID for the batch.
    Inspect all bounded records before applying the selection limit.
    """
    now = _number(now, "current Unix time")
    if type(limit) is not int or not 1 <= limit <= 5:
        raise ValidationError("Question limit must be 1-5")
    by_id, invalid_ids = {}, set()
    for candidate in _items(records, "questions", 100):
        if not isinstance(candidate, dict):
            continue
        try:
            question_id = _identifier(candidate.get("question_id"))
        except ValidationError:
            continue
        try:
            item = _fields(candidate, {"question_id", "show_id", "episode_id", "manifest_sha256", "text",
                                       "approved_text_sha256", "moderation_status", "approved_at", "expires_at"})
            digest = text_digest(item["text"])
            approved = _number(item["approved_at"], "approval time")
            expires = _number(item["expires_at"], "expiry time")
            if (item["moderation_status"] != "APPROVED" or item["approved_text_sha256"] != digest
                    or item["show_id"] != episode.show_id or item["episode_id"] != episode.episode_id
                    or item["manifest_sha256"] != episode.sha256 or not approved <= now < expires
                    or not 0 < expires - approved <= 3600):
                invalid_ids.add(question_id)
                continue
            if question_id in by_id and by_id[question_id] != item:
                invalid_ids.add(question_id)
            else:
                by_id[question_id] = item
        except ValidationError:
            invalid_ids.add(question_id)

    selected, seen_text = [], set()
    for question_id, item in by_id.items():
        if question_id in invalid_ids:
            continue
        normalized = " ".join(item["text"].casefold().split())
        if normalized in seen_text:
            continue
        seen_text.add(normalized)
        selected.append({"question_id": question_id, "text": item["text"],
                         "text_sha256": text_digest(item["text"])})
        if len(selected) == limit:
            break
    return selected


class PlayoutDecision(str, Enum):
    EPISODE = "EPISODE"
    Q_AND_A = "Q_AND_A"
    INTERMISSION = "INTERMISSION"


def decide_playout(episode: Episode | None, reviews: object, questions: object = None,
                   *, post_episode: bool = False, now: float = 0) -> PlayoutDecision:
    """Offline recommendation only; no stream lifecycle or permission changes."""
    if type(post_episode) is not bool:
        raise ValidationError("post_episode must be a boolean")
    if episode is None:
        return PlayoutDecision.INTERMISSION
    if post_episode:
        if select_questions(episode, [] if questions is None else questions, now):
            return PlayoutDecision.Q_AND_A
        return PlayoutDecision.INTERMISSION
    if assess_readiness(episode, reviews)["status"] == "READY":
        return PlayoutDecision.EPISODE
    return PlayoutDecision.INTERMISSION


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--reviews", type=Path)
    parser.add_argument("--questions", type=Path)
    parser.add_argument("--post-episode", action="store_true")
    parser.add_argument("--accepted-seconds", type=float)
    parser.add_argument("--wall-seconds", type=float)
    parser.add_argument("--buffer-seconds", type=float, default=0)
    parser.add_argument("--duty-cycle", type=float, default=1)
    parser.add_argument("--headroom", type=float, default=0.25)
    parser.add_argument("--price-per-second", type=float)
    parser.add_argument("--paid-take-multiplier", type=float, default=1)
    args = parser.parse_args(argv)
    try:
        episode = parse_manifest(_read_bounded(args.manifest))
        reviews = _json(_read_bounded(args.reviews)) if args.reviews else []
        questions = _json(_read_bounded(args.questions)) if args.questions else []
        now = time.time()
        metrics = None
        if (args.accepted_seconds is None) != (args.wall_seconds is None):
            raise ValidationError("Supply both --accepted-seconds and --wall-seconds")
        if args.accepted_seconds is not None:
            metrics = assess_throughput(args.accepted_seconds, args.wall_seconds, args.buffer_seconds,
                                        args.duty_cycle, args.headroom)
        cost = None if args.price_per_second is None else estimate_cost(
            args.price_per_second, episode.duration_seconds, args.paid_take_multiplier)
        report = {"simulation": True, "broadcasting": False, "generated_media": False,
                  "manifest": asdict(episode), "readiness": assess_readiness(episode, reviews),
                  "playout_recommendation": decide_playout(episode, reviews, questions,
                                                           post_episode=args.post_episode, now=now).value,
                  "selected_questions": select_questions(episode, questions, now) if args.post_episode else [],
                  "throughput": metrics, "generation_only_cost_usd": cost,
                  "limitations": [EVIDENCE_NOTE, "No model, renderer, YouTube, or live chat integration.",
                                  "No actual media, subjective quality, asset content, or license validation.",
                                  "Null cost/throughput means no inputs supplied; no sample measurements invented."]}
        print(json.dumps(report, indent=2, allow_nan=False))
        return 0
    except (OSError, ValidationError) as exc:
        print(json.dumps({"simulation": True, "broadcasting": False, "generated_media": False, "error": str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
