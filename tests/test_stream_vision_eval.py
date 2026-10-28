"""Synthetic tests validate the quality gate, not real vision accuracy."""
import json
import pytest

from star.stream_visual_perception import VisualFinding, VisualPacket

from star.stream_vision_eval import (
    VisionEvalCase, VisionEvalPrediction, compare_vision, prediction_from_packet, read_jsonl,
)


def predicted(*kinds, status="accepted", latency=60, age=120):
    return VisionEvalPrediction.from_dict({
        "status": status, "latency_ms": latency, "age_ms": age,
        "findings": [{"kind": name, "region": "hud", "confidence": .95}
                     for name in kinds],
    })


def case(i, *, b=None, c=None, truth=None):
    positive = i % 2 == 0
    return VisionEvalCase(
        f"case{i}", "Obby", "v1", "studio_engine",
        ((("hud_change", "hud"),) if positive else ()) if truth is None else truth,
        b or predicted("hud_change" if positive else "menu_change", latency=100),
        c or predicted(*(["hud_change"] if positive else []), latency=70),
    )


def cohort(n=100):
    return [case(i) for i in range(n)]


def test_eligible_only_for_manual_pilot_with_fresh_quality():
    result = compare_vision(cohort())
    assert result.verdict == "eligible_for_manual_pilot"
    assert result.cases == 100
    assert result.positive_cases == result.negative_cases == 50
    assert result.candidate.f1 == 1
    assert result.baseline.false_alert_rate == 1
    assert result.candidate.false_alert_rate == 0
    assert result.candidate.p95_latency_ms == 70
    assert result.f1_gain_ci95[0] > 0
    assert "authorize deployment" in result.note
    assert "case0" not in json.dumps(result.to_dict())
    assert compare_vision(list(reversed(cohort()))) == result


def test_false_alerts_veto_fast_but_inaccurate_candidate():
    bad = [case(i, c=predicted("menu_change", latency=10)) for i in range(100)]
    result = compare_vision(bad)
    assert result.verdict == "regressed"
    assert result.candidate.false_alert_rate == 1


def test_stale_predictions_are_ignored_and_lateness_vetoes():
    rows = [case(i, c=predicted("hud_change", latency=20, age=2200))
            for i in range(100)]
    result = compare_vision(rows)
    assert result.candidate.false_alert_rate == 0
    assert result.candidate.stale_rate == 1
    assert result.candidate.recall == 0
    assert result.verdict == "regressed"


def test_failed_workers_cannot_produce_game_cues():
    rows = [case(i, c=predicted(status="timeout", latency=1000))
            for i in range(100)]
    result = compare_vision(rows)
    assert result.candidate.failed_rate == 1
    assert result.candidate.recall == 0
    assert result.verdict == "regressed"


def test_p95_latency_regression_vetoes_candidate():
    rows = [case(i, c=predicted(*(["hud_change"] if i % 2 == 0 else []),
                                latency=120)) for i in range(100)]
    assert compare_vision(rows).verdict == "regressed"


def test_small_and_nonrepresentative_holdouts_remain_inconclusive():
    assert compare_vision(cohort(20)).verdict == "inconclusive"
    negatives = [case(i, truth=(), b=predicted(), c=predicted())
                 for i in range(100)]
    assert compare_vision(negatives).verdict == "inconclusive"


def valid_row():
    prediction = lambda ms: {
        "status": "accepted", "latency_ms": ms, "age_ms": 90,
        "findings": [{"kind": "hud_change", "region": "hud", "confidence": .95}],
    }
    return {
        "case_id": "frame1", "game_id": "Obby", "game_version": "v1",
        "partition": "holdout", "truth_source": "studio_engine",
        "truth": [{"kind": "hud_change", "region": "hud"}],
        "baseline": prediction(120), "candidate": prediction(70),
    }


def test_schema_drops_untrusted_text_unknown_and_training_rows():
    for kind in ("victory", "user_chat"):
        with pytest.raises(ValueError):
            predicted(kind)
    row = valid_row()
    row["caption"] = "secret screen text"
    with pytest.raises(ValueError):
        VisionEvalCase.from_dict(row)
    row = valid_row()
    row["partition"] = "practice"
    with pytest.raises(ValueError):
        VisionEvalCase.from_dict(row)
    row = valid_row()
    row["truth_source"] = "model_self_report"
    with pytest.raises(ValueError):
        VisionEvalCase.from_dict(row)


