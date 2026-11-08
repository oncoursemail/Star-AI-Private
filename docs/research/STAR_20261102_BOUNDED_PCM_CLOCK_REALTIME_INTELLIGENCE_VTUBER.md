# STAR research: bounded audible playback, realtime intelligence, gaming, and natural VTuber operation
**Date:** 2026-11-02 UTC. **Scope:** Tested offline Python audio-clock correction plus evidence-based architecture and Windows rehearsal plan.
**Status:** Audio-clock correction implemented on this draft branch; everything else below is research or a proposed experiment, **not** a deployed feature or demonstrated speed/model-quality improvement.

## 1. Reproduced defect: repeated callbacks could invent heard audio time

The local `StarPlayoutClock.observe_playhead()` used this check for every device observation:

`position_delta <= max_playback_rate * elapsed_since_previous_callback + 0.080s`

Because the full 80-ms tolerance was **regranted every callback**, three successive cursor reports at the *same* monotonic timestamp (0.00s, 0.07s, 0.14s) all passed even though only the first 80ms of extra position should ever have been tolerated. A faulty device callback could therefore cause STAR's avatar mouth to animate far ahead of the actual output-device timeline. The same scenario propagated through `DeviceAudibleSampleHost` and consumed-PCM avatar synchronization.

Before the fix, two new tests failed at the expected assertions while a positive playback test passed.

**Implemented:** Replace per-call headroom with a shared, replenishable 80-ms tolerance budget. At each monotonic sample:

- `available = max_playback_rate * elapsed + remaining_slack`;
- if `position_delta > available + floating_point_epsilon`, reject and revoke the current rig lease;
- otherwise `remaining_slack = min(80ms, max(0, available - max(0, position_delta)))`.

The budget is initialized and cleared with each speech track. True clock progression replenishes tolerance, but duplicate timestamps do not. Repeated identical timestamps with a total 140ms advance now fail; normal 50ms progression and 70ms of initial jitter remain permitted. The host retains independent responsibility for attesting actual consumed samples, audio-device stop/flush, and final output neutralization.

**Scope of change:** `star/stream_playout_clock.py`, `tests/test_stream_playout_clock.py`, `tests/test_stream_audio_sample_host.py`. No TTS model, OBS, gameplay input, hardware, audio samples, viewer messages, or broadcast actions are touched.

### Windows integration: hardware clock, not guessed cursor

For the *future* trusted Windows backend, prefer the WASAPI stream/device clock (`IAudioClock::GetPosition` + `GetFrequency`, with its correlated QPC timestamp) when appropriate; `IAudioClock2::GetDevicePosition` reports a hardware position in shared mode. Convert units and align to the application's output epoch. Do not substitute the count of samples queued by the TTS engine for samples consumed by the playback path. `IAudioClient::GetCurrentPadding` measures **endpoint-buffer padding**, not a standalone proof of audio heard. Confirm how the selected shared/exclusive mode and device driver expose time before using any of these readings. Handle device loss, stream stop, resampling, paused cursors, and recreation as new epochs.

A driver callback, websocket payload, local model, or microphone transcript cannot authenticate itself. The trusted host must still validate the device identity and scene/speech lease at the final boundary. On malformed clocks or implausible jumps, stop expressive motion and send a neutral pose; do **not** assume that invalidation stopped the physical audio device.

Sources:
- Microsoft `IAudioClock`: https://learn.microsoft.com/en-us/windows/win32/api/audioclient/nn-audioclient-iaudioclock
- Microsoft `IAudioClock2::GetDevicePosition`: https://learn.microsoft.com/en-us/windows/win32/api/audioclient/nf-audioclient-iaudioclock2-getdeviceposition
- Microsoft `IAudioClient::GetCurrentPadding`: https://learn.microsoft.com/en-us/windows/win32/api/audioclient/nf-audioclient-iaudioclient-getcurrentpadding

## 2. Intelligence architecture: three cooperating time scales

