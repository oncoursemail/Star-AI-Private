"""Synthetic gate tests; neither model quality nor OBS playback was measured."""
import dataclasses

import pytest

from star.stream_realtime_benchmark import RealtimeRun
from star.stream_realtime_quality_gate import QualityWitness, assess_quality_gate


def trial(pair, variant, *, ttfa, finished=True):
    return RealtimeRun(pair, variant, "ObbyA", "v1", ttfa,
                       (16.7 if variant == "baseline" else 16.8,) * 150,
                       5200, finished)


def samples(n=24):
    runs = []
    witnesses = []
    for i in range(n):
        pair = f"pair{i}"
        for variant in ("baseline", "candidate"):
            runs.append(trial(pair, variant,
                              ttfa=650 + (i % 5) * 9 if variant == "baseline"
                              else 410 + (i % 5) * 9))
            witnesses.append(QualityWitness(pair, variant, True, True, True, 22.0))
    return runs, witnesses


def change(witnesses, *, pair="pair2", variant="candidate", **changes):
    return [dataclasses.replace(w, **changes)
            if (w.pair_id, w.variant) == (pair, variant) else w
            for w in witnesses]


def test_paired_quality_and_speed_can_only_qualify_manual_rehearsal():
    runs, witnesses = samples()
    report = assess_quality_gate(runs, witnesses)
    assert report.status == "eligible_for_manual_rehearsal"
    assert report.speed_verdict == "eligible_for_manual_pilot"
    assert report.witness_coverage == report.expected_witnesses == 48
    assert report.candidate_av_p95_ms == 22.0
    assert report.authorized_to_stream is False
    assert "pair2" not in str(report)
    assert report == assess_quality_gate(reversed(runs), reversed(witnesses))


def test_faster_but_worse_response_is_never_eligible():
    runs, witnesses = samples()
    report = assess_quality_gate(runs, change(witnesses, correct=False))
    assert report.status == "quality_regressed"
    assert report.candidate_correct == report.baseline_correct - 1


def test_speed_does_not_excuse_fabricated_game_claim_or_obs_missing():
    runs, witnesses = samples()
    assert assess_quality_gate(runs, change(witnesses, grounded=False)).status == "quality_regressed"
    missing = change(witnesses, obs_audible=False, av_offset_ms=None)
    report = assess_quality_gate(runs, missing)
    assert report.status == "quality_regressed" and report.candidate_obs_missing == 1
    assert assess_quality_gate(runs, change(witnesses, av_offset_ms=240)).status == "quality_regressed"


def test_missing_quality_evidence_cannot_support_a_speed_claim():
    runs, witnesses = samples()
    assert assess_quality_gate(runs, witnesses[:-1]).status == "insufficient_evidence"
    assert assess_quality_gate(runs, witnesses[:12]).status == "insufficient_evidence"
    assert assess_quality_gate(runs[:30], witnesses[:30]).status == "insufficient_evidence"


def test_missing_baseline_capture_cannot_be_called_verified():
    runs, witnesses = samples()
    missing = change(witnesses, variant="baseline", obs_audible=False, av_offset_ms=None)
    assert assess_quality_gate(runs, missing).status == "insufficient_evidence"


def test_speed_and_fps_remain_independent_required_gates():
    runs, witnesses = samples()
    slow = [dataclasses.replace(r, first_audio_ms=800)
            if r.variant == "candidate" else r for r in runs]
    report = assess_quality_gate(slow, witnesses)
    assert report.status == "speed_not_verified"
    assert report.speed_verdict == "regressed"


def test_low_correctness_rate_is_ineligible_even_if_baseline_worse():
    runs, witnesses = samples()
    degraded = [dataclasses.replace(w, correct=False)
                if w.pair_id in {"pair1", "pair2"} else w for w in witnesses]
    report = assess_quality_gate(runs, degraded)
    assert report.status == "quality_regressed"


def test_extra_wrong_and_duplicate_quality_witness_fail_closed():
    runs, witnesses = samples()
    with pytest.raises(ValueError, match="duplicate"):
        assess_quality_gate(runs, witnesses + [witnesses[0]])
    with pytest.raises(ValueError, match="does not match"):
        assess_quality_gate(runs, witnesses + [dataclasses.replace(witnesses[0], pair_id="unmeasured")])
    with pytest.raises(TypeError):
        assess_quality_gate(runs, witnesses + ["not a witness"])


@pytest.mark.parametrize("bad", [None, False, float("nan"), float("inf"), -6000, 6000, 10**1000, "23"])
def test_bad_recording_offset_rejected(bad):
    with pytest.raises(ValueError):
        QualityWitness("pair", "candidate", True, True, True, bad)


def test_witness_bounded_fields_and_independent_capture_are_required():
    with pytest.raises(ValueError):
        QualityWitness("../bad", "baseline", True, True, True, 2)
    with pytest.raises(ValueError):
        QualityWitness("id", "other", True, True, True, 2)
    with pytest.raises(ValueError):
        QualityWitness("id", "baseline", 1, True, True, 2)
    with pytest.raises(ValueError):
        QualityWitness("id", "candidate", True, True, False, 2)
    with pytest.raises(ValueError):
        QualityWitness("id", "candidate", True, True, True, None)


@pytest.mark.parametrize("bad", [True, "100", float("nan"), float("inf"), 10**1000, 2])
def test_invalid_av_sync_guardrail_rejected(bad):
    runs, witnesses = samples()
    with pytest.raises(ValueError):
        assess_quality_gate(runs, witnesses, max_av_p95_ms=bad)