def test_duplicate_case_mixed_version_and_bad_types_rejected():
    with pytest.raises(ValueError, match="duplicate"):
        compare_vision([case(0), case(0)])
    other = VisionEvalCase("other", "Obby", "v2", "studio_engine",
                           (), predicted(), predicted())
    with pytest.raises(ValueError, match="game version"):
        compare_vision([case(0), other])
    with pytest.raises(ValueError):
        VisionEvalPrediction.from_dict({
            "status": "accepted", "findings": [], "latency_ms": True, "age_ms": 1,
        })
    with pytest.raises(ValueError):
        VisionEvalPrediction.from_dict({
            "status": "timeout", "latency_ms": 1, "age_ms": 1,
            "findings": [{"kind": "hud_change", "region": "hud", "confidence": 1}],
        })
    row = valid_row()
    row["truth"] = row["truth"] * 2
    with pytest.raises(ValueError, match="duplicate"):
        VisionEvalCase.from_dict(row)


def test_jsonl_bounds_and_duplicate_keys(tmp_path):
    path = tmp_path / "holdout.jsonl"
    path.write_text(json.dumps(valid_row()) + "\n", encoding="utf-8")
    assert len(read_jsonl(path)) == 1
    assert compare_vision(read_jsonl(path)).verdict == "inconclusive"
    path.write_text('{"case_id":"one","case_id":"two"}', encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        read_jsonl(path)
    path.write_bytes(b" " * 8193 + b"\n")
    with pytest.raises(ValueError, match="byte bound"):
        read_jsonl(path)
    path.unlink()
    path.symlink_to(tmp_path / "holdout-original.jsonl")
    with pytest.raises(ValueError):
        read_jsonl(path)


def test_confidence_threshold_filters_weak_cues():
    row = valid_row()
    row["candidate"]["findings"][0]["confidence"] = .84
    item = VisionEvalCase.from_dict(row)
    assert item.candidate.labels == ()
    assert item.baseline.labels == (("hud_change", "hud"),)


def test_hidden_truth_is_separate_from_predictions():
    row = valid_row()
    row["truth"] = [{"kind": "scene_change", "region": "world"}]
    item = VisionEvalCase.from_dict(row)
    assert item.truth != item.candidate.labels
    assert compare_vision([item]).candidate.recall == 0


def test_actual_visual_packet_adapter_tracks_age_and_suppresses_unknown():
    packet = VisualPacket(300, 1280, 720, (
        VisualFinding("hud_change", "hud", .95),
        VisualFinding("unknown", "world", .92),
    ))
    result = prediction_from_packet(
        packet, status="accepted", captured_ms=300,
        started_ms=320, finished_ms=380,
    )
    assert result.latency_ms == 60
    assert result.age_ms == 80
    assert result.labels == (("hud_change", "hud"),)
    with pytest.raises(ValueError, match="match"):
        prediction_from_packet(
            packet, status="accepted", captured_ms=301,
            started_ms=320, finished_ms=380,
        )
    with pytest.raises(ValueError):
        prediction_from_packet(packet, status="error", captured_ms=300,
                               started_ms=320, finished_ms=380)


def test_direct_unvalidated_constructor_cannot_inject_truth_or_stale_success():
    with pytest.raises(ValueError):
        VisionEvalPrediction("accepted", (("victory", "hud"),), 1, 1)
    with pytest.raises(ValueError):
        VisionEvalCase("case", "Obby", "v1", "model_self_report",
                       (), predicted(), predicted())
    with pytest.raises(ValueError):
        VisionEvalCase("case", "Obby", "v1", "studio_engine",
                       (("unknown", "world"),), predicted(), predicted())
    row = valid_row()
    row["candidate"]["findings"][0]["kind"] = "unknown"
    assert VisionEvalCase.from_dict(row).candidate.labels == ()
