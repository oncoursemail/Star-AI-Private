# STAR Research — Local Model Telemetry, Realtime VTuber Quality, and Generalist Learning

**Research date:** 2026-11-11  
**Scope:** A source-backed implementation plan plus a new read-only llama.cpp metrics parser. This is not a claim that Star has become faster, mastered games, or completed a hardware/live-stream integration.

## Executive summary

The most useful next infrastructure step is to measure the entire experience instead of optimizing a single model metric. Star can feel slow even when token generation is fast if queueing, audio endpointing, TTS, device playback, avatar synchronization, game rendering, OBS rendering, or network delivery is the actual bottleneck.

This update adds a small local parser for llama.cpp's documented Prometheus metrics. It distinguishes cumulative counters from current gauges, derives rates only from two snapshots of the same server epoch, and suppresses rates when a counter resets. It does not poll a server, open a network connection, change a model setting, or make scheduler decisions.

The broader recommendation is one evidence-driven runtime with separate fast interaction and background-learning lanes:

- Fast lane: audio capture/playback, interruption response, avatar timing, fresh game observation, and urgent game control.
- Background lane: research, strategic planning, coding, skill consolidation, knowledge retrieval, and game-creator work.
- Shared session ledger: task identity, session epoch, game/build version, observation freshness, memory revision, completion state, and delivery receipts.
- Independent evaluation: model latency, voice quality, conversation-floor quality, game outcome, creator correctness, factuality, and stream health must remain separate scores.

## 1. Repository audit and integration boundary

The current development architecture already contains useful foundations:

| Existing area | Current responsibility | What it does not prove |
|---|---|---|
| STAR streaming inference benchmark | First-content, second-content, request and chunk-cadence measurements | Token-level ITL or a hardware speedup |
| Adaptive QoS | Advisory, owner-enabled workload admission using host measurements | Actual process scheduling or GPU improvement |
| Stream Director | Consent-gated speech-intent arbitration | Microphone capture, ASR, diarization, or OBS delivery |
| Realtime A/B benchmark | Paired analysis of host-supplied audio and frame measurements | That a candidate is safe to deploy automatically |
| Game skill memory / learning ladder | Evidence and practice foundations | General game mastery or verified transfer by itself |
| General Knowledge Lab | Domain curriculum and research plans | That the model has learned or verified every domain |

The new parser is deliberately adjacent to, not inside, the scheduler. llama.cpp server counters do not contain all the host information needed by STAR's QoS policy: game frame time, free VRAM, CPU pressure, audio backlog, and actual device playback. A future Windows/Linux host adapter must collect those signals on a consistent monotonic clock and apply its own permissions and freshness checks.

## 2. llama.cpp metrics: what is available and what to measure

The current llama.cpp server README documents a Prometheus-compatible GET /metrics endpoint. It must be enabled with the server's metrics option. In router mode, the model query parameter is required. The documented metrics include:

| Metric family | Meaning | Interpretation |
|---|---|---|
| Prompt token and prompt-time counters | Prompt work accumulated by the server | Derive interval throughput from same-epoch counter deltas |
| Predicted token and generation-time counters | Generated work accumulated by the server | Derive interval throughput; not per-request latency |
| Prompt and predicted token-rate gauges | Server-reported average rates | Current server view; compare with interval deltas |
| Requests processing / deferred | Current server load gauges | Snapshot state, not cumulative request counts |
| Maximum observed context tokens | High-water mark | Treat as a current high-water value, not a rate |
| Decode calls and busy slots per decode | Decode activity and batch/slot utilization | Useful workload context, not a standalone quality score |
| Speculative draft / accepted token / verification-step counters | Speculative decoding activity | Calculate acceptance from counter deltas, then verify end-to-end latency |
| Accepted tokens by draft position | Labelled per-position cumulative counters | Keep position labels separate; never collapse them into an ambiguous scalar |

The server also documents a /slots endpoint for per-slot processing state. It can be disabled, so a host adapter must detect unsupported endpoints and degrade gracefully. Do not assume that a KV-cache-usage metric exists in every server build; use only the metrics actually documented and returned by the pinned build.

### New code in this branch

- STAR module: star/llama_metrics.py
- Regression tests: tests/test_llama_metrics.py
- Parser: parse_llama_cpp_metrics(text, instance_id, captured_at_ms)
- Interval analysis: compare_llama_cpp_metrics(previous, current)

