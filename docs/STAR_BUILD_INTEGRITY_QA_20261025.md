# STAR Scene Integrity: design-first buildings, placements and visible-quality gate

**Date:** 2026-10-25
**Scope:** Offline geometry gate for STAR's bounded procedural Blender-Z-up building plans.
**Status:** Implemented and focused-tested on an isolated branch; no real Roblox Studio or Blender execution in this change. **Not** proof of attractive or defect-free buildings.

## Why this exists

An object count, triangle count, and valid GLB cannot establish that a building is assembled correctly. A scene can have all expected parts but still show dislocated walls, missing entrance panels, props intersecting surfaces, coplanar flicker, incorrect fixture scale, drifting furniture or misplaced windows. Passing a code check is not artistic approval.

The production contract is **intent -> measurable scene blueprint -> deterministic geometry -> static integrity gate -> native import -> multi-camera vision review -> avatar/physics playtest -> human art direction -> performance evidence**.

## Implemented (this branch)

- `star/scene_integrity.py` audits exact duplicate box transforms (possible z-fighting), continuous fixed-kit shell parts against the deterministic generator, misplaced windows/doors/roof segments, unintended solid interpenetration, and authored prop attachments/placements.
- Geometry collision broad phase uses X-axis interval sweep, with oriented rectangular-solid separating axis tests in the Blender XZ plane to avoid declaring colliding parts solely because two rotated AABBs overlap. Decorative trim and roofing intersections are expected, not defects. This does **not** cover arbitrary triangular mesh self-intersections or Roblox's actual collision fidelity.
- Custom prop geometry can declare `role="prop"` and `placement={"target_center":[x,y,z],"max_offset_studs":0.1,"support_name":"foundation","support_mode":"vertical"}`. A prop without the declared support, sitting above it, or departing its intended anchor fails. `support_mode="attached"` handles side-attached props using bounding-box proximity. Props with no placement contract are rejected.
- Optional `scene_contract` allows an independently reviewed blueprint to name **required** extras and connectivity; if an object never gets generated, the gate still detects the omission. The contract is evidence of declared intent, **not** independent proof if the model secretly changes its own targets to make bad output pass.
- Optional `texture` metadata on boxes checks bounded tile scales and the syntax of Roblox `rbxassetid://` image references. These checks do not prove the asset exists, normals/tangents are good, UV density consistent, or textures visually align.
- `star/architecture_quality.audit_plan` now runs these checks before `star/architecture_pipeline.create_package` writes a building, and includes `scene_integrity`, `blueprint_integrity` and `scene_contract` in the audit. Any detected problem blocks the standard output gate.
- `propose_shell_repair` reconstructs **only** recognizable deterministic shell components from the original brief. It returns a new candidate in memory and a re-audit, preserving original input. Extra bespoke parts are never silently discarded; repair remains blocked if unresolved problems survive.
- `star/scene_quality_cli.py` exposes offline inspection and optional exclusive-create proposal output, with no Studio editing, publishing, network or credential access.

### Running an audit

```bash
python -m star.architecture_pipeline examples/architecture/harbor_warehouse.json --out out/harbor-plan
python -m star.scene_quality_cli out/harbor-plan/building-plan.json
```

To propose known, deterministic repairs **without** touching the original file or Studio:

```bash
python -m star.scene_quality_cli damaged-building-plan.json --repair-proposal corrected-candidate.json
```

The CLI writes a new file only if a necessary proposal passes all checks. An unknown prop, a broken required prop contract, an unresolved material problem or existing destination blocks writes; it must be fixed or reviewed, not falsely auto-accepted.

### Optional custom-prop blueprint fragment

Author and review the intended scene contract **before** generation. The deterministic shell itself already has a canonical blueprint.

```json
{
  "scene_contract": {
    "required": [
      {"name": "checkout_register", "center": [0, 0, 0.5], "size": [1, 1, 1], "tolerance_studs": 0.1}
    ],
    "connections": [
      {"first": "checkout_register", "second": "foundation", "max_gap_studs": 0.12}
    ]
  }
}
```

For actual extras, keep the box in `parts` with `role="prop"`, the corresponding `placement` anchor/support contract and accurate `metrics`. `scene_contract` is optional for the existing generator; absent custom requirements are reported as `no_custom_contract`, **never** represented as verified missing-prop coverage.

### Defect -> check -> suggested recovery

