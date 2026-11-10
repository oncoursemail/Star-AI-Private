# STAR: Paired Inference Experiments, Generalist Intelligence, Gaming and VTuber Runtime

**Research date:** 2026-11-09
**Status:** Research-backed engineering plan. The paired local inference comparator described below is implemented in this branch; the broader integrations are proposed work, not completed features.

## Executive summary

STAR should become more capable by improving the whole system around its models, not by assuming that a larger model or a higher tokens-per-second number automatically makes it smarter.

The highest-leverage architecture is a set of coordinated loops:

1. **Fast interaction loop:** low-latency perception, short decisions, speech turn-taking, and bounded actions.
2. **Deep reasoning loop:** research, planning, debugging, game strategy, and difficult questions.
3. **Memory and learning loop:** preserve evidence, retrieve only relevant memories, practice, evaluate, and retain only verified improvements.
4. **Creator loop:** inspect a real project, build, run, visually inspect, playtest, repair, and evaluate.
5. **VTuber performance loop:** keep game, inference, audio, avatar, and OBS workloads inside a shared resource budget.

The loops must exchange compact, timestamped evidence rather than dumping every observation into one enormous prompt.

## Implemented in this change

### Paired randomized local inference benchmark

New module: star/inference_paired_benchmark.py
New tests: tests/test_inference_paired_benchmark.py

The comparator:

- Compares two or three explicitly supplied model aliases on one already-running loopback endpoint.
- Sends the same fixed synthetic workload to every model in each matched pair.
- Randomizes model order within each pair using a reproducible seed.
- Warms every model alias before the measured schedule.
- Runs requests sequentially so the benchmark does not introduce its own concurrent-load interference.
- Reports candidate-minus-baseline first-content and end-to-end latency deltas, p50/p95 summaries, faster/tied/slower pair counts, and incomplete pairs.
- Keeps failed requests in incomplete-pair counts rather than silently removing them.
- Stores neither prompt text nor generated output.
- Uses the existing Settings.validate() loopback-only endpoint policy.
- Never changes STAR's active model route or launches a model.

Run from the repository root after starting a local OpenAI-compatible model server:

    python -m star.inference_paired_benchmark \
      --model star-fast \
      --compare-model star-reasoning \
      --repeats-per-workload 2 \
      --seed 20261109 \
      --output paired-inference.json

A third model can be added by repeating --compare-model.

**Interpretation:** negative candidate-minus-baseline deltas mean the candidate was faster in that matched observation. The comparator does not grade answer quality, prove model residency, or isolate GPU kernel time. If the server loads/unloads models on demand, that switching cost is included. Confirm equivalent residency, context, runtime build, and hardware before treating results as steady-state decode comparisons.

## Research findings and architectural recommendations

## 1. Faster inference: measure the user's experience, not one headline number

NVIDIA AIPerf's current metric reference separates per-request measurements from aggregate throughput. Its streaming metrics include time to first token, time to second token, inter-token latency, request latency, output sequence length, and output throughput. Percentiles matter because a low median can hide bad tail latency.

Sources:
- https://docs.nvidia.com/aiperf/reference/ai-perf-metrics-reference
- https://developer.nvidia.com/blog/benchmarking-llm-inference-at-scale-with-aiperf/

STAR's current streaming benchmark intentionally labels its first nonempty client text chunk as **first-content latency**, not tokenizer-level TTFT. This is the honest name: an SSE chunk may contain multiple tokens, and network/chunk scheduling is part of the observation.

Recommended benchmark layers:

| Layer | Measurement | Why it matters |
|---|---|---|
| Client experience | First nonempty content, first audible PCM, full response | What a viewer actually waits for |
| Streaming cadence | Inter-chunk gap p50/p95, silence gaps, cancellation latency | Whether speech feels smooth and interruptible |
| Engine | Prompt tokens/sec, predicted tokens/sec, cache tokens, decode timings | Separates prefill from generation |
| Workload | Requests/sec, concurrency, queue wait, failed/deferred work | Exposes saturation |
| Host | GPU utilization, VRAM peak, CPU, RAM, power, thermals | Explains regressions |
| Stream | Game frame-time p95, OBS dropped frames, audio underruns | Prevents AI speed from damaging the stream |

The llama.cpp server can expose /metrics when enabled and returns timing fields such as prompt processing, predicted tokens, cache reuse, and generation throughput. Capture the server build, flags, model/quantization digest, context size, and metrics-enabled state beside every result. Do not mix server-side timings with client-observed latency as if they were the same clock.

