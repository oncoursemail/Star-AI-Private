"""Authored offline artifact controls; no provider, model, profile or native call."""
from copy import deepcopy
from dataclasses import FrozenInstanceError
import json
from pathlib import Path

import pytest

from star import general_knowledge_benchmark as bench


@pytest.fixture
def artifacts():
    suite = bench.load_suite()
    return suite, bench.load_oracles(suite)


def model(name="fixture-model"):
    return {"model_id": name, "revision": "fixture-revision", "weights_sha256": "b" * 64,
            "tokenizer_sha256": "c" * 64, "quantization": "fixture-q4"}


def identity():
    return {"app_commit": "a" * 40, "source_sha256": "a" * 64,
            "request_builder_sha256": "d" * 64, "adapter_sha256": "e" * 64,
            "backend_build": "fixture-build", "model": model(), "mode": "direct_text",
            "options": {"temperature": 0, "top_p": 1, "max_output_tokens": 128,
                        "seed": None, "stop": [], "tools": []}}


def answer(row, value):
    row["response"] = value if type(value) is str else json.dumps(value)
    row["response_sha256"] = bench.digest(row["response"].encode("utf-8"))


def raw_run(suite, oracles, repeats=1):
    plan = bench.prepare(suite, repeats)
    rows = []
    for request in plan["requests"]:
        row = {key: request[key] for key in ("task_id", "attempt", "request_sha256")}
        row.update(outcome="completed", error_code=None)
        answer(row, oracles.data["cases"][request["task_id"]]["expected"])
        rows.append(row)
    return {"schema_version": 1, "kind": "general_foundation_raw_run", "suite_id": suite.data["suite_id"],
            "suite_sha256": suite.sha256, "oracle_sha256": oracles.sha256,
            "grader_sha256": bench.grader_digest(), "identity": identity(), "repeats": repeats, "rows": rows}


@pytest.mark.parametrize("repeats", [1, 2, 3])
def test_reviewed_development_answers_and_full_attempts_are_scored_without_gain_authority(artifacts, repeats):
    suite, oracles = artifacts
    run = raw_run(suite, oracles, repeats)
    report = bench.score_run(suite, oracles, run)
    assert report["counts"] == {"pass": 10 * repeats} and report["total"] == 10 * repeats
    assert report["provenance"] == "operator_declared_not_authenticated"
    assert "allowed" not in report and "response" not in report["rows"][0]
    assert oracles.data["cases"]["GF-10"]["expected"]["order"] == ["E4", "E2", "E3", "E1"]


def test_preparation_uses_only_public_messages_without_opening_oracle_canary(artifacts, monkeypatch, tmp_path, capsys):
    suite, _ = artifacts
    canary = tmp_path / "oracles.json"
    canary.write_text('{"expected":"ORACLE_ONLY_CANARY"}', encoding="utf-8")
    original_open = Path.open
    def guarded_open(path, *args, **kwargs):
        assert path != canary and path != bench.DEFAULT_ORACLES
        return original_open(path, *args, **kwargs)
    monkeypatch.setattr(Path, "open", guarded_open)
    monkeypatch.setattr(bench, "load_oracles", lambda *a, **k: pytest.fail("prepare cannot load oracles"))
    plan = bench.prepare(suite, 2)
    assert len(plan["requests"]) == 20
    for request in plan["requests"]:
        assert list(request["messages"][0]) == ["role", "content"]
        assert [message["role"] for message in request["messages"]] == ["system", "user"]
        assert request["messages"][1]["content"] == suite.data["tasks"][bench.IDS.index(request["task_id"])]["prompt"]
    assert bench.main(["prepare", "--oracles", str(canary)]) == 0
    assert "ORACLE_ONLY_CANARY" not in capsys.readouterr().out


def test_default_cli_is_inert_without_suite_or_oracle_reads(monkeypatch, capsys):
    monkeypatch.setattr(bench, "load_suite", lambda *a, **k: pytest.fail("no command must be inert"))
    assert bench.main([]) == 0
    assert "prepare" in capsys.readouterr().out


