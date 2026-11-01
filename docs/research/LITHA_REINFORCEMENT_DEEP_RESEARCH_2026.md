# Litha reinforcement architecture — deep research synthesis (2026)

Status: implementation plan plus first production primitives on `feature/litha-reinforcement-loop`.

This document goes beyond a simple "LLM retries its answer" loop. The target is a verifier-first,
two-speed self-improvement system that can improve a difficult answer immediately, collect trustworthy
experience, and only later change durable behavior when an independent holdout says the change actually helped.

## Executive design

Litha should use **verification as a first-class systems primitive**.

```
                         +------------------------------+
user/task -------------->| difficulty + risk router     |
                         +---------------+--------------+
                                         |
                              adaptive compute budget
                                         |
                 +-----------------------v-----------------------+
                 | diversified generator / Best-of-N            |
                 | different seeds, strategies, agents, models  |
                 +-----------------------+-----------------------+
                                         |
                                         v
                 +-----------------------------------------------+
                 | verifier panel                                |
                 | hard tools + tests + API + safety + judges   |
                 | required checks, vetoes, disagreement block  |
                 +----------------------+------------------------+
                                        |
                         verified ------+------ failed
                            |                       |
                            v                       v
                      return winner          compact evidence
                                                    |
                                                    v
                                             critique / hint
                                                    |
                                                    v
                                            fresh re-exploration
                                                    |
                                                    +----> verify again
                            |
                            v
                 verified trajectory store
                            |
                  +---------+----------+
                  |                    |
                  v                    v
             SFT candidate        preference pair
                  |                    |
                  +---------+----------+
                            |
                    decontamination / rights
                            |
                    frozen outer evaluation
                            |
                      promote or reject
```

The architecture deliberately separates three concepts that are often mixed together:

1. **Inference-time reinforcement** — spend extra compute now to get a better answer.
2. **Experience curation** — save only independently verified trajectories as possible training data.
3. **Weight learning** — optional later GRPO/RLVR/SFT/DPO experiments, isolated behind stronger gates.

A local success is not proof that the system became globally smarter. Durable promotion must still be decided by
a protected baseline and holdout.

---

## Research conclusions that matter most for Litha

### 1. Reliable verification is the bottleneck, not raw generation count

DeepSeek-R1 shows that rule-based verifiable rewards can induce useful reflection, verification and strategy
adaptation. It also explicitly warns that learned/model-based rewards are more vulnerable to reward hacking.
For Litha, executable checks should therefore outrank model opinions whenever a task permits them.

Practical ordering:

1. deterministic constraints / parser;
2. compiler, type checker, linter;
3. unit and regression tests;
4. mutation / adversarial sanity checks;
5. sandbox or real environment execution;
6. API/schema validation;
7. independent learned judges only for dimensions that tools cannot measure.

Source:
- https://www.nature.com/articles/s41586-025-09422-z

### 2. Process reward should measure *progress*, not merely "nice reasoning"

The ICLR 2025 "Rewarding Progress" work argues that an intermediate step is useful when it increases the
probability of eventually reaching a correct answer. This is a better fit for engineering agents than rewarding
verbose chain-of-thought.

For Litha, process progress should be based on **observable external state deltas**, for example:

- compiler errors: 8 -> 2 -> 0;
- passing assertions: 4/12 -> 10/12 -> 12/12;
- mutation kill rate: 0.42 -> 0.83;
- invalid Roblox API references: 5 -> 0;
- Studio playtest failures: 3 -> 1 -> 0;
- unsupported research claims: 7 -> 2 -> 0;
- accessibility violations: 6 -> 1 -> 0.

Do **not** require storing private internal chain-of-thought. The useful training artifact is
`state_before -> action/output -> verifier evidence -> state_after`.

Source:
- https://openreview.net/pdf?id=A6Y7AqlzLW

### 3. Test-time compute must be adaptive

Scaling test-time compute optimally found that the best strategy changes with prompt difficulty and reported
more than a 4x efficiency gain over a fixed Best-of-N baseline in its math experiments.

That means Litha should not always run 8 agents or 4 critique rounds.

Starting policy:

