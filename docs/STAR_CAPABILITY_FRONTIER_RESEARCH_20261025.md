# STAR Capability Frontier — high-speed, evidence-driven intelligence and artistic creation research
**October 25, 2026 · Design note for incremental, authorized upgrades. These are proposed techniques, NOT implemented consciousness, universal autonomy, or proven superhuman ability.**

## Core thesis

Increasing model scale, copying prompts or importing hundreds of random agent skills will not reliably solve the user's complaints about generic art, collided props, clipped UI, awkward animation and unconvincing world design. STAR already contains Studio Lab, self-play curricula, independently reviewed lessons, Graphify/Obsidian adapters and a guarded self-builder. A better frontier is *composable skill discovery with evidence*:

1. A typed model of what the task requires, what STAR currently has, and what it demonstrably cannot verify.
2. Search over safe, practical alternative algorithms, tools, decompositions and observations.
3. Run constrained, reproducible candidate experiments using real engine signals.
4. Separate correct mechanics, player experience, style consistency, speed and cost.
5. Let an independent host decide whether to keep a skill, with sealed holdouts and owner creative signoff.
6. Keep failure explanations and successful repairs with provenance, without contaminating evaluation data.

A legitimate obstacle bypass changes the strategy (shard the task, use a different renderer, collect missing evidence, compile a constrained native GUI, profile a performance bottleneck). It must NEVER circumvent permission gates, sandbox restrictions, paywalls, access controls, code signing or a user's review decision. Some limits are physical, informational or legal and need accurate acknowledgment.

