# STAR AI — Native PCM epoch handoff, real-time learning and natural gaming VTuber roadmap
**Research date:** 2026-11-07. **Status:** source implementation and offline tests; **not** installed in the Windows runtime. Success here is not a speed benchmark, gameplay win, audio-audibility verification or completed private stream.

## Engineering contribution: the missing application-PCM handoff

The preceding stacked changes already introduced NaturalTurnBridge (speech timing), NaturalTurnPhysicalHost (verified stop requirements), StreamOutputEpochFence (invalidate generation after interruption), and StreamOutputConsumerQueue (second check before delivery). The missing native integration was a narrow adapter for **the existing** `star.voice.devices.SoundSpeaker`, not another model or frontend.

`star/stream_epoch_pcm_sink.py` adds `LocalEpochPCMSink`:

- Owner opt-in required. The speaker must already be opened on a trusted local control worker; this module opens **no audio device**, microphone, game, OBS or network.
- A bounded, never-reused native playback epoch is attached to the output consumer's `tts_pcm` route. Only immutable, mono little-endian PCM16 chunks at the speaker's **actual sample rate** can be queued. Byte size, sample alignment and native app-buffer age are constrained before submit; the existing SoundSpeaker does not need to resample.
- Every write and stop is serialized. The local stop invalidates its native epoch **before** clearing application PCM. A playback exception faults and latches the epoch rather than pretending audio has stopped. Duplicate stop *requests* from the output fence and physical stop controller are idempotent for the same epoch, but never imply driver silence.
- A new epoch is refused until the host separately attests that the native output path has been flushed/quiet and the application queue is empty. Reused IDs never become valid within the same adapter lifetime. False native callbacks, stale epochs, buffer pressure and unconfirmed quiet fail closed.
- Metrics contain only counters and flags. No transcripts, PCM buffers, viewer details or raw device IDs are exported.

**Critical limitation:** `SoundSpeaker.stop()` clears its Python buffer, not necessarily frames already handed by PortAudio to an OS/driver buffer. Even `played_seconds()` counts callback handoff frames, **not actual human-audible sound**. `native_output_flushed=True` is a trusted external host assertion, not internally verified silence. A production Windows host needs WASAPI/PortAudio stop-abort or explicit playout callback evidence plus a liveness watchdog, then an independent audio/rig check before new speech. Merely binding this adapter is not sufficient to certify streaming quality.

### Wiring sketch for a future owner-approved, nonbroadcast Windows pilot

The host (never an LLM, viewer or plugin) owns one `SoundSpeaker` instance and `LocalEpochPCMSink`. With a verified private host sound path, it opts in, binds a fresh native epoch, and routes `StreamOutputConsumerQueue.consume_one(..., submit=route)` into the sink **only** for `tts_pcm`. `model_text` and `avatar_motion` require their own separate, trusted destinations. When a higher-priority owner interruption or critical game event occurs: revoke the output fence, call native sink stop (or a trusted epoch-specific cancel hook), stop/drain actual audio, neutralize VTube Studio, reject all previously queued chunks, and require native quiet before a new epoch. No OBS start-stream command belongs in this path.

The new test suite uses a fake speaker to cover validation, stale epochs, application backpressure, exceptions, stop/flush barriers, races, and an end-to-end two-stage queue-to-speaker-interface interruption. It does **not** play PCM through a physical device.

## High-value research findings

### 1. Game intelligence is constrained by time, not just reasoning depth

**Gym-Anything-RT (2026-10-27)** constructed 100 real-time minigames and compared them with paused environments. Its authors report a large gap between pass rates in real time and when games pause during reasoning. The implication for Star: an expensive large model should not decide every 60 Hz keypress. **ROAR (2026-10-16)** studies asynchronous agents in shooter scenarios where the environment never pauses. Design Star's gameplay with a local 30–60 Hz control path (simple reflexes/short horizon), periodic perception (adaptive sampling when changes happen), and a slower 0.5–5 Hz strategic planner that can miss a turn without freezing the world. Use action deadlines and authenticated foreground-game identity, never unrestricted viewer-directed game input.

Train the fast path with safe, offline minigames: randomized obstacle motion, resource collection, timing games, cooperative goals and adversarial objectives. Each trial must independently measure observations, action-deadline misses, success, damage and game-frame stability. Compare paused versus live simulations and previously unseen seeds. Prevent self-reported reward, training/holdout leakage and unverified game-state assertions. Inspect existing `game_live_clock_benchmark.py`, `game_verified_fast_path.py`, `game_contended_skill_lab.py` before adding another overlapping learner.

Sources: https://arxiv.org/abs/2610.37567 ; https://arxiv.org/abs/2610.24282

### 2. Spending compute on reasoning only when useful

On 8 GiB consumer NVIDIA hardware, **test** small local models, KV/prompt caching and bounded, short fast-path prompts while games render. Treat any statement that a model "fits" at a given context length as an experiment rather than an immutable hardware fact: VRAM depends on model quantization, GPU use by game/OBS/avatar, KV cache and batching. Route deep Rust/Luau debugging and long research to another machine or owner-approved remote model only when the local path has insufficient confidence. Keep synchronized stream and game loops responsive: avoid synchronous retrieval, database validation or heavyweight vision in the audio callback.

