# STAR Research — Paired Intelligence, Latency and Streaming Quality Evaluation

**Date:** 2026-11-12  
**Status:** Research and implementation proposal attached to draft PR #1143  
**Scope:** Local inference, voice/VTuber streaming, gaming, game creation, continual learning and general knowledge.

## Executive decision

STAR should stop treating "faster", "smarter", and "more natural" as independent claims. Every runtime/model/agent change should be evaluated on matched tasks under the same hardware and workload conditions, with an explicit quality non-inferiority gate and streaming guardrails.

This PR adds a pure, content-free paired experiment evaluator. It does not run benchmarks, call a model, change routing, promote models, or control the stream. It gives the existing runtime and future Windows host adapter a strict way to decide whether an experiment has enough evidence for human review.

The central rule is:

> A candidate is an improvement only when it is measurably faster, independently evaluated quality is not meaningfully worse, and configured gameplay/audio guardrails do not regress.

An inconclusive result is not a pass.

## 1. Repository audit and current product boundary

The repository README on main describes STAR v1.0.0 as a Windows 11 chat-first application with:
- local llama.cpp inference and an optional self-hosted Linux server;
- Roblox-focused knowledge, development tools and opt-in Studio access;
- image generation and opt-in web search;
- server-side night school with a paired statistical lesson gate;
- basic optional voice calls, while the warmer Star voice and fuller voice experience remain marked "coming soon";
- Studio Lab and end-to-end Blender driving marked "coming soon".

The README explicitly warns that open PRs, CI artifacts and passing tests do not mean a feature is in the installer. This PR therefore does not change product claims or the v1.0 installer.

Relevant architecture:
- star/providers.py, star/local_runtime.py, star/brain_setup.py: provider and local-model path.
- star/stream_load_governor.py, star/stream_workload_admission.py, star/stream_workload_runtime.py: opt-in stream pressure and abstract resource admission.
- star/stream_rehearsal_recorder.py, star/stream_rehearsal_eval.py, star/stream_diagnostics.py: trusted host measurement boundary and offline rehearsal evaluation.
- star/stream_continuity.py: disabled-by-default owner-approved cross-session practice continuity.
- star/agent.py, star/lessons.py, server/: tool orchestration and reviewed learning loop.

The new evaluator is deliberately independent of model providers and runtime scheduling. It can be integrated later without changing v1.0 defaults.

## 2. Research findings

### 2.1 llama.cpp: benchmark the server under the intended concurrency

The upstream llama.cpp server benchmark uses k6 with Server-Sent Events and supports a configurable number of concurrent virtual users. Its example starts llama-server with continuous batching, metrics, a configured parallel slot count, batch size and context size. The benchmark reports tokens/second, prompt and completion token counts, truncation rate and stop rate; it can compare client metrics with the server's /metrics endpoint.

Source: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/README.md

Implications for STAR:
- do not increase --parallel by guesswork;
- match client concurrency to server slots and actual simultaneous workloads;
- keep model, quantization, context, prompt distribution, output cap and warm-up identical in paired runs;
- record prompt and decode performance separately;
- track truncation and errors so a fast but incomplete response is not called an improvement;
- run both idle inference and mixed streaming/game workloads.

### 2.2 OpenTelemetry: keep model-server and client timing distinct

The GenAI semantic conventions distinguish client operation duration and token usage from server request duration, time-to-first-token and time-per-output-token. The conventions are still marked development, so STAR should record its schema/version and avoid hard-coding unstable attribute names into persisted user data.

Source: https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai-metrics.md

Implications:
- first token is not first audible speech;
- model decode time is not end-to-end response time;
- a tool/agent workflow needs separate spans for model, retrieval and tool stages;
- token counts should only be reported when supplied or reliably counted;
- do not infer output tokens from whitespace splitting.

### 2.3 LiveKit: conversational naturalness is turn management, not just TTS quality

LiveKit's current turn documentation describes semantic/audio turn detection alongside VAD, adaptive interruption handling, dynamic endpointing and interruption recovery. It also notes that VAD-only can be useful when minimum latency is the priority or language coverage is needed.

Source: https://docs.livekit.io/agents/logic/turns/

Implications for STAR's future Social/Voice Brain:
- treat "someone made a sound" separately from "someone is taking the floor";
- allow short acknowledgements without repeatedly cutting off the avatar;
- use semantic end-of-turn when natural phrasing matters;
- maintain a low-latency fallback when the turn detector is unavailable;
- truncate conversational history to the portion of speech actually heard after interruption;
- measure turn precision/recall and false interruption rate with labeled rehearsal scenarios.

Do not add a mandatory LiveKit dependency in this PR. The design pattern can be implemented around STAR's existing voice path or evaluated in an isolated adapter.