Source: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md

### Caching: where it helps and where it does not

vLLM Automatic Prefix Caching reuses KV state for shared prefixes and can reduce repeated prompt prefill. Its documentation explicitly notes that APC does not speed up the decode phase when generation dominates, and it only helps when prompts share a prefix.

Source: https://docs.vllm.ai/en/latest/features/automatic_prefix_caching/

For STAR:
- Keep stable system instructions and tool schemas byte-stable where possible.
- Separate static project context from dynamic game observations.
- Avoid appending timestamps or volatile telemetry to the front of every prompt.
- Cache retrieval artifacts and verified skill summaries outside the live prompt.
- Do not claim that prefix caching increases raw tokens/sec.

### Model routing should be quality-first

The next routing policy should optimize a constrained Pareto frontier, not simply choose the fastest model:

- First filter by required capability: vision, tools, long context, code, or speech.
- Then require held-out task quality to remain within a preregistered non-inferiority margin.
- Then require latency and resource budgets to pass under the actual workload.
- Keep the owner-selected baseline when evidence is missing, stale, unmatched, or inconclusive.
- Treat a route recommendation as advisory until a trusted host separately approves and binds the actual worker.

A fast model that fails more Luau tasks, misses game hazards, or produces unstable commentary is not an upgrade.

## 2. Long-term memory: preserve evidence and retrieve selectively

Recent research points toward a memory substrate with multiple complementary views rather than a single vector index.

**Agent Zero Memory** proposes:
- an episodic event timeline for what changed and when;
- an entity-event graph for associative, multi-hop links;
- a curated documentary memory for durable facts;
- provenance pointers and citation-locked reading so answers only cite evidence actually opened.

Source: https://arxiv.org/abs/2608.29606

**Zero-Mem** explores structured temporal and entity-context retrieval without spending extra LLM tokens on every memory operation. Its reported results motivate testing deterministic retrieval and indexing before adding an LLM summarization call to every turn.

Source: https://arxiv.org/abs/2607.29377

**Remember When It Matters** treats memory as a selective intervention: a background memory agent decides whether a relevant reminder should be injected, instead of always exposing the entire memory bank. The paper reports better results from selective intervention than always-on memory exposure in its evaluated tasks.

Source: https://arxiv.org/abs/2607.08716

### Recommended STAR memory layers

| Layer | Stored information | Retrieval rule |
|---|---|---|
| Working state | Current task, active game, open subtasks | Very small, expires quickly |
| Episodic ledger | Timestamped observations, actions, outcomes, failures | Retrieve for “what happened?” and continuity |
| Skill memory | Procedures, prerequisites, tested examples, known failure modes | Retrieve when a matching task is detected |
| Semantic knowledge | Curated facts, docs, APIs, source versions | Retrieve for factual and technical questions |
| Preference/persona | Explicit owner preferences and approved character style | Apply only in relevant contexts |
| Hypotheses | Unverified ideas with confidence and expiry | Never present as established fact |

Every durable item should carry source ID, source type, timestamp, project/game scope, confidence, validation state, and a pointer to the original evidence. Updates should append a new version and mark the old version superseded rather than erase history.

An intent gate should skip memory work for self-contained questions. Retrieval should combine lexical and semantic search, then rerank a small set of candidates. A final citation lock should prevent claims from being attributed to a source that was not opened.

## 3. Real-time gaming: separate reflexes from strategy

**Gym-Anything-RT** evaluates 100 generated real-time minigames and can compare the same environment while running, paused, or slowed. Its paper reports a large gap between real-time play and paused play for the evaluated frontier agent. The lesson is that deliberative reasoning alone does not produce real-time skill.

Source: https://arxiv.org/abs/2610.37567

STAR should use three levels:

- **Reflex loop:** current frame, immediate threat, bounded input, action deadline, stop condition.
- **Tactical loop:** route choice, positioning, cooldowns, target priority, short-horizon prediction.
- **Strategic loop:** mechanics, map knowledge, build choices, practice curriculum, post-match analysis.

The reflex loop must not wait for a long reasoning response. The strategic loop must not directly inject unverified actions into the game.

### Learning protocol

