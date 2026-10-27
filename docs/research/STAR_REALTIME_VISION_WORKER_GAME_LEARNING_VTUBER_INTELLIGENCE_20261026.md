# STAR: real-time vision worker safety, game intelligence and natural VTubing

**Research updated:** 2026-10-26 (America/Chicago; 2026-10-27 UTC).  
**Status:** Implemented: visual-admission hardware bridge, worker quarantine after timeout/revocation, latency-aware sampling and offline regression tests. Researched only: gameplay-controller integration, avatar/audio application, model benchmarks, autonomous knowledge improvements and physical Windows performance outcomes.  
**Release policy:** AI-authored, owner-review draft. Offline first; Star Core Forge remains the autonomous development system, GitHub is an optional review/publishing mirror. Never automatically merge to main or broadcast.

## 1. Problem found in STAR's actual architecture

The existing `star/stream_observe.py` admitted bounded visual-inference requests using a 64-bit perceptual fingerprint, event novelty and `StreamTelemetry` with conservative online/offline sampling. But it treated a ticket timeout as though the inference worker had stopped. The next request could be admitted while the old GPU worker was still executing. On an 8 GiB GPU shared with a game, OBS, avatar and TTS, that can multiply VRAM pressure, cause hitches and make both gameplay and streaming worse. It also left the visual admission scheduler as a standalone component: production host telemetry wasn't connected directly to it.

### Implemented in this change

1. **Physical-worker quarantine.** Deadline expiry moves an active vision ticket into a quarantine state; a new request cannot start until the *trusted host* acknowledges actual worker termination. Disabling capture or restarting the session does not clear the quarantine. Old, late outputs are discarded, not learned from.
2. **Separate explicit worker-stop acknowledgement.** `acknowledge_worker_stopped(ticket, now_ms, worker_stopped)` refuses speculative cancellation, mismatched tickets or boolean impostors. This is a host attestation, not cryptographic proof of process termination.
3. **Feedback-controlled sampling.** A 16-result rolling window tracks actual finished request durations; the nearest-rank p90, multiplied by an owner-selected safety factor (default 2), lowers observation request frequency when inference becomes slow. It never raises the pre-existing maximum (1 FPS live; 4 FPS offline). Both admitted and deferred decisions report the *effective* target frequency, not an optimistic policy maximum.
4. **Actual hardware integration.** `StreamVisionHost` connects an owner-authorized `RealtimeTelemetryHost` to `ObservationGovernor`. Admission uses only fresh, real GPU, RAM, CPU, game-present and speaker-backlog samples. Missing CPU, stale FPS or unavailable hardware measurements fail closed. No caller-provided FPS values, model claims or chat text are accepted in place of hardware.
5. **One-shot host leases and session epochs.** A `VisionLease` is issued for a single observation; reservations survive disable until the host stops the worker, and stale/forged lease copies cannot finish a newer session. Metrics are aggregate counters only.

**Important interface contract:** The host owns image capture, model runtime, permission checks and worker termination. This PR does not capture a frame, infer a game event, create a new game control capability, run OBS, or make Star playable. All methods are host-only and must not be exposed as LLM or audience tools. Perceptual hashes are heuristics about change, not proofs of gameplay achievements. The trust boundary also applies to `worker_stopped=True`: it is appropriate only after join/exit verification from the actual process supervisor.

## 2. Why this is relevant to smarter game-playing agents

### A three-speed architecture

**Fast reflex (20–100 ms, conditional on real hardware):** deterministic action constraints, time-based game cues, safe mouse/keyboard or virtual-controller commands authorized by the player. Do not put a slow language model into a 30–60 Hz reflex loop.

**Medium perception (0.25–2 seconds):** a selective visual/language model produces structured descriptions of *changes*, not a full scene essay every frame. Schedule only when a location, HUD indicator, hazard, menu, objective or recent action warrants new information. Reuse verified observation state for near-identical frames.

