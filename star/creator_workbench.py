"""STAR Creator Workbench: combine offline evidence, topology and experiment planning.

Pure, opt-in composition. It never talks to Studio or modifies a project.
The trusted caller owns the registered technique catalog, permissions and
provenance receipts; this wrapper is NOT such a trust boundary.
"""
from __future__ import annotations

from typing import Any

from .capability_frontier import MAX_FINDINGS, plan_frontier
from .creator_evidence import assess_creation
from .scene_topology import audit_scene


def review_and_plan(
    packet: dict[str, Any],
    techniques: list[dict[str, Any]],
    *,
    allowed_scopes: tuple[str, ...] = ("read_project",),
    wall_time_ms: int = 60_000,
    peak_memory_mb: int = 4096,
    max_steps: int = 3,
) -> dict[str, Any]:
    """Combine any available report types; do not treat an omitted modality as passing."""
    if not isinstance(packet, dict):
        raise ValueError("creative workbench packet must be a dictionary")
    creation = packet.get("creation")
    scene = packet.get("scene")
    if creation is None and scene is None:
        raise ValueError("one or both domain reports are needed")
    creative_report = assess_creation(creation) if creation is not None else None
    scene_report = audit_scene(scene) if scene is not None else None
    if creative_report is not None and scene_report is not None \
            and creative_report["project"] != scene_report["project"]:
        raise ValueError("creation and scene reports disagree on project")
    project = (creative_report or scene_report or {})["project"]
    findings: list[dict[str, Any]] = []
    if creative_report is not None:
        findings.extend(creative_report["findings"])
    else:
        findings.append({"code": "creative-evidence-missing", "target": project,
                         "severity": "unverified", "evidence": "No UI, playtest or visual capture report."})
    if scene_report is not None:
        findings.extend(scene_report["findings"])
    else:
        findings.append({"code": "geometry-evidence-missing", "target": project,
                         "severity": "unverified", "evidence": "No structural scene-topology report."})
    if len(findings) > MAX_FINDINGS:
        # Never claim full coverage when results are truncated.
        findings = sorted(findings, key=lambda x: {"error": 0, "unverified": 1, "review": 2}.get(
            str(x.get("severity")), 3))[:MAX_FINDINGS]
        truncated = True
    else:
        truncated = (bool(creative_report and creative_report.get("findings_truncated"))
                     or bool(scene_report and scene_report.get("findings_truncated")))
    combined = {"project": project, "findings": findings}
    proposal = plan_frontier(combined, techniques, allowed_scopes=allowed_scopes,
                             wall_time_ms=wall_time_ms, peak_memory_mb=peak_memory_mb,
                             max_steps=max_steps)
    errors = sum(row.get("severity") == "error" for row in findings)
    unverified = sum(row.get("severity") == "unverified" for row in findings)
    readiness = "needs_repair" if errors else "needs_evidence"
    # Even a zero-defect inferred report is not a valid Studio pass or art approval.
    return {"project": project, "readiness": readiness,
            "error_count_at_least": errors, "unverified_count_at_least": unverified,
            "truncated": truncated, "creation": creative_report, "scene": scene_report,
            "capability_frontier": proposal, "studio_verified": False,
            "owner_approved": False, "executed": False,
            "next_gate": "trusted Studio live readback, human visual review and measured paired trials"}
