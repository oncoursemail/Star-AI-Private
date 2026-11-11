# STAR — Streaming Inference, Conversational Coordination & Game-Agent Evaluation

Date: 2026-11-11  
Status: research and implementation note  
Implementation branch: `feat/streaming-inference-probes-20261111`

## Executive summary

STAR already has substantial foundations for the requested capabilities. The current `star/next` tree includes:

- **Voice:** `star/voice/call.py`, `turn.py`, `devices.py`, `metrics.py`, streaming TTS, end-of-turn detection and interruption.
- **Streaming behavior:** `stream_director.py`, `stream_turntaking.py`, `stream_quality.py`, `stream_realtime_benchmark.py`, `stream_load_governor.py`, `stream_qos.py`, `stream_hardware_telemetry.py`, and `stream_motion.py`.
- **Game agency:** `game_closed_loop.py`, `game_action_gate.py`, `game_navigation.py`, `gameplay_skill_bank.py`, `game_skill_promotion.py`, `game_transfer_eval.py`, and `game_learning_ladder.py`.
- **Creation and knowledge:** `roblox_benchmark.py`, `general_knowledge_benchmark.py`, `agent_resource_planner.py`, specialist agents, research and memory systems.

The largest opportunity is not another disconnected subsystem. It is **measuring and coordinating the existing systems end to end**.

This pass closes one measurable gap: `star/inference_benchmark.py` previously measured completed non-streaming requests, but could not tell whether a local model started producing content quickly and then streamed smoothly. A new opt-in local streaming probe now reports first-content latency, request latency and inter-content-chunk gaps without retaining generated text.

The new probe intentionally does not call chunk cadence “tokens per second” or “inter-token latency”: an API chunk may contain multiple tokens. Use a token-aware harness such as NVIDIA GenAI-Perf or server-side token timings for that comparison.

## 1. Implemented: local streaming inference measurements

### New API

`benchmark_local_model_streaming(...)` uses the existing OpenAI-compatible local-client configuration and the same endpoint validation as STAR's existing local inference benchmark.

It is bounded to:
- 1–12 requests per run;
- 1–4 concurrent requests;
- an already-running loopback model or the configured STAR Server;
- a fixed, non-sensitive benchmark prompt.

It records only timing and count metadata:
- first non-empty content delta after request start;
- elapsed request time;
- gaps between non-empty content chunks;
- number of content chunks;
- success/failure.

It never returns or stores generated text. Empty streams and failed requests count as failures rather than zero-latency successes. The stream is closed when the client exposes an asynchronous or synchronous close method.

### Why this matters

A single request-latency number hides two different user experiences:

1. A slow first response followed by fast generation.
2. A fast first response followed by long pauses between chunks.

Those should lead to different optimization choices. The first often points toward prompt processing, model loading or queueing; the second can point toward decode speed, contention, batching or transport buffering.

### Measurement terminology

- **First-content latency** is the first non-whitespace text delta observed by the client.
- **Inter-chunk gap** is the time between text-bearing API chunks.
- **Request latency** is request start to stream completion.
- **First audible latency** remains a separate voice/device metric.
- **Token-level ITL** must come from token-aware server telemetry or a benchmark that knows how many tokens each streamed chunk contains.

The probe's first-content timestamp is not the time a listener hears STAR. It is not a device DAC timestamp, WASAPI loopback timestamp, OBS program-output timestamp or remote viewer receipt.

## 2. Inference performance research

### Use the right benchmark for the question

**NVIDIA GenAI-Perf** documents TTFT, inter-token latency, request latency, output sequence length, output-token throughput and request throughput. Its methodology distinguishes the first streamed response from later token delivery.  
Source: https://docs.nvidia.com/deeplearning/triton-inference-server/user-guide/docs/perf_benchmark/genai-perf-README.html

**llama.cpp SPEED-Bench** is specifically useful for an already-running `llama-server`, speculative decoding and per-category latency/throughput. Its README says to match client concurrency to the server slot count (`--np`) when measuring throughput.  
Source: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md

