# STAR — verified OBS load continuity, real-time gaming intelligence and natural VTuber roadmap
**Research checkpoint:** 2026-11-08. **Status:** tested offline code + research; not deployed to Windows/OBS, not a measured speedup.

## 1. Finding and concrete engineering fix

OBS v5 exposes two distinct evidence streams: `GetStats` reports renderer/output frame counters; `GetStreamStatus` reports whether a stream is active/reconnecting and stream transport frame counters. These MUST NOT be replaced with a single lifetime percentage, treated as zero when absent, or combined from different OBS process/connection epochs.

An audit of STAR's existing `ObsStatsWindow` found a genuine counter-continuity flaw: after a trusted valid baseline, a malformed timestamp/counter, lost host authentication, or replayed receipt did **not** destroy the earlier baseline. A later valid snapshot could therefore bridge the unobserved gap and report a healthy interval. That is unsafe when measured stream load influences admission of extra AI/TTS workloads.

**Implemented**:
- `ObsStatsWindow` now clears counter baseline and time watermark after any malformed clock/schema, replayed/non-monotonic clock, or unauthenticated receipt. Existing exceptions for invalid clock/schema remain; rejected non-verified/replayed submissions still return `None`. It demands two fresh valid readings before producing another interval. Rejection metrics expose the invalidation.
- Added `ObsAlignedLiveSampler`, a disabled-until-armed helper for one owner-approved OBS host process/socket epoch. It independently validates OBS renderer and network windows, checks bounded cross-response receipt skew, receipt age, active/non-reconnecting stream, counter continuity, and requires complete genuine frame deltas before emitting a paired `ObsAlignedLiveWindow`.
- A broken source or counter epoch disarms BOTH samplers. It cannot silently reuse its previous ID; a verified host must arm a new process/socket epoch. The paired result expressly cannot authorize a broadcast or game input.
- Offline regression cases cover authentication loss, malformed counters, backward clocks, cross-request skew, stream restart/reconnect, counter reset, idle stream, future-time poison, and successful two-sample recovery. No audio, media, user data, credentials or stream keys are persisted.

This is **evidence quality**, not direct inference acceleration. Better evidence lets future load governors avoid expensive commentary when gaming/OBS is actually constrained.

### Deployment boundary
The sampler itself never connects to OBS, toggles streaming, starts recording, moves a game character, or publishes chat. A trusted Windows adapter must still make actual authenticated OBS WebSocket v5 read-only calls (GetStats and GetStreamStatus), pin OBS PID+creation time and socket identity, provide receipt times from one host monotonic clock, and revoke on host restart/reconnect/disconnect. The `host_verified=True` argument is NOT cryptographic attestation and MUST NOT be populated from a model or chat message. Live-stream telemetry is separate from STAR's already existing *nonbroadcast/private-recording* observation gate. Successful OBS observations cannot authorize going live.

## 2. Streaming AI system: prioritize latency AND game quality

### Three-layer decision loop
1. **Subframe local reflex:** operate only on verified game telemetry/state under a safe allowlist. Short deterministic policies handle urgent movement/avoidance without waiting for language inference. Reject stale frames and refuse cross-game focus changes.
2. **Deadline-aware tactical intelligence:** bounded local vision/VLM + fast model chooses actions for the next 0.2–2 s. Use actual capture-to-act p50/p95 and reaction correctness, not token/s in isolation.
3. **Slow strategic intelligence:** larger model reviews failed mechanics, route planning, viewer questions, match adaptation, programming/creation tasks and episodic memories between urgent moments. Stop or suspend it whenever game/OBS performance is constrained.

Use a bounded FIFO or latest-frame-wins vision queue rather than building up stale model work. Give live game/render/OBS/audio deadlines resource precedence over speculative reasoning. Never shrink resolution without a matched held-out accuracy study: crucial HUD text can disappear.

**Research evidence:** Gym-Anything-RT (published Oct 27, 2026) benchmarks 100 minigames under live versus paused execution and documents a major gap; it is evidence for architecture, not evidence STAR has already mastered a game.