| Estimated pass@1 | Search policy |
| --- | --- |
| >= 0.85 | 2 candidates, 1 repair round |
| 0.45–0.85 | 4 candidates, up to 3 rounds |
| 0.12–0.45 | 6 candidates, up to 4 rounds |
| < 0.12 | cap the attempt; avoid a compute sink and escalate strategy/tools |

Increase scrutiny for high-risk changes; reduce it when verifier cost or latency pressure is high.

This is implemented as the first heuristic in `star/reinforcement_verifiers.py`; it should later be calibrated
from Litha's own telemetry rather than treated as a universal formula.

Source:
- https://openreview.net/pdf?id=4FWAwZtd2n

### 4. Critique must cause re-exploration, not endless patching

CURE (ACL 2026 Outstanding Paper) trains solving, critiquing and guided re-exploration together. Its especially
useful design insight is to discard the incorrect initial solution during re-exploration to reduce anchoring.

Litha should maintain two repair modes:

- **local repair** for obvious mechanical failures: syntax, typing, deprecated API;
- **fresh solve** when semantic tests keep failing or progress stalls.

After one or two failed local repairs, the system should feed the task plus compact failure evidence to a fresh
solver context, not the entire failing transcript.

Source:
- https://aclanthology.org/2026.acl-long.1321/

### 5. Multiple weak verifiers are better than pretending one judge is an oracle

WEAVER (NeurIPS 2025) shows that verification itself can be scaled by combining imperfect verifiers, and that
weighted ensembles can outperform naive averaging.

The first Litha implementation therefore includes:

- required checks;
- weighted verifier scores;
- hard veto thresholds;
- minimum trusted-verifier count;
- disagreement detection;
- evidence hashes and excerpts.

Longer term, Litha should learn verifier reliability per domain. A Luau compiler should have very high authority
for syntax, but zero authority over whether a UI looks polished; a visual judge has the inverse limitation.

Sources:
- https://papers.nips.cc/paper_files/paper/2025/hash/715f48023c26ad210321a4c0da67f27c-Abstract-Conference.html
- https://arxiv.org/abs/2506.18203

### 6. A rising RL benchmark does not prove the reward is meaningful

The 2026 ICML paper "Spurious Rewards" is an important warning: GRPO improved one Qwen math model substantially
even when rewards were random or negatively correlated with correctness. The paper attributes this to clipping
bias amplifying strong pretrained behaviors.

Litha must therefore measure **true held-out capability**, not celebrate rising training reward.

Mandatory checks for every RL experiment:

- frozen pre-training baseline;
- sealed tasks never visible to the policy or reward builder;
- at least one metric recomputed independently of the training reward;
- cross-domain regression suites;
- reward ablation / shuffled-reward control for serious experiments;
- compare more than one checkpoint, not just "before vs final";
- report reward, true evaluator score and generalization separately.

Source:
- https://proceedings.mlr.press/v306/shao26d.html

### 7. Agentic reward hacking is a systems problem

An agent that can edit files, tests, logs and evaluators has more ways to "win" without solving the task.
The 2026 reward-hacking literature specifically highlights evaluator gaming and environment-level tampering.

For Litha:

- evaluator source and sealed tests must be read-only to the policy;
- reward calculation should run in another process/service;
- the model must not be able to edit the gate that promotes its own output;
- independent recomputation should happen after a candidate exits the agent workspace;
- test mutation and hidden counterexamples should detect brittle hacks;
- sensitive evaluator details should not be copied into model-facing training text;
- protected paths stay protected even during autonomous self-improvement.

Source:
- https://link.springer.com/article/10.1007/s44163-026-01980-z

### 8. Tool/environment RL is now practical enough to plan for

Hugging Face TRL's current GRPO tooling supports agent rollouts with tools and stateful environments. A future
Litha trainer can therefore expose a narrow sandbox API (compile, analyze, run tests, inspect allowed environment
state) rather than training only on static text.

This is a future training component, not a reason to put the current desktop agent directly in control of its
training environment.

Source:
- https://huggingface.co/docs/trl/grpo_trainer

---

## The Litha two-speed loop

### Fast loop: current-task improvement

Goal: maximize independently verified success per unit of latency/compute.

