# STAR: Real-Time Audio Callback Budget, Conversation Evaluation, and Roblox Game Creation

**Research date:** 2026-11-11  
**Scope:** local Windows voice runtime, VTuber responsiveness, conversational evaluation, Roblox game creation, local inference, and evidence-backed learning.

## Executive summary

This pass found two actionable problems in the current voice-device development branch:

1. The PortAudio output callback still performed NumPy import/conversion and RMS calculation inline. PortAudio documents that callbacks run under real-time constraints and should avoid memory allocation, I/O, mutex operations, context switches, and other operations that may block.
2. The device-output PR introduced optional metrics that were not represented in an older zero-difference test, and its new numeric validation was not fully narrowed for Pyright.

The implementation now moves speaker-level metering to a bounded worker queue, keeps PCM delivery independent from meter overload, and treats an unknown/pending meter sample conservatively so the echo gate does not mistake delayed telemetry for silence. It also repairs the inherited Pyright and regression failures.

The research adds two useful external evaluation tracks that complement STAR's existing systems: TurnBench for dyadic interruption/end-of-turn timing, and OpenGameEval for stateful Roblox Studio exploration/build/play verification.

## 1. Repository audit and implementation

### Existing behavior

The existing star/voice/devices.py output callback performed these operations inline:

- allocate/copy the output PCM chunk;
- acquire the speaker buffer lock and delete consumed bytes;
- import NumPy on the first non-empty callback;
- convert the PCM to a float32 array;
- allocate intermediate arrays for squaring;
- calculate mean-square and square-root RMS;
- append the result to a shared deque.

