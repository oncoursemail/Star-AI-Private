"""Offline regression cases for explicit UI coverage, not aesthetic grading."""
from __future__ import annotations

from copy import deepcopy

import pytest

from star.ui_evidence import inspect_contract, validate_contract

SOURCE = "a" * 64
CAPTURE = "b" * 64
TRACE = "c" * 64
OTHER = "d" * 64


def _data():
    case = {"id": "menu-default", "screen": "menu", "state": "default",
            "viewport": {"width": 320, "height": 240, "unit": "css_px"},
            "input": "pointer", "motion": "default", "elements": ["Play", "Title"]}
    contract = {"version": 1, "target": "web", "cases": [case]}
    observation = {key: deepcopy(case[key]) for key in ("screen", "state", "viewport", "input", "motion")}
    observation.update(case=case["id"], view="desktop", pixel_ratio=1,
                       sources_sha256={"app.tsx": SOURCE}, capture_sha256=CAPTURE)
    manifest = {"ui_observations": [observation], "layout": {"desktop": [
        {"id": "Play", "rect": [10, 50, 100, 40]}, {"id": "Title", "rect": [10, 10, 100, 30]}]}}
    evidence = {"sources_sha256": {"app.tsx": SOURCE}, "captures": {
        "desktop": {"width": 320, "height": 240, "sha256": CAPTURE}}}
    return contract, manifest, evidence


def _add_case(contract, manifest, evidence, *, ident="menu-reduced", view="reduced", **labels):
    case = deepcopy(contract["cases"][0])
    case.update(id=ident, **labels)
    contract["cases"].append(case)
    observation = deepcopy(manifest["ui_observations"][0])
    observation.update(case=ident, view=view, **labels)
    manifest["ui_observations"].append(observation)
    evidence["captures"][view] = deepcopy(evidence["captures"]["desktop"])
    manifest["layout"][view] = deepcopy(manifest["layout"]["desktop"])


def _trace(contract, manifest, evidence, names=("open", "noise", "activate")):
    contract["cases"][0]["events"] = ["open", "activate"]
    manifest["ui_observations"][0]["trace_sha256"] = TRACE
    return {"engine": "web", "run_finished": True, "sources_sha256": deepcopy(evidence["sources_sha256"]),
            "events": [{"name": name, "t_ms": index * 10, "case_id": "menu-default", "capture_sha256": CAPTURE}
                       for index, name in enumerate(names)]}


def _codes(result):
    return {item["code"] for item in result["findings"]}


def test_complete_declarations_do_not_claim_runtime_accessibility_motion_or_approval():
    result = inspect_contract(*_data())
    assert result["status"] == "declared_coverage_complete"
    assert result["case_count"] == result["complete_count"] == 1
    assert result["failed_count"] == result["unverified_count"] == 0
    assert result["automated_check_count"] > 0
    assert not result["runtime_executed_by_this_tool"]
    assert not result["capture_authenticity_proven"]
    assert not result["accessibility_conformance_proven"]
    assert not result["motion_preference_honored_proven"]
    assert not result["owner_approved"]


def test_missing_required_case_is_incomplete_even_if_other_case_matches():
    contract, manifest, evidence = _data()
    _add_case(contract, manifest, evidence, motion="reduced")
    manifest["ui_observations"].pop()
    result = inspect_contract(contract, manifest, evidence)
    assert result["status"] == "insufficient_evidence"
    assert result["complete_count"] == 1
    assert result["cases"][1]["status"] == "unverified"
    assert "ui_case_unverified" in _codes(result)


def test_no_observations_cannot_vacuously_pass():
    contract, manifest, evidence = _data()
    del manifest["ui_observations"]
    result = inspect_contract(contract, manifest, evidence)
    assert result["status"] == "insufficient_evidence"
    assert result["complete_count"] == result["automated_check_count"] == 0


@pytest.mark.parametrize("field,value", [("state", "loading"), ("screen", "shop"),
                                          ("input", "keyboard"), ("motion", "reduced")])
def test_other_condition_cannot_satisfy_required_case(field, value):
    contract, manifest, evidence = _data()
    manifest["ui_observations"][0][field] = value
    result = inspect_contract(contract, manifest, evidence)
    assert result["status"] == "automated_checks_failed"
    assert "ui_condition_mismatch" in _codes(result)


def test_missing_element_evidence_is_unverified_not_success_or_inferred_absence():
    contract, manifest, evidence = _data()
    manifest["layout"]["desktop"].pop()
    result = inspect_contract(contract, manifest, evidence)
    assert result["status"] == "insufficient_evidence"
    assert result["findings"][0]["elements"] == ["Title"]


