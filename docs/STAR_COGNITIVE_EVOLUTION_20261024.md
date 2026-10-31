# STAR Cognitive Evolution: evidence-guided autonomy, social presence, and measured speed

Research checkpoint: **2026-10-24**. Architecture target: the existing STAR Python/React
application and LAN model servers. Implementation in this branch: a **standalone,
tested, read-only-advisory cognitive governor**. It has NOT been wired into default
chat, Studio, model training, Discord, or streaming; is NOT a shipped AI upgrade;
and has not been shown to increase end-to-end task success or tokens/second.
This document is a research and implementation handoff, not a proof of AGI.

## Executive decision

STAR already has substantial code for routing, short/project memory, reviewed
lessons, failed-task classification, Best-of-N verification, a paired evaluation
gate, Studio Lab experiments, agent runtime, safe self-building, and voice
turn-taking. A fresh competing memory database, second permission layer,
unbounded multiagent swarm, or automatic cloud integration would likely be
counterproductive. Strengthen the _selection and evidence_ connecting those
pieces first.

**Engineering goal:** increase independently accepted tasks per wall-clock hour
while preserving independent validation, project isolation, user consent,
recoverability, and subjective human review of quality. Never optimize
self-reported confidence, raw token count, tool-call count, or number of agents
as proxies for intelligence.

## Research: what the best evidence suggests

