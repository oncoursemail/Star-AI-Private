# STAR AI — verifiable Roblox scene integrity, game intelligence and natural VTuber roadmap
**Date:** October 28, 2026. **Status:** source-backed design + locally tested OFFLINE code; not deployed.

## What this iteration actually implements

`star/studio_scene_integrity.py` introduces a pure, deterministic compiler for **bounded, owner-curated Roblox Studio smoke tests**. `SceneCheck` asserts named instance presence, expected class, anchored/collision behavior, maximum transparency, geometric position tolerance, minimum dimensions, and optionally a minimum number of model descendants. `StudioSceneTest` validates 1–64 distinct checks, pins a suite identifier and requests 1–8 simulated clients. `compile_scene_integrity` emits two separately installed Luau scripts: a test-server verifier and a manually run, authorized Studio plugin script.

The compiler **does not execute Studio**, create or modify objects, control Roblox, fetch assets, authenticate a game or certify visual quality. It serializes prevalidated numbers and quoted names; never interpolates arbitrary model-supplied Luau. The emitted hash marks the manifest version, **not** an independently signed outcome. Never treat compiled text or a simulated test as proof a real game passed.

Why this matters: missing walls, disconnected props, out-of-place parts, transparent walls and undersized terrain can hide behind otherwise successful Luau compilation. Inspecting the scene and running targeted checks is more informative than asking STAR whether its own build looks right. Many problems still need geometry probes, visual frame analysis, game-feel evaluation, and player playtests beyond this new smoke test.

## Verified source research: Roblox Studio test capabilities

1. Roblox's official `StudioTestService` API allows plugins to start scripted test modes and multiplayer sessions, and allows the test server to return a result using `EndTest`: https://create.roblox.com/docs/reference/engine/classes/StudioTestService .
2. Roblox's official Studio testing modes documentation describes up to eight simulated clients and the `VirtualInput` capability for exercising actual input paths: https://create.roblox.com/docs/studio/testing-modes .
3. Roblox's new testing APIs announcement adds device simulation and scripted UI/input workflows; these are a clear path beyond simple Part property checks: https://devforum.roblox.com/t/new-studio-testing-apis-and-assistant-improvements/4657854 .
4. Roblox's DataStore guidance warns that Studio access to a live experience's data stores can modify production data: https://create.roblox.com/docs/cloud-services/data-stores . **Do not enable production data-store access for an automated test**.
5. Existing STAR `studio_test_farm.py`, `studio_loop.py`, `studio_practice_runner.py` and `gameplay_skill_bank.py` already implement separate admission, protected-input and signed-evidence principles; extend those, do not create a competing permission system.

## How to run a manual acceptance rehearsal

- Create a **disposable, private Studio copy**, verify universe/place identities and that all asset rights permit local testing. Never insert a verifier into an unapproved published experience.
- Have an owner or trusted local host define expected objects/size/position from an independent design specification — not from STAR's own possibly defective scene. Generate both scripts offline using `compile_scene_integrity`.
- In the private test copy, place the verifier as a normal server Script under `ServerScriptService`. Run the matching plugin code using an authorized plugin with no other test active. Check that the returned result matches the manifest marker. A missing server verifier must produce **no pass**.
- Repeat with 1, 2, 4 and when supported 8 simulated clients. Verify physical spawning, replication, UI on multiple aspect ratios, player join/leave, interaction, audio and network behavior **separately**; the supplied smoke test itself currently checks static scene properties only.
- Turn the smoke test into one gate of a broader **build acceptance matrix**: source check (Luau lint/type), scene shape/attachment, Studio playability, gameplay mechanics, visual screenshots, animation/VFX, accessibility, frame pacing and multiplayer.
- Store results with provenance (test manifest hash, pinned Roblox build, code commit, trusted host timestamp, actual Studio logs and optional independently signed outcome); don't allow model-authored PASS strings to enter the evidence bank.
- Record failures as `missing / wrong class / misplaced / too small / collision / transparent / incomplete` and route repair proposals through Star Core Forge's isolated best-of-N candidates, tests and rollback. Human sign-off before publishing.

## Intelligence and game-learning upgrades with measurable gates

