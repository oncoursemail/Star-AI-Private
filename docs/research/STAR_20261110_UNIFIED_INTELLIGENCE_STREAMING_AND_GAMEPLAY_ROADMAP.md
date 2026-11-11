# STAR research: unified intelligence, VTuber, gaming and realtime runtime

**Research date:** 2026-11-10  
**Scope:** architecture synthesis against the current `star/next` codebase; no live broadcast or game-control actions were performed.

## Executive direction

STAR already contains many of the necessary pieces: realtime brain admission, stream QoS, resource planning, turn-taking, a stream director, gameplay evidence, transfer evaluation, general-knowledge artifact checks, and portable Agent Skills. The next quality jump is not another isolated "brain." It is a measured integration layer that makes these systems share one trustworthy view of the current session while preserving separate authority boundaries.

The central architecture should be:

```text
Audio / Chat / Game / Studio / Host Telemetry
                    |
                    v
          Typed, scoped event envelope
                    |
                    v
         Session state + evidence ledger
                    |
        +-----------+------------+
        |           |            |
        v           v            v
    Social      Game/World     Creator/
    Director    Intelligence   Research
        |           |            |
        +-----------+------------+
                    |
                    v
           Deadline-aware conductor
                    |
          +---------+----------+
          |                    |
          v                    v
      Interactive jobs     Background jobs
      voice/game/avatar    research/build/eval
          |                    |
          +---------+----------+
                    |
                    v
          Independent validation
```

The conductor coordinates plans and budgets. It does not become a new unrestricted authority layer: trusted host adapters continue to own microphones, game input, OBS, avatar control, filesystem writes, credentials and external side effects.

## 1. Current STAR building blocks inspected

| Existing module | Existing responsibility | Integration opportunity |
|---|---|---|
| `star/stream_brain_governor.py` | Host boundary for realtime gaming intelligence; admits/reserves inference capacity from trusted telemetry | Make it the live-workload admission authority, not a model-callable tool |
| `star/stream_load_governor.py` | Offline QoS advice using FPS p10, voice p95, OBS dropped frames, free VRAM and audio underruns | Feed it atomic, monotonic host samples and use its decisions in a real host scheduler |
| `star/agent_resource_planner.py` | Dry-run resource admission for concurrent specialists sharing physical CPU/RAM pools | Reconcile background agents against the live stream budget |
| `star/stream_turntaking.py` / `stream_director.py` | Turn advice and stream event direction | Add multi-party addressing and silence-preservation evidence |
| `star/gameplay_skill_bank.py` | Independently validated, signed gameplay outcomes | Keep practice separate from validation and bind results to game version/objective |
| `star/game_skill_memory.py` | Bounded offline episode evidence and practice recommendations | Link reusable action skills to validated transfer evidence |
| `star/game_transfer_eval.py` | Owner-only paired holdout evaluation | Use unseen maps/seeds and independent scoring for skill promotion |
| `star/general_knowledge_benchmark.py` | Ten-task development artifact-consistency checks | Expand to domain and transfer tests; its current scope is not broad general-knowledge proof |
| `star/agent_skills.py` / `tool_workshop.py` | Portable skills and reviewed read-only recipes | Add ranked metadata retrieval and then controlled progressive disclosure |
| `star/skill_routing.py` | Optional embedding fallback for the specialized skill-pack path | Keep separate from the general installed-skill catalog unless paired evaluation supports a unified router |

This inventory means STAR does not need duplicate governors, game-skill banks or memory stores. It needs stable contracts and cross-system acceptance tests.

## 2. New research: natural multi-party VTuber interaction

### Duplex-MPE (2026-09-25)

Paper: https://arxiv.org/abs/2609.31948

Duplex-MPE contains 2,000 continuous-audio scenarios with three or four human speakers and one assistant. Each request is paired across explicit and implicit addressing. It scores fresh response initiation, answer accuracy, silence preservation, and stopping when a human has already resolved a request.

The important lesson is that a lively voice agent is not one that speaks constantly. A capable participant must know when a request is addressed to it, when it has already been answered, when to stay silent, and when to stop an utterance.

### MP-Bench (Findings of EMNLP 2026)

