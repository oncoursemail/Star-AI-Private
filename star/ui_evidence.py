"""Optional, bounded UI coverage contracts over already verified local evidence.

This inspector does not run a browser/Studio or authenticate a capture. It binds
declared observations to the source files and PNGs verified by creative_review,
and reports missing requirements separately from contradictory evidence. Input
and motion labels describe a requested test condition, not proof of behavior.
"""
from __future__ import annotations

import math
import re
from typing import Any

MAX_CASES = 12  # Same bound as creative_review.capture_evidence.
MAX_ELEMENTS = 32
MAX_EVENTS = 500
MAX_SEQUENCE = 16
_ID = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,63}\Z")
_VIEW = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_INPUTS = frozenset({"pointer", "keyboard", "touch", "gamepad"})
_MOTIONS = frozenset({"default", "reduced"})
_UNITS = frozenset({"css_px", "rendered_px"})
_LABELS = ("screen", "state", "viewport", "input", "motion")
_CASE_KEYS = {"id", *_LABELS, "elements", "events"}
_OBS_KEYS = {"case", "view", *_LABELS, "pixel_ratio", "sources_sha256", "capture_sha256", "trace_sha256"}


def _object(value: Any, required: set[str], allowed: set[str], label: str) -> dict:
    if type(value) is not dict or not required <= value.keys() or value.keys() - allowed:
        raise ValueError(f"{label} has missing or unknown fields")
    return value


def _identifier(value: Any, label: str) -> str:
    if type(value) is not str or not _ID.fullmatch(value):
        raise ValueError(f"{label} must be a bounded stable ID")
    return value


def _view_id(value: Any) -> str:
    # Match the existing creative_review capture IDs, including numeric prefixes.
    if type(value) is not str or not _VIEW.fullmatch(value):
        raise ValueError("view must use a bounded capture ID")
    return value


def _choice(value: Any, choices: frozenset[str], label: str) -> str:
    if type(value) is not str or value not in choices:
        raise ValueError(f"{label} has an unsupported value")
    return value


def _digest(value: Any, label: str) -> str:
    if type(value) is not str or not _SHA.fullmatch(value):
        raise ValueError(f"{label} must be a SHA-256 digest")
    return value


def _source_hashes(value: Any, label: str) -> dict[str, str]:
    if type(value) is not dict or not 1 <= len(value) <= 32:
        raise ValueError(f"{label} must contain one to thirty-two source hashes")
    for path, digest in value.items():
        if type(path) is not str or not 1 <= len(path) <= 500:
            raise ValueError(f"{label} has an invalid source name")
        _digest(digest, label)
    return value


def _viewport(value: Any) -> dict:
    obj = _object(value, {"width", "height", "unit"}, {"width", "height", "unit"}, "viewport")
    for dim in ("width", "height"):
        if type(obj[dim]) is not int or not 100 <= obj[dim] <= 8192:
            raise ValueError("Viewport dimensions must be integer values from 100 to 8192")
    _choice(obj["unit"], _UNITS, "viewport unit")
    return obj


def _labels(value: dict) -> None:
    _identifier(value["screen"], "screen")
    _identifier(value["state"], "state")
    _viewport(value["viewport"])
    _choice(value["input"], _INPUTS, "input")
    _choice(value["motion"], _MOTIONS, "motion")


def _ids(value: Any, label: str, maximum: int, *, nonempty: bool, unique: bool) -> list[str]:
    if type(value) is not list or not int(nonempty) <= len(value) <= maximum:
        raise ValueError(f"{label} exceeds its supported list bounds")
    for item in value:
        _identifier(item, label)
    if unique and len(set(value)) != len(value):
        raise ValueError(f"{label} must contain unique IDs")
    return value