1. Inspect the game and identify allowed controls.
2. Build a mechanic map and explicit success/failure signals.
3. Record an immutable baseline on a preregistered scenario set.
4. Practice on training scenarios with action and observation timestamps.
5. Diagnose failures by category (perception, prediction, timing, pathing, execution).
6. Propose one skill update at a time.
7. Compare baseline and candidate on matched held-out scenarios.
8. Keep the change only if it improves success without worsening safety or latency.
9. Test transfer on an unfamiliar map or variant.

Measure win rate, objective completion, survival, reaction delay, action accuracy, invalid actions, recovery time, and transfer performance. Keep human or owner approval for public multiplayer actions and irreversible account actions.

## 4. Game creation: inspect first, then validate the running experience

**OpenGameEval** evaluates agents inside reproducible Roblox Studio sessions. It separates observation tools from editing tools and scores both the edited scene and a simulated play session. Its reported results show that inspection before editing is associated with higher task success.

Sources:
- https://arxiv.org/abs/2610.02563
- https://github.com/Roblox/open-game-eval

**GameDevBench** broadens evaluation across game-development tasks, including visuals, animation, UI, and gameplay.

Source: https://github.com/waynchi/gamedevbench

STAR's creator loop should be:

    Inspect hierarchy and references
      -> write a small plan
      -> edit an isolated test place
      -> run static checks
      -> launch a playtest
      -> capture visual and runtime evidence
      -> compare against acceptance criteria
      -> repair one defect
      -> rerun the same test
      -> run a held-out scenario

A successful compile is not a successful game. Evaluate camera behavior, collision, input, replication, UI layout, animation, sound, performance, and actual playability. Preserve the test place and evidence so a future run can reproduce the result.

## 5. Natural VTuber interaction: full-duplex, context-aware, and interruptible

**Realtime-Venus** describes a full-duplex architecture that keeps perception and conversation active while delegated tasks run asynchronously. Its system separates the live interaction loop from background task execution and returns delegated results to the same conversation.

Source: https://arxiv.org/abs/2609.13814

STAR should follow the same separation:

- Live loop: incremental audio, current game events, turn-taking, short reactions, immediate barge-in.
- Background loop: research, memory retrieval, long reasoning, viewer question preparation, game strategy.
- Return path: background results are checked for freshness and relevance before they can influence the live turn.

The live loop should choose among speak, nonverbal acknowledgement, defer, and silence. It should not narrate every frame. A natural stream needs quiet stretches, contextual humor, short reactions during danger, and longer explanations when the game is calm.

### Windows audio: isolate STAR's voice from the game mix

WASAPI endpoint loopback captures the audio mix played through a rendering endpoint. That mix may include the game, browser, alerts, OBS monitoring, and STAR. It is not proof that STAR herself spoke.

Sources:
- https://learn.microsoft.com/en-us/windows/win32/coreaudio/loopback-recording
- https://learn.microsoft.com/en-us/windows/win32/coreaudio/wasapi

Windows process-loopback activation can include or exclude audio rendered by a specified process and its child-process tree. This is a strong candidate for capturing STAR's TTS process separately from game/OBS audio, subject to a Windows host implementation and real-device tests.

Sources:
- https://learn.microsoft.com/en-us/windows/win32/api/audioclientactivationparams/ne-audioclientactivationparams-audioclient_activation_type
- https://learn.microsoft.com/en-us/windows/win32/api/audioclientactivationparams/ns-audioclientactivationparams-audioclient_process_loopback_params
- https://github.com/microsoft/Windows-classic-samples/tree/main/Samples/ApplicationLoopback

The Windows host should also subscribe to endpoint changes and invalidate old route/calibration evidence when a device disappears or the default endpoint changes. Every audible receipt should identify the process/route, monotonic start and end, and output epoch. A loopback observation is still not a substitute for the host's own PCM submission and device acknowledgement.

### Avatar and broadcast controls

VTube Studio's plugin API can trigger hotkeys, control tracking parameters, and inject custom parameters. The user must enable the API and approve plugins; a granted plugin can control the model, so the integration must be treated as privileged local software.

Sources:
- https://github.com/DenchiSoft/VTubeStudio/wiki
- https://github.com/DenchiSoft/VTubeStudio/wiki/Plugins

OBS WebSocket uses a challenge/salt authentication exchange. Keep it password-protected, bind it to the local machine/network policy, store credentials outside logs, and expose a narrow host allowlist rather than arbitrary OBS RPC to the model.

Sources:
- https://github.com/obsproject/obs-websocket
- https://github.com/obsproject/obs-websocket/blob/master/docs/docs/partials/introduction.md