| Defect | First automated check | Corrective action |
|---|---|---|
| Missing/shifted wall, roof, doorway, window | Canonical blueprint exact-name and transforms | Rebuild known generator element in a *proposal*, re-audit |
| Missing artist-requested hero prop | Reviewed scene contract required names | Restore original approved asset; no blind hallucinated substitution |
| Floating or unattached prop | Surface support + declared attached/vertical mode | Fix expected support hierarchy and world transform |
| Random geometry overlap | Sweep broadphase + oriented box SAT | Reposition or revise contract; retain intentional trim contacts |
| Two exact boxes on same position | Duplicate transform check | Remove duplicate or deliberately offset noncoincident surfaces |
| Mis-sized prop / asymmetric placement drift | Reviewed center, bounding size, tolerance | Reset to design coordinates and preserve grid/pivot |
| Missing/invalid material images | Material/texture metadata check | Reimport/verify valid maps and UVs in *render* |
| Wrong physical/avatar scale | Native Studio avatar/camera inspection **not implemented here** | Correct import units and pivots, then re-test |
| Bad-looking lighting, plastic shaders, washed materials | Matched Studio/Blender camera critique **not implemented here** | Professional art pass with reference board and calibration |
| False geometry pass due to transformed/mesh collision | Native Studio overlap/physics/avatar test **not implemented here** | Verify actual contacts in playtest |

## Recommended next native quality gate (not in this change)

The next phase must run in an authorized **disposable, private** Roblox test place:

1. **Before import:** record asset provenance/license, orientation, scale convention, local pivots, applied Blender transforms, unique mesh path identity, UV-set counts, material/texture slot consistency. Preserve an editable DCC source and stable reimport identities.
2. **After import:** read-only inventory of instance names/classes, `Size`, `CFrame`, `CanCollide`, `Anchored`, material/texture bindings, position relative to parent pivots, and tagged logical attachments. Never decide a collision is bad using `GetPartBoundsInBox` alone; it is a *candidate* broad-phase test. Use `GetPartsInPart` and targeted collision/penetration tests where justified, with an explicit intentional-overlap allowlist.
3. **Place accurately:** preserve authored coordinates with `PVInstance:PivotTo` (and verified pivot offsets), not blind `Model:MoveTo` that can relocate a model upward to avoid blockers. Keep consistent snapping rules and rotated bounding-box tolerances.
4. **Verify physically:** walk the entrance and circulation on R6 and R15 avatars, test doors with collision on/off as intended, ground support, doors/windows, nav paths, furniture placement, room scale, shadows and streamed areas. Native physics evidence is necessary before claiming gameplay-safe collisions.
5. **Verify visually:** render fixed-camera elevations (all four sides), overhead, 45-degree, first-person gameplay angle and a close view of seam/UV/PBR. Include known human-approved references and visible defect annotations; repeat at multiple graphic settings and with streaming. Test normal direction and tangent-space maps, tiling seams, texture repetition, distant mip/aliasing and surface flicker by moving camera.
6. **Judge design:** silhouette, hierarchy, culturally/style-consistent details, credible support/load paths, clear egress and scale, intentional prop roles, material coherence, optimized foliage/clutter and clear focal points. Distinct style palettes do not by themselves imply distinct architectural quality. Have an independent artist gate; never let STAR self-award an automatic "AAA" label.
7. **Measure performance:** mobile and desktop budgets, memory/draw calls, mesh instancing, LOD, streaming, MicroProfiler and load time. Profile a representative level, not a tiny empty scene.
8. **Iterate intelligently:** cache unchanged kit elements and candidate scene hashes; regenerate only damaged components; render low-cost preview for rapid rejection, higher quality final preview only for survivors. Never count a faster run as better unless static and native gates remain green.

Safety: Keep Studio read-only unless the owner allowed editing the exact disposable session. Any correction is staged with a reversible, evidence-bound journal and undo. Never publish/upload/reimport into production automatically.

## Primary technical references

- Roblox modular environments: https://create.roblox.com/docs/tutorials/use-case-tutorials/modeling/assemble-modular-environments
- Roblox third-party/Blender import: https://create.roblox.com/docs/art/blender
- Roblox model movement (PVInstance PivotTo): https://create.roblox.com/docs/reference/engine/classes/PVInstance#PivotTo
- Roblox MoveTo semantics: https://create.roblox.com/docs/reference/engine/classes/Model#MoveTo
- Roblox world overlap queries: https://create.roblox.com/docs/reference/engine/classes/WorldRoot#GetPartBoundsInBox
- Roblox PBR and SurfaceAppearance: https://create.roblox.com/docs/art/modeling/surface-appearance
- Roblox texture specifications: https://create.roblox.com/docs/art/modeling/texture-specifications
- Roblox reimport: https://create.roblox.com/docs/art/modeling/reimport
- Roblox performance: https://create.roblox.com/docs/performance-optimization/improve

## Evidence and acceptance limits

Focused offline regression entrypoint: `python3 -m unittest tests.test_scene_integrity -v`. A passing result establishes the cases exercised, **not** global correctness or artistic polish. All eight current style fixtures passed static generation on the tested revision. Blender export, Studio import/playback, textures viewed in-scene, owner aesthetic review, native overlap fidelity, mobile profiling, general arbitrary interiors, and full-suite CI are separate outstanding acceptance steps. This branch does not change active Studio places or claim anything was deployed.