**Slow planning and offline practice (seconds to hours):** analyze mistakes, create hypotheses about mechanics, select deliberate experiments, rehearse with game engine test fixtures, compare signed outcomes and store transferable skills.

Real-time interaction research recognizes the delay mismatch between reactive actions and deliberative multimodal reasoning. See *The Latent Bridge* (2026-06-23) and *GameWorld* (2026-04-08), which explicitly treats game action validation, latency, context memory and verifiable task results as important benchmark dimensions.

### Data required to actually learn mechanics

For each authorized local game practice episode: game/version, abstract objective, starting situation/seed commitment, legal action sequence, monotonic frame/action times, game engine state observation at start and end, score or completion verdict from **independent game engine/host**, collision/error traces and a sealed train/validation split. Use `GameTrial`, `GameMechanicProbeLab`, `GameTransferEval` and `ActivePracticePlanner` instead of inventing another incompatible skill ledger.

Apply hypothesis-driven probes: “Does holding jump extend range?” must be tested with matched starts, multiple random seeds and independent outcome checks. **Never treat a viewer's text, a VLM's impression of a win, a GIF, or a generated success string as completion evidence.** Unknown outcomes stay unknown. Promote a skill only after precommitted, withheld cross-level evaluation; retain negative results and counters.

DeepMind's SIMA 2 (November 13, 2025) demonstrates the value of following high-level goals across held-out game worlds, but is a research preview, not a plug-and-play Star dependency. The April 2026 GameWorld benchmark has 34 games and 170 state-verifiable tasks, highlighting how far agents still are from human-level general gameplay. Treat it as a *testing design pattern*, not a claim Star has solved gaming.

### Roblox creation is a second, different evaluation pipeline

A good builder must validate **structure AND appearance AND playability**. The game project needs an object graph with room anchors, wall/floor connections, valid local orientations, collision clearance, material consistency, navigation routes, art direction constraints, named prop zones and per-device GUI safe areas. Then inspect the actual Studio DataModel, run scripted Luau checks, playtest movement and interaction, and capture visual evidence for independent judgment. No generic “generated and looks good” success claims.

Roblox's April 15, 2026 Studio/Assistant announcement explicitly describes planning → building → playtesting with code, model and logs in the loop; official Studio documentation also distinguishes real Play/Test Here/Run modes. *Code2Games* (2026-10-04) studies connecting spatial/scene and gameplay representations across engine generation. STAR should reuse that idea for persistent prop-to-mechanic correspondence rather than placing random meshes by language.

## 3. The human-natural VTuber stack Star needs

The target is convincing, entertaining **AI character performance**, not deceptive claims that a digital avatar is actually a human.

**Attention:** combine real game phase (danger / quiet / menu), signed events, viewer messages (moderated) and owner's explicit priority. During a difficult section Star is allowed to go quiet, then resume with a concise game-grounded reaction; don't narrate every frame.

**Voice:** first *audible* speech is the latency metric. A generated PCM buffer is not an utterance. Separate the text planner, prosody/emotion plan, chunked synth, speaker queue, physical-audio acknowledgement and avatar mouth/blink/tail motion. If a turn is interrupted, stop the device first; invalidate stale animation sequences and keep the host's safety lease until physical stop is confirmed. Star's prior stream governor, speech recovery, and conversation-fairness work already provide relevant pieces; this vision release should connect, not replace them.

**Turn-taking:** LiveKit's current documentation distinguishes speaker activity, true interruption, brief acknowledgements, false interruptions, endpointing, and preemptive generation. STAR's own gated VAD should be calibrated with measured room/game audio, including echo cancellation. An owner correction can yield the floor; random audience chat cannot issue OS instructions. Natural reactions require real events and occasional silence, rather than canned laugh every 10 seconds.

**Expression and motion:** derive brows, lip shapes, eyes, shoulder/head movement, hair physics and cat/puppy emotes from audio + verified game mood. Avoid uncanny constant smiling. Offer a reduced-motion setting. An expression change must be bound to the *currently audible* speech plan. Never assert she “remembers winning” without recorded evidence, although fictional personality lore can be expressed transparently.