**A. Action-grounded game understanding.** Keep perception, proposed action, actual authorized input, and independent state observation separate. Precommit predictions before action; accept success only via trusted game-state evaluation, never an AI's claim. Create increasingly difficult but bounded practice sessions. Pin game versions and keep hidden holdouts inaccessible to the planner. Evaluate exact task success, false success rate, time to learn a new mechanic, and performance on unseen maps/games.

**B. Better game creation.** Use scene-integrity smoke tests as a cheap preflight before expensive Studio simulation. Add read-only attachment audits, camera-path screenshot comparisons, terrain collision checks, map traversal and multiplayer repl/latency checks. Optimize for a *playable, polished result* instead of code volume or arbitrary numbers of features. If a test fails, let a bounded repair agent inspect and propose modifications, then rerun independent checks; preserve rollback.

**C. General knowledge.** Maintain source-backed, versioned retrieval over verified APIs, code docs, gameplay tutorials and licensed assets. The assistant must distinguish verified facts, observed gameplay, hypotheses, and creative fiction. Freshness thresholds and per-source licenses are necessary; more indexed material is not automatically better reasoning. Measure citation correctness, grounded question accuracy, unknown-answer restraint, code execution quality, and memory retrieval cost. Do not use private streams/chat as public training corpora.

**D. Faster local inference.** The upstream llama.cpp project maintains speculative decoding and server throughput tools. Evaluate draft-model versus n-gram speculation *on this hardware and actual prompts*, and choose using tokens/sec, p50/p95 first-token time, GPU memory, total power and accuracy, not promotional percentages. Source: https://github.com/ggml-org/llama.cpp/tools/server/bench/speed-bench/README.md and https://github.com/ggml-org/llama.cpp/common/speculative.cpp . Preserve responsive audio/gameplay on an RTX 4060 8GB-class GPU; if a second PC is available, move offline analysis there. Keep new acceleration flags OFF until quality and FPS gates pass. Test caching and slot count independently to avoid KV-memory exhaustion.

**E. More naturally animated, conversational VTuber.** STAR should coordinate actual game context, speech playback and body motion: eye saccades, blink rhythms, ear/ribbon/twin-tail physics, mouth movement synced to audible PCM, expressive but infrequent gestures, a quiet focus mode, interruptions and moderated deferred questions. Base jokes and stories on things she genuinely observed. Animated cat/puppy modes and viewer banter are character performance, not evidence of human consciousness or personal experiences she did not have. The VTube Studio public API supports parameter injection; preserve authenticated local-only access: https://github.com/DenchiSoft/VTubeStudio .

**F. Streaming acceptance.** Use paired blind human evaluation with genuine but consented game contexts. Score first-audible latency, turn-taking and awkward silence, hallucinated game events, laughter naturalness, repeat phrases/hour, eye/mouth desync, dropped OBS frames, 1%-low game FPS, and interruption recovery. Don't increase stream talking frequency just to look more human. Require explicit broadcast permission and never auto-open a public chat, use chat messages as tool permissions or impersonate a real human.

## Risks, priority and release discipline

1. First pilot this exact static-scene compiler in a disposable private Studio session and add true game-state receipts. **No gameplay or streaming was actually performed in this iteration.**
2. Next build a host adapter to run the generated tests through existing authorized Studio workflows, rather than a second Studio controller. Add independent geometry + visual evidence reviews. Avoid production data stores.
3. Pilot verified gameplay on Brain 2; keep expensive vision and model comparisons off-stream or on Brain 1. Enforce game FPS/OBS/audio headroom.
4. Pilot voice/Live2D with true device-audible timing and human review; compare default Kokoro with opt-in Pocket TTS before selecting any voice backend.
5. Preserve Star Core Forge as the local-first record of experiments and rollbacks. Publish to GitHub only as an optional reviewed export; retain a **draft PR** and do not merge without Windows acceptance.

**Security:** The GitHub repository named `Star-AI-Private` is reported publicly visible. Treat every pushed file as world-readable: never publish tokens, unreleased media, genuine viewer identities, internal IPs, private files or biometric material.

**Acceptance boundary:** Locally passing Python tests validate this compiler's input checks and emitted text. They cannot establish that generated Luau ran in Studio, improved real-game builds, sped up model inference, improved gameplay skill or sounded more human on-stream.