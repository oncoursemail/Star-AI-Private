# STAR AI: Playback-Clock Telemetry, Runtime Integrity, and Capability Research

**Date:** 2026-11-12  
**Implementation branch:** `feat/voice-playback-clock-and-validation-fix-20261112`  
**Parent:** OBS stream-status work in PR #1150  
**Status:** Draft implementation; full CI and Windows hardware validation pending.

## Executive summary

This change set addresses three concrete runtime/infrastructure problems discovered while reviewing the current STAR development chain:

1. **Holdout mapping bug:** the session-cluster evaluator received calibration *and* holdout group IDs even though it was scoring only holdout spans. Its exact-key contract correctly rejected the extra calibration IDs. The validator now passes the exact holdout-only mapping to both the holdout ledger and cluster evaluator.
2. **Duplicate affect event:** a completed STAR Home activity could finish a related life goal inside `life.after_session`, which already emitted an affect event, and then emit a second generic success event for the same activity. The loop now uses the goal-completion result to avoid counting that one accomplishment twice.
3. **Voice latency was measured at queue submission, not output playback:** `first_audio_at` records when PCM is submitted to the speaker queue. It did not establish when the audio backend began handing that PCM to the output device. A new callback-level playback clock now records the first non-empty PortAudio output callback and active-audio underflows, without claiming to measure physical acoustic arrival.

These are targeted corrections to existing STAR infrastructure. They do not enable new runtime permissions, change default feature flags, store raw audio, or merge anything into production.

---

## 1. Voice playback clock

### Existing measurement gap

STAR already records end-of-turn, ASR, first-token, TTS and first-audio timestamps. The previous `first_audio_at` timestamp is taken immediately before `speaker.play(...)`; that is a **queue-submission** event. It cannot reveal delay between submission and the audio backend's first output callback.

The new `star/voice/playback.py` provides a small thread-safe `PlaybackTelemetry` object and immutable `PlaybackSnapshot`.

### New measurements

- `first_playback_at`: PortAudio's `outputBufferDacTime` for the first non-empty output buffer, mapped to Python monotonic time using the callback's `currentTime`; if time info is missing or implausible, the callback-invocation timestamp is used.
- `output_callbacks_with_audio`: number of output callbacks that actually copied queued audio.
- `output_underflows`: PortAudio output-underflow flags observed on callbacks that also emitted audio.
- `speech_end_to_first_submission`: earliest acknowledgement or TTS submission; the legacy `speech_end_to_audio_submitted` retains its TTS-only meaning.
- `speaker_queue_to_playback`: elapsed time from the earliest acknowledgement/TTS audio submission to the first output callback.
- `speech_end_to_first_playback`: end-of-user-speech to first output callback.
- Existing `total` remains queue-submission based for compatibility.
- `latency_summary` now reports p50, p95 and max for queue submission, first playback callback and queue-to-callback delay, including acknowledgement-only turns.

### Measurement limits

PortAudio documents `outputBufferDacTime` as the estimated time when the first sample of the output buffer will reach the DAC, while `currentTime` is the callback invocation time. STAR maps their difference onto Python's monotonic clock. This is a better backend timing estimate than queue submission or callback invocation alone. It still does **not** prove when a listener physically heard it: Bluetooth transport, downstream device processing, speakers, room acoustics and listener position remain outside this measurement. If the time info is missing, reversed or implausibly far in the future, STAR falls back to callback invocation time.

The file-driven `VirtualSpeaker` reports its scheduled simulated playback start. That is useful for deterministic pipeline tests, but it is not a hardware callback and must not be mixed with physical-device measurements without tagging the backend.

For true client-heard latency, the next stage should add an opt-in Windows WASAPI loopback capture or calibrated external loopback path, with a shared monotonic clock and an explicit device-latency estimate. No raw microphone or speaker audio should be retained by default.

### Callback safety

- No model calls or disk I/O occur in the PortAudio callback.
- The callback records bounded counters and one timestamp only.
- Idle underflow flags are excluded from the active-audio dropout count.
- Snapshot failures are swallowed by the call layer so telemetry cannot break a voice turn.
- Fake and virtual speakers expose the same snapshot contract, while reporting hardware-only counters as unavailable.

---

## 2. Conversational streaming research

Two recent benchmarks reinforce why voice quality must be measured as several independent dimensions instead of a single latency score.

### Full-Duplex-Bench v3

