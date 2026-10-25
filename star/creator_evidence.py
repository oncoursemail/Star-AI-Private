"""Bounded, offline creative QA of *reported* Studio observations.

This is a staging/evidence checker, not a visual-model judge, test runner,
permission grant, model trainer or publication gate. Results describe only the
observations supplied by a trusted calling workflow. In particular, a screenshot
hash is not proof that a screenshot was inspected or that it looks good.
"""
from __future__ import annotations

from hashlib import sha256
import json
from math import isfinite
import re
from typing import Any

MAX_BYTES = 160_000
MAX_ITEMS = 200
MAX_FINDINGS = 100
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


class CaptureError(ValueError):
    """Input is too large or too malformed to evaluate safely."""


def _identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise CaptureError(f"{field} must be a short identifier")
    return value


def _items(packet: dict, field: str) -> list[dict]:
    entries = packet.get(field, [])
    if not isinstance(entries, list) or len(entries) > MAX_ITEMS or any(not isinstance(x, dict) for x in entries):
        raise CaptureError(f"{field} must be a list of at most {MAX_ITEMS} records")
    return entries


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not isfinite(value):
        return None
    return float(value)


def _rect(value: Any) -> tuple[float, float, float, float] | None:
    if (not isinstance(value, list) or len(value) != 4):
        return None
    coords = [_number(x) for x in value]
    if any(x is None for x in coords):
        return None
    x, y, w, h = coords
    return (x, y, w, h) if w > 0 and h > 0 else None


def _intersection(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    width = max(0., min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0]))
    height = max(0., min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1]))
    return width * height