The character can express excitement, curiosity, frustration, amusement, and affection through a consistent persona and avatar animation. Keep the distinction clear: expressive behavior is a designed AI persona, not evidence of biological human feelings.

## 6. General knowledge and broader capabilities

The knowledge system should be a verified pipeline:

    Discover source
      -> identify publisher/version/date/license
      -> extract facts and procedures
      -> preserve exact source references
      -> index lexical + semantic representations
      -> answer with citations and uncertainty
      -> test application on an unfamiliar task
      -> retain only validated lessons

Priority domains:
- mathematics, science, history, geography, and general factual knowledge;
- programming, operating systems, networking, and security;
- Roblox/Luau, other game engines, game design, and multiplayer systems;
- art direction, UI/UX, Blender, animation, VFX, and audio;
- communication, writing, planning, and research;
- practical computer operation and application workflows.

A capability is not complete because STAR can describe it. It needs a runnable tool path, an explicit permission boundary, a measurable success condition, a failure/recovery path, and an evaluation set.

## 7. Prioritized implementation roadmap

| Priority | Work | Acceptance evidence |
|---|---|---|
| P0 | Run paired model benchmark on the actual STAR host | Same workload, pinned runtime/model identity, randomized paired schedule, p50/p95, failures retained |
| P0 | Add engine timing and host telemetry to benchmark artifacts | Prompt/decode/cache metrics plus GPU/VRAM/CPU/RAM and game/OBS impact |
| P1 | Process-specific WASAPI loopback and endpoint-change observer | STAR-only TTS receipts, device-change invalidation, underrun/recovery tests |
| P1 | Selective provenance-aware memory retrieval | LongMemEval-style temporal/update/abstention tests; citations only from opened evidence |
| P1 | Real-time gaming closed loop | Live-clock success, action deadlines, safe stop, held-out scenario gains |
| P1 | Full-duplex VTuber director | Barge-in, end-of-turn, backchannel, silence, freshness and long-session tests |
| P2 | VTube Studio and OBS adapters | Local authenticated connection, owner-approved plugin, narrow action allowlist |
| P2 | Roblox Studio creator evaluation | Inspection-first tasks, scene checks, playtest checks, visual evidence |
| P2 | General knowledge curriculum | Source attribution, temporal updates, transfer tasks, correction-to-regression tests |

## 8. Release and promotion gates

Do not promote a model or skill because one run was faster or one game was won.

A promotion candidate must have:
- an immutable model/runtime/quantization identity;
- a preregistered task suite and scoring rubric;
- paired baseline/candidate trials;
- a held-out quality non-inferiority check;
- fresh host resource measurements under the intended game/OBS/TTS workload;
- a rollback path and an owner-visible change summary.

For the target 8 GB VRAM gaming machine, protect headroom for the game, OBS, avatar renderer, and TTS. Benchmark CPU offload and CPU TTS only as measured alternatives; they may reduce VRAM pressure but can create CPU contention and worse tail latency.

## 9. Verification status and limitations

Implemented here:
- paired randomized comparator for two or three local model aliases;
- bounded sequential requests and warm-up;
- matched prompts and deterministic seed;
- per-candidate and per-workload paired deltas;
- explicit incomplete-pair accounting;
- offline regression tests.

Not implemented by this change:
- automatic model routing or route promotion;
- answer-quality grading;
- GPU or Windows telemetry collection;
- process-loopback capture;
- VTube Studio or OBS network adapters;
- autonomous gameplay or game editing;
- model training or weight changes.

The benchmark's first-content metric remains a client-observed first nonempty chunk, not engine-token TTFT. The local verification tests use fake streams; the live model and RTX 4060 benchmark must be run on the actual Windows/STAR host before any speed claim is made.


## 10. Local verification for this change

On the STAR Linux development workspace:

- 142 focused tests passed across paired inference, mixed-workload inference, existing inference benchmark, route selection, and proactive response timing.
- Ruff passed for the new implementation and tests.
- Python compilation passed.
- Pyright 1.1.414 reported 0 errors, 0 warnings, and 0 informations across the paired benchmark and the two existing benchmark modules.
- Git whitespace validation passed.
- The CLI help path was exercised successfully.

No live model, RTX 4060, Windows audio, OBS, VTube Studio, or gameplay benchmark was run in this change. GitHub Actions must still run the repository's full offline regression and desktop workflows after publication.

[executed on device: starai (04f6aa98-0095-4f4d-8546-724e7fb588fa)]