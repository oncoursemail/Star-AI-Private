# STAR Creator Brain — evidence-first game building and visual-quality research
**October 25, 2026 · Research + tested offline quality-evidence checker · NOT a new AAA-trained model**

## Why this exists

STAR is meant to create complete, art-directed Roblox and Unity experiences, not just compile scripts. Passing Luau checks is not proof that platforms connect correctly, a wall is aligned, a player can see the next obstacle, a jump animation makes physical sense, touch controls work, or a game is actually fun.

In October 2026 Roblox described a creation evaluation split into separate axes: game specification, static engineering and design, actual player-input playtests, and visual/experiential quality. In one example, an obby scored 98/100 for engineering and 100/100 for playtesting yet only 31/100 for game design. This is why STAR must not substitute "working code" for "professional game."
Source: https://d3kmd4famnmhh.cloudfront.net/newsroom/2026/10/how-roblox-evaluates-build-game-creation

OpenGameEval (2026) measures real Roblox Studio tasks and finds that inspecting affected objects before edits is important. STAR should run the reproducible benchmark under comparable limits instead of claiming superiority without test evidence.
Sources: https://arxiv.org/abs/2610.02563 , https://github.com/Roblox/open-game-eval

## What already exists in STAR (augment, don't duplicate)

- star/studio_loop.py and star/studio_lab.py: owner-gated Studio edits, geometry/path probes, playtesting, screenshot capabilities, iteration and undo. Scripted avatar probes do NOT substitute for keyboard/mouse/touch control.
- star/roblox_craft.py and star/architecture_quality.py: useful deterministic craft/geometry heuristics. These don't judge aesthetic appeal.
- star/roblox_ui_compiler.py: native, editable Roblox UI from a declarative specification. Never replace the interface with a flat screenshot.
- star/creative_review.py: separate owner review bound to actual candidate source and screenshot evidence. Preserve this authority boundary.
- star/graphify_bridge.py: bounded, read-only exported code graph. Treat extracted facts and inferred connections differently.
- star/obsidian_bridge.py: opt-in local Markdown vault reader. Preserve existing private vault and read permissions.
- star/knowledge.py, star/lessons.py, star/selfbuild.py: project-scoped evidence, reviewed lessons and constrained self-builder. Learning proposals are NOT automatically trustworthy.

## New code in this change

star/creator_evidence.py takes a bounded, normalized JSON record of evidence from an already trusted test wrapper. It performs read-only deterministic QA and returns a defect ledger with one of three states:
- needs_repair: an observed failure is reported;
- needs_evidence: important testing observations are absent;
- ready_for_review: no flagged issue in the supplied report, but no quality certification or release permission.

Checks: stated requirements linked to passing acceptance evidence; mobile/desktop safe-area UI bounds; overlapping interactive hit targets; phone touch-target review heuristic; unintended 3D penetrations only when reported as measured in Studio; missing animation event markers; excessive planted-foot slide heuristic; real virtual-input versus teleport/script-only playtest methods; reported runtime exceptions; missing screenshot evidence for phone/desktop.

The code does not authenticate reported observations. A generated fake JSON could falsify results; a future trusted adapter must attach hashes/logs from the actual Studio session and independently validate their provenance. Screenshot SHA-256 presence is NOT image understanding. Genuine visual critique and human creative signoff remain separate.

propose_memory(report) creates candidate Graphify-style node/link JSON plus a proposed Obsidian Markdown lesson. It does not alter a graph, write to a vault, approve a lesson, train weights or update an agent's permissions. Source and capture hashes enable an independent reviewer to trace the proposed correction.

CLI in a working source checkout:

    python -m star.creator_evidence path/to/capture.json --propose-memory
    python -m unittest discover -s tests -p test_creator_evidence.py

Tests focus on fixed contract behavior, adversarial oversized/malformed input, intentional versus unintended contact, UI overlap and safe-area errors, animation regressions, missing real playtest input and non-mutating candidate lessons. Tests are offline. Live Studio game QA was NOT performed by this patch.

## Proposed complete Star Creator Brain

### Layer A — Director: intent before output

1. Create a short canonical, versioned game brief that captures the owner's actual requirements: genre, look, mechanics, level progression, camera, supported devices, UI/animation priorities, accessibility, performance budgets and deliverables.
2. Convert requirements to IDs with observable acceptance tests. Track unknown assumptions explicitly rather than silently replacing the user's vision with a generic template.
3. Create an art-direction board: architecture shape grammar, material palette, surface roughness, light/color hierarchy, silhouette rules, typography/icon family, motion principles, camera composition and audio mood.
4. Maintain one consistent aesthetic across native GUI, characters, stages, particles, icons and animations. The reference board informs designs; it is not permission to redistribute copied works.