The parser:
- Accepts bounded Prometheus text only; it performs no HTTP request.
- Whitelists documented llama.cpp metric names and ignores unknown names for version compatibility.
- Validates finite, nonnegative values and integer-valued counters/counts.
- Rejects duplicate scalar series and ambiguous labels.
- Preserves the position label for the per-position speculative counter.
- Separates counters from gauges.
- Requires an opaque server-epoch identifier and monotonic capture time.
- Rejects comparisons across server epochs or reversed timestamps.
- Detects counter resets and suppresses the affected rate instead of emitting a negative or fabricated result.
- Reports speculative acceptance anomalies rather than clamping them.
- Emits aggregate metrics only; it does not retain prompts, completions, model paths, credentials, or user data.

The caller must rotate instance_id whenever the llama-server process or selected model epoch is restarted. A process restart can reset cumulative counters. If the host cannot establish a stable server epoch, it must discard the interval rather than guess.

### Important metric distinctions

- A high speculative acceptance percentage does not prove higher tokens per second. Compare wall-clock request latency and quality under the same offered load.
- A server-wide counter delta is not attributable to one request when multiple requests are concurrent.
- A server's prompt/decode compute-time rate is not the same as end-to-end user-perceived response time.
- A chunk gap is not token-level inter-token latency. Use token-aware server telemetry or AIPerf for token-level comparisons.
- Request processing and deferred gauges should be sampled as state; do not subtract them as if they were cumulative counters.
- The maximum-context high-water mark should not be interpreted as current KV-cache occupancy.

## 3. AIPerf: request-level performance workbench

NVIDIA's current AIPerf documentation lists stable v0.13.0 and documents record, aggregate, and derived metrics. Its streaming metrics include time to first token, time to second token, inter-token latency, inter-chunk latency, and output-token throughput. It also documents speculative-decoding acceptance metrics, audio metrics, and multi-run confidence statistics.

Recommended STAR use:
1. Keep STAR's local synthetic/streaming probe lightweight and private.
2. Add an optional, version-pinned AIPerf runbook for supported local endpoints.
3. Pin the model file hash, quantization, llama.cpp build/flags, prompt set, context length, sampling parameters, server slot count, and concurrency.
4. Separate warm-resident runs from cold model-load runs.
5. Match concurrency to available server slots for normal-load tests; run overload sweeps separately.
6. Run multiple profile repetitions and report variance/confidence intervals.
7. Compare quality and completion success alongside speed. A faster wrong answer is not an intelligence improvement.

For an 8 GB consumer GPU, avoid copying datacenter benchmark results or tuning values. Test the exact model, quantization, context, server build, host RAM, CPU, PCIe path, and simultaneous game/OBS workload.

## 4. Mixed-workload performance protocol

A useful test matrix is:

| Scenario | Active work | Questions answered |
|---|---|---|
| A | Model only, idle desktop | Baseline inference |
| B | Game only | Baseline game frame pacing |
| C | Game + voice input/output | Speech interference and playback latency |
| D | Game + voice + avatar | Animation and audio synchronization |
| E | Game + voice + avatar + OBS | Actual streaming workload |
| F | Full stream + one bounded research task | Background isolation and task continuity |
| G | Full stream + controlled burst of background tasks | Scheduler overload behavior and recovery |

Record these independently:

- AIPerf request-level TTFT, TTST, ITL/ICL, completion latency, throughput, errors, and run-to-run variance.
- llama.cpp counter deltas, current processing/deferred gauges, prompt/decode rates, and speculative acceptance.
- Host CPU utilization, CPU saturation, RAM availability, GPU utilization, VRAM use, clocks, thermals, and power state.
- Game FPS plus frame-time distribution and 1% low, not average FPS alone.
- Speech request-to-first-audible output, playback completion, interruption correctness, and audio underruns.
- OBS render-skipped frames, output-skipped frames, active FPS, render time, output congestion, and network reconnect/drop state.

OBS exposes GetStats and GetStreamStatus through obs-websocket. Keep renderer skips, encoder/output skips, and network drops separate because they indicate different bottlenecks. Capture a baseline at stream start: some OBS counters are cumulative since OBS launched, so a lifetime count is not a per-stream result.