The llama.cpp server supports OpenAI-compatible streaming, parallel decoding, continuous batching, monitoring endpoints and speculative decoding. Feature availability and flags must be pinned to the exact build used for a run.  
Source: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md

### Recommended local A/B matrix

Run the same fixed prompt suite and model build under these conditions:

| Profile | Workload | Question |
|---|---|---|
| A | Idle model server, one request | Cold/warm first-content baseline |
| B | Idle model server, 2 concurrent requests | Queueing and slot contention |
| C | Idle model server, 4 concurrent requests | Throughput versus tail latency |
| D | Game running, no OBS | CPU/GPU contention from gameplay |
| E | OBS + avatar + game | Rendering/encoding pressure |
| F | Voice capture + ASR + LLM + TTS + game + OBS | Actual VTuber mixed workload |

For each run pin:
- repository commit and llama.cpp build/version;
- model file SHA-256, quantization and context length;
- GPU layers, Flash Attention setting and CPU thread counts;
- server slot count and request concurrency;
- prompt-cache and KV-cache configuration;
- speculative-decoding draft model/configuration, if enabled;
- game, scene, resolution, frame cap and OBS encoder profile.

Use warm-up runs, then randomized paired baseline/candidate order. Keep prompt, output cap and request count identical. Report p50/p95, failures and the exact number of successful samples. Do not select a configuration from one lucky run.

### RTX 4060 8 GB / CPU-first guidance

Do not copy H100/H200/B200 cache or batching settings onto a consumer GPU. Measure:
- model VRAM residency and peak VRAM;
- host RAM and page-file activity;
- CPU saturation and per-core load;
- first-content p50/p95;
- token-level ITL when available;
- game frame-time p50/p95/p99;
- audio underruns and device errors;
- OBS render skips, output skips and network drops separately.

Try prompt-prefix reuse, smaller context, KV-cache quantization, speculative decoding, CPU/GPU layer placement and MoE expert caching as separate experiments. A change is useful only if it improves the target mixed workload without harming response quality or game/stream stability.

## 3. Natural VTuber conversation: evaluate the social behavior, not just ASR

### TurnBench — dyadic turn timing

TurnBench measures end-of-turn and interruption detection using dual-channel conversations. Its current public leaderboard reports recall, false-positive rate and detection latency separately; no single operating point should be selected from latency alone.  
Sources:
- https://turnbench.sesame.com/
- https://github.com/SesameAILabs/turnbench

STAR should evaluate its own endpointer on the public development split and keep the held-out test split sealed. Report:
- end-of-turn recall and false-positive rate;
- interruption recall and false-positive rate;
- signed detection latency p10/p50/p90;
- separate results for backchannel-heavy, casual, formal and overlapping speech.

TurnBench is dyadic. It is not a substitute for multiparty evaluation.

### MP-Bench — group conversation

MP-Bench evaluates agents as active participants in multi-party conversations, measuring turn-taking awareness, response appropriateness and comprehension. Its October 2026 paper reports that the 12 evaluated agents reached at most 22% multiparty comprehension and near-chance multiparty turn-taking.  
Source: https://aclanthology.org/2026.findings-emnlp.1437/

This is a major gap for a VTuber who needs to follow a group chat rather than simply answer the latest message.

Recommended Social Director behavior:
1. Maintain a short-lived conversation graph of anonymous session-local speaker labels, topics, addressees and unresolved questions.
2. Distinguish speech addressed to STAR from viewer-to-viewer conversation.
3. Treat laughter, acknowledgements and backchannels as context, not automatic interruption commands.
4. Select one useful response opportunity; do not answer every message.
5. Preserve silence when the conversation does not need STAR.
6. Give owner speech and explicit stop/interrupt signals highest priority.
7. Expire stale game reactions and viewer prompts rather than speaking about old events.
8. Keep raw audio and chat out of aggregate telemetry; store only consented, minimal memory.