**A. Fast live actor (critical path):** one small, tested local model handles immediate on-screen observations, limited tactical decisions, short audience replies and event-aware reactions. Reserve explicit deadlines from capture through inference to *actual* key dispatch or audible playback. Reject stale game frames and superseded voice turns. Keep key ownership, game focus, OBS telemetry, and permissions independently host-verified. A fast answer that arrives after the scene deadline is not an improvement.

**B. Deliberative teacher (between attempts):** a stronger model reconstructs a failed game sequence, proposes a *small* revised policy, and generates a short instruction/skill. The student is then evaluated again on unseen levels or seeds; only statistically credible improvement is promoted. Teacher calls never block live input. RealtimeBench (Oct 14, 2026) reports 180 live-clock game tasks across six game types and a two-timescale training approach; it measured an average student progress-score increase from 13.51 to 24.19 after two rounds. Those are the authors' results, **not** STAR's.
Source: https://arxiv.org/abs/2610.20665

**C. Autonomous software builder (offline):** run bounded generate-and-verify candidates for game scripts, UI, lighting, animation, plugins and backend services. Each candidate gets syntax and type checks, unit/property tests, in-engine replay, collision/placement audits, screenshot comparison and independent reviewer checks. Archive negative cases. Promote only after passing held-out tests and preserving functionality. Require human review for irreversible, external, spending or publicly published actions.

Keep *knowledge* separate from *model weights*: verified documentation, version-scoped game mechanics, trace-backed personal experiences, and uncertain hypotheses should have provenance, freshness, permission, and revocation fields. RAG retrieval must filter privacy and game scene first, then rank. Remembering an instruction is not the same as improving model parameters; a true fine-tuning claim requires reproducible held-out evaluation.

## 3. 8 GB VRAM: measure total system speed rather than peak decode tokens

On a shared 8 GB GPU, gaming, OBS encoding, VTube Studio rendering, ASR/vision and text inference compete for VRAM and memory bandwidth. The high-priority metric is **end-to-end response latency and game stability**, not tokens/s alone.

Proposed opt-in A/B matrix (keep old configuration available for rollback):
1. Baseline local model with recorded prompt/cache reuse and fixed skill/test corpus.
2. Same model with prompt/KV reuse; compare first-token delay, correctness and cache hit rates.
3. Same model with llama.cpp speculative decoding (`draft` or `ngram-cache` if supported in the pinned build); compare acceptance rate, first token, total response and added RAM/VRAM. It may be *slower* when acceptance is low.
4. Resource-aware dispatch: FPS/encoder lag/GPU peaks trigger smaller context, reduced parallelism or postponement of teacher work. Keep owner-requested web/tool switches off by default.
5. CPU-based speech candidates against the current TTS baseline. Kyutai's Pocket TTS has October 2026 small English models (18.2M / 6.9M / 1.9M parameters), but published speed/quality claims are not STAR Windows measurements.

Use at least 20 pre-registered paired game/voice trials per comparison; record p50/p95 first audible PCM, p95 and max A/V offset from **independent OBS recordings**, gameplay frametime tails/hitches, peak VRAM, answer correctness and groundedness. Match game/version/scene, time windows and system loads; protect against first-run cache bias. Do not promote if game smoothness, audible capture, truthful replies, or event accuracy regress.

Sources:
- llama.cpp server: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md
- llama.cpp speculation: https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md
- Kyutai Pocket TTS: https://github.com/kyutai-labs/pocket-tts

## 4. Live game mastery and creation: observable competence, not role-play

**Game player:** Start with bounded offline/tutorial or explicitly authorized games. Define an action vocabulary; verify focus before input and release keys after each permit. Record telemetry-only outcomes (checkpoint, score, damage, elapsed time, attempt/seed), not secrets or viewer identity. Generate a curriculum of mechanics (camera, navigation, timed actions, crafting, teamwork) and quantify learning as win rate or normalized progress on unseen tasks. Separate training episodes from held-out evaluation seeds, with opt-out and instant stop.

