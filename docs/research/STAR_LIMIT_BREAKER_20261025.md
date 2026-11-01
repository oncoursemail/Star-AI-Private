# STAR Limit Breaker — evidence-first autonomous problem solving

**Design snapshot:** 2026-10-25. **Status:** engineering plan plus a small, tested selection fix;
not a deployed autonomous learner or new foundation model. **Base:** `star/next`.
No weights changed, no policy bypass, no automatic promotion, and no Studio or Blender
live run is claimed here.

## The key change in thinking

STAR should not equate "think harder" with "spend more inference tokens." Measure
**verified useful results per unit of time, memory and risk**. When something fails,
STAR should change its *approach* using observations, not simply retry the same
prompt with more confidence. A finite GPU cannot exceed its memory or compute limits;
STAR can, however, avoid unnecessary work, cache reusable observations, choose more
appropriate methods and delegate difficult tests to an authorized second worker.

The existing `skill_evolution_lab.py`, `frontier_lab.py`, `oracle/`,
`failure_ledger.py`, `verify_ladder.py`, `mission_checkpoint.py`,
`selfplay_curriculum.py`, `agent_resource_planner.py`, and Studio tooling provide
foundations. **Extend those systems, do not create a parallel agent stack.**

## Seven high-leverage research directions

### 1. Constraint compiler: explain the exact obstacle before seeking alternatives

Build one typed, reviewable record when a task stalls:

```text
Goal              "Create a polished 3v3 Roblox arena with no collisions"
Observed outcome  2 overlapping props in a measured scene snapshot
Evidence          scene hash, inspector version, object paths, bounding boxes
Constraint type   geometry, capability, resource, uncertainty, access, or policy
Hard boundaries   ownership, allowed Studio place, time/RAM/VRAM, approvals
Possible routes   move one prop, resize preserving anchors, regenerate segment
Falsifying probe  inspect all pairs after a proposed move
Reconsider when   object count, rig, camera, world scale or tool version changes
```

A policy restriction is **never** a puzzle to evade. The compiler searches only
within authorized alternatives. Do not store a model's suggested cause as proven
until a separate reproduction distinguishes it from competing causes.

*Implement by extending existing failure ledger and checkpoint contracts, not
by allowing a model-written tool to set policy or mutate tasks.*

### 2. Causal counterexample search: learn from the smallest reproducible failure

For each failed task, form multiple plausible explanations, then select the
cheapest *discriminating* check. Example: GUI text clips only at narrow widths.
Instead of redrawing all UI, render the same screen at two widths with fixed
font, content and layout. Vary one parameter at a time. A verified diagnosis
becomes a scoped lesson; a plausible explanation without proof stays a proposal.

Use property-based and metamorphic checks:
- **Roblox:** changing player count should not duplicate rewards; rerunning
  a save must not duplicate an inventory transaction.
- **Building:** object transforms must preserve attachment, avoid destructive
  overlap, reject z-fighting and place required props in the expected region.
- **UI:** resizing to known viewports must not overflow, overlap keycaps, or
  lose contrast; UI remains native/editable, not a screenshot.
- **Animation:** clips must preserve rig identity and contact constraints across
  scale, retiming and repeated playback.

A generated test is *not independent evidence* unless the trusted evaluator
approves the check and executes it in the correct isolated environment.

### 3. Evolution portfolio: compare candidates against a real incumbent

AlphaEvolve's publicly described approach couples creative candidates with
automated evaluators and an evolving population. For STAR, apply the principle
narrowly to reviewed skills, tactics, prompts, and resource settings, not
unrestricted self-modifying application code.

**Implemented here:** `star/skill_evolution_lab.py` now evaluates the incumbent
on the development suite, supplies its diagnostic feedback to the proposer,
rejects candidates tested with a different evaluator/version or task count,
accepts only strictly better development scores into the winning slot, and
avoids sealed holdout calls when no such improvement is measurable. The
development suite must be fixed for all compared candidates. A 4/4 baseline
has no demonstrable correctness gain on that suite, so the search stops.

**Next improvement:** give independent evaluators an immutable case-set
fingerprint plus environment/model/suite version so equal task counts cannot
hide different cases. Keep the sealed holdout unseen until candidate selection
is frozen, and preserve the existing owner review and no-publish rules.

**Critical limitation:** development and holdout callback evidence is host-supplied;
this patch does not turn reported results into cryptographically proven runtime
evidence. Independent testing and CI still matter.

### 4. Cost-per-proof scheduler: spend compute where it changes the decision

Route ordinary chat, deterministic syntax checking, image analysis, Studio
playtest, and model deliberation through the existing resource planner. Each
step should record wall time, RAM, VRAM, cache hits, test coverage and whether
the output changed the final verified decision.

Candidate priority can use a conservative heuristic such as:
```text
value = (estimated_probability_of_useful_new_evidence * decision_impact)
        / (seconds + memory_contention_penalty + verification_cost)
```