def test_missing_layout_and_missing_capture_remain_incomplete():
    contract, manifest, evidence = _data()
    manifest.pop("layout")
    assert "ui_elements_unverified" in _codes(inspect_contract(contract, manifest, evidence))
    manifest["ui_observations"][0]["view"] = "uncaptured"
    result = inspect_contract(contract, manifest, evidence)
    assert result["status"] == "insufficient_evidence"
    assert "ui_capture_unverified" in _codes(result)


def test_view_names_preserve_existing_numeric_prefix_capture_convention():
    contract, manifest, evidence = _data()
    manifest["ui_observations"][0]["view"] = "320-desktop"
    manifest["layout"]["320-desktop"] = manifest["layout"].pop("desktop")
    evidence["captures"]["320-desktop"] = evidence["captures"].pop("desktop")
    assert inspect_contract(contract, manifest, evidence)["status"] == "declared_coverage_complete"


@pytest.mark.parametrize("change", ["modified_source", "added_source", "removed_source", "modified_capture"])
def test_complete_current_source_set_and_exact_capture_bytes_are_required(change):
    contract, manifest, evidence = _data()
    if change == "modified_source":
        evidence["sources_sha256"]["app.tsx"] = OTHER
    elif change == "added_source":
        evidence["sources_sha256"]["app.css"] = OTHER
    elif change == "removed_source":
        manifest["ui_observations"][0]["sources_sha256"]["old.css"] = OTHER
    else:
        evidence["captures"]["desktop"]["sha256"] = OTHER
    result = inspect_contract(contract, manifest, evidence)
    assert result["status"] == "automated_checks_failed"
    assert ("ui_capture_stale" if change == "modified_capture" else "ui_sources_stale") in _codes(result)


@pytest.mark.parametrize("ratio,png", [(1, (320, 240)), (2, (640, 480)), (1.25, (400, 300))])
def test_css_viewport_is_distinct_from_png_pixels(ratio, png):
    contract, manifest, evidence = _data()
    manifest["ui_observations"][0]["pixel_ratio"] = ratio
    evidence["captures"]["desktop"].update(width=png[0], height=png[1])
    result = inspect_contract(contract, manifest, evidence)
    assert result["status"] == "declared_coverage_complete"
    assert not result["accessibility_conformance_proven"]


def test_retina_image_does_not_satisfy_css_viewport_without_explicit_scale():
    contract, manifest, evidence = _data()
    evidence["captures"]["desktop"].update(width=640, height=480)
    result = inspect_contract(contract, manifest, evidence)
    assert "ui_viewport_mismatch" in _codes(result)


def test_roblox_uses_rendered_pixels_without_web_dpr_scaling():
    contract, manifest, evidence = _data()
    contract["target"] = "roblox"
    contract["cases"][0]["viewport"]["unit"] = "rendered_px"
    manifest["ui_observations"][0]["viewport"]["unit"] = "rendered_px"
    assert inspect_contract(contract, manifest, evidence)["status"] == "declared_coverage_complete"
    manifest["ui_observations"][0]["pixel_ratio"] = 2
    evidence["captures"]["desktop"].update(width=640, height=480)
    result = inspect_contract(contract, manifest, evidence)
    assert "ui_pixel_scale_mismatch" in _codes(result)


@pytest.mark.parametrize("dimension", ["width", "height"])
def test_roblox_viewport_minimum_matches_capture_collector(dimension):
    contract, _, _ = _data()
    contract["target"] = "roblox"
    viewport = contract["cases"][0]["viewport"]
    viewport["unit"] = "rendered_px"
    viewport[dimension] = 199
    with pytest.raises(ValueError, match="at least 200"):
        validate_contract(contract)
    viewport[dimension] = 200
    assert validate_contract(contract) is contract


def test_web_minimum_css_viewport_can_use_a_two_x_capture():
    contract, manifest, evidence = _data()
    contract["cases"][0]["viewport"].update(width=100, height=100)
    manifest["ui_observations"][0]["viewport"].update(width=100, height=100)
    manifest["ui_observations"][0]["pixel_ratio"] = 2
    evidence["captures"]["desktop"].update(width=200, height=200)
    assert inspect_contract(contract, manifest, evidence)["status"] == "declared_coverage_complete"


