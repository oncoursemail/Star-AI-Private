"""Offline-first, bounded cross-domain animation choreography for STAR.

One declarative source ties Blender Action/NLA *plans* to Roblox animation
marker/VFX/sound/UI/camera events. This module performs NO I/O, no Blender
execution, no Studio writes, no publishing, and no self-approval. NLA strips
and Roblox graph recommendations must be verified in real target software.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any

MAX_SPEC_BYTES = 64_000
MAX_CLIPS = 20
MAX_LAYERS = 32
MAX_CUES = 48
MAX_EVENTS = 256
MAX_FRAMES = 1_800
MIN_MARKER_LAYER_INFLUENCE = 0.05  # Heuristic: native graph event weight can differ.
_ID = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,63}\Z")
_TARGETS = frozenset({"full_body", "upper_body", "face", "secondary"})
_MODES = {"replace": "REPLACE", "add": "ADD", "combine": "COMBINE"}
_CUE_KINDS = frozenset({"vfx", "sound", "camera", "ui"})


def _object(value: Any, keys: set[str], required: set[str], label: str) -> dict:
    if type(value) is not dict or not required <= value.keys() or value.keys() - keys:
        raise ValueError(f"{label}: missing, unexpected, or non-object fields")
    return value


def _id(value: Any, label: str) -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise ValueError(f"{label}: expected safe identifier")
    return value


def _int(value: Any, label: str, low: int, high: int) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{label}: expected integer {low}..{high}")
    return value


def _weight(value: Any, label: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= 1:
        raise ValueError(f"{label}: expected finite weight in (0, 1]")
    return float(value)


def _array(value: Any, label: str, maximum: int, *, minimum: int = 1) -> list:
    if type(value) is not list or not minimum <= len(value) <= maximum:
        raise ValueError(f"{label}: expected {minimum}..{maximum} items")
    return value


def _unique(items: list[dict], label: str) -> None:
    ids = [item["id"] for item in items]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{label}: duplicate IDs")


def _no_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key[:64]}")
        result[key] = value
    return result


def validate_spec(spec: Any) -> dict:
    """Validate and return a detached canonical JSON object, never executable code."""
    if type(spec) is str:
        try:
            text_size = len(spec.encode("utf-8"))
        except UnicodeError as exc:
            raise ValueError("Timeline input is not valid UTF-8") from exc
        if text_size > MAX_SPEC_BYTES:
            raise ValueError("Timeline input is too large")
        try:
            spec = json.loads(spec, object_pairs_hook=_no_duplicate_pairs,
                              parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Non-finite JSON")))
        except (UnicodeError, RecursionError, json.JSONDecodeError) as exc:
            raise ValueError("Malformed timeline JSON") from exc
    if type(spec) is not dict:
        raise ValueError("Timeline must be a JSON object")
    try:
        canonical = json.dumps(spec, sort_keys=True, separators=(",", ":"),
                               ensure_ascii=True, allow_nan=False)
    except (TypeError, ValueError, RecursionError, OverflowError) as exc:
        raise ValueError("Timeline must contain finite, serializable JSON") from exc
    if len(canonical.encode("utf-8")) > MAX_SPEC_BYTES:
        raise ValueError("Timeline JSON exceeds size limit")
    spec = json.loads(canonical, object_pairs_hook=_no_duplicate_pairs)
    _object(spec, {"version", "name", "fps", "total_frames", "clips", "layers", "cues", "budgets"},
            {"version", "name", "fps", "total_frames", "clips", "layers", "cues"}, "timeline")
    if type(spec["version"]) is not int or spec["version"] != 1:
        raise ValueError("Unsupported timeline version")
    _id(spec["name"], "timeline.name")
    _int(spec["fps"], "timeline.fps", 24, 120)
    _int(spec["total_frames"], "timeline.total_frames", 2, MAX_FRAMES)

    clips = _array(spec["clips"], "clips", MAX_CLIPS)
    for clip in clips:
        _object(clip, {"id", "action", "duration", "loop", "target", "markers"},
                {"id", "action", "duration", "loop", "target", "markers"}, "clip")
        _id(clip["id"], "clip.id")
        _id(clip["action"], "clip.action")
        _int(clip["duration"], "clip.duration", 2, MAX_FRAMES)
        if type(clip["loop"]) is not bool or type(clip["target"]) is not str or clip["target"] not in _TARGETS:
            raise ValueError("clip: loop/target invalid")
        markers = _array(clip["markers"], "clip.markers", 24, minimum=0)
        for marker in markers:
            _object(marker, {"id", "frame"}, {"id", "frame"}, "marker")
            _id(marker["id"], "marker.id")
            _int(marker["frame"], "marker.frame", 0, clip["duration"] - 1)
        _unique(markers, f"clip {clip['id']} markers")
    _unique(clips, "clips")
    by_clip = {clip["id"]: clip for clip in clips}

    layers = _array(spec["layers"], "layers", MAX_LAYERS)
    for layer in layers:
        _object(layer, {"id", "clip", "start", "end", "blend", "weight", "fade_in", "fade_out"},
                {"id", "clip", "start", "end", "blend", "weight", "fade_in", "fade_out"}, "layer")
        _id(layer["id"], "layer.id")
        _id(layer["clip"], "layer.clip")
        clip = by_clip.get(layer["clip"])
        if clip is None:
            raise ValueError(f"layer {layer['id']}: unknown clip")
        _int(layer["start"], "layer.start", 0, spec["total_frames"] - 1)
        _int(layer["end"], "layer.end", layer["start"] + 1, spec["total_frames"])
        if type(layer["blend"]) is not str or layer["blend"] not in _MODES:
            raise ValueError("layer.blend: unsupported NLA mode")
        _weight(layer["weight"], "layer.weight")
        _int(layer["fade_in"], "layer.fade_in", 0, MAX_FRAMES)
        _int(layer["fade_out"], "layer.fade_out", 0, MAX_FRAMES)
        span = layer["end"] - layer["start"]
        if layer["fade_in"] + layer["fade_out"] > span:
            raise ValueError("layer fade durations exceed span")
        if span % clip["duration"] or (span != clip["duration"] and not clip["loop"]):
            raise ValueError(f"layer {layer['id']}: span must equal an integral number of clip cycles")
        if clip["target"] != "full_body" and layer["blend"] == "replace":
            # Replace is valid for facial-only F-curves, but warn at audit time instead of rejecting.
            pass
    _unique(layers, "layers")
    by_layer = {layer["id"]: layer for layer in layers}

    cues = _array(spec["cues"], "cues", MAX_CUES, minimum=0)
    occurrences = 0
    for cue in cues:
        _object(cue, {"id", "layer", "marker", "kind", "resource", "offset", "duration", "reduced_motion"},
                {"id", "layer", "marker", "kind", "resource", "offset", "duration"}, "cue")
        _id(cue["id"], "cue.id")
        _id(cue["resource"], "cue.resource")
        if type(cue["kind"]) is not str or cue["kind"] not in _CUE_KINDS:
            raise ValueError("cue.kind: only cosmetic/UI cues supported, never gameplay authority")
        _id(cue["layer"], "cue.layer")
        _id(cue["marker"], "cue.marker")
        layer = by_layer.get(cue["layer"])
        if layer is None:
            raise ValueError(f"cue {cue['id']}: unknown layer")
        clip = by_clip[layer["clip"]]
        marker_by_id = {m["id"]: m["frame"] for m in clip["markers"]}
        if cue["marker"] not in marker_by_id:
            raise ValueError(f"cue {cue['id']}: marker not present in referenced clip")
        _int(cue["offset"], "cue.offset", -60, 60)
        _int(cue["duration"], "cue.duration", 1, MAX_FRAMES)
        if cue["kind"] in {"camera", "ui"}:
            if type(cue.get("reduced_motion")) is not str or cue.get("reduced_motion") not in {"instant", "skip"}:
                raise ValueError("UI/camera cues need explicit reduced-motion behavior")
        elif "reduced_motion" in cue and (type(cue["reduced_motion"]) is not str or cue["reduced_motion"] not in {"instant", "skip"}):
            raise ValueError("Invalid reduced-motion behavior")
        repetitions = (layer["end"] - layer["start"]) // clip["duration"]
        occurrences += repetitions
        if occurrences > MAX_EVENTS:
            raise ValueError("Too many expanded cue occurrences")
        for cycle in range(repetitions):
            at = layer["start"] + cycle * clip["duration"] + marker_by_id[cue["marker"]] + cue["offset"]
            if at < 0 or at + cue["duration"] > spec["total_frames"]:
                raise ValueError(f"cue {cue['id']}: event runs outside timeline")
    _unique(cues, "cues")

    budgets = spec.get("budgets", {})
    _object(budgets, {"max_vfx", "max_ui", "max_camera", "max_sound", "require_base_pose"}, set(), "budgets")
    for key in ("max_vfx", "max_ui", "max_camera", "max_sound"):
        if key in budgets:
            _int(budgets[key], f"budgets.{key}", 0, 32)
    if "require_base_pose" in budgets and type(budgets["require_base_pose"]) is not bool:
        raise ValueError("require_base_pose must be boolean")
    return spec


def expand_cues(spec: dict | str) -> list[dict]:
    """Expand named clip markers into deterministic global frame cues."""
    data = validate_spec(spec)
    clips = {c["id"]: c for c in data["clips"]}
    layers = {l["id"]: l for l in data["layers"]}
    expanded = []
    for cue in data["cues"]:
        layer = layers[cue["layer"]]
        clip = clips[layer["clip"]]
        mark = next(m["frame"] for m in clip["markers"] if m["id"] == cue["marker"])
        count = (layer["end"] - layer["start"]) // clip["duration"]
        for cycle in range(count):
            expanded.append({"id": cue["id"], "at_frame": layer["start"] + cycle * clip["duration"] + mark + cue["offset"],
                             "until_frame": layer["start"] + cycle * clip["duration"] + mark + cue["offset"] + cue["duration"],
                             "iteration": cycle, "kind": cue["kind"], "resource": cue["resource"],
                             "reduced_motion": cue.get("reduced_motion", "skip")})
    return sorted(expanded, key=lambda e: (e["at_frame"], e["id"], e["iteration"]))


def _runs(flags: list[bool]) -> list[dict]:
    spans = []
    start = None
    for i in range(len(flags) + 1):
        active = i < len(flags) and flags[i]
        if active and start is None:
            start = i
        if not active and start is not None:
            spans.append({"start_frame": start, "end_frame": i})
            start = None
    return spans


def _layer_influence(layer: dict, frame: int) -> float:
    if not layer["start"] <= frame < layer["end"]:
        return 0.0
    weight = float(layer["weight"])
    if layer["fade_in"]:
        weight *= min(1., (frame + 0.5 - layer["start"]) / layer["fade_in"])
    if layer["fade_out"]:
        weight *= min(1., (layer["end"] - frame - 0.5) / layer["fade_out"])
    return max(0., weight)


def audit_timeline(spec: dict | str) -> dict:
    """Plan-only checks. Never claims actual Blender or Roblox success."""
    data = validate_spec(spec)
    clips = {c["id"]: c for c in data["clips"]}
    events = expand_cues(data)
    findings: list[dict] = []
    base_layers = [l for l in data["layers"] if clips[l["clip"]]["target"] == "full_body" and l["blend"] == "replace"]
    if data.get("budgets", {}).get("require_base_pose", True):
        weights = [sum(_layer_influence(l, frame) for l in base_layers) for frame in range(data["total_frames"])]
        for kind, bad in (("base_pose_gap", [v < 0.98 for v in weights]),
                          ("base_pose_overlap", [v > 1.02 for v in weights])):
            for span in _runs(bad):
                findings.append({"code": kind, "severity": "review", **span})
    # Advisory only: Blender's declared strip influence is not the native
    # Roblox Animation Graph weight. Roblox can suppress zero-weight markers,
    # so low-influence cue markers deserve a real engine trace.
    for cue in data["cues"]:
        layer = next(l for l in data["layers"] if l["id"] == cue["layer"])
        clip = clips[layer["clip"]]
        marker_frame = next(m["frame"] for m in clip["markers"] if m["id"] == cue["marker"])
        count = (layer["end"] - layer["start"]) // clip["duration"]
        for repetition in range(count):
            at = layer["start"] + repetition * clip["duration"] + marker_frame
            if _layer_influence(layer, at) < MIN_MARKER_LAYER_INFLUENCE:
                findings.append({"code": "possible_suppressed_marker", "severity": "review",
                                 "cue": cue["id"], "marker_frame": at})
    for layer in data["layers"]:
        clip = clips[layer["clip"]]
        if layer["blend"] in {"add", "combine"} and clip["target"] == "full_body":
            findings.append({"code": "full_body_additive_requires_review", "severity": "review", "layer": layer["id"]})
        if layer["blend"] == "replace" and clip["target"] != "full_body":
            findings.append({"code": "partial_replace_requires_fcurve_audit", "severity": "review", "layer": layer["id"]})
    for kind, key in (("vfx", "max_vfx"), ("ui", "max_ui"), ("camera", "max_camera"), ("sound", "max_sound")):
        if key not in data.get("budgets", {}):
            continue
        limit = data["budgets"][key]
        counts = [0] * (data["total_frames"] + 1)
        for event in events:
            if event["kind"] == kind:
                counts[event["at_frame"]] += 1
                counts[event["until_frame"]] -= 1
        peak = 0
        for frame in range(data["total_frames"]):
            peak += counts[frame]
            counts[frame] = peak
        highest = max(counts[:data["total_frames"]], default=0)
        if highest > limit:
            findings.append({"code": f"declared_{kind}_concurrency_exceeded", "severity": "review",
                             "observed_declared_peak": highest, "budget": limit})
    return {
        "name": data["name"],
        "spec_sha256": hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "clip_count": len(data["clips"]), "layer_count": len(data["layers"]),
        "expanded_event_count": len(events), "total_frames": data["total_frames"],
        "findings": findings,
        "status": "static_review_required" if findings else "static_checks_passed_native_review_required",
        "blender_executed": False, "studio_tested": False, "art_approved": False,
        "limitations": "Declared timeline only: weight sums are a heuristic, not Blender composite evaluation; not verified against actual F-curves, action slots, root motion, audio latency, native markers, UI scaling, visual quality or device frame time.",
    }


def blender_nla_plan(spec: dict | str) -> dict:
    """Editable NLA strip recipe for Blender 5.x; never executes bpy."""
    data = validate_spec(spec)
    clips = {clip["id"]: clip for clip in data["clips"]}
    strips = []
    for index, layer in enumerate(data["layers"]):
        clip = clips[layer["clip"]]
        strips.append({"track_order": index, "track": "STAR_" + layer["id"], "action": clip["action"],
                       "frame_start": layer["start"] + 1, "frame_end_exclusive": layer["end"] + 1,
                       "action_span_frames": clip["duration"],
                       "repeat": (layer["end"] - layer["start"]) // clip["duration"],
                       "blend_type": _MODES[layer["blend"]], "influence": float(layer["weight"]),
                       "blend_in": layer["fade_in"], "blend_out": layer["fade_out"],
                       "extrapolation": "NOTHING", "target": clip["target"]})
    return {"type": "blender_nla_authoring_plan", "timeline": data["name"], "fps": data["fps"],
            "strips": strips, "native_applied": False,
            "preflight": "Verify existing Action slots/rig compatibility, keyed bone masks, bind pose and NLA transitions; author in a disposable copy and bake tested motion before export."}


def roblox_graph_handoff(spec: dict | str) -> dict:
    """Native Roblox Animation Graph *handoff*, not an unpublished graph asset."""
    data = validate_spec(spec)
    return {
        "type": "roblox_animation_graph_handoff", "timeline": data["name"],
        "clips": [{"clip": clip["id"], "action": clip["action"], "target": clip["target"],
                   "markers": [m["id"] for m in clip["markers"]]} for clip in data["clips"]],
        "cues": expand_cues(data), "published_graph_asset_id": None,
        "needs_owner_approved_import": True, "native_graph_created": False, "studio_tested": False,
        "guidance": "Import verified compatible clips, create Graph Editor nodes and masks, publish with owner approval; drive parameters via AnimationTrack:SetParameter and route cosmetic marker events via GetMarkerReachedSignal. Native graph node event weights may silence markers at zero blend influence; independently test transitions, interrupt/cancel, and timing. Do not drive gameplay authority from client effects.",
    }


def build_creator_handoff(spec: dict | str) -> dict:
    data = validate_spec(spec)
    return {"audit": audit_timeline(data), "blender_nla": blender_nla_plan(data),
            "roblox": roblox_graph_handoff(data)}


def main(argv: list[str] | None = None) -> int:
    """Owner-run CLI: read an explicit local JSON file and print the plan. Never writes."""
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(description="Preview STAR creator choreography without running Blender/Studio")
    parser.add_argument("spec", help="JSON timeline to validate; no execution or uploads")
    args = parser.parse_args(argv)
    path = Path(args.spec)
    if path.is_symlink() or not path.is_file() or path.suffix.lower() != ".json":
        parser.error("Input must be a regular .json file, not a symlink")
    if path.stat().st_size > MAX_SPEC_BYTES:
        parser.error("Input timeline is too large")
    try:
        handoff = build_creator_handoff(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError) as exc:
        parser.error(f"Invalid creator timeline: {exc}")
    print(json.dumps(handoff, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())