def validate_contract(contract: Any) -> dict:
    """Validate strict v1 requirements without I/O or modifying the caller's data."""
    value = _object(contract, {"version", "target", "cases"}, {"version", "target", "cases"}, "UI contract")
    if type(value["version"]) is not int or value["version"] != 1:
        raise ValueError("Only UI contract version 1 is supported")
    _choice(value["target"], frozenset({"web", "roblox"}), "target")
    cases = value["cases"]
    if type(cases) is not list or not 1 <= len(cases) <= MAX_CASES:
        raise ValueError("A UI contract requires one to twelve cases")
    seen_ids: set[str] = set()
    seen_conditions: set[tuple] = set()
    unit = "css_px" if value["target"] == "web" else "rendered_px"
    for case in cases:
        case = _object(case, _CASE_KEYS - {"events"}, _CASE_KEYS, "UI case")
        ident = _identifier(case["id"], "case id")
        _labels(case)
        if case["viewport"]["unit"] != unit:
            raise ValueError("Contract viewport unit must match its target")
        if value["target"] == "roblox" and any(case["viewport"][dim] < 200 for dim in ("width", "height")):
            raise ValueError("Roblox rendered-pixel viewport dimensions must be at least 200")
        _ids(case["elements"], "required elements", MAX_ELEMENTS, nonempty=True, unique=True)
        if "events" in case:
            _ids(case["events"], "required event sequence", MAX_SEQUENCE, nonempty=True, unique=False)
        condition = (case["screen"], case["state"], case["viewport"]["width"],
                     case["viewport"]["height"], case["input"], case["motion"])
        if ident in seen_ids or condition in seen_conditions:
            raise ValueError("UI cases require unique IDs and distinct test conditions")
        seen_ids.add(ident)
        seen_conditions.add(condition)
    return value


def _observations(manifest: dict, case_ids: set[str]) -> dict[str, dict]:
    values = manifest.get("ui_observations", [])
    if type(values) is not list or len(values) > MAX_CASES:
        raise ValueError("ui_observations must be a list of at most twelve observations")
    found: dict[str, dict] = {}
    views: set[str] = set()
    for item in values:
        obj = _object(item, _OBS_KEYS - {"trace_sha256"}, _OBS_KEYS, "UI observation")
        ident = _identifier(obj["case"], "observation case")
        view = _view_id(obj["view"])
        if ident not in case_ids or ident in found or view in views:
            raise ValueError("Observations require known, unique cases and distinct view references")
        _labels(obj)
        scale = obj["pixel_ratio"]
        if type(scale) not in (int, float) or not 1 <= scale <= 4 or not math.isfinite(scale):
            raise ValueError("pixel_ratio must be a finite PNG-to-viewport scale from 1 to 4")
        _source_hashes(obj["sources_sha256"], "observation sources_sha256")
        _digest(obj["capture_sha256"], "observation capture_sha256")
        if "trace_sha256" in obj:
            _digest(obj["trace_sha256"], "observation trace_sha256")
        found[ident] = obj
        views.add(view)
    return found


def _verified_inputs(evidence: dict, manifest: dict) -> tuple[dict, dict, dict[str, set[str]]]:
    if type(evidence) is not dict or type(manifest) is not dict:
        raise ValueError("Verified evidence and manifest must be objects")
    sources = _source_hashes(evidence.get("sources_sha256"), "verified sources_sha256")
    captures = evidence.get("captures")
    if type(captures) is not dict or not 1 <= len(captures) <= MAX_CASES:
        raise ValueError("Verified evidence requires one to twelve captures")
    for name, capture in captures.items():
        _view_id(name)
        if type(capture) is not dict:
            raise ValueError("Verified captures must be objects")
        _digest(capture.get("sha256"), "verified capture sha256")
        for dim in ("width", "height"):
            if type(capture.get(dim)) is not int or not 200 <= capture[dim] <= 8192:
                raise ValueError("Verified PNG dimensions are outside supported bounds")
        if capture["width"] * capture["height"] > 16_000_000:
            raise ValueError("Verified PNG exceeds the pixel budget")
    layout = manifest.get("layout", {})
    if type(layout) is not dict or len(layout) > MAX_CASES:
        raise ValueError("Layout evidence must be a bounded per-view object")
    elements: dict[str, set[str]] = {}
    for view, items in layout.items():
        if view not in captures or type(items) is not list or len(items) > 120:
            raise ValueError("Layout evidence must refer to captured views with bounded elements")
        found: set[str] = set()
        for item in items:
            if type(item) is not dict:
                raise ValueError("Layout elements must be objects")
            ident = _identifier(item.get("id"), "layout element")
            if ident in found:
                raise ValueError("Layout element IDs must be unique within a view")
            found.add(ident)
        elements[view] = found
    return sources, captures, elements


