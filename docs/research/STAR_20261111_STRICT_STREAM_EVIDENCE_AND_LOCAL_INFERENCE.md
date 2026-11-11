# STAR: Strict Streaming Evidence, Natural Voice Evaluation, and Local Inference Research

**Research date:** 2026-11-11  
**Implementation branch:** `fix/strict-stream-benchmark-jsonl-20261111-auto11`  
**Base:** `star/next`  
**Scope:** strengthen the integrity of STAR's existing streaming performance evidence and turn recent voice/inference research into concrete evaluation and rollout requirements. This note does not claim that STAR has passed external benchmarks or that a new model/runtime is faster on the owner's hardware.

## Executive finding

STAR already has more of the needed components than a fresh architecture diagram suggests:

- `star/voice/call.py` performs streaming sentence synthesis, supports barge-in, calls the speaker's stop method, and tracks the portion of a reply that was actually played.
- `star/voice/metrics.py` records turn-stage timing.
- `star/stream_director.py` arbitrates owner interruptions, viewer questions, game events, and deliberate silence.
- `star/stream_multiparty_floor_eval.py` (in its development PR) evaluates response selection in group conversations.
- `star/stream_hardware_telemetry.py` gathers read-only host telemetry away from the game/audio hot path.
- `star/stream_realtime_benchmark.py` compares paired runs using first-audio timing, game frame intervals, and peak GPU memory.
- `star/stream_qos.py` now has a proposed `game_control` lane in PR #1123, separate from actual game-input authorization.
- `star/game_closed_loop.py`, `star/game_skill_memory.py`, `star/game_skill_promotion.py`, and `star/game_transfer_eval.py` provide a foundation for observe-act-verify gameplay and held-out transfer evaluation.
- `star/general_knowledge_benchmark.py` and the continual-learning evaluation work provide separate routes for broad knowledge and memory-transfer measurement.

The audit found a data-integrity gap in an existing benchmark, not a need for another scheduler: `read_jsonl()` used Python's permissive default `json.loads`. Duplicate object keys silently used the last value, and JavaScript-style `NaN` / `Infinity` constants were accepted by the decoder. This is unsuitable for evidence used to compare candidate runtime configurations.

## Implementation in this branch

### Strict JSONL evidence decoding

Updated `star/stream_realtime_benchmark.py`:

- A custom `object_pairs_hook` rejects duplicate keys before a run is converted into a benchmark record.
- A `parse_constant` hook rejects `NaN`, `Infinity`, and `-Infinity` at the decoder boundary.
- Malformed or excessively nested JSON records are rejected as invalid JSONL records.
- Existing exact-field validation, numeric bounds, run-count limits, paired-run requirements, and aggregate-only reporting remain in place.

Updated `tests/test_stream_realtime_benchmark.py` with regressions for duplicate keys and non-finite constants.

Why this matters: RFC 8259 says object member names should be unique and notes that implementations differ when they are not. A benchmark must not silently accept ambiguous evidence.

This is a narrow integrity fix. It does not change any live voice, game, model, or OBS behavior and does not itself improve inference speed.

## New research findings

### 1. InteractionBench: evaluate the whole listener experience

**InteractionBench** was submitted to arXiv on 2026-11-02. It evaluates four dimensions on the same recorded conversations: conversational timing, spoken-task accuracy, whisper/volume control, and groundedness over conversations longer than 20 turns. Its evaluation contains 221 items per system across 13 scenarios and 1,519 graded runs.

The paper's key engineering lesson is measurement-boundary discipline: timing is measured where the client hears the audio, not merely from the server's own clock. It reports a case where a roughly 1.5-second timing-reference difference materially changed a hosted system's timing score.

Sources:
- https://arxiv.org/abs/2611.02430
- https://thelatestinai.com/papers/2611.02430

**STAR implication:** distinguish all of these timestamps rather than calling them all "first audio":