### 2.4 Recuris: working memory should guide skill retrieval

Recuris proposes separating task-focused Working Memory from accumulated Experiential Memory. Working Memory tracks current task progress and guides which skills to retrieve; validated execution evidence then supports bounded updates to skill memory.

Source: https://arxiv.org/abs/2608.24876

Implications for STAR:
- keep current task state compact and separate from the entire history;
- retrieve a skill only when it matches the current objective and environment;
- store evidence and known failure conditions with each skill;
- update skills through a fixed evaluator and held-out tests;
- never let a candidate rewrite its own grader or acceptance threshold.

The paper's reported benchmark gains are results from its own evaluated systems, not a prediction of STAR performance.

### 2.5 AgentCL: measure transfer and interference separately

AgentCL constructs task streams where earlier solutions are intentionally reusable, and contrasts them with task streams where reuse is not guaranteed. It emphasizes both transfer and memory-induced degradation.

Source: https://arxiv.org/abs/2606.02461

Implications for STAR:
- build compositional Roblox/game-development curricula, not only random task lists;
- test whether a learned mechanic transfers to a new game/version;
- include unrelated-task controls to detect harmful overgeneralization;
- track old-skill retention and new-skill acquisition separately;
- do not treat recall accuracy as proof of procedural competence.

## 3. New implementation contract

File: star/stream_experiment_eval.py

The evaluator accepts only bounded, content-free paired observations:
- opaque pair, task and environment identifiers;
- baseline/candidate variant;
- independent quality evidence source: human, held-out test or tool assertion;
- normalized quality score;
- optional first-content, first-audible, inter-token and end-to-end latency;
- optional game frame-time p99;
- optional audio underrun and playback chunk counts.

It rejects:
- duplicate baseline/candidate entries;
- incomplete pairs;
- mismatched task, environment or quality evidence within a pair;
- missing primary latency;
- non-finite or unbounded metrics;
- model self-judging as the quality evidence source;
- malformed audio counters;
- unbounded observation lists.

It computes:
- paired candidate/baseline latency ratios (below 1.0 is faster);
- candidate-minus-baseline quality deltas;
- deterministic paired bootstrap confidence intervals;
- optional game frame-time and audio underrun guardrails.

Decision states:
- IMPROVED: speed is better, quality is non-inferior within the predeclared margin, and every configured guardrail passes;
- REGRESSION: at least one gate confidently fails;
- INCONCLUSIVE: sample count is too small, evidence is incomplete, or a confidence interval overlaps the decision boundary.

No decision triggers model promotion or changes a runtime setting.

## 4. Experiment protocol for STAR

### 4.1 Local inference

Run matched baseline/candidate trials with:
- same model family and exact model artifact unless model change is the variable;
- same quantization, context size, prompt set and output token ceiling;
- same llama.cpp build and server flags;
- same client concurrency and warm-up;
- randomized or counterbalanced A/B order;
- identical background load.

Capture:
- first-content latency;
- first-audible latency when voice is enabled;
- inter-token latency;
- full request duration;
- input/output tokens from server usage;
- truncation/error rate;
- CPU/RAM/VRAM peaks from a trusted host adapter.

Run a single-user benchmark and a mixed workload benchmark. Never infer a win from aggregate tokens/second alone.

### 4.2 Quality and intelligence

Use a frozen task set with a blind holdout:
- factual answer correctness with source support;
- multi-step reasoning with executable or independently checkable answers;
- tool selection and tool result correctness;
- Roblox Luau compile/analyzer/runtime outcomes;
- game-development task completion in a reproducible engine session;
- held-out skill transfer to a related but unseen game/task;
- unrelated-task controls to detect memory interference.

Use human labels, deterministic tests or independently defined held-out checks. A model may provide a secondary critique, but it cannot be the sole authority for its own quality score.

### 4.3 Streaming and VTuber rehearsal

For a paired run, hold the game scene, OBS settings, encoder, audio device, avatar model, voice configuration and viewer-simulation script constant.

Measure separately:
- model first-content latency;
- TTS first-chunk latency;
- actual playback acknowledgement;
- avatar mouth/audio synchronization;
- game frame-time p95/p99;
- OBS render skips;
- OBS output skips;
- audio underrun rate;
- turn precision/recall;
- false interruptions and successful recovery;
- duplicate audible speech.

Do not subtract unrelated p95 values to estimate a pipeline stage. Record per-request timestamps and derive paired end-to-end values from the same request.

### 4.4 Gaming and skill learning

Use two loops:
- fast loop: visual observation, immediate action, safety checks and current-state update;
- strategic loop: objectives, route planning, memory retrieval, mechanic hypotheses and post-run analysis.

