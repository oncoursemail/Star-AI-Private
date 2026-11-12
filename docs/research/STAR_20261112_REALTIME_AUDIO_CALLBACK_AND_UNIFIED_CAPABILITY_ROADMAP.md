# STAR AI: Real-Time Audio Callback Isolation and Unified Capability Roadmap

**Research date:** 2026-11-12  
**Implementation branch:** `feat/voice-playback-clock-and-validation-fix-20261112`  
**Parent:** PR #1151  
**Scope:** voice runtime reliability, natural VTuber interaction, local inference performance, game-playing/creation, continual skill learning, and general knowledge.

## Executive summary

A direct audit of the current `star/voice/devices.py` found that the PortAudio output callback still imported NumPy, converted PCM to float arrays, allocated intermediate arrays, calculated RMS, and appended meter history inline. This is avoidable work on a time-sensitive audio callback.

The change in this branch moves speaker-level RMS analysis to a dedicated worker behind a bounded, best-effort queue. The callback still delivers the original PCM. Meter backlog or overflow can discard only telemetry samples, never audio. If meter data is pending, dropped, or invalid, the echo gate treats the level as conservatively audible instead of interpreting unknown output as silence.

This is a soft-real-time improvement, not a hard-real-time guarantee. The Python callback still copies PCM and acquires the existing speaker-buffer lock; playback telemetry also uses a small lock. A native preallocated single-producer/single-consumer ring buffer is a future option only if Windows device profiling demonstrates callback jitter or priority inversion.

## 1. Repository audit and implementation

### Before

For each non-empty output callback, the speaker did the following after copying audio to the device buffer:

1. Imported NumPy on the callback thread.
2. Wrapped the PCM bytes as an array.
3. Converted samples to float32.
4. Allocated an intermediate squared array.
5. Calculated mean-square and square-root RMS.
6. Appended the result to a shared history deque.

The NumPy import and array reductions are not required to deliver PCM. The PortAudio callback guidance recommends keeping callbacks to minimal data movement and simple math, and avoiding memory allocation, I/O, OS services, and locks that can be held by lower-priority threads.