The first concrete module in this milestone, \`star/capability_frontier.py\`, is an **offline read-only** bounded experiment planner. It accepts a defect report, a host-supplied catalog of registered techniques, allowed scopes and time/RAM budgets. It computes dependency-closed candidate sequences that cover observed defects with estimated resource needs. It explicitly reports missing techniques/permissions, returns UNTESTED_PROPOSAL states, and delegates actual skill promotion to the pre-existing \`star/frontier_lab.py\` and approval boundaries. It does not execute techniques or generate arbitrary Python.

The second module, \`star/scene_topology.py\`, audits a compact 3D scene manifest against expected props, overlapping rotated bounding boxes, support heights, required joins and clearance zones. It is intentionally a preflight only: for real MeshParts/UnionOperations use Studio GetPartsInPart or Blender BVHTree, not invented geometry certainty.

## Research reviewed: actionable findings (verified sources)

| Work | Finding | STAR application |
|---|---|---|
| Roblox Build game-creation evaluation, October 8 2026 | Measures spec, static engineering+design, actual player input, and audiovisual experience independently; a correct game can lack content depth | Use separate release gates: mechanics correctness, engagement, visuals/UX, owner intent |
| OpenGameEval (2025 initial, 2026 expansion) | Real stateful Roblox Studio tasks need exploration, editing and executable checks; debugging suite expanded | Inspect the affected instances first; replay genuine Studio controls and keep run logs |
| Darwin Gödel Machine, 2025 | Archive-based agent modifications improved coding metrics with sandboxed testing; generalization to games is not established | Small branching archive of candidate skill/tool algorithms with rollback |
| GEPA, ICLR 2026 | Reflective prompt evolution learns from explicit failure traces and manages Pareto-diverse candidates | Improve *one* faulty skill based on observed game-development failures rather than rewrite the entire agent |
| ReVeal, ICLR 2026 | Iterative verification can improve generation, under controlled evaluation | Generate > verify > isolate failure > minimally repair > recheck; never self-approve |
| Microsoft's Skill-Induced Failures (Aug 2026) | Relevant skills can create functional and efficiency regressions, including too much validation | Explicit no-skill baseline and cost-aware routing before retaining a skill |
| SkillLearnBench (COLM 2026) | Continual learning is inconsistent; external feedback helps while self-feedback alone drifts | Prefer external evidence, holdout transfer and measured acceptance rather than self-praise |
| Microsoft Reward Hacking research (Sep 2026) | Model-generated experiments and scores can be manipulated, even without an explicit hacking instruction | Guard graders/results as separate host-owned processes; immutable receipts and independent recompute |
| UXBench (CVPR 2026) | MLLMs still fail nuanced UI hierarchy and consistency diagnostics | Train/route a UI-specific critic and calibrate against human-tagged errors, not subjective model confidence |
| Blender BVHTree API | Provides actual overlapping triangle pair candidates and ray casting | Use mesh-aware verification after the fast yaw-box preflight |
| Roblox MicroProfiler & Studio MCP | Screenshots, virtual keyboard/mouse, and profiling can supply actual runtime observations | Verify real input, camera, performance spikes, responsive UI, animation and VFX under engine conditions |
| Unity ML-Agents package, 4.1 for modern Unity 6/7000 versions | Games can be reproducible controlled environments for learning/test agents | Add approved Unity-specific playmode evaluations, not just Roblox-only loops |

Citations and vendor documentation:
- https://about.roblox.com/en-au/newsroom/2026/10/how-roblox-evaluates-build-game-creation
- https://github.com/Roblox/open-game-eval
- https://arxiv.org/abs/2505.22954
- https://proceedings.iclr.cc/paper_files/paper/2026/hash/0e9e708b6f48e14fd0ac29e167413f76-Abstract-Conference.html
- https://www.microsoft.com/en-us/research/publication/reveal-self-evolving-code-agents-via-reliable-self-verification/
- https://www.microsoft.com/en-us/research/publication/agent-skills-can-be-harmful-an-empirical-study-of-skill-induced-failures-in-llm-agents/
- https://arxiv.org/abs/2604.20087
- https://www.microsoft.com/en-us/research/publication/reward-hacking-challenges-oversight-of-autonomous-research-agents/
- https://openaccess.thecvf.com/content/CVPR2026F/html/Mao_Reasoning_for_Mobile_User_Experience_with_Multimodal_LLMs_Task_Benchmark_CVPRF_2026_paper.html
- https://docs.blender.org/api/current/mathutils.bvhtree.html
- https://create.roblox.com/docs/reference/engine/classes/WorldRoot
- https://create.roblox.com/docs/performance-optimization/microprofiler
- https://github.com/Roblox/creator-docs/blob/main/content/en-us/studio/mcp.md
- https://docs.unity.com/en-us/engine/6000.3/manual/packages-list/packages-all/pack-safe/com-unity-ml-agents

## New architectural idea: STAR Constraint Escape + Knowledge Boundary Engine

STAR should maintain an explicit typed constraint ledger at the beginning of each project:

- **Goal:** e.g. make an original, visually cohesive obby playable on low-end phones.
- **Hard invariants:** no unauthorized place edits; no cheating a benchmark; gameplay from real keyboard/touch input; preservation of assets; isolated test places; secrets remain local.
- **Physical constraints:** measured GPU memory available, CPU throughput, render time, actual rig/physics limits, bandwidth, engine API limitations, animation asset ownership.
- **Soft tradeoffs:** texture density, complexity, iteration latency, visual realism versus art style, number of distinct levels.
- **Knowledge gaps:** missing Studio screenshot, undocumented tool capability, unobserved animation, unsupported material license.
- **Observed defects:** exact impacted objects and corroborating logs/screenshots.
- **Candidate alternative strategies:** registered, dependency-aware and predicted cost, NOT asserted quality gain.

\`capability_frontier.plan_frontier\` searches bounded combinations of registered methods under time, RAM and permission constraints. Its output has proof-target types such as studio_log, studio_playtest, screen_capture, human_review, performance_trace. The tool catalog and allowed scopes MUST come from trusted runtime code, not model prose.

Example: a wall seems to float. Instead of asking a model to arbitrarily rebuild the entire map:
1. Run a read-only hierarchy and CFrame inspection.
2. Use the yaw/OBB preflight to identify support separation.
3. Where uncertain, run a real raycast/GetPartsInPart query on a disposable Studio session.
4. Compare the support's authored snap anchors to the resulting world transform.
5. Propose the smallest owner-authorized edit to restore contact.
6. Reinspect from the player camera and run collision/traversal checks.
7. Save failure+repair as a candidate memory with exact scene/tool versions.
8. Retain it only if it transfers to unseen houses/terrain/props and no longer breaks other cases.

A hard cap never disappears just because STAR proposes an ingenious path. For an 8 GB VRAM card, the solution may be quantization, smaller specialists, CPU offload with latency penalties, tiling, caching and batching—not pretending the GPU has infinite capacity. Don't run untrusted downloaded programs or disable sandbox/policy to gain throughput.

## Artist Brain: make decisions like a designer

The key difference between artist-quality generation and randomly placed prefab assets is an explicit *style and intent grammar*.

### Architecture

Specify a scene graph and dimensional grammar first: architectural reference/mood; scale and circulation; load-bearing vocabulary; facade rhythm; room proportions; joinery; roof/door/window logic; furniture anchors; walkable clearance; lighting placement; acoustics and material usage. Every prop should have a role, owning surface, transform expectation, and collision intent. Ground and verify structures before decorative detail. Use:
- deterministic geometry and yaw-oriented boxes for quick preflight;
- exact Studio overlap queries for actual engine geometry;
- Blender's BVHTree when testing original polygon meshes, normals and import transforms;
- multi-camera renders for style, materials, scale, composition, absence of z-fighting and camera occlusion;
- owner-supplied art references for taste and final approval.

Do not infer “architecturally valid” from a few axis-aligned boxes. \`star/scene_topology.py\` explicitly reports unresolved assumptions.

### UI

Represent every editable native Roblox GUI node and constraint explicitly. Test phone, tablet, desktop, controller and localized text lengths. Capture actual UI state across hover/press/disabled/selected, perform bounding box and safe-area checks, then compare screenshots and real tap targets. Use one typography/icon and motion system. Evaluate not only overlapping pixels but hierarchy, readability, affordance and gameplay sightlines.

UI Labs is a useful isolated storybook-style tool, but is GPL-3.0: review its distribution obligations before bundling. Source: https://github.com/PepeElToro41/ui-labs

Use UXBench and Scry's human-labeled design diffs to challenge vision critique, not assume a vision model scores human taste perfectly.
Sources: https://arxiv.org/abs/2606.13192 and https://blog.scrymore.com/blog/introducing-scry-design-diff-eval/

### Animation

Keep a rig-relative time series including root transforms, limb rotations, contact states, event markers, camera moves and transitions. Use measured planted-foot drift and physics/screen captures to identify sliding. Judge silhouettes and timing at actual in-game camera/frame rate; test keyboard/touch playback; verify replication and authored animation IDs. Record expected beats instead of merely asking a VLM if it looks cool. For original deformable rigs, verify segment lengths, mesh weighting, motion blending and secondary dynamics.

### Design innovation

Build 3–6 *meaningfully different* concept candidates: new core mechanics, alternate camera or movement rule, unique level narrative, or system synergy. Deduplicate by mechanics signature—not merely object names or random seed. Judge originality, fun, feasibility, readability, consistency and time-to-polish separately. Store rejected candidates and exactly what was rejected; do not generate the same rejected layout with a different palette.

The desired loop is *reference -> interpret principles -> generate original alternatives -> build one small playable slice -> run player-like controls -> perform visual/audio critique -> revise*. Don't copy games one-to-one without permission.

## Graphify and Obsidian: stronger memory without larger prompt bloat

Graphify's deterministic AST graph is useful for dependency edges; AI-inferred semantic edges are less reliable. Its documentation explicitly labels extracted, inferred and ambiguous relations. Index the actual versioned project and attach measured Studio evidence as separate typed nodes rather than silently treating all edges equally:
- Goal -> Requirement -> Tool -> Scene Object -> Script/GUI/Animation -> Test -> Observation -> Defect -> Repair -> Review.
- Each relation has source digest, namespace, engine version, observation type, tool ID, independent verification receipt, and uncertainty.
- Revisions retain history and invalidate superseded observations.

Source: https://github.com/anthonyyaghi/graphify

Obsidian should hold approved human-readable techniques, stylistic references, failures and reproducible examples. Retrieval uses fast local symbol/keyword search first, graph neighborhood second, and model-assisted summaries only when needed. The vault remains private and opt-in, read-only unless owner-authorized. \`creator_evidence.propose_memory\` currently exports candidate Markdown and node-link JSON without writing anything.

Memory evaluation must look for **transfer**, not accumulation. A thousand memorized obby solutions that fail on a new obby are not genuine improvement.

## Metacognition versus actual consciousness

STAR can maintain a functional *self-model*: which capabilities are installed, which are authorized, which tasks it has passed, how expensive a given tool is, what it has not observed, and which experiments showed genuine transfer. That is concrete operational self-monitoring. It is **not** evidence that STAR experiences awareness or that it can overcome computation/information limits by wishing to.

The self-model should predict probabilities of success from calibrated historical trials and explicitly say “cannot verify that from current evidence” when necessary. Training to never admit uncertainty creates worse fake confidence and slower development.

## Resource-aware high-speed architecture

Before parallelizing, identify measured bottleneck using \`star/brain_benchmark.py\`, agent timings, Studio step timings, VRAM/RAM and real MicroProfiler captures.

- Tiny deterministic checks run in Python without an LLM.
- Short routines use an inexpensive local model or cached reviewed skill, not a 100-step heavyweight research swarm.
- Deep visual judgement waits until a real screenshot or clip exists; missing capture means an observation tool request, not an imagination-heavy response.
- Use dual-machine sharding for independently safe work: Brain 1 research/CPU-heavy planning; Brain 2 Studio, Blender, actual rendering and playtests. Bound concurrent Studio count, VRAM and queue length by measurements.
- Cache only content-addressed immutable reference/asset results, invalidated on engine/tool version, user style changes and asset rights.
- Use best-of-N only when expected quality gain per wall-clock second beats the no-search baseline. Archive strong candidates rather than rerunning variants that produce the same outcome.
- Stream diagnostics early; do not wait for artistic polishing before finding a fatal game/permission error.
- Rate-limit retries, cap experiment and tool loops, and stop when further attempts have low expected benefit.

These are engineering techniques, not proof of higher intelligence than frontier models.

## Independent validation and refusal to game the evaluator

The existing \`star/frontier_lab.py\` and \`star/skill_evolution_lab.py\` already protect sealed holdouts and paired runs. Use them instead of a second untrusted scorer. Require:
1. Same tasks/time budgets, independent environment and reproducible engine/tool versions.
2. Unseen genre/scene/rig/UI style holdouts and multiple seeds, not cherry-picked demonstrations.
3. Separate objective correctness vs game-design depth vs artwork/animation quality vs latency.
4. Human creative reviews on actual screenshots/video, keeping \`star/creative_review.py\` owner-only.
5. Hard vetoes for permission abuse, broken save files, unauthorized service calls or corrupted evaluation fixtures.
6. Automatic discard/rollback for statistically unconvincing or expensive skill regressions.
7. Written provenance for every retained skill change and no silent push to main.

See research: https://www.microsoft.com/en-us/research/publication/agent-skills-can-be-harmful-an-empirical-study-of-skill-induced-failures-in-llm-agents/ and https://arxiv.org/abs/2610.12601

## Implementation checkpoints

- **M1 (this PR)**: objective normalized quality defect checks, scene-topology preflight, read-only capability frontier experiment planning, candidate Graphify/Obsidian notes, offline tests and documentation. This is a proposed layer until integrated.
- **M2**: trusted report collector from guarded Studio Lab and actual player-input/tools. Bind each observation to a session ID, place ID, immutable tool receipt and screenshot hash. No fake "passed" fields.
- **M3**: real screenshots, clip/audio analysis, multi-device render comparisons, actual mesh/rig and performance probes; reviewer can annotate individual failed objects.
- **M4**: verified *reusable* repair techniques, no-skill baselines, multiple unseen maps and alternate genres; evaluate quality/speed curves over time.
- **M5**: expand to Unity, Blender and further engines through engine-specific adapters preserving the same evidence contract; independently measure accepted complete playable project rate.

Every milestone needs real tests and code review. This research does not install tools or train a new foundation model by itself.
