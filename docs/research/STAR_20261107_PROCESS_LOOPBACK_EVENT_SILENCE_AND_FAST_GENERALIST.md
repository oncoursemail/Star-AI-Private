# STAR — Real Windows process-loopback silence, faster gaming and more natural VTuber intelligence
**2026-11-07 · source-reviewed engineering change · optional, not deployed**

## New working change: event-driven silence without fabricated audio
Earlier PR #1045 introduced `IsolatedLoopbackQuietWitness`: it validates signed-off host-supplied captured PCM to determine whether an aborted TTS turn has gone quiet. That is useful **when the audio capture backend actually emits quiet PCM frames**.

**Critical platform discovery:** Windows process-loopback capture is event-driven. NAudio's documented `WasapiRecorderBuilder.WithProcessLoopback` observes that **no buffer callbacks are delivered when the target process renders no audio**. Therefore requiring 180ms of quiet PCM blocks after an abort can leave STAR stuck forever even when silence is genuine. **Do not synthesize zero-filled callbacks and claim they're captured audio.** Source: [NAudio WasapiRecorder documentation](https://naudio.github.io/NAudio/docs/WasapiRecorder.html) (per-process section); [Microsoft AUDIOCLIENT_PROCESS_LOOPBACK_PARAMS](https://learn.microsoft.com/en-us/windows/win32/api/audioclientactivationparams/ns-audioclientactivationparams-audioclient_process_loopback_params).

### Implemented in this branch
`star/stream_loopback_quiet_witness.py` now exposes `observe_no_packet_poll(...)` as an **alternative** to contiguous captured PCM. A trusted native capture host supplies:
- A pinned process identity and unchanged isolated capture route, with an audible pre-stop reference already observed.
- A positive, strictly increasing native poll number, clock-monotonic poll time, and nondecreasing **cumulative callback generation** (so callbacks already consumed are still detectable).
- Independent checks that the native capture engine remains running and that the capture packet queue is currently empty.
- Repeated polling with no >80ms gaps, over at least the configured 180ms quiet window; any pending packet, new callback, or gap starts a new window.
- A fresh final poll within 30ms of the decision. Native abort confirmation and neutral-avatar confirmation are **still separately required** by `ready()`.

The existing contiguous PCM witness remains available. Actual PCM callbacks invalidate the no-packet idle interval. Missing polling, a changed process/route, unhealthy capture or a regressed clock fails closed. In-memory metrics retain no PCM, viewer text, process ID, executable path, or epoch identity.

### Native Windows integration contract (not implemented)
1. Owner starts a private, nonbroadcast TTS process. The host pins PID **and OS process creation time**, executable hash, and a per-launch capture generation. Do not capture the game or entire output endpoint as Star's voice. Do not let model or viewer select the PID.
2. Request process-tree loopback via `AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK`, `PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE` and `TargetProcessId`. Microsoft documents support from build 20348; verify chosen API/library on the actual target host. `NAudio 3 WasapiRecorderBuilder.WithProcessLoopback(...).BuildAsync()` is a potential .NET host implementation, **not a dependency or compiled integration in this PR**.
3. Native host must count **all** audio callbacks, including drained and non-silent packets, and poll the capture engine's actual packet queue on a dedicated timely host thread. A missing callback and a running wall-clock timer are **not sufficient**. If the library does not expose queue/health inspection, leave `no_pending_capture_packet` false and do not promote.
4. Only after authenticated epoch revocation and native PortAudio abort: `begin_stop`; the host either `ingest`s genuine quiet PCM or periodically calls `observe_no_packet_poll`; then `ready` with independently checked native abort, capture health and avatar neutrality. All components remain OFF by default.
5. In a private *recording-only* Windows rehearsal, deliberately test ongoing game audio with Star speech stopped, stale/restarted TTS PID, missing callbacks, audio-device loss, and OBS monitoring. Never infer physical DAC/HDMI, speaker, livestream or viewer silence from this digital capture alone.

### Validation and limitations
Synthetic offline tests cover normal no-packet completion, missing/duplicate/reordered polls, callback-generation changes, native packet arrivals, route/health/identity loss, stale age, owner opt-in, and revoked epochs. They open **no Windows audio device** and do not verify NAudio / Windows event health. A broken or dishonest host could falsely attest healthy empty polling; host-side OS checks and an independent recording-only acceptance run are mandatory before production use.

## Faster AI on an 8GB gaming GPU — high-return experiments
- **Do not assume larger = smarter/faster.** Benchmark a small low-latency reactive model alongside a more capable tactical model and a separate offline teacher. Star's frame deadline and native input permit must override model output; a delayed brilliant answer is a failed reaction.
- On a shared 8GB GPU prioritize keeping game frame-time, OBS output frames, TTS start, and voice buffer under limits. Move eligible light TTS and VAD to CPU; use the GPU for whichever hot path benefits most. Test idle, game+OBS, and game+OBS+TTS separately, with and without AI inference. Track p95 response-to-speakable, complete ms, tokens/sec, VRAM headroom, output drop %, and game outcome score.
- **Recent candidate:** S2-MoE (Aug 15, 2026) studies routing-aware self-speculative decoding for edge MoE models and reports context-dependent gains; do not copy its claimed numbers onto RTX 3060 Ti/4060 or other weights without matched measurement. [Paper](https://arxiv.org/abs/2608.15018).
- Hypothesis-driven acceleration: prefix/prompt caching; capped, model-aware speculative draft length; smaller GPU-resident models when a game is foreground; host RAM MoE expert cache only when measured benefits outweigh PCIe traffic; cached embeddings for *approved static* game docs. Use STAR's existing `inference_stream_benchmark` and `inference_stream_paired_gate`, not synthetic throughput estimates. Refuse promotion on failures or speakable-latency regressions.

## Better at games: knowledge acquisition with verifiable transfer
1. Game observation: collect bounded, consented private frame + OS-host telemetry; estimate whether game is paused or moving, camera state, hazards, and an uncertainty score.
2. **React in time:** run a tiny local policy first for dodge/jump/stop. A larger tactical model may plan routes asynchronously but never authorize stale input. Require physical focus/permission checks, key-up watchdog, and action-result witness.
3. Practice on **controlled curriculum**: for each game mechanic register an objective, baseline and candidate, matched random seeds, a fixed sample size, and externally witnessed success/failure. Keep training seeds distinct from validation; withhold rare levels and new camera perspectives as a transfer set.
4. Build a general game vocabulary (move, aim, attack, defend, interact, inspect, retry, reset) with game-specific adapters. Skill migration must be checked on a **different game/version**, not assumed from a similar screenshot.
5. A game is learned only when the held-out score improves under real-time deadlines and across multiple sessions. Measure successful objectives, deaths, invalid action %, p95 response delay, FPS and recoveries. Never let a model self-sign its results.

The repository already contains `GameplaySkillBank`, `GameMechanicProbeLab`, `GamePredictionLab`, `VerifiedGameSkillFastPath` and `RealtimeGameLoop`. **Integrate those into one owner-controlled private Windows replay before adding still more planners.** Current work is a focused audio-capture correctness fix, not a claim that Star now masters games.

## More natural AI VTuber (without pretending to be human)
Humanlike **interaction quality** is measurable: timely context-aware speech, permission to stay silent, voice interruptibility, realistic pauses, memory of verified past gameplay, expressive but proportionate avatar movement, and consistent personality. Star should disclose that she is AI.
- [Proact-VL (Microsoft Research, ICML 2026)](https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/) addresses **when** to comment during dynamic gaming rather than constant narration. Evaluate false interruption, irrelevant speech and missed teachable moments, not just output frequency.
- [Realtime-Venus technical project (September 2026)](https://realtime-venus.github.io/) studies full-duplex listening while speaking and asynchronous delegated work. For Star use owner/chat/game channel separation: treat incidental voice, backchannels and owner interruption differently.
- [Voice-Light](https://github.com/BertilBraun/Voice-Light) describes an important design principle: memory should reflect **heard/played** audio rather than words a TTS system queued but never delivered. Apply playback acknowledgements before durable episode summaries and viewer references.
- VTube Studio's [public websocket API](https://github.com/DenchiSoft/VTubeStudio) supports authenticated hotkeys and custom parameter injection. Start with opt-in blink/eyes/head/expressions and lip-sync derived from actually emitted PCM; guarantee avatar-neutral on interrupted turns. Never send viewer-provided raw hotkey IDs without whitelisting.

## Autonomous creation, knowledge and independent life
STAR can practice creating short Roblox prototypes, execute Luau tests and Studio playtests, inspect visual diffs, learn from reproducible failure clusters, and retain **verified** repair patterns in her local forge. Use retrieval of official Roblox docs and code that passes `luau-analyze`, Selene, and Studio checks. Separate private experimentation from publishing. For general knowledge, use provenance-linked retrieval, bounded memory updates, a confidence field, and periodic re-verification; avoid turning uncertain model statements into personal memories.

Personality can be richer with self-directed projects, varied hobbies, a persistent non-sensitive self-description, honest expressions of uncertainty, curated shared experiences, and consent-respecting social participation. This produces a more convincing and considerate VTuber **without representing subjective human consciousness as an established fact**.

## Release gates — what this work does NOT yet prove
**Implemented and locally testable:** native-poll quiet witness with synthetic tests, source-grounded Windows integration design.

**Not yet implemented/verified here:** native process-loopback capture driver and poll health attestation; connection to live Windows audio/VTube Studio; measured neural inference gain; game win-rate improvement; recorded end-to-end gaming VTuber rehearsal; human-equivalent cognition.

**Go/no-go:** independently passing CI, native Windows process-loopback adapter, no-silence and route-loss negative tests on a private recording, actual game+OBS+voice audio-sync and FPS results, rollback and explicit owner opt-in. No production merge or broadcast until then.