**Voice budget:** Kyutai released much smaller Pocket TTS variants on **October 20, 2026** (18.2M, 6.9M and 1.9M parameters). CPU TTS could preserve VRAM while Star games, but model size alone doesn't guarantee low first-audio latency or human-like voice. Compare multiple engines by consented human listening, level artifacts, tail latency and actual game FPS. Do not download a voice clone from an unconsenting person.

## 4. Faster intelligence without breaking game FPS

Proposed offline A/B search matrix, in ascending memory risk:

| Candidate | Why it may help | Ground truth |
| --- | --- | --- |
| Tool/result cache with versioned sources | Saves duplicate work on stable knowledge and game explanations | Revalidation correctness and cold/warm p95 |
| Selective vision + p90 duration feedback (implemented) | Fewer redundant expensive game-frame analyses | Vision invocations/min, confirmed work completions, game p99 frametime |
| Grammar/n-gram speculative decoding | Potential token throughput increase with no extra draft model weights | Effective output tokens/wall-time, first-audible p95, generated correctness |
| Quantized KV cache / context budgeting | May fit longer verified episodic context in an 8 GiB card | Accuracy on held-out questions, cache memory, spill rate |
| Small CPU speech model | Reserve GPU capacity for rendering, physics and necessary vision | Actual PCM emission, clarity ratings, FPS, CPU load |
| Fast/slow conditional routing | Spend expensive reasoning only on unfamiliar/hard tasks | Successful game decisions/task, wall time, power and rollback rate |

Official llama.cpp documentation explains speculative decoding choices and statistics; acceptance rates and throughput are model- and hardware-dependent. A new “faster” route must beat the same held-out task/stream at **equal or better factual accuracy and successful audible-response coverage**, not merely a best-case tokens/sec screenshot.

The present change **does not** install speculative decoding, TTS, or retrain a model. It is a GPU-workload integrity and host-admission improvement. Positive vision throughput or FPS change on Windows remains unmeasured.

## 5. General knowledge, independent growth and Star Core Forge

Use a two-stage system: (1) structured source knowledge (owner-approved, dated, attributed, with revocation/TTL) and (2) tested behavioral capability (solving new questions or playing new levels). More bytes in a vector store do not make the base model smarter. STAR already has `KnowledgeRecallPlanner`, `KnowledgePracticeHost`, signed holdouts and a local self-improvement platform. Add high-quality, license-safe topic curricula: STEM, history, visual design, comedy, conversational context, Blender/PBR, physics, Luau, digital audio, accessibility and security.

Prioritize **learning rate as improvement per verified GPU-minute**, not merely “questions generated per hour.” Fix one benchmark weakness at a time, use independent hidden judges, keep a frozen baseline and periodically run a withheld task distribution. Maintain a multi-agent proposer → code/test worker → independent verifier → Star Core Forge review → rollback checkpoint chain. Never treat generated tests or agent-authored grades as independent proof.

A realistic feature Star could add next is an **adaptive curiosity queue**: she identifies low-confidence knowledge/game areas, requests a bounded offline experiment, generates 3–5 alternative hypotheses and uses an independent evaluator to decide whether any hypothesis improves real task success. Don't train on the evaluation split, use copyrighted/secret data without permission, or self-modify the evaluation keys.

## 6. Empirical protocol on Star's real machines