The benchmark uses 100 human-recorded spoken requests across 79 scenarios and 12 speakers, with disfluencies and chained tool calls. It evaluates task/tool accuracy, turn-taking and latency separately.

Source: [Full-Duplex-Bench v3](https://www.full-duplex.ai/benchmarks/fdb-v3) · [paper](https://arxiv.org/abs/2604.04847) · [PortAudio callback time info](https://files.portaudio.com/docs/v19-doxydocs/structPaStreamCallbackTimeInfo.html) · [python-sounddevice callback documentation](https://python-sounddevice.readthedocs.io/en/latest/)

**STAR application:** replay real recorded conversations through the same ASR/turn/brain/TTS/speaker pipeline and separately score:
- interruption precision and recall;
- false barge-ins;
- missed user turns;
- first-token and first-audio-submission latency;
- first output-callback latency;
- complete spoken-task success;
- tool-call correctness and completion.

### InteractionBench

The November 2026 benchmark reports 221 items across 13 scenarios and 1,519 graded runs. It evaluates conversational timing, spoken-task accuracy, whisper/volume control and groundedness separately. Its timing is measured where the client hears the system, so hosted-system network delay is included.

Source: [InteractionBench](https://www.fullduplex.ai/benchmarks/interactionbench) · [arXiv paper](https://arxiv.org/abs/2611.02430)

**STAR application:** add a client-side playback/loopback timing lane and keep task accuracy, conversational floor control, prosody and groundedness as separate scorecards. A fast but incorrect reply must not pass; a correct but awkwardly delayed reply must not pass the streaming-experience gate either.

### Windows audio path

Microsoft's `IAudioClient3` exposes the audio engine's supported shared-mode periods. STAR should query the actual supported periods and choose a stable value rather than forcing the smallest imaginable buffer. Smaller periods can increase callback frequency and CPU pressure.

Source: [IAudioClient3::GetSharedModeEnginePeriod](https://learn.microsoft.com/en-us/windows/win32/api/audioclient/nf-audioclient-iaudioclient3-getsharedmodeengineperiod)

The current implementation still uses the existing PortAudio/sounddevice path. A native WASAPI adapter is a future measured experiment, not part of this patch.


### Avatar Director and expressive VTuber behavior

VTube Studio's official API supports feeding Live2D parameter values, triggering hotkeys and subscribing to events. Live2D Cubism documents audio-driven lip-sync parameters and motion-linked lip-sync.

Sources: [VTube Studio API](https://github.com/DenchiSoft/VTubeStudio) · [Live2D lip-sync manual](https://docs.live2d.com/4.2/en/cubism-sdk-manual/lipsync/)

STAR should use one **Avatar Director** with independent, composable layers rather than letting every subsystem issue conflicting avatar commands:

- **Mouth layer:** driven by the exact PCM blocks being played, using the same playback clock as voice telemetry.
- **Expression layer:** emotion/context chooses a bounded expression target (happy, amused, surprised, confused, focused, concerned, calm); smoothing prevents abrupt jumps.
- **Eye layer:** blink scheduler and gaze/attention target; do not let a gaze update override a blink already in progress.
- **Body/idle layer:** low-amplitude idle motion and breathing, paused or reduced during deliberate gestures.
- **Gesture layer:** authored hotkeys/animations for wave, nod, laugh, point, celebrate and game reactions.
- **State arbitration:** idle → listening → thinking → speaking → reacting/game-focused, with explicit priorities and interruption recovery.

The mouth must follow the audio that is actually being played, not text generation or TTS enqueue time. Expression and gesture timing may be predicted, but the mouth clock must be output-driven. VTube Studio API access and any higher-risk permissions must be explicitly enabled by the owner; do not silently load models/items or request permissions that the current feature does not need.


### Existing STAR VTuber stack

STAR already has a local VTuber camera subsystem in `star/vtuber`: a layered mascot model, `LiveRig`, expression timeline, 20 ms mouth/viseme analysis, a virtual-camera sink, and VMC/OSC output for VRM receivers. The current `LipSyncSpeaker` schedules mouth frames against the speaker's queued-audio estimate. This patch makes the new playback snapshot explicitly pass through that wrapper, so call metrics can observe the underlying audio backend without breaking the existing camera path.

This does **not** replace the existing queue-based lip-sync schedule with a hardware-calibrated schedule. The first callback timestamp is a measurement anchor for a later calibration experiment; per-chunk playback scheduling and client-heard loopback remain separate follow-up work. VTube Studio should be treated as an optional future adapter, not as an already-connected runtime.


For a natural stream, use conversational turn-taking and social context to decide whether a reaction is warranted. Do not fill every silence, manufacture a laugh on every message, or claim real-world experiences the system did not have. The goal is expressive, coherent AI-character performance, not deceiving viewers about being human.

### OBS signal separation

The OBS WebSocket protocol exposes output congestion, bytes sent, skipped frames and total output frames. Keep these separate from render-thread frame loss and from STAR's own audio callback metrics.

Source: [OBS WebSocket protocol](https://github.com/obsproject/obs-websocket/blob/master/docs/generated/protocol.json)


---

## 3. Roblox gameplay and game-creation research

### OpenGameEval

Roblox's OpenGameEval is especially relevant because it runs agents in reproducible, stateful Roblox Studio sessions and checks both edited scenes and simulated play sessions. Its October 2026 paper reports 84 human-curated tasks, 13 frontier models and 16 attempts per task. It separates observation tools from editing tools. Runs that inspected every object touched by the reference solution passed 13.4 percentage points more often on scene-only tasks and 9.8 points more often on script-only tasks than runs that inspected none.

Sources: [OpenGameEval paper](https://arxiv.org/abs/2610.02563) · [official repository](https://github.com/Roblox/open-game-eval)

**STAR Creator application:**
1. Inspect the DataModel and relevant instances before editing.
2. Record which objects/scripts were inspected.
3. Make the smallest targeted edit.
4. Run edit-mode assertions.
5. Start a play session and run runtime checks.
6. Capture output/errors and relevant screenshots.
7. Repair failures, then rerun the checks.
8. Save only a verified artifact.

The official runner requires an owner-provided Roblox Open Cloud API key with the documented evaluation permission. STAR must read it from a secure local secret store, never commit it, never print it, and keep external evaluation opt-in. The official repository also documents rate limits; do not fan out unbounded evaluation jobs.

### GameDevBench

GameDevBench contains 333 Godot game-development tasks across 2D/3D graphics and animation, UI and gameplay logic. Its authors report that visual feedback improved one evaluated GPT-5.4 configuration from 41.1% to 52.0%.

Source: [official GameDevBench repository](https://github.com/waynchi/gamedevbench)

**STAR Creator application:** visual feedback must be part of the development loop. A successful compile is not enough; Star should inspect the rendered scene and exercise the actual interaction.

### CEGame-Bench

CEGame-Bench evaluates long-horizon game creation across Defold, Godot, Roblox Studio, Unity and Unreal. Its October 2026 paper emphasizes the gap between a project that builds and a game that can actually be launched, played through, and resumed from a saved world. The paper reports that only 16% of evaluated agent runs reached the ending, and describes a requirement-driven playtesting skill that improved execution-based scores by 14.1–24.3 points for three evaluated models.

Source: [CEGame-Bench paper](https://arxiv.org/abs/2610.26098)

**STAR Creator acceptance contract:**
- project opens without fatal errors;
- intended game mode starts;
- core loop can be completed with real input;
- win and loss states behave correctly;
- save/load or persistence survives a restart;
- multiplayer behavior is tested when required;
- no missing assets or broken references;
- performance stays within a declared budget;
- test evidence is retained without private player data.

### STAR Gamer: two-speed control

Keep real-time control separate from expensive strategic reasoning:

- **Reactive controller:** movement, aim, dodge, camera, navigation and immediate input.
- **Strategic planner:** objectives, map understanding, tactics, practice curriculum and retrieval of verified skills.

The strategic planner must not block the control loop. Skills should be versioned, scoped to the game/version/input scheme, and promoted only after repeated held-out success. A skill that works in one game must not be assumed to transfer unchanged to another.

---

## 4. Local inference speed and intelligence research

### Prefix/KV reuse

The llama.cpp server documents `cache_prompt`, which reuses a matching prompt prefix so only the changed suffix needs processing. It also exposes optional prompt/generation timing information.

Source: [llama.cpp server documentation](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)

**STAR application:**
- keep stable system/persona/tool prefixes byte-identical;
- append changing user/context data after the stable prefix;
- trim conversation history in larger blocks rather than sliding one message at a time;
- record prompt tokens processed versus prompt tokens reused;
- track cache hit rate and memory pressure;
- verify output quality when changing cache settings.

### Speculative decoding

llama.cpp supports draft-model and n-gram speculative decoding and reports generated/accepted draft statistics.

Source: [llama.cpp speculative decoding](https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md)

Do not enable speculation universally. Acceptance rate, draft overhead, model pair, context length, quantization and backend all affect whether it helps. Benchmark each supported configuration against a no-speculation baseline and keep the feature disabled when it loses.

### UlaCache research

UlaCache (October 21, 2026) explores a unified logical address space across GPU KV pools and optional CPU memory. The paper reports peak decoding-throughput improvements on H200/B300 under its own tested configurations.

Source: [UlaCache paper](https://arxiv.org/abs/2610.29820)

This is a research lead, not a promised speedup for STAR's local hardware. Its large accelerator results must not be projected onto a small desktop GPU. STAR should first profile whether the real bottleneck is prompt prefill, decode bandwidth, KV residency, CPU scheduling, GPU memory, or model loading.

### Recommended benchmark matrix

For each model/build/hardware configuration, record:
- cold model load time;
- warm time-to-first-token;
- prompt tokens/sec;
- decode tokens/sec;
- p50/p95 request latency;
- peak RAM and VRAM;
- KV-cache memory;
- cache hit/reuse ratio;
- speculative draft acceptance and net speedup;
- answer quality on held-out tasks;
- streaming audio latency under concurrent game/OBS load.

Do not trade away correctness or voice responsiveness for a synthetic tokens/sec win.

---

## 5. General knowledge and learning

Keep the six memory roles distinct:
- semantic facts and concepts;
- episodic verified experiences;
- procedural skills;
- current working state;
- temporal facts that can go stale;
- world/environment models.

Every learned fact or skill should retain provenance, timestamp, confidence, scope and a revalidation rule. The retrieval system should prefer verified project knowledge over unverified model-generated recollection. General-knowledge tasks should measure application and transfer, not only recall.

For continuous learning, use a loop of **observe → attempt → receive external feedback → diagnose → practice → verify on held-out tasks → promote skill**. Self-evaluation alone is not sufficient evidence of mastery.

---

## 6. Privacy, security and operational boundaries

- Never commit provider, Roblox Open Cloud, OBS or platform credentials.
- Audio capture and loopback are opt-in and clearly indicated.
- Keep raw audio/video out of telemetry and benchmark summaries by default.
- Store aggregate timings and bounded counters only.
- Do not capture unrelated applications when process-specific capture is sufficient.
- Keep game-control tools inside owner-authorized accounts, processes and sandboxes.
- Require explicit owner approval for public posts, purchases, account changes, destructive operations and other irreversible/external actions.
- Keep new capabilities off by default until their tests, permissions and resource budgets are verified.

---

## 7. Implementation status and next gates

### Implemented in this branch

- Holdout-only group mapping is passed to the cluster evaluator and ledger.
- A regression test asserts exact holdout mapping.
- STAR Home avoids emitting a second generic affect event when the same activity completed a life goal.
- PortAudio callback telemetry records first non-empty output callback, audio-bearing callback count and active-audio underflows.
- Voice turn metrics distinguish queue submission from backend playback callback.
- Latency summaries include acknowledgement-only turns and reject invalid/reversed playback clocks.
- Fake and virtual speaker snapshots allow offline tests without an audio device.

### Not yet implemented or verified

- Physical DAC/Bluetooth/acoustic arrival measurement.
- Windows WASAPI loopback capture.
- Live OBS/VTube Studio connection.
- Live avatar lip-sync driven by the actual output clock.
- RTX/CPU/RAM mixed-load benchmarks.
- OpenGameEval jobs against a real Roblox Studio environment.
- End-to-end game-agent training or skill promotion.
- Full repository CI and Windows packaging on this revision.

### Acceptance gates

1. The previously failing holdout-validation tests pass with exact holdout-only mappings.
2. The STAR Home completion test emits one affect event per completed activity.
3. Playback telemetry tests pass without hardware.
4. Voice-call and file-call tests preserve interruption/history behavior.
5. Pyright and full offline Python suite pass.
6. Windows build succeeds.
7. A real-device rehearsal confirms output callback timestamps and underflow counts.
8. A client-heard loopback experiment is run before making acoustic-latency claims.
9. Benchmark gains are reproduced on the target machine and do not regress held-out answer quality.

**This document is a research and integration plan. It does not claim that the unimplemented adapters or hardware tests are already complete.**
