# STAR AI — retained gaming skill, natural conversation, slow–fast intelligence and deployment research

Date: 2026-10-31
Status: engineering research + two opt-in policy changes; NOT deployed or benchmarked on the Windows gaming/streaming host.
Scope: local-first, owned/authorized gameplay, game creation, private-by-default VTuber rehearsal, Star Core Forge, and CPU/GPU inference optimization.

## 0. Verified code changes in this revision

1. star/stream_turntaking.py: an authenticated VAD stream now checks the silence between the previous frame's end and the new frame's start before accumulating continuous speaker evidence. Previously, four separated 30-ms owner frames, 80 ms apart, could sum to the 120-ms owner barge-in threshold. The new 40-ms maximum unobserved silence is conservative and leaves truly continuous frames intact. No host speaker authentication, microphone processing, TTS cancellation or network traffic is provided by this function.
2. star/game_practice_curriculum.py: signed practice aggregates whose most recent observation is over seven days old now require explicit independent reassessment at the lowest unmastered tier rather than implicitly unlocking harder tasks. The age window is configurable (60 seconds to 30 days). A lifetime total cannot tell us whether the skill is still retained, and one new event cannot by itself prove retained mastery; therefore the reason is REVIEW_REQUIRED, not automatic retraining/promotion.
3. Tests: synthetic sparse-VAD and signed-practice-expiration cases. These tests assert policy semantics only; they do not establish real game skill, a true voice identity, or any deployed performance improvement.

## 1. A useful distinction: speed, reasoning quality, and successful action

STAR must evaluate three different outcomes separately:
- Responsiveness: end-to-end capture-to-action age, time to first audible speech, mid-utterance interruption and 95th-percentile stall duration.
- Correctness: independent game outcome, factual QA grounded to sources, Luau test outcomes, hallucination rate, and visual/artifact defects.
- Robustness: held-out scenes, unfamiliar maps, different game versions, packet loss, sleep/resume, OBS restart, resource overload and practice retention after inactivity.

Optimizing only generated tokens/second is insufficient: a faster response can worsen gaming outcomes if it is stale when dispatched. October 15's Realtime-Bench study separates Wall Clock, Paused Clock and Token Clock to reveal these tradeoffs; use the same three modes in STAR's evaluation harness, never report paused-clock gains as live wins.

Source: https://arxiv.org/abs/2610.22155 (Realtime-Bench, submitted October 15, 2026).

## 2. Slow–fast execution without starving the game

Suggested host pipeline:
- Game capture adapter (trusted, exact game session; no browser/model claims as verified observations). It emits monotonically numbered observations and wall/monotonic timestamps.
- Reactive controller: small and predictable; computes immediate legal action from the newest state and a compact plan cache. Rejects stale observations at dispatch using GameActionFreshnessGate.
- Deliberative tutor: stronger local model, possibly on a different machine, that studies recordings and verified outcomes between bouts. Produces a bounded, versioned plan candidate with evidence and expiry; never directly presses game keys.
- Curriculum: signed practice outcomes -> next curated exercise -> separate host game launch authorization -> independent performance evaluation -> retain or roll back. Old aggregate confidence requires reassessment, not silent assumed retention.
- Forge: saves the candidate plan, task/test hashes, model/runtime identity, measured resource costs and reason for acceptance; previous known-good plan is always available. Do not expose held-out seeds to the tutor.

Evidence: The June 23 Latent Bridge paper demonstrates the benefits and caveats of separating reactive and deliberative models. It also shows that combining distinct communication channels can seriously interfere. START with a short, typed text/structured plan bridge; do not add a trainable latent bridge unless a controlled A/B test shows a net benefit.

Source: https://arxiv.org/abs/2606.24470 (The Latent Bridge, June 23, 2026).

