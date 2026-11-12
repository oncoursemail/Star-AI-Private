# STAR Research: Evidence-Bounded Streaming Bottleneck Triage

**Research date:** 2026-11-11  
**Implementation:** read-only diagnostic layer over the existing rehearsal evaluator and causal trace profiler  
**Status:** offline analysis; no runtime tuning or device integration

## Executive summary

STAR already has three useful pieces in its current development chain:

1. A bounded rehearsal evaluator that distinguishes PASS, FAIL and INCONCLUSIVE quality gates.
2. A privacy-minimal stream recorder that collects host-supplied latency, frame, audio, OBS, avatar, turn-taking and held-out skill measurements.
3. A causal trace ledger and profiler that distinguish inclusive span duration, direct-child coverage, exclusive wall time and parallel overlap.

The missing piece is a disciplined bridge from a failed quality gate to the next engineering experiment.

This update adds that bridge. It does not add another agent, scheduler, memory store or telemetry collector. It combines the existing evidence into a bounded investigation plan, keeps OBS render and output losses separate, ranks only the configured failures, and refuses to call a co-occurring trace span the cause of a session-level regression.

The purpose is to shorten the diagnose → experiment → verify loop without allowing a diagnostic heuristic to rewrite live settings.

## 1. New implementation

### Files

- star/stream_diagnostics.py
- tests/test_stream_diagnostics.py

### Input

The function accepts:

- one aggregate rehearsal snapshot;
- the existing operator-supplied RehearsalLimits;
- optionally one AgentTrace snapshot;
- the host-supplied trace_run_id that must match the rehearsal run_id;
- optional operator-supplied per-component exclusive-time budgets;
- a bounded maximum number of diagnosis entries.

The trace/rehearsal run-ID match is an assertion made by trusted host code. It is not a cryptographic attestation. The report labels the relationship as host-asserted and never upgrades it to authenticated provenance.

### Output

The report contains:

- overall configured rehearsal status;
- exact configured gate results;
- evidence gaps for INCONCLUSIVE gates;
- trace health and completed/open/failed span counts;
- root child coverage and unattributed wall-time fraction;
- per-component inclusive and exclusive p95 values;
- optional operator-budget status;
- one recommended next experiment for each failed gate;
- a bounded list of candidate component observations.

It deliberately omits trace IDs, span IDs, event attributes, prompt content, transcripts, viewer identifiers, audio, screenshots and model outputs.

## 2. Why this bridge matters

A stream can fail in several different places that look similar to the viewer:

- The model starts generating late.
- Retrieval or tool work delays first content.
- TTS takes too long to produce its first chunk.
- Audio is queued but the device has not played it.
- The avatar updates on a different clock from audible playback.
- The game misses frame deadlines.
- OBS misses render deadlines.
- The encoder or network misses output deadlines.

A single end-to-end number cannot distinguish these stages.

The new diagnostic maps each failed gate to a small set of components worth inspecting first. The map is intentionally called an investigation route, not a causal graph.

## 3. Statistical rules that prevent false diagnoses

### Do not subtract unrelated percentiles

NVIDIA AIPerf reports Time to First Token, Inter Token Latency and Request Latency as separate measurements. ITL describes steady-state token generation after the first-token delay; it is not a substitute for TTFT.

Reference:
- https://docs.nvidia.com/aiperf/dev/reference/ai-perf-metrics-reference
- https://docs.nvidia.com/aiperf/getting-started/ai-perf-comprehensive-llm-benchmarking

For STAR, first-content latency and first-audible latency are also different distributions. Subtracting their p95 values does not produce the p95 of the content-to-audio interval. The correct next step is to retain paired per-turn stage timestamps on one monotonic clock and compute the interval per turn before summarizing it.

This diagnostic does not subtract those percentiles.

### Inclusive time is not additive

OpenTelemetry traces model operations as spans with start/end timestamps and parent relationships. Parent spans often contain child spans; concurrent children can overlap.

Reference:
- https://opentelemetry.io/docs/concepts/signals/traces/

STAR's profiler reports inclusive duration, child coverage, overlap and exclusive time separately. The diagnostic uses exclusive p95 only as a component-level observation. It does not sum inclusive durations, invent a critical path, or interpret unattributed root time as idle CPU time.

### A component budget is an operator hypothesis

