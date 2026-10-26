# Star self-learning: evidence, transfer and revisitable limits

Research snapshot: October 22, 2026. Inspected baseline: `80bf8540b75633c065437036baf75614afe68f74` on `main`.

## Recommendation

Make Star better at choosing, testing and retaining useful improvements. A learning event should produce more than a confident explanation: record the conditions, the observation, a candidate procedure, its measured effect, and what would make the conclusion change.

Use three loops with different costs:

1. **Ordinary work:** capture actual outcomes and propose narrow lessons.
2. **Idle practice:** reproduce important failures, test competing explanations, and compare candidates with the incumbent.
3. **Consolidation:** merge duplicate procedures, retire stale ones, check old capabilities, and consider adapter training only when simpler changes have reached a measured limit.

The recommendations below are hypotheses for Star. Published benchmark improvements are not measured Star improvements, and no global originality or indefinite self-improvement is claimed.

## Existing foundations and this change

Star already has contextual learning, Night School, paired evaluation gates, provisional lesson expiry, undo/restore controls, and a bounded report. [SELF_LEARNING_LOOP.md](../SELF_LEARNING_LOOP.md) documents that reviewed release lessons with a paired `PROMOTE` result can become provisionally live with `learning_auto_live` enabled by default. Preserve that behavior and the existing review and promotion boundaries.

