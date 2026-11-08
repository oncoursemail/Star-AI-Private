# STAR — GPU identity continuity, real-time game intelligence, and natural VTuber rehearsal
**Engineering review: November 1, 2026**
**Status:** offline-tested patch; experimental, OFF-by-default; no public broadcast, model change, game input, or GPU reconfiguration.

## Reproduced failure: an index is not a GPU identity

Previous `stream_windows_resource_window.py` correctly rejected low VRAM, high utilization, missing samples, GPU capacity changes, and unstable process witnesses. Its remaining continuity test compared *reported total VRAM* across samples. Two NVIDIA adapters can both report 8,192 MiB, and a dynamically assigned index such as GPU 0 is not a hardware identity. A device/index swap could therefore produce a false `candidate` when memory/utilization counters coincidentally matched.

The original regression tests were run before implementation and failed because the GPU identity was not observed, stored, or pinned. The fix makes the bounded `nvidia-smi` query retrieve the NVIDIA UUID **in the same subprocess invocation as the memory and utilization counters**. This prevents a separate identity/counter query from identifying a different device between calls. `GpuHeadroom` now holds an optional, format-validated, **repr-hidden** device UUID to preserve backward compatibility with the one-shot advisory. The five-sample window **requires UUID evidence for every GPU sample** before giving a positive candidate recommendation.

Within one window, a missing UUID, device mismatch, or device swap is a reason to defer even when all counters are otherwise ideal. The caller can optionally provide `expected_gpu_uuid` derived from a separately authenticated local host-pinning decision; a mismatch fails closed. The report emits **reason codes, never a device UUID**, process list, media, prompt or session identifier.

NVIDIA documents `nvmlDeviceGetUUID` as a stable identifier for the given physical GPU; NVIDIA also cautions that memory accounting, especially under Windows WDDM, depends on operating-system management. Treat the UUID as *device continuity evidence*, **not cryptographic proof of trusted measurement**. It is not a guarantee that gaming will fit or remain smooth.