Benchmark overview: https://www.fullduplex.ai/benchmarks/mp-bench

The benchmark page reports that 12 evaluated voice agents reached at most 22% on multi-party comprehension and near-chance performance on multi-party turn-taking. STAR should therefore treat group conversation as a distinct capability, not assume single-user ASR plus a fast LLM solves it.

### Full-Duplex-Bench v3

Benchmark overview: https://www.full-duplex.ai/benchmarks/fdb-v3

The published setup uses 100 human-recorded spoken requests across 79 scenarios and 12 speakers, including disfluencies and requests requiring one to three chained tool calls. Its dimensions include tool-call accuracy, Pass@1, latency and turn-taking. This is useful for evaluating Star's voice-plus-tools loop, not just speech quality.

### Proposed Star Social Director

Use explicit state transitions rather than a single "generate reply" step:

1. **Listen:** continuously collect permitted audio and transient speaker segments.
2. **Resolve speakers:** diarize speakers with uncertainty; never treat uncertain identity as fact.
3. **Resolve addressing:** distinguish direct address, group address, side conversation, quoted text and ambiguous speech.
4. **Resolve obligation:** decide whether a response is needed, optional, already answered or unsafe.
5. **Plan:** choose a short response or a bounded tool sequence.
6. **Speak:** stream cancellable audio chunks with a playback/utterance ID.
7. **Barge-in:** stop or yield when a human starts speaking or the request is resolved.
8. **Remember:** retain only allowed, useful stream context with provenance and privacy scope.

Recommended metrics: response initiation accuracy, answer accuracy, silence preservation, stop-after-human-resolution rate, false interruption rate, diarization error, first-audio latency, p50/p95 response latency, audio underruns and OBS dropped frames.

### Human-like behavior without deceptive identity

The desired result is natural timing, contextual humor, expressive reactions, memory continuity and appropriate silence—not pretending to be a human. Keep the AI identity transparent. Viewer messages, donation text, game chat and subtitles are untrusted input, not instructions that can change tools or permissions. Store viewer-specific personal information only under explicit, scoped policy; prefer ephemeral session context and aggregate stream analytics.

## 3. New research: exploration-first game and Studio agents

### OpenGameEval (2026-10-01)

Paper: https://arxiv.org/abs/2610.02563  
Official benchmark: https://github.com/Roblox/open-game-eval

OpenGameEval runs agents in reproducible Roblox Studio sessions, separates observation tools from editing tools, and scores both the edited scene and a simulated play session. It includes 84 human-curated core tasks and reports results across 13 frontier models with repeated attempts.

A particularly actionable finding: holding task and model fixed, runs that inspected every object touched by the reference solution passed 13.4 percentage points more often on scene-only tasks and 9.8 points more often on script-only tasks than runs that inspected none of those objects.

### Required Star behavior: observe before mutate

For Studio and game creation, require an evidence phase before writes:

- Inspect the place hierarchy, relevant instances, scripts, properties, constraints and current selection.
- Capture the relevant output/errors and visual state.
- Identify which objects and symbols the intended change depends on.
- Produce a compact plan tied to those observations.
- Only then request the minimum necessary edit capability.
- Reinspect the changed objects and run the relevant playtest.
- Compare screenshots/state and logs against explicit acceptance criteria.
- Roll back or isolate a failed change rather than layering guesses.

Measure **observation coverage**: the fraction of reference-relevant objects/symbols inspected before the first mutation. Keep read-only observation tools distinct from mutating tools in both the agent policy and benchmark logs.

### Star Gamer: closed-loop mastery

Use the existing gameplay evidence and transfer evaluator as the foundation:

```text
Observe -> Estimate state -> Choose objective -> Plan action
   ^                                      |
   |                                      v
Validate outcome <- Execute authorized action
```

Separate perception, state estimation, tactical planning, action selection, and outcome evaluation. Do not treat a screenshot or the model's own claim as proof of a successful action. The trusted game adapter must produce the practice evidence; an independent scorer must sign validation evidence.

Train progressively:
- controls and movement;
- camera and spatial navigation;
- timing and physics;
- aiming and combat;
- resource/economy decisions;
- map and objective knowledge;
- team coordination;
- strategy adaptation to new opponents;
- transfer to unseen maps, seeds and game versions.