The pre-existing [Star Oracle draft, PR 546](https://github.com/oncoursemail/Star-AI-Private/pull/546), already explores predictions of improvement. Its author-reported pilot is inconclusive. Further work should improve calibration and task-level measurements there rather than introduce a competing prediction framework.

This change adds a **read-only evidence summary and a bounded next-probe suggestion** to Night School's existing report. It does not schedule experiments, promote lessons, alter evaluators, change settings, run Studio, or train a model. The test results accompanying the pull request establish software behavior, not improved task-solving ability.

The existing state is a snapshot with incomplete history:

- `tries` includes some infrastructure backoff attempts. It is not a denominator for independent success trials.
- A stored task status may describe an earlier judged outcome. Later infrastructure errors can preserve it.
- Error counts and `last_error` can remain after a success. They do not establish a current outage.
- A cause label is a heuristic diagnosis, not a proven causal explanation.
- Multiple fixed task IDs do not establish independence, cross-project transfer, or model-version coverage.
- The validation slice is protected. Report aggregate coverage only; never disclose its task IDs, prompts, or answers as practice material.

For those reasons, the summary reports evidence gaps without inventing confidence, mastery, or success percentages.

## What the research supports

| Finding | Evidence | Implication for Star |
| --- | --- | --- |
| Useful agent learning can occur without updating model weights. | Voyager [1], Reflexion [2], Contextual Experience Replay [3]. | Prioritize scoped procedures and relevant retrieval before training. |
| A skill needs applicability, execution, termination and maintenance rules. | Skill-Pro [4]. | Store contracts and counterexamples with each reusable procedure. |
| Memory can interfere with older knowledge even when model weights stay fixed. | Memory competition [5]. | Replay older tasks after memory or retrieval changes. |
| Skill utility depends on the consuming model and decomposition. | Skill lifecycle [6], subtask transfer [7]. | Evaluate compact skills on the actual local model. |
| Prompts and context can be optimized from execution feedback. | GEPA [8], ACE [9]. | Optimize one small component at a time using comparable budgets. |
| Agent code and the method that proposes changes can evolve. | DGM [10], HyperAgents [11], AIDE2 [13]. | Maintain candidate histories and independent acceptance, with bounded experiments. |
| Failure patterns and predicted effects can guide experiment selection. | Predict Before You Modify [12], ActiveSaddler [14]. | Rank useful next probes and measure the ranking's realized value. |
| Self-tests, self-grades and self-reports can be misleading. | Self-authored verification [16], calibration studies [17–18], memory reward inflation [19]. | Prefer independently collected or executable outcome evidence. |
| Retrieval and revision can help some tasks while harming others. | Skill Following [20], revision study [21]. | Count rescues and harms on the same task instances. |

Some sources are conference papers; others are recent preprints. Results are specific to their models, tasks and budgets. The October 2026 ActiveSaddler report, for example, finds 4.4 and 7.5 percentage-point test Pass@1 gains over fixed scenario ordering with the same optimizer on GAIA2 and Terminal-Bench 2.0 [14]. That supports testing adaptive curricula, not forecasting the same gain for Roblox development.

## Capability evidence: acknowledge limits in a useful form

| State | Meaning | Appropriate action |
| --- | --- | --- |
| Unknown | No comparable observation exists. | Gather the smallest relevant observation. |
| Blocked or unrun | A prerequisite was unavailable. | Resolve or await it; exclude from skill success/failure rates. |
| Observed failure | A valid attempt failed its requirements or exhausted its budget. | Test a diagnosis; keep unknown causes explicit. |
| Narrow success | A procedure worked under stated conditions. | Reuse within that scope and probe a nearby boundary. |
| Transfer supported | Independent related tasks supply evidence. | Record exactly which task families and environments were covered. |
| Inconclusive | Evidence is incomplete, noisy or contradictory. | Run a discriminating check. |
| Needs revalidation | A relevant dependency changed. | Reprobe affected capabilities and preserve historical observations. |

A future structured record should include task lineage, environment and model versions, evidence references, verifier version, conditions tested, known counterexamples, total cost, and a reconsideration trigger. Keep observed facts separate from proposed causes and prospective predictions. Hidden reasoning is unnecessary: concise decision summaries and tool observations are sufficient.

Example of desired language, **not an executed result**: “Static checks passed. Multiplayer behavior is untested because Studio was unavailable. The next useful check is a two-client reproduction of the delayed throw.”

## Twelve experiments worth pursuing

### 1. Reconsider old limits when their causes change

Attach a dependency and a reconsideration trigger to each limitation. A restored runtime makes an old blocked probe eligible; a model update triggers bounded revalidation of affected skills. Preserve the old observation rather than overwriting it. Compare avoided futile retries and correctly resumed tasks against ordinary retry behavior.

### 2. Find the edge of a successful procedure

Vary meaningful dimensions after a success: latency, object count, player count, resolution, interruption or API version. Search for reproducible failures near the demonstrated scope. Compare boundary practice against random practice under the same total budget, evaluating reserved combinations. This is a Star proposal related to adaptive failure-target selection [14].

### 3. Test the connections between individually working skills

For Blender-to-Roblox work, isolated mesh export and script checks are insufficient. Test scale, import, materials and runtime behavior together. When components pass but the workflow fails, investigate their connecting assumptions. Measure end-to-end success on new assets.

### 4. Turn contradictory lessons into discriminating experiments

Conflicting rules may apply in different environments. Preserve both observations and vary one likely distinguishing condition. A diagnosis is useful when it predicts a fresh reproduction. Causal replay supplies related methodology [26], but its synthetic validation does not establish causal reliability in live Studio workflows.

### 5. Measure the alternate outcome without a lesson

Run the same development task with and without the candidate, restoring files, memory and runtime state and balancing order. Record rescues, harms and cost. Begin with a small pilot across genuinely different task families; increase sample size when uncertainty warrants it. Skill Following directly motivates matched-instance comparisons [20].

### 6. Test whether the verifier notices known mistakes

Use deliberately wrong artifacts: code that compiles but breaks a requirement, a stale screenshot, or a fix that only works for the first player. Maintenance of these checks belongs to the independent evaluator workflow, outside the candidate's editable scope. Measure detection of known faults before treating a verifier as trustworthy [10,16].

### 7. Predict regressions before spending the experiment budget

Record which task families a proposal should help or harm, then compare predictions with actual results. Extend Star Oracle rather than duplicate it. Compare its ranking with a simple recurring-failure baseline under equal total cost. A prediction prioritizes testing; it never replaces acceptance evidence [12].

### 8. Learn which improvement strategy fits a failure

Compare documentation lookup, direct repair, runtime probing, visual inspection and deeper investigation. Track resolution, cost and failed attempts. Start with a small router and preserve exploration of unfamiliar categories. More ambitious changes to the improvement process itself should follow measured success of the simpler router [11].

### 9. Share verified capability packets between brains

Transfer a procedure with prerequisites, version scope, a minimal reproduction and evidence references. The receiving machine reruns environment-dependent probes. Measure successful transfer and adaptation cost. This exchanges explicit artifacts, not model weights or unsupported machine-specific assumptions.

### 10. Compress working procedures while checking behavior

Compare a full trace, a compact procedure and no procedure at a comparable total budget. Remove redundant explanation and tool calls only while new-task quality and old-task retention remain acceptable. Skill-Pro and subtask-transfer results motivate the experiment [4,7]; the best representation depends on Star's actual consumer model.

### 11. Learn visual preferences from accepted work

Preserve approved references and specific corrections: legibility, spacing, animation, palette, icon consistency and unwanted decoration. Separate functional correctness from preference. Evaluate predictions on withheld pairs and check actual interaction at several viewport sizes. A judge model's aesthetic confidence does not establish the owner's preference.

### 12. Learn when another revision is unlikely to help

Detect repeated identical repairs and revisions without new evidence. Compare always-revise, never-revise and evidence-gated revision on fresh tasks. Count correct-to-wrong changes and total cost, as well as recovered errors. Revision benefits and harms vary across models and tasks [21].

These combinations are tailored proposals, not claims that each mechanism is new to the field or already implemented.

## Night School curriculum pilot

Start with a transparent scheduling heuristic: expected useful improvement multiplied by recurrence and reuse, divided by total experiment cost. Inputs should come from observations where possible; predictions should be checked against realized outcomes. Apply repetition caps and reserve exploration. Compare scheduling policies under an equal total compute budget, including scheduling, verification and failed experiments, on an independently assigned future-task panel.

A candidate initial allocation is 50% recurring real failures, 25% unfamiliar conditions and boundaries, 15% old-task retention, and 10% cost reduction. These are proposed pilot percentages, not research-established optima. Do not spend the budget repeatedly invoking unavailable tools.

Use separate development tasks, acceptance audits, and infrequently used fresh reporting tasks. Track exposure: repeated accept/reject feedback can overfit a sealed audit even without revealing answers. Retrieved memory and web search can contaminate benchmark comparisons [23]. Replay can compare strategies on historical branches, but it cannot invent outcomes for branches that were never executed [15].

## Measures and rollout order

Track successful tasks over predeclared eligible attempts; paired rescues and harms; retained old capabilities; recurrence of recorded failure patterns; all-attempt cost per verified result; calibration of prospective predictions; coverage of important conditions; and verifier sensitivity. Count agent-caused timeouts, budget exhaustion and abandonment as unsuccessful attempts. Report infrastructure-invalid, blocked and unrun cases separately with exclusion counts and reasons. Report task lineage and sample counts, not only percentages. Control task order and stochastic variation [24].

Implement in this order:

1. Explain what existing evidence does and does not establish (this report addition).
2. Extend the existing failure ledger with richer versioned episodes, uncertain diagnoses and bounded next-probe ranking.
3. Extend the existing paired gate with explicit applicability, retention coverage and transfer evidence.
4. Search over small prompts, procedures and helpers with independent acceptance.
5. Improve experiment selection using measured prediction errors.
6. Consider adapter training for frequent skills whose remaining limitation is measured.

For the previously reported 8 GB GPU class, memory, procedure and workflow improvements are the first practical track. Exact adapter feasibility depends on model size, sequence length, optimizer state and implementation; QLoRA reduces memory requirements but does not guarantee arbitrary training runs fit [22]. Self-Adapting Language Models demonstrates a distinct gradient-based approach [27]. Neither reading a document nor saving a lesson constitutes that kind of training.

Keep full contracts and evidence in storage; retrieve a compact applicable procedure within the existing 2,400-character per-turn learning budget, with references for opening supporting evidence. Evaluate improvements within that actual budget.

Preserve source-to-lesson lineage and supersession. Removing a bad source should identify derived skills that need review; deleting the source alone need not remove its effects [25]. Use existing project policy for acceptance, rollback and permissions.

## Primary sources

1. [Voyager](https://arxiv.org/abs/2305.16291), 2023.
2. [Reflexion](https://arxiv.org/abs/2303.11366), 2023.
3. [Contextual Experience Replay](https://aclanthology.org/2025.acl-long.694/), ACL 2025.
4. [Skill-Pro](https://proceedings.mlr.press/v306/mi26d.html), ICML 2026.
5. [When Continual Learning Moves to Memory](https://arxiv.org/abs/2604.27003), April 2026 preprint.
6. [From Raw Experience to Skill Consumption](https://arxiv.org/abs/2605.23899), May 2026 preprint.
7. [Break It Down, Pass It On](https://arxiv.org/abs/2608.20274), October 2026 revision.
8. [GEPA](https://arxiv.org/abs/2507.19457), ICLR 2026.
9. [Agentic Context Engineering](https://arxiv.org/abs/2510.04618), ICLR 2026.
10. [Darwin Godel Machine](https://arxiv.org/abs/2505.22954), 2025; revised 2026.
11. [HyperAgents](https://arxiv.org/abs/2603.19461), March 2026 preprint.
12. [Predict Before You Modify](https://arxiv.org/abs/2610.13991), October 2026 revision.
13. [Recursive self-improvement of AI research agents (AIDE2)](https://arxiv.org/abs/2609.26457), September 2026 preprint.
14. [ActiveSaddler](https://arxiv.org/abs/2610.00906), October 2026 preprint.
15. [Dream-RSI](https://arxiv.org/abs/2609.14858), October 2026 revision.
16. [Self-Authored Verification Is Unreliable in Heuristic Self-Improving Agents](https://arxiv.org/abs/2607.24300), July 2026 preprint.
17. [From Knowing to Acting](https://arxiv.org/abs/2606.20661), June 2026 preprint.
18. [MIRROR](https://arxiv.org/abs/2604.19809), April 2026 preprint.
19. [Memory Reward Inflation](https://arxiv.org/abs/2608.00017), 2026 preprint.
20. [Skill Following](https://arxiv.org/abs/2609.00549), Findings of EMNLP 2026.
21. [When Should LLMs Trust Their Own Revisions?](https://arxiv.org/abs/2609.35832), September 2026 preprint.
22. [QLoRA](https://arxiv.org/abs/2305.14314), 2023.
23. [Search-Time Data Contamination](https://arxiv.org/html/2508.13180v1), August 2025 preprint.
24. [On the Fragility of Self-Improving Agents](https://arxiv.org/abs/2608.18066), September 2026 revision.
25. [SkillJack](https://arxiv.org/abs/2608.03509), August 2026 preprint.
26. [Causal Agent Replay](https://arxiv.org/abs/2606.08275), June 2026 preprint.
27. [Self-Adapting Language Models (SEAL)](https://arxiv.org/abs/2506.10943), 2025.
28. [OpenEvolve](https://github.com/algorithmicsuperintelligence/openevolve), project documentation, accessed October 22, 2026.