Different devices, games, encoders, audio devices, model sizes and concurrency levels need different budgets. No universal TTS, inference, frame-time or avatar-sync threshold is hard-coded.

If an operator supplies a component budget, the report marks the observed component exclusive p95 as OVER_BUDGET or WITHIN_BUDGET. That status is not a production failure gate and does not change runtime configuration.

## 4. Gate-to-experiment playbook

| Failed gate | First investigation route | Next controlled experiment |
| --- | --- | --- |
| First-content p95 | Scheduler, retrieval, memory, model, network | Paired fixed-prompt trial with queue, retrieval, prefill, decode and tool stages separated |
| First-audible p95 | Scheduler, voice, TTS, audio, avatar | Timestamp first content, first TTS chunk, queue submission and device-confirmed playback |
| Game-frame p99 | Game, desktop, OBS, scheduler | Repeat the same scene while enabling voice, vision and background work one at a time |
| Avatar-sync p95 | Avatar, audio, voice | Compare playback-clock timestamps with actual avatar parameter application |
| Audio underruns | Audio, voice, scheduler | Fixed speech workload with device callback and underrun counters |
| OBS render skips | OBS, game, desktop | Compare render lag with frame timing and GPU headroom |
| OBS output skips | OBS, network | Separate encoder/network/output behavior from rendering |
| Turn precision/recall | Voice, audio, runtime | Held-out human-labelled direct-address, backchannel, side-conversation and interruption cases |
| Task recovery | Runtime, memory, tool | Inject interruptions at known checkpoints and verify revision/freshness/exactly-once effects |
| Duplicate speech | Voice, audio, runtime | Inject lost playback acknowledgements and planner restarts |
| Skill transfer | Game, memory, tool | Evaluate a learned mechanic on unseen maps or games with independent outcome labels |

The experiment should change one factor at a time. Keep model revision, quantization, prompt, game scene, capture resolution, encoder, audio device and workload fixed unless that item is the variable being tested.

## 5. Natural VTuber streaming: quality and timing are separate

### Full-Duplex-Bench v3

The benchmark profile describes 100 human-recorded spoken requests across 79 scenarios, 12 speakers and four domains. It scores task/tool correctness, latency and turn-taking rather than treating voice realism as one scalar.

Reference:
- https://www.full-duplex.ai/benchmarks/fdb-v3

### MP-Bench

MP-Bench evaluates active participation in multi-party conversation. Its reported results show that group conversation comprehension and turn-taking remain difficult for evaluated voice agents.

Reference:
- https://aclanthology.org/2026.findings-emnlp.1437/

### LiveKit adaptive interruption handling

LiveKit documents an adaptive interruption model that distinguishes true barge-ins from short backchannels such as acknowledgements. It also documents boundary cooldowns and false-interruption recovery behavior.

References:
- https://docs.livekit.io/agents/logic/turns/adaptive-interruption-handling/
- https://docs.livekit.io/agents/logic/turns/tuning/

STAR should evaluate at least five separate behaviors:

1. Respond to a direct question.
2. Avoid replying to a viewer-to-viewer side conversation.
3. Avoid interrupting a short acknowledgement.
4. Yield to a genuine interruption.
5. Resume only if the original thought is still relevant and was not already heard.

A high turn precision score does not prove natural timing. A low first-audible latency does not prove that the response was socially appropriate. Keep these gates separate.

## 6. Gaming and creator intelligence

### OpenGameEval

OpenGameEval runs agents inside reproducible Roblox Studio sessions. It separates observation tools from editing tools and evaluates both scene state and simulated play. The paper reports 84 human-curated tasks and finds that inspection behavior is associated with better task success in its evaluated setting.

References:
- https://arxiv.org/abs/2610.02563
- https://github.com/Roblox/open-game-eval

STAR implication: a creator agent should inspect the DataModel and relevant objects before editing, then run executable scene checks and gameplay tests. A generated script or successful file write is not proof that the game works.

### GameDevBench

GameDevBench evaluates multimodal game-development work in Godot, including gameplay logic, UI, 2D/3D graphics and animation. Its project reports that visual feedback can improve performance on multimodal tasks.

Reference:
- https://github.com/waynchi/gamedevbench

STAR implication: keep code correctness and visual/runtime correctness as separate evidence lanes. Use screenshots or runtime video only in a controlled local evaluation harness, not as free-form telemetry attached to every trace.

