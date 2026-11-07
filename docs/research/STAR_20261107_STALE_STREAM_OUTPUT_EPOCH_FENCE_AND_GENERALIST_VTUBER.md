# STAR AI: live-output epoch fencing, streaming cognition, and realtime learning
**Research and implementation review — 2026-11-07**
**Change:** `star/stream_output_epoch_fence.py`, `tests/test_stream_output_epoch_fence.py`
**Status:** offline implementation; opt-in, not integrated with the actual Windows PCM/TTS/model process, VTube Studio, game input or OBS. All performance claims require real measurement.

## Executive finding: finish the live stream *feedback loop*, not another decorative assistant

STAR already has separate GPU worker leases, native Windows Job containment, verified model-launch pins, first-speakable benchmark gates, game outcome evidence, context/memory retrieval, audio sample/rig synchronization, OBS rehearsal instruments and now a natural-turn physical stop host. The urgent reliability gap is **asynchronous model/TTS output arriving after an owner interruption or critical game event**. Stopping audio on the physical device is insufficient if stale text, PCM, or animation remains in a producer queue and later re-enters playback.

This change supplies a **trusted-host output epoch fence**. A vetted `prepare` result can bind a short-lived native output epoch. All model-text, TTS-PCM and avatar-motion queue submissions must go through an identity-checked host callback. Before any cancellation callbacks run, STAR invalidates the epoch. Cancellation callbacks are addressed to the original epoch only, invoked at most once, and the old epoch cannot be reused. Starting another turn after an interrupt requires separately observed model-idle, TTS-idle, drained PCM, and neutral avatar. Failed cancellation latches a fault requiring explicit owner recovery; the fence cannot mistake a queued TTS chunk for audible playback. This lowers a specific class of stale-response race, but *is not* a hardware stop, capability security boundary, OS sandbox, cryptographic epoch identity, or proof of human-level conversation.

### Reference architecture

```text
Trusted local host signals (game / mic / viewer moderation / OBS health)
  |                            no direct model/viewer access to host callbacks
  v
StreamDirector + TurnTakingGate -> NaturalTurnBridge -> PhysicalTurnResult
  |                                                        |
  | host reviews "prepare"                                 | stop or fault
  v                                                        v
StreamOutputEpochFence(issue)                     revoke(ticket) immediately
  |                                                         |
  | model_text / tts_pcm / avatar_motion via quick      cancel generation + TTS
  | host queue callbacks (same epoch)                       |
  v                                                         v
Trusted TTS + audio output / VTS worker            NaturalTurnPhysicalHost
  |                                                physical PCM drain / neutral rig
  +----------> report independent idle and drain <----------+
                                      |
                              settle / owner-reviewed rearm
```

**Integration rule:** Disallow all alternative direct producer-to-device queue paths while an epoch is fenced. In addition, when the host receives an authenticated owner interruption, it must call `revoke` *before* it waits for full physical stop. A model text tool or a viewer message is never sufficient evidence of a device stop. The local driver must implement its own hard watchdog on the output thread. `dispatch` holds its lock while calling the local nonblocking queue adapter, so it MUST run on an isolated producer worker, never the audio callback, and that adapter must never block on networks, disks or large TTS synthesis.

### Threat and failure model

1. **Late inference result:** denied because the exact ticket is invalidated before cancellation.
2. **Stale avatar animation:** denied if sent via the same fence; still requires a separate physical animation flush.
3. **Old-model callback after a newer turn starts:** denied by object identity; the serial/epoch string alone never grants permission.
4. **TTS callback races owner barge-in:** serialized at the host queue boundary; once submission has occurred, only the physical PCM stop can guarantee draining. Return values do not prove audibility.
5. **Failed cancel or uncertain native state:** no automatic re-arm; owner-recovery mode requires all four independent quiet observations, and turns auto-disable after settlement.
6. **Unknown chunk types, malformed clocks, backwards time, huge duration, or chunk flooding:** rejected, or the active epoch is revoked.
7. **Privacy:** counts only in metrics; avoid including ticket identities, generated speech, frame contents, viewers, raw PCM, local paths or private note text in logs.
8. **Intent provenance:** the `PhysicalTurnResult` parameter only works as trusted host data. An untrusted caller can fabricate Python objects: never expose this class directly to model tools or viewer WebSockets.

