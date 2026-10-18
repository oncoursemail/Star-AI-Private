# STAR: Evolutionary Research, Brainstorming and Agent Optimization Laboratory

**Date:** 2026-10-18. **Target:** star/next after human-reviewed integration. **Status:** research/architecture only; no actual experiments or training installed.

## 1. Research directly relevant to continuously improving STAR

### AlphaEvolve (Google DeepMind)
Research: https://deepmind.google/blog/alphaevolve-a-gemini-powered-coding-agent-for-designing-advanced-algorithms/
2026 follow-up: https://deepmind.google/blog/alphaevolve-impact/

AlphaEvolve combines powerful and economical idea-generating models, program mutation, automatically executable evaluators and a growing population of candidate solutions. Instead of asking a model to claim its own code is better, the system runs a scoring harness. Google reports improvements in algorithm discovery, serving infrastructure, cache policies and kernels. Results depend on the *particular* objective and verifyable tests and must not be presented as an achieved STAR speedup.

### Agent Lightning v1.0 (Microsoft Research)
Research: https://www.microsoft.com/en-us/research/project/agent-lightning/
Code: https://github.com/microsoft/agent-lightning
Architecture/docs: https://microsoft.github.io/agent-lightning/stable/
Technical report: https://www.microsoft.com/en-us/research/publication/agent-lightning-v1-0-towards-harnessed-agentic-rl/

A separately managed trainer, API gateway and rollout controller can learn from actions of *real* agent harnesses rather than simplified training tasks. Microsoft reports that its reproducible Qwen3.5-9B coding recipe improved SWE-bench Verified from 41.8% to 56.4% using about 6,000 training examples; a separate 35B-A3B experiment reports 47.8% to 61.6%. These are Microsoft-reported experiments, **not** an expected return for Starry; the MoE recipe specifies multiple B200 GPUs. A CPU-based EPYC host should NOT run those training workflows as a default background job.

### DSPy / GEPA optimizer
Research: https://github.com/stanfordnlp/dspy/blob/main/docs/docs/getting-started/gepa-optimization.md

Rather than rewriting all of STAR, define small prompt/tool-use programs and a verified metric; GEPA-style optimization can trial alternative instructions using a local/approved model and compare held-out accuracy. Optimizing prompts and task routers is far less hardware intensive than updating base-model weights. Still, many scored candidates can consume enormous inference time, so require an owner-defined budget and idle windows.

### Independently validated software engineering tasks
Reference: https://openai.com/index/introducing-swe-bench-verified/
Reference: https://github.com/SWE-bench/SWE-bench

SWE-bench Verified uses real repository issues with hidden tests and FAIL_TO_PASS/PASS_TO_PASS measurements. STAR should adopt the pattern for its own Roblox, Java Minecraft, Qt/React, server and infrastructure fixtures, not assert that a score on SWE-bench automatically establishes game-development quality.

## 2. Proposed STAR Evolution Lab architecture

    Research Scout -> grounded hypotheses, source/version/license
          |
          v
    Feasibility Filter -> no duplication of current modules, task-specific metric, limits
          |
          v
    Idea Search -> existing solution + 2+ alternatives + skeptical critique
          |
          v
    Candidate Generation -> bounded editable config, prompt, pure function or patch
          |
          v
    Isolated Evaluator -> reproducible tests in temporary project-scoped sandbox
          |
          v
    Population Store -> hashes, costs, failures, rewards, novelty, exact dependencies
          |
          v
    Compare Against Locked Baseline -> independent blind tasks + counterfactual checks
          |
          v
    star/innovation_gate.py -> reject / more evidence / owner review
          |
          v
    Human approval + existing STAR GitHub PR/CI release process -> project lessons

Each improvement proposal should include its exact task domain, measurable expected gain, assumptions, direct/indirect costs, risk, rollback method, benchmark suite digest, operating hardware and model checkpoints. The system must distinguish "test proposed", "test attempted", "test passed", "human reviewed" and "released". Display unknown instead of invented results.

## 3. Autonomous brainstorming that has a purpose

A good brainstorming agent needs a structured novelty loop, not free-form endless suggestions. For each problem, retrieve the relevant existing STAR source and past rejected ideas, generate a low-complexity baseline and at least two materially different options, state a falsifiable hypothesis for each, request an independent critic, calculate a resource estimate and choose the smallest authorized experiment.

Example: "Increase CPU model throughput" -> alternatives might be shorter stable context with reusable prompt cache, fewer concurrent decode slots, measured NUMA affinity, changed quantization, or long-context retrieval instead of full-history prompting. The answer is determined by measured p95 latency **and** holdout task quality on the same EPYC server, not by the number of agents that voted for it.

Example: "Make Minecraft GUIs look professional" -> independent oracles check generated Java/plugin code and resource pack load; actual Minecraft client screenshots and human owner visual acceptance judge typography, composition, animation consistency and real input latency. Static code compilation is necessary but not sufficient.