Change one variable per A/B pair. Pre-register the workload and acceptance thresholds. Do not promote a configuration just because a single run is faster. The existing paired realtime benchmark is the right place to enforce minimum sample counts, complete pairs, uninterrupted audio, and a frame-rate non-regression guard.

## 5. Faster inference: experiments in priority order

| Priority | Experiment | Measure | Main risk |
|---|---|---|---|
| 1 | Keep the selected model resident | Cold/warm first-token and reload time | Memory pressure while gaming |
| 2 | Stable prompt prefixes and cache reuse | Prompt processing time and cache-read telemetry | Cache invalidation or misleading hit assumptions |
| 3 | KV-cache type/context sweep | VRAM, context capacity, quality, p95 latency | Quality loss or context regression |
| 4 | Speculative decoding | Acceptance, TTFT/ITL, end-to-end latency | Draft model overhead can erase gains |
| 5 | CPU/GPU layer placement | Decode rate, GPU headroom, game frame time | CPU contention and PCIe transfer cost |
| 6 | Model routing by task complexity | Quality-adjusted latency and escalation rate | Small model silently underperforms |
| 7 | Bounded continuous batching | Throughput and p95 under concurrency | Interactive requests queue behind long work |
| 8 | Context trimming and retrieval | Prompt tokens, factuality, task success | Removing a needed detail |
| 9 | Background admission and cancellation | Voice/game deadlines and queue age | Stale work continuing after context changes |

Do not change all these at once. First establish the baseline. Then compare one exact model/server configuration at a time. Keep reasoning depth, model quality, and user-facing response length in the evaluation so a shorter or less capable answer is not mislabeled as a speed win.

## 6. Natural VTuber streaming: timing, social awareness, and delivery

A natural stream requires more than low-latency TTS. The runtime should understand when to listen, when a person has finished, when an interruption is real, who is being addressed, and when silence is the right response.

LiveKit's turn-detection documentation distinguishes voice activity detection from end-of-turn detection and interruption handling. Its documented endpointing defaults differ when an audio turn detector is used. These defaults are useful references, not values to copy blindly into STAR. Calibrate on disjoint recordings and measure false cutoffs, late responses, missed interruptions, and correct silence by language and conversational situation.

Recommended pipeline:

1. Capture audio in a dedicated realtime worker; never run an LLM, network call, disk write, or unbounded vision operation in the device callback.
2. Use VAD for speech presence, then turn detection for end-of-turn confidence.
3. Add speaker attribution and addressee detection for multiparty streams. Diarization confidence must be explicit; do not invent a speaker identity.
4. Give the Stream Director a compact, evidence-labelled proposal rather than raw untrusted chat instructions.
5. Keep an interruption-safe task ledger. If a viewer interrupts, preserve the previous task's ID, progress, deadline, and last verified state.
6. Generate speech incrementally, but allow a newer owner interruption or urgent event to cancel stale speech.
7. Synchronize avatar mouth movement to the audio actually being played, not merely to text generation.
8. Track generated, queued, device-output, OBS-output, and remote-delivery stages separately. Local playback does not prove a viewer heard it.

For character quality, maintain a stable persona bible and a small, relevant autobiographical memory retrieval. Measure persona consistency separately from conversational usefulness, factual grounding, and turn-taking. Avoid forced chatter, repetitive catchphrases, fake claims of human experience, or exaggerated emotion. Star can be expressive and socially warm while remaining transparent that she is an AI.

Suggested streaming quality lanes:
- Turn timing and correct waiting.
- Multiparty speaker/addressee attribution.
- Interruption precision and false-interruption rate.
- Spoken-task completion and correction recovery.
- Prosody, volume, and voice naturalness.
- Avatar/audio synchronization.
- Groundedness to current game and conversation evidence.
- Silence preservation and viewer response appropriateness.

## 7. Game mastery: from screenshots to verified reusable skills

Research anchors:

- Google DeepMind's SIMA 2 demonstrates language-guided interaction, reasoning, and learning in virtual 3D worlds. Treat it as a research direction, not a drop-in package for STAR.
- Voyager demonstrates an automatic curriculum, an executable skill library, and feedback-driven skill improvement in Minecraft. The transferable lesson is reusable skills with explicit preconditions and environment feedback.
- Cradle explores general computer control through screenshots and keyboard/mouse actions. It is a useful fallback model for games without a supported structured API, but each game still needs calibration and a safe action boundary.