## Research: natural, human-like interaction without misleading the audience

Microsoft's Proact-VL (ICML 2026) frames a real-time gaming companion around *whether and when to speak*, as well as what to say. STAR's priority should be an objective conversation benchmark: first **audible** response latency, owner barge-in stop time, accidental interruptions, game-danger silence, groundedness, max PCM stutter gap and commentator overtalk. The existing `stream_social_turn_benchmark.py` already measures matched A/B moments; retain it instead of inventing another unverified personality score.

NVIDIA's June 2026 DyaPlex research demonstrates streaming full-duplex speech+motion in dyadic interactions. The engineering lesson for STAR is time-aligned audio/rig parameters and the ability to listen while speaking, not the unsupported claim that an 8 GB PC can run DyaPlex. Use the existing `DeviceAudibleSampleHost`, `AudibleAvatarSession` and `VTubeLocalHost` and keep neutral-face fail-safe, blink, breathing and subtle head motion driven by controlled parameters. STAR should have contextual humor, occasional quiet attention, memory of *verified* shared experiences, adaptive emotional **expression**, and the ability to gracefully say she is unsure. Keep public disclosure that STAR is an AI VTuber; functional self-model and persona continuity do not demonstrate consciousness or literal human emotions.

Official interfaces: VTube Studio's plugin WebSocket API uses configurable localhost transport (default 8001) and explicit plugin access approval. OBS's obs-websocket 5.x is included in OBS Studio 28+ (default server port 4455) and should be authenticated. Keep both bound to owner-controlled local transport and read-only OBS status until the private rehearsal is accepted. Never allow this module to start an OBS broadcast.

**Sources**
- Proact-VL (May 2026): https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/
- DyaPlex (June 2026): https://research.nvidia.com/labs/amri/publication/nagano2026dyaplex/
- VTube Studio plugin API: https://github.com/DenchiSoft/VTubeStudio/blob/master/README.md
- OBS WebSocket upstream: https://github.com/obsproject/obs-websocket

## Research: genuine gaming competence under deadline, not just richer game narration

Gym-Anything-RT (published Oct 27, 2026) compares acting in live minigames against paused environments, finding that real-time delay can dominate apparent model ability. STAR's policy should combine:
- **5–30 Hz bounded reaction layer** using symbolic game state or lightweight vision, never a long model call within a game-input or audio callback. This is a *proposed* controller rate, not an observed result on STAR's device.
- **0.5–3 second tactical layer** for choosing objective and play style based on visible mechanics, player state and verified successes. This must not bypass the focused/permissioned local game-input host.
- **Off-stream learning layer** for 10–100 short practice episodes (chosen based on available resources), difficulty ladders and held-out tests with independently checked outcomes. Do not allow validation scenes or private test outcomes into the practice memory. STAR's `VerifiedGameSkillFastPath` (preceding stacked change) can cache host-reviewed hints without SQLite on the realtime game path; it is not a game input driver.
- **Transfer evaluation** across unseen maps, opponents and altered mechanics; report success rate, action delay, missed deadlines, collisions, invalid actions and failure recoveries rather than self-reported mastery.
- **Closed-loop observations**: game frame -> validated state -> allowed action -> receipt of action and *actual* ensuing frame/state. Never confuse a keypress request with a successful move.

Source: Gym-Anything-RT: https://arxiv.org/abs/2610.37567

## Research: game creation and debugging that actually works