def test_artifact_bytes_are_immutable_and_data_views_cannot_change_grading(artifacts):
    suite, oracles = artifacts
    original = oracles.sha256
    oracles.data["cases"]["GF-01"]["expected"]["remaining_pencils"] = 0
    assert oracles.data["cases"]["GF-01"]["expected"]["remaining_pencils"] == 79
    assert oracles.sha256 == original
    with pytest.raises(FrozenInstanceError):
        oracles.raw = b"{}"


@pytest.mark.parametrize("index,value,status", [
    (0, {"remaining_pencils": 80}, "incorrect"),
    (0, {"remaining_pencils": True}, "invalid_format"),
    (0, {"remaining_pencils": 79.0}, "invalid_format"),
    (0, {"remaining_pencils": 79, "extra": 0}, "invalid_format"),
    (0, '{"remaining_pencils":79,"remaining_pencils":0}', "invalid_format"),
    (0, '```json\n{"remaining_pencils":79}\n```', "invalid_format"),
    (0, '{"remaining_pencils":NaN}', "invalid_format"),
    (0, '{"remaining_pencils":1e999}', "invalid_format"),
    (2, {"numerator": 2, "denominator": 10}, "invalid_format"),
    (2, {"numerator": 1, "denominator": 0}, "invalid_format"),
    (4, {"end_utc": "2026-02-30T00:05:00Z"}, "invalid_format"),
    (4, {"end_utc": "2026-02-01T00:05:00+00:00"}, "invalid_format"),
    (5, {"order": ["A", "B", "C"]}, "incorrect"),
    (6, {"ids": ["P3", "P1"]}, "incorrect"),
    (7, {"delivery_date": "2026-03-12", "source_ids": ["R2"]}, "incorrect"),
    (8, {"tickets": 0, "status": "provided", "source_ids": []}, "incorrect"),
    (8, {"tickets": False, "status": "not_provided", "source_ids": []}, "invalid_format"),
    (9, {"order": ["E4", "E3", "E2", "E1"]}, "incorrect"),
])
def test_semantic_and_format_failures_do_not_become_keyword_passes(artifacts, index, value, status):
    suite, oracles = artifacts
    run = raw_run(suite, oracles)
    answer(run["rows"][index], value)
    report = bench.score_run(suite, oracles, run)
    assert report["rows"][index]["status"] == status and report["counts"]["pass"] == 9


def test_object_order_and_whitespace_are_irrelevant_but_all_outcomes_remain_in_totals(artifacts):
    suite, oracles = artifacts
    run = raw_run(suite, oracles)
    answer(run["rows"][2], ' \n { "denominator": 5, "numerator": 1 }\t')
    assert bench.score_run(suite, oracles, run)["counts"] == {"pass": 10}
    answer(run["rows"][0], "   ")
    answer(run["rows"][1], {"seconds": 121})
    answer(run["rows"][3], "I cannot answer this")
    answer(run["rows"][4], "")
    run["rows"][4].update(outcome="transport_error", error_code="timeout")
    report = bench.compare_runs(suite, oracles, run, deepcopy(run))
    assert report["baseline"]["counts"] == {"empty": 1, "incorrect": 1, "invalid_format": 1, "transport_error": 1, "pass": 6}
    assert report["baseline"]["total"] == 10 and len(report["baseline"]["rows"]) == 10
    assert report["comparison_status"] == "incomplete_transport" and report["changes"] == []


