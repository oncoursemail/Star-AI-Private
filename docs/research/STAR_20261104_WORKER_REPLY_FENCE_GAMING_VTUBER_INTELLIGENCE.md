# Star AI: real-time worker reply fencing, gaming intelligence and VTuber research

**2026-11-04 — experimental implementation; opt-in, offline-tested, not deployed.**
**Based on draft PR #966 (unmerged).** This work builds on the host-owned model catalog, artifact preflight, worker epoch registry, AdaptiveQoS, and pre-playback advice. No real game, OBS, model process, viewer or microphone session was started in this change.

## Concrete bug and fix

A fast speech worker may have produced a perfectly valid sentence at *request* time, then been restarted or replaced before a result is ready to be played. Old-worker output is no longer necessarily relevant to the current game state or conversation and should not silently reach the audience. Another concurrency bug: a delayed process observation of an **older PID** could previously replace a newer current PID in the registry because replay protection checked the time only for refreshes of the same process. Retirement also discarded the observation watermark, allowing replayed evidence to be reaccepted.

This patch:
- Keeps per-route, monotonic observation watermarks **across process replacements and retirement**, rejecting equal or reordered observations. The cardinality is bounded by verified catalog aliases.
- Adds `HostWorkerEpochRegistry.is_current()` for last-moment checks: epoch object identity, freshness, and monotonic clock. This is not live OS process attestation.
- Introduces `HostWorkerReplyFence`: owner-disabled by default, thread-safe, bounded, no text/audio storage, and no external actions. It binds the current worker epoch to an already-admitted QoS ticket and refuses a reply if the process changes, observation expires, ticket/deadline is invalid, or an output is replayed. It consumes each permit once, including across disable/enable cycles.
- Returns only a *candidate* to the trusted host. Both `authorizes_audio` and `authorizes_broadcast` are explicitly false. In particular, it cannot confer game-control or live-stream permissions.

### Required trusted-host sequence (not yet wired to Windows)

1. Independently verify the worker executable/loaded model configuration and observe PID + OS process creation time; do not accept a process name, model-provided SHA, chat text or viewer input as proof.
2. Validate and bind `InferenceJob` to a current `HostWorkerEpoch`; obtain real `AdaptiveQoS.admit()` and separately enforce CPU/VRAM reservations.
3. Enable `HostWorkerReplyFence` only through authorized host config. Call `arm(epoch, bound_job, admitted_decision, now_ms)` before dispatch.
4. When a worker completes, call `claim(permit, now_ms, host_output_ready)` **immediately before** output enqueue. Check live OS process identity and actual result origin in the worker transport independently.
5. For speech: additionally require `assess_preplay` from fresh host VAD/scene/PCM evidence and actual audio-device acknowledgments. At a restart, physically flush queued old PCM and reset affected avatar motion. Re-check identity during longer streaming output, not only at the first chunk.
6. For vision/game narration: verify the observation is still from the present scene, with an explicit game-state scope and no stale action suggestions. QoS admission does not establish truth of a vision result.

**Limits:** This module is not a signed IPC transport or proof of the model loaded into GPU memory. It does not inspect processes, stop audio, obtain permissions, publish broadcasts, enforce QoS reservations or automatically attach to existing streaming pipelines. Only synthetic offline tests are currently performed.

## Research for a distinctly more natural Star VTuber

**Speak selectively.** The 2026 ICML Proact-VL work evaluates proactive commentary, co-commentary and gaming assistance with attention to timing *and* response volume. Star should add a learned/symbolic “should I speak now?” step ahead of TTS, based on verified event importance, ongoing viewer turns, and voice backlog; the default for uncertain evidence is silence rather than filler. Source: https://proceedings.mlr.press/v306/yan26c.html .

**Conversational timing rather than pretending to be human.** Microsoft's March 2026 RESPOND work examines backchannels and predictive turn claims. Star can emulate natural acknowledgments and short interjections while keeping separate controls for frequency and aggressiveness, and always disclose that she is an AI VTuber. Real laughter or audible responses should match her observed game context, not scripted fabricated emotions or false claims of winning. Source: https://www.microsoft.com/en-us/research/publication/respond-responsive-engagement-strategy-for-predictive-orchestration-and-dialogue/ .