### Hardware-aware inference experiments (RTX 4060 8 GB host)
- Benchmark baseline GPU-only small model, CPU TTS, speculative decoding with measured draft acceptance, and *no* draft with realistic gameplay+OBS overlap. Speculation can slow down or exceed VRAM; never assume a win from a vendor benchmark.
- Compare warm versus cold prompt prefix cache, role-specialized small/large model routing, optional quantizations and smaller vision crops. Record TTFT, prompt prefill, decode token/s, p95 control-loop latency, game FPS/1% lows, OBS render/output/network loss, VRAM peaks, native TTS first-audio and end-of-utterance latency, and accuracy on a fixed challenge set.
- On 8 GB VRAM, preserve an explicit dynamic OBS/game VRAM reserve. Extra GPU workers require fresh host health receipts; on missed telemetry, pause optional work. NVML can provide GPU utilization/memory evidence, but it does not prove real game frame presentation or speech timing.
- A/B experiments should use matched replay episodes and independent holdout games. Only promote a candidate if both throughput and end-to-end task correctness improve without harming game/stream QoS.

**Voice candidate:** Kyutai Pocket TTS published new CPU-oriented English 18.2M/6.9M/1.9M models in October 2026. This is a **benchmark candidate**, not an installed voice swap. Compare voice identity/intonation, natural pauses, first chunk latency, CPU load and game 1% lows to current TTS. Keep stable approved voice data private.

## 3. STAR as a natural, recognizable AI VTuber

*Human-like* should mean believable interaction rather than pretending to be biologically human.

- **When to speak:** proactive commentary only after a meaningful game-state change, achievement, unusual failure, owner request or suitable conversational opening. Explicit cooldowns and silence are positive behaviors. Separate actionable warnings from optional jokes or filler. Proact-VL (ICML 2026) specifically studies this timing/quality/quantity problem.
- **What to say:** bind to *verified current game events* and genuine prior play; never invent achievements, viewer messages or opponents' reactions. Provide brief authentic emotional style (surprise, excitement, playful frustration) without asserting that an LLM has human subjective feelings.
- **How she moves:** synchronize facial visemes to actual audible PCM, not planned text; use look direction, blinks, tail/hair secondary motion, hand and posture reactions with short bounded transitions. On failed audio stop, neutralize animation only after physical audio drain evidence. Honor reduced-motion and stream-safe avatar assets.
- **Conversation:** distinguish owner speech from STAR's own playback (echo cancellation/source separation), implement priority owner barge-in, queue interruption, preserve context of actually spoken words and events, handle moderation and privacy, and avoid unending monologues.
- **Persistent personality:** editable interests, long-term goals, established jokes, trusted game achievements and lessons learned, with source/time/provenance. Maintain clear separation between personality fiction, verified observations, user-provided facts and hypotheses.
- **Social integrity:** disclose she is AI, do not impersonate private individuals, protect viewers and minors, require permission for external messages, channel creation, going live and financial actions. Routine offline experiments can run within the owner's established permissions.

**Evaluation:** owner/independent blinded ratings for groundedness, audio/viseme alignment, interruption behavior, conversational relevance, silence, tone, hallucinated memories, and perceived naturalness. Explicitly measure how often STAR *should stay quiet*.

## 4. Real game-learning system

Use a practice curriculum with a state/action/reward ledger and replayable evidence:
- **Observe:** authorized game process/window, controls, HUD, camera motion, enemies, map edges, score, cooldowns and input delay. Do not assume any particular title's mechanics.
- **Probe:** safe short actions one variable at a time in single-player/testing or permitted multiplayer; fit a mechanics hypothesis with confidence and expected outcome.
- **Train:** deterministic scripted policy for reflexes; episodic planner for strategy; a bounded self-play opponent for games under STAR's control. Retain per-game/version skill metadata and discovered counterexamples.
- **Verify:** fixed benchmark plus hidden new levels/opponents/maps; log effective input-to-result, pass/success/win rates, survival/score, p95 reaction, resource cost, and variance across seeds. Stop if performance falls.
- **Transfer:** re-run on different game mechanics, resolutions, unseen HUD layouts, and controller mappings. Treat transfer success as measured; do not merely recall previously generated strategies.