The strategic loop must not block the fast control loop. A game skill is not promoted because the agent describes a successful strategy: it must pass repeatable trials and held-out transfer tasks.

Use a sandbox/test place, bounded actions, owner-approved game access and explicit stop conditions. Do not use automation against games where it violates rules or harms other players.

### 4.5 General knowledge

Maintain source-backed knowledge cards with:
- claim/procedure;
- source URL and publication date;
- retrieval date;
- confidence and scope;
- contradictions and expiry/review policy;
- related task/skill;
- a held-out application question.

Evaluate both factual recall and the ability to apply knowledge to a new task. Keep rapidly changing facts separate from stable foundational knowledge.

## 5. Statistical and operational rules

1. Predeclare the primary latency metric and all quality/stream guardrail margins before running trials.
2. Pair the same task and environment; do not compare unrelated averages.
3. Randomize or counterbalance baseline/candidate order to reduce thermal, cache and time-order bias.
4. Warm up both configurations equally.
5. Keep the holdout out of prompt, skill and threshold tuning.
6. Use at least 30 matched pairs by default; increase this for noisy game/stream workloads.
7. Report confidence intervals and raw pair count, not only a point estimate.
8. Preserve inconclusive outcomes; never silently count missing measurements as passing.
9. Repeat promising results on a second session/reboot and, when relevant, a second game/map.
10. Require human review before changing the production model, provider, quantization, concurrency or scheduler policy.

Bootstrap intervals are descriptive and depend on representative paired samples. They do not guarantee future performance or correct sensor/label provenance.

## 6. Prioritized STAR roadmap

### P0 — Evidence bridge
- Integrate this evaluator with the trusted rehearsal recorder and the existing trace/profile schema.
- Add a local-only experiment manifest with opaque task/config IDs and predeclared thresholds.
- Export a small JSON report without prompts, transcripts, viewer IDs or raw media.

### P1 — Actual Windows measurements
- Implement a read-only Windows host adapter.
- Collect process-tree CPU and working-set/RAM data, GPU/VRAM telemetry where available, PresentMon frame times, OBS render/output counters and playback acknowledgements.
- Timestamp every source with a monotonic clock and source epoch.
- Fail closed on stale, reset or missing telemetry.
- Calibrate resource budgets from repeated observations; do not treat abstract resource vectors as measured capacity.

### P2 — Inference tuning
- Benchmark one, two and higher inference slots only under matched workloads.
- Compare continuous batching and speculative decoding only when the exact server build/model supports them.
- Test prompt-prefix/KV caching separately from decode throughput.
- Keep an always-responsive speech/game-control path and defer research/asset generation during active play.

### P3 — Natural streaming
- Integrate semantic turn detection, VAD, adaptive interruption filtering and false-interruption recovery.
- Add a speech scheduler that tracks queued, generated, audible and interrupted segments separately.
- Drive avatar mouth parameters from actual playback and expressions from grounded conversation/game events.
- Evaluate group conversation scenarios, including correct silence.

### P4 — Game mastery and creation
- Build versioned game-mechanic skill artifacts.
- Use compositional curricula and held-out transfer tests.
- Connect Roblox Studio inspection, build, playtest and repair to reproducible test places.
- Keep fast game control separate from slow strategic planning.

### P5 — General intelligence and continuity
- Separate working memory, episodic experience, procedural skills and semantic knowledge.
- Add source provenance, conflict resolution and expiration.
- Measure transfer, retention, forgetting and unrelated-task interference.
- Promote only independently verified changes through rollback-capable review.

## 7. Explicit non-goals and limitations

This PR does not:
- call or fine-tune a model;
- connect to Windows hardware, GPU drivers, OBS, VTube Studio or game input;
- record audio, screen frames, chat or transcripts;
- change inference flags, model routing or concurrency;
- automatically train weights, promote skills or merge PRs;
- claim a measured speedup, intelligence gain, human-level streaming behavior or game mastery.

The evaluator's input labels and host measurements remain assertions supplied by the future trusted adapter. A signed report does not by itself prove that the sensor or grader was truthful.

## 8. Sources

- llama.cpp server benchmark: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/README.md
- OpenTelemetry GenAI metrics: https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai-metrics.md
- LiveKit turn detection and interruption handling: https://docs.livekit.io/agents/logic/turns/
- Recuris experiential/working memory: https://arxiv.org/abs/2608.24876
- AgentCL continual-learning evaluation: https://arxiv.org/abs/2606.02461

---
**Review boundary:** Draft PR only. No automatic merge. GitHub Actions must pass on the exact head, followed by a Windows integration run and private rehearsal before any production claim.
