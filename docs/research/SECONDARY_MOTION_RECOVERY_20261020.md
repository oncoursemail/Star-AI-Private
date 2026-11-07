# STAR secondary-motion recovery — October 20, 2026

## Why this is a new, smaller submission

The earlier approval expired before the prepared production kit was committed. Its original unsubmitted source package was not available in the current session. This branch is a freshly reconstructed, smaller implementation, NOT a byte-for-byte recovery of that earlier package. Earlier reported Python/Luau/routing totals are not reused as evidence here. The wider reference-video, VFX, animation and production-tool work is not claimed complete.

Base inspected: oncoursemail/Star-AI-Private main, 80bf8540b75633c065437036baf75614afe68f74.
Branch: star/secondary-motion-recovery-20261020. Re-landed as star/secondary-motion-20261021 on star/next; the skill pack is EXPERIMENTAL and off by default.

## Delivered

- Candidate roblox-secondary-motion-lab skill: sources, system-selection guidance, implementation boundaries and native comparison matrix. No default prompt routing or tool registration changes.
- Original scalar-array StarSpringXPBD numerical kernel: bounded particles/links/iterations, distance compliance, inverse mass weighting, pins, explicit teleport reset and discrete static point/sphere projection.
- FixedStepper: bounded cosmetic catch-up, preserved fractional time and explicitly reported dropped time.
- Read-only rig audit: finite geometry, duplicate names, hierarchy cycles/missing parents, degenerate bones, scale, vertex-weight validity and configurable influence budget. A separate optional Blender extractor exists but has NOT been run inside Blender.
- Fresh Python fixture tests and portable Luau numerical tests; compiler/type checks on the exact Luau files.

No new service, model, automatic training, approval bypass, default solver activation, Roblox upload, release or production restart is performed. Existing evaluation gates and other branches are untouched. Related PRs such as #479, #481, #487 and #488 are not merged or included.

## Fresh verification

Python: `python -m pytest -q tests/test_secondary_rig_audit.py` — 30 passed.
Luau 0.743: `luau scripts/test_secondary_motion.luau` — 25 passed, 0 failed.
`luau-analyze` on both kernels and the test script — exit 0.
`luau-compile` on each of those three Luau files — exit 0.
The Luau runtime archive was SHA-256 checked against the pinned release digest. Numerical checks ran in a temporary directory on the authorized STAR server; no running application was changed. File hashes are in the companion verification manifest.

NOT RUN: full STAR regression suite, installed-app skill discovery/routing, native Blender extraction/render, Roblox Studio import, Bone binding, multi-client replication, physical mobile tests, SmartBone 2 comparison, visual owner acceptance. No independent external reviewer or model-quality promotion gate is claimed to have run for this new submission.

## Reproduce

From a reviewed checkout, with Python/pytest and Luau already installed:

```sh
python -m pytest -q tests/test_secondary_rig_audit.py
python -m compileall -q scripts/secondary_rig_audit.py
luau scripts/test_secondary_motion.luau
luau-analyze scripts/test_secondary_motion.luau star/skill_packs/roblox-secondary-motion-lab/assets/FixedStepper.luau star/skill_packs/roblox-secondary-motion-lab/assets/StarSpringXPBD.luau
```

Under pytest: `python -m pytest -q tests/test_secondary_motion_luau.py tests/test_secondary_motion_pack.py` runs the 25 Luau tests when a `luau` CLI is on PATH and skips that one test otherwise.

Rig snapshot preflight: `python scripts/secondary_rig_audit.py --snapshot selected-rig.json`.
The Blender CLI workflow is documented in that script; it reads a deliberately selected mesh in a trusted inspection copy and never exports or repairs. JSON supplied by an agent remains untrusted data.

## Limits and next engineering increment

This is a distance-only prototype with point/sphere contacts; it lacks bend/twist limits, continuous and self-collision, Bone binding, animation layering, culling and LOD. It cannot yet be compared fairly as a complete SmartBone 2 replacement. Develop the adapter and missing capabilities, then execute the native benchmark matrix before choosing what is better.

The candidate is reviewable source, not an installed upgrade. Preserve its source archive and hashes so another interrupted approval does not erase the current deliverable.