1. user end-of-turn detected;
2. transcript finalized;
3. first model token;
4. first sentence accepted by the TTS worker;
5. first PCM chunk generated;
6. PCM enqueued to the speaker;
7. first sample actually presented by the output device;
8. final sample actually presented;
9. interruption requested;
10. output device confirms silence / queue drained.

The current `CallSession` metric `first_audio_at` is set when PCM is handed to `speaker.play()`; that is an enqueue-side event, not proof that the listener has heard a sample. The existing offline benchmark can accept host-measured first-audible latency, but a trusted Windows output adapter still needs to provide that measurement from the device/loopback callback on the same monotonic clock as the rest of the run.

Likewise, `Speaker.stop()` expresses a stop request. The host should expose a separate acknowledgement that the output queue is physically silent. Do not report interruption latency as complete merely because a cancellation flag was set.

### 2. MP-Bench: multiparty streaming is a separate capability

The Findings of EMNLP 2026 paper evaluates voice agents as active participants in group conversations. It separately scores turn-taking awareness, response appropriateness, and comprehension. In its evaluation of 12 systems, real-time agents reached at most 22% multiparty comprehension and were near chance on turn-taking.

Source:
- https://aclanthology.org/2026.findings-emnlp.1437/

**STAR implication:** keep the following scores separate:
- addressee accuracy (is this directed at Star?);
- response appropriateness (should she take the floor?);
- silence preservation (should she remain quiet?);
- interruption/yield accuracy;
- group-conversation comprehension;
- factual answer accuracy;
- client-heard response latency.

A single "voice quality" score would hide exactly the failures that make a VTuber feel socially awkward. Session-local speaker labels are enough for turn-taking; do not turn diarization into identity or voiceprint claims.

### 3. StrataFlux: promising memory-hierarchy research, not a drop-in 4060 optimization

**StrataFlux** was submitted on 2026-11-05. It co-designs low-bit weight/KV quantization and selective precision delivery from host RAM/SSD, evaluating 2–4-bit weights and 2–3-bit KV cache. Its reported RTX 5090 experiments include quality recovery at high throughput retention for a particular 2-bit Llama configuration.

Source:
- https://arxiv.org/abs/2611.08363

**STAR implication:** add it to the candidate research queue, but do not claim its RTX 5090 results transfer to an 8 GB RTX 4060. A local test must pin the exact model revision, quantization, context length, llama.cpp/build/runtime revision, CPU, RAM speed, GPU, driver, and concurrent workload. Measure both task quality and end-to-end latency.

### 4. Sparse KV cache systems: useful concepts, different hardware regime

**UlaCache** (2026-10-21) proposes a logical KV address space spanning GPU and optional CPU memory. Its published speedups are on H200/B300 multi-GPU configurations with speculative decoding, not on a single 8 GB consumer GPU.

Source:
- https://arxiv.org/abs/2610.29820

**STAR implication:** borrow the design questions—cache locality, transfer overlap, eviction policy, and stable logical references—but do not port the reported speedup numbers into STAR's performance targets. A single-GPU implementation should be judged on measured transfer stalls, RAM pressure, context quality, and first-audible latency.

## Research-backed capability plan

### A. Natural VTuber interaction

The target is a coherent interaction loop, not a chatbot that simply talks more:

- Listen while viewers talk to each other.
- Recognize direct address, group address, and unrelated side conversation.
- Use brief acknowledgements only when they do not steal the floor.
- Yield promptly on a genuine interruption.
- Avoid cutting off pauses, backchannels, or self-corrections.
- Vary response length and prosody to the moment.
- Ground jokes and reactions in observed context.
- Keep a compact session memory of topics, game events, and promises.
- Synchronize mouth/viseme motion to actual playback, and return to listening only after the output device confirms silence.
- Preserve clear AI disclosure; natural interaction should not depend on pretending to be a human.

### B. Game mastery

Keep two reasoning horizons:

- **Reactive controller:** short deadlines for movement, aiming, dodging, interaction, and recovery.
- **Strategic planner:** longer asynchronous planning for objectives, maps, resource routes, team tactics, and skill learning.

