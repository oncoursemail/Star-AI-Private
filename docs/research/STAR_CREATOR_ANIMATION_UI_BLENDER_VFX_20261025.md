# STAR Creator Intelligence: Blender, Animation Graphs, UI, VFX and synchronized creative direction

**Research and prototype:** October 25, 2026. **Status:** a review-only source proposal; not a deployed feature or a model-weight update. This supplement carries the prior creator-mastery research into the source tree and adds a tested, offline timeline foundation. No actual Blender animation, Roblox Studio playback, rig import, VFX capture, UI interaction, GPU speedup, training run or owner aesthetic approval occurred for this patch.

## Main finding

Creative competence is a *closed, evidence-bound design workflow*, not a longer system prompt. STAR must preserve editable sources, meaning, device profiles and object identities as art passes through Blender, Roblox, and STAR's own desktop UI. Every output needs three independently assessed dimensions: (1) correctness and engine semantics, (2) performance and accessibility, and (3) human art direction. Passing a static check does not imply an attractive interface or convincing animation.

`owner brief / licensed references -> art direction -> semantic scene + motion + UI + VFX specifications -> cheap static checks -> editable native authoring -> low-cost preview -> true destination-engine replay -> targeted repair -> independent approval -> sealed holdout learning gate`

Do not replace existing sources, automatic review requirements, permissions, licensing terms, or `star/next` tests. Add improvements via a unique draft branch.

## What's already in STAR

* `star/blender_animation.py`, `star/blender_animation_worker.py`: strict R15/R6 clip preflight plus an experimental bone-only R15 Blender FBX worker. Not a production-ready avatar exporter; R6 import requires separate proofs.
* `star/animation_regression.py`: offline Euler-key comparison and sampled-motion anomaly warnings. It does not measure skeletal contact or native interpolation.
* `star/architecture_pipeline.py`, `scripts/blender_building.py`, `star/architecture_quality.py`: bounded exterior shells and export checks. No fully modeled architecture, authored meshes, or verified avatar navigation from that alone.
* `star/roblox_ui_compiler.py`: declarative JSON-to-Luau UI components, contrast warnings, mobile constraints and interaction states. Does not yet prove phone/controller design quality.
* `star/roblox_vfx_studio.py`: style profiles and event-stage VFX recipes, intended opt-in. Production visual quality still depends on authorized native playtests.
* `star/creative_review.py`: owner-bound screenshot hashes and review records. No model should set its own approval.
* Concurrent drafts: #578 creator VFX/batching, #588 creator evidence & scene topology, #589 visual quality audit, #533 secondary physics, #240 UI compiler. Reuse/sequence, do not delete or overwrite their work.

## What this implementation adds now

`star/creative_timeline.py` validates a non-executable, tightly bounded JSON choreography linking *existing* action names, Blender NLA layer declarations, animation markers and cosmetic Roblox events. It supplies:

1. One canonical timeline with 24–120 FPS, finite frame bounds, distinct clip/layer/event IDs, bounded event expansion, and SHA-256 of normalized intent.
2. Stable clip references, integer-duration repeats, known marker references, frame-accurate VFX/audio/UI/camera cue timings, and rejection of off-timeline effects.
3. Blender 5.x NLA *authoring plan* (1-based frames, strip order, `REPLACE` / `ADD` / `COMBINE`, fade regions, `NOTHING` extrapolation, explicit repeat counts); a plan, not a `bpy` execution.
4. A Roblox Animation Graph *handoff*, including marker and cue linkage. This does not create/publish graph assets; users or authorized tools must build and validate them in Studio.
5. Cheap static warnings for declared missing/overlapping full-body base motion, questionable additive full-body layers, questionable partial replaces, and over-limit *declared* event concurrency. These warnings are not actual frame-time or deformation measurements.
6. `camera`/`ui` event requirements for reduced-motion alternatives; no gameplay damage requests or arbitrary commands accepted in the input.
7. A read-only manual CLI, tests, and an original 90-frame sword demonstration.

The `weight sum` warning is a heuristic envelope, *not Blender's mathematical NLA compositing*. NLA `REPLACE` applies sequential mix semantics, while `COMBINE` uses property-specific math (quaternion multiplication for rotations), per Blender documentation. Native render and F-curve inspection remain mandatory.

