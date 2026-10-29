"""Contract and adversarial tests for bounded Roblox VirtualInput smoke artifact."""
from __future__ import annotations

from dataclasses import replace
import json
import math
import re

import pytest

from star.studio_virtual_input_smoke import (
    VirtualInputSmokePlan, VirtualInputStep, compile_virtual_input_local_script,
    parse_virtual_input_log,
)

PREFIX = "STAR_STUDIO_INPUT_SMOKE "


def plan():
    return VirtualInputSmokePlan(
        "test-build-07",
        (VirtualInputStep("W", 130, 0.2), VirtualInputStep("E", 75)),
    )


def results(p, *, passed=True):
    rows = [
        {
            "key": s.key, "began": passed, "ended": passed,
            "released": True, "horizontal_studs": max(.4, s.min_horizontal_studs),
            "passed": passed,
        } for s in p.steps
    ]
    return {
        "run_id": p.run_id, "plan_sha256": p.digest,
        "steps": rows, "passed": passed,
    }


def line(payload):
    return PREFIX + json.dumps(payload, separators=(",", ":"), allow_nan=True)


def test_generates_studio_guarded_real_virtual_input_client_script():
    p = plan()
    script = compile_virtual_input_local_script(p, owner_approved=True)
    assert 'if not RunService:IsStudio() then return end' in script
    assert 'UserInputService:CreateVirtualInput()' in script
    assert 'virtual:SendKey(true, step.key, false)' in script
    assert 'virtual:SendKey(false, step.key, false)' in script
    assert "InputBegan:Connect" in script
    assert "InputEnded:Connect" in script
    assert "task.delay(0.4" in script
    assert "task.wait(0.060)" not in script  # exact bounded settle, no branch on LLM
    assert "HttpService:JSONEncode" in script
    assert p.digest in script and p.run_id in script
    assert "Enum.KeyCode.W" in script
    assert "Enum.KeyCode.E" in script
    assert "min_motion = 0.20000" in script
    assert "__RUN_ID__" not in script and "__STEPS__" not in script
    assert all(k not in script for k in (
        "HttpService:PostAsync", "TeleportService", "DataStoreService",
        "loadstring(", "writefile(", "VirtualInputManager",
    ))


def test_compilation_is_explicitly_opted_in_and_has_no_side_effects():
    p = plan()
    with pytest.raises(PermissionError):
        compile_virtual_input_local_script(p)
    with pytest.raises(PermissionError):
        compile_virtual_input_local_script(p, owner_approved=1)
    with pytest.raises(TypeError):
        compile_virtual_input_local_script("fake", owner_approved=True)
    assert compile_virtual_input_local_script(p, owner_approved=True) == (
        compile_virtual_input_local_script(p, owner_approved=True))


@pytest.mark.parametrize("key", [
    "Escape", "Enter", "Chat", "LeftControl", "F4", "Tab",
    "W); loadstring('unsafe')", "Click", "w", "",
])
def test_unallowed_input_codes_rejected(key):
    with pytest.raises(ValueError):
        VirtualInputStep(key)


@pytest.mark.parametrize("hold", [0, 29, 181, 1000, True, 120.1, "100"])
def test_unbounded_and_mistyped_hold_rejected(hold):
    with pytest.raises(ValueError):
        VirtualInputStep("W", hold)


@pytest.mark.parametrize("distance", [
    -1, 11, math.nan, math.inf, -math.inf, True, "0.5",
])
def test_invalid_motion_threshold_rejected(distance):
    with pytest.raises(ValueError):
        VirtualInputStep("W", 100, distance)


def test_only_movement_keys_permit_horizontal_displacement_expectations():
    with pytest.raises(ValueError):
        VirtualInputStep("SPACE", 100, 0.2)
    assert "Enum.KeyCode.Space" in compile_virtual_input_local_script(
        VirtualInputSmokePlan("jump", (VirtualInputStep("SPACE"),)),
        owner_approved=True,
    )


@pytest.mark.parametrize("run", ["", ".unsafe", "A" * 65, "bad\nline", "é"])
def test_run_identifier_cannot_inject_luau(run):
    with pytest.raises(ValueError):
        VirtualInputSmokePlan(run, (VirtualInputStep("W"),))