### Full-Duplex-Bench v3 — spoken tasks and interruptions

FDB-v3 evaluates real human disfluent speech, chained tool use, task accuracy, latency and turn-taking. It is useful for testing whether STAR can keep a task's state while a person corrects or redirects it.  
Sources:
- https://arxiv.org/abs/2604.04847
- https://github.com/DanielLin94144/Full-Duplex-Bench

### New research: Joi-Bench-Task

A paper posted on 2026-11-09 studies coordination between tool execution and spoken conversation. It evaluates whether an agent knows what is running, completed, communicated and still owed after request changes or interruptions. The reported results show substantial omission under interruption.  
Source: https://arxiv.org/abs/2611.12118

**Application to STAR:** represent each long-running task as a small transactional state machine:
- requested;
- accepted;
- running;
- paused;
- superseded;
- completed;
- failed;
- communicated.

When the owner interrupts, STAR should stop or pause the correct task, retain completed facts, invalidate obsolete plans and explicitly report unfinished work. Do not infer task completion from a model's narration.

## 4. Avatar embodiment and audio synchronization

Live2D's Cubism SDK documents how lip-sync parameter IDs are mapped from `.model3.json` and how audio/motion values are applied to those parameters.  
Source: https://docs.live2d.com/en/cubism-sdk-manual/lipsync/

Recommended layers:
- mouth-open envelope from the actual output audio;
- viseme/phoneme track when the selected TTS exposes reliable alignment;
- emotion and expression state from the conversation/game event;
- gaze and attention target from the active speaker or game focus;
- idle/blink/breathing motion on a separate low-cost animation clock.

Drive mouth motion from the playback timeline, not from text-generation time. A queued sentence must not make the avatar's mouth move before the device starts playing it. If audio is cancelled, clear the corresponding viseme queue and return to a listening state.

Do not make expression intensity a proxy for truth or confidence. A cheerful animation should not make an uncertain factual answer appear verified.

## 5. Game mastery: fast reactive control plus slow strategic reasoning

Google DeepMind's SIMA 2 work is a useful research direction because it combines high-level goal reasoning with action in diverse 3D environments and describes self-improvement through task generation and feedback. It is a research system, not a drop-in local model for STAR's 8 GB GPU.  
Source: https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/

Recommended architecture using STAR's existing game systems:

**Reactive controller**
- consumes fresh frames and compact telemetry;
- handles short-horizon movement, aiming, dodging and interactions;
- uses bounded action durations and a key-up watchdog;
- rejects stale observations and expired tickets.

**Strategic planner**
- maintains objectives, map hypotheses, resource plans and team strategy;
- runs asynchronously at a lower priority;
- emits short-lived proposals, never raw key presses;
- must re-check the current frame before any action is considered.

**Skill and evidence layer**
- stores game-version-scoped practice outcomes;
- separates practice evidence from held-out validation;
- records unsafe outcomes as veto evidence;
- tests skills across different maps, seeds and situations;
- retires skills when game version, control mapping, physics or environment fingerprint changes.

STAR already has a signed, versioned `GameplaySkillBank`, a game action gate, closed-loop movement verification and a held-out transfer evaluator. Keep the signer keys outside model/agent processes. A screenshot, model-generated explanation or self-reported win is not independent evidence.

## 6. Roblox Creator: exploration before editing

Roblox's OpenGameEval is a stateful Roblox Studio benchmark. It separates observation tools from editing tools and checks both the edited scene and a simulated play session. The October 2026 paper describes 84 curated tasks; the best reported single-attempt pass rate was 51.7%, while five-of-five consistency was 39.4%. This demonstrates why a single successful run is not enough to establish reliable Studio skill.  
Sources:
- https://github.com/Roblox/open-game-eval
- https://arxiv.org/abs/2610.02563