def _trace_events(trace: dict | None, trace_sha256: str | None) -> list[dict]:
    if trace is None:
        if trace_sha256 is not None:
            raise ValueError("A trace digest requires its parsed trace")
        return []
    if type(trace) is not dict or type(trace.get("run_finished")) is not bool:
        raise ValueError("Trace must provide a boolean run_finished flag")
    if trace_sha256 is not None:
        _digest(trace_sha256, "verified trace_sha256")
    _choice(trace.get("engine"), frozenset({"roblox", "web", "godot", "unity", "unreal", "blender", "other"}),
            "trace engine")
    if "sources_sha256" in trace:
        _source_hashes(trace["sources_sha256"], "trace sources_sha256")
    events = trace.get("events")
    if type(events) is not list or len(events) > MAX_EVENTS:
        raise ValueError("Trace events must be a list of at most five hundred events")
    previous = -1.0
    for event in events:
        if type(event) is not dict:
            raise ValueError("Trace events must be objects")
        _identifier(event.get("name"), "trace event name")
        timestamp = event.get("t_ms")
        if (not isinstance(timestamp, (int, float)) or isinstance(timestamp, bool)
                or not 0 <= timestamp <= 3_600_000
                or not math.isfinite(timestamp) or timestamp < previous):
            raise ValueError("Trace timestamps must be finite, bounded and in time order")
        previous = timestamp
        if "case_id" in event:
            _identifier(event["case_id"], "trace case_id")
        if "capture_sha256" in event:
            _digest(event["capture_sha256"], "trace capture_sha256")
    return events