```
route difficulty
-> sample diverse solutions
-> cheap verifier pass
-> expensive checks only on contenders
-> choose verified winner if available
-> otherwise convert failure evidence to concise critique
-> re-solve using local repair or fresh re-exploration
-> stop on pass / stagnation / cost budget
```

This should run during normal coding/research/build tasks.

### Slow loop: durable learning

Goal: only retain behaviors that generalize.

```
verified fast-loop trajectory
-> provenance / rights / secret scan
-> decontamination
-> SFT and/or preference candidate
-> optional training job
-> compare frozen baseline vs candidate
-> protected development validation
-> sealed holdout
-> paired statistics
-> owner-visible promotion / rollback
```

The existing Night School and verified-training code already provides much of this outer structure.

---

## Domain reward design

### Roblox / Luau / coding

Hard evidence should dominate.

Suggested reward vector:

| Signal | Role |
| --- | --- |
| parse/format | hard prerequisite |
| compile | hard veto |
| type analysis | hard veto when task promises typed correctness |
| API validity/current API | required |
| deterministic unit tests | primary correctness |
| regression tests | primary correctness |
| repeated-run determinism | reliability |
| mutation kill rate | detects weak tests |
| security/trust checks | veto on security-sensitive task |
| Studio Lab playtest | environment correctness |
| visual screenshot checks | UI/gameplay quality adjunct |
| latency/memory budget | optimization objective after correctness |

Do not collapse all of these into one opaque judge. Keep component scores visible and let required checks veto.

### Research

Use a claim-evidence graph:

```
claim
 -> citation exists?
 -> source actually contains the claim?
 -> authority/primary-source score
 -> publication/freshness requirement
 -> contradiction search
 -> numerical/date consistency
```

A language-model judge can help classify nuanced support, but it should not be the sole verifier for a claim it
or a sibling model just invented.

### UI / design

Split **functional correctness** from **taste**.

Functional panel:
- requested components exist;
- layout fits target resolutions;
- no overlap/clipping;
- keyboard/accessibility checks;
- contrast;
- interaction states;
- performance budgets.

Aesthetic panel:
- visual hierarchy;
- spacing consistency;
- typography;
- animation timing;
- style adherence;
- comparison against owner-approved references.

Aesthetic scoring can use vision/judge models, but hard functional failures must still veto promotion.

### Agent/computer-use tasks

Reward completion by external state, not by the agent narrating success.

Examples:
- target file hash changed as expected;
- application reports expected state;
- UI element visibly exists;
- command exit status + postcondition;
- independent re-open/re-read confirms persistence.

---

## Counterexample-driven verification

One major future upgrade should be an **adversarial verifier agent** whose job is not to solve the task but to find
a small input that breaks a proposed solution.

For code:

1. infer preconditions and invariants from the task;
2. generate edge cases;
3. run them in an isolated sandbox;
4. minimize any failing case;
5. add the minimized case to temporary verification;
6. never silently convert it into a permanent test without the normal review/decontamination path.

This creates a stronger signal than asking a judge "is this correct?".

---

## Observable process advantage for Litha

A future `ProgressState` can contain only externally measurable fields:

```json
{
  "compile_errors": 0,
  "type_errors": 1,
  "tests_passed": 11,
  "tests_total": 12,
  "mutation_kill_rate": 0.83,
  "invalid_api_refs": 0,
  "security_failures": 0
}
```

Then:

```
progress_reward = V(state_after) - V(state_before)
```

where `V` estimates future success from verifier state, not from hidden reasoning prose.

This can drive:

- which branch of a search tree to expand;
- whether to continue local repair;
- which trajectories become preference pairs;
- eventually token/action credit assignment in a training experiment.

---

## Training-data products

The reinforcement loop can produce several distinct datasets. Keep them separate.

### Verified SFT

Only final answers with trusted passing evidence.

Use for:
- teaching stable correct patterns;
- distilling expensive multi-agent/search behavior into the fast local model.

### Preference pairs

`chosen = verified winner`
`rejected = strongest failed candidate`

Require a meaningful verifier margin. Avoid arbitrary pairs where both answers are almost tied.

