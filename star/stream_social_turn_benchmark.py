"""Offline, privacy-minimal natural conversation evaluation for STAR streams.

A fast first token is not a natural turn. Independently reviewed, matched
A/B moments must also measure audible response delay, unnecessary overlap,
real owner interruptions, incidental-noise false interruptions, and silence
in a critical game. This does not ingest audio, operate OBS, control games,
or authenticate the host/reviewer. Never an authorization to stream.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Iterable, cast

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
SCENARIOS = (
    "viewer_question", "gameplay_commentary", "owner_barge_in",
    "incidental_noise", "critical_gameplay",
)


def _millis(value: object, field: str) -> float:
    if type(value) not in (float, int):
        raise ValueError(f"{field} requires a finite numeric millisecond interval")
    try:
        out = float(cast(float | int, value))
    except (ValueError, OverflowError) as exc:
        raise ValueError(f"{field} requires a finite numeric millisecond interval") from exc
    if not math.isfinite(out) or not 0 <= out <= 60_000:
        raise ValueError(f"{field} must be within 0..60000ms")
    return out


@dataclass(frozen=True)
class SocialTurnMoment:
    """A pre-registered A/B scenario reviewed outside the speaking model.

    first_audible_ms: event end -> independently recorded first audible PCM;
    overlap_ms: viewer/STAR overlapping speech captured from actual playback;
    playback_stop_ms: confirmed barge-in -> actual audible playback cessation.
    For critical_gameplay, first_audible_ms denotes *unnecessary* speech.
    These are relative durations, not sensitive timestamps or text content.
    """

    case_id: str
    variant: str
    scenario: str
    first_audible_ms: float | None = None
    overlap_ms: float | None = None
    interrupted: bool = False
    playback_stop_ms: float | None = None
    grounded: bool = True
    independently_reviewed: bool = False
    # Independently reviewed longest UNPLANNED gap during audible playback.
    # Optional until the streaming host records annotated PCM gap evidence.
    max_unplanned_gap_ms: float | None = None

    def __post_init__(self) -> None:
        if type(self.case_id) is not str or _ID.fullmatch(self.case_id) is None:
            raise ValueError("bounded opaque case ID required")
        if type(self.variant) is not str or self.variant not in {"baseline", "candidate"}:
            raise ValueError("variant must be baseline or candidate")
        if type(self.scenario) is not str or self.scenario not in SCENARIOS:
            raise ValueError("scenario must be pre-registered")
        for name in ("interrupted", "grounded", "independently_reviewed"):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} must be boolean")
        if self.first_audible_ms is not None:
            _millis(self.first_audible_ms, "first_audible_ms")
        if self.overlap_ms is not None:
            _millis(self.overlap_ms, "overlap_ms")
        if self.playback_stop_ms is not None:
            _millis(self.playback_stop_ms, "playback_stop_ms")
        if self.max_unplanned_gap_ms is not None:
            _millis(self.max_unplanned_gap_ms, "max_unplanned_gap_ms")
            if (self.scenario not in ("viewer_question", "gameplay_commentary")
                    or self.first_audible_ms is None):
                raise ValueError("playback gap needs an audible, reviewed speech case")
        if self.scenario in ("viewer_question", "gameplay_commentary"):
            if self.interrupted or self.playback_stop_ms is not None:
                raise ValueError("ordinary speech cases cannot claim barge-in")
            if (self.first_audible_ms is None) != (self.overlap_ms is None):
                raise ValueError("audible speech and measured overlap must occur together")
        elif self.scenario in ("owner_barge_in", "incidental_noise"):
            if self.first_audible_ms is not None or self.overlap_ms is not None:
                raise ValueError("voice-interruption scenarios must not include speech latencies")
            if (self.playback_stop_ms is None) != (not self.interrupted):
                raise ValueError("actual interruption requires a measured playback-stop latency")
            if not self.grounded:
                raise ValueError("grounding rubric applies only to speech cases")
        else:
            if self.overlap_ms is not None or self.playback_stop_ms is not None or self.interrupted:
                raise ValueError("critical gameplay only measures unnecessary speech")
            if not self.grounded:
                raise ValueError("grounding rubric applies only to speech cases")


@dataclass(frozen=True)
class SocialTurnReport:
    status: str
    reason: str
    complete_pairs: int
    reviewed_moments: int
    expected_moments: int
    candidate_failures: int
    new_case_regressions: int
    candidate_false_interruptions: int
    candidate_missed_barge_ins: int
    candidate_critical_speech: int
    candidate_ungrounded_speech: int
    candidate_pair_regressions: int
    baseline_question_p95_ms: float | None
    candidate_question_p95_ms: float | None
    candidate_stop_p95_ms: float | None
    candidate_dropped_commentary: int = 0
    candidate_late_commentary: int = 0
    candidate_stutter_regressions: int = 0
    authorized_to_stream: bool = False
    note: str = ("Offline operator-reviewed timing evidence, not authenticated media, "
                 "human-equivalence proof, automatic model promotion or broadcast permission")


def _p95(values: list[float]) -> float | None:
    if not values:
        return None
    values.sort()
    return round(values[math.ceil(0.95 * len(values)) - 1], 2)


def assess_social_turns(
    moments: Iterable[SocialTurnMoment], *,
    minimum_per_scenario: int = 4,
    max_question_p95_ms: float = 1500,
    max_playback_stop_ms: float = 350,
    max_overlap_ms: float = 150,
    max_question_regression_ms: float = 100,
    max_pair_question_regression_ms: float = 250,
    max_pair_stop_regression_ms: float = 100,
    max_commentary_first_audible_ms: float = 2000,
    max_pair_commentary_regression_ms: float = 500,
    max_unplanned_gap_ms: float = 550,
    max_pair_gap_regression_ms: float = 200,
) -> SocialTurnReport:
    """Conservative A/B gate for a *manual* gaming/VTuber rehearsal.

    Every scenario needs independent baseline and candidate observations.
    Aggregate improvements cannot conceal a newly wrong matched scenario.
    Correct timing does not measure personality quality or consciousness.
    """
    if type(minimum_per_scenario) is not int or not 2 <= minimum_per_scenario <= 100:
        raise ValueError("minimum_per_scenario must be 2..100")
    for name, value in (("max_question_p95_ms", max_question_p95_ms),
                        ("max_playback_stop_ms", max_playback_stop_ms),
                        ("max_overlap_ms", max_overlap_ms),
                        ("max_question_regression_ms", max_question_regression_ms),
                        ("max_pair_question_regression_ms", max_pair_question_regression_ms),
                        ("max_pair_stop_regression_ms", max_pair_stop_regression_ms),
                        ("max_commentary_first_audible_ms", max_commentary_first_audible_ms),
                        ("max_pair_commentary_regression_ms", max_pair_commentary_regression_ms),
                        ("max_unplanned_gap_ms", max_unplanned_gap_ms),
                        ("max_pair_gap_regression_ms", max_pair_gap_regression_ms)):
        if not 0 < _millis(value, name) <= 10_000:
            raise ValueError(f"invalid {name}")
    data: dict[str, dict[str, SocialTurnMoment]] = {}
    for moment in moments:
        if not isinstance(moment, SocialTurnMoment):
            raise TypeError("SocialTurnMoment evidence required")
        if len(data) >= 500 and moment.case_id not in data:
            raise ValueError("at most 500 paired scenarios")
        versions = data.setdefault(moment.case_id, {})
        if moment.variant in versions:
            raise ValueError("duplicate measured variant for one case")
        if versions and next(iter(versions.values())).scenario != moment.scenario:
            raise ValueError("one paired scenario must have the same rubric")
        versions[moment.variant] = moment

    counts = {scenario: 0 for scenario in SCENARIOS}
    baseline_questions: list[float] = []
    candidate_questions: list[float] = []
    candidate_stops: list[float] = []
    candidate_failures = 0
    new_regressions = 0
    pair_regressions = 0
    false_interruptions = missed_barge_ins = critical_speech = ungrounded_speech = 0
    dropped_commentary = late_commentary = stutter_regressions = 0
    incomplete_gap_pairs = False
    coverage = 0
    complete_pairs = 0
    reviewed = 0

    def good(w: SocialTurnMoment) -> bool:
        if not w.independently_reviewed:
            return False
        if w.scenario == "viewer_question":
            return (w.first_audible_ms is not None and
                    w.first_audible_ms <= max_question_p95_ms and
                    w.overlap_ms is not None and w.overlap_ms <= max_overlap_ms
                    and w.grounded and
                    (w.max_unplanned_gap_ms is None or
                     w.max_unplanned_gap_ms <= max_unplanned_gap_ms))
        if w.scenario == "gameplay_commentary":
            # A speech-expected commentary moment is different from an
            # explicitly silent, game-critical moment. Late audio is not a
            # useful reaction after the action has already finished.
            return ((w.first_audible_ms is None or
                     (w.first_audible_ms <= max_commentary_first_audible_ms
                      and w.overlap_ms is not None and w.overlap_ms <= max_overlap_ms))
                    and (w.first_audible_ms is None or w.grounded)
                    and (w.max_unplanned_gap_ms is None or
                         w.max_unplanned_gap_ms <= max_unplanned_gap_ms))
        if w.scenario == "owner_barge_in":
            return (w.interrupted and w.playback_stop_ms is not None
                    and w.playback_stop_ms <= max_playback_stop_ms)
        if w.scenario == "incidental_noise":
            return not w.interrupted
        return w.first_audible_ms is None

    for versions in data.values():
        reviewed += sum(w.independently_reviewed for w in versions.values())
        if set(versions) != {"baseline", "candidate"}:
            continue
        base, cand = versions["baseline"], versions["candidate"]
        complete_pairs += 1
        if not (base.independently_reviewed and cand.independently_reviewed):
            continue
        coverage += 1
        counts[cand.scenario] += 1
        if cand.scenario in ("viewer_question", "gameplay_commentary"):
            # Do not accept a selective A/B comparison which instruments only
            # one model's fluent playback. Unspoken moments have no PCM gap.
            if (base.first_audible_ms is not None
                    and cand.first_audible_ms is not None
                    and (base.max_unplanned_gap_ms is None)
                        != (cand.max_unplanned_gap_ms is None)):
                incomplete_gap_pairs = True
            if cand.max_unplanned_gap_ms is not None and (
                cand.max_unplanned_gap_ms > max_unplanned_gap_ms
                or (base.max_unplanned_gap_ms is not None and
                    cand.max_unplanned_gap_ms - base.max_unplanned_gap_ms
                    > max_pair_gap_regression_ms)
            ):
                stutter_regressions += 1
                pair_regressions += 1
        if cand.scenario == "viewer_question":
            if base.first_audible_ms is not None:
                baseline_questions.append(float(base.first_audible_ms))
            if cand.first_audible_ms is not None:
                candidate_questions.append(float(cand.first_audible_ms))
            # A pooled p95 can completely hide a catastrophic regression in
            # one matched viewer's response (e.g. one outlier among 20 cases).
            if (base.first_audible_ms is not None
                    and cand.first_audible_ms is not None
                    and cand.first_audible_ms - base.first_audible_ms
                    > max_pair_question_regression_ms):
                pair_regressions += 1
        elif cand.scenario == "gameplay_commentary":
            # Without a paired coverage guard, a candidate that never speaks
            # can appear 'more natural' by silently dropping every reaction.
            # Explicitly silent moments belong in critical_gameplay instead.
            if base.first_audible_ms is not None and cand.first_audible_ms is None:
                dropped_commentary += 1
                pair_regressions += 1
            elif (base.first_audible_ms is not None
                  and cand.first_audible_ms is not None
                  and cand.first_audible_ms - base.first_audible_ms
                  > max_pair_commentary_regression_ms):
                late_commentary += 1
                pair_regressions += 1
        elif cand.scenario == "owner_barge_in":
            if cand.playback_stop_ms is not None:
                candidate_stops.append(float(cand.playback_stop_ms))
            missed_barge_ins += not cand.interrupted
            if (base.playback_stop_ms is not None
                    and cand.playback_stop_ms is not None
                    and cand.playback_stop_ms - base.playback_stop_ms
                    > max_pair_stop_regression_ms):
                pair_regressions += 1
        elif cand.scenario == "incidental_noise":
            false_interruptions += cand.interrupted
        elif cand.scenario == "critical_gameplay":
            critical_speech += cand.first_audible_ms is not None
        if cand.scenario in {"viewer_question", "gameplay_commentary"}:
            ungrounded_speech += cand.first_audible_ms is not None and not cand.grounded
        if not good(cand):
            candidate_failures += 1
            if good(base):
                new_regressions += 1

    baseline_p95 = _p95(baseline_questions)
    candidate_p95 = _p95(candidate_questions)
    stop_p95 = _p95(candidate_stops)
    expected = 2 * len(data)
    def report(status: str, reason: str) -> SocialTurnReport:
        return SocialTurnReport(
            status, reason, complete_pairs, reviewed, expected,
            candidate_failures, new_regressions, false_interruptions,
            missed_barge_ins, critical_speech, ungrounded_speech,
            pair_regressions, baseline_p95, candidate_p95, stop_p95,
            dropped_commentary, late_commentary, stutter_regressions,
        )
    if (not data or incomplete_gap_pairs or any(len(v) != 2 for v in data.values())
            or coverage != len(data)
            or any(n < minimum_per_scenario for n in counts.values())):
        return report("insufficient_evidence", "missing_unreviewed_or_unbalanced_scenarios")
    if (len(baseline_questions) != counts["viewer_question"]
            or baseline_p95 is None or candidate_p95 is None
            or candidate_p95 > baseline_p95 + max_question_regression_ms
            or candidate_p95 > max_question_p95_ms
            or stop_p95 is None or stop_p95 > max_playback_stop_ms
            or candidate_failures or new_regressions or pair_regressions):
        return report("naturalness_regressed", "timing_interruption_grounding_or_game_focus")
    return report("eligible_for_manual_rehearsal", "paired_conversation_guardrails_met")


__all__ = ["SocialTurnMoment", "SocialTurnReport", "assess_social_turns", "SCENARIOS"]
