# STAR — Broad General Knowledge, Generalist Agents, Game Mastery and Natural Streaming

**Research date:** 2026-11-10  
**Status:** source-backed engineering plan; a 24-task domain-balanced development suite and per-domain scoring were added in this change.  
**Scope:** STAR's local-first desktop/server, Roblox Studio creator workflow, game-learning lab and optional Windows VTuber runtime.

This work improves evaluation and decision quality. It does **not** change foundation-model weights, prove an intelligence gain, or establish faster inference or human-equivalent behavior.

## Executive recommendation

STAR should be developed as one coordinated generalist system, but evaluated as several distinct capabilities. A single overall score hides important weaknesses. A model can be fast at chat and weak at factual recall, strong at code and weak at real-time control, or expressive in TTS but poor at conversational timing.

Use separate evidence for:

1. **Knowledge and reasoning:** factual accuracy, multi-step reasoning, source attribution, uncertainty and abstention.
2. **Memory:** correct retrieval across sessions, people, projects, corrections and time.
3. **Gaming:** perception, action timing, objective success, recovery and transfer to unseen scenarios.
4. **Game creation:** inspection, code correctness, scene invariants, playtest behavior and visual quality.
5. **Streaming:** addressee recognition, turn-taking, grounded commentary, natural pacing, voice/avatar synchronization and interruption safety.
6. **Performance:** first-content/first-audio latency, inter-token/inter-chunk gaps, p95 tails, CPU/GPU/VRAM, game frame time and OBS/audio health.

The fast path should handle fresh perception, urgent gameplay and conversational turn-taking. The deep path should handle research, strategy, coding, memory synthesis and post-round reflection. The deep path must never block a live stop/interrupt path or reuse stale observations.

## New implementation in this change

### 1. Dynamic multi-domain evaluation

`star/general_knowledge_benchmark.py` now supports development suites containing 10–64 ordered tasks instead of exactly ten. Suite and oracle identity remain pinned, and oracle keys must exactly match the selected suite.

Scoring now reports:

- Overall pass/incorrect/invalid/empty/transport-error counts.
- Per-domain counts.
- The category attached to each scored task.
- Category metadata in prepared requests and request fingerprints.
- Suite-specific scope text rather than a misleading global ten-task description.

The original ten-task closed-world suite remains the default and remains backward compatible.

### 2. New 24-task broad development suite

`evals/general_knowledge/broad-development-v1.prompts.json` contains 24 original tasks across twelve domains, with two tasks per domain:

| Domain | Coverage |
|---|---|
| Astronomy | Planet size and ordering |
| Chemistry | Atomic number and molecular formula |
| Biology | Photosynthesis and oxidative phosphorylation |
| Physics | Newton's third law and the exact speed of light |
| Geography | National capital and largest ocean |
| History | Apollo 11 and the Wright Flyer |
| Literature and arts | Frankenstein and the Mona Lisa |
| Computing | HTML and Python mutability |
| Language | Two common Spanish translations |
| Environment | Ozone layer and dry-air composition |
| Civics and economics | U.S. government branches and inflation |
| Evidence reasoning | Corrected facts and missing-data abstention |

The separate `broad-development-v1.oracles.json` file contains reviewed expected objects and source derivations. It is evaluator-only: `prepare` never opens it and never places oracle answers or derivations into model messages.

This is a small public development diagnostic, not a sealed holdout, a full knowledge benchmark, or a model leaderboard. Repeated use can cause benchmark contamination. Use fresh held-out questions before making promotion decisions.

### Run it

List the suite and domain balance:

```bash
python -m star.general_knowledge_benchmark list \
  --suite evals/general_knowledge/broad-development-v1.prompts.json
```

Prepare two attempts per task without loading the oracle sidecar:

```bash
python -m star.general_knowledge_benchmark prepare \
  --suite evals/general_knowledge/broad-development-v1.prompts.json \
  --repeats 2
```

Score an operator-collected raw run:

```bash
python -m star.general_knowledge_benchmark score \
  --suite evals/general_knowledge/broad-development-v1.prompts.json \
  --oracles evals/general_knowledge/broad-development-v1.oracles.json \
  --run broad-run.json
```

The raw run must include exact suite/oracle/grader digests and a declared model/runtime identity. The declaration is not cryptographic authentication. The report omits response text; the raw run should be stored privately and handled according to the project's retention policy.

## Research findings and design consequences

### 1. Generalist game agents: learn transferable skills, not just button sequences

Google DeepMind's [SIMA 2](https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/) (2025-11-13) describes an agent that follows natural-language instructions, reasons about goals, converses and improves across 3D virtual worlds. The authors also report tests in held-out games and newly generated Genie worlds.

**STAR implication:** use a reusable game-skill representation with explicit preconditions, observations, actions and measured outcomes. Evaluate on unseen maps, seeds and game versions. SIMA 2 is a research reference, not a drop-in local model or evidence that STAR has the same capability.

### 2. Real-time gaming is a deadline problem, not only a reasoning problem

[Gym-Anything-RT](https://arxiv.org/abs/2610.37567) (2026-10-27) introduces 100 minigames with real-time and paused/slow counterparts. One reported GPT-6 Astra xHigh configuration passed 9.0% in real time and 75.0% when paused. These are results for that paper's benchmark and configuration, not expected STAR scores.

**STAR implication:** measure the same task under live, slowed and paused timing. Separate perception freshness, decision quality, action latency and objective outcome. A delayed action based on an old frame must be discarded, not executed late.

### 3. Roblox creation needs inspection and playtest evidence

[OpenGameEval](https://arxiv.org/abs/2610.02563) (2026-10-01) evaluates agents in reproducible Roblox Studio sessions, scoring both edited scenes and simulated play. Its paper reports 84 curated tasks across 13 models and finds that inspecting touched objects before editing is associated with higher task pass rates.

**STAR implication:** preserve an inspect-before-edit trace. Run Luau analysis and formatting, check scene invariants, execute server/client playtests, inspect logs and compare visual output. A successful code-generation response or a clean syntax check is not proof that a feature works in game.

### 4. Human-like streaming requires synchronized multimodal context

[LiViBench](https://ojs.aaai.org/index.php/AAAI/article/view/39859), published at AAAI 2026, evaluates interactive livestream understanding across 24 tasks with audio, speech and real-time comments. Its work includes a Video-to-Comment Retrieval component to connect livestream observations with comments.

**STAR implication:** build a local event timeline that aligns fresh game frames, game-state events, audio activity, speaker/addressee labels and moderated comments. Retrieval should be scoped to the current scene and event window. Star should respond, backchannel or remain silent based on relevance and turn ownership—not on every incoming sound or message.

Naturalness should be assessed by independent human review of interruption handling, silence, repetition, grounding, pacing, prosody and voice/avatar synchronization. A model-generated self-rating is not sufficient evidence.

### 5. Long-term memory needs temporal and multi-party reasoning

[LongMemEval](https://arxiv.org/abs/2410.10813), accepted at ICLR 2025, evaluates information extraction, multi-session reasoning, temporal reasoning, knowledge updates and abstention across 500 questions.

[EverMemBench](https://arxiv.org/abs/2602.01313) extends the challenge to long multi-party, multi-group histories with evolving information and role-conditioned facts. Its reported results highlight the difficulty of multi-hop attribution and temporal updates.

[EGMEMORY](https://arxiv.org/abs/2609.23465) proposes separating persistent message evidence from an explicit active state, using a propose-verify-commit protocol before changing that state. Its results are pre-publication research claims and should be reproduced before adoption.

**STAR implication:** preserve immutable evidence separately from current accepted facts. Record who/what a fact concerns, project/game scope, valid time, observation time, source, confidence, status and supersession links. A correction should update the active view without erasing the historical evidence. Unknown information must remain unknown; no retrieved evidence means abstain or ask.

### 6. Faster inference: optimize end-to-end quality under stream load

The [llama.cpp speculative decoding guide](https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md) documents draft-model and n-gram approaches. Speculation helps only when draft proposals are cheap and accepted often enough; acceptance statistics must be measured.

[vLLM serving documentation](https://docs.vllm.ai/en/latest/cli/serve/) documents prefix caching and chunked prefill controls. Prefix caching can reduce repeated prefill work; it does not directly make every generated token faster. Chunked prefill can improve scheduling behavior but must be benchmarked against STAR's actual concurrency and context lengths.

**STAR implication for an 8 GB gaming GPU:**

1. Establish a same-model, same-runtime baseline first.
2. Keep stable system/tool prefixes byte-stable and place per-turn context after them.
3. Test native prefix caching and n-gram speculation before loading another GPU-resident draft model.
4. Measure prompt processing, first content, first audible audio, inter-token/inter-chunk gaps, end-to-end p50/p95, VRAM, game frame time and OBS/audio losses.
5. Test the complete game + OBS + TTS + avatar workload.
6. Promote no model or runtime configuration from one lucky run; require paired repetitions and quality non-regression.

A faster isolated token rate is not an improvement if it causes frame drops, audio underruns or worse answers.

## Recommended unified runtime

| Layer | Responsibility | Required behavior |
|---|---|---|
| Perception | Game frames/state, audio activity, comments, desktop | Timestamp, scope and expire observations |
| Working state | Current game/scene/round and conversation state | Reject stale or cross-scene context |
| Fast decision | Reflex, turn-taking, stop/yield/silence | Meet hard deadlines; preemption wins |
| Deep reasoning | Research, strategy, code and planning | Run asynchronously with bounded budgets |
| Memory | Evidence, active facts, experiences and procedures | Propose → verify → commit; preserve history |
| Execution | Game, Studio, audio, avatar and OBS adapters | Owner-approved, least-privilege adapters only |
| Verification | Benchmarks, playtests and host receipts | No evidence means inconclusive |
| Resource governor | CPU, GPU, VRAM, frame time, OBS and audio | Protect the game and live stream first |

## Prioritized next engineering stages

### P0 — Establish domain-specific model quality
- Run both the ten-task foundational suite and the new 24-task broad suite against each local model alias.
- Pin model weights, tokenizer, quantization, backend, prompt builder, options and app commit.
- Compare models on the same tasks and report per-domain pass rates alongside first-content and end-to-end latency.
- Keep development results separate from sealed holdout results. Do not automatically change routes.

### P1 — Strengthen long-term memory
- Add a LongMemEval-style private/synthetic test track for knowledge updates, temporal reasoning, multi-session recall and abstention.
- Add role-aware multi-party attribution and explicit version/supersession semantics.
- Keep original evidence immutable; promote only reviewed facts.
- Measure retrieval recall, answer accuracy, latency and memory bytes per useful fact.

### P2 — Demonstrate game mastery
- Use a real game observer and independently witnessed outcomes.
- Compare live and paused timing on the same objective.
- Test at least three distinct scenarios plus held-out maps/seeds.
- Measure progress, objective success, recovery, stale-action rejection and transfer.
- Never let practice results grade their own holdout.

### P3 — Demonstrate game creation
- Inspect the target place before editing.
- Work in an unpublished test experience.
- Run static Luau checks, scene invariants and server/client playtests.
- Capture independent visual review and performance evidence.
- Keep publishing, monetization, asset uploads and live player-data writes separately gated.

### P4 — Demonstrate natural VTuber behavior
- Connect trusted Windows audio observation, ASR/VAD, speaker/addressee labels, TTS, VTube Studio and OBS.
- Measure first-audible latency and interruption-to-quiet latency at the device, not just at the TTS queue.
- Tie audio and avatar receipts to the same event/session epoch.
- Run a 30–60 minute private rehearsal with gameplay, OBS, TTS, avatar and background reasoning.
- Have independent reviewers score timing, silence, repetition, grounding, expressiveness and consistency.

### P5 — Optimize speed without harming quality
- Run paired AB/BA inference experiments under idle and full gaming load.
- Compare n-gram speculation, draft-model speculation, quantization and prefix caching independently.
- Record p50/p95/p99, VRAM, CPU, game frame time, OBS dropped frames and audio underruns.
- Retain the configuration with the best quality-adjusted user experience, not merely the highest idle tokens/second.

## Source register

- Google DeepMind, [SIMA 2: An Agent that Plays, Reasons, and Learns With You in Virtual 3D Worlds](https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/), 2025-11-13.
- Aggarwal & Welleck, [Gym-Anything-RT](https://arxiv.org/abs/2610.37567), 2026-10-27.
- Turkel et al., [OpenGameEval](https://arxiv.org/abs/2610.02563), 2026-10-01; [Roblox evaluation repository](https://github.com/Roblox/open-game-eval).
- Wang et al., [LiViBench](https://ojs.aaai.org/index.php/AAAI/article/view/39859), AAAI 2026-03-14.
- Wu et al., [LongMemEval](https://arxiv.org/abs/2410.10813), ICLR 2025; [official code and data](https://github.com/xiaowu0162/LongMemEval).
- Hu et al., [EverMemBench](https://arxiv.org/abs/2602.01313), 2026-02-01; [official repository](https://github.com/EverMind-AI/EverMemBench).
- Lu et al., [EGMEMORY](https://arxiv.org/abs/2609.23465), 2026-09-20.
- [llama.cpp speculative decoding](https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md).
- [vLLM serving options](https://docs.vllm.ai/en/latest/cli/serve/).
- [NIST CODATA speed of light](https://physics.nist.gov/cgi-bin/cuu/Value?c).
- [NASA solar-system planets](https://science.nasa.gov/solar-system/planets/).
- [OpenStax Biology 2e](https://openstax.org/books/biology-2e/pages/8-2-the-light-dependent-reactions-of-photosynthesis).
- [NOAA atmosphere](https://www.noaa.gov/jetstream/atmosphere) and [ozone layer](https://www.nesdis.noaa.gov/news/unlocking-the-secrets-of-the-stratosphere-the-jpss-ozone-mapping-and-profiler-suite-omps).
- [Smithsonian National Air and Space Museum: 1903 Wright Flyer](https://airandspace.si.edu/collection-objects/wright-1903-flyer/nasm_A19610048000).
- [USAGov: branches of government](https://www.usa.gov/branches-of-government).

## Honest status

Implemented in this change: dynamic 10–64-task suite support, per-domain scoring, a 24-task/12-domain development suite, evaluator-only source-backed oracles, regression tests and this research roadmap.

Not demonstrated in this change: higher foundation-model intelligence, model-weight training, faster hardware inference, automatic model routing, real-game mastery, autonomous game creation, live Windows audio/OBS/VTube Studio integration, or human-equivalent streaming. Those require actual model runs, independent holdouts and the private Windows acceptance tests described above.