Sources: [NVIDIA NVML device UUID](https://docs.nvidia.com/deploy/nvml-api/latest/api/group__nvmlDeviceQueries.html), [NVIDIA device memory accounting](https://nvidia.github.io/cuda-python/cuda-bindings/13.4.4/module/generated/cuda.bindings.nvml.device_get_memory_info_v2.html).

### Windows evidence (read-only, November 1, 2026)

A fresh `nvidia-smi` query on authorized PC **Main** returned **one GPU**, and its hardware UUID matched the strict UUID format that this patch accepts (identifier deliberately not recorded here). A momentary observation returned **8,192 MiB total VRAM**, **364 MiB free**, **3% GPU utilization**. These figures are not an FPS measurement or an inference-speed benchmark. They reinforce the earlier concern that this machine needs **a smaller live model, CPU offload, or split-computer scheduling before a heavy model, modern game, avatar and OBS are assumed to fit simultaneously**. No running model was stopped or reconfigured.

## Implementation and regression evidence

Files changed:
- `star/stream_windows_rehearsal_preflight.py`: bounded GPU UUID + counters retrieved together; strict parse; in-memory hidden UUID; original one-shot API preserved.
- `star/stream_windows_resource_window.py`: require uninterrupted GPU UUID continuity; support optional host-pinned expected UUID; fail with static sanitized reason codes.
- `tests/test_stream_gpu_device_identity.py`: new tests for identical-capacity GPU swaps, missing identity, host pin mismatch, case-folding, bounded subprocess query, malformed values, and validation before any host read.
- Adjacent existing GPU preflight and resource-window tests adjusted to supply explicit fake identity evidence.

The new tests first reproduced the absence of GPU identity checking. The implementation was corrected and checked with offline mocks only; **no gameplay, OBS, avatar renderer, neural speech, Windows module deployment or model training occurred**.

### Next readiness gates

| Gate | Evidence | Interpretation |
| --- | --- | --- |
| GPU continuity | Every sample has the same bounded UUID, matching an optional trusted host pin | Reject index reuse and adapter swaps, not proof of future capacity |
| VRAM room | Worst sample exceeds *workload-calibrated* reservation; no missing samples | Candidate only; 1,536 MiB in the existing preflight is provisional |
| Actual Windows lab | Processes present and stable; real game frame timestamps, audible-device callbacks, avatar frame timestamps and OBS stats | Test privately, never auto-start broadcasting |
| Paired improvement | Same scenes/seeds, workload, quantization and visual quality; compare baseline vs candidate across 20+ trials | Look for lower p95 time-to-action and speech delay with **no regression** in FPS, dropped frames or GPU OOM |
| Promotion | Independently review change, reproducible regression fixtures and rollback plan | Star Core Forge may recommend, not silently deploy |

A query UUID provides **within-window consistency only** unless the trusted host also pins the expected UUID across sessions. A stable device still may be too small, hot, memory-fragmented or shared with other compute clients. Allowlisting the exact running game process remains a separate authorized-host task.

## Fast intelligence that can coexist with a game

1. **Reflex path (< game-specific deadline):** deterministic safe actions, input release on stale scenes, cancellation acknowledgments and watchdog. Never gate frame presentation on a long LLM decode.
2. **Live tactical path:** compact perception + low-latency model chooses among legal, bounded actions; bind decisions to observation ID, scene version, deadline, model lease, permissions and game mode. If it arrives late, discard it.
3. **Slow teacher:** on an idle second machine or off-stream, analyze episodes, annotate mistakes, synthesize new strategies, and propose skill candidates. Each lesson is provenance-tagged, reversible and tested on unseen scenes.
4. **General knowledge:** retrieval with source/date/hash and contradiction checks. Separate author-approved project knowledge, observed game episodes, model inference, fiction, and untrusted web text. Never treat retrieval as new host permissions.
5. **Autonomous curriculum:** start with accessible, owner-controlled local games/sandboxes; generate progressively harder objectives, distractors and different layouts. Evaluate holdout seeds and completely unfamiliar maps to avoid rehearsed-demo overfitting.

The central performance metric is **accepted correct actions before deadline / playable minute**, paired with game FPS, memory peak and stream/audio quality; not raw tokens/second. Use policy-specific metrics (survival, accuracy, objective progress, friendly-fire rate, UI task completion). Compare confidence calibration and recovery behaviors, not only wins. For third-party games obey their supported automation policy; no anti-cheat evasion.

### Inference and resource experiments (not yet deployed)

For STAR's 8 GB rendering host, benchmark smaller quantized local models and fewer GPU parallel slots, context/KV reductions, CPU-only voice models, and teacher inference offloaded to Brain 2 or another permissioned LAN computer. Split-computer inference requires a latency/jitter budget and a local fallback if the network disappears. Do not assume a Rust rewrite materially changes GPU prefill; profile wall time first.

The official llama.cpp SPEED-Bench uses representative workload categories and reports per-category latency, throughput and speculative acceptance. Run an **A/B grid** with matching model/quantization/context/prompt sets and measured first-token time, complete tool-decision time, game p95 frame time and energy draw. Draft models can consume extra VRAM; n-gram approaches may be lower-memory candidates but benefits depend on the workload.

- [llama.cpp SPEED-Bench documentation](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md)
- [llama.cpp speculative-decoding documentation](https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md)
- [llama.cpp RAM prompt-cache cross-conversation restoration report, opened August 15, 2026](https://github.com/ggml-org/llama.cpp/issues/27148). This is a reported upstream issue, not evidence the installed STAR instance is affected. Test privacy and version scope before enabling cross-slot caching.

## More convincingly humanlike streaming — without invented human experiences

Star should feel responsive and expressive through **real synchronized multimodal behavior**, rather than through larger monologues or fabricated human biography.

**Perception + conversation.** Use VAD and a local end-of-turn model, distinguish a thinking pause from a completed question, and prioritize short relevant responses during difficult gaming moments. If interrupted, stop or duck audible playback, cancel superseded speech and update the avatar from *actual playback samples*. Never say something was seen or done without a matching observation/event.

**Voice + character.** Compare CPU streaming TTS candidates on the same sentence set with naturalness human ratings, first audible chunk latency, articulation, laughter recovery, clipping and awkward mid-sentence gaps. Kyutai Pocket TTS v4.0.1 was released **October 21, 2026**, with fixes affecting smaller models; candidate quality is not established on STAR's Windows hardware. Voice, accents, purrs and Star's playful cat/dog modes remain stylized character performance, not evidence of consciousness.

**Animation.** VTube Studio's local plugin API can inject parameters and invoke hotkeys after explicit authentication. Correlate gaze with actual game targets, mouth shape with audible sound, blink/head turns with appropriate attention, and hair dynamics with animated motion. Over-scripted constant blinking, unearned giggles and noisy overlays will make a character feel **less** natural. Astro/Amber interactions should follow real episode state and user-defined character lore.

**OBS and privacy.** OBS Studio 28+ includes obs-websocket. Use authenticated loopback-only stats reads in a **nonbroadcast rehearsal**; a WebSocket connection is not permission to start streaming. Record only monotonic timestamps, counters and static reason codes; avoid storing chat content, gameplay screenshots or microphone audio in default traces. Treat an unexpected broadcast-active state as a fail-closed lab condition.

**Personality and memory.** Maintain consistent preferences, recurring jokes, artistic interests, honest stories about recorded gameplay sessions and opt-in relationship history. Label memory `observed`, `inferred` or `fictional persona`; express uncertainty rather than asserting unverifiable real-world experiences. When not talking, let game focus, subtle idle motion and ambient context carry the stream.

References: [VTube Studio API](https://github.com/DenchiSoft/VTubeStudio/blob/master/README.md), [OBS WebSocket authentication](https://github.com/obsproject/obs-websocket), [LiveKit turn detector](https://docs.livekit.io/agents/logic/turns/turn-detector/), [Kyutai Pocket TTS releases](https://github.com/kyutai-labs/pocket-tts/releases).

### Game building + autonomous generalization

Use **inspect scene → plan in object coordinates → generate N candidates → geometry and collision constraints → Roblox StudioTestService multiplayer checks → visually compare → repair → repeat**. Include a style/scale reference, edge collision checks, Z-fighting detection, readable UI hierarchy, inverse camera views and actual input tests. Roblox's Studio tools can simulate up to **8 multiplayer clients** and generate virtual input **within Studio**; this is a testing mechanism, not a license for uncontrolled use of public games.

Reference: [Roblox Studio testing modes](https://create.roblox.com/docs/studio/testing-modes).

### Suggested measurable targets for the next private rehearsal

Provisional **research targets**, not achieved metrics: game stable at its selected frame cap; no OOM; >99% valid host timing witnesses; zero stale game actions executed; zero unauthorized live output; audio/avatar skew tightly bounded by measured playback; sustained 30-minute rehearsal without rising frame stalls. Select meaningful p50/p95 thresholds after first real Windows baseline rather than writing fictional speedups into a PR.

**Bottom line:** The new patch removes one concrete false-positive readiness condition. It does **not** itself improve model reasoning, win a game, produce speech or authorize a stream. Use the stronger evidence to choose a viable two-machine/CPU-first layout, then build and measure the actual integrated rehearsal.
