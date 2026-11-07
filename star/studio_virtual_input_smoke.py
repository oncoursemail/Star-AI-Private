"""Bounded, offline compiler for real-input smoke tests in private Roblox Studio.

Generates a reviewable CLIENT LocalScript that uses Roblox's documented
UserInputService:CreateVirtualInput / VirtualInput:SendKey API. Never executes
Roblox, creates a Studio session, sends OS input, or signs a playthrough event.

Client console output is UNTRUSTED candidate evidence. Parsing it cannot
advance StudioPlaythroughGate; only a separate authenticated host observer can.
Feature OFF by default; generated code must be manually installed and run in
an owner-authorized, private Studio test.
"""
from __future__ import annotations

from typing import cast

from dataclasses import dataclass
import hashlib
import json
import math
import re

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_KEYS = frozenset({"W", "A", "S", "D", "Q", "E", "F", "R", "SPACE"})
_LOG_PREFIX = "STAR_STUDIO_INPUT_SMOKE "
_DOMAIN = b"star.studio.virtual_input.smoke.v1\x00"


def _real(value: object, field: str, minimum: float, maximum: float) -> float:
    if type(value) not in (int, float):
        raise ValueError(f"{field} must be a finite number")
    number = float(cast(int | float, value))
    if not math.isfinite(number):
        raise ValueError(f"{field} must be a finite number")
    if not minimum <= number <= maximum:
        raise ValueError(f"{field} outside permitted range")
    return number


@dataclass(frozen=True)
class VirtualInputStep:
    """Owner-curated key pulse and optional horizontal gameplay motion check."""

    key: str
    hold_ms: int = 120
    min_horizontal_studs: float = 0.0

    def __post_init__(self) -> None:
        if type(self.key) is not str or self.key not in _KEYS:
            raise ValueError("not an allowed gameplay key")
        if type(self.hold_ms) is not int or not 30 <= self.hold_ms <= 180:
            raise ValueError("key pulse must be 30..180ms")
        _real(self.min_horizontal_studs, "minimum horizontal distance", 0, 10)
        if self.min_horizontal_studs and self.key not in {"W", "A", "S", "D"}:
            raise ValueError("horizontal displacement check requires movement key")


@dataclass(frozen=True)
class VirtualInputSmokePlan:
    """Immutable plan created by the host, never by the candidate model/game."""

    run_id: str
    steps: tuple[VirtualInputStep, ...]
    warmup_ms: int = 650

    def __post_init__(self) -> None:
        if type(self.run_id) is not str or _ID.fullmatch(self.run_id) is None:
            raise ValueError("invalid opaque run ID")
        if (type(self.steps) is not tuple or not 1 <= len(self.steps) <= 8
                or any(not isinstance(step, VirtualInputStep) for step in self.steps)):
            raise ValueError("1..8 curated input steps required")
        if type(self.warmup_ms) is not int or not 100 <= self.warmup_ms <= 2500:
            raise ValueError("warmup must be 100..2500ms")

    @property
    def digest(self) -> str:
        payload = {
            "run_id": self.run_id,
            "steps": [{"key": s.key, "hold_ms": s.hold_ms,
                       "min_horizontal_studs": float(s.min_horizontal_studs)}
                      for s in self.steps],
            "warmup_ms": self.warmup_ms,
        }
        return hashlib.sha256(_DOMAIN + json.dumps(
            payload, sort_keys=True, allow_nan=False, separators=(",", ":")
        ).encode("ascii")).hexdigest()


@dataclass(frozen=True)
class InputSmokeSample:
    key: str
    began: bool
    ended: bool
    released: bool
    horizontal_studs: float
    passed: bool


@dataclass(frozen=True)
class InputSmokeReport:
    """Parsed CLIENT claim, NOT a signed or independently verified outcome."""

    run_id: str
    plan_sha256: str
    samples: tuple[InputSmokeSample, ...]
    candidate_passed: bool
    independent_gameplay_verified: bool = False


