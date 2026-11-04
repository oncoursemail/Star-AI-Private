# STAR AI — clock-independent VTuber output safety and evidence-first intelligence
**Research and implementation note | 2026-11-03 | draft PR after #950**

## Executive finding: an emergency stop cannot depend on the failing sensor

A focused review of PR #950 found a concrete reliability gap in the host-side audio interruption pathway. Star's strictly monitored voice feed already detected absent microphone frames, but its emergency-stop path, watchdog tick, and Stage disable path could depend on a host-provided monotonic clock. If that clock failed (NaN, Infinity, unavailable), output-stop logic could abort before calling the real audio-stop callback. A Python watchdog also depended on callbacks that could throw before the shutdown occurred. This is not merely a theoretical concern for a continuously running VTuber: an error in the observation or timing subsystem should never make the stop pathway fail open.

This patch is a **bounded safety improvement**, not a claim of real hardware muting. It adds:
- A private, epoch-scoped, **clock-independent last-resort stop** in `StreamInterruptionHost`. When a tick or owner emergency stop cannot obtain a valid clock, it revokes its former speech epoch, invokes trusted `stop_epoch` and `flush_animation` callbacks, closes the avatar connection, latches a fault, and refuses to claim a measured stop latency.
- Fail-closed `StarStage.disable()` even if journal/director bookkeeping requires the broken clock. It discards speech as abandoned rather than silently marking speech complete.
- Immediate watchdog revocation on voice observation or tick failures; invalid/replayed VAD is not evidence of silence.
- A strict pyright typing correction in `stream_preplay_fence.py`. GitHub's November 3 CI for PR #950 actually **failed** on `reportArgumentType` in this file even though offline Python and React CI passed; this patch addresses the cited diagnosis without modifying the error baseline.
- Focused simulated adversarial tests for bad clocks, physical-stop failure, replayed VAD, stale epochs, and sensor callback failure.

Important scope: all of these are *trusted-host components*. They do not contact viewers, OBS, VTube Studio or a game. The voice and avatar interfaces remain behind owner authorization, separate from model-generated text and untrusted chat. Output-stop callback returns are **host attestations, not physical guarantees**. A Python daemon is not an OS-process-crash-proof watchdog.

## Safety invariants and proposed Windows proof

1. **No audible turn from unknown microphone state.** Strict mode only starts/rechecks speech using independently acquired, fresh VAD/echo evidence. Capture loss, corrupted timestamps, or invalid frames must revoke the old epoch; silent input must not be inferred from absence of frames.
2. **Stop first, explain later.** The emergency stop should not require successful telemetry, retrieval, token decoding, OBS sampling, clock formatting or a TTS completion callback. Attempt physical PCM stop and animation-queue flush even if the source clock fails.
3. **Epoch isolation.** A late failure from speech epoch A must never neutralize or destroy the replacement epoch B. The fallback only revokes the Stage if A remains current, while it still asks the trusted device to stop A.
4. **Never claim hardware success from a Boolean alone.** Separate `stop_requested`, device callback confirmed, output cursor stopped, loopback/recording silence observed, and avatar-rig neutral. If any witness is missing, mark unknown/fail rather than fabricating success.
5. **Manual recovery after uncertain stop.** No automatic replay of interrupted syllables, no automatic transition to public broadcast, and no guest/chat-triggered tool control.
6. **Windows acceptance drills (still pending).** In a *private, nonbroadcast* game window, inject a stuck clock, terminate the voice sensor, replay a VAD frame, kill the TTS worker, disconnect the avatar bridge, and force a device callback to throw. Independently verify a physical output stop, key-up safety, harmless OBS state, and a manual-only recovery. Use a separate process and device loopback where possible. Simulate OS crash paths separately; an in-process Python fallback cannot handle a total process freeze.

## STAR intelligence architecture: measure skill, not just token speed

**Reactive loop (deadline constrained).** Keep observations and model inference under a true screenshot-to-action deadline. The game must continue running during evaluation. The GameScaling team posted a **November 1, 2026** ViZDoom correction: real-time GameScaling-9B-S3 and 27B-S3 scores became **11.5 and 8.5** versus the earlier **16.4 and 13.2** after a paused-environment protocol and uncounted capture/transfer/preprocessing/action/video overhead were corrected. Therefore, track capture p50/p95, transfer p95, prefill/decode p95, OS action acknowledgment, input release, game FPS and successful objectives in one monotonic trace; never treat tokens/sec as game-playing competence.

**Tactical loop (between reactions).** Maintain an explicit short-term model of mission, available actions, recent failure, scene identity and time budget. A candidate action should be verified against fresh authoritative game state. Prefer smaller and faster control policies to expensive chain-of-thought on each frame; invoke stronger reasoning only when deadline and resource headroom permit.

**Learning loop (between games / off-stream).** Use the existing signed gameplay evidence and skill mastery ladder to propose harder tasks, train a replacement strategy, and evaluate on genuinely distinct holdout episodes. No replayed frames across baseline/candidate groups; partition seeds and maps by purpose; do not promote a skill after one lucky win. Retain reproducible environment version, objective success, failure category, cost and exact behavior change. Use persistent memory only for independently verified outcomes, not invented sensations.