Acceptance protocol:
- Host-defined tasks; holdouts include unseen maps, seeds, game version, and difficulty; check scenario-level pass and latency regression.
- At least three fixed-seed paired runs per experimental profile for instrumentation sanity, followed by sufficient disjoint holdouts for confidence. Use the existing signed bank and promotion rules for actual qualification.
- Compare fast-only, tutor-on-between-attempts, and tutor-on-continuous under the SAME game-clock regime.
- Record p50/p95 observation-to-physical-input age, retries, game wins, crash count, RAM/VRAM, OBS losses and audio jitter. PRE-dispatch age is not proof that a physical key was pressed.
- Retest retained skills after 1, 7 and 30 days with independently verifiable fresh trials rather than lifetime aggregates. Treat curriculum expiry as a reminder to get that data, not as proof of actual forgetting.

## 3. Faster local inference: experiments not blanket toggles

llama.cpp provides continuous batching, speculative decoding and monitored server slots; each may trade more memory or latency for throughput. Its official SPEED-Bench evaluates speculative draft acceptance, throughput and latency per workload. Cache reuse has nondeterminism and isolation considerations; STAR already has an opt-in synthetic cache-contamination probe.

Authoritative references:
- https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md
- https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md
- https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md

Experiment matrix for an 8-GB RTX 4060:
- Primary: stable quantized single request, no speculative draft, reduced context. Measure baseline while game + OBS + TTS run.
- Next: vary context size and GPU layers; confirm no OOM or unexpected context truncation. Run private cache-isolation probes under concurrent synthetic identities.
- Then: compare n-gram speculative decoding and small draft models, but only if resident memory stays comfortably below the live GPU VRAM budget. Test the same prompt suite and compare answer correctness.
- Last: multiple slots and continuous batching only if total stream responsiveness improves. More concurrency may increase individual request latency.
- Keep the stream admission / OBS health evidence authoritative: pause expensive work immediately when capture or stream quality degrades. Do not infer a performance win from an idle GPU benchmark.

Compute schedule: during broadcasts favor game/OBS/voice, use cheap reactive observations, batch deep research on Brain 1 or during intermissions, and keep GPU-heavy game creation and video generation outside live broadcasts. Rust is worth considering only for measured Python bottlenecks in high-frequency frame transport or scheduling; it will not automatically accelerate model inference or Studio work.

Proposed thresholds for initial Windows A/B acceptance (targets, not achieved results): no added OBS render/output loss above 1% rolling, no material degradation of the game's p95 frame time, under 250-ms p95 pre-dispatch observation age on supported simple tasks, and first audible response under 500 ms for short local voice replies when resources allow. Define per-game thresholds before experiments; harder tasks may require a different decision interval.

## 4. Human-natural VTuber behavior without invented human history

Naturalness primarily comes from turn-taking, expressive timing, grounding, and personality consistency, not merely larger language models.

Priority live loop:
1. Moderated viewer or owner speech -> echo suppression -> trusted VAD -> local end-of-turn detection -> TurnTakingGate.
2. If confirmed owner barge-in during speech: host stops actual audio, invalidates pending facial animation and caption timing, then informs StarStage; an advisor return alone must not count as interrupted audio.
3. If guest is speaking: pause new speech (do not grant guest owner privileges). Avoid answering every chat message; select relevant and safe prompts at a calm rate.
4. Distinguish one continuous utterance from short sparse noise bursts. The current synthetic VAD continuity fix does not replace a validated acoustic pipeline.
5. Compose a short, factual utterance using only accessible game observations/approved knowledge; Stage's moment journal provides bounded suggestions, not human-biography claims.
6. Drive mouth/eye animation from audible playback time, not raw text-generation time; interrupted speech must stop lip movement and expressions synchronously.
7. During combat or tight platforming, prioritize gameplay and purposeful silence. At safe transitions add reactions, brief jokes, questions, and genuine reflection; never force constant chatter.

LiveKit documents a locally running CPU v1-mini audio turn detector. Its role is end-of-turn prediction, not owner speaker authentication, game input authorization or voice cloning. Its documentation expects an accompanying VAD and a minimum VAD silence duration of 250 ms; this is a separate timescale from STAR's short-frame continuous-owner barge-in check.