Every action must be tied to a game/session epoch and a fresh observation sequence. A strategy computed from an old frame expires; it cannot overwrite a newer observation. Repeated failure should stop the loop and request diagnosis rather than trigger unlimited retries.

A reusable skill should store its game/version scope, preconditions, action policy, expected state transition, failure modes, recovery, and verifier. Promotion requires repeated practice evidence and an independently held-out transfer test; self-critique alone is not a verifier.

### C. Game creation

For Roblox, Blender, and later Unity/Godot, keep engine-specific tool contracts and validators. The shared creator loop is:

1. inspect the project and version;
2. identify requirements and acceptance checks;
3. plan the smallest coherent change;
4. edit in a disposable/test workspace;
5. launch/import in the actual engine;
6. playtest or run deterministic scene checks;
7. inspect visual output;
8. repair defects;
9. run regressions and an unseen task.

A successful compile is not a visual-quality or gameplay-success result. Keep publishing, monetization, live player-data writes, and player consequences outside unattended workflows.

### D. General knowledge and memory

For each retained claim, store source URL, source date, retrieval date, version/scope, confidence, and conflicting evidence. Assign freshness policies: current APIs/prices/software versions expire quickly; stable mathematics does not. Keep episodic memories (what happened), semantic memories (what is supported as true), and procedural memories (how to do a verified task) distinct.

Measure memory with paired memory-on/off task streams, dependent transfer probes, unrelated interference probes, and held-out tasks. Do not automatically promote a memory policy because it improves one development set.

## Local inference plan for the 8 GB GPU class

Run one-variable-at-a-time, paired tests with the same prompt set and mixed workload:

1. stable-prefix prompt caching on/off;
2. one versus multiple server slots;
3. context/KV type and context length;
4. quantization levels with a fixed quality suite;
5. CPU/GPU layer placement;
6. speculative decoding only with a measured draft/target pair;
7. MoE expert cache size only for applicable MoE models;
8. model routing: fast small model for bounded reactions, stronger model for complex strategy/research;
9. voice engine placement and warm/cold behavior;
10. game-vision sampling frequency and resolution.

A valid comparison pins model and tokenizer revision, runtime commit, build flags, quantization, prompt/context, CPU threads, GPU layers, context length, slot count, driver, game build/scene, OBS profile, and background workload. Randomize or balance baseline/candidate order and retain failed/cancelled runs.

Report:
- prefill/prompt-processing time;
- time to first token and inter-token p50/p95;
- first PCM generation;
- first client-heard sample;
- cancellation-to-confirmed-silence;
- task accuracy and held-out transfer;
- game p10 FPS / 1% low and frame-time p95/p99;
- OBS render/encode drops;
- audio underruns;
- peak/free VRAM and RAM;
- queue wait and deadline misses.

Do not optimize tokens/second if the game stutters, audio underruns, first-audible latency worsens, or answer quality regresses. Keep a configuration eligible for a **manual** pilot only; no benchmark report should auto-change live model routing.

## Recommended next implementation sequence

1. Add a trusted Windows playback adapter that distinguishes enqueue, device-start, device-drained, and stop-ack events.
2. Export privacy-minimized, same-clock audio/OBS/game telemetry to the existing paired real-time benchmark.
3. Add a host-run rehearsal that replays the same conversation/game workload against baseline and candidate configurations.
4. Connect the multiparty floor evaluator to actual host annotations and keep a sealed conversation holdout.
5. Add a game-practice curriculum that uses versioned skills and independently verified objective outcomes.
6. Run the full mixed workload: game + OBS + VAD/ASR + TTS + model + avatar + background tasks.
7. Only then consider model/runtime changes.

## Verification boundary

The new JSONL decoder and regression tests are committed to this branch. GitHub Actions is the independent repository test/lint/type gate. No full pytest, Ruff, Pyright, Windows, OBS, microphone, speaker-loopback, GPU, Roblox Studio, or gameplay run is claimed here.

The new decoder hardens benchmark evidence; it does not change the running application, model weights, prompts, routing defaults, memory store, avatar, OBS, devices, game controls, or broadcast settings.