Roblox's OpenGameEval (Oct 2026) tests editing and exploration in stateful Studio sessions and scores actual executable checks. STAR should develop feature-complete games by running an explicit loop:
1. Choose one restricted Studio project and measurable feature acceptance criteria.
2. Inspect relevant Roblox objects and API docs before editing. Record a pre-change snapshot.
3. Draft 4–8 candidate Luau implementations offline, lint and typecheck, apply only the best candidate inside a disposable Studio Lab session.
4. Test gameplay and UI visually plus script/test assertions; reject candidates with regressions, performance spikes or visible errors.
5. Use failure evidence to update the local skill database, not hidden validation results; back up and rollback independently.
6. Advance only after reproducible held-out tests and manual review; publishing a Roblox experience remains owner-controlled.

Source: Roblox OpenGameEval https://github.com/Roblox/open-game-eval

## Research: faster useful intelligence on 8 GB VRAM, honestly measured

STAR's previous engineering work established actual RTX 3060 Ti 8 GB monitoring, GPU reservations, Windows Job process-tree containment and pinned worker files, but not an end-to-end model speedup. **Do not estimate tokens/sec from parameter count alone.** Context length, KV-cache type, thermal behavior, other applications and draft-token acceptance all alter results.

**High-return experimental matrix**, only after a stable private rehearsal baseline:
- Compare lightweight fast-path model vs a higher-quality planner using the *same task pairs*, budget, prompt set and hardware-state window; use source-grounded outcome quality and first audible response, not only tokens/sec.
- Test prompt prefix caching, quantized KV cache and GPU-layer budgets with llama.cpp version pinned; every model variant must report prompt processing, decode throughput, first speakable and actual first audible latency.
- Test speculative decoding against normal decoding with matched loads; reject if acceptance or extra VRAM hurts p95 live response.
- Keep speech and OBS protected during GPU scheduling. Voice may eventually use a CPU-local lightweight TTS backend, **only if intelligibility, expressiveness and latency are actually measured** on the target machine.
- Run context retrieval over a curated local knowledge bank; use citation provenance, age metadata and ambiguity checks. Personal viewer chat is not a durable fact; owner approval is needed before storing potentially identifying stream memories.
- Restrict autonomous self-improvement to isolated experiments with tested diffs, rollback and a regression suite; observed increases in pass rates are evidence of system improvement, not proof of model-weight learning.

Useful upstream: llama.cpp https://github.com/ggml-org/llama.cpp

## Acceptance criteria and runbook before a private Windows launch

1. **Offline tests:** verified output epoch tickets reject forged/stale/expired chunks; failure cases independently measured. No direct model/tool invocation can run trusted host callbacks.
2. **Trusted host integration:** all live model/TTS/avatar queues adopt the same fence. Add host-unique epoch IDs and record only sanitized event counts, not generated speech.
3. **Physical confirmation:** a disposable, audibly observable local PCM test must show that a stop physically drains output, flushes VTS parameters and blocks late generated chunks after an owner interruption. Do not treat a callback boolean as independent evidence.
4. **Stress test:** intentionally add slow TTS, half-failed cancellation, reverse clock, reentrant callbacks, accidental viewer noise, OBS high load, and critical gameplay. On uncertain state STAR should remain muted and return to neutral rig, not improvise a recovery.
5. **Paired A/B rehearsal:** offline/nonbroadcast game, local inference, TTS, VTube Studio and OBS *recording only*. Match scenarios, record first audible p50/p95, stop p95, speech overlap, game win rate, missed input deadlines, OBS frame drop %, GPU free memory and recovered faults.
6. **Promotion:** owner-reviewed only, feature disabled by default until all relevant acceptance gates pass, with known rollback. No claim of live streamer readiness or increased intelligence from isolated mock tests.

### Scope verification (must stay honest)

This change improves the *design and test coverage* for stale asynchronous speech outputs. No real hardware integration, real audio stop, VTube Studio parameter flow, active OBS recording, gameplay victory, viewer interaction, model-weight improvement or measured faster inference is demonstrated by its offline tests. Those are next steps, not completed outcomes.