Source: [PortAudio callback guidance](https://github.com/PortAudio/portaudio/wiki/Tips_Callbacks) · [python-sounddevice callback documentation](https://python-sounddevice.readthedocs.io/en/latest/)

### After

The new path is:

```text
PortAudio callback
    |
    +--> copy queued PCM to output buffer (existing behavior)
    |
    +--> record playback timing/counters
    |
    +--> append (sequence, output time, PCM block) to bounded deque
                    |
                    v
             meter worker thread
                    |
              PCM16 RMS
                    |
             bounded history
                    |
               echo gate
```

Implementation details:

- The meter handoff is a `collections.deque(maxlen=64)`; memory use is bounded.
- The callback never waits for the meter worker and performs no NumPy import or RMS reduction.
- A monotonically increasing sequence number lets the worker detect samples evicted by queue overflow. Drop accounting happens on the worker, not the callback.
- RMS uses a native-endian PCM16 memory view and ordinary arithmetic. The block size is the audio callback block, not the whole utterance.
- The original PCM buffer, output bytes, played-sample counter, scheduled-DAC playback timestamp, and PortAudio underflow measurement remain separate from the meter.
- Meter overload drops only old meter observations; it does not drop, modify, or delay PCM output.
- While samples are pending, or after a meter drop/failure for the 400 ms echo window, `level()` returns a conservative audible value. Unknown speaker output must not be mistaken for silence, because that could admit the agent's own speech as a false user interruption.
- The worker drains the bounded queue after the stream is stopped and is joined with a bounded timeout.

### Remaining real-time limitations

This patch does not claim that Python/PortAudio is hard-real-time safe:

- The output callback still acquires the existing PCM buffer lock.
- It still copies a bounded PCM block into a Python `bytes` object.
- `PlaybackTelemetry` records through a small lock.
- Python scheduling and the GIL remain part of the callback path.
- A full native SPSC ring buffer and native callback shim would be a larger architectural change.

Do not add a native extension or force an aggressive Windows audio period without a reproducible device trace. First measure callback duration, underflows, queue depth, and p95/p99 jitter on the actual Windows audio devices.

## 2. Streaming quality is more than response speed

STAR should optimize a live stream as an end-to-end interaction, not just model tokens per second.

Track these separately:

- end-of-turn detection recall and false positives;
- interruption detection recall and false positives;
- backchannel continuation and selective yielding;
- first token;
- first TTS submission;
- first scheduled device output;
- client-heard/loopback output;
- task correctness and tool completion;
- prosody/volume control;
- long-conversation groundedness;
- avatar/audio synchronization;
- OBS render, encode, and network health.

### TurnBench: dyadic floor control

TurnBench evaluates end-of-turn and interruption detection on 154 recorded two-channel conversations, about 30 hours, 106 speakers, and six conversation types. It reports recall, false-positive rate, and detection latency. Its analysis shows that interruption false positives concentrate in backchannel-heavy casual conversation; an acoustic event is not automatically a true takeover.

Sources: [TurnBench benchmark](https://turnbench.sesame.com/) · [paper and methodology](https://www.sesame.com/journal/turnbench) · [scorer repository](https://github.com/SesameAILabs/turnbench)

STAR application:

- keep EOT and interruption as separate classifiers/metrics;
- distinguish a backchannel ("yeah", laughter, acknowledgement) from a real attempt to take the floor;
- require causal predictions: no future audio may be used to label a decision at time t;
- tune on the public development split only and keep test labels sealed;
- report slices for casual, task-oriented, instructional, collaborative, argumentative, and narrative conversation;
- do not optimize a single latency number at the expense of false barge-ins.

### MP-Bench: multiparty conversation

MP-Bench evaluates voice agents as participants in multi-party conversations, including turn-taking awareness, response appropriateness, and comprehension. Its October 2026 benchmark report found that evaluated real-time agents reached at most 22% on multiparty comprehension and near-chance performance on multiparty turn-taking.

Source: [MP-Bench](https://www.fullduplex.ai/benchmarks/mp-bench)

STAR application:

- preserve separate speaker channels when available;
- maintain speaker turns, addressee hypotheses, and confidence;
- distinguish speech addressed to Star from viewer-to-viewer conversation;
- do not answer every utterance;
- handle overlapping speech without assuming the loudest speaker owns the floor;
- track whether a viewer's question was already answered by another participant.

### Full-Duplex-Bench v3 and InteractionBench

Full-Duplex-Bench v3 uses 100 human-recorded spoken requests across 79 scenarios and 12 speakers, including disfluencies and chained tool calls. It reports task/tool accuracy, turn-taking, and latency separately.

Source: [Full-Duplex-Bench v3](https://www.full-duplex.ai/benchmarks/fdb-v3)

InteractionBench evaluates 221 items across 13 scenarios and 1,519 graded runs. It separately scores conversational timing, spoken-task accuracy, whisper/volume control, and groundedness across long conversations. Its timing is measured at the client-heard output point, so network delay is included for hosted systems.

Sources: [InteractionBench benchmark](https://www.fullduplex.ai/benchmarks/interactionbench) · [paper](https://arxiv.org/abs/2611.02430)

STAR application:

- replay the same recorded input through ASR, turn detector, brain, tools, TTS, and playback;
- score task correctness independently from turn timing;
- add audio loopback or an explicitly calibrated client-output capture before claiming client-heard latency;
- measure whether STAR can whisper, lower her volume, and respond to quiet speech;
- use long conversations to test whether she tracks updates, speaker attribution, constraints, and facts that were never stated.

A fast but incorrect response is not a pass. A correct response that arrives after an awkward pause is not a complete streaming pass either.

## 3. Natural VTuber character runtime

STAR should feel expressive and coherent, not like a text chatbot with a mouth animation. The goal is natural character performance while remaining honest that she is an AI character; do not invent offline experiences or manufacture laughter on every message.

Use one Avatar Director to arbitrate layered animation:

- **Mouth:** driven by the PCM actually being played, anchored to the output clock rather than LLM text-generation time.
- **Expression:** context selects a bounded expression target; smooth transitions and allow neutral/listening states.
- **Eyes:** blink and gaze have separate priorities so attention updates do not cancel a blink.
- **Body/idle:** subtle breathing/idle motion, reduced during deliberate gestures.
- **Gestures:** authored wave, nod, laugh, point, celebrate, thinking, and game-reaction animations.
- **State arbitration:** idle, listening, thinking, speaking, reacting, game-focused, interrupted, and recovering.
- **Recovery:** after interruption, stop stale speech, clear stale mouth frames, preserve the unfinished thought, and decide whether to resume.

The existing STAR camera/LiveRig/VMC stack should remain the primary internal avatar path. VTube Studio is an optional adapter, not a required dependency. Its API can be used only when explicitly enabled and authorized by the owner.

Sources: [VTube Studio API](https://github.com/DenchiSoft/VTubeStudio) · [Live2D Cubism lip-sync](https://docs.live2d.com/4.2/en/cubism-sdk-manual/lipsync/)

## 4. STAR Gamer: learn games through feedback, not prompt memory

### SIMA 2 and Voyager

SIMA 2 demonstrates a 3D-world agent combining language instructions, goal reasoning, conversation, perception, and actions. Voyager demonstrates an open-ended learning loop with an automatic curriculum, executable skill library, execution-error feedback, and self-verification.

Sources: [Google DeepMind SIMA 2](https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/) · [Voyager paper](https://arxiv.org/abs/2305.16291) · [Voyager project](https://voyager.minedojo.org/)

STAR application:

- **Reactive controller:** high-frequency movement, camera, aiming, dodging, and immediate input.
- **Strategic planner:** goals, map understanding, route planning, tactics, practice curriculum, and memory retrieval.
- The strategic planner runs asynchronously and must never block the control loop.
- Use a curriculum that moves from basic movement to navigation, interaction, resource use, combat, objectives, and team coordination.
- Convert successful behaviors into versioned executable skills, not vague prose memories.
- Each skill records game/build version, map or mode, control scheme, preconditions, action sequence, expected observations, failure conditions, and test evidence.
- Promote a skill only after repeated success on fresh states and held-out variants.
- Record failure traces and use them to propose a repair; never silently mark an unverified attempt as mastery.
- Do not assume a skill transfers between games just because the controls look similar.

## 5. STAR Creator: ship playable games, not merely compiling projects

### OpenGameEval

Roblox's OpenGameEval runs agents in reproducible stateful Roblox Studio sessions. It separates observation from editing and checks both the edited scene and a simulated play session. The October 2026 paper reports 84 curated tasks and 13 evaluated models; inspecting relevant objects before editing correlated with higher pass rates.

Sources: [OpenGameEval paper](https://arxiv.org/abs/2610.02563) · [official Roblox repository](https://github.com/Roblox/open-game-eval)

STAR Creator workflow:

1. Inspect the DataModel, scripts, assets, properties, and dependencies.
2. Record the exploration trace separately from the edit trace.
3. Plan the smallest targeted change.
4. Apply changes in a disposable development copy.
5. Run static checks and edit-mode assertions.
6. Start a play session and exercise real input.
7. Inspect screenshots, output, runtime state, and errors.
8. Repair and repeat.
9. Verify win/loss conditions, save/load, multiplayer behavior, and performance when required.
10. Save/promote only when the acceptance contract passes.

External evaluation must remain opt-in, use a disposable place, and read owner-provided credentials from a local secret store. Never commit or print Open Cloud keys.

### GameDevBench and CEGame-Bench

GameDevBench contains 333 Godot tasks across 2D/3D graphics and animation, UI, and gameplay. Its paper reports that visual feedback improved one evaluated configuration from 41.1% to 52.0%.

CEGame-Bench evaluates long-horizon complete-game creation across Defold, Godot, Roblox Studio, Unity, and Unreal. Its October 2026 preprint reports that only 16% of evaluated agent runs reached the ending; requirement-driven playtesting improved execution-based scores by 14.1–24.3 points for three evaluated models.

Sources: [GameDevBench](https://github.com/waynchi/gamedevbench) · [CEGame-Bench paper](https://arxiv.org/abs/2610.26098)

STAR acceptance contract: a project is not complete because it compiles. It must launch, start the intended mode, support the core loop with real input, reach expected endings, persist state where required, and survive a restart.

## 6. General knowledge and memory governance

Use the existing STAR memory infrastructure rather than adding an ungoverned second database.

Keep these categories distinct:

- **Semantic:** facts, concepts, definitions, and relationships.
- **Episodic:** what happened in a particular conversation, game session, or project run.
- **Procedural:** verified skills and how to execute them.
- **Working:** current task state and near-term context.
- **Temporal:** facts that can change, with source and freshness.
- **World model:** causal and spatial understanding of environments.

Every reusable memory or skill should carry:

- source/provenance;
- observation date and last verification date;
- confidence and uncertainty;
- version/environment scope;
- supporting test or execution evidence;
- known limitations and failure cases;
- privacy classification and retention policy.

Separate an observed event from an interpretation. For example, "viewer said X" is not the same as "viewer believes Y." Provide deletion/retention controls for viewer-related memory, and do not retain raw audio by default.

General knowledge evaluation should combine closed-book factual accuracy, current-information retrieval, reasoning, and practical transfer. Keep benchmark datasets and answer keys isolated from tuning data.

## 7. Local inference performance: measure the whole mixed workload

The project targets a consumer desktop GPU with 8 GB VRAM. Do not project H100/H200/B300 research throughput onto that hardware.

Run paired A/B experiments, one change at a time:

- stable prompt-prefix reuse;
- context trimming and summarization;
- KV-cache format and residency;
- quantization;
- speculative decoding with a compatible draft model;
- model routing by task difficulty;
- CPU/GPU layer placement;
- batching/concurrency;
- model residency and warm-start behavior.

Record:

- time to first token;
- inter-token latency where true token timestamps are available;
- prompt prefill and decode throughput;
- first TTS submission and first device output;
- p50/p95/p99 latency;
- peak VRAM and host RAM;
- game frame-time/FPS;
- OBS render/encode/network drops;
- task success, groundedness, and answer quality.

A change is a win only if the same workload improves the intended metric without unacceptable regressions in voice latency, gameplay frame-time, stream health, or task quality. API chunk arrival is not token-level inter-token latency.

Sources: [llama.cpp server](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md) · [llama.cpp speculative decoding](https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md)

## 8. Recommended implementation order

| Priority | Work | Required evidence |
|---|---|---|
| P0 | Keep RMS/echo metering off the PortAudio callback | fake callback isolation, bounded overflow, PCM preservation tests |
| P0 | Complete exact-head CI for PR #1151 | offline suite, Pyright, React checks |
| P1 | Windows audio device rehearsal | callback duration, underflow rate, route/epoch changes |
| P1 | WASAPI loopback timing | same-clock loopback and route-reset tests; no raw audio retention |
| P1 | TurnBench adapter | frozen operating point, dev/test split discipline, EOT/INT metrics |
| P1 | MP-Bench-style multiparty rehearsal | addressee, comprehension, response appropriateness, floor control |
| P2 | Avatar Director calibration | output-driven mouth timing and expression arbitration |
| P2 | OpenGameEval adapter | disposable Studio runs, scene checks, simulated play checks |
| P2 | Versioned Gamer skill library | repeated held-out success and transfer evaluation |
| P2 | Creator completion gate | real-input playthrough, ending, persistence, restart |
| P3 | Mixed-workload inference A/B | paired speed/quality/VRAM/FPS/OBS measurements |
| P3 | Knowledge Lab | source freshness, provenance, transfer, and memory-governance tests |

## 9. Validation boundary

- New tests use a fake PortAudio stream and do not open a physical device.
- The callback-worker change is not a native hard-real-time implementation.
- No Windows WASAPI/MMCSS, acoustic loopback, OBS, VTube Studio, microphone, RTX 4060, Roblox Studio, live gameplay, or public livestream test is claimed.
- No model weights, routing defaults, prompt defaults, persistent memory policy, game-control permissions, avatar permissions, OBS settings, or broadcast behavior are changed.
- No measured speedup, win-rate improvement, game mastery, or human-equivalent behavior is claimed.
- The branch remains a draft stacked on PR #1151; production `main`, installer, and release channel are unchanged.