Source: https://docs.livekit.io/agents/logic/turns/turn-detector/

Kyutai released Pocket TTS 4.0 on October 20 and 4.0.1 on October 21, 2026. These include new tiny English CPU model variants. A host experiment should compare listener-rated voice naturalness, phoneme errors, startup latency, language coverage, CPU load and game frame time. Do not silently overwrite Star's accepted voice, nor clone any real person's voice without consent.

Source: https://github.com/kyutai-labs/pocket-tts/releases

Persona specifications:
- The Star, Astro and Amber companion personalities remain consistent with the owner's approved character designs and modes (including optional cat/dog expressions). This is design direction, not a claim of biological consciousness.
- Maintain a private fictional-lore store separate from real experience memory. A character may tell clearly fictional stories; it must not invent viewer interactions, games played or history as factual memory.
- Natural laughter uses situation-appropriate expressive timing plus audio-aware animation; avoid inserting laughter in every sentence.
- Add post-stream viewer-rated samples (with opt-in): perceived latency, conversational naturalness, awkward interruption count, repetitive phrases, inappropriate overtalk and facial sync errors.

### Avatar, gaze and hair-physics implementation path

A convincing model is a synchronized interactive character, not a constant stream of random gestures. STAR should use one monotonic playback clock as the source of truth for lip shapes, glances, blink timing, pupil travel, head angle, breathing, tail movement and the approved Star/Astro/Amber companion reactions. Scripted facial animation is a host-controlled performance layer, not evidence of genuine emotional experience.

Live2D Cubism physics settings are exported in physics3.json and evaluated by the Cubism runtime. Physics responses can be driven by head/body motion and parameterized gravity/wind; use the approved twin-tail shape and ribbon as visually checked constraints. A rig-quality test should render neutral, whisper, laugh, surprised and look-left/right key poses, then verify the hair remains attached and does not cross the face or shoulders unnaturally.

Source: https://docs.live2d.com/en/cubism-sdk-manual/physics/
Source: https://github.com/Live2D/CubismSpecs/blob/master/FileFormats/physics3.json.md

VTube Studio's documented local plugin API supports triggered hotkeys and injecting custom facial/body parameters through WebSocket. The host can make typed, bounded parameter updates based on audible phoneme/viseme timing and game events. Keep the API on loopback, require the user-enabled plugin access and token authentication, do not put credentials in public GitHub, and never allow chat text to become unvalidated parameter IDs, hotkey names or commands.

Source: https://github.com/DenchiSoft/VTubeStudio/blob/master/README.md

Proposed playback and animation contract:
- An utterance has an immutable stage ID, playback ID, monotonic start time and cancellation generation. Sample the actual audio buffer clock; text generation timestamps are only estimates.
- Lip shapes and jaw opening follow real audible amplitude/phoneme cues. A cancelled utterance invalidates every queued mouth pose and caption after the host acknowledges cancellation.
- Eye micro-saccades and blinks have individually seeded, bounded timing; surprise, confusion, concentration and laughter use authored poses rather than arbitrary parameter noise.
- Hair/ribbon springs react to actual angular motion; excessive wobbles are suppressed in low-motion mode. Check geometry clipping and mouth-to-audio lead/lag in a rendered 30-minute rehearsal.
- Star/Astro/Amber interactions are coordinated with separate animation layers and ownership of the conversation turn. An off-screen companion must not interrupt the owner or represent unverified viewer speech.
- Character costumes, proportions and silhouettes follow the owner's accepted direction; tools must compare generated rigs to approved art references rather than guessing.

## 5. Game creation: verified artifacts instead of attractive screenshots

STAR's Studio pipeline should be inspect -> specify scene graph -> generate Luau/assets -> validate syntax/API -> place -> run Studio multiplayer simulation -> inspect gameplay visuals -> repair -> rerun -> promote artifact.