def test_ordered_case_bound_events_match_and_repeated_expectations_require_repetition():
    contract, manifest, evidence = _data()
    trace = _trace(contract, manifest, evidence)
    assert inspect_contract(contract, manifest, evidence, trace=trace, trace_sha256=TRACE)["status"] == "declared_coverage_complete"
    contract["cases"][0]["events"] = ["activate", "activate"]
    result = inspect_contract(contract, manifest, evidence, trace=trace, trace_sha256=TRACE)
    assert "ui_event_sequence_missing" in _codes(result)


@pytest.mark.parametrize("names", [("activate", "open"), ("open",), ("activate",)])
def test_completed_bound_trace_contradicting_sequence_fails(names):
    contract, manifest, evidence = _data()
    trace = _trace(contract, manifest, evidence, names)
    result = inspect_contract(contract, manifest, evidence, trace=trace, trace_sha256=TRACE)
    assert result["status"] == "automated_checks_failed"
    assert "ui_event_sequence_missing" in _codes(result)


@pytest.mark.parametrize("change", ["no_trace", "unfinished", "no_observation_hash", "no_verified_hash",
                                   "no_source_binding", "no_case_id", "other_case", "no_capture_binding"])
def test_missing_trace_or_case_bindings_remain_unverified(change):
    contract, manifest, evidence = _data()
    trace = _trace(contract, manifest, evidence)
    digest = TRACE
    if change == "no_trace":
        trace, digest = None, None
    elif change == "unfinished":
        trace["run_finished"] = False
    elif change == "no_observation_hash":
        manifest["ui_observations"][0].pop("trace_sha256")
    elif change == "no_verified_hash":
        digest = None
    elif change == "no_source_binding":
        trace.pop("sources_sha256")
    else:
        for event in trace["events"]:
            if change == "other_case":
                event["case_id"] = "shop-phone"
            else:
                event.pop("case_id" if change == "no_case_id" else "capture_sha256")
    result = inspect_contract(contract, manifest, evidence, trace=trace, trace_sha256=digest)
    assert result["status"] == "insufficient_evidence"
    assert result["unverified_count"] > 0


@pytest.mark.parametrize("change,code", [("trace_bytes", "ui_trace_stale"), ("source", "ui_trace_stale"),
                                         ("capture", "ui_event_capture_stale"), ("engine", "ui_trace_engine_mismatch")])
def test_trace_cannot_reuse_other_bytes_sources_captures_or_engine(change, code):
    contract, manifest, evidence = _data()
    trace = _trace(contract, manifest, evidence)
    if change == "trace_bytes":
        manifest["ui_observations"][0]["trace_sha256"] = OTHER
    elif change == "source":
        trace["sources_sha256"]["app.tsx"] = OTHER
    elif change == "capture":
        trace["events"][0]["capture_sha256"] = OTHER
    else:
        trace["engine"] = "roblox"
    result = inspect_contract(contract, manifest, evidence, trace=trace, trace_sha256=TRACE)
    assert result["status"] == "automated_checks_failed"
    assert code in _codes(result)


def test_one_global_sequence_cannot_cover_a_second_input_state():
    contract, manifest, evidence = _data()
    trace = _trace(contract, manifest, evidence)
    _add_case(contract, manifest, evidence, ident="menu-keyboard", view="keyboard", input="keyboard")
    result = inspect_contract(contract, manifest, evidence, trace=trace, trace_sha256=TRACE)
    assert result["complete_count"] == 1
    assert result["cases"][1]["status"] == "unverified"


def test_duplicate_capture_hashes_allowed_for_static_states_but_views_must_be_distinct():
    contract, manifest, evidence = _data()
    _add_case(contract, manifest, evidence, motion="reduced")
    assert inspect_contract(contract, manifest, evidence)["complete_count"] == 2
    manifest["ui_observations"][1]["view"] = "desktop"
    with pytest.raises(ValueError, match="distinct view"):
        inspect_contract(contract, manifest, evidence)


def test_output_is_deterministic_and_inputs_are_not_changed():
    data = _data()
    trace = _trace(*data)
    before = deepcopy((data, trace))
    first = inspect_contract(*data, trace=trace, trace_sha256=TRACE)
    assert first == inspect_contract(*data, trace=trace, trace_sha256=TRACE)
    assert (data, trace) == before


@pytest.mark.parametrize("version", [True, "1", 1.0, 0, 2, None, {}])
def test_version_is_an_explicit_supported_integer(version):
    contract, _, _ = _data()
    contract["version"] = version
    with pytest.raises(ValueError):
        validate_contract(contract)