Recommended STAR gaming architecture:

| Layer | Responsibility |
|---|---|
| Perception | Fresh screenshots, UI, audio cues, and structured game state when available |
| Reactive controller | Short-horizon movement, aiming, dodging, interaction, and recovery |
| Strategic planner | Objectives, map routes, inventory, team strategy, and long-horizon goals |
| Skill registry | Versioned, composable, executable skills |
| Evaluator | Independent scoring of outcomes and constraints |
| Curriculum | Select the next practice task from measured weaknesses |
| Transfer evaluator | Test a skill on held-out maps, modes, and game versions |

Every stored skill should contain:
- Stable skill ID and version.
- Game adapter and compatible game/build versions.
- Preconditions and required observations.
- Bounded action sequence or policy reference.
- Expected state transition and postconditions.
- Failure modes and recovery behavior.
- Safety classification and action permissions.
- Evidence count, success rate, uncertainty, and last validation time.
- Dependencies on other skills.
- Expiry or revalidation trigger.

Do not call a skill mastered after one success. Require repeated successes, a held-out scenario, and independent outcome evidence. Test transfer separately from in-game practice. A navigation skill may transfer between similar maps; weapon timing, physics, and key bindings often do not.

## 8. Roblox and game creation

The official Roblox Studio MCP server runs locally over stdio and can inspect/edit a connected Studio session. Roblox documents support for multiple Studio instances, with a studio_id supplied to target each instance. This is especially useful for STAR's planned Studio Lab: separate projects or test places can be assigned to separate Studio instances, but agents must not race edits or assume that Edit-mode operations work while the same Studio window is occupied by Play mode.

The Open Cloud MCP permission model is per game and per person. The user controls scopes; the client cannot grant itself additional permissions. Full access includes scopes that can affect live games, players, monetization, secrets, or publishing. Keep those scopes out of unattended building and test loops.

Recommended Creator loop:
1. Inspect the place, DataModel, scripts, assets, dependencies, and current game version.
2. Produce a plan with measurable acceptance criteria before editing.
3. Build small, reversible changes in a disposable test place.
4. Run Luau static analysis and project-specific tests.
5. Playtest with deterministic scenarios and a test character.
6. Capture structured logs, assertions, screenshots, and actual outcome evidence.
7. Repair the smallest failing unit and rerun the original regression plus neighboring scenarios.
8. Have a separate visual/gameplay review compare the result with the design brief.
9. Keep publishing, monetization, live DataStore writes, player consequences, and credential operations as explicit owner-approved actions.

The same inspect → plan → build → test → observe → repair → review discipline should later extend to Blender, animation, VFX, audio, lighting, UI, and other engines.

## 9. General knowledge and continual learning

AgentCL argues that memory should be tested on task streams where earlier skills are genuinely reusable, alongside independent tasks that reveal interference. MemTrace emphasizes that old execution evidence can become invalid after the repository or environment changes.

Apply both lessons to STAR:
- Store source, date, author, claim, confidence, and verification status with factual memories.
- Store skills separately from facts and episodes.
- Attach repository/game/build fingerprints to execution evidence.
- Revalidate old evidence before using it to edit a project or control a game.
- Keep development tasks, dependent transfer tasks, and independent interference probes separate.
- Compare memory-off and memory-on arms with the same model, prompt, tools, context budget, grader, and task order.
- Promote a lesson only after external evidence; self-critique alone is not a reliable grader.
- Keep knowledge freshness checks for fast-changing domains such as APIs, software versions, platform policies, and current events.

A useful general-knowledge curriculum includes mathematics, science, history, geography, computing, engineering, art, music, languages, psychology, economics, and game design. Each domain needs source-grounded lessons, independent questions, counterexamples, and practical transfer tasks. Store uncertainty and date-sensitive claims instead of presenting every retrieved passage as timeless fact.

## 10. Phased implementation roadmap