The PortAudio callback documentation warns against callback work that can allocate, block, perform I/O, context-switch, or acquire contended mutexes. See the official [PortAudio callback guidance](https://files.portaudio.com/docs/v19-doxydocs/writing_a_callback.html).

### Implemented change

- Move PCM16 RMS calculation into _process_levels, a dedicated daemon worker.
- Keep the telemetry queue bounded at 64 samples.
- Use a bounded collections.deque for callback-to-worker handoff; callback never waits for the meter worker.
- Drop the oldest meter sample when the telemetry queue is full; never drop or alter the PCM output because of meter pressure.
- Count dropped meter blocks.
- Keep the level-history deque protected by its own lock, separate from the speaker PCM buffer lock.
- If a meter sample is pending, dropped, or failed, level() returns a conservative full-scale value until the worker catches up or the 400 ms overflow window expires. This prevents the echo gate from treating unknown speaker output as silence and accidentally admitting echo as a user interruption.
- Drain the bounded meter queue during orderly shutdown, with a bounded join.
- Preserve the PortAudio scheduled-DAC timestamp and the legacy speaker interface.

### Important limitation

This is a targeted soft-real-time improvement, not a claim that the callback is fully hard-real-time safe. It still copies PCM and takes the existing speaker-buffer lock. A future native single-producer/single-consumer ring buffer with preallocated blocks is the stronger design if Windows device tests show callback jitter or lock contention. Do not replace the current path with an unmeasured native extension.

### Regression and type fixes

- test_negative_clock_differences_are_clamped_and_zero_generation_has_no_rate now distinguishes legacy zero-clamped stages from optional device-output stages that are legitimately unknown when no device timestamp exists.
- call.py and metrics.py use explicit finite-number type guards, rejecting booleans and invalid clock values while satisfying Pyright's narrowing requirements.

## 2. New conversational research: TurnBench

[TurnBench](https://turnbench.sesame.com/) is a multi-domain benchmark for end-of-turn (EOT) and interruption (INT) detection in two-channel human conversations. Its published corpus contains 154 conversations, approximately 30 hours, 106 speakers, six conversation types, and triple annotations. It reports recall, false-positive rate, and detection latency rather than collapsing them into one score.

The November 2026 leaderboard and analysis show an important trade-off: no evaluated system simultaneously achieves fast detection, high recall, and low false-positive rates. False interruptions are especially difficult in casual, backchannel-heavy conversations. The human corpus has a median turn-transfer onset about 151 ms before the previous turn ends; this is a useful reference point, not a universal target for every language or stream.

**Application to STAR:**

- Add a TurnBench scorer adapter to the existing voice EOT/duplex evaluation suite rather than replacing STAR's own evaluators.
- Tune only on the public development split; keep the held-out test split sealed.
- Report EOT and interruption separately: recall, FPR, signed latency p10/p50/p90, and conversation-type slices.
- Preserve MP-Bench for multiparty comprehension/appropriateness; TurnBench is dyadic and does not replace multiparty evaluation.
- Check dataset terms before downloading or redistributing audio; a benchmark scorer can be integrated without bundling restricted recordings.

Sources: [Sesame TurnBench paper and analysis](https://www.sesame.com/journal/turnbench), [TurnBench scorer repository](https://github.com/SesameAILabs/turnbench).

## 3. New Roblox creator research: OpenGameEval

[OpenGameEval](https://github.com/Roblox/open-game-eval) is a stateful Roblox Studio evaluation framework described in the October 1, 2026 paper [arXiv:2610.02563](https://arxiv.org/abs/2610.02563).

The paper reports:

- 84 human-curated core tasks;
- an eight-tool action space separating observation from editing;
- executable checks on the edited scene and a simulated play session;
- 13 evaluated models with 16 attempts per task;
- a best single-attempt pass rate of 51.7%, with 39.4% consistency across five attempts.

A key finding is that exploration predicts success. Inspecting every object that a reference solution touches was associated with 13.4 percentage points higher pass rate on scene-only tasks and 9.8 points on script-only tasks than inspecting none, with task and model held fixed.

**Application to STAR Creator:**

1. Keep observation tools distinct from scene-editing tools.
2. Require inspection of relevant objects, scripts, properties, constraints, and dependencies before modifying them.
3. Record an exploration trace separately from the edit trace.
4. Validate both the resulting scene and an actual simulated play session.
5. Preserve task-specific holdouts and repeat attempts to measure consistency, not just best-of-N success.
6. Keep OpenGameEval's place files and plugin isolated in a disposable local evaluation environment; do not point evaluation at a production experience.

OpenGameEval complements [GameDevBench](https://github.com/waynchi/gamedevbench), which focuses on 333 Godot game-development tasks across graphics/animation, 3D, UI, and gameplay. STAR should use the Roblox benchmark for Roblox Studio workflows and GameDevBench for cross-engine/Godot capability; neither is a substitute for real user-game playtesting.

## 4. Multiparty VTuber streaming remains a separate problem

[MP-Bench](https://aclanthology.org/2026.findings-emnlp.1437/) evaluates agents as active participants in multi-party speech. Its October 2026 paper reports that evaluated real-time agents scored at or below 22% on multiparty comprehension and near chance on multiparty turn-taking.

[Full-Duplex-Bench v3](https://www.full-duplex.ai/benchmarks/fdb-v3) adds real spoken requests with disfluencies and chained tool calls, scoring tool accuracy, latency, and turn-taking.

STAR should maintain distinct acceptance dimensions:

- dyadic EOT/interruption timing (TurnBench);
- multiparty addressee, comprehension, and response appropriateness (MP-Bench);
- spoken-task completion and chained tool correctness (Full-Duplex-Bench v3);
- local first-audible/device-output and interruption-to-silence measurements;
- avatar synchronization to the actual audio output path.

A high score on one dimension must not hide a failure on another.

## 5. Inference speed and intelligence: local evidence only

STAR's 8 GB RTX 4060 target is not comparable to multi-GPU H200/B300 research platforms. UlaCache's published throughput results use H200/B300 configurations; they are architectural inspiration, not an expected speedup on STAR's machine.

Keep optimization experiments paired and workload-specific:

- time to first token and time to first audible/device-output sample;
- inter-token latency and end-to-end completion;
- prompt-processing versus decode time;
- peak VRAM and host RAM;
- game p10 FPS and OBS render/encode/network drops;
- task success and answer quality.

Test prompt-prefix caching, KV-cache formats, quantization, speculative decoding, model routing, and CPU/GPU layer placement one change at a time. A cache hit or higher isolated tokens/second is not a win if first-audible latency, answer quality, or game frame-time regresses.

## 6. Memory and general knowledge

[MemTrace](https://arxiv.org/abs/2610.04838) emphasizes that historical execution evidence can become stale as a repository changes. STAR should keep immutable episodic traces with file/symbol/test anchors and revalidate them against the current repository before reusing a solution.

The same rule applies to game skills and general knowledge:

- game skill: bind to game/version/map/control scheme and verify on a fresh state;
- general fact: retain source, date, confidence, and freshness;
- code technique: retain tests and environment/version constraints;
- persona memory: distinguish observed events from interpretation or speculation.

This complements STAR's existing memory-transfer and skill-evaluation work; it should not create a second ungoverned memory store.

## 7. Unified roadmap

| Priority | Work | Acceptance evidence |
|---|---|---|
| P0 | Finish device-output timing PR and this callback follow-up | full offline tests + Pyright + Windows audio test |
| P1 | Native WASAPI loopback/IAudioClock adapter | same-clock loopback and route-epoch tests |
| P1 | TurnBench adapter | dev-set score with frozen operating point; sealed test untouched |
| P1 | OpenGameEval adapter | disposable Studio runs, scene checks and simulated-play checks |
| P2 | Social Director | MP-Bench slices plus live multiparty rehearsal |
| P2 | Live2D/audio embodiment | mouth/viseme and expression timing against device output |
| P2 | Game skill transfer | scenario-balanced unseen maps and versions |
| P2 | Creator Brain | OpenGameEval + GameDevBench + project-specific playtests |
| P3 | Local inference A/B | paired mixed-workload improvement without quality regression |
| P3 | Knowledge Lab | source freshness, transfer, and interference evaluations |

## 8. Validation boundary

- New tests are deterministic and do not open a physical audio device.
- The callback worker is exercised through a fake PortAudio stream.
- GitHub Actions must complete on the final branch head before this change is considered verified.
- No Windows WASAPI/MMCSS, OBS, microphone, acoustic loopback, RTX 4060, Roblox Studio, live gameplay, or livestream test is claimed.
- No model, prompt, memory policy, routing default, process priority, avatar, OBS setting, game permission, or broadcast behavior is changed.
- No speedup, improved win rate, or human-equivalent behavior is claimed.