@pytest.mark.parametrize("change", ["missing", "extra", "duplicate", "swapped", "attempt", "request", "response", "saved_grade", "saved_kind"])
def test_full_ordered_raw_row_identity_and_regrading_are_required(artifacts, change):
    suite, oracles = artifacts
    run = raw_run(suite, oracles)
    if change == "missing":
        run["rows"].pop()
    elif change == "extra":
        run["rows"].append(deepcopy(run["rows"][0]))
    elif change == "duplicate":
        run["rows"][1] = deepcopy(run["rows"][0])
    elif change == "swapped":
        run["rows"][0], run["rows"][1] = run["rows"][1], run["rows"][0]
    elif change == "attempt":
        run["rows"][0]["attempt"] = True
    elif change == "request":
        run["rows"][0]["request_sha256"] = "0" * 64
    elif change == "response":
        run["rows"][0]["response"] = '{"remaining_pencils":0}'
    elif change == "saved_grade":
        run["rows"][0]["status"] = "pass"
    else:
        run["kind"] = "general_foundation_scores"
    with pytest.raises(ValueError):
        bench.compare_runs(suite, oracles, raw_run(suite, oracles), run)


@pytest.mark.parametrize("field", ["suite_id", "suite_sha256", "oracle_sha256", "grader_sha256"])
def test_current_suite_oracle_grader_bytes_are_not_replaceable_by_labels(artifacts, field):
    suite, oracles = artifacts
    run = raw_run(suite, oracles)
    run[field] = "changed" if field == "suite_id" else "0" * 64
    with pytest.raises(ValueError):
        bench.score_run(suite, oracles, run)


def test_changed_suite_or_oracle_with_same_suite_id_refuses_old_raw_run(artifacts, tmp_path):
    suite, oracles = artifacts
    run = raw_run(suite, oracles)
    public = suite.data
    public["tasks"][0]["prompt"] += " "
    path = tmp_path / "changed-suite.json"
    path.write_text(json.dumps(public), encoding="utf-8")
    changed = bench.load_suite(path)
    with pytest.raises(ValueError):
        bench.score_run(changed, bench.load_oracles(changed), run)
    private = oracles.data
    private["cases"]["GF-01"]["expected"]["remaining_pencils"] = 0
    path.write_text(json.dumps(private), encoding="utf-8")
    with pytest.raises(ValueError):
        bench.score_run(suite, bench.load_oracles(suite, path), run)


@pytest.mark.parametrize("field", ["app_commit", "source_sha256", "request_builder_sha256", "adapter_sha256", "backend_build", "mode", "model", "options"])
@pytest.mark.parametrize("axis", ["same", "model"])
def test_only_an_explicit_exact_model_pair_can_differ_and_other_controls_are_strict(artifacts, field, axis):
    suite, oracles = artifacts
    before, after = raw_run(suite, oracles), raw_run(suite, oracles)
    if field == "model":
        after["identity"][field] = model("different-model")
    elif field == "options":
        after["identity"][field]["temperature"] = 0.1
    elif field in {"backend_build", "mode"}:
        after["identity"][field] = "different"
    else:
        after["identity"][field] = "f" * len(after["identity"][field])
    kwargs = {"axis": axis}
    if axis == "model":
        kwargs.update(expected_baseline_model=model(), expected_candidate_model=model("different-model"))
    if axis == "model" and field == "model":
        report = bench.compare_runs(suite, oracles, before, after, **kwargs)
        assert report["comparison_status"] == "artifact_consistent" and "allowed" not in report
    else:
        with pytest.raises(ValueError):
            bench.compare_runs(suite, oracles, before, after, **kwargs)


@pytest.mark.parametrize("kind", ["missing_pair", "wrong_pair", "implicit_pair", "verified", "missing_source", "empty_backend", "tools", "bad_options", "repeats"])
def test_missing_invalid_or_claimed_verified_provenance_never_gets_a_comparison(artifacts, kind):
    suite, oracles = artifacts
    before, after = raw_run(suite, oracles), raw_run(suite, oracles)
    kwargs = {}
    if kind == "missing_pair":
        kwargs["axis"] = "model"
    elif kind == "wrong_pair":
        kwargs.update(axis="model", expected_baseline_model=model(), expected_candidate_model=model("unexpected"))
    elif kind == "implicit_pair":
        kwargs.update(expected_baseline_model=model(), expected_candidate_model=model())
    elif kind == "verified":
        after["identity"]["verified"] = True
    elif kind == "missing_source":
        del after["identity"]["source_sha256"]
    elif kind == "empty_backend":
        after["identity"]["backend_build"] = ""
    elif kind == "tools":
        after["identity"]["options"]["tools"] = ["tool"]
    elif kind == "bad_options":
        after["identity"]["options"]["temperature"] = True
    else:
        after = raw_run(suite, oracles, 2)
    with pytest.raises(ValueError):
        bench.compare_runs(suite, oracles, before, after, **kwargs)