A skill should be promoted only after it succeeds on withheld situations, not merely because it repeats a memorized route.

### Star Creator: closed-loop game development

Combine OpenGameEval's stateful Studio exploration with GameDevBench's graphics-aware tasks:

- design and requirements;
- scene/code inspection;
- implementation;
- asset/animation/VFX creation;
- launch in an isolated test place;
- screenshot and runtime inspection;
- deterministic checks and playtests;
- defect localization;
- bounded repair;
- independent retest.

Benchmark visual and gameplay quality separately from code correctness. A compiling script does not prove that a UI is readable, an animation is correctly aligned, an effect is performant or a game loop is fun.

GameDevBench reference: https://github.com/waynchi/gamedevbench

## 4. New research: state-consistent long-term memory

### MemTrace (2026-10-04)

Paper: https://arxiv.org/abs/2610.04838

MemTrace treats long-running agent history as immutable execution traces anchored to files, symbols and tests, organized by dependencies. When context is refreshed, compact anchors reconstruct the relevant task state. Before historical evidence is reused, the system checks whether the evidence remains valid against the current repository state.

The reported improvements on its evaluated coding benchmarks are substantial, but those numbers are specific to the authors' backbone and harness; STAR should reproduce its own paired tests rather than import the percentages as a prediction.

### Recommended STAR memory contract

A durable engineering memory should carry:

- project/repository identity;
- file, symbol, test or artifact identifiers;
- content or tree digest;
- parent trace and dependency IDs;
- tool and model identity;
- observed time and monotonic session epoch;
- command/test result and exit status;
- evidence digest;
- validity predicate and invalidation reason.

On retrieval, compare the stored digest with the current source. If the file, symbol, dependency, model, tool or test suite has changed, mark the old evidence stale and rerun the minimum relevant check. Do not silently reuse an old "passed" result after code has changed.

Keep a compact working anchor for context efficiency; retrieve full trace segments only when the next action needs them. This is better than replaying entire chat histories.

## 5. General knowledge and transferable skill growth

The existing `general_knowledge_benchmark.py` explicitly describes itself as ten public development tasks and artifact consistency checks, not proof of broad knowledge or model delivery. That is a useful honesty boundary.

Expand the curriculum with frozen, source-grounded suites for:
- mathematics and formal reasoning;
- natural and physical sciences;
- history and geography;
- computing and software engineering;
- game design and game mechanics;
- art, music and visual communication;
- practical computer operations;
- language understanding and communication.

For each domain, measure factual accuracy, calibrated uncertainty, source quality, multi-step reasoning, tool correctness, and transfer to unseen tasks. Separate closed-book recall from source-assisted research. A fact retrieved from a page is not the same as durable understanding.

For reusable capabilities, use the SRA three-stage model (retrieval, incorporation, application). This PR adds BM25 metadata search to the bounded installed-skill catalog; the next step is explicit progressive disclosure and paired utility evaluation. See `STAR_20261110_GENERAL_SKILL_RETRIEVAL_AND_SRA.md`.

## 6. Speed: protect the interactive critical path

STAR already has a stream QoS model and resource-planning primitives. The missing acceptance step is to make the trusted host consume real, atomic measurements and enforce scheduling decisions.

Recommended priority classes:

| Class | Work | Scheduling rule |
|---|---|---|
| P0 | audio capture/playback, interruption and emergency stop | reserved capacity; never queue behind research |
| P1 | live response, turn-taking, avatar lip-sync and immediate game decisions | strict deadline; cancel stale work |
| P2 | gameplay analysis and stream event summarization | bounded queue; coalesce duplicate events |
| P3 | background coding, research, asset generation and training | preemptible; pause under FPS/VRAM/audio pressure |
| P4 | indexing, corpus refresh and long benchmark sweeps | run only in an idle window |

Use measured p10 game FPS, p95 voice latency, audio underruns, OBS dropped frames, CPU/RAM, GPU utilization and free VRAM. The model must not supply its own telemetry. Unknown or stale measurements should reduce admission rather than be treated as spare capacity.