@pytest.mark.parametrize("steps", [(), (VirtualInputStep("W"),) * 9, [
    VirtualInputStep("W"),
]])
def test_bounded_immutable_step_count(steps):
    with pytest.raises(ValueError):
        VirtualInputSmokePlan("safe", steps)


@pytest.mark.parametrize("warmup", [0, 99, 2501, True, 150.5])
def test_warmup_fails_closed(warmup):
    with pytest.raises(ValueError):
        VirtualInputSmokePlan("safe", (VirtualInputStep("W"),), warmup)


def test_digest_changes_for_every_playthrough_significant_field():
    p = plan()
    digests = {
        p.digest,
        replace(p, run_id="test-build-08").digest,
        replace(p, warmup_ms=651).digest,
        replace(p, steps=(VirtualInputStep("W", 131, 0.2),
                          VirtualInputStep("E", 75))).digest,
        replace(p, steps=(VirtualInputStep("W", 130, 0.3),
                          VirtualInputStep("E", 75))).digest,
        replace(p, steps=tuple(reversed(p.steps))).digest,
    }
    assert len(digests) == 6
    assert re.fullmatch(r"[0-9a-f]{64}", p.digest)


def test_complete_candidate_report_requires_ordered_input_begin_end_and_release():
    p = plan()
    parsed = parse_virtual_input_log(p, line(results(p)))
    assert parsed.candidate_passed
    assert parsed.independent_gameplay_verified is False
    assert len(parsed.samples) == 2
    assert parsed.samples[0].horizontal_studs >= 0.2


def test_failed_step_can_be_reported_but_never_claimed_as_passed():
    p = plan()
    r = results(p, passed=False)
    r["steps"] = r["steps"][:1]
    parsed = parse_virtual_input_log(p, line(r))
    assert not parsed.candidate_passed
    assert not parsed.independent_gameplay_verified
    assert len(parsed.samples) == 1


@pytest.mark.parametrize("change", [
    lambda r: r.update(run_id="different-run"),
    lambda r: r.update(plan_sha256="0" * 64),
    lambda r: r.update(steps=r["steps"][::-1]),
    lambda r: r.update(passed=False),
    lambda r: r["steps"][0].update(passed=False),
    lambda r: r["steps"][0].update(released=False),
    lambda r: r["steps"][0].update(horizontal_studs=0),
    lambda r: r["steps"][0].update(horizontal_studs=float("nan")),
    lambda r: r["steps"][0].update(horizontal_studs=float("inf")),
    lambda r: r["steps"][0].update(key="S"),
    lambda r: r["steps"][0].update(began=1),
    lambda r: r["steps"][0].update(unknown="surprise"),
    lambda r: r.update(extra="unknown"),
    lambda r: r.update(steps=r["steps"] + [r["steps"][0]]),
])
def test_forged_or_contradictory_candidate_logs_rejected(change):
    p = plan()
    data = results(p)
    change(data)
    with pytest.raises(ValueError):
        parse_virtual_input_log(p, line(data))


@pytest.mark.parametrize("payload", [
    "",
    "garbage",
    PREFIX + "true",
    PREFIX + '{"bad":',
    PREFIX + " " * 8200,
    "warn " + PREFIX + "{}",
])
def test_malformed_client_output_never_advances_observation(payload):
    with pytest.raises(ValueError):
        parse_virtual_input_log(plan(), payload)


def test_failure_to_emit_any_steps_cannot_be_success():
    p = plan()
    record = results(p, passed=False)
    record["steps"] = []
    report = parse_virtual_input_log(p, line(record))
    assert not report.candidate_passed
    record["passed"] = True
    with pytest.raises(ValueError):
        parse_virtual_input_log(p, line(record))


def test_tampered_negative_and_non_numeric_position_rejected():
    p = plan()
    for invalid in (-.01, "0.7", None, True):
        r = results(p)
        r["steps"][0]["horizontal_studs"] = invalid
        with pytest.raises(ValueError):
            parse_virtual_input_log(p, line(r))