# STAR Research: Causal Turn-Taking, Natural Streaming, and Skill Transfer

**Date:** 2026-11-12  
**Status:** Research and offline evaluator implementation; runtime integration is not included.  
**Branch:** `feat/causal-turntaking-evaluation-20261112`

## Executive summary

STAR already has a small, opt-in `TurnTakingGate`, a `StreamDirector`, a stable streamer persona, a cross-session continuity store, a workload-admission policy, and a paired latency/quality evaluator. The missing piece is a reproducible way to measure whether a voice-turn policy is both **fast and socially correct**.

This change adds `star/stream_turntaking_eval.py`. It evaluates causal end-of-turn score traces against labeled silence spans, sweeps thresholds/action delays/timeouts, includes a silence-only baseline, and returns a Pareto frontier over:

1. False cutoffs during a human's mid-turn pause.
2. End-of-turn response delay (with censored/missed turns made visible).
3. Missed final turns.

It stores no audio, transcript, viewer identity, speaker identity, prompt, or model output. It does not run a model or control speech playback.

The larger STAR roadmap remains broader than voice: a two-timescale game agent, visual-feedback game creation, verified procedural skills, general-knowledge cards with provenance, and workload-aware local inference. Those should share evaluation contracts rather than be fused into one untestable mega-agent.

---

## 1. Repository findings and existing architecture

The current `main` README describes STAR v1.0.0 as a Windows 11 chat-first product. Roblox documentation and several local/remote model paths are available or opt-in; Studio Lab and richer voice behavior are still marked coming soon. Draft pull requests, passing CI, or a source-only component do not mean the feature is shipped in the installer.

The current development branch already contains:

- `star/stream_turntaking.py`: an opt-in deterministic advisor over host-supplied, preprocessed VAD frames. It can hold speech or request an owner-authenticated yield; it is not a speech recognizer or semantic end-of-turn model.
- `star/stream_director.py`: bounded event arbitration, priority, cooldown and deliberate quiet time.
- `star/stream_persona.py`: stable AI-transparent streamer brief and untrusted event framing.
- `star/stream_continuity.py`: disabled-by-default owner-approved gameplay continuity sourced from signed practice evidence.
- `star/stream_load_governor.py`, `star/stream_workload_admission.py`, and `star/stream_workload_runtime.py`: policy and resource-allocation layers; they do not sample Windows hardware or launch workers.
- `star/stream_experiment_eval.py`: paired latency/quality evaluation; it does not execute model experiments.

### Architectural gap

The existing VAD gate answers a narrow question using host-provided source labels and silence timing. It does not evaluate the more difficult question:

> Given only the information available at each pause, should Star keep listening, yield to a real interruption, or take the conversational floor now?

A simple fixed silence timeout can be quick but cut people off. A very conservative timeout avoids some false cutoffs but creates dead air. A single accuracy score hides that tradeoff.

The new evaluator addresses the measurement gap before any detector or policy is changed.

---

## 2. Research: End-of-turn evaluation must measure the policy, not only the classifier

### 2.1 LiveKit eot-bench

Repository and methodology: https://github.com/livekit/eot-bench

The benchmark includes human-to-agent turns with multiple silence spans. Earlier pauses are labeled as holds; the final pause is the true end-of-turn. Predictions are evaluated causally at the information available at each point.

The harness sweeps three policy dimensions together:

- confidence threshold;
- minimum action delay;
- maximum timeout.

It reports the false-cutoff/latency tradeoff, includes a silence-only VAD baseline, and provides multilingual comparisons across 14 languages. This is a better model for STAR than picking a threshold from one development conversation.

**STAR application:** the new `SilenceSpan` and `EndOfTurnScore` types represent content-free pause labels and timestamped causal scores. `sweep_turn_policies` evaluates a predeclared grid and includes a silence-only baseline.

Important distinction: eot-bench's endpointing latency is conversational wait after the human finishes. It is not LLM time-to-first-token or TTS playback latency. STAR must measure these separately.

### 2.2 TurnBench

Project and leaderboard: https://turnbench.sesame.com/  
Paper: https://www.alphaxiv.org/abs/2608.25218v2

TurnBench introduces a multi-domain, hand-annotated corpus of dyadic human conversation and evaluates end-of-turn and interruption detection with recall, false-positive rate and latency. Its central lesson is that turn-taking is a joint quality/latency problem, not a binary accuracy problem.

**STAR application:** retain both endpointing and barge-in tests. A detector that ends a turn correctly can still mishandle a real interruption, and vice versa. A future adapter should map the benchmark's held-out examples into STAR's content-free evaluation schema without retaining recordings in STAR's runtime database.

### 2.3 MP-Bench

Paper: https://aclanthology.org/2026.findings-emnlp.1437/

MP-Bench evaluates voice agents as active participants in multi-party conversation, including turn-taking awareness, response appropriateness and comprehension. In its evaluation of 12 voice agents, real-time systems scored at or below 22% on multi-party comprehension and near chance on multi-party turn-taking.

**STAR application:** dyadic end-of-turn success is not enough for a VTuber. A later Social Brain evaluation needs scenarios where several people speak, address each other, backchannel, overlap, or talk to Star. The system must sometimes continue listening when a viewer says “yeah” while Star is speaking, and sometimes yield when the owner actually interrupts.

Do not infer that an agent is socially competent from ASR word accuracy alone.

---

## 3. Implementation: `star/stream_turntaking_eval.py`

### Data contract

- `SilenceSpan`: opaque span/turn/environment IDs, pause kind, observed duration, and a bounded tuple of score points.
- `EndOfTurnScore`: elapsed milliseconds from pause start and a finite score in [0, 1].
- `TurnPolicy`: predeclared threshold, action delay and timeout.
- `TurnPolicyResult`: aggregate cutoff, detection, miss and observed-latency metrics.
- `TurnTakingSweep`: all evaluated policies plus a non-dominated Pareto frontier.

The adapter contract requires each score to use only information available by its `elapsed_ms`. The evaluator validates timestamps and bounds, but it cannot prove that an external model did not leak future context; that remains a dataset/adapter provenance requirement.

### Decision semantics

- On a HOLD span, speech resumes at `duration_ms`. A detector action at or after that boundary is not counted as a false cutoff because the host should already have received the resumed speech.
- On an END_OF_TURN span, `duration_ms` is the recorded observation horizon.
- A model score can trigger only after the minimum action delay and no later than the timeout.
- A timeout triggers a final turn if it falls within the observed horizon.
- A timeout that fires strictly before speech resumes is a false cutoff on a HOLD span.
- If the final observation horizon ends before a decision, the turn is counted as missed. Its horizon is included as a right-censored observed latency so missed turns cannot make a policy look artificially fast.

### Reported metrics

- false-cutoff count and rate per HOLD span;
- final turns detected and missed;
- missed-final-turn rate;
- mean, p50 and p95 observed final-turn latency;
- policy threshold, action delay and timeout;
- score source (model or silence-only baseline).

The Pareto frontier minimizes false-cutoff rate, p95 observed latency and missed-final-turn rate. It does not invent one scalar “human-likeness” score.

### Safety and scope

This module is pure/offline. It does not access a microphone, store audio, transcribe speech, identify speakers, call an inference provider, generate TTS, interrupt playback, operate OBS/VTube Studio, or authorize tools. Labels and score traces are supplied by a trusted evaluation adapter; they are not authenticated by this module.

---

## 4. How to make Star's streaming feel natural

The engineering target is not to imitate a real person or claim human experiences. It is to make an AI character conversationally competent, expressive, transparent, and responsive.

### Recommended voice pipeline

Keep these clocks separate:

1. **End-of-turn delay:** how long the system waits after the speaker's final silence.
2. **Interruption detection delay:** how long a genuine barge-in takes to be recognized.
3. **ASR/final transcript delay:** when the recognized user turn is stable enough for reasoning.
4. **LLM TTFT:** when the model emits its first token.
5. **TTS first-audio delay:** when synthesized audio becomes available.
6. **Device playback delay:** when audio is actually audible.
7. **Avatar reaction delay:** when the corresponding mouth/face/body animation becomes visible.

Do not subtract percentiles from different clocks or combine them into one “response latency.” Use same-turn trace IDs at the host boundary and calculate per-turn end-to-end durations.

### Behavior to evaluate

- Correctly hold through hesitations and backchannels.
- Yield to a verified owner interruption.
- Do not let a viewer's chat text become tool instructions.
- Resume only the unspoken remainder after a false interruption.
- Avoid speaking over other people.
- Choose silence during tense gameplay when there is no useful commentary.
- Avoid repeating the same callback or canned reaction.
- React to observed gameplay evidence, not inferred events.
- Maintain a stable persona while being honest that Star is AI.
- Evaluate response appropriateness with blinded human labels, not the model grading itself.

### Proposed acceptance targets (initial hypotheses, not measured results)

Set thresholds before a held-out run. For example:

- false cutoff rate at or below a predeclared 5% operating point on a suitable held-out dataset;
- report endpointing delay at that operating point;
- report false cutoffs at fixed 300 ms and 600 ms latency budgets where the dataset supports them;
- report missed-turn rate and interruption precision/recall separately;
- no increase in audio underruns or game frame-time p95/p99 under the same mixed workload;
- human-rated response appropriateness must not regress.

These are proposed gates, not current STAR scores. A threshold must not be tuned on the final holdout.

---

## 5. Research: Make Star better at games and game creation

### 5.1 Real-time control needs two timescales

A game agent should not wait for a long language-model chain every time it needs to move.

Recommended architecture:

- **Reactive loop:** recent observation, immediate hazard detection, short-horizon action, fast feedback.
- **Strategic loop:** objective planning, mechanics discovery, route selection, strategy review and skill retrieval.
- **Skill store:** versioned procedures with preconditions, environment scope, success evidence and known failure cases.
- **Evaluator:** held-out scenarios and actual environment outcomes.

The strategic loop may suggest a plan, but the reactive loop must remain responsive and safety-bounded. Do not let an LLM produce unrestricted keyboard/mouse commands from untrusted game text.

### 5.2 GameDevBench

Project: https://github.com/waynchi/gamedevbench

The ICML 2026 benchmark contains 333 Godot game-development tasks across 2D/3D graphics and animation, UI, and gameplay logic. It reports that visual feedback materially improves agent performance; graphics-focused tasks remain difficult.

**STAR Creator application:**

- Inspect the current scene, assets and scripts before editing.
- Build a minimal reproducible change.
- Run the game in an isolated test project.
- Capture a small, owner-approved set of screenshots/video frames for evaluation.
- Compare expected and actual scene state.
- Run engine diagnostics and gameplay assertions.
- Fix and rerun the same tests plus held-out regression tasks.

A successful code patch is not proof that the game looks correct or plays correctly. Visual evaluation and runtime playtests are necessary.

### 5.3 Transferable game skills

Store skills as scoped artifacts, not vague natural-language claims:

- game/engine/version scope;
- mechanic and objective IDs;
- preconditions and observation requirements;
- action sequence or policy reference;
- trial count and outcome;
- failure modes;
- confidence and last validation date;
- held-out transfer results.

A movement technique learned in one game should be tested before being applied to another. Do not call a skill “mastered” because it succeeded once.

---

## 6. Research: General knowledge that can be used, not just recalled

### Mem2ActBench

Paper: https://arxiv.org/abs/2601.19935

Mem2ActBench evaluates whether an agent actively uses long-term memory to choose tools and ground action parameters. Its 2,029-session benchmark and 400 tool-use tasks highlight the gap between passive recall and applying memory in future tasks.

**STAR application:** evaluate knowledge by asking Star to perform a later task that requires it, not just repeat the stored fact.

### AFTER procedural-memory benchmark

Paper: https://arxiv.org/abs/2606.23127

AFTER evaluates procedural-skill transfer across tasks, professional roles and model backbones. Its findings support testing each skill's transfer scope instead of assuming that every procedure generalizes.

**STAR application:** maintain a knowledge/skill card with source, date, scope, evidence, uncertainty, review date and task-level validation. Separate factual knowledge from executable skills.

### Recommended curriculum

- mathematics and statistics;
- physics, chemistry and biology;
- computer science and software engineering;
- history and geography;
- economics and practical finance concepts;
- languages and communication;
- psychology and social reasoning;
- art, music, design and storytelling;
- game design and production;
- everyday digital and practical skills.

Use retrieval with source provenance and freshness checks. A source-backed card is not automatically true; contradictory claims should remain visible until resolved. Use held-out questions and real tasks to test application.

---

## 7. Local inference speed: benchmark the whole serving path

### llama.cpp server benchmark

Upstream benchmark guide: https://github.com/ggml-org/llama.cpp/tree/master/tools/server/bench

The upstream server benchmark uses a repeatable request workload and records server metrics under controlled concurrency. Its documentation exposes server parallelism, batch/context configuration, request count and duration, and Prometheus metrics.

**STAR application:**

- Record the exact model file hash, quantization, backend, context size and llama.cpp build.
- Match client concurrency to server parallel slots.
- Run warm-up separately from measured requests.
- Use the same prompt set, output budget and randomization policy for baseline/candidate.
- Measure TTFT, inter-token latency, full request duration, queue wait, throughput and memory.
- Repeat with the game, OBS, voice and avatar workloads active.
- Pair latency with held-out task quality and stream guardrails.

Do not blindly increase `-np` or background agent count. More concurrency can improve aggregate throughput while making an individual voice turn slower or exhausting VRAM. Select the configuration by the actual mixed workload, not a standalone tokens/second number.

### STAR's next performance experiment

Run a predeclared matrix:

- one, two and four inference slots where memory permits;
- short and long context profiles;
- cold and warm prefix-cache runs;
- normal and speculative decoding if supported by the exact model/backend;
- one foreground voice task plus bounded background research/learning.

Record:
- first-content and first-audible latency separately;
- p50/p95/p99 inter-token and request latency;
- tokens/sec and completed requests/sec;
- CPU/RAM/VRAM peaks and OOM/reload events;
- game frame-time p95/p99;
- OBS render/output skips;
- audio underruns;
- held-out task quality.

Reject any candidate that improves aggregate throughput but violates the predeclared interactive latency, quality, audio or game-frame guardrails.

---

## 8. Integration plan

### Phase A — offline evaluation (this PR)

- Add causal pause-score schema.
- Evaluate one policy.
- Sweep threshold/action-delay/timeout.
- Include silence-only baseline.
- Report Pareto frontier.
- Keep raw content outside the evaluator.

### Phase B — rehearsal adapter

- Adapt a public eot-bench subset or locally generated owner-approved rehearsal labels.
- Preserve dataset license and provenance.
- Ensure each score is generated causally from the prefix available at its timestamp.
- Add a separate interruption/backchannel test set.
- Keep all microphone capture and playback in an owner-controlled host adapter.

### Phase C — connect to STAR paired experiments

- Add turn-taking metrics to paired baseline/candidate evaluation.
- Require the same turns, environment and label source.
- Report false-cutoff, missed-turn, endpointing-delay and appropriateness deltas.
- Never let model self-grading be the sole quality label.

### Phase D — Windows host integration

- Add an opt-in WASAPI/voice adapter and explicit device consent.
- Add playback acknowledgements and echo cancellation before barge-in decisions.
- Keep owner identity proof separate from voice similarity.
- Add OBS and avatar telemetry through authenticated local APIs.
- Keep raw audio/transcripts ephemeral unless separately approved.

### Phase E — game and general-intelligence integration

- Connect the dual-loop Gamer Brain to a sandboxed game adapter.
- Keep skill artifacts versioned and scope-bound.
- Use GameDevBench-style visual feedback for game creation.
- Add source-backed general-knowledge cards and task-based evaluation.
- Use the existing workload runtime to defer noncritical learning during a live stream, after a calibrated Windows host adapter exists.

---

## 9. Validation and limitations

- The new evaluator is pure Python and has no runtime wiring.
- It trusts the adapter's labels and causal-score provenance; it cannot verify the upstream model did not inspect future audio.
- The silence-only baseline is a simple action-delay policy, not a full VAD implementation.
- The Pareto frontier is an operating-point aid, not a proof of social intelligence.
- No real audio, microphone, TTS, OBS, VTube Studio, Windows hardware, RTX 4060, Roblox Studio or live game was exercised by this PR.
- No speedup, quality gain, game mastery or human-equivalent behavior is claimed.
- The current shipping README remains authoritative for v1.0 product status.
- Production `main` and the installer remain unchanged.

## Sources

1. LiveKit eot-bench — https://github.com/livekit/eot-bench
2. TurnBench — https://turnbench.sesame.com/
3. MP-Bench, Findings of EMNLP 2026 — https://aclanthology.org/2026.findings-emnlp.1437/
4. GameDevBench — https://github.com/waynchi/gamedevbench
5. Mem2ActBench — https://arxiv.org/abs/2601.19935
6. AFTER procedural memory — https://arxiv.org/abs/2606.23127
7. llama.cpp server benchmark — https://github.com/ggml-org/llama.cpp/tree/master/tools/server/bench

## Files in this change

- `star/stream_turntaking_eval.py`
- `tests/test_stream_turntaking_eval.py`
- `docs/research/STAR_20261112_CAUSAL_TURNTaking_NATURAL_STREAMING_AND_SKILL_TRANSFER.md`
