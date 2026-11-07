# STAR AI: visual/spatial Studio QA and next-generation intelligence
**Research date: October 28, 2026. Implementation: offline Python-to-Luau compiler only; no real Studio or streaming deployment.**

## The highest-value improvement

More code or a larger prompt is not sufficient to make STAR smarter. The central quality bottleneck is **independent acceptance** of what she builds, plays, sees and says. The prior Studio smoke-test compiler only checked instance names, classes, size, location, opacity and simple properties. It could silently accept an arbitrary one of two identically named sibling Parts; it could not catch mismatched visual materials/colors/orientations; and it could not detect *designated* pairs of badly overlapping props.

### Delivered in the existing Studio-integrity compiler

1. **Unambiguous paths:** direct-child walks reject every duplicated sibling name along a checked instance path rather than trusting the first matching child. Missing paths still fail.
2. **Trusted, bounded visual expectations:** optional BasePart material allowlist, 8-bit RGB target plus channel tolerance, and orientation against the basis vectors of a declared Roblox orientation. These are independently specified by the owner or a trusted spec, not inferred from the possibly defective scene being graded.
3. **Explicit unwanted-overlap checks:** up to 16 owner-curated pairs of rectangular Block Parts in Workspace checked with a 15-axis oriented-box separating-axis test using actual test-session CFrames and Sizes. Rotated rectangles are handled; touching faces and intrusion below the specified tolerance are allowed. Non-Block shapes fail closed. Do not add intentional floor/wall joints.
4. **Bounded, reproducible spec:** every new expectation contributes to the SHA-256 manifest fingerprint; changing colors, rotations, or a no-overlap pair invalidates an old matching marker. The marker is **not** an independent signature or externally authenticated outcome.
5. **No permission expansion:** still emits text only; the server verifier requires Studio, the test-runner must execute from an authorized plugin in a disposable private Studio copy, and the compiler itself does not operate Roblox, issue network commands, generate gameplay inputs or interact with DataStores.

### A usable owner-curated test

~~~python
from star.studio_scene_integrity import SceneCheck, DisjointParts, StudioSceneTest, compile_scene_integrity

wall = ("Workspace", "Aquarium", "Arena", "NorthWall")
statue = ("Workspace", "Aquarium", "Arena", "Statue")
test = StudioSceneTest("arena_v2", (
    SceneCheck(wall, "Part", anchored=True, can_collide=True,
               expected_position=(0, 6, 14), minimum_size=(12, 10, 0.5),
               expected_material="SmoothPlastic", expected_color_rgb=(39, 112, 190),
               color_tolerance_rgb=6, expected_orientation_degrees=(0, 0, 0)),
    SceneCheck(statue, "Part", anchored=True),
), simulated_clients=2,
    disjoint_pairs=(DisjointParts(wall, statue, penetration_tolerance_studs=0.05),))
bundle = compile_scene_integrity(test)
assert not bundle.verified_in_studio
# Install the returned server_script into ServerScriptService in a PRIVATE test
# copy. A trusted plugin runs the returned plugin_script after place approval.
~~~

### Limits that matter

Material and Color are object properties, not pixel-accurate visible appearance; baked textures, MeshPart TextureIDs, SurfaceAppearance, lights and postprocessing can all change the output. An orientation basis match does not guarantee good UVs or artistic quality. The SAT overlap test only covers explicitly designated rectangular Part pairs; it is not a whole-scene collision audit or physics simulation. Name ambiguity is a runtime error, not an instruction to arbitrarily rename parts. Real screenshots, private playtests, UI checks and animation checks remain necessary. Every generated run is a **smoke test**, not a proof the game is fun or production-ready.

Validation limits: 1–64 scene checks, 0–16 declared disjoint pairs, 1–8 simulated clients, safe ASCII path segments, bounded finite tolerances, class/material allowlists. No user-authored Luau interpolation; runtime plugin failure or mismatched/missing result cannot pass.

## Verified external research (October 28, 2026)

Roblox documents property/shape checks for Part and distinguishes Block, Ball, Cylinder, Wedge and CornerWedge. StudioTestService supports plugin-launched multiplayer tests with up to eight simulated clients, returning a server result. The testing guides also describe VirtualInput and device simulation. These official APIs are opportunities for the **next** Studio acceptance step; they are not already wired to this compiler.

- https://create.roblox.com/docs/parts
- https://create.roblox.com/docs/reference/engine/classes/StudioTestService
- https://create.roblox.com/docs/studio/testing-modes
- https://devforum.roblox.com/t/new-studio-testing-apis-and-assistant-improvements/4657854
- https://robloxapi.github.io/ref/enum/PartType.html