**Voice and motion from audible output.** Benchmark Kyutai Pocket TTS's October 20/21 2026 CPU-oriented small English models using actual first PCM delivery, pronunciation, silence, interruptions and CPU contention. The October 21 release fixed a pronunciation issue affecting small models. Keep GPU graphics headroom for game+avatar. Test current default and `english_18m_2026-10`, `english_7m_2026-10` and experimental `english_2m_2026-10` models without assuming smaller always sounds better. Source: https://github.com/kyutai-labs/pocket-tts/releases .

**Persona with credible continuity.** Maintain private, opt-in episodic memories of verified gameplay, friendships/interactions, preferences and user-approved hobbies; label simulated fiction separately from observed facts. Star should be able to describe what she is currently doing, know when she is uncertain, keep topic continuity, use good humor, and respect silence. Safety/privacy and creator consent remain human-controlled.

## Research for faster, higher-quality intelligence

**Latency in context:** Retain distinct “idle, game, private game+OBS+avatar, live stream” regimes and worker epochs. A model that finishes a text response at 60 tokens/s but delivers speech after a game event is over is slower *for the user* than a smaller model that replies on time. Measure p50/p95 first *audible* speech, p95 screen-to-action, game-frame time, OBS skipped frames, VRAM reservation, number of verified correct actions, and unwanted speaking-over-owner rate. Do not present mocked measurements as hardware benchmarks.

**Inference A/B methodology:** llama.cpp's official SPEED-Bench can measure throughput, latency and speculative draft acceptance for an already-running localhost `llama-server`. Try prompt-prefix caching, 1-slot service, short reactive context and n-gram speculation before adding a second GPU-loaded draft model. Compare both correct-answer rates and end-to-end latency on identical problem sets; test under actual game+OBS load. No claim of acceleration is made by this PR. Source: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md .

**Multi-tier cognition:** Reflex planner for input deadlines; tactical agent for short-horizon goals and recovery; slower coding/research agent for offline project work, retrieval, simulation, and practice. Resource-aware scheduling must preempt background work during gameplay and opt into GPU model admissions only with guaranteed headroom. A consistent, calibrated small model plus grounded tools can outperform an unverified long response on interactive tasks.

**General knowledge:** Versioned, source-grounded retrieval with explicit timestamps; contradiction tests; citation verification; context summarization with important constraints preserved; problem-specific small best-of-N proposals selected only after executable tests and independent visual verification. No learning from unverified model-written "success" claims.

## Game-playing, game-making, and autonomy

- **Learn to play:** collect legal, private/local game traces (frame timestamps, actual action acknowledgments and environment-confirmed outcomes), construct safe practice curricula for navigation, hazards, timing, aiming and coordination, use unseen maps/seeds for holdout evaluation, and keep a hard cap on active requests. Do not automate competitive online gameplay where disallowed.
- **Learn to build:** use Roblox Studio's authorized MCP integration and local sandbox to inspect existing assets, generate multiple Luau implementations, run lint, functional tests, visual inspections and controlled Studio multiplayer playtests. Compare before/after behavior, keep undo/rollback, never publish an owner's game without explicit approval.
- **Have interests:** hobby projects, drawing, strategic game practice, friendly co-op, solo narration and creator assets can all be scheduled around owner budget/resource gates. This is functional autonomy and social expressiveness, not proof of consciousness or literal human identity.
- **Operational resilience:** recover from app restart with a clean worker epoch, stable memory snapshot and rebuilt QoS statistics; never replay an old permit into the next stream, leak a private chat excerpt, or run a silent broadcast.

## Acceptance criteria for the next real-host integration

1. A trusted Windows worker supervisor observes executable identity, process birth, actual model bindings and output IPC, not only user-supplied metadata.
2. Private local OBS recording with game+avatar+TTS for at least two cold starts and one forced worker restart; no network broadcast.
3. A stale speech reply generated before restart must not be heard afterward; queued PCM and avatar motion are physically flushed. A current speech reply must still pass a fresh turn-taking and preplay witness.
4. Measure true end-to-end and audible latency, CPU utilization, GPU memory, p95 FPS, OBS frame skips, completion rate, utterance appropriateness and verified game progress. No fabricated metrics.
5. Fail closed on clock regression, old PID callbacks, unbound workers, missing PCM evidence, duplicate replies, stale scene captures or owner interruption.
6. Keep opt-in off by default; preserve user privacy; publish changes only through reviewable PR and independent CI before any merge.

**Status:** Code, tests and research added. No neural weights trained, no independent evidence that Star became faster/smarter in real gameplay, no natural voice quality claims, and no live VTuber rehearsal completed.