Example: "Be better at coding" -> include tests failing on the old revision but passing on a candidate, regression tests passing on both, static analysis and reviewer inspection. Do not allow the candidate model to see hidden expected outputs.

## 4. Adaptation without constant retraining

Preferred order on current STAR hardware:

| Level | Method | Typical feasibility | What actually changes |
| --- | --- | --- | --- |
| L0 | Inference server settings, request admission, prefix caching, retrieved context | CPU feasible, measure first | Speed and capacity |
| L1 | Approved knowledge/lessons, error-repair playbooks, trusted APIs, skill manifests | CPU feasible | Better task context and workflows, **not weights** |
| L2 | Select from existing specialized models by measured domain, cost and error class | Conditional on resident RAM and model support | Routing accuracy and latency |
| L3 | Optimize bounded instructions with metric-driven candidate search | CPU feasible but costly in trials | Prompts and control logic |
| L4 | Controlled patch evolution + real static/integration tests + independent holdouts | CPU feasible for small diffs, strict sandbox | Program code after normal review |
| L5 | Fine-tuning/LoRA/RL from sanitized, consented agent trajectories | Usually demands compatible GPU and training time | Actual model weight adaptations |

A training loop must use separate training, validation and final sealed holdout sets. Only owner-authorized, permitted project content enters a training corpus; never include raw customer data, private Discord content, credentials, session cookies, private code from unapproved repositories or passwords. Logged trajectories can include secrets so a trusted scrubber is necessary *before* persistence or export. If a model cannot pass privacy and safety tests, it cannot graduate.

Reward functions should measure actual task success, latency/cost and legitimate user review. Prevent reward hacking such as deleting tests, moving assertions, changing the expected-output files, hiding broken features, using leaked holdouts, or favoring an answer because it is more verbose.

## 5. Statistical and operational guardrails

star/innovation_gate.py added in the companion PR is an initial lightweight offline *screen*, not a full scientific claim. Its exact paired sign test and resource caps do not prove statistical independence, detect all reward hacking, authenticate evidence, or protect against repeated comparisons.

Add signed observation receipts: task ID and immutable input hash, source-control revision, model weights/checkpoint hash, exact inference settings, evaluator version/hash, wall-clock start/end, measured hardware load, unedited logs, independent oracle decision, peak RAM and timing.

Do not mutate the locked test oracle or hidden task sets after candidate generation; protect tests using operating-system permissions separate from the agent execution identity. Keep mutable development fixtures separate from unobserved final holdouts. Repeatedly selecting "winners" among hundreds of trials on the same test suite overfits it even when every single p-value looks compelling. Apply multiplicity and sequential-evaluation protections and conduct an independent confirmatory validation on a reserved final suite.

During another tenant's active game traffic, hard pause all offline jobs if admission conditions fail. Distinguish guaranteed foreground inference capacity from experimental training quotas; enforce CPU shares, cgroup memory limits, disk quotas, max file operations, network egress policy, timeout and cancellation. No shared Docker socket, host root mounts, raw production secrets or direct deployment credential paths.

## 6. Suggested interfaces and data contracts

New opt-in "Evolution Lab" view: a research backlog with citations and timestamps, experiment hypotheses, metric definitions, estimated resource use, locked suite IDs, generation history, baselines, failure reasons, human quality screens and rollback plans. Display clear "Not measured" and "Human review required" labels; do not show fabricated savings or fake improvement trends.

Candidate contract fields: schema version, run ID, project ID, objective, immutable baseline and candidate revisions, suite fingerprints, model/quantization IDs, hardware fingerprint, source URLs, permission scope, CPU/RAM/time budgets, test adapter, expected safe output, and the owner's explicit authorization receipt.

Evaluation events: proposed -> accepted_for_test -> running -> evaluated -> rejected | needs_more_evidence | pending_owner_review -> human_approved -> separately_merged_or_released. Only trusted application code can advance permissions or release states. Tool results and research snippets remain untrusted data.

Record *negative* outcomes and why they failed. A negative result prevents STAR from cycling back to identical proposals. Track benchmark drift and upstream model version changes so an older recommendation is revalidated before future use.

## 7. The next concrete integrations, in order

First connect a read-only observation recorder to an isolated test-mode STAR agent worker; generate a few real cases with independently asserted outcomes and no user data. Second integrate the innovation gate output into a local private dashboard with manual artifact review. Third implement a bounded candidate-generator adapter that produces **patch proposals only** and never direct deployment. Fourth add CPU-only instruction/algorithm optimization trials under strict idle-resource budgets. Fifth consider Agent Lightning v1.0 training only when a compatible, independently isolated GPU compute environment, allowed dataset, reliable reward oracle and owner approval exist.

No source cited here gives STAR a shortcut to a globally fastest foundation model. A superior system for its actual tasks is built by choosing the cheapest verified successful path, repeatedly testing for regressions, and integrating only improvements that survive independent assessment.