**General knowledge.** Ground factual answers in traceable, timestamped sources and route speculation to labeled hypotheses; keep private and potentially public summaries separate. New material is first stored as an untrusted citation, then vetted and only promoted to reusable knowledge with provenance and expiration. A charismatic voice must not turn guessed facts into confident speech.

## Performance experiments on 8 GB gaming GPUs

The running game, OBS encoder, avatar, voice capture and speech are real-time priority. Do not blindly push a nominally faster 9B quant into limited VRAM if KV cache and rendering lead to memory thrashing. Proposed A/B matrix on the same Windows PC:
- Reactive fast model on CPU vs 4–9B GPU quant, using identical sampled states and latency budget. Measure quality-adjusted objective success at **matched** game FPS and render-lag limits.
- One warm model vs independent short-lived TTS, counting context cache hit rate, prompt reprocessing, VRAM high-water and missed capture-to-action deadlines. Speculative decoding and KV reuse require *reproduction* of a measured quality-neutral speedup before enabling.
- Kyutai Pocket TTS **v4.0.0, released October 20, 2026**, added English 18M, 7M and experimental 2M model variants, including reflection variants. Evaluate actual CPU real-time factor, first audible sample latency, listening preference, and interruption responsiveness against Star's existing voice. Do not equate smaller size with better streaming voice.
- Shed optional GPU image reasoning, art and long research when the OBS render thread, speech cursor, game p95 frame, or available VRAM deteriorate. Keep safety/watchdog callbacks free of model dependencies.

**Hypothesis acceptance:** only ship a route if action success increases or stays level with statistically meaningful p95 latency gains, and the same session demonstrates no increase in render/encode misses or missed physical stops. Report confidence intervals and failures, not only averages.

## More convincing humanlike AI streaming, without pretending to be human

Aim for *behavioral continuity*: short speech anchored to actual events, strategically timed silence, believable surprise only after a witnessed result, occasional recalled preferences, and an evolving but disclosed AI persona. Do not script perpetual chatter or fake gameplay memories. LiveKit's turn-handling guidance distinguishes true barge-ins from brief backchannels and exposes explicit false-interruption controls. STAR must favor owner interruption/physical muting over automatic resume when its host evidence has failed; any future nuanced interruption classifier must not override this safety latch.

Prioritized next features:
1. **Speech delivery ledger**: which text/audio spans were actually played, interrupted or never emitted, with privacy-minimal counters. Only actually heard words should enter conversational continuity; pending TTS is not a spoken memory.
2. **Gameplay impression journal**: a recent verified event, uncertainty, mood *expression* and observed outcome; persist only independently observed events. A happy reaction is authored persona output, not evidence of conscious human experience.
3. **Quiet-time behavior**: gaze, blinks, idle avatar motion and unobtrusive game focus; do not spend GPU on decorative movement while FPS suffers.
4. **Viewer social fairness**: moderation before the model, fixed reply budgets per user/topic, explicit owner override, defer good questions during intense moments, and never expose identities, private paths or unsafe tool access.
5. **Solo creator loop**: read Roblox game layout → propose candidate Luau repairs → static checks → scripted Studio integration tests → visual/physics observations → bounded rollback if regressions. Roblox Studio's `StudioTestService` supports 1–8 simulated clients, including mid-test joins/disconnects. Use private place and per-instance approvals; Studio MCP is not authority to run arbitrary desktop commands.

## Acceptance gates, ownership and source links

Before a public stream: a real Windows audio/OBS/game/device rehearsal; an independent device-state witness; verified game controls and key release; nonbroadcast OBS safety; voice/rig sync measurement; a no-restart-on-stop-failure test; a clearly disclosed AI persona; opt-in moderation/privacy. Keep all experimental features **disabled by default**. Keep proposed code in a **draft GitHub PR**, with no automatic merge to main.

First-party sources (read 2026-11-03):
- GameScaling, Nov 1 correction: https://gamescaling.github.io/
- LiveKit turn handling and false interruptions: https://docs.livekit.io/agents/logic/turns/
- LiveKit adaptive interruption: https://docs.livekit.io/agents/logic/turns/adaptive-interruption-handling/
- Kyutai Pocket TTS releases: https://github.com/kyutai-labs/pocket-tts/releases
- Roblox Studio testing modes: https://create.roblox.com/docs/studio/testing-modes
- Roblox StudioTestService API: https://create.roblox.com/docs/reference/engine/classes/StudioTestService
- OBS v5 WebSocket protocol: https://github.com/obsproject/obs-websocket/blob/master/docs/generated/protocol.md

**Explicit result boundary:** New code repairs failure-handling paths and a CI typing diagnostic. No model was retrained, no inference speed gain measured, no game-winning improvement demonstrated, and no Windows audible or broadcast rehearsal was conducted in this change.