Benchmark inference in both isolation and mixed-load mode:
- prompt-prefill throughput and first-token latency;
- generated tokens/second;
- first audible response;
- p50/p95 end-to-end latency;
- KV-cache hit/miss and memory footprint;
- CPU, RAM, GPU and VRAM;
- concurrency and queue depth;
- audio underruns, OBS dropped frames and game FPS.

Keep prompts, model quantization, context length, sampling, cache state, concurrency and hardware constant. Compare cold and warm runs. Test speculative decoding and MoE cache settings individually; a draft model or expert transfer can compete for the same constrained VRAM and make the live workload slower even if isolated token throughput improves.

## 7. Unified acceptance plan

### A. Streaming rehearsal

A private 60-minute rehearsal should include direct and implicit viewer address, two-to-four-speaker conversations, side conversations, interruptions, human-resolved questions, noisy audio, TTS cancellation, avatar expressions, game reactions and background research.

Pass only if:
- response and silence decisions are logged and scored;
- no repeated answer after a human has resolved the question;
- interruptions cancel stale speech cleanly;
- audio and avatar playback remain synchronized;
- no viewer text can invoke privileged tools;
- p95 voice latency, audio underruns and OBS drops remain within a preregistered hardware-specific budget.

### B. Gameplay rehearsal

Run a frozen task set on both familiar and unseen maps/seeds. Score objective completion, safe-action rate, reaction latency, navigation efficiency and transfer. Practice data and holdout validation data must use independent keys and the evaluated agent must not see the holdout labels.

### C. Studio/game-creation rehearsal

Use a disposable place. Require observation coverage before edits, run static checks, execute a simulated play session, inspect visual results, and retest after repairs. Keep publishing and live-player operations outside the automated test scope.

### D. Intelligence and memory rehearsal

Run skill-free, metadata-only, selected-skill and distractor arms. Run the same questions with stale and current repository evidence. Score retrieval, skill need-awareness, skill application, stale-evidence rejection, final task quality and context cost separately.

### E. Mixed-load performance rehearsal

Run voice, avatar, OBS, gameplay and one preemptible background task simultaneously. Compare against a no-background baseline. A throughput gain is accepted only if it does not violate the live FPS, audio and response-latency guardrails.

## 8. Rollout and safety rules

- Keep new behavior opt-in until paired holdout evidence supports it.
- Never let the LLM fabricate hardware telemetry, test receipts, game outcomes or viewer consent.
- Keep model outputs, viewer chat, game text, retrieved skill bodies and MCP descriptions untrusted.
- Do not expose host governor callbacks, microphone capture, raw filesystem writes, game input, OBS control or credential operations as unrestricted model tools.
- Require explicit owner approval for publishing, spending, account changes, external messaging and irreversible actions.
- Preserve independent validation keys outside the evaluated agent.
- Record exact model, runner, tool, prompt, suite and repository digests for every benchmark.
- Report unrun and infrastructure-failed cases as incomplete, never as successes.

## Research references

1. OpenGameEval, arXiv:2610.02563 (2026-10-01): https://arxiv.org/abs/2610.02563
2. OpenGameEval implementation and MIT benchmark assets: https://github.com/Roblox/open-game-eval
3. Duplex-MPE, arXiv:2609.31948 (2026-09-25): https://arxiv.org/abs/2609.31948
4. MP-Bench, Findings of EMNLP 2026 overview: https://www.fullduplex.ai/benchmarks/mp-bench
5. Full-Duplex-Bench v3: https://www.full-duplex.ai/benchmarks/fdb-v3
6. MemTrace, arXiv:2610.04838 (2026-10-04): https://arxiv.org/abs/2610.04838
7. Skill Retrieval Augmentation, arXiv:2604.24594 (2026-04-27): https://arxiv.org/abs/2604.24594
8. GameDevBench: https://github.com/waynchi/gamedevbench

## What this document does not claim

This is a research and integration roadmap, not a report of a completed stream, game playtest, Roblox Studio run, model training session or hardware benchmark. It does not claim that Star is human, that her intelligence has been measured as generally superior, or that local inference speed has increased. The only runtime implementation in the accompanying PR is the bounded BM25 skill-metadata search and Tool Workshop integration; all other changes above are recommended integration work to be validated in separate, reviewable PRs.