Recommended Creator workflow:
1. Inspect the DataModel tree, relevant scripts, properties, constraints and dependencies.
2. Save a concise exploration trace.
3. Plan a minimal change.
4. Apply the change only in an isolated test place.
5. Run static Luau checks.
6. Run Studio playtest and executable scene/game checks.
7. Capture screenshots/video for visual review.
8. Repair and rerun the same task.
9. Evaluate on a separate holdout task/scene.
10. Promote the skill only after repeated independent validation and owner review.

OpenGameEval's public README currently documents its hosted evaluation API and required credentials; it also says its `--llm-url` option is not yet supported. Do not assume it can directly call STAR's local endpoint. Reuse the benchmark tasks/annotations in STAR's existing local Studio harness or implement a tested adapter after the API supports it. Never commit Open Cloud keys or external provider keys.

STAR's existing Roblox benchmark and Studio Lab remain the local execution path. OpenGameEval is a complementary external benchmark, not a reason to replace the existing harness.

## 7. OBS and system observability

OBS WebSocket's `GetStats` response exposes active FPS, average frame render time, render-skipped frames and output-skipped frames.  
Source: https://github.com/obsproject/obs-websocket/blob/master/src/requesthandler/RequestHandler_General.cpp

Keep three loss channels separate:
- render/compositor skips — usually GPU/source-composition pressure;
- encoder skips — encoder or CPU/GPU encoding pressure;
- network drops — delivery/uplink pressure.

Correlate these with STAR's CPU/GPU/RAM telemetry and game frame-time samples. A single generic “stream health” number hides the cause and leads to the wrong optimization.

## 8. Audio callback follow-up

PortAudio's callback guidance warns against operations with unbounded duration, including allocation/deallocation, I/O, context switches and mutex operations.  
Source: https://files.portaudio.com/docs/v19-doxydocs-dev/writing_a_callback.html

The current child PR #1128 moves RMS metering away from the PortAudio callback, which is a useful first reduction in callback work. The callback still copies PCM and uses the speaker-buffer lock. A preallocated native single-producer/single-consumer ring buffer is the next possible step only if real Windows profiling demonstrates callback jitter or lock contention. Do not add a native extension based on theory alone.

## 9. Acceptance gates for a real VTuber session

Run a private 60-minute session with a fixed game build, scene, avatar and model configuration. Include quiet periods, busy chat, interruptions, game combat, scene changes and background research.

A candidate passes only if all applicable gates pass:

| Dimension | Required evidence |
|---|---|
| Local inference | first-content p50/p95 and token-level ITL where available |
| Speech | first device output, loopback output and interruption-to-silence |
| Conversation | TurnBench dyadic metrics and MP-Bench-style multiparty review |
| Task continuity | no lost completed work after interruption; unfinished work reported |
| Avatar | mouth/viseme follows actual playback; cancellation clears motion |
| Game | objective success, action safety, fresh-frame compliance and p99 frame-time |
| OBS | render skips, encoder skips and network drops reported separately |
| Resources | CPU, RAM, VRAM, GPU headroom and audio underruns |
| Knowledge | answer accuracy, source freshness and abstention on unsupported claims |

Use paired baseline/candidate trials on the same opportunities. A faster configuration must not win by speaking less, skipping difficult questions, lowering game FPS or dropping audio.

## 9. General knowledge: broaden the benchmark before claiming breadth

The current `star/general_knowledge_benchmark.py` explicitly describes itself as ten public development tasks and says it does not establish model delivery, broad knowledge or a knowledge gain. Keep it as a small artifact-integrity check; do not present it as a general-knowledge benchmark.

Build a layered Knowledge Lab evaluation set:

| Layer | Research benchmark | What STAR should measure |
|---|---|---|
| Stable factual recall | SimpleQA | Short-answer factual accuracy and abstention |
| Misconceptions | TruthfulQA | Reject common false premises instead of echoing them |
| Time-sensitive facts | FreshQA | Detect stale answers, verify current evidence and flag false premises |
| Hard research | BrowseComp | Persistent search, query reformulation, multi-source synthesis and citation support |
| General assistant work | GAIA | Multimodal input, file handling, browsing and multi-step tool use |
| Expert science reasoning | GPQA Diamond | Deep specialist reasoning; keep separate from everyday general knowledge |