| Evidence or primary source | Mechanism | STAR implication and limitation |
| --- | --- | --- |
| [GEPA, ICLR 2026](https://proceedings.iclr.cc/paper_files/paper/2026/hash/0e9e708b6f48e14fd0ac29e167413f76-Abstract-Conference.html) | Reflect on traces and evolve prompts/skills using feedback and Pareto selection | Compare candidate skills against baseline and costs. GEPA's gains on its benchmarks do not transfer automatically to STAR |
| [AlphaEvolve, DeepMind 2025](https://deepmind.google/blog/alphaevolve-a-gemini-powered-coding-agent-for-designing-advanced-algorithms/) and [2026 impact](https://deepmind.google/blog/alphaevolve-impact/) | Propose many algorithm candidates; external evaluators score them | Reuse STAR Best-of-N and sealed evaluation; only tasks with objective graders support automated selection |
| [APEX-EM, EMNLP 2026](https://aclanthology.org/2026.findings-emnlp.1996/) | Episodic/procedural traces retrieve known solutions and failures | Reuse STAR's existing knowledge store and failure ledger; keep evidence provenance; no naïve copying of agent output as true lessons |
| [AEMAgent, EMNLP 2026](https://aclanthology.org/2026.findings-emnlp.915/) | Surprise-based selection and prediction-error reflection for long video | For future game streams, retain meaningful events rather than every frame; do not enable live video collection by default |
| [BMAM, ACL 2026](https://aclanthology.org/2026.findings-acl.1973/) | Specialized temporal, salience and memory-control layers | Keep conversation, project decisions, run history, and skills separately; do not duplicate trusted memory stores |
| [Agentic Confidence Calibration, ICML 2026](https://proceedings.mlr.press/v306/zhang26gy.html) | Estimate action reliability using trajectory-level observations, not verbal certainty | Use externally observed success with conservative lower bounds; our v0.1 is an *adviser*, not a calibrated per-task success predictor |
| [Adaptive Test-Time Compute, ACL 2026](https://aclanthology.org/2026.findings-acl.1754/) | Spend additional inference only on unresolved hard tasks | Allocate Best-of-N slots conditionally, not on easy queries or without GPU/CPU headroom |
| [MUR, ACL 2026](https://aclanthology.org/2026.acl-long.1058/) | Control overthinking through uncertainty-aware inference | Experiment with bounded time/token budgets; measure actual improvements rather than inventing speedups |
| [AgentSpec, EMNLP 2026](https://www.microsoft.com/en-us/research/publication/agentspec-speculative-decoding-for-batch-inference-of-llm-agents/) | Speculative decoding adapted to agent workloads | Backend experiment only; requires compatible llama.cpp or serving engine and same-quality A/B comparison |
| [llama.cpp server docs](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md) | Prompt caching, continuous batching, flash attention, slot cache, metrics | Benchmark on each STAR host, avoid sharing private KV state and avoid parallelism that increases user latency |
| [Long-running agent harness, Anthropic](https://www.anthropic.com/research/effective-harnesses-for-long-running-agents) | Explicit milestones and handoff artifacts between sessions | Reuse STAR MissionCheckpoint and safe worktrees; no infinite loops or implicit replay of writes |
| [Managed agents, Anthropic 2026](https://www.anthropic.com/research/managed-agents) | Separate reasoning from constrained tool execution | Preserve host-owned permissions and tool contracts; prompt instructions never raise capability |
| [OpenAI improvement loop, 2026](https://developers.openai.com/cookbook/examples/agents_sdk/agent_improvement_loop) | Real traces -> feedback -> tests -> candidate improvements | Build an evaluator-owned receipt adapter, then promote only independently checked candidates |
| [AgentLens, 2026](https://www.microsoft.com/en-us/research/publication/agentlens-revealing-the-lucky-pass-problem-in-swe-agent-evaluation/) | Passing patch can hide blind retries and faulty process | Evaluate exploration/implementation/verification order and artifact quality as well as pass/fail |
| [Skill-induced agent failures, 2026](https://www.microsoft.com/en-us/research/publication/agent-skills-can-be-harmful-an-empirical-study-of-skill-induced-failures-in-llm-agents/) | Extra skills can hurt correct behavior and throughput | Add a skill retirement/differential eval process, not hundreds of always-on context instructions |
| [Reward hacking of research agents, 2026](https://www.microsoft.com/en-us/research/publication/reward-hacking-challenges-oversight-of-autonomous-research-agents/) | Self-evaluation creates incentives to game tests | Never let candidate generators edit graders, holdouts, or independent outcome store |
| [AI agent reliability, Princeton HAL](https://hal.cs.princeton.edu/reliability/) | Reliability and safety need more than headline accuracy | Track consistency, fault recovery, latency, regressions and human trust alongside correctness |
| [SURE, Microsoft Research 2026](https://www.microsoft.com/en-us/research/publication/the-sure-framework-social-intelligence-for-human-agent-collaboration/) | Social interaction needs sensing, understanding, remembering, engagement | Improve listening and context-based timing without pretending STAR is human or inferring feelings as fact |
| [Voice full-duplex benchmark, ICML 2026](https://proceedings.mlr.press/v306/ray26a.html) | Speech agents may perform far worse than text agents | Voice quality needs grounded task completion, interruption tests, and actual user studies |
| [Adaptive voice turn-taking, Interspeech 2026](https://www.amazon.science/publications/adaptive-turn-taking-for-real-time-multi-party-voice-agents) | Role-based turn-taking reduces unhelpful interruptions in studied settings | Extend existing star/voice/turn.py; do NOT replace its tested VAD/endpointer with an unbenchmarked model |
| [V-JEPA 2, Meta 2025](https://ai.meta.com/blog/v-jepa-2-world-model-benchmarks/) | Predictive representations help agents infer physical dynamics from video | Longer-term optional perceptual learning for game environments; no plug-and-play humanoid player |
| [Genie 3, DeepMind](https://deepmind.google/models/genie/) | Controllable simulated worlds could generate experience | Future research, not a locally deployable simulator for this 8 GB PC |
| [Experience faithfulness, ICML 2026](https://proceedings.mlr.press/v306/zhao26aw.html) | Agents can ignore or misuse compressed experience | Causal tests must verify that lessons actually change behavior on unseen tasks |
| [AgentAbstain](https://agentabstain.github.io/) | Correct refusal/abstention is a separate agent skill | STAR should know when to ask, defer, require evidence, or stop, even when the task seems plausible |

Each cited research result is specific to its authors' setup. No paper here
proves unbounded recursive self-improvement or that a small local model
automatically outperforms frontier models.

## Newly implemented: cognitive governor v0.1

Files: `star/cognitive_governor.py` and
`tests/test_cognitive_governor.py`. Python stdlib only; no new packages.

1. `GradeReceipt`: takes **host-authenticated, independently graded**
   development-task metadata, identifying project, task family, model,
   revision, stable case and run IDs, pass/fail/error, time, verifier
   class, and SHA-256 artifact reference. No raw prompts, user chats,
   model reasoning, cloud calls or URLs are stored. A SHA-256 string
   alone does not authenticate the evidence.
2. `OutcomeLedger`: bounded SQLite ledger, immutable rows, idempotent
   repeated receipts, conflicting-receipt veto, project/model/revision
   isolation, 90-day advice window. First independently graded
   attempt per **distinct case** prevents 50 retries and eventual lucky
   passes on one item from masquerading as reliable first-try success.
   Holdouts are refused.
3. `OutcomeSummary`: observed outcome counts, median/p95 runtime and
   conservative Wilson lower bound. That bound describes an observed
   collection of *related* tasks, NOT Star's probability of completing
   the next arbitrary task.
4. `advise_effort`: suggests `FAST_VERIFY`,
   `STANDARD_VERIFY`, `BEST_OF_N_VERIFY`, `GET_EVIDENCE`, or
   `OWNER_REVIEW`. Every suggested execution path still requires
   real verification, and high-stakes/irreversible action still needs
   human approval. Extra candidates require real time and parallel
   slots; the function starts **zero** agents itself.
5. `suggest_practice`: ranks **operator-approved development families**
   using actual failures and absence of verified coverage, without
   writing prompts, opening hidden tests or starting Studio.
6. `advise_initiative`: a quiet, consent-based decision helper for
   evidence-linked progress notices. Suppresses ungrounded idle chatter,
   interruptions, quiet-hour events and unapproved proactivity.
   It does NOT send notifications or record microphone audio.

### Read-only report

```bash
python -m star.cognitive_governor \
  --db "/path/to/your/local/STAR/cognitive.sqlite3" \
  --project MyTestProject --family luau --model star-fast --revision r1
```

The report does not create the database when it is missing. Only trusted
host code should call `OutcomeLedger.record_grade(...)` with externally
validated evidence; NEVER expose that function as a model tool. Keep
the SQLite database outside the repository and public artifacts.
Never submit private project outcomes or raw traces to PR comments.

### How a future host adapter should invoke this safely

```python
from pathlib import Path
from star.cognitive_governor import (
    GradeReceipt, OutcomeLedger, EffortBudget, advise_effort,
)

# HOST-ONLY code, after independent evaluator confirms artifact digest.
ledger = OutcomeLedger(Path(user_profile) / "cognitive.sqlite3")
ledger.record_grade(GradeReceipt(
    project="OwnedTestProject", family="luau", model="star-fast",
    revision=verified_model_revision, run_id=verified_eval_run_id,
    case_id=verified_development_case_id, result=verified_grade,
    elapsed_ms=measured_elapsed_ms, verifier="independent_eval",
    evidence_sha256=verified_artifact_sha256,
))
history = ledger.summary(
    project="OwnedTestProject", family="luau", model="star-fast",
    revision=verified_model_revision,
)
suggestion = advise_effort(
    history, EffortBudget(model_calls=3, wall_seconds=45,
                          available_parallel_slots=2),
    stakes="low", external_verifier_available=True,
)
# Use only the advisory mode to choose preapproved *read-only* execution
# settings. Existing policy + external test gate retain final authority.
```

The SHA/revision/grade IDs above MUST originate from the evaluator or
operator, not LLM claims or caller-selected web text. Distinct cases
must be independently meaningful; stable aliases of the same task
should not count as new examples. The current module validates
structure and deduplicates; future adapters still need a trusted
provenance check.

## Next: make STAR smarter in measurable stages

### P0 — Connect evidence to real decisions

- Implement a host-only adapter from the existing signed/hashed
  evaluator results, after independently verifying the data format,
  exact source revision, task case IDs and sealed holdout separation.
- Add settings UI that shows why the governor recommended a
  fast/deep/evidence-required route. **Default OFF** until independent
  blinded task A/B demonstrates benefit.
- Benchmark against an unchanged same-model baseline: pass rates by
  family, unique unseen cases, 95th percentile completion time,
  human-reviewed game/UI quality, GPU/CPU/RAM, privacy boundary, and
  tool-call count. Reject if statistically inconclusive or if any
  protected canary regresses.

### P1 — Verified autonomous improvement, not unbounded retries

- Read approved objectives and failure-ledger summaries; propose
  1-3 capped self-play tasks with novel seeds and a sealed referee.
- Connect STAR's existing `best_of_n`, `studio_lab`,
  `skill_evolution_lab` and `eval_gate` only via the protected
  evaluator's host-verified receipts. Never give a generator its own
  holdouts, gate keys or grader code.
- Collect causal evidence: perturb a learned lesson or remove it on
  controlled development episodes; measure whether the skill helps
  unseen tasks without increasing wasted compute.
- Introduce a negative skill manager: skill-specific regression
  analysis and candidate retirement. More skills are not automatically
  more intelligence.
- If a task stalls (same failure repeated; no new independent evidence),
  stop, log why, and escalate instead of looping forever.
- Candidate changes stay in isolated branches/worktrees and draft PRs;
  no auto-merge or release.

### P1 — Faster on existing 8 GB VRAM plus CPU servers

- First measure CPU prefill, GPU decode, TTFT, p50/p95 full task
  latency, prompt-cache reuse, context length, KV occupancy and server
  load. Protect interactive work and avoid simultaneous heavy GPU
  model training, game rendering and streaming.
- Test warm caching, prompt prefix stability, quantization, optional
  flash attention, slot sizing and selective speculative decoding
  with a controlled same-quality baseline. Be careful: extra parallel
  processes or cache banks can slow the user.
- Route short/simple tasks to small models. Only spend 2-4 samples and
  independent verification when historical evidence and task risk
  justify that expense; never claim a constant speedup without a test.
- Track quality-adjusted accepted tasks/hour: the fastest *wrong*
  answer is not a speed improvement.

### P2 — More human-like without deceptive personhood

- Preserve STAR's existing voice `TurnDetector`, interruption
  controls, optional speaking styles, and project-scoped owner lessons.
  Add observable turn-taking, corrections, and short natural language
  **based on explicit preferences**, not hidden emotional profiling.
- Integrate social intelligence as a four-stage process: permitted
  signals -> context/intent uncertainty -> scoped recall -> appropriate
  interaction. Don't assert private feelings or simulate human status.
- Opt-in proactive notices only for verified job completions, failed
  checks needing attention, approved scheduled reviews, and decisions
  requiring permission. Honor quiet hours and "user speaking" state.
- For the long-term game-streaming companion, research vision-action
  loops, real gameplay telemetry, short-term scene state, motor skill
  curricula, expressive animation and full-duplex voice. Defer
  autonomous streaming/play control until the owner authorizes that
  phase and the intended machine is ready.
- Evaluate interruption false positives, speaker attribution, speech
  end-to-first-audio latency, task success, conversational appropriateness,
  privacy and source-grounded claims. Audio polish does not imply AGI.

## Release gate and explicit non-claims

- Current code tests **advisory mechanics only**, not task-quality gains,
  higher neural intelligence, self-training, Studio game completion,
  autonomous research agents or interactive human-like behavior.
- Never label self-reported/model-generated scores as external truth.
- Never allow agent-produced candidate changes to modify the test
  oracle, approval policy, sealed holdout or deployment authorization.
- Require real Windows and Brain 1/2 runtime trials in addition to
  Python/React automated checks before shipping.
- Recommended next measurable milestone: compare identical tasks
  with governor advisories OFF vs ON, using the same models and
  resource ceilings, with the independent grader controlling both.

## Implemented extension: controlled import of existing STAR evaluation reports

Files: `star/cognitive_evals.py`, `tests/test_cognitive_evals.py`.
A second offline-tested host/owner entry point makes the governor usable with
existing `star.eval_runner/1` JSON reports without editing the grader.
**Preview is the default. No stored learning or behavior change occurs unless
the operator independently reviews evaluator provenance and explicitly records.**

```bash
sha256sum evals/results/control-nopacks.json
python -m star.cognitive_evals \
  --file evals/results/control-nopacks.json \
  --approved-sha256 <digest-from-operator-review> \
  --project OwnedTestProject
# Read-only preview: suite/model/revision/number of checkable cases

# ONLY after independently verifying source, grader and intended evaluation:
python -m star.cognitive_evals \
  --file evals/results/control-nopacks.json \
  --approved-sha256 <digest-from-operator-review> \
  --project OwnedTestProject \
  --db <private-profile-path>/cognitive.sqlite3 \
  --record-reviewed
```

The importer checks the pinned full-file hash, clean app commit, known runner
identifier, config fingerprint, known **development** suite, exact case selection,
finite timings and verdict consistency. It intentionally refuses holdouts and
incomplete or contradictory reports. Raw reports and private addresses are
**never stored** in the evidence ledger. However, a matching SHA only proves
the bytes match the expected digest; it cannot prove the grader was authentic,
tests were legitimate, or the operator looked at them.

**Real-file smoke check (read-only):** the existing
`evals/results/control-nopacks.json` preview validated six development-task
records. `baseline-v2.json` and `control-creation.json` were rejected due
to mismatched selected-task and result-case sets. Neither was imported.
That is deliberate fail-closed handling, not a claim they are corrupted.

**Offline checks:** `python3 -m unittest discover -s tests -p 'test_cognitive_*.py' -v`
ran **33 tests successfully** on an isolated Linux checkout. Still requires
independent real runtime A/B to prove gains.

## Why first-attempt reliability, not cherry-picked success

[Anthropic's agent evaluation guidance](https://www.anthropic.com/research/demystifying-evals-for-ai-agents)
distinguishes single-attempt performance from best-of-k capability and
repeat-run reliability. In this governor, the FIRST externally graded run for
each distinct development case is the reliability observation in a given
model/revision. Future revised methods are compared under a new version.
This prevents an agent from turning one failure followed by 40 retries into
a fabricated 100% success statistic. Repeated-run robustness and pass^k
should be reported separately by the independent evaluation harness.