1. **Baseline profiles:** Windows 11 + RTX 3060 Ti (8 GiB) or dedicated RTX 4060 (8 GiB); record driver, CPU, RAM, model quantization, resolution, game, scene, OBS render preset, voice engine and session flags. Don't assume the two GPUs are equivalent.
2. **Triplicate A/B trials:** 3 or more matched, seeded scenes per profile; run baseline and candidate in alternating order. Use physical frame-present records (e.g. PresentMon), host-reported speaker PCM timestamps, OS/NVIDIA resource snapshots and explicit worker exit acknowledgements.
3. **Metrics:** game p50/p95/p99 frametime and 1%-low FPS proxy; VRAM peak/free; first-audible p50/p95; speech complete/failed/cancelled; voice overlap and end-of-turn false interruptions; vision requests, completed, deferred, expired and physically quarantined. Store aggregate metrics, not viewer text or raw video in public repos.
4. **Failure injection:** stall a vision worker beyond ticket timeout, disable during a GPU call, restart the session, return an old ticket, fail the telemetry poll, induce a game FPS drop and cancel the speaker during phoneme output. A failed stop **must not** free the reservation.
5. **Suggested review gates (owner-configurable, not demonstrated):** zero overlapping unacknowledged vision workers; zero expired success receipts counted; 0 raw private frames/logs published; at least 95% audible completion in opportunities; no more than 2 ms regression in p99 frame duration; no statistically credible drop in matched held-out game success. Apply statistical CIs and independent review before promoting.
6. **Release:** branch → offline unit/regression/smoke → physical device benchmark → local Star Core Forge checkpoint → owner-approved deployment → GitHub publish only if desired. Never push signing keys, personal recordings, private leaderboard cases, chat transcripts or machine credentials.

## 7. Known boundaries and next coding milestones

**Implemented here:** conservative observation admission, quarantined worker stop, a measured-duration sampler, an opt-in hardware bridge and deterministic tests. These are components; they are not a deployed camera/driver, VLM, gameplay controller, new avatar animation library or self-trained intelligence.

**Next highest-value integration:** implement a real Windows host that obtains authenticated game-frame timestamps, captures a permitted viewport, computes cheap CPU-side visual deltas, calls `StreamVisionHost.consider`, runs a local VLM under the returned lease, checks exit status, and passes *only independently scored game events* to the existing action/voice planners. Then compare FPS, latency and held-out task success under a controlled protocol. If host can't kill its worker, leave vision admission blocked and report the fault.

**Security:** As checked on 2026-10-26, the GitHub repo named `Star-AI-Private` was publicly visible. The name does not make the repository private. This change must remain safe for public disclosure; repository exposure should be corrected before any sensitive testing artefacts are ever considered for publication.

## Primary sources and dates

- Roblox, “Roblox Studio is Going Agentic,” **2026-04-15**: https://about.roblox.com/en-nz/newsroom/2026/04/roblox-studio-going-agentic
- Roblox Creator Hub, Studio MCP API: https://create.roblox.com/docs/studio/mcp
- Roblox Creator Hub, Studio Testing Modes: https://create.roblox.com/docs/studio/testing-modes
- Google DeepMind, “SIMA 2: An Agent That Plays, Reasons and Learns With You in Virtual 3D Worlds,” **2025-11-13**: https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/
- Mingyu Ouyang et al., “GameWorld: Towards Standardized and Verifiable Evaluation of Multimodal Game Agents,” **2026-04-08**: https://arxiv.org/abs/2604.07429
- Wei Wu et al., “Code2Games: Enabling Coding Agents for Gaming World Generation,” **2026-10-04**: https://arxiv.org/abs/2610.05033
- “The Latent Bridge: A Continuous Slow-Fast Channel for Real-Time Game Agents,” **2026-06-23**: https://arxiv.org/abs/2606.24470
- LiveKit, Turn-Taking Tuning documentation, verified **2026-10-26**: https://docs.livekit.io/agents/logic/turns/tuning/
- ggml-org llama.cpp, Speculative Decoding, inspected **2026-10-26**: https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md
- Kyutai, “The tiny TTS was actually 10x too big,” **2026-10-20**: https://kyutai.org/blog/2026-10-20-pocket-tts-small/

**Interpretation:** independent research informs a roadmap; it does not by itself validate Star's actual improvement. Only repository tests and real device measurements can do that.