def assess_creation(packet: dict[str, Any]) -> dict[str, Any]:
    """Return auditable findings; never claim a game is released or high quality.

    Boolean fields are claims from the caller, not authenticated observations.
    For promotion, the host must bind them to actual Studio/tool logs and a
    separate owner review using STAR's existing creative_review boundary.
    """
    if not isinstance(packet, dict):
        raise CaptureError("capture must be an object")
    try:
        raw = json.dumps(packet, allow_nan=False, ensure_ascii=False, sort_keys=True)
    except (ValueError, TypeError) as error:
        raise CaptureError("capture must contain finite, JSON-safe data") from error
    if len(raw.encode("utf-8")) > MAX_BYTES:
        raise CaptureError("capture exceeds maximum size")
    project = _identifier(packet.get("project"), "project")
    requirements = _items(packet, "requirements")
    viewports = _items(packet, "viewports")
    collisions = _items(packet, "collisions")
    animations = _items(packet, "animations")
    playtests = _items(packet, "playtests")
    screenshots = _items(packet, "screenshots")
    findings: list[dict] = []

    def finding(code: str, domain: str, severity: str, target: str, why: str, fix: str) -> None:
        if len(findings) < MAX_FINDINGS:
            findings.append({"code": code, "domain": domain, "severity": severity,
                             "target": target[:96], "evidence": why[:400], "suggested_fix": fix[:320]})

    observed_requirements: set[str] = set()
    if not requirements:
        finding("requirements-missing", "intent", "unverified", project,
                "No requirement-to-test ledger supplied.", "Record each requested feature and an executable check.")
    for req in requirements:
        ident = _identifier(req.get("id"), "requirement.id")
        if ident in observed_requirements:
            raise CaptureError("duplicate requirement id")
        observed_requirements.add(ident)
        if req.get("passed") is False:
            finding("requirement-failed", "intent", "error", ident, "Requirement explicitly failed.",
                    "Repair the requested behavior, then re-run its acceptance check.")
        elif req.get("passed") is not True or not req.get("evidence"):
            finding("requirement-unverified", "intent", "unverified", ident,
                    "No passing check with evidence reference.", "Record a tool result or reproducible test artifact.")

    if not viewports:
        finding("viewport-missing", "ui", "unverified", project,
                "No measured UI layout at a real viewport.", "Capture measured mobile and desktop GUI rectangles.")
    seen_viewports: set[str] = set()
    for viewport in viewports:
        name = _identifier(viewport.get("id"), "viewport.id")
        if name in seen_viewports:
            raise CaptureError("duplicate viewport id")
        seen_viewports.add(name)
        safe = _rect(viewport.get("safe_rect"))
        if safe is None:
            raise CaptureError("viewport.safe_rect must be an [x,y,width,height] rectangle")
        controls = viewport.get("controls", [])
        if (not isinstance(controls, list) or len(controls) > MAX_ITEMS
                or any(not isinstance(control, dict) for control in controls)):
            raise CaptureError("viewport controls malformed or oversized")
        interactive: list[tuple[str, tuple[float, float, float, float], dict]] = []
        seen_controls: set[str] = set()
        for control in controls:
            ident = _identifier(control.get("id"), "control.id")
            if ident in seen_controls:
                raise CaptureError("duplicate control id")
            seen_controls.add(ident)
            r = _rect(control.get("rect"))
            if r is None:
                raise CaptureError("control.rect must be a positive-size rectangle")
            label = f"{name}/{ident}"
            visible_fraction = _intersection(r, safe) / (r[2] * r[3])
            if control.get("critical") is True and visible_fraction < .98:
                finding("ui-safe-area", "ui", "error", label,
                        f"Critical control visible area: {visible_fraction:.1%} of its bounds.",
                        "Adjust constraints and safe-area insets; recapture the viewport.")
            if control.get("interactive") is True:
                if min(r[2], r[3]) < 44 and viewport.get("device") == "phone":
                    finding("ui-small-target", "ui", "review", label,
                            "Interactive target has a dimension below STAR's 44-pixel review heuristic.",
                            "Check touch usability at target phone resolution; enlarge when appropriate.")
                interactive.append((ident, r, control))
        for i, (left, a, ctl_a) in enumerate(interactive):
            for right, b, ctl_b in interactive[i + 1:]:
                if ctl_a.get("overlap_group") and ctl_a.get("overlap_group") == ctl_b.get("overlap_group"):
                    continue  # explicit, author-controlled intentional overlay
                intersection = _intersection(a, b)
                smaller_area = min(a[2] * a[3], b[2] * b[3])
                if intersection / smaller_area >= .15:
                    finding("ui-control-overlap", "ui", "error", f"{name}/{left}+{right}",
                            f"Controls overlap by {intersection / smaller_area:.1%} of smaller area.",
                            "Separate interactive hit regions and test touch/mouse/gamepad activation.")

    if not collisions:
        finding("collision-evidence-missing", "building", "unverified", project,
                "No observed collision probes.", "Use Studio spatial queries then investigate intentional contact.")
    for collision in collisions:
        a = _identifier(collision.get("a"), "collision.a")
        b = _identifier(collision.get("b"), "collision.b")
        if a == b:
            raise CaptureError("self-collision pair")
        if collision.get("verified_in_studio") is not True:
            finding("collision-not-measured", "building", "unverified", f"{a}+{b}",
                    "The collision is not from a verified Studio check.", "Run GetPartsInPart for the candidate pair.")
        elif collision.get("intersecting") is True and collision.get("intentional") is not True:
            finding("unintended-penetration", "building", "error", f"{a}+{b}",
                    "Reported exact intersection is not marked intentional.",
                    "Reposition or remodel objects, or explicitly document a designed intersection.")

    if not animations:
        finding("animation-not-tested", "animation", "unverified", project,
                "No played animation evidence.", "Play and capture the required animation transitions.")
    for clip in animations:
        ident = _identifier(clip.get("id"), "animation.id")
        if clip.get("played") is not True:
            finding("animation-unplayed", "animation", "unverified", ident,
                    "No observed running playback.", "Inspect rig, transitions, timing and animation ownership in Studio.")
        required, observed = clip.get("required_markers", []), clip.get("observed_markers", [])
        if (not isinstance(required, list) or not isinstance(observed, list) or len(required) > 32
                or len(observed) > 32 or any(not isinstance(x, str) for x in required + observed)):
            raise CaptureError("animation markers malformed")
        if clip.get("played") is True and set(required) - set(observed):
            finding("animation-marker-missing", "animation", "error", ident,
                    "Observed playback omitted expected event markers.",
                    "Repair the rig/clip/event wiring and capture the full playback.")
        slide = _number(clip.get("foot_slide_studs"))
        if slide is not None and slide > .4:
            finding("animation-foot-sliding", "animation", "review", ident,
                    f"Observed planted-foot drift is {slide:g} studs (STAR heuristic).",
                    "Adjust contact timing, root motion or foot IK; recapture before/after.")

    if not playtests:
        finding("playtest-missing", "gameplay", "unverified", project,
                "No real play session recorded.", "Start Studio play, drive input, check logs, and test retries.")
    for test in playtests:
        ident = _identifier(test.get("id"), "playtest.id")
        if test.get("passed") is False:
            finding("playtest-failed", "gameplay", "error", ident,
                    "Reported gameplay acceptance test failed.", "Reproduce from player input, repair, and repeat.")
        elif test.get("passed") is not True or not test.get("evidence"):
            finding("playtest-unverified", "gameplay", "unverified", ident,
                    "No passing playtest evidence reference.", "Attach real Studio playtest evidence.")
        if test.get("method") != "virtual_input":
            finding("playtest-input-limited", "gameplay", "unverified", ident,
                    "No observed user-like input; scripted navigation/teleport is insufficient for full gameplay QA.",
                    "Run mouse, keyboard or touch controls with real virtual-input tools.")
        if test.get("runtime_errors"):
            finding("runtime-errors", "gameplay", "error", ident,
                    "Nonempty reported runtime error list.", "Fix console errors and retest from clean start.")

    image_devices: set[str] = set()
    for shot in screenshots:
        device = _identifier(shot.get("device"), "screenshot.device")
        if not _DIGEST.fullmatch(str(shot.get("sha256", ""))):
            raise CaptureError("screenshot hash must be SHA-256 hex")
        image_devices.add(device)
    for device in ("phone", "desktop"):
        if device not in image_devices:
            finding("visual-view-missing", "visual", "unverified", device,
                    "No hashed evidence of a captured view; appearance remains unjudged.",
                    "Capture the real viewport and obtain a separate visual review.")

    counts = {kind: sum(x["severity"] == kind for x in findings) for kind in ("error", "review", "unverified")}
    status = "needs_repair" if counts["error"] else ("needs_evidence" if counts["unverified"] else "ready_for_review")
    return {"project": project, "status": status, "counts": counts, "findings": findings,
            "findings_truncated": len(findings) == MAX_FINDINGS,
            "capture_sha256": sha256(raw.encode("utf-8")).hexdigest(),
            "dimensions": {"intent": len(requirements), "ui": len(viewports), "building": len(collisions),
                           "animation": len(animations), "gameplay": len(playtests), "visual": len(screenshots)},
            "limitations": ["Reported data is not independently authenticated; bind to actual tool evidence.",
                            "Geometry reports cannot identify untested collisions or distinguish art from design intent.",
                            "A screenshot hash does not establish visual quality or a human's approval.",
                            "ready_for_review is NOT permission to publish or evidence of AAA quality."]}