Sources:
- SimpleQA: https://openai.com/index/introducing-simpleqa/
- TruthfulQA: https://openai.com/index/truthfulqa/
- FreshQA/FreshLLMs: https://github.com/freshllms/freshqa and https://arxiv.org/abs/2310.03214
- BrowseComp: https://openai.com/index/browsecomp/
- GAIA: https://ai.meta.com/research/publications/gaia-a-benchmark-for-general-ai-assistants/
- GPQA: https://arxiv.org/abs/2311.12022

The source projects have important scope limits. SimpleQA uses short, stable fact questions and does not establish long-form factuality. BrowseComp is intentionally difficult web research, not a representative sample of ordinary conversation. GAIA tests tool-using assistant workflows, not only stored knowledge. GPQA is expert science reasoning, not a broad trivia score. FreshQA requires dated snapshots because answers change.

### Knowledge Lab architecture

1. **Question router:** classify stable fact, current fact, specialist reasoning, research, multimodal or task-execution request.
2. **Evidence retriever:** search approved local indexes and, when enabled, authoritative current sources.
3. **Claim ledger:** store claim, source URL, source date, retrieval time, exact supporting passage span, scope and confidence.
4. **Conflict resolver:** keep competing claims with provenance; do not silently collapse disagreement.
5. **Freshness policy:** set review/expiry windows by domain. API versions, prices, current events and game balance data age faster than mathematics or established history.
6. **Answer planner:** separate known facts, sourced current facts, inference and uncertainty.
7. **Abstention/calibration:** test whether confidence predicts correctness; allow “I could not verify that” as a successful behavior.
8. **Memory promotion:** promote only reviewed, source-backed, versioned facts; retain the source and date so the claim can be rechecked.
9. **Practice loop:** generate spaced-repetition questions from verified knowledge, then score on unseen paraphrases rather than repeating the exact prompt.
10. **Privacy boundary:** do not turn private viewer conversations or owner data into general training examples without explicit permission.

### General-knowledge acceptance

Track accuracy separately by domain and freshness class; citation precision/recall; unsupported-claim rate; false-premise correction; abstention precision; stale-answer rate; multi-hop completion; and performance on paraphrased holdouts. A single aggregate score must not hide a domain regression.

Do not train on hidden test answers. Keep benchmark answer keys outside the model and tool sandbox. Use public development data for iteration, sealed holdouts for final comparisons, and human review for open-ended or ambiguous answers.

## 10. Implementation and verification boundary

This branch adds:
- `StreamingProbe`;
- `summarize_stream_probes`;
- `benchmark_local_model_streaming`;
- synthetic async-stream tests covering first-content timing, chunk gaps, empty streams, bounded concurrency and local-endpoint validation.

The streaming probe measures API content chunks, not individual model tokens and not audible playback. No local model was queried, no RTX 4060 benchmark was run, and no audio device, OBS session, Roblox Studio playtest or livestream was exercised by this change.

The next implementation steps should be:
1. Run this probe against the pinned local llama.cpp build.
2. Compare its summary with GenAI-Perf/SPEED-Bench for token-level validation.
3. Add host-side WASAPI/loopback and OBS GetStats capture to the existing mixed-workload recorder.
4. Add TurnBench scoring to the existing voice evaluation suite.
5. Use MP-Bench-style human-reviewed scenarios for multiparty turn-taking.
6. Build a task-continuity evaluator based on Joi-Bench-Task's state dimensions.
7. Run OpenGameEval tasks through a local Studio adapter only after confirming the integration contract.

No production routing, model, prompt, memory, permissions, avatar, game-control behavior or broadcast setting is changed by this branch.
