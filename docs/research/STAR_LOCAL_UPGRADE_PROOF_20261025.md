# STAR Local Upgrade Proof: Better, Faster and More Reliable

**October 25, 2026 — Evidence-focused research and isolated code proposal.**
**Status:** offline audit; not a deployed model upgrade or measured hardware speedup.

## Why passing locally is not enough

The owner wants every change to make STAR materially more capable, more accurate, faster or more reliable. The right evidence must distinguish:

| Proof tier | Evidence | Does not prove |
| --- | --- | --- |
| Static | compileall, syntax, lint/type, permissions | AI intelligence |
| Offline | deterministic unit and regression tests | Real-model quality, real hardware or game quality |
| End-to-end | A/B comparison of STAR on identical real tasks | Generalization outside evaluated cases |
| Independent | Sealed, independent holdout and reviewer calibration | Universal correctness |
| Runtime | End-to-end p50/p95, first-token latency, cold/warm cache, correct tasks/minute | Better creativity by token speed alone |
| Roblox/creative | Native Studio playtest, real input, device captures, human visual/design review | Guaranteed artistic perfection |
| Release | Owner approval, full CI, Windows installer and rollback proof | Foundation-model retraining |

STAR already has a protected paired statistical gate under star/eval_gate.py, star/eval_stats.py and docs/evals.md. Do not weaken, bypass or duplicate its authority. The current proposed additions are independent *read-only reviewer aids*, not another release system.

## What is actually coded

- star/counterfactual_skills.py: experimental proof-carrying procedural references, scoped matched development evidence and review-only advice.
- star/upgrade_evidence.py: an extra pure audit of independently supplied real-task A/B evidence. It distinguishes first-attempt correctness, cold and warm p95 complete latency, time-to-first-token, correct successes/minute, infrastructure completeness, masked duplicate cases, blind holdout aggregate and genre-specific checks.
- tests/test_counterfactual_skills.py and tests/test_upgrade_evidence.py: synthetic first-attempt quality/speed and failure-mode tests.
- No model runs, automatic model/skill enablement, self-written grader, hidden holdout access, network, Studio mutation, permissions or merges.

The calibration booleans and statistics passed into the module are NOT authenticated evidence by themselves. Before any integration, a separate trusted harness and reviewer must establish origin and store private cases outside model-visible memory.

## 2025–2026 primary research and resulting decisions

**Independent verification is worth more than unchecked sampling.** ICML 2025 Sample, Scrutinize and Scale and ICML 2026 Scaling Agentic Verifier show why generate-and-check can help, especially when verifier tests actively expose differences rather than blindly guessing.
- https://proceedings.mlr.press/v267/zhao25a.html
- https://proceedings.mlr.press/v306/ma26av.html

**Evolve prompts/skills using tested failure analysis, not speculative self-confidence.** ICLR 2026 GEPA combines reflection and Pareto-frontier prompt evolution. STAR can propose changed recipes, but their success must be established outside the proposing agent's writable files.
- https://proceedings.iclr.cc/paper_files/paper/2026/hash/0e9e708b6f48e14fd0ac29e167413f76-Abstract-Conference.html

**Measure pass@1, pass@k and all-run consistency separately.** Anthropic's 2026 evaluation guide explains why a lucky success with many attempts isn't comparable to consistent first-try success. Count retries and verification time in every end-to-end measurement.
- https://www.anthropic.com/research/demystifying-evals-for-ai-agents

**Real Roblox games need native tests and separate visual quality.** Roblox's October 2026 Build evaluation separately measures specification quality, static engineering/design, real player-like playtesting and visual/experiential polish. OpenGameEval tests stateful Studio behavior and highlights the importance of inspecting actual scene objects before editing.
- https://about.roblox.com/newsroom/2026/10/how-roblox-evaluates-build-game-creation
- https://github.com/Roblox/open-game-eval
- https://arxiv.org/abs/2610.02563

**Protect graders and blind holdouts from contamination and exploits.** OpenAI's 2026 audit of SWE-bench Verified exposed contaminated/underspecified evaluation data. Microsoft Research's reward-hacking study shows that optimizing a grader can increase the reported score without solving more tasks.
- https://openai.com/index/why-we-no-longer-evaluate-swe-bench-verified/
- https://www.microsoft.com/en-us/research/publication/reward-hacking-challenges-oversight-of-autonomous-research-agents/