Roblox officially documents StudioTestService multiplayer simulation up to eight simulated clients, with plugin-side ExecuteMultiplayerTestAsync. Use this for join/leave, replication, lobby, server/client ownership and race conditions; do not confuse a pass in one Studio simulation with actual live-server scalability.

Source: https://create.roblox.com/docs/reference/engine/classes/StudioTestService/AddPlayers

Structural game-build invariants:
- Anchored/connected walls, correct collision groups, prop-local coordinate frame, no missing meshes or Z-fighting, consistent character grip and collision scale.
- UI contrast, hierarchy, focus/gamepad navigation, safe-area clipping and screen-size regressions; evaluate using captured screenshots plus deterministic layout assertions.
- Animation contacts and hand-grip IK, playable camera constraints, loading transitions, audio onset sync, motion-reduced option, basic accessibility.
- Separate gameplay UX tests from game-style ratings: attractive screenshots do not show that a round starts, win/loss works, multiplayer replicates or a store is correct.

A larger asset library is not the goal by itself. Keep provenance/license in the asset index, check package signatures, and only present verified reusable designs rather than scraping every repository indiscriminately.

## 6. General intelligence, self-directed learning and Forge deployment

A local intelligence architecture must separate:
- Reference knowledge: source URL, publication date, trust tier, verification date, expiry rules, entity/version scope, contradiction/confidence metadata.
- Episodic evidence: what Star actually observed on approved sessions, with a retention policy and redaction.
- Procedural skills: typed preconditions, ordered steps, failure diagnostics, verified examples, environment version and a bounded rollback strategy.
- Hypotheses: explicitly unverified ideas that do not enter facts or production policy automatically.
- Fiction: roleplay and character lore, visibly separate from real-world facts and actual stream experiences.

A knowledge gain is counted only when blind new tasks show improved correctness without retrieval leakage, overconfident unsupported answers, performance regressions or hidden costs. Keep unknown-answer tests. Train or edit a skill only after failing cases are collected; re-evaluate older capabilities to catch forgetting.

Star Core Forge should remain the local system of record. GitHub is optional publication/review, not a dependency for local tests, version history or rollback. Suggested artifact manifest: {experiment_id, parent_snapshot, code_hash, model_hash, prompt_hash, dataset_hash, provenance, test_manifest, resource_profile, evaluation, approval_class, rollback_target}. Allow routine sandbox experiments without repeated approval, but require host authority for external posting, financial transactions, high-risk system writes and production actions.

## 7. Immediate Windows integration checklist

P0: Run the new synthetic tests on the PR and repair any failure. Keep the PR draft until the suite passes.
P0: Bind owner/VAD voice frames, OBS status, action timestamps and signed game evidence to the same trusted host session; never accept viewer/chat/model-generated provenance flags.
P1: Execute a 30-minute offline game + OBS recording + Star voice + avatar rehearsal with the new continuity gate. Verify actual interrupted playback and camera/mouth timestamps, plus performance telemetry.
P1: Use fresh signed retention trials to validate the curriculum's seven-day staleness gate. An age rule is a *prompt to reassess*, not a demonstrated cognitive forgetting curve.
P1: Compare local TTS versions under game/OBS load and measure actual voice onset, prosody, laughter, CPU threads and memory budget.
P2: Compare fast-only and tutor-assisted gaming on unseen seeds with the same Wall Clock. Preserve rollback and reject scenario-level regressions.
P2: Create a StudioTestService sample suite for game joining/leaving, movement controls, UI flows and replication, with captured visual defect checks.
P2: Use Forge to archive reproducible verified lessons and periodic blind general-knowledge evaluations. Export only reviewed/public artifacts to GitHub.

## Evidence and limitations

These implementation changes are conservative policy checks, not proof of humanlike emotions, consciousness, trained model weights, streaming performance improvements or gaming skill. They intentionally do not control the Windows desktop, OBS, Roblox Studio, microphone, model backend or game input. Host/session integration and real hardware benchmarks are still required. Public GitHub repositories must not be used for secrets, unapproved viewer recordings or confidential game telemetry.