OpenGameEval (posted October 1, 2026) tests thirteen frontier models across 84 Roblox Studio tasks with executable scene/play checks; a model inspecting relevant objects before editing is associated with higher success. GameWorld evaluates verifiable game outcomes in 34 games/170 tasks; it emphasizes state-grounded control rather than self-graded success. VISTA (posted October 26, 2026) explores active self-improvement through new interactive experiments and a history of verified harness changes. These are research pointers, not demonstrated STAR capability.

- https://arxiv.org/abs/2610.02563
- https://github.com/Roblox/open-game-eval
- https://gameworld-bench.github.io/
- https://arxiv.org/abs/2610.35051

For faster local models, official llama.cpp supports speculative decoding with small draft models, EAGLE-3 and n-gram options; each can hurt latency/VRAM if poorly matched. Small Kyutai Pocket TTS English models support a possible CPU voice pathway while the GPU runs a game; VTube Studio supports injected facial parameters. Always A/B test real first-audible latency and expressiveness, not the model-size marketing claims.

- https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md
- https://github.com/ggml-org/llama.cpp
- https://github.com/kyutai-labs/pocket-tts
- https://github.com/DenchiSoft/VTubeStudio/blob/master/README.md

## Prioritized Star upgrades beyond this branch

**P0: Real Windows Studio acceptance.** Connect emitted checks to the existing approved Studio Lab identity/permission gate. Test in disposable private place copies only, never production DataStores. Test with 1, 2, 4 and up to 8 simulated clients where supported; inspect independent scene state and camera screenshots. Add client input tests for platforming, HUD, spawn/replication, interactions and win conditions. Visual failures (z-fighting, wrong materials/texture UVs, misaligned props, unreadable UI, odd lighting) require separate screenshot-and-geometry quality gates. End with human review and actual playability tests.

**P1: Self-directed game mastery.** Integrate existing game vision, action controller, independent outcome receipts, episodic evidence and skill memory into observation -> hypothesis -> permitted action -> verified result -> practice -> unseen-level evaluation. Split practice and evaluation maps/physics seeds; compare retries and success curves, not claims of feeling or intelligence. Respect each game's permissions, multiplayer rules and opt-outs. Keep an experiment lineage in Star Core Forge and roll back tactics that fail outside training.

**P1: Expand general knowledge honestly.** Index documents, videos and approved gameplay observations with source, date, license, trust tier, revision and confidence. Separate directly witnessed events from speculative interpretation and third-party claims. Invalidate time-sensitive facts and contradictory answers; measure source-backed answer accuracy on withheld topics, not just the number of items in a database. Keep personal viewer data private and ephemeral by default.

**P1: Real speed gains on 8 GB VRAM plus 32 GB RAM.** Benchmark *matched*, representative 30-minute mixed sessions: Roblox gameplay, OBS encoding, Live2D, voice, visual understanding and background knowledge tasks. Collect first token/first audible delay, prefill, tokens/sec, RAM/VRAM peaks, 1%-low FPS, encoder/render drops, mouth sync drift, hallucinated visual events and outcome success. A/B prompt caching, quantized KV, a selected speculative decoding method, CPU offload, frame region-of-interest vision and GPU/CPU admission control individually. Keep gameplay and voice latency priorities; shed research workers rather than slowing a live broadcast. Do not claim gains without measured benchmarks.

**P1: Star as a natural and believable virtual performer.** Coordinate game-state attention, turn taking, short genuine reaction utterances, emotionally appropriate laughter, lip movements driven by **played audio**, gaze and blink micro-movements, spring-physics ribbons and twin tails, occasional cat/puppy character modes and chat focus recovery. Test actual listening preference and synchronization against baseline. Let Star remember only authentic game achievements, conversations with consent and her own completed work; do not invent human memories or suggest she is biologically human. A lively, autonomous virtual character can feel personable without being misrepresented as human.

**P2: Better self-owned Star Core Forge.** Treat every self-improvement as a bounded experiment with exact inputs, snapshot, source diff, evaluation, evidence, provenance and automatic rollback. Offline-first internal history and tested promotion are primary; GitHub is optional publication/review and a draft PR is not a deploy. A coding agent, retrieved website or chat message must not gain permission to publish, spend or act as a player.

## Required acceptance before stronger claims

The changed Python and generated Luau text have only been tested **offline**. No Luau compiler pass, Windows Roblox/OBS/VTube Studio run, game-state check, real collision, human listening judgement or actual inference benchmark has been completed for this branch. The work is one concrete improvement to *verification coverage*, not evidence of increased model intelligence, faster neural weights, game mastery, human-quality streaming or consciousness. Keep new checks off unless an authorized host explicitly requests them; do not automatically merge or deploy.
