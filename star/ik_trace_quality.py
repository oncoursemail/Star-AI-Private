"""Offline diagnostics for supplied IK traces; no solver, capture, or quality gate.

Run ``python -m star.ik_trace_quality trace.json``. The version-1 JSON schema is:
``{schema_version: 1, rig_scale: positive_number, chains: [{name, samples}]}``.
Each sample requires ``t`` (seconds), ``effector`` and ``target`` (xyz lists in
one consistent coordinate frame). Optional quaternion pairs ``effector_q`` /
``target_q`` use xyzw order and must be unit length within 0.001.

Optional ``contact`` is boolean. When true, all three contact observation keys
may be supplied: ``contact_frame`` (stable support-frame identifier),
``contact_position`` and ``contact_anchor`` (xyz, BOTH in that support's local
frame). An anchor must stay fixed across adjacent observations of one contact.
False/absent contact, missing observations, or a changed support frame breaks
the measured span. Reacquisition starts a new span; gaps are never interpolated.

Coordinates are bounded to +/-1e9, rig_scale to 1e-6..1e6, timestamps to
0..86400 with >=1e-6 seconds between samples (one timestamp ULP tolerance).
At most 64 chains, 10000 samples
per chain and 20000 total samples are accepted. Unknown fields are rejected.
The CLI reads at most 8 MiB from a regular file. The pure API expects an already decoded JSON value.
Missing observations produce null metrics with sample count zero, never a pass.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import stat
import sys

MAX_CHAINS = 64
MAX_SAMPLES = 10000
MAX_TOTAL_SAMPLES = 20000
MAX_FILE_BYTES = 8 * 1024 * 1024
_CONTACT_KEYS = {"contact_frame", "contact_position", "contact_anchor"}
_OPTIONAL_KEYS = {"effector_q", "target_q", "contact"} | _CONTACT_KEYS
_LIMITATIONS = (
    "Diagnostics describe supplied observations, not independently verified engine capture.",
    "No solver, bone-length, collision, skinning, balance, or visual-appeal validation is performed.",
    "Contact coordinates must share the declared support-local frame; this cannot be inferred from JSON.",
    "Angular rates use shortest arcs between samples; undersampling can hide full rotations.",
    "No quality threshold, promotion decision, or runtime setting is changed.",
)


def _object(value: object, required: set[str], optional: set[str], label: str) -> dict:
    if type(value) is not dict or any(type(key) is not str for key in value):
        raise ValueError(f"{label} must be a JSON object")
    if not required <= value.keys() or value.keys() - required - optional:
        raise ValueError(f"{label} has missing or unsupported fields")
    return value


def _number(value: object, label: str, minimum: float = -1e9, maximum: float = 1e9) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not minimum <= value <= maximum:
        raise ValueError(f"{label} must be a finite number in {minimum}..{maximum}")
    return float(value)


def _name(value: object, label: str) -> str:
    if type(value) is not str or not 1 <= len(value) <= 128 or not value.isprintable():
        raise ValueError(f"{label} must be a printable string of 1..128 characters")
    return value


def _vector(value: object, count: int, label: str, *, unit: bool = False) -> tuple[float, ...]:
    if type(value) is not list or len(value) != count:
        raise ValueError(f"{label} must be a JSON array of {count} numbers")
    result = tuple(_number(item, label) for item in value)
    if unit:
        length = math.hypot(*result)
        if abs(length - 1.0) > 0.001:
            raise ValueError(f"{label} must be a unit quaternion in xyzw order")
        result = tuple(item / length for item in result)
    return result


def _sample(value: object, label: str) -> dict:
    raw = _object(value, {"t", "effector", "target"}, _OPTIONAL_KEYS, label)
    result = {
        "t": _number(raw["t"], f"{label}.t", 0, 86400),
        "effector": _vector(raw["effector"], 3, f"{label}.effector"),
        "target": _vector(raw["target"], 3, f"{label}.target"),
    }
    quaternions = {"effector_q", "target_q"} & raw.keys()
    if quaternions and len(quaternions) != 2:
        raise ValueError(f"{label} requires both quaternion observations or neither")
    for key in quaternions:
        result[key] = _vector(raw[key], 4, f"{label}.{key}", unit=True)
    if "contact" in raw:
        if type(raw["contact"]) is not bool:
            raise ValueError(f"{label}.contact must be boolean")
        result["contact"] = raw["contact"]
    contact_keys = _CONTACT_KEYS & raw.keys()
    if contact_keys:
        if contact_keys != _CONTACT_KEYS or raw.get("contact") is not True:
            raise ValueError(f"{label} requires all contact observations and contact=true")
        result["contact_frame"] = _name(raw["contact_frame"], f"{label}.contact_frame")
        for key in ("contact_position", "contact_anchor"):
            result[key] = _vector(raw[key], 3, f"{label}.{key}")
    return result


def _difference(left: tuple, right: tuple) -> tuple[float, ...]:
    return tuple(a - b for a, b in zip(left, right))


def _distance(left: tuple, right: tuple) -> float:
    return math.hypot(*_difference(left, right))


def _angle(left: tuple, right: tuple) -> float:
    # The shorter quaternion chord identifies q and -q as one rotation. This
    # atan2 form stays accurate near zero, where acos(dot) loses precision.
    difference = math.hypot(*_difference(left, right))
    total = math.hypot(*(a + b for a, b in zip(left, right)))
    return math.degrees(4.0 * math.atan2(min(difference, total), max(difference, total)))


def _summary(values: list[float]) -> dict:
    if not values:
        return {"samples": 0, "mean": None, "rms": None, "p95": None, "max": None}
    ordered = sorted(values)
    return {
        "samples": len(values),
        "mean": math.fsum(values) / len(values),
        "rms": math.sqrt(math.fsum(item * item for item in values) / len(values)),
        "p95": ordered[math.ceil(0.95 * len(values)) - 1],
        "max": ordered[-1],
    }


def _chain_report(raw: dict, scale: float, index: int) -> dict:
    names = (
        "position_error_rig", "orientation_error_deg", "step_displacement_rig",
        "speed_rig_per_second", "velocity_change_rig_per_second",
        "acceleration_rig_per_second2", "angular_step_deg", "angular_speed_deg_per_second",
        "contact_error_rig", "contact_drift_rig", "contact_slip_speed_rig_per_second",
    )
    values: dict[str, list[float]] = {key: [] for key in names}
    previous = previous_velocity = first_contact_position = None
    previous_dt = first_time = last_time = None
    contact_true_samples = contact_known_samples = contact_spans = 0
    for sample_index, value in enumerate(raw["samples"]):
        frame = _sample(value, f"chains[{index}].samples[{sample_index}]")
        last_time = frame["t"]
        if first_time is None:
            first_time = last_time
        values["position_error_rig"].append(_distance(frame["effector"], frame["target"]) / scale)
        if "effector_q" in frame:
            values["orientation_error_deg"].append(_angle(frame["effector_q"], frame["target_q"]))
        dt = None
        if previous is not None:
            dt = frame["t"] - previous["t"]
            resolution = max(math.ulp(frame["t"]), math.ulp(previous["t"]))
            if dt <= 0 or dt < 1e-6 - resolution:
                raise ValueError("timestamps must increase by at least 1e-6 seconds within each chain")
            delta = _difference(frame["effector"], previous["effector"])
            velocity = tuple(item / dt / scale for item in delta)
            values["step_displacement_rig"].append(math.hypot(*delta) / scale)
            values["speed_rig_per_second"].append(math.hypot(*velocity))
            if previous_velocity is not None:
                change = _distance(velocity, previous_velocity)
                values["velocity_change_rig_per_second"].append(change)
                # Velocities live at interval midpoints; this is their actual time separation.
                values["acceleration_rig_per_second2"].append(change / ((dt + previous_dt) / 2))
            previous_velocity, previous_dt = velocity, dt
            if "effector_q" in frame and "effector_q" in previous:
                angle = _angle(frame["effector_q"], previous["effector_q"])
                values["angular_step_deg"].append(angle)
                values["angular_speed_deg_per_second"].append(angle / dt)
        contact_known_samples += "contact" in frame
        contact_true_samples += frame.get("contact") is True
        if "contact_position" in frame:
            position, anchor = frame["contact_position"], frame["contact_anchor"]
            values["contact_error_rig"].append(_distance(position, anchor) / scale)
            same_span = (previous is not None and "contact_position" in previous
                         and previous["contact_frame"] == frame["contact_frame"])
            if same_span:
                assert previous is not None and dt is not None and first_contact_position is not None
                if anchor != previous["contact_anchor"]:
                    raise ValueError("contact_anchor must stay fixed within a continuous support-frame span")
                values["contact_drift_rig"].append(_distance(position, first_contact_position) / scale)
                values["contact_slip_speed_rig_per_second"].append(
                    _distance(position, previous["contact_position"]) / dt / scale)
            else:
                first_contact_position = position
                contact_spans += 1
        else:
            first_contact_position = None
        previous = frame
    assert first_time is not None and last_time is not None     # samples are validated as non-empty
    return {
        "name": raw["name"], "sample_count": len(raw["samples"]),
        "duration_seconds": last_time - first_time,
        "contact_state_observations": contact_known_samples,
        "contact_true_observations": contact_true_samples,
        "measured_contact_spans": contact_spans,
        "metrics": {key: _summary(items) for key, items in values.items()},
    }


def report_ik_trace(payload: object) -> dict:
    """Validate and summarize a bounded trace without I/O or changing its input.

    All distances/rates are normalized by rig_scale; angular measures use degrees.
    Statistics weight each observation equally, not by elapsed duration. Temporal
    rates use actual adjacent timestamps. Missing data is never filled in.
    Raises ValueError for malformed input. This function makes no pass/fail claim.
    """
    raw = _object(payload, {"schema_version", "rig_scale", "chains"}, set(), "trace")
    if type(raw["schema_version"]) is not int or raw["schema_version"] != 1:
        raise ValueError("schema_version must be integer 1")
    scale = _number(raw["rig_scale"], "rig_scale", 1e-6, 1e6)
    chains = raw["chains"]
    if type(chains) is not list or not 1 <= len(chains) <= MAX_CHAINS:
        raise ValueError(f"chains must contain 1..{MAX_CHAINS} entries")
    seen: set[str] = set()
    total = 0
    for index, value in enumerate(chains):
        chain = _object(value, {"name", "samples"}, set(), f"chains[{index}]")
        name = _name(chain["name"], f"chains[{index}].name")
        if name in seen:
            raise ValueError("chain names must be unique")
        seen.add(name)
        if type(chain["samples"]) is not list or not 1 <= len(chain["samples"]) <= MAX_SAMPLES:
            raise ValueError(f"each chain must contain 1..{MAX_SAMPLES} samples")
        total += len(chain["samples"])
        if total > MAX_TOTAL_SAMPLES:
            raise ValueError(f"trace exceeds {MAX_TOTAL_SAMPLES} total samples")
    return {
        "schema_version": 1, "rig_scale": scale, "total_samples": total,
        "chains": [_chain_report(chain, scale, index) for index, chain in enumerate(chains)],
        "engine_capture_verified": False, "quality_proven": False,
        "limitations": list(_LIMITATIONS),
    }


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object keys are not allowed")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError("non-finite JSON constants are not allowed")


def _read_trace(path: Path) -> bytes:
    if not path.is_file():
        raise ValueError("trace must be a regular file")
    # A nonblocking open also avoids a POSIX FIFO race after the initial check.
    def opener(name: str, flags: int) -> int:
        return os.open(name, flags | getattr(os, "O_NONBLOCK", 0))
    with open(path, "rb", opener=opener) as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("trace must be a regular file")
        data = stream.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise ValueError(f"trace exceeds the {MAX_FILE_BYTES}-byte limit")
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path, help="Path to a version-1 IK trace JSON file")
    args = parser.parse_args(argv)
    try:
        data = _read_trace(args.trace)
        payload = json.loads(data, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
        report = report_ik_trace(payload)
    except (OSError, ValueError, RecursionError) as error:
        print(f"IK trace error: {error}", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