def propose_memory(report: dict[str, Any]) -> dict[str, Any]:
    """Generate local Graphify-style node-link and Obsidian Markdown *proposals* only.

    Does not write files, call Graphify/Obsidian, grant trust or self-edit.
    Callers must keep these project-scoped and require a separate human review.
    """
    project = _identifier(report.get("project"), "project")
    digest = str(report.get("capture_sha256", ""))
    if not _DIGEST.fullmatch(digest):
        raise CaptureError("report missing capture digest")
    issues = report.get("findings")
    if not isinstance(issues, list) or len(issues) > MAX_FINDINGS:
        raise CaptureError("invalid findings")
    root = f"project:{project}"
    nodes = [{"id": root, "label": project, "kind": "project", "trust": "candidate"}]
    links = []
    notes = [f"# STAR creative QA — {project}", "", "> Candidate learning only. Owner review required.", "",
             f"Evidence capture SHA-256: `{digest}`", "", "## Defects and review targets", ""]
    for index, issue in enumerate(issues):
        if not isinstance(issue, dict):
            raise CaptureError("invalid finding record")
        code = _identifier(issue.get("code"), "finding.code")
        domain = _identifier(issue.get("domain"), "finding.domain")
        ident = f"finding:{digest[:12]}:{index}"
        nodes.append({"id": ident, "label": code, "kind": domain, "trust": "candidate",
                      "source_digest": digest})
        links.append({"source": root, "target": ident, "type": "HAS_CANDIDATE_FINDING",
                      "provenance": "reported_tool_observation"})
        target = str(issue.get("target", ""))[:96].replace("\n", " ").replace("\r", " ")
        detail = str(issue.get("evidence", ""))[:400].replace("\n", " ").replace("\r", " ")
        fix = str(issue.get("suggested_fix", ""))[:320].replace("\n", " ").replace("\r", " ")
        notes.append(f"- **{code}** ({domain}, {issue.get('severity', 'review')}) — `{target}`. {detail} Proposed fix: {fix}")
    notes.extend(["", "## Reuse gate", "", "Do not promote to trusted lessons without verified results and owner review.",
                  "This export is not an Obsidian vault write or a Graphify graph mutation."])
    return {"graph_candidate": {"directed": True, "multigraph": False, "nodes": nodes, "links": links},
            "obsidian_markdown_candidate": "\n".join(notes) + "\n", "written": False, "approved": False}


def main(argv: list[str] | None = None) -> int:
    """Offline CLI intended for trusted build/test wrappers, never as an owner approval tool."""
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(description="Audit normalized STAR creative evidence offline")
    parser.add_argument("capture", type=Path, help="Path to a normalized, already-authorized test report JSON")
    parser.add_argument("--propose-memory", action="store_true", help="Print non-writing memory proposals")
    args = parser.parse_args(argv)
    try:
        with args.capture.open("rb") as source:
            payload = source.read(MAX_BYTES + 1)
        if len(payload) > MAX_BYTES:
            raise CaptureError("capture exceeds maximum size")
        report = assess_creation(json.loads(payload.decode("utf-8")))
        if args.propose_memory:
            report["learning_proposal"] = propose_memory(report)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, CaptureError) as error:
        parser.error(str(error))
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