Use for:
- DPO/IPO-style experiments;
- critic/reranker training.

### Repair trajectories

Keep metadata such as:
- failing gate;
- before/after output hashes;
- verifier-state delta;
- repair round;
- whether the repair generalized.

Do not blindly include hidden evaluator source or sealed test text.

### Failure bank

Failures are valuable even if no correct answer was found:
- recurring type errors;
- API hallucinations;
- UI layout failures;
- tool misuse;
- incomplete research evidence.

Use them for curriculum/task generation, not as positive examples.

---

## Real GRPO / RLVR roadmap

Do not begin by online-RL training the largest Litha model.

### Stage A — inference loop

Already started in this branch.

Benefit:
- immediate quality gains;
- no weight instability;
- produces measurement data.

### Stage B — critic / verifier distillation

Train a small fast verifier or reranker from trusted panel labels.

Benefit:
- reduce the cost of running a large verifier ensemble on every candidate.

### Stage C — SFT on verified winners

Use project-disjoint data and existing provenance/decontamination gates.

### Stage D — preference optimization

Use high-margin verified winner/failure pairs.

### Stage E — small-model GRPO/RLVR experiment

Build a narrow environment around verifiable tasks. A training rollout should get capabilities such as:
- read task;
- submit candidate;
- compile/analyze;
- run a limited verifier;
- receive structured observations.

The final reward is independently recomputed.

Use TRL or Unsloth for the first single-GPU experiments; use a distributed stack only when hardware actually
requires it.

### Stage F — agentic environment RL

Only after the reward and isolation design survives adversarial testing.

---

## RTX 4060 8 GB strategy

The 8 GB card is valuable, but Litha should use it strategically.

For the main local assistant:
- prioritize quantized inference;
- Best-of-N/reinforcement search can reuse one loaded model sequentially or in micro-batches;
- verifier tools such as compiler/tests mostly consume CPU rather than VRAM;
- distill successful search behavior so common tasks return to pass@1.

For weight-level RL:
- start with genuinely small models and short contexts;
- prefer LoRA/QLoRA;
- keep generation count small during feasibility tests;
- benchmark peak VRAM before committing to a model size;
- use CPU/RAM for datasets/verifiers where possible.

An 8 GB desktop GPU should be treated as a **research node for small-model RL and a strong inference node**, not
as if it were a multi-GPU RL cluster.

---

## Reinforcement-loop anti-hacking checklist

A candidate may be promoted only if:

- [ ] verifier is outside the candidate's write boundary;
- [ ] required deterministic checks pass;
- [ ] no veto check fires;
- [ ] verifier disagreement is below threshold or escalated;
- [ ] evidence is recorded/hashable;
- [ ] candidate cannot modify evaluator/test files;
- [ ] hidden/holdout tests were not inserted into model context;
- [ ] result survives independent recomputation;
- [ ] no credential/private-data leakage is present;
- [ ] durable training data passes decontamination;
- [ ] weight-level promotion beats a frozen baseline on protected validation;
- [ ] sealed holdout does not regress;
- [ ] unrelated capability regressions are checked.

---

## Metrics Litha should log

### Answer quality
- pass@1;
- pass@N before critique;
- solve rate after repair;
- solve rate after fresh re-exploration;
- final verified score.

### Efficiency
- generated candidates per solved task;
- verifier calls per solved task;
- tokens per solved task;
- wall-clock latency;
- GPU seconds / CPU seconds;
- percentage of easy prompts that unnecessarily entered the loop.

### Verifier health
- false-promotion rate;
- false-rejection rate;
- verifier disagreement;
- per-verifier calibration;
- reward-hack/counterexample discovery rate;
- percentage of promoted answers later failing stronger tests.

### Learning
- outer holdout win/loss/tie;
- regression rate by domain;
- SFT/DPO/GRPO gain over the *same* frozen baseline;
- shuffled/spurious-reward control where appropriate;
- data efficiency (verified wins per training token).

### Repair
- repair success by initial failure gate;
- progress per round;
- fraction of no-change repairs;
- marginal gain from round 1, 2, 3;
- fresh-solve success after local-repair stagnation.

---

## Concrete rollout for this repository

### Phase 0 — branch implementation (now)