def test_compare_recomputes_wrong_answers_instead_of_trusting_prior_score(artifacts):
    suite, oracles = artifacts
    before = raw_run(suite, oracles)
    after = deepcopy(before)
    assert bench.score_run(suite, oracles, after)["counts"] == {"pass": 10}
    answer(after["rows"][0], {"remaining_pencils": 0})
    report = bench.compare_runs(suite, oracles, before, after)
    assert report["candidate"]["counts"] == {"incorrect": 1, "pass": 9}
    assert report["changes"] == [{"task_id": "GF-01", "attempt": 1, "baseline": "pass", "candidate": "incorrect"}]


@pytest.mark.parametrize("data", [b'{"x":1,"x":2}', b'{"x":Infinity}', b'{"x":NaN}', b'{"x":1} trailing', b'"\xff"', b"[" * 18 + b"0" + b"]" * 18])
def test_strict_bounded_json_rejects_ambiguous_or_deep_inputs(data):
    with pytest.raises(ValueError):
        bench.parse_json(data)


def test_file_and_response_bounds_and_exclusive_output_preserve_input(artifacts, tmp_path, capsys):
    suite, oracles = artifacts
    run = raw_run(suite, oracles)
    answer(run["rows"][0], "x" * (bench.MAX_RESPONSE + 1))
    with pytest.raises(ValueError):
        bench.score_run(suite, oracles, run)
    with pytest.raises(ValueError):
        bench.parse_json(b" " * (bench.MAX_FILE + 1))
    target = tmp_path / "prepared.json"
    assert bench.main(["prepare", "--out", str(target)]) == 0
    original = target.read_bytes()
    assert bench.main(["prepare", "--out", str(target)]) == 2
    assert target.read_bytes() == original
    source = tmp_path / "raw.json"
    source.write_text(json.dumps(raw_run(suite, oracles)), encoding="utf-8")
    original = source.read_bytes()
    assert bench.main(["score", "--run", str(source), "--out", str(source)]) == 2
    assert source.read_bytes() == original
    assert "no model was called" in capsys.readouterr().out


def test_cli_scores_and_compares_existing_raw_files_and_rejects_saved_grades(artifacts, tmp_path, capsys):
    suite, oracles = artifacts
    raw = tmp_path / "raw.json"
    raw.write_text(json.dumps(raw_run(suite, oracles)), encoding="utf-8")
    assert bench.main(["score", "--run", str(raw)]) == 0
    scores = json.loads(capsys.readouterr().out)
    assert scores["counts"] == {"pass": 10}
    assert bench.main(["compare", "--baseline", str(raw), "--candidate", str(raw)]) == 0
    assert json.loads(capsys.readouterr().out)["comparison_status"] == "artifact_consistent"
    raw.write_text(json.dumps(scores), encoding="utf-8")
    assert bench.main(["compare", "--baseline", str(raw), "--candidate", str(raw)]) == 2


def _app_stamp(run):
    """Only predeclared source identity may vary in an app-axis trial."""
    return {key: run["identity"][key] for key in ("app_commit", "source_sha256")}


def _app_pair(artifacts):
    suite, oracles = artifacts
    baseline, candidate = raw_run(suite, oracles), raw_run(suite, oracles)
    candidate["identity"]["app_commit"] = "f" * 40
    candidate["identity"]["source_sha256"] = "e" * 64
    kwargs = {"axis": "app", "expected_baseline_app": _app_stamp(baseline),
              "expected_candidate_app": _app_stamp(candidate)}
    return suite, oracles, baseline, candidate, kwargs


