---
name: roblox-editablemesh-batching
description: Official Roblox 2026 EditableMesh batch methods, serial mesh writes, parallel read-only queries, bounded procedural water and mesh performance measurements.
---
# EditableMesh batching and parallel queries (verified 2026)

## When to use
For Roblox procedural waves, mesh deformation, destruction, surface raycasts, geometry scanning, dynamic mesh creation, or performance fixes. Always inspect the current official API version. This pack is **off by default** until independently benchmarked on Star's evaluation gate.

## Verified API rules
1. Roblox announced the beta on **August 6, 2026** and live-experience availability on **September 15, 2026**. Up to ~8x batch call speed and ~2x read-query throughput were reported on specific benchmark workloads; these are **not** guaranteed FPS gains.
2. `EditableMesh:BatchAdd(Enum.MeshAttribute.Vertex, positions)` takes a `{Vector3}` array and returns ordered vertex IDs. `BatchAdd(Enum.MeshAttribute.Face, triangles)` takes an array of arrays of vertex IDs. Use proper winding order.
3. `EditableMesh:BatchSetValues(vertexIds, positions)` takes **two** same-length arrays and determines the attribute type from the IDs; it has NO `Enum.MeshAttribute` argument. Never mix different ID types or pass face IDs to this method.
4. Color creation takes color AND alpha arrays. Batch reads include `BatchGetValues`, `BatchGetVertexAttributes`, `BatchGetFaceAttributes`, and `BatchGetVertexFaceAttributes`. Some getters return a second array of alpha values for color IDs.
5. Read-only mesh methods may run in parallel Actors after `task.desynchronize()`. **Only read/query methods** are parallel-safe. Do `task.synchronize()` before any writes, Instance property changes, or serial-only operations.
6. Avoid dynamic topology in the update loop. Build once; store vertex IDs and base positions; generate bounded new positions; make one batch write per tick. **Do not** call `CreateMeshPartAsync` per frame.
7. EditableMesh allocation is constrained by device-dependent budgets and creator eligibility/permissions. Wrap creation in `pcall`, check nil, and provide a regular Part/mesh fallback. Preview quality must have a mobile tier.
8. Set a quality-specific mesh size and work limit, cap update FPS and concurrent effects, measure actual **device FPS, update time, triangle count, draw cost, and fallback rate**. Do not label static budgets as measured performance.
9. Water in this pack is purely **client-side visual geometry**. Swimming, buoyancy, collision, replication, and sound need separate systems. Never imply automatic game-ready water.
10. Clean up Heartbeat connections, mesh/part instances, remote listeners, and any effect resources after stop, respawn, or cancellation.

## Offline bounded example shipped with Star
```python
from star.roblox_editablemesh_batch import compile_wave_panel, estimate_wave_panel
print(estimate_wave_panel({"quality": "mobile"}))
luau_source = compile_wave_panel({"quality": "mobile", "span": 32, "amplitude": 0.5})
# Owner reviews this string, then optionally installs it into a TEST place.
```
The generator only returns Luau source; it does **not** edit Roblox Studio, upload assets, release a game, or benchmark GPU hardware. To preview, owner may save the output as a LocalScript in StarterPlayerScripts in an authorized test place.

## Anti-slop VFX and procedural mesh review
Use clear silhouette, readable direction, staged impact, limited glow, differentiated palette, and temporal decay. Prefer custom shape language over piles of neon rings. Compare footage at impact, follow-through and dissipation, not just a single best-looking frame. Pair with `roblox-vfx-composer` and `roblox-animation-craft` under explicit opt-in; keep hit detection server authoritative and VFX client visual only.

## References
See `references/sources.md` (official Roblox pages and the announcement this pack was written from).