@pytest.mark.parametrize("field,value", [("id", []), ("screen", {}), ("state", "a" * 65),
                                          ("input", []), ("motion", {}), ("elements", ["Play", "Play"]),
                                          ("elements", []), ("elements", [None]), ("elements", ["a"] * 33),
                                          ("events", []), ("events", ["open"] * 17), ("events", [True])])
def test_malformed_case_fields_fail_with_value_error(field, value):
    contract, _, _ = _data()
    contract["cases"][0][field] = value
    with pytest.raises(ValueError):
        validate_contract(contract)


@pytest.mark.parametrize("field,value", [("width", True), ("width", 319.5), ("height", float("nan")),
                                          ("height", 10**400), ("unit", []), ("unit", "device_px")])
def test_viewport_values_are_bounded_and_typed(field, value):
    contract, _, _ = _data()
    contract["cases"][0]["viewport"][field] = value
    with pytest.raises(ValueError):
        validate_contract(contract)


def test_contract_rejects_unknown_keys_duplicate_conditions_and_wrong_platform_units():
    contract, _, _ = _data()
    contract["passed"] = True
    with pytest.raises(ValueError):
        validate_contract(contract)
    del contract["passed"]
    contract["cases"].append(deepcopy(contract["cases"][0]))
    contract["cases"][1]["id"] = "other-name"
    with pytest.raises(ValueError, match="distinct test conditions"):
        validate_contract(contract)
    contract["cases"].pop()
    contract["cases"][0]["viewport"]["unit"] = "rendered_px"
    with pytest.raises(ValueError, match="match its target"):
        validate_contract(contract)


@pytest.mark.parametrize("bad", [True, float("nan"), float("inf"), 10**400, 0.5, 5, [], None])
def test_capture_scale_rejects_bool_nan_unhashable_and_oversized_numbers(bad):
    contract, manifest, evidence = _data()
    manifest["ui_observations"][0]["pixel_ratio"] = bad
    with pytest.raises(ValueError):
        inspect_contract(contract, manifest, evidence)


@pytest.mark.parametrize("change", ["passed", "duplicate", "unknown_case", "invalid_case", "bad_hash",
                                   "missing_motion", "too_many", "unknown_viewport_key"])
def test_observations_cannot_smuggle_a_pass_or_skip_required_fields(change):
    contract, manifest, evidence = _data()
    item = manifest["ui_observations"][0]
    if change == "passed":
        item["passed"] = True
    elif change == "duplicate":
        manifest["ui_observations"].append(deepcopy(item))
    elif change == "unknown_case":
        item["case"] = "unrequested"
    elif change == "invalid_case":
        item["case"] = []
    elif change == "bad_hash":
        item["capture_sha256"] = {"approved": True}
    elif change == "missing_motion":
        item.pop("motion")
    elif change == "too_many":
        manifest["ui_observations"] *= 13
    else:
        item["viewport"]["trusted"] = True
    with pytest.raises(ValueError):
        inspect_contract(contract, manifest, evidence)


@pytest.mark.parametrize("bad", [True, float("nan"), float("inf"), 10**400, -1, 3_600_001, [], None])
def test_trace_timestamps_are_bounded_not_coerced(bad):
    data = _data()
    trace = _trace(*data)
    trace["events"][0]["t_ms"] = bad
    with pytest.raises(ValueError):
        inspect_contract(*data, trace=trace, trace_sha256=TRACE)


def test_trace_limits_duplicate_layout_and_unhashable_labels_are_rejected():
    data = _data()
    trace = _trace(*data)
    trace["events"][1]["case_id"] = []
    with pytest.raises(ValueError):
        inspect_contract(*data, trace=trace, trace_sha256=TRACE)
    trace = _trace(*data)
    trace["events"] *= 168
    with pytest.raises(ValueError):
        inspect_contract(*data, trace=trace, trace_sha256=TRACE)
    contract, manifest, evidence = _data()
    manifest["layout"]["desktop"].append(deepcopy(manifest["layout"]["desktop"][0]))
    with pytest.raises(ValueError):
        inspect_contract(contract, manifest, evidence)


def test_twelve_cases_allowed_thirteen_rejected():
    contract, manifest, evidence = _data()
    for index in range(1, 12):
        _add_case(contract, manifest, evidence, ident=f"case-{index}", view=f"view-{index}", state=f"state-{index}")
    assert inspect_contract(contract, manifest, evidence)["complete_count"] == 12
    _add_case(contract, manifest, evidence, ident="case-13", view="view-13", state="state-13")
    with pytest.raises(ValueError, match="one to twelve"):
        inspect_contract(contract, manifest, evidence)