Implemented:
- verifier-first bounded task loop;
- trusted evidence requirement;
- verifier panel with veto/disagreement;
- adaptive compute heuristic;
- verified SFT/preference trajectory builder;
- opt-in training-generator repair loop;
- tests for these primitives.

### Phase 1 — observe-only integration

Wire the reinforcement engine to selected coding tasks but do not alter answers yet.

Log:
- what it would have selected;
- verifier agreement;
- candidate count;
- latency;
- pass@1 versus selected pass.

This produces calibration data without user-facing risk.

### Phase 2 — training-generator repair pilot

Set:

```bash
STAR_TRAIN_SOLVER_REPAIR_ROUNDS=1
```

on the isolated server only after review.

Compare:
- keep rate;
- tokens per kept example;
- which gates repairs fix;
- whether mutation/decontamination quality changes;
- number of second-round successes.

Do not enable more repair rounds merely because they produce more examples.

### Phase 3 — live task-time coding loop

Start with tasks that have strong verifiers:
- Luau;
- Python/Rust unit-tested code;
- structured data transformations.

### Phase 4 — counterexample verifier + progress scoring

Add external-state progress vectors and adversarial test generation.

### Phase 5 — verified trajectory bank

Feed only independently verified, decontaminated candidates into the existing verified-training path.

### Phase 6 — small-model RL pilot

Run an isolated GRPO/RLVR experiment against a narrow, reproducible tool environment.

### Phase 7 — promotion

A trained checkpoint is only eligible for Litha if it beats the frozen baseline under the repository's protected
evaluation process without unacceptable regressions or reward-hacking evidence.

---

## Current implementation files

- `star/reinforcement_loop.py` — bounded Best-of-N / verify / critique / re-explore engine.
- `star/reinforcement_verifiers.py` — verifier ensembles, vetoes, disagreement and adaptive compute.
- `star/reinforcement_trajectory.py` — verified SFT and preference-data candidate builders.
- `tests/test_reinforcement_loop.py`
- `tests/test_reinforcement_verifiers.py`
- `tests/test_reinforcement_trajectory.py`
- `server/training/startrain/config.py` — opt-in repair budget.
- `server/training/startrain/prompts.py` — compact verifier-feedback repair prompt.
- `server/training/startrain/loop.py` — retry only solution-controlled failures and re-run the same gates.
- `server/training/tests/test_loop.py` — repair-loop test.

The server repair loop intentionally does **not** expose or repair:
- decontamination failures;
- near-duplicate failures;
- weak/broken generated tests (G4);
- evaluator source;
- sealed evaluation tasks.

---

## Research index

Primary references used for this design:

1. DeepSeek-R1 — RL with verifiable/rule rewards and GRPO:
   https://www.nature.com/articles/s41586-025-09422-z
2. Rewarding Progress — process rewards as progress:
   https://openreview.net/pdf?id=A6Y7AqlzLW
3. Scaling LLM Test-Time Compute Optimally:
   https://openreview.net/pdf?id=4FWAwZtd2n
4. CURE — critique-driven re-exploration:
   https://aclanthology.org/2026.acl-long.1321/
5. WEAVER — combine weak verifiers:
   https://papers.nips.cc/paper_files/paper/2025/hash/715f48023c26ad210321a4c0da67f27c-Abstract-Conference.html
6. Spurious Rewards — why reward curves alone are not proof:
   https://proceedings.mlr.press/v306/shao26d.html
7. Reward-hacking survey for agentic LLM systems:
   https://link.springer.com/article/10.1007/s44163-026-01980-z
8. Hugging Face TRL GRPO agent environments:
   https://huggingface.co/docs/trl/grpo_trainer
9. Existing repository architecture:
   `docs/SELF_LEARNING_LOOP.md`, `server/training/README.md`, `star/verified_training.py`.

## Bottom line

The strongest version of a "reinforcement loop" for Litha is not one model repeatedly telling itself to improve.

It is a **search + verification + feedback + re-exploration + evidence + protected-learning system** where the
generator is allowed to be creative, the verifier is difficult to game, compute is spent where it matters, and
only changes that survive independent evaluation become durable behavior.