### Run manually (from a source checkout)

```sh
python -m star.creative_timeline examples/creative_timeline/arcane_sword.json
python -m unittest discover -s tests -p test_creative_timeline.py -v
```

CLI prints a JSON plan only. It does not write to a workspace, run Blender, upload assets, edit a Roblox place, or train a model. The example names `RunCycle` and `SwordSlash` are placeholder action identifiers: it cannot animate without matching real existing Blender actions and manually authored marker tracks. Do not call this runtime-integrated yet; the agent dispatcher/UI hookup is intentionally deferred to review and permissions testing.

## Production animation/Blender research deep dive

### Rigging: geometry is only one part of an animated asset

Store *Rig DNA*: source mesh ID, bind pose, root axes, scale, parent map, export skeleton, animation slots, bone visibility, deformation flags, IK/FK control separation, per-vertex weights, facial blendshape conventions, and secondary appendage bones. `Rigify` is a control-rig generator, not proof of export-correct deformations. Use a deformation rig compatible with the chosen engine, and bake constraints when supported. Test arms, feet, tails, ears, mouth, eyelids, and extreme crouches with screenshots under skinning, not just neutral pose. Avoid silently treating R6 Motor6D as skinned R15.

### Animation blend correctness

A production clip needs a semantic intent and declared contact constraints, not merely Euler angles. Choreograph stance/anticipation, action, recovery, planted foot contact, pelvis/root velocity, and events such as footstrike, sword contact and facial cues. Foot sliding should be measured in world coordinates using host-observed root/joint transforms. Euler-angle difference alone cannot prove correct feet or rigid transformations; use quaternion/skeletal evaluation and real engine replay. Distinguish same-priority weighted blends from masks or priority overlays in Roblox. Bind upper-body additions only to their intended F-curves or graph masks; don't assume specifying `target:upper_body` actually masks a Blender Action.

Blender NLA 5.2 allows reusable named Actions and strips, tracks, modifiers and influence. Its `REPLACE` is an influence-weighted overwrite; `ADD` adds keyed values, `COMBINE` uses rotation-aware mathematics. Action Slots must match their target datablocks. The safe next step is a version-pinned, **fixed-source** Blender worker that reads only the validated choreography and applies it in an owner-chosen *copy* of a blend file, then extracts action/slot inventory and runs independent exporter checks. Do **not** execute model-generated Blender Python or arbitrary third-party add-ons.

Roblox Animation Graphs reached full release July 15, 2026. Graphs can implement Blend1D, Blend2D, state/sequence nodes, masks, phase synchronization and additive motion. Drive their published graph track parameters with `AnimationTrack:SetParameter`; listen to `GetMarkerReachedSignal` for cosmetic cues. Graph publication remains a separately approved owner/engine operation. Gameplay hits, inventory changes and combat authority must remain server-validated; animation markers can request display but cannot grant damage.

### Blender 5.2 LTS capabilities to turn into reviewed skills

* **NLA and reusable Action assets:** named semantic clip libraries with character, rig, slot compatibility, contact markers, looping contracts, and clear licensing.
* **Geometry Nodes:** modular trim, stairs, roof tiles, cables, leaves and terrain scatter as instances; avoid premature `Realize Instances` and repeated geometry evaluations.
* **XPBD node physics:** Blender 5.2 experimental hair/cloth can support authored, baked animation references. It does **not** transfer as live Roblox physics when exporting glTF/FBX; replicate carefully using the target engine's supported systems or bake the supported transforms.
* **Materials/textures:** UV integrity, consistent texel density, PBR color/normal/roughness/metalness paths, material variants, LOD budgets, import-side parity captures. Blender Eevee/Cycles appearance is not Roblox shading parity.
* **Scene design:** silhouettes, functional space planning, supports, doorway clearance, no unintentional mesh intersections, functional prop placements, stable pivots, style grammar (storybook/industrial/modern/horror/sci-fi). Use multiview render and gameplay camera.
* **Color/audio:** evaluated render at known color management settings, exposure and audio cues. Blender 5.2 has audio-reactive Geometry Nodes; test samples but do not claim automatic native Roblox transfer.