Never modify online game clients, bypass anti-cheat, automate unauthorized multiplayer activity, or assume permission from a visible window. For complex tests, prefer STAR-created minigames and explicit Roblox Studio testing sessions.

## 5. Autonomous game-building and general knowledge

For Roblox, use the **built-in Studio MCP** (not the retired standalone Rust server). Roblox's Apr 15, 2026 announcement describes plan/build/playtest workflows; the Nov 4, 2026 update added permission-scoped Open Cloud access and asset import. Keep asset uploads, publishing, commerce and external changes separately permissioned.

A practical verified loop: specification → task graph → create Luau/meshes/UI/animations → syntax/style/static checks → Studio test → recorded failing observation → minimal patch → repeat test → independent held-out acceptance. Preserve project checkpoints and revert failed trials in STAR's internal Forge. Store successful tool calls + exact SDK/API version as reusable examples; retrieve relevant docs and working code before generating rather than hoping a giant context window holds everything.

Broaden STAR's independent curriculum to perception, spatial reasoning, planning, audio, video editing, art, debugging, Blender, UI design, narrative, physics and social timing. Knowledge ingestion must retain source, license, freshness and verification status; self-generated claims cannot silently become facts.

## 6. Integration plan and promotion gates (NOT done)

| Priority | Next measurable integration | Release gate |
| --- | --- | --- |
| P0 | Trusted Windows OBS v5 loopback sampler, pinned process/socket epoch and raw read-only receipt times | Different OBS sessions can never be paired; forced reconnect immediately revokes all healthy advice |
| P0 | Combine aligned OBS live windows with independently trusted game frame p95, VRAM and TTS first-audio host receipts | Match within skew and monotonic deadlines; missing metrics cannot become green zero |
| P0 | Private nonbroadcast gaming+OBS+avatar+TTS rehearsal | Independent p95 capture-to-act, first audio, game/OBS frame loss and playback-drain telemetry |
| P1 | Paired GPU/CPU voice and small/big model router A/B | No regression in game FPS, OBS QoS or held-out correctness; declare actual measured speed only after evidence |
| P1 | Safe game-mechanics practice with replay/hidden holdout tests | Positive effect sizes across unseen levels and seeds, repeatable rollback |
| P2 | Grounded spontaneous reactions + emotion/avatar synchronization | Independent evaluation including silence, interruptions, provenance and AI disclosure |
| P2 | Built-in Roblox MCP create/test/repair experiments | Verified playtests, zero unauthorized publication, reproducible success |

No models were downloaded, no Windows host/OBS controls were invoked, no broadcasts launched, and no actual player input was sent in this change. New code is opt-in and remains a draft GitHub branch.

## Primary sources checked (as of 2026-11-08)
- OBS WebSocket v5 protocol: https://github.com/obsproject/obs-websocket/blob/master/docs/generated/protocol.md
- Gym-Anything-RT, **Oct 27 2026**: https://arxiv.org/abs/2610.37567
- Proact-VL, **ICML May 2026**: https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/
- llama.cpp official speculative-decoding guidance: https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md
- Kyutai Pocket TTS Oct 2026 releases: https://github.com/kyutai-labs/pocket-tts/releases
- NVIDIA NVML: https://developer.nvidia.com/management-library-nvml
- Roblox Studio Going Agentic, **Apr 15 2026**: https://about.roblox.com/newsroom/2026/04/roblox-studio-going-agentic
- Roblox Studio MCP permissions/import update, **Nov 4 2026**: https://devforum.roblox.com/t/studio-mcp-server-updates-open-cloud-access-in-your-mcp-client-and-asset-import-workflows/4975849