These are *planning estimates*, not ground truth. Never use them to mark a task
passed; periodically calibrate estimates to observed outcomes. Prefer cheap
static tests before slow server execution or Studio rendering. Reserve GPU
work for uncertainty a cheap check cannot settle.

### 5. Interface contract graph: find failures that single tools miss

Build explicit interfaces between already working tools:
```text
Blender skeleton -> export -> Roblox rig -> animation -> rendered clip
Roblox model -> import -> placement -> collision -> client playtest
UI spec -> layout -> native instances -> multiple viewports -> visual review
```

Test units individually *and at transitions*. A mesh may be valid in Blender
but wrong-sized in Roblox. A Luau module may compile yet race in multiplayer.
A clean static UI image may be unreadable as native Roblox controls. Use
source/artifact hashes to verify that every step inspected the same revision.

Extend existing scene and animation quality tooling; do not add a replacement
Studio automation route. Owner-scoped private test places remain mandatory.

### 6. Scope-aware lesson inheritance: do not forget the counterexamples

Stored skill lessons need an environment, prerequisites, independent evidence,
known failures, revision, negative examples and a revalidation trigger.
A lesson from a single obby is not a universal architecture rule. STAR should
retrieve it only when the required conditions match, and re-check it when the
model version, engine, tool or runtime changes.

Use the existing project-scoped KnowledgeStore/review flow and keep unreviewed
model suggestions out of approved memory. Measure *rescued tasks minus
previously passing tasks harmed* on matched workloads.

### 7. Unknown-unknown detector: probe the boundary, not just the center

After a success, vary one dimension in a bounded disposable test: screen width,
concurrency, latency, missing inputs, character respawn, large scene count,
animation retiming or resource exhaustion. Save the minimal counterexample
and a reason to retry after a fix. Separate performance/security stress from
creative visual judgment; each needs a different evaluator.

A capability is **narrowly verified** only under the conditions actually
tested. Do not infer sentience, universal intelligence or indefinite
self-improvement from passing tests.

## Evidence contract for future experiments

Each independently reported observation should include `candidate_digest`,
`baseline_digest`, `suite_digest`, `environment_digest`, `evaluator_version`,
`task_family`, `input_revision`, `trial_index`, `outcome`, `wall_seconds`,
`peak_ram_mib`, `peak_vram_mib`, `blocked_reason`, `artifact_digest`,
`test_provenance` and `retest_trigger`. Unknown values must remain unknown,
not invented. This is a proposed future schema, not a claim that STAR records
all of it today.

Holdouts should be independently authored or periodically refreshed, reviewed
for underspecification and grading errors, and excluded from model-provided
examples. Quality improvements require paired baselines, repeated trials,
low regression risk, and a review before merge. Published coding benchmarks
alone are not a deployment gate: contaminated or flawed tests can reward
memorization or reject correct solutions.

## Phased implementation, anchored to existing code

1. **Completed on this branch:** evaluate original skill first, reject
   incomparable development results, skip needless sealed holdout. Focused
   server-side regression tests: 13 passed on Python 3.12 environment.
2. **Next:** add immutable suite identity to *trusted* development evidence,
   audit all callers, and enforce matching case IDs, not merely equal totals.
3. **Next:** attach counterexample reproduction links to `failure_ledger`
   and `mission_checkpoint`; test that blocked/retryable/policy states are
   kept distinct and never authorize new writes.
4. **Next:** run controlled comparison on at least two workloads
   (Roblox coding + cross-layer UI/build/animation) with same seeds,
   resources, wall-clock budget and independent evaluators. Publish honest
   non-improvements, failures and regressions.
5. **Only after review:** connect winner selection to an owner-approved
   release gate. Never auto-merge, deploy, retrain, spend money or publish games.

## Sources and what they do *not* prove

- Google DeepMind, *AlphaEvolve* (2025):
  https://deepmind.google/blog/alphaevolve-a-gemini-powered-coding-agent-for-designing-advanced-algorithms/
  — supports automated scoring of candidate algorithms, not a STAR speed claim.
- Google DeepMind, *AlphaEvolve impact* (2026):
  https://deepmind.google/blog/alphaevolve-impact/
  — examples of measured domain-specific optimizations, not universal AGI.
- Shinn et al., *Reflexion* (2023): https://arxiv.org/abs/2303.11366
  — trial-feedback memory can help without changing model weights.
- Xia et al., *Live-SWE-agent* (2025):
  https://arxiv.org/abs/2511.13646
  — evidence for evolving agent scaffolds in specific coding experiments.
- OpenAI, *Why we no longer evaluate SWE-bench Verified* (2026):
  https://openai.com/index/why-we-no-longer-evaluate-swe-bench-verified/
- OpenAI, *Separating signal from noise in coding evaluations* (2026):
  https://openai.com/index/separating-signal-from-noise-coding-evaluations/
  — reason to audit benchmark validity and use independent, task-relevant
  tests rather than claim improvements from contaminated scores.

**Honest finish condition:** STAR solves more previously failed tasks at
the same or lower *total* cost without materially harming already-working
tasks, as demonstrated by independent repeatable evidence.
