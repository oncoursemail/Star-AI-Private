# Litha verifier-first reinforcement loop

This design adds a bounded **task-time self-improvement loop** to the existing STAR/Litha learning stack.

It is intentionally not unrestricted recursive self-modification and it does not change model weights by itself.

## Why this layer exists

The repository already has a slower outer loop:

```
practice -> score -> lesson candidate -> paired held-out gate -> owner review
```

That is good for durable learning, but it does not help enough on a single hard task. The new inner loop is:

```
generate N diverse attempts
        |
        v
independent host verifier
        |
   +----+-------------------+
   | verified              | failed
   v                       v
 return winner       critique evidence
                            |
                            v
                  re-solve / re-explore K ways
                            |
                            v
                     verify again
                            |
                   pass / stagnate / budget cap
```

The important property is **verifier-first reinforcement**: the model does not get to award itself success.

## Research synthesis

Litha should combine several established ideas rather than copying one paper literally:

- **Self-Refine**: iterative feedback and refinement can improve task-time results without retraining.
- **Reflexion**: convert trial feedback into explicit linguistic reflection and reuse it on the next attempt.
- **Best-of-N / GRPO intuition**: generate a group of candidates and compare relative quality instead of trusting one sample.
- **CURE-style re-exploration**: critique an error, then re-derive a solution rather than endlessly patching the first answer; this reduces anchoring.
- **ICRL direction**: later, verified critique-to-improvement trajectories can become training candidates so the base solver internalizes useful critique patterns.
- **Agent-loop engineering**: reliability depends on termination, verification, context control, recovery and cost budgets as much as on the model.

## Implementation

Core module: `star/reinforcement_loop.py`

The loop is model/provider agnostic. Callers inject four functions:

1. `generate(task, seed)` — produce diverse initial candidates.
2. `verify(task, candidate)` — trusted host-owned checks returning a normalized score, pass bit and evidence.
3. `critique(task, candidate, verification)` — explain the failure using verifier evidence.
4. `refine(task, candidate, critique, variant)` — re-solve using a different strategy.

The result contains every attempt, immutable SHA-256 identifiers, verifier evidence, score, ancestry and stop reason.

## Promotion rules

A result is considered verified only when all of these hold:

- verifier output is marked trusted;
- verifier returns `passed=True`;
- score reaches the configured `pass_score`;
- candidate is within the configured size budget;
- it is a novel candidate, not a duplicate retry.

A model saying “tests passed” is not evidence.

## Default compute policy

Current safe defaults:

- 4 initial candidates;
- at most 3 refinement rounds;
- 2 refinements per round;
- stop after two stagnant rounds;
- stop immediately on a trusted passing result.

This bounds worst-case generation to 10 unique candidates per task before duplicate elimination. Higher Best-of-N settings can be enabled for difficult tasks when hardware permits.

## Recommended Litha integration

### Coding / Roblox

Use a layered verifier score:

- syntax/type/lint result;
- unit or regression tests;
- Luau sandbox / Studio Lab execution;
- API validity;
- task-specific assertions;
- optional visual/gameplay checks.

Hard failures should cap the score below the promotion threshold.

### Research

Use evidence coverage, source authority, contradiction checks, freshness and citation validity. Do not let the same model both invent a claim and act as its only verifier.

### UI / visual work

Use structured requirements plus image/render inspection. Keep aesthetic critic feedback separate from hard functional requirements so one does not hide the other.

## Relationship to night school

The inner loop should emit a compact trajectory:

```json
{
  "task": "...",
  "winner_sha256": "...",
  "verifier": "studio_lab",
  "score": 0.97,
  "rounds": 2,
  "failure_evidence": ["...", "..."],
  "passed": true
}
```

Only **verified** trajectories should be eligible for the existing durable-learning pipeline. The outer paired/held-out gate remains authoritative.

This creates a two-speed system:

- **fast loop:** improve the current answer now;
- **slow loop:** learn only changes that survive independent evaluation later.

## Future weight-learning path

If Litha later trains a local model, do not directly reinforce raw self-scores. Prefer verifiable rewards from compilers, tests, sandboxes, deterministic task checks, or trusted external evaluators. Store critique/refinement trajectories separately, deduplicate them against holdouts, and pass them through the repository's existing rights/provenance controls in `star/verified_training.py`.

A practical progression is:

1. inference-only loop;
2. collect verified trajectories;
3. train a critic or reranker;
4. LoRA/SFT on verified improved answers;
5. optional GRPO/RLVR experiment in an isolated training branch;
6. compare against a frozen baseline and sealed holdout before promotion.

## Failure modes to defend against

- **Reward hacking:** candidate exploits a weak checker. Use multiple independent checks and hidden assertions.
- **Self-confirmation:** generator and verifier share the same unsupported assumption. Favor executable or external evidence.
- **Anchoring:** every refinement patches the same bad approach. Require variants to re-solve from first principles.
- **Loop bloat:** repeated critique consumes context and latency. Keep concise evidence and hard round/token budgets.
- **Benchmark contamination:** never feed sealed holdouts or evaluator internals into generation/training.
- **Regression by learning:** a local success is not a global improvement. Durable changes still need paired held-out evaluation.

## Success metrics

Track these separately:

- pass@1;
- pass@N before refinement;
- pass after reinforcement loop;
- average verifier calls per solved task;
- latency/token cost per solved task;
- regression rate on unrelated held-out tasks;
- fraction of failures caused by verifier weakness vs model weakness.

The objective is not “more loops.” It is **more independently verified correct work per unit of compute**.