**Game creator:** The Oct 1, 2026 OpenGameEval paper describes 84 human-curated Roblox Studio tasks and executable edit-time/play-time checks. Its best reported single-attempt score was 51.7%, and inspecting all relevant objects before editing correlated with stronger results. Borrow the pattern: inspect hierarchy/materials/constraints/scripts first; then make small edits and rerun multiplayer, physics, UI and collision checks. Do not label a generated scene finished until visual QA and playtesting pass.
Sources: https://arxiv.org/abs/2610.02563 and https://github.com/Roblox/open-game-eval

Roblox's current testing documentation describes `StudioTestService` up to eight simulated clients, `UserInputService:CreateVirtualInput()`, network simulation, device emulation and UI automation. Integrate these as owner-controlled Studio Lab tests, not as unrestricted player input in online games.
Source: https://create.roblox.com/docs/studio/testing-modes

Suggested first complete game-creation demonstration: build a two-player checkpoint obby from an empty permitted Roblox place; verify server-client state, UI scaling, reachable platforms, spawn consistency, avatar grip/animations, collision-free props, FPS and an actual simulated player completion. Compare first attempt versus repaired version and keep full diffs and replay evidence.

## 5. Humanlike VTuber operation without manufactured experiences

A believable STAR persona is a consistent animated character with a voice, values, preferences, persistent but **grounded** memories, game-specific goals, a schedule and social context. Avoid claiming biological sensations, private experiences, real emotions as facts, or human identity. Viewer trust and stream safety are part of quality.

**Timing:** End-of-turn detection needs both pause tolerance and quick final response. LiveKit's published English evaluation reports 4.5% false cutoffs at a 600ms latency setting for its v1 detector, and 543ms endpointing delay at a 5% false-cutoff operating point. These are third-party benchmark measurements; test STAR's actual mic/echo cancellation/host before enabling. Maintain authenticated owner override, hold on uncertain VAD or missing observations, and do not let a viewer spoof owner identity.
Sources: https://livekit.com/blog/solving-end-of-turn-detection and https://github.com/dlange-aai/livekit-eot-bench

**Expression:** Drive VTube Studio's custom parameters through a locally authenticated plugin host; match lip movement to *consumed* audio position, not synthesized text offsets. Use subtle eye shifts and smiles only with plausible verified causes, allow natural silence, and queue/cancel motions by scene and speech epoch. VTube Studio's plugin docs describe custom parameter injection, authentication and revocation.
Source: https://github.com/DenchiSoft/VTubeStudio/wiki/Plugins

**Continuity:** Keep game accomplishments, episodic memories and chat interactions scoped to the correct game/version/scene, with time and provenance. Astro and Amber interactions can be authored playful character behavior but must never override a real viewer, game safety or event correctness. During OBS microphone-device changes or game switches, revoke old speech/avatar epochs and reestablish a clean witness before speaking.

## 6. Acceptance gates: still unverified on real Windows devices

1. **Offline tests:** adversarial many-callback same-timestamp progression is rejected; legitimate timestamp progression is accepted; bad cursor revokes motion; old epoch cannot disturb the new one; new token-budget starts clean after reset.
2. **Device bench:** feed actual WASAPI device-clock observations through the host; test clock precision, callback burst, delayed callback, pause/resume, device unplug, sample-rate switch and output route switch. Compare against a separate loopback measurement.
3. **Nonbroadcast game+voice rig:** game process, inference server, VTube Studio and OBS must be distinct identities; report GPU VRAM at start and every interval. Verify actual OBS playback against the audio track and mouth shape, including neutralization on interrupt.
4. **Gaming teacher loop:** run paired repeated-seed and held-out-seed progress evaluations; promote no strategy solely on one good demonstration. Track failure categories, incorrect game state and action misses.
5. **Ship gate:** CI green, source tree equals tested commit, owner opt-in, manual Windows hardware rehearsal and clear rollback. Stay draft until these pass.

This patch corrects **a proven playback-clock accounting problem**. It does **not** increase LLM tokens/s, train STAR, create a Windows audio backend, prove that sound was heard by a viewer, demonstrate new game wins, or authorize live broadcasts.