**Treat caching and concurrent inference as measured hardware engineering.** llama.cpp supports prefix caching, slot save/restore, continuous batching and multiple slots. vLLM automatic prefix caching skips prompt prefill when prefixes repeat but doesn't accelerate generated token decoding. The fastest setup depends on model, context, memory, cache warmth and work contention.
- https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md
- https://docs.vllm.ai/en/latest/features/automatic_prefix_caching/

**Optimize the quality/compute Pareto frontier instead of adding agents indiscriminately.** ACL 2026 found large differences among self-consistency, self-refinement, debate and mixture-of-agents at equal inference budgets.
- https://aclanthology.org/2026.acl-srw.1/

## Proposed benchmark protocol

1. Freeze a suite, grading method and test environment; record model/quantization, OS/device, relevant code revision, cold/warm state, cache handling and concurrent workload. Only the targeted improvement may differ intentionally.
2. Interleave baseline and candidate first-attempt runs, ideally with randomized order and repeatability experiments. Begin with at least 24 distinct development cases per family as an exploratory pilot, then determine actual sample size from noise and effect size. A cold/warm pair is still one distinct task when estimating quality significance.
3. Record both full task latency and first-token latency, every model call, model switch, tool, verification, retry, error and GPU/CPU pressure. Report successful tasks/minute alongside pass rate, not merely tokens/second. Infrastructure failures mean INCOMPLETE.
4. Measure independent blind holdout aggregate once after development; protect its case-level tasks/answers from the generating agent. Never adapt to the holdout results and then call that same holdout blind.
5. Require explicit domain evidence: Roblox scripts need static+isolated-unit+real-task checks; UI and builds also need Studio visual/device review; full games additionally require player-like input and multiplayer. Failure in a required dimension is not compensated by extra speed.
6. Let a separate trusted host verify the independent proof and invite owner review. This audit can only advise, never modify the model or merge/release.

## Deliberately conservative prototype acceptance logic

- At least 24 distinct real development cases, at least 24 measurements per cold/warm cache mode, and at least 12 independent holdout confirmation cases; these are starting thresholds, NOT power guarantees.
- Exact paired sign-test, Bonferroni-corrected for how many variants were tried. For a quality increase, prior passing cases must not regress, and p95 full task or first-token latency must stay within the proposed 5% budget in both cache modes.
- For a pure speed claim, first-attempt correctness must be unchanged, at least some tasks must be solved, statistical speed improvement must exist, and each cache mode's p95 complete latency must be at least 10% faster without worsening first-token speed.
- An unverified trial, missing holdout or missing scene visuals yields INSUFFICIENT, not PASS.
- The result is candidate_for_review only, never production approved.

These are strict proposed engineering policies. They do not guarantee perfect creativity or all future tasks, nor do they substitute for user choice of the speed-versus-quality tradeoff.

## Special scene-integrity checks for Starry Eyes

For buildings and maps, inspect actual object hierarchy, transforms, pivots, parent connections, anchored parts, collision volumes, mesh intersection, floor contact, wall thickness, missing props, z-fighting surfaces, materials, texture scale and lighting. Require reference-matched art direction, native device screenshots and a human visual reviewer, not just a textual judgement.

For animation/VFX, inspect transitions, keyframes/secondary motion, clipping, playback timing, effect duration, particles, sound sync and performance. For full games, test real user controls, multiplayer authority, progression, failure/retry, performance and game feel. Distinguish technical correctness from engaging design.

## Evidence obtained in this work

The isolated container executed:

- 16 original counterfactual-skills unit tests: **passed**
- 23 additional local-upgrade-evidence unit tests: **passed**
- Combined pytest: **39 passed**
- Python compileall of experimental star and tests: **passed**

All 39 are **deterministic synthetic policy tests**, NOT live STAR A/B model quality results, actual GPU/CPU speedups, Roblox Studio playtests, native Windows installer validation, full-repository CI or an installed release.

Next needed: authenticated host adapter -> frozen paired real-model baseline -> visual/gameplay studies -> cold/warm machine benchmark -> independent holdout evidence -> owner-reviewed merge after full CI. Protect the active computers from disruptive unattended benchmarking.