### Layer B — Librarian: references that are legally and technically usable

Source references from official developer documentation, creator tutorials, actual screenshots, recorded demonstrations and permissively licensed assets. For each: creator/source, URL, version/date, usage license, attribution requirements, target engine, whether it can be redistributed, local checksum and confidence. Reference retrieval is opt-in where network access is involved. Reject unknown-license material for automated distribution, and never copy other developers' complete games.

Use official engine semantics to avoid hallucinated APIs. Roblox built-in Studio MCP has official connection/read/edit/playtesting and screenshot features; discover methods dynamically and keep guarded permissions.
Sources: https://create.roblox.com/docs/studio/mcp ,
https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643 ,
https://devforum.roblox.com/t/assistant-updates-mesh-generation-new-mcp-server-tools-screenshot-tool-and-more/4527258

Recommended source-checked tools:
- Roblox: built-in Studio MCP; Rojo, StyLua, Selene, official Luau analyzer; native Roblox animation editor, IKControl, TweenService, UI layouts and device emulator.
- Previews: React-Lua and UI Labs (check the latter's GPL-3.0 before bundling/distributing). Never replace native editable GUI with rendered UI art.
- 3D: Blender in a constrained separate worker, glTF checks, Blender Rigify, approved PBR material packs with license metadata.
- 2D/texture concepts: existing STAR ComfyUI path; inspect weights, models and checkpoints and their individual licenses before deployment.
- Unity: official Test Framework and ML-Agents for controlled testing/learning; use editor-integrated tests and play mode rather than pretending scripts demonstrate game quality.
- Graph understanding: Graphify / tree-sitter, including Luau coverage where supported by grammar/version; don't assume an old graph describes the latest repository.
Sources: https://github.com/rojo-rbx/rojo ; https://github.com/JohnnyMorganz/StyLua ;
https://github.com/Kampfkarren/selene ; https://github.com/luau-lang/luau ;
https://github.com/PepeElToro41/ui-labs ;
https://github.com/Graphify-Labs/graphify ;
https://unity-technologies.github.io/ml-agents/ ;
https://docs.unity3d.com/Packages/com.unity.test-framework@latest ;
https://docs.blender.org/manual/en/latest/addons/rigging/rigify/index.html

### Layer C — Specialist workcells (shared scene/brief, different QA)

- World architect: real scale, modular assembly, join/snap rules, topology, sensible pivot/origin, lighting, sightlines, intentional contact sets, colliders and traversal volumes.
- UI artist: information hierarchy, type scale, responsive layout, safe insets, contrast, icon consistency, controller/phone/mouse interactions and readable animation.
- Animation director: R15 or target rig compatibility, keyframes, IK, planted contacts, root-motion intent, easing, secondary motion and reliable transition markers.
- Gameplay director: server-authoritative core loop, hazards, checkpoint/retry, progression, input feel, controls, onboarding and repeatability.
- VFX and audio artist: particle texture design, stage timing, event coupling, readable impact feedback, occlusion, mix and mobile budget.
- Visual critic: actual Studio/engine screenshots and brief video clips viewed independently from the code writer, with clear observations, uncertainty and before/after comparisons.
- Optimization lead: frame-time tails on target phones/PCs, streaming, draw/triangle/particle budgets, memory, network and replication constraints.
- Learning curator: extract repeatable defects and verified repairs while respecting user approvals and evaluation holdouts.

These specialists can share one bounded context graph and reference citations without loading all project files into every prompt.

### Layer D — Authentic verify-and-polish loop

Request -> versioned brief -> retrieval and design language -> architecture/UI/animation alternatives ->
compose editable game -> read actual engine state -> static/build/security checks ->
run disposable place with actual virtual keyboard/mouse/touch inputs ->
capture viewport/rig/audio/performance observations -> classify defects ->
repair ONE affected layer -> regressions on other layers -> compare candidate with baseline ->
owner-visible review -> delivery of editable source, evidence and remaining limitations.

Run rough order:
1. Prevent broken game logic and missing required features.
2. Fix impassable geometry, bad collisions and broken respawn/camera/input.
3. Fix clipped/overlapping GUI and unplayable mobile controls.
4. Fix mismatched materials/scale, unprofessional silhouettes and inconsistent art direction.
5. Polish animation contact, timing, VFX, sound and mood.
6. Tune frame-time worst cases, stable network and memory.
7. Perform final blind quality review, not self-certified "AAA".

Bounding-box spatial queries produce potential contacts; Roblox WorldRoot:GetPartsInPart is appropriate for exact occupied-part overlaps. Intentional floor/wall contacts should be explicitly allowlisted and not mislabeled as defects.
Sources: https://create.roblox.com/docs/reference/engine/classes/WorldRoot#GetPartBoundsInBox ;
https://create.roblox.com/docs/reference/engine/classes/WorldRoot#GetPartsInPart

### Layer E — Obsidian + Graphify evolution

**Graphify** should function as an evidence-grounded dependency and mistake graph, not simply a bigger memory dump:
- Typed nodes: scene object, scripted behavior, module, GUI component, asset, design rule, movement phase, requirement, acceptance check, defect, repair and tool.
- Typed edges: requires, controls, renders, collides-with, visually-occludes, tested-by, caused-by, fixed-by, contradicted-by, compatible-with.
- Per edge: source hash, timestamp/version, source tool, certainty, project scope and owner decision.
- Query "what broke when I changed jump animation" by tracing motion state, GUI, movement and tests, not by returning arbitrary similar files.
- Candidate discoveries must never masquerade as code-parsed or Studio-verified facts.

**Obsidian** should act as a human-readable design notebook and durable approved-skill library:
- One short, reviewable note per recurrent defect/repair, with minimal reproduction, environment, before/after evidence, why it worked, when it failed, and owner feedback.
- Suggested links to techniques and accepted art direction, but default read-only vault boundary stays.
- Conflict detection, version/supersession, per-game context, canonical source links, bounded retrieval and explicit note approval.
- Don't ingest a private personal vault into a shared model, external embedding API or public Git repository.

**Learning loop**: discover/observe -> isolate cause -> propose controlled candidate -> run reproducible tests -> compare with baseline on unseen holdout cases -> owner review -> activate only if quality and speed improved -> monitor drift -> disable on regression. This is autonomous *skill acquisition and workflow refinement*, not a promise of unconstrained recursive model self-training.

### Layer F — Intelligence and speed on existing hardware

Use cheap deterministic validators for geometry, schema, layout and static lint. Reserve an expensive vision or reasoning model for ambiguous design judgments. Cache only immutable documentation/artifact results by hash+tool version. Use best-of-N only where the expected gain exceeds latency and GPU/RAM contention. Run CPU/retrieval planning on Brain 1 and actual Studio/render/evidence capture on Brain 2 when owner-authorized. Independent render/test candidates can be parallel, but limit concurrency by measured VRAM, memory and p95 throughput. A small 4B local model won't become a frontier-scale model through knowledge retrieval alone; measured routing, specialized skills and reliable tools are the practical lever.

### Metrics and comparison

Track distinct metrics rather than a single invented "smartness" number: accepted requirement coverage; executed player-input test pass; runtime errors; unintended scene penetrations; GUI hitbox overlap and safe-area violations on multiple devices; animation marker/foot-plant defects; blinded human art-direction rating; gameplay interest/replay; mobile p10 FPS; time-to-first working vertical slice; time-to-accepted delivery; tool/model total cost; and how often a reviewed lesson transfers to a new scene.

Compare STAR to ChatGPT/Claude/others only under matched hardware, tools, source material, time budgets, available assets, repeated trials and independently chosen holdouts. Do not give STAR access to hidden graders or allow it to mark its own work as approved.

## Concrete sequence

M1 (this PR): independent offline creative evidence schema, defect checker, tests, and proposed Graphify/Obsidian lesson records. No studio or vault mutations.
M2: authenticated adapters from existing Studio Lab, roblox_craft and first-party MCP virtual input; 1 genuinely replayed disposable place proof.
M3: approved multi-view screenshots/audio/motion capture and human-assisted visual critique; preserve native editable Roblox GUI.
M4: three fully playable owned mini-game vertical slices (parkour, shooter, horror) with style consistency and adversarial device tests.
M5: opt-in Unity loop plus blinded cross-agent comparative benchmark and a longitudinal learning-transfer gate.

Safety and accuracy: no automatic publishing, changed credentials, unguarded Studio code execution, unauthorized remote machines, public vault upload, secret collection, auto-merging, model-generated eval fixtures or forced integration into main. Test results for this PR are offline unit tests, not evidence of final AAA games.
