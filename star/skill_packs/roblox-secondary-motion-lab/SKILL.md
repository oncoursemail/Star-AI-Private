---
name: roblox-secondary-motion-lab
description: EXPERIMENTAL, off by default. Candidate Roblox secondary-motion workflow, XPBD kernel, rig preflight and fair SmartBone 2 comparison. Reference only; no automatic routing, execution or installation.
---
# Secondary motion: choose by evidence (EXPERIMENTAL)

Use when investigating hair, tails, clothing, foliage, cosmetic chains, SmartBone 2, or authored animation plus physics. This is a candidate reference pack, not an automatically enabled runtime feature. Existing routing, tool permissions, release settings and evaluation gates are unchanged.

## Select the correct system

SmartBone 2 is the baseline for cosmetic bone motion; retain its optimized build and exact revision for comparison. Its documented features already include collision, wind, culling and rotational constraints. Do not market those alone as new STAR advantages. [S1]

Roblox AnimationConstraint is a different system: animated physical joints between parts. Detect the actual rig and supported engine APIs. For upgraded rigs, do not write the read-only C0/C1 aliases or rewrite RigAttachment frames. Procedural Transform work needs a single animation owner and correct PreSimulation ordering. It is not a direct replacement for skinned Bone deformation. [S2][S3]

The original StarSpringXPBD kernel in assets/ is an experimental numerical foundation. It provides fixed-step distance compliance, inverse masses, pins, explicit translation/reset and discrete point/sphere contacts. It DOES NOT implement bone binding, angular/bend/twist limits, continuous collision detection, self-collision, wind fields, culling, LOD transitions, Animator blending, Studio installation or multiplayer replication. These are remaining implementation tasks, not achieved capabilities. [S4]

## Work sequence

Inspect the approved source rig and its hierarchy; preserve editable mesh, UV, weights and authored clips. Run scripts/secondary_rig_audit.py on a deliberately selected snapshot or trusted Blender inspection copy. Structural success is not proof of deformation quality; check bent poses and animation transitions in the actual application.

Run scripts/test_secondary_motion.luau with a separately installed, pinned Luau CLI (tests/test_secondary_motion_luau.py does it under pytest when `luau` is on PATH). The source uses scalar arrays so the same numerical kernel can be tested without pretending to run Roblox. Module state belongs to trusted application code; do not expose its mutable arrays as untrusted agent/tool inputs. Stop and discard a state after a solver range assertion.

Keep h and the scheduler's h identical. Sample moving anchors for each accepted substep. FixedStepper deliberately drops excessive whole-step backlog for COSMETICS, reports dropped seconds and retains a fractional step; never use that clock for authoritative damage, cooldowns or networking. Reset scheduler debt on teleport/pause, and explicitly reset or translate the solver. There is no hidden catch-up loop.

Before implementing a Bone adapter, specify who owns the unmodified authored pose, parent/child coordinate spaces, twist preservation, root displacement, Animator throttling, culling re-entry and destruction cleanup. Bone.Transform is not replicated; cosmetic presentation must not become hit or damage authority. [S3]

Use the native matrix in references/benchmark-plan.md before choosing a replacement. Record native frame captures and MicroProfiler evidence; compare visual quality and total client frame time, not only the inner constraint loop. Retain the baseline whenever the candidate fails the agreed checks. [S5]

## Related production work

For VFX, separate editable shape/texture/timing from gameplay, test full anticipation-impact-recovery sequences, cap overdraw, and inspect real captures. For Blender animation, check silhouette, contact, weight deformation, event timing and loop continuity before adding simulation. Preserve the user's exact reference identity and art direction; do not replace them with generic effects. These are workflow requirements, not new VFX/animation engines delivered here.

The existing star_skill_reference reader supports text reference formats, not .luau. Read sources.md and benchmark-plan.md through it; read code assets through an authorized workspace/repository code reader. Loading this skill grants no execution permissions. Sources and limitations: references/sources.md.
