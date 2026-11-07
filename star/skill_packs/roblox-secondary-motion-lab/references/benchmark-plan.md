# Native comparison plan — not executed

## Freeze the comparison

Choose one approved rig, material set, clips, camera path, collider layout and wind input trace. Record content hashes, Roblox version, exact SmartBone 2 optimized-build commit, STAR candidate commit, hardware, graphics settings and frame cap. Pin every dependency before recording. Compare identical visible rigs and collision complexity; do not call a missing feature an optimization.

Run three conditions: authored animation only, optimized SmartBone 2, STAR candidate. Keep observer overhead identical. Alternate order across at least five independent runs per condition, warm up, then collect a sufficiently long trace. These are initial engineering defaults, not a statistical proof. Report per-run distributions rather than pooling every frame as an independent experiment.

## Six required scenarios

1. Stationary and rotating roots: hair/tail equilibrium, twist preservation, bone-parent transforms and coupling to authored animation.
2. Walking, jumping and abrupt direction changes: visible lag, stretch, contact penetration, root anchoring and settling time.
3. Teleport, respawn, pause/resume and destruction: no false velocity impulse, stale references or leaked connections. Log explicitly discarded cosmetic time.
4. Low frame rates and stalls: 15/30/60/120/240 FPS where available, jitter and an injected 250 ms hitch. Separate bounded catch-up policy from unchanged physical integration. Never advertise exact frame-rate invariance.
5. Culling/LOD/streaming lifecycle: offscreen sleep and re-entry, camera cuts and streaming removal. Currently unimplemented in the candidate and therefore BLOCKED, not PASS.
6. Crowds on actual devices: 1, 10, 50 and 100 rigs as hardware permits, client frame p50/p95/p99, simulation section time, allocation/memory, collision cost and visual review. Include one physical mobile device; desktop emulation is not that test.

## Acceptance contract

Require source-bound logs plus real same-camera video; record missing cases as NOT RUN or BLOCKED. Review clipping, silhouette, rigidity, oscillation, deterministic reset, excessive stretch and animation interference. Label visually chosen tolerances as owner/design decisions. MicroProfiler provides runtime measurement; no self-authored success field certifies a test.

Choose a replacement only after the complete integrated candidate meets the agreed visual quality, feature coverage, memory and frame-time budgets on the target devices. Keep gameplay authority and input acceptance independent from cosmetic motion. A numerical unit test, a compiler pass, a skinned-mesh screenshot or an author demo alone cannot establish superiority.

## Integration still required

Build one single-writer Bone adapter with fresh authored-pose capture and parent-aware transforms; implement bend/twist limits and appropriate collider geometry; then add measured culling/LOD and lifecycle handling. Version capabilities explicitly. Do not install the current numeric kernel as an automatic SmartBone 2 replacement.