llama.cpp's SPEED-Bench supports paired ordinary/speculative inference comparisons. Track **time to first speakable response**, request p95, end-to-end action deadline, quality/error rate and GPU contention in addition to tokens/sec and draft acceptance. Use held-out prompts and identical model/context settings. A config is only a candidate if measured spoken-response and game results improve without regressions.

Source: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md

### 3. Natural VTuber behavior needs timing and continuity

Star should know **when silence is appropriate**, distinguish an authenticated owner interruption from chatter/noise, allow complete interruptions, avoid narrating stale screen events, maintain verified memory of her own game attempts, and express consistent interests/humor. Make speech, mouth and gesture clocks derive from the same observed playback epochs, not estimated TTS length. NVIDIA's **DyaPlex (June 2026)** explores streaming full-duplex speech-motion; Microsoft's **Proact-VL** explores proactive timing for gaming companions. These are research directions, **not** proof that a frozen base model can be made human-equivalent.

Prioritize low-latency acknowledgments, turn-taking, contextual pauses, variable expression intensity, motion easing, avatar idle behavior and believable reaction timing over artificially frequent commentary. Be transparent that Star is an AI, protect chat/voice privacy, and make microphone/voice cloning explicitly consent-based. A persistent persona and self-model improve behavioral continuity, but do not establish subjective feelings or consciousness.

Sources: https://research.nvidia.com/labs/amri/publication/nagano2026dyaplex/ ; https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/

### 4. Keep TTS off the game GPU when real measurements support it

Kyutai's **Pocket TTS** offers CPU-oriented streamed speech. Its October 2026 small English models (18.2M, 6.9M, 1.9M parameters) are reasonable *candidates* for a fast reflex-voice mode, not guaranteed to match the expressive quality of a larger voice. Compare on Star's real CPU: first chunk p50/p95, interruption/flush time, pronunciation, consistency, emotional expressiveness, real-time factor, CPU load during gameplay, and owner-approved voice identity. Record no private user audio in benchmark artifacts.

Source: https://github.com/kyutai-labs/pocket-tts

### 5. Autonomous Roblox game development must be verifiable

**OpenGameEval (2026)** evaluates agents on stateful Roblox Studio tasks, including executable checks of scene edits and play simulation. Add a comparable repeatable workflow: plan feature and test -> inspect existing scene/objects -> implement Luau + Rojo code -> run static checks -> start permitted Studio lab -> verify behavior in play -> inspect screenshots/performance -> repair only failed cases -> archive generalized lessons with source/evaluation provenance. Support Blender/VFX, sound, animation and UI design via the same independent artifacts and visible-output checks. Keep Open Cloud credentials only on trusted hosts and allow asset publishing/public game changes behind explicit release gates.

Source: https://github.com/Roblox/open-game-eval

### 6. Infrastructure and streaming boundaries

VTube Studio offers a local authenticated WebSocket plugin API and parameter injection. OBS WebSocket is available in OBS 28+ and supports recording and streaming commands; keep streaming disabled during private rehearsals and distinguish *recording* from *broadcasting*. Authentication is mandatory. Default new adapters to OFF; native device/session IDs must be trusted host-owned, inaccessible to viewer messages and LLM-produced text. Continue backup/rollback and consent gates for irreversible changes. Prefer failing closed on stale observations, GPU overload, process-tree uncertainty, disconnection or unmatched stream epochs.

Sources: https://github.com/DenchiSoft/VTubeStudio/blob/master/README.md ; https://github.com/obsproject/obs-websocket

## Read-only host snapshot (2026-11-07)

On the connected Windows **Main** computer, a read-only NVIDIA query returned an **RTX 3060 Ti, 8192 MiB VRAM, 6017 MiB currently free, 17% GPU utilization**. OBS, VTube Studio and Roblox game processes were not present in the checked names at that moment. This is a transient snapshot, **not** evidence that a game+OBS+VTube Studio+local model rehearsal will fit, and does not verify the planned RTX 4060 system.

## Prioritized acceptance gates

| Milestone | Testable acceptance criteria | Current status |
|---|---|---|
| Native PCM handoff | PCM16 + epoch checks, queue capacity, cancellation, stale-output races; no device/broadcast | **Implemented/tested with a fake speaker** |
| Independent Windows audio stop | stop/abort backend, check driver-native quiet, final avatar neutral, 0 audible stale chunks after interruption | **Unverified / production integration required** |
| Nonbroadcast rehearsal | Game + inference + speech + VTS + OBS *recording only*; p95 first speakable response, interruption time, frame p99, GPU free minimum | **Not run** |
| Gaming progress | Paired held-out *real-time* game scenarios with autonomous scoring and lower missed-deadline rate | **Not demonstrated by this change** |
| Coding quality | Roblox Studio executable tests on unseen development tasks; Luau/Rust error and repair rates | **Needs benchmark cohort** |
| Persona naturalness | Owner-reviewed privacy-safe recordings, validated memory consistency, interruption quality, silence rate and expressiveness | **Needs human evaluation** |
| Model acceleration | Baseline versus candidate under matched GPU game/OBS load; no quality regression | **Not measured** |

A successful offline Python test only proves those Python invariants. Do not auto-deploy, auto-publish assets, change credentials, start broadcasts, or claim Star is indistinguishable from a human. The next meaningful test should be a **private, explicitly owner-approved Windows audio/rig and game rehearsal**, not another disconnected orchestration layer.