| Phase | Deliverable | Acceptance evidence |
|---|---|---|
| 1 | Read-only llama.cpp metrics parser | Offline parser tests, reset tests, bounded input tests |
| 2 | Optional host polling adapter | Loopback/private endpoint validation, auth kept outside parser, timeout and cancellation tests |
| 3 | Unified performance dashboard | Model, host, game, audio, and OBS signals with independent clocks/epochs |
| 4 | Mixed-workload benchmark harness | Repeated paired runs, confidence intervals, no audio loss, frame pacing guard |
| 5 | Multiparty social director | Disjoint speaker/addressee/turn-taking evaluation |
| 6 | Task continuity ledger | Interrupt/resume tests with stale-result rejection |
| 7 | Game skill transfer | Held-out maps/modes and outcome verification |
| 8 | Studio Lab | Multi-Studio routing, isolated test places, rollback, owner-gated publishing |
| 9 | Knowledge and memory improvement | Source-grounded holdouts, interference probes, stale-evidence rejection |
| 10 | 60-minute private stream rehearsal | Voice, avatar, gameplay, OBS, task continuity, and resource stability together |

## 11. 60-minute private streaming acceptance test

Run a private rehearsal, not a public broadcast:

- Start with a known game and a version-pinned model/server configuration.
- Ask Star to learn an unfamiliar mechanic using an allowed test environment.
- Have two or more test viewers converse with one another and address Star intermittently.
- Include a real interruption while Star is mid-sentence and while she is doing background research.
- Confirm the current utterance stops cleanly, the interruption is handled, and the original task resumes from a verified checkpoint.
- Trigger game success, danger, failure, and ambiguous visual events.
- Confirm she only describes what the current evidence supports.
- Verify avatar lip-sync follows playback and stops when playback is cancelled.
- Run one bounded background research/creator task and verify it cannot starve the live audio/game lane.
- Capture game frame-time percentiles, audio stage timestamps, OBS render/output/network counters, model metrics, and resource use.
- Repeat the same scenario with one candidate optimization and compare paired outcomes.

Pass criteria must be set before the run. At minimum: no lost or duplicated speech, no stale task result spoken, no unauthorized game/publish action, no sustained game/OBS regression beyond the declared tolerance, and a verified completion record for every task that Star claims to have finished.

## Sources

1. llama.cpp server README — /metrics, /slots, router-mode model selection, documented counters/gauges and speculative-decoding counters: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md
2. NVIDIA AIPerf v0.13.0 metrics reference — streaming, token, speculative-decoding, audio and multi-run metrics: https://docs.nvidia.com/aiperf/reference/ai-perf-metrics-reference
3. LiveKit turn detector documentation — VAD, endpointing, dynamic delays, interruption handling and language support: https://docs.livekit.io/agents/logic/turns/turn-detector/
4. OBS obs-websocket protocol — GetStats, GetStreamStatus, render/output counters and session metrics: https://github.com/obsproject/obs-websocket
5. Roblox Studio MCP documentation — local stdio integration, multiple Studio instances and studio_id routing: https://create.roblox.com/docs/studio/mcp
6. Roblox Open Cloud with Studio MCP — per-game/per-person scopes and explicit permission ownership: https://create.roblox.com/docs/studio/mcp-open-cloud
7. AgentCL, Toward Rigorous Evaluation of Continual Learning in Language Agents (2026): https://arxiv.org/abs/2606.02461
8. MemTrace, State-Consistent Memory for Long-Horizon Coding Agents (2026-10-04): https://arxiv.org/abs/2610.04838
9. SkillLearnBench, Benchmarking Continual Learning Methods for Agent Skill Generation (2026-04-22): https://arxiv.org/abs/2604.20087
10. SIMA 2, Google DeepMind (2025-11-13): https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/
11. Voyager, An Open-Ended Embodied Agent with Large Language Models (NeurIPS 2023): https://arxiv.org/abs/2305.16291
12. Cradle general computer control framework: https://github.com/BAAI-Agents/Cradle

## Verification boundary

The parser and its tests are committed to a development branch. Local scratch validation ran 15 pytest cases and Python compilation successfully. Ruff was not installed in the scratch environment. GitHub Actions remains the repository-level type/lint/test gate.

No llama.cpp server was polled, no model was run, no GPU was benchmarked, no Windows audio/OBS/VTube Studio/Roblox Studio session was exercised, and no public stream was started. No inference route, model weights, prompt, memory policy, avatar, OBS setting, game-control permission, or production default was changed.