Prefer the production 5.2 LTS maintenance line (5.2.3 dated October 22, 2026) over bleeding-edge 5.3 beta for stable automation. Pin API version and regression fixtures. More GPU use does not necessarily produce better assets; schedule high-cost renders off the active 8-GB-VRAM gameplay/stream workload.

## Professional UI/UX research and checks

Think in reusable systems: type scale, text roles, colors, contrast, shadows, layout constraints, accessibility and explicit interaction semantics. A nice screenshot is not an input-operable GUI. The Roblox Style Editor and native stylesheet ecosystem support `StyleSheet`, `StyleLink`, tokens, selectors, themes, responsive queries, hover transitions and style-defined component states. Prefer first-class native Roblox UI and a single editable design system to rasterizing an entire HUD.

Automated checks should include screen-safe areas, hit targets, interactive collision/overlap, text clipping, missing essential buttons, label/action association, color contrast, Xbox/controller focus and selection transitions, reduced-motion behavior, and real touch/click activation. Collect screenshots from phone/desktop/console emulator settings plus a physical lower-powered device; don't infer all device behavior from a desktop capture. Avoid animated UI that obscures essential health, ammo, ability keycaps or characters.

For Star's own React desktop interface: style tokens, Motion animation and reduced-motion preferences must respect user settings, and visual tests should verify no pixel regression across app viewport sizes. Coordinate with existing UI PRs rather than creating a second frontend architecture.

## Layered VFX/audio/camera research

VFX should communicate causality: anticipation -> activation -> contact -> secondary reaction -> lingering debris/smoke -> cleanup. Create the effect stack around real animation markers, not independent timers that drift after playback speed changes. Be careful: an NLA timeline is an offline authoring clock, while real gameplay requires run-time marker signals and can undergo speed changes, replication latency, interruption or cancellation.

Roblox `ParticleEmitter` provides flipbook layouts, framerate, modes, emission rates, lifetime and cleanup methods. `Grid2x2`, `Grid4x4`, `Grid8x8` and custom grids have different tile and memory requirements; low-memory clients may degrade effects. Use mesh trails, camera shake, per-character effect pools, fixed maximum particle counts, local cosmetic emission, reliable cleanup and device-specific fallback profiles. Track measured draw calls, GPU/CPU frame time and texture memory with the actual MicroProfiler, not model-estimated numbers. Flash photosensitivity safety and reduced-motion settings matter, especially for frequent abilities.

## Visual intelligence: how STAR should actually correct itself

1. **Capture origin:** prove which authorized Blender/Studio process, rig version, project seed and editor/engine version produced the observation. File hashes are useful only alongside trusted capture provenance.
2. **Establish correspondence:** mapping from brief requirement -> object/action/mesh/GUI node -> exported object/Studio Instance -> rendered image region -> observed defect.
3. **Compare temporal samples:** start/end of fade, contact moments, seam, impact and device interactions. A still image cannot establish motion quality.
4. **Targeted repairs:** modify the specific bone curve, weight group, UI anchor, style token, particle rate, camera cue or prop transform. Preserve accepted assets and a rollback recipe.
5. **Separate three gates:** technical/static checks (repeatable), native device tests (measured), owner art approval (subjective but essential). Star's generated plan may be useful but never supply its own independent ground truth.
6. **Learn from verified changes:** record baseline/candidate side-by-side, true before/after checks, human art judgments, time/VRAM costs, source attribution and failure taxonomy; promote optional skills only after sealed, paired independent tests.

Avoid reward hacking, AI-generated self-ratings, invented captures, and silently approving a generated UI as "perfect". Humans can define art quality for a project; STAR can learn preferences from actual accepted edits, not hallucinate a universal beauty score.

## Research experiment slate (prioritized)

| Experiment | Measured output | Failure condition |
|---|---|---|
| Choreography manifest -> Blender NLA preview | Valid action-slot binding, strip timing, no misleading Action overlap | Incorrect slots, wrong deformation, no native capture |
| Native Roblox Graph Editor handoff | Published graph, synchronized locomotion and attack markers | Hand-coded placeholder called a native graph; missing asset permissions |
| Low-VRAM draft and selective rerender | Total wall time, frame time, peak RAM/VRAM and quality | Cheaper proxy hides important errors or produces worse acceptance rate |
| Star mascot rig/tail/ears hair physics | Close-up, side, gameplay-distance QA and deterministic collision replay | Twitching, obvious clipping, unexplained physics, unlicensed sample |
| UI challenge (animal shooter HUD) | Operable mobile/PC/controller, focus, clipping, small target checks | Overlaps ability keys, unreadable bars or missing hit actions |
| VFX impact cue challenge | marker/video alignment within calibrated tolerance + GPU profiling | Effect triggers on wrong event, persists after interrupt, excessive particles |
| Modular building kit | Studio import parity, no unattached walls, avatar access, prop placements | Facade looks like random primitives, broken collisions or UV/PBR |
| Sealed creator holdout | Paired owner scores, accepted assets, mean repair rounds/time | No statistical or quality gain against unchanged baseline |

## Research leads for future review (not installed by this patch)

- UniRig: research automatic rig/skin proposals; check per-model licenses, CPU/GPU feasibility, supported skeletons, and real weight deformation before using.
- Rigify: included Blender control-rig system, useful when control/deform skeleton distinction is explicit.
- Infinigen: procedural world and material grammar research; generated scenes do not automatically become production game assets.
- Khronos glTF-Validator: independent structural/content conformance check; required before native import, never proof of good animation.
- Poly Haven CC0: source-attributed production material/HDRI model references; license permits broad reuse but record exact provenance.
- Blender online Essentials asset libraries: remotely fetched asset data is untrusted, and library contents require review. Network is opt-in.

## Primary source references (reviewed October 25, 2026)

1. Blender 5.2 LTS releases and patch list: https://www.blender.org/releases/5-2/ ; https://www.blender.org/download/releases/5-2/
2. Blender NLA tracks: https://docs.blender.org/manual/en/5.2/editors/nla/introduction.html
3. Blender NLA blending/influence: https://docs.blender.org/manual/en/5.2/editors/nla/sidebar.html
4. Blender actions and slots: https://docs.blender.org/manual/en/5.2/animation/actions.html
5. Blender NLA Strip API: https://docs.blender.org/api/current/bpy.types.NlaStrip.html
6. Blender XPBD node physics explanation: https://code.blender.org/2026/07/geometry-nodes-physics/
7. Blender Geometry Nodes performance guidance: https://docs.blender.org/manual/en/5.2/modeling/geometry_nodes/performance.html
8. Roblox Animation Graphs full release: https://devforum.roblox.com/t/full-release-animation-graphs-create-complex-character-motion-visually/4739840
9. Roblox Animation Graph Editor and state machines: https://create.roblox.com/docs/animation/graph-editor ; https://create.roblox.com/docs/animation/graph-editor-state-machine
10. AnimationTrack parameters/events: https://create.roblox.com/docs/reference/engine/classes/AnimationTrack
11. Roblox Style Editor: https://create.roblox.com/docs/ui/styling/editor ; https://create.roblox.com/docs/ui/styling
12. Roblox asset importer: https://create.roblox.com/docs/studio/importer
13. Roblox particle flipbooks: https://create.roblox.com/docs/reference/engine/classes/ParticleEmitter
14. Roblox profiling and optimization: https://create.roblox.com/docs/performance-optimization/improve
15. Khronos glTF 2.0 specification: https://registry.khronos.org/glTF/
16. Khronos validator: https://github.com/KhronosGroup/glTF-Validator
17. Poly Haven CC0 licenses: https://polyhaven.com/license
18. Procedural world research Infinigen: https://infinigen.cs.princeton.edu/
19. UniRig: https://github.com/VAST-AI-Research/UniRig

## Integration and shipping gates

**Already done in this patch:** original source + tests + example + research, no permissions or settings altered; static-only offline test. **Still needed before native integration:** owner-selected opt-in tool schema, trusted Studio/Blender adapter, Action-slot inspection, real camera/frame evidence, comparable performance/quality benchmarks, independent owner art review, full repository CI on latest base, installer acceptance. Do not merge to main or deploy from draft. No policy, protected evaluations, CI/workflows, existing creator modules or active worktrees were edited by this patch.