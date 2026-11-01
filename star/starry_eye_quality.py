"""STAR's evidence-based, cross-engine visual/playtest quality inspector.

Read-only and opt-in through a user-selected workspace. It checks real captured
screenshots, declared native UI geometry, frame changes and bounded run traces.
It neither runs an engine nor treats model assertions as proof or owner approval.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import math
import re
from typing import Any

from PIL import Image

from .creative_review import capture_evidence, compare_pixels

MAX_JSON_BYTES = 120_000
MAX_ELEMENTS = 120
MAX_EVENTS = 500
MAX_CHECKS = 50
MAX_CONCEPTS = 80
MAX_FINDINGS = 100
FIELDS = ("genre", "core_loop", "setting", "art_style", "twist")
WEIGHTS = (0.05, 0.35, 0.20, 0.10, 0.30)
ENGINES = frozenset({"roblox", "godot", "unity", "unreal", "web", "blender", "other"})
_WORD = re.compile(r"[a-z0-9]+")
_HEX = re.compile(r"#[0-9a-fA-F]{6}\Z")
_ID = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,63}\Z")


def _read_json(workspace, name: str) -> tuple[dict, str]:
    """Never follow a path outside the selected workspace or a forbidden file."""
    if not isinstance(name, str) or not name.lower().endswith(".json"):
        raise ValueError("Choose a JSON manifest inside the selected workspace")
    path = workspace.resolve(name)
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= MAX_JSON_BYTES:
        raise ValueError("Manifest or trace must be a small regular JSON file")
    raw = path.read_bytes()
    try:
        value = json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ValueError("Malformed JSON evidence") from exc
    if not isinstance(value, dict):
        raise ValueError("Evidence must be a JSON object")
    return value, hashlib.sha256(raw).hexdigest()


def _validate_source_paths(workspace, manifest: dict) -> None:
    # creative_review performs its own containment/size/pixel checks; this extra
    # boundary also enforces Workspace's blocked credentials and path spellings.
    entries: list[Any] = [manifest.get("source")]
    entries.extend(manifest.get("sources", []) if isinstance(manifest.get("sources", []), list) else [])
    views = manifest.get("views", {})
    if isinstance(views, dict):
        entries.extend(view.get("file") for view in views.values() if isinstance(view, dict))
    baselines = manifest.get("baselines", {})
    if isinstance(baselines, dict):
        entries.extend(baselines.values())
    for entry in entries:
        if not isinstance(entry, str):
            raise ValueError("Source and screenshot file paths must be strings")
        path = workspace.resolve(entry)
        if path.is_symlink() or not path.is_file():
            raise ValueError("Evidence paths must be ordinary workspace files")


def _finite(value: Any, *, low: float = 0, high: float = 1_000_000) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError("Evidence numbers must be finite and within the supported range")
    return float(value)


def _id(value: Any) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError("Invalid bounded evidence ID")
    return value


def _rect(value: Any) -> tuple[int, int, int, int]:
    if (not isinstance(value, list) or len(value) != 4 or
            any(type(n) is not int or not -16_384 <= n <= 16_384 for n in value)):
        raise ValueError("UI rectangles need four bounded integer coordinates")
    x, y, w, h = value
    if w <= 0 or h <= 0:
        raise ValueError("UI rectangle width and height must be positive")
    return x, y, w, h


def _contrast(foreground: str, background: str) -> float:
    if not _HEX.fullmatch(foreground) or not _HEX.fullmatch(background):
        raise ValueError("Contrast colors must be opaque #RRGGBB values")

    def luminance(color: str) -> float:
        channels = [int(color[i:i+2], 16) / 255 for i in (1, 3, 5)]
        transformed = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
                       for c in channels]
        return sum(w * v for w, v in zip((0.2126, 0.7152, 0.0722), transformed))

    bright, dark = sorted((luminance(foreground), luminance(background)), reverse=True)
    return round((bright + 0.05) / (dark + 0.05), 3)


def _overlap(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    x = max(0, min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0]))
    y = max(0, min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1]))
    return x * y / min(a[2] * a[3], b[2] * b[3])


def _tokens(text: str) -> set[str]:
    return set(_WORD.findall(text.casefold()))


def _concept(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ValueError("Each concept must be an object")
    result = {}
    for field in FIELDS:
        part = value.get(field)
        if not isinstance(part, str) or not 2 <= len(part.strip()) <= 200:
            raise ValueError("Each concept needs genre, core_loop, setting, art_style and twist")
        result[field] = " ".join(part.casefold().split())
    return result


def concept_similarity(first: dict, second: dict) -> float:
    """Structured similarity, not semantic originality verification."""
    a, b = _concept(first), _concept(second)
    scores = []
    for key in FIELDS:
        ta, tb = _tokens(a[key]), _tokens(b[key])
        scores.append(len(ta & tb) / len(ta | tb) if ta and tb else 0)
    return round(sum(w * s for w, s in zip(WEIGHTS, scores)), 4)


def rank_concepts(candidates: list, history: list | None = None, *, count: int = 3,
                  required_genre: str = "") -> dict:
    """Select different model-proposed concepts; no automatic model calls or writes."""
    if (not isinstance(candidates, list) or not 1 <= len(candidates) <= MAX_CONCEPTS or
            not isinstance(history or [], list) or len(history or []) > MAX_CONCEPTS or
            type(count) is not int or not 1 <= count <= 10 or
            not isinstance(required_genre, str) or len(required_genre) > 100):
        raise ValueError("Concept ranking request exceeds supported bounds")
    historic = [_concept(item) for item in (history or [])]
    pool = [_concept(item) for item in candidates]
    required = " ".join(required_genre.casefold().split())
    selected: list[dict] = []
    used: set[int] = set()
    rejected: list[dict] = []
    for i, item in enumerate(pool):
        if required and item["genre"] != required:
            used.add(i)
            rejected.append({"index": i, "reason": "genre_mismatch"})
    while len(selected) < count and len(used) < len(pool):
        scored = []
        for i, item in enumerate(pool):
            if i in used:
                continue
            prior = historic + [record["concept"] for record in selected]
            max_sim = max((concept_similarity(item, p) for p in prior), default=0.0)
            scored.append((max_sim, i))
        max_sim, index = min(scored, key=lambda x: (x[0], x[1]))
        used.add(index)
        if max_sim >= 0.82:
            rejected.append({"index": index, "reason": "near_duplicate", "similarity": max_sim})
            continue
        selected.append({"index": index, "concept": pool[index],
                         "max_similarity": max_sim, "relative_novelty": round(1 - max_sim, 4)})
    return {"selected": selected, "rejected": sorted(rejected, key=lambda x: x["index"]),
            "considered": len(pool), "history_size": len(historic),
            "originality_proven": False,
            "note": "Only relative diversity against provided concepts; not proof of worldwide originality."}


def audit(workspace, manifest_path: str) -> dict:
    """Verify source + capture evidence, then independently inspect layout, motion and recorded events."""
    manifest, manifest_sha = _read_json(workspace, manifest_path)
    _validate_source_paths(workspace, manifest)
    evidence = capture_evidence(workspace.root, manifest)
    findings: list[dict] = []
    checked = 0
    incomplete = 0

    def finding(code: str, status: str, message: str, *, view: str = "") -> None:
        if len(findings) < MAX_FINDINGS:
            findings.append({"code": code, "status": status, "message": message,
                             **({"view": view} if view else {})})

    views = manifest["views"]
    # A screenshot proves only that an image was captured; a smooth dark screen
    # could be intentional, so a blank frame is a warning, never an automatic fail.
    for name, spec in views.items():
        path = workspace.resolve(spec["file"])
        with Image.open(path) as image:
            entropy = image.convert("L").resize((64, 64)).entropy()
        if entropy < 0.08:
            finding("nearly_uniform_frame", "review", "Capture has almost no visual detail; verify the scene loaded.",
                    view=name)

    layout = manifest.get("layout", {})
    if not isinstance(layout, dict) or len(layout) > 12:
        raise ValueError("layout must be a bounded per-view object")
    for view, elements in layout.items():
        if view not in views or not isinstance(elements, list) or len(elements) > MAX_ELEMENTS:
            raise ValueError("Layout elements must reference a captured view")
        width, height = views[view]["width"], views[view]["height"]
        seen: set[str] = set()
        interactive = []
        for item in elements:
            if not isinstance(item, dict):
                raise ValueError("Layout elements must be objects")
            name = _id(item.get("id"))
            if name in seen:
                raise ValueError("UI element IDs must be unique within a view")
            seen.add(name)
            rect = _rect(item.get("rect"))
            x, y, w, h = rect
            checked += 1
            if x < 0 or y < 0 or x + w > width or y + h > height:
                finding("ui_clipped", "fail", f"{name} extends beyond the viewport.", view=view)
            active = item.get("interactive", False)
            if type(active) is not bool:
                raise ValueError("interactive must be a boolean")
            if active:
                interactive.append((name, rect, item))
                min_target = item.get("min_target_px", 32)
                _finite(min_target, low=1, high=256)
                checked += 1
                if w < min_target or h < min_target:
                    finding("tiny_hit_target", "fail", f"{name} is too small for its declared minimum target.",
                            view=view)
            if "foreground" in item or "background" in item:
                if not isinstance(item.get("foreground"), str) or not isinstance(item.get("background"), str):
                    raise ValueError("Color contrast requires both foreground and background")
                ratio = _contrast(item["foreground"], item["background"])
                threshold = 3.0 if item.get("large_text", False) is True else 4.5
                checked += 1
                if ratio < threshold:
                    finding("low_text_contrast", "fail", f"{name}: declared {ratio}:1 contrast; need {threshold}:1.",
                            view=view)
        for i, (a_name, a_rect, a_spec) in enumerate(interactive):
            for b_name, b_rect, b_spec in interactive[i + 1:]:
                # Explicitly permitted layering is allowed, but never inferred.
                allow_a = a_spec.get("allow_overlap_with", [])
                allow_b = b_spec.get("allow_overlap_with", [])
                if (not isinstance(allow_a, list) or not isinstance(allow_b, list) or
                        any(not isinstance(n, str) for n in allow_a + allow_b)):
                    raise ValueError("allow_overlap_with must contain element IDs")
                checked += 1
                if b_name not in allow_a and a_name not in allow_b and _overlap(a_rect, b_rect) >= 0.05:
                    finding("ui_hit_target_overlap", "fail", f"{a_name} overlaps {b_name}.", view=view)

    motion = manifest.get("motion", [])
    if not isinstance(motion, list) or len(motion) > MAX_CHECKS:
        raise ValueError("motion must be a bounded list")
    for test in motion:
        if not isinstance(test, dict) or test.get("from") not in views or test.get("to") not in views:
            raise ValueError("Motion must name two captured views")
        expected = test.get("expected")
        if expected not in {"moving", "static"}:
            raise ValueError("Motion expectation must be moving or static")
        a = workspace.resolve(views[test["from"]]["file"])
        b = workspace.resolve(views[test["to"]]["file"])
        with Image.open(a) as ai, Image.open(b) as bi:
            fraction = compare_pixels(ai, bi, tolerance=16)
        threshold = _finite(test.get("threshold", 0.005 if expected == "moving" else 0.02),
                            low=0, high=1)
        checked += 1
        if expected == "moving" and fraction < threshold:
            finding("frozen_frames", "fail", f"Changed-pixel ratio {fraction} below {threshold}.",
                    view=test["to"])
        elif expected == "static" and fraction > threshold:
            finding("unexpected_frame_change", "fail", f"Changed-pixel ratio {fraction} above {threshold}.",
                    view=test["to"])

    trace_sha = None
    trace = None
    if "trace_file" in manifest:
        trace, trace_sha = _read_json(workspace, manifest["trace_file"])
        if trace.get("engine") not in ENGINES or type(trace.get("run_finished")) is not bool:
            raise ValueError("Trace requires a recognized engine and run_finished flag")
        events = trace.get("events")
        if not isinstance(events, list) or len(events) > MAX_EVENTS:
            raise ValueError("Trace events must be a bounded list")
        prior_t = -1
        for event in events:
            if not isinstance(event, dict):
                raise ValueError("Malformed trace event")
            _id(event.get("name"))
            t = _finite(event.get("t_ms"), high=3600_000)
            if t < prior_t:
                raise ValueError("Trace events must be in time order")
            prior_t = t
        if not isinstance(trace.get("metrics", {}), dict):
            raise ValueError("Trace metrics must be an object")
    expectations = manifest.get("expect_events", [])
    budgets = manifest.get("budgets", {})
    if not isinstance(expectations, list) or len(expectations) > MAX_CHECKS or not isinstance(budgets, dict) or len(budgets) > MAX_CHECKS:
        raise ValueError("Event and performance assertions must be bounded")
    for item in expectations:
        if not isinstance(item, dict):
            raise ValueError("Invalid required event")
        name = _id(item.get("name"))
        min_count = item.get("min_count", 1)
        if type(min_count) is not int or not 1 <= min_count <= MAX_EVENTS:
            raise ValueError("min_count must be 1..500")
        if trace is None or not trace["run_finished"]:
            incomplete += 1
            finding("event_unverified", "review", f"{name} needs a completed run trace.")
            continue
        checked += 1
        amount = Counter(event["name"] for event in trace["events"])[name]
        if amount < min_count:
            finding("event_missing", "fail", f"{name}: observed {amount}; expected at least {min_count}.")
    for key, target in budgets.items():
        _id(key)
        if not isinstance(target, dict) or set(target) != {"max"}:
            raise ValueError("Each performance budget requires one numeric max")
        limit = _finite(target["max"])
        if trace is None or not trace["run_finished"] or key not in trace["metrics"]:
            incomplete += 1
            finding("metric_unverified", "review", f"{key} needs measured runtime evidence.")
            continue
        measured = _finite(trace["metrics"][key])
        checked += 1
        if measured > limit:
            finding("budget_exceeded", "fail", f"{key}: observed {measured}; maximum {limit}.")

    failures = sum(f["status"] == "fail" for f in findings)
    status = ("automated_checks_failed" if failures else
              "insufficient_evidence" if incomplete or checked == 0 else
              "automated_checks_passed")
    return {"project": evidence["project"], "artifact": evidence["artifact"],
            "status": status, "automated_check_count": checked, "failed_count": failures,
            "unverified_count": incomplete, "findings": findings, "captures": evidence["captures"],
            "source_sha256": evidence["source_sha256"], "evidence_key": evidence["evidence_key"],
            "manifest_sha256": manifest_sha, "trace_sha256": trace_sha,
            "runtime_executed_by_this_tool": False, "owner_approved": False,
            "warning": "Model/user-supplied bounds and traces are not trusted execution receipts; pixel change "
                       "is not animation quality. Artist approval and real engine tests remain separate."}