def compile_virtual_input_local_script(plan: VirtualInputSmokePlan, *,
                                       owner_approved: bool = False) -> str:
    """Generate a private Studio-only LocalScript without controlling any game.

    The caller must review and install this separately in StarterPlayerScripts
    for a *private* test. The script is intentionally incapable of accessing
    the chat, CoreGui, remote hosts, credentials, or a public Roblox session.
    """
    if not isinstance(plan, VirtualInputSmokePlan):
        raise TypeError("expected an immutable trusted-host plan")
    if owner_approved is not True:
        raise PermissionError("explicit owner approval needed to compile Studio input")
    steps = "\n".join(
        "    { key = Enum.KeyCode.%s, label = %s, hold_s = %.3f, min_motion = %.5f },"
        % ("Space" if s.key == "SPACE" else s.key,
           json.dumps(s.key), s.hold_ms / 1000, s.min_horizontal_studs)
        for s in plan.steps
    )
    # All interpolation is constrained: alphanumeric ID, allowlisted enum names,
    # finite positive numbers. No raw game/model/user text is embedded.
    lua = r'''-- STAR private Studio-only local input smoke test. Owner-reviewed.
-- Install as a LocalScript in StarterPlayerScripts for a disposable test place.
-- Output is ONLY candidate evidence; it cannot sign a playthrough receipt.
local RunService = game:GetService("RunService")
if not RunService:IsStudio() then return end

local Players = game:GetService("Players")
local UserInputService = game:GetService("UserInputService")
local HttpService = game:GetService("HttpService")
local RUN_ID = "__RUN_ID__"
local PLAN_SHA256 = "__PLAN_SHA__"
local steps = {
__STEPS__
}

local samples = {}
local function emit(passed)
    print("STAR_STUDIO_INPUT_SMOKE " .. HttpService:JSONEncode({
        run_id = RUN_ID, plan_sha256 = PLAN_SHA256,
        steps = samples, passed = passed,
    }))
end

if not game:IsLoaded() then game.Loaded:Wait() end
task.wait(__WARMUP_S__)
local player = Players.LocalPlayer
if not player then
    emit(false)
    return
end
local creationOK, virtual = pcall(function()
    return UserInputService:CreateVirtualInput()
end)
if not creationOK or not virtual then
    emit(false)
    return
end

local overall = true
for _, step in ipairs(steps) do
    -- Prevent typing into a UI field and never target Roblox CoreGui.
    if UserInputService:GetFocusedTextBox() ~= nil then
        overall = false
        break
    end

    local before = nil
    local root = nil
    if step.min_motion > 0 then
        local character = player.Character
        root = character and character:FindFirstChild("HumanoidRootPart")
        if root then before = root.Position end
    end

    local began, ended, released = false, false, false
    local beginConnection = UserInputService.InputBegan:Connect(function(input)
        if input.KeyCode == step.key then began = true end
    end)
    local endConnection = UserInputService.InputEnded:Connect(function(input)
        if input.KeyCode == step.key then ended = true end
    end)

    local downOK = pcall(function()
        virtual:SendKey(true, step.key, false)
    end)
    -- A separate bounded watchdog attempts key-up if the normal release fails.
    task.delay(0.4, function()
        if not released then
            pcall(function() virtual:SendKey(false, step.key, false) end)
        end
    end)
    if downOK then task.wait(step.hold_s) end
    local upOK = pcall(function()
        virtual:SendKey(false, step.key, false)
    end)
    released = upOK
    task.wait(0.06)
    beginConnection:Disconnect()
    endConnection:Disconnect()

    local motion = 0
    if before and root and root.Parent then
        local after = root.Position
        motion = (Vector3.new(after.X - before.X, 0, after.Z - before.Z)).Magnitude
    end
    local passed = downOK and upOK and began and ended
        and motion >= step.min_motion
    table.insert(samples, {
        key = step.label, began = began, ended = ended,
        released = released, horizontal_studs = motion, passed = passed,
    })
    if not passed then
        overall = false
        break
    end
end
emit(overall and #samples == #steps)
'''
    return (lua.replace("__RUN_ID__", plan.run_id)
            .replace("__PLAN_SHA__", plan.digest)
            .replace("__STEPS__", steps)
            .replace("__WARMUP_S__", f"{plan.warmup_ms / 1000:.3f}"))


def parse_virtual_input_log(plan: VirtualInputSmokePlan, line: str) -> InputSmokeReport:
    """Strictly parse one candidate client log; never authenticate it.

    Rejects cross-plan data, oversized output, inconsistent claims, non-finite
    measurements, duplicate/reordered steps, and unbounded input. Parsing
    cannot substitute for host-verified game observations or replay receipts.
    """
    if not isinstance(plan, VirtualInputSmokePlan):
        raise TypeError("expected a trusted-host plan")
    if type(line) is not str or not line.startswith(_LOG_PREFIX) or len(line) > 8192:
        raise ValueError("missing or oversized input smoke record")

    def reject_constant(_value: str) -> None:
        raise ValueError("non-finite JSON")
    try:
        record = json.loads(line[len(_LOG_PREFIX):], parse_constant=reject_constant)
    except (ValueError, TypeError) as exc:
        raise ValueError("malformed input smoke JSON") from exc
    if not isinstance(record, dict) or set(record) != {
        "run_id", "plan_sha256", "steps", "passed"
    } or record["run_id"] != plan.run_id or record["plan_sha256"] != plan.digest:
        raise ValueError("cross-plan or invalid input smoke schema")
    rows = record["steps"]
    if type(rows) is not list or len(rows) > len(plan.steps):
        raise ValueError("invalid input smoke step count")
    samples: list[InputSmokeSample] = []
    for i, row in enumerate(rows):
        if type(row) is not dict or set(row) != {
            "key", "began", "ended", "released", "horizontal_studs", "passed"
        } or row["key"] != plan.steps[i].key:
            raise ValueError("reordered or malformed input observation")
        if any(type(row[k]) is not bool for k in
               ("began", "ended", "released", "passed")):
            raise ValueError("input flags must be booleans")
        distance = _real(row["horizontal_studs"], "horizontal distance", 0, 1000)
        locally_passed = (row["began"] and row["ended"] and row["released"]
                          and distance >= plan.steps[i].min_horizontal_studs)
        if row["passed"] is not locally_passed:
            raise ValueError("contradictory client input claim")
        samples.append(InputSmokeSample(
            row["key"], row["began"], row["ended"], row["released"],
            distance, locally_passed,
        ))
    passed = len(samples) == len(plan.steps) and all(s.passed for s in samples)
    if type(record["passed"]) is not bool or record["passed"] is not passed:
        raise ValueError("inconsistent aggregate smoke result")
    return InputSmokeReport(plan.run_id, plan.digest, tuple(samples), passed)


__all__ = [
    "VirtualInputStep", "VirtualInputSmokePlan", "InputSmokeSample",
    "InputSmokeReport", "compile_virtual_input_local_script",
    "parse_virtual_input_log",
]