def test_app_axis_compares_software_revisions_without_switching_model_or_backend(artifacts):
    suite, oracles, baseline, candidate, kwargs = _app_pair(artifacts)
    answer(candidate["rows"][0], {"remaining_pencils": 0})
    result = bench.compare_runs(suite, oracles, baseline, candidate, **kwargs)
    assert result["axis"] == "app" and result["comparison_status"] == "artifact_consistent"
    assert result["candidate"]["counts"] == {"incorrect": 1, "pass": 9}
    assert result["changes"][0]["task_id"] == "GF-01"
    assert result["provenance"] == "operator_declared_not_authenticated"
    assert "authorized_to_promote" not in result


@pytest.mark.parametrize("field", [
    "model", "backend_build", "adapter_sha256", "request_builder_sha256", "mode", "options",
])
def test_app_axis_rejects_confounded_model_prompt_adapter_backend_or_sampling(artifacts, field):
    suite, oracles, baseline, candidate, kwargs = _app_pair(artifacts)
    if field == "model":
        candidate["identity"]["model"] = model("changed")
    elif field == "options":
        candidate["identity"]["options"]["temperature"] = 0.4
    else:
        candidate["identity"][field] = "changed" if field in ("backend_build", "mode") else "0" * 64
    with pytest.raises(ValueError):
        bench.compare_runs(suite, oracles, baseline, candidate, **kwargs)


@pytest.mark.parametrize("variant", [
    "missing", "mismatched_candidate", "same_app_commit", "same_source_digest",
    "extra_key", "malformed_hash", "wrong_axis", "model_pair_conflict",
])
def test_app_axis_refuses_undeclared_or_fake_app_changes(artifacts, variant):
    suite, oracles, baseline, candidate, kwargs = _app_pair(artifacts)
    if variant == "missing":
        kwargs["expected_candidate_app"] = None
    elif variant == "mismatched_candidate":
        kwargs["expected_candidate_app"] = _app_stamp(baseline)
    elif variant == "same_app_commit":
        candidate["identity"]["app_commit"] = baseline["identity"]["app_commit"]
        kwargs["expected_candidate_app"] = _app_stamp(candidate)
    elif variant == "same_source_digest":
        candidate["identity"]["source_sha256"] = baseline["identity"]["source_sha256"]
        kwargs["expected_candidate_app"] = _app_stamp(candidate)
    elif variant == "extra_key":
        kwargs["expected_candidate_app"]["verified"] = True
    elif variant == "malformed_hash":
        kwargs["expected_candidate_app"]["source_sha256"] = "not-a-hash"
    elif variant == "wrong_axis":
        kwargs["axis"] = "same"
    else:
        kwargs["expected_baseline_model"] = model()
    with pytest.raises(ValueError):
        bench.compare_runs(suite, oracles, baseline, candidate, **kwargs)


def test_app_axis_cli_requires_two_explicit_app_identities(artifacts, tmp_path, capsys):
    suite, oracles, baseline, candidate, kwargs = _app_pair(artifacts)
    before, after = tmp_path / "baseline.json", tmp_path / "candidate.json"
    before.write_text(json.dumps(baseline), encoding="utf-8")
    after.write_text(json.dumps(candidate), encoding="utf-8")
    args = [
        "compare", "--baseline", str(before), "--candidate", str(after),
        "--axis", "app", "--baseline-app", json.dumps(kwargs["expected_baseline_app"]),
        "--candidate-app", json.dumps(kwargs["expected_candidate_app"]),
    ]
    assert bench.main(args) == 0
    assert json.loads(capsys.readouterr().out)["axis"] == "app"
    assert bench.main(args[:-2]) == 2
    assert "no model was called" in capsys.readouterr().out