def inspect_contract(contract: dict, manifest: dict, evidence: dict, *, trace: dict | None = None,
                     trace_sha256: str | None = None) -> dict:
    """Compare required cases with declarations tied to verified files and hashes.

    Call only after capture_evidence has read and hashed the actual source/PNG
    files. This pure function cannot establish how those files were produced.
    ``pixel_ratio`` is PNG pixels per viewport unit, not necessarily the browser's
    devicePixelRatio (a CSS-scale screenshot is 1 even on a Retina display).
    Existing layout rectangles remain in captured PNG pixels; no CSS target-size
    or keyboard/reduced-motion conformance is inferred here. Roblox dimensions
    start at 200 rendered pixels to match the PNG collector at scale 1; web
    dimensions can start at 100 CSS pixels when captured at sufficient scale.
    """
    requirements = validate_contract(contract)
    sources, captures, elements = _verified_inputs(evidence, manifest)
    observations = _observations(manifest, {case["id"] for case in requirements["cases"]})
    events = _trace_events(trace, trace_sha256)
    findings: list[dict] = []
    cases: list[dict] = []
    checks = 0

    for case in requirements["cases"]:
        ident = case["id"]
        observation = observations.get(ident)
        view = observation["view"] if observation else None
        start = len(findings)

        def finding(code: str, status: str, message: str, **details) -> None:
            findings.append({"code": code, "status": status, "case": ident,
                             **({"view": view} if view else {}), "message": message, **details})

        if observation is None:
            finding("ui_case_unverified", "review", "Capture and describe this required UI case.")
        else:
            mismatched = [key for key in _LABELS if observation[key] != case[key]]
            checks += 1
            if mismatched:
                finding("ui_condition_mismatch", "fail", "Observation labels contradict the required test condition.",
                        fields=mismatched)
            checks += 1
            if observation["sources_sha256"] != sources:
                finding("ui_sources_stale", "fail", "Observation does not bind the complete current source set.")
            capture = captures.get(view)
            if capture is None:
                finding("ui_capture_unverified", "review", "The observation needs a verified PNG capture.")
            else:
                checks += 2
                if observation["capture_sha256"] != capture["sha256"]:
                    finding("ui_capture_stale", "fail", "Observation references different screenshot bytes.")
                ratio = observation["pixel_ratio"]
                expected = {dim: math.floor(case["viewport"][dim] * ratio + 0.5) for dim in ("width", "height")}
                if requirements["target"] == "roblox" and ratio != 1:
                    finding("ui_pixel_scale_mismatch", "fail", "Roblox rendered-pixel viewports require pixel_ratio 1.")
                if any(capture[dim] != expected[dim] for dim in expected):
                    finding("ui_viewport_mismatch", "fail", "PNG dimensions do not match the required viewport and capture scale.",
                            expected_png=expected)
                missing = [name for name in case["elements"] if name not in elements.get(observation["view"], set())]
                checks += 1
                if missing:
                    finding("ui_elements_unverified", "review", "Add layout evidence for these required elements.",
                            elements=missing)

            if "events" in case:
                if trace is None or not trace["run_finished"]:
                    finding("ui_trace_unverified", "review", "This case requires a completed run trace.")
                elif trace_sha256 is None or "trace_sha256" not in observation or "sources_sha256" not in trace:
                    finding("ui_trace_binding_unverified", "review", "Bind the trace digest and its complete source set.")
                else:
                    checks += 1
                    bound = True
                    if observation["trace_sha256"] != trace_sha256 or trace["sources_sha256"] != sources:
                        bound = False
                        finding("ui_trace_stale", "fail", "Trace bytes or trace source binding do not match current evidence.")
                    if trace["engine"] != requirements["target"]:
                        bound = False
                        finding("ui_trace_engine_mismatch", "fail", "Trace engine contradicts the required UI target.")
                    case_events = [event for event in events if event.get("case_id") == ident]
                    if not case_events:
                        bound = False
                        finding("ui_case_events_unverified", "review", "Recorded events need this case_id and capture binding.")
                    elif any("capture_sha256" not in event for event in case_events):
                        bound = False
                        finding("ui_event_binding_unverified", "review", "Every event for this case needs its capture digest.")
                    elif capture is None or any(event["capture_sha256"] != capture["sha256"] for event in case_events):
                        bound = False
                        finding("ui_event_capture_stale", "fail", "Case events refer to a different or unverified capture.")
                    if bound:
                        checks += 1
                        remaining = iter(case["events"])
                        wanted = next(remaining, None)
                        for event in case_events:
                            if event["name"] == wanted:
                                wanted = next(remaining, None)
                        if wanted is not None:
                            finding("ui_event_sequence_missing", "fail", "Completed bound trace lacks the required ordered event sequence.",
                                    expected_events=case["events"])

        local = findings[start:]
        status = ("failed" if any(item["status"] == "fail" for item in local) else
                  "unverified" if local else "declared_evidence_complete")
        cases.append({"id": ident, "status": status, **({"view": view} if view else {}),
                      "finding_codes": [item["code"] for item in local]})

    failed = sum(item["status"] == "fail" for item in findings)
    unverified = sum(item["status"] == "review" for item in findings)
    return {
        "version": 1, "target": requirements["target"],
        "status": ("automated_checks_failed" if failed else "insufficient_evidence" if unverified else
                   "declared_coverage_complete"),
        "case_count": len(cases), "complete_count": sum(case["status"] == "declared_evidence_complete" for case in cases),
        "automated_check_count": checks, "failed_count": failed, "unverified_count": unverified,
        "cases": cases, "findings": findings,
        "runtime_executed_by_this_tool": False, "capture_authenticity_proven": False,
        "accessibility_conformance_proven": False, "motion_preference_honored_proven": False, "owner_approved": False,
        "limits": [
            "Source, capture and trace hashes detect changed bytes; supplied declarations are not authenticated execution receipts.",
            "Screen, state, input and motion conditions are declared; matching labels do not prove keyboard behavior or reduced motion.",
            "Required element IDs refer to supplied layout records, not recognition of controls in screenshot pixels.",
            "Existing layout rectangles use PNG pixels; this contract does not establish CSS target-size or accessibility conformance.",
            "Coverage is limited to these explicit cases and checks, not aesthetic approval or completeness of the entire product.",
        ],
    }