### Game mastery

For player skills, use held-out maps, different starting states and changed objectives. A technique that succeeds on the same practice seed may be memorization, not transferable mastery. The diagnostic therefore treats held-out skill transfer as a separate gate from practice success.

## 7. Local inference: optimize the user-visible path

Use matched workload trials and keep the following measurements distinct:

- queue wait;
- prompt prefill;
- first-content latency;
- inter-token latency;
- full response latency;
- TTS first-chunk latency;
- audio queue delay;
- device-confirmed first-audible latency.

AIPerf documents TTFT, ITL, request latency and throughput as separate metrics. The same separation should be preserved in STAR's local llama.cpp benchmarks.

Do not select a quantization, speculative-decoding draft model, context limit, GPU offload layer count or concurrency level from token/s alone. Require paired quality and speed evidence, and test under the full stream workload.

Recommended workload matrix:

1. inference alone;
2. game alone;
3. voice alone;
4. game plus voice;
5. game plus voice plus avatar;
6. OBS plus game plus voice;
7. full stream plus bounded background agents.

A candidate is not a speed improvement if it raises tokens/s but worsens first-audible p95, game frame p99, audio underruns, OBS skips or held-out task quality.

## 8. Safe integration boundary

This diagnostic is deliberately read-only:

- no model calls;
- no shell execution;
- no network requests;
- no OBS or VTube Studio control;
- no device polling;
- no audio or screen capture;
- no game input;
- no memory writes;
- no model routing or scheduler changes;
- no automatic promotion or rollback.

The trace is an observation record, never an authorization token. The model must not be able to call the diagnostic with forged host evidence and then use its output to grant itself permissions.

## 9. Acceptance plan

### Offline acceptance

- Every configured gate is preserved exactly from the existing evaluator.
- FAIL produces a bounded investigation entry.
- INCONCLUSIVE produces an evidence gap, not a failure or pass.
- Missing trace data never creates component attribution.
- Mismatched run IDs are rejected.
- Open spans remain open and receive no fabricated duration.
- Private trace attributes and identifiers do not appear in the report.
- Operator budgets are strictly validated and never auto-applied.
- Diagnoses are deterministically ordered and bounded.

### Windows acceptance still required

On the actual target PC, connect trusted host adapters for:

- llama.cpp request-stage timing;
- TTS chunk timing;
- device-confirmed audio playback;
- avatar parameter application;
- game frame presentation;
- OBS render and output counters;
- CPU, RAM, VRAM and GPU telemetry.

Run the private rehearsal matrix and compare baseline/candidate with matched scenes and prompts. Retain failed and aborted runs. Do not claim a speedup or intelligence gain until the same workload shows a repeatable quality-preserving improvement.

## 10. Recommended next milestones

1. Finish and merge the existing trace, evaluator and recorder stack only after all required CI checks pass.
2. Add trusted Windows adapters that correlate one rehearsal run with its request/session traces.
3. Build a paired baseline/candidate experiment runner with fixed workload identity and randomized order.
4. Add confidence intervals and repeatability checks for session-level metrics.
5. Connect the diagnostic report to a human-readable performance panel.
6. Use the report to select one bounded optimization experiment at a time.
7. Add held-out gaming and creator evaluations to the same private rehearsal evidence package.

## References

- OpenTelemetry Traces: https://opentelemetry.io/docs/concepts/signals/traces/
- NVIDIA AIPerf metrics: https://docs.nvidia.com/aiperf/dev/reference/ai-perf-metrics-reference
- NVIDIA AIPerf LLM benchmarking: https://docs.nvidia.com/aiperf/getting-started/ai-perf-comprehensive-llm-benchmarking
- Full-Duplex-Bench v3: https://www.full-duplex.ai/benchmarks/fdb-v3
- MP-Bench: https://aclanthology.org/2026.findings-emnlp.1437/
- LiveKit adaptive interruption handling: https://docs.livekit.io/agents/logic/turns/adaptive-interruption-handling/
- LiveKit turn-taking tuning: https://docs.livekit.io/agents/logic/turns/tuning/
- OpenGameEval paper: https://arxiv.org/abs/2610.02563
- OpenGameEval repository: https://github.com/Roblox/open-game-eval
- GameDevBench repository: https://github.com/waynchi/gamedevbench
