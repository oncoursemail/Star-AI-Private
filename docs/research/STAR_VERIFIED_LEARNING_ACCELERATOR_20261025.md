# STAR verified-learning accelerator (2026-10-25)

## Purpose and honest scope

STAR must increase **verified tasks completed per hour**, not just accumulate
webpages, prompt tokens, generated code, untested skills, or benchmark claims.
This is a local-first experimental agent, not a frontier foundation model.
Neither observing a test nor saving a lesson modifies model weights.

This change provides an **operational first step**: a bounded and read-only
curriculum planner backed by real completed Brain 2 Roblox test receipts.
It does **not** launch training, collect live player data, auto-research the web,
write Roblox places, modify grader files, bypass approvals, or enable any
new autonomous permission. A host-controlled future scheduler could consume
its recommendations within existing resource and approval limits.

### What was already implemented

- Project-local owner-reviewed lessons: star/lessons.py, star/learning.py.
- Independently gated evolution: star/skill_evolution_lab.py,
  star/verified_training.py, star/eval_gate.py.
- Inference-speed infrastructure: star/cache_banks.py, star/instant_route.py,
  star/cascade_router.py, star/inference_benchmark.py, star/best_of_n.py.
- Host-owned test history: star/brain2_practice.py.
- Host resource limits: star/agent_resource_planner.py.

Do not duplicate their responsibilities or claim that separate experimental
branches have been reviewed, merged, or enabled.

## What this patch does

star/learning_accelerator.py:
1. Opens an existing local Brain 2 practice SQLite DB in read-only mode.
2. Selects completed, test-executed cycles only in the exact project, with an
   optional pinned universe/place scope.
3. Requires a positive Saved version, source SHA-256, timezone-aware start and
   finish, consistent per-case pass/fail totals and sane bounded case names.
4. Excludes blocked, pending, unknown, corrupt and future-dated cycles.
5. Deduplicates repeated case observations on the **same source revision** and
   pinned place even when a Saved version number differs.
6. Gives verified failures priority after a short delay, and applies widening
   spaced-repetition intervals to successful capabilities.
7. Includes optional **operator-curated, untried** capabilities so learning
   is not limited to tasks that STAR already tried.
8. Ranks expected practice value relative to *estimated* time, with a simple
   domain-diversity penalty to avoid starving other specialties.
9. Prints an explanatory JSON preview; it NEVER executes the proposed work.

Score = (0.8 * Beta-smoothed failure fraction + 1.2 / sqrt(samples + 1)
        + recent-failure bonus + staleness bonus)
        * operator-importance / sqrt(estimated minutes).

This heuristic is **not** a statistically calibrated probability of success,
information-theoretic gain, or a validated intelligence measure. Hardware,
revision recency, user impact and verifier reliability must be measured to
tune it. Its principal benefit now is verifiable focus and avoided repeats.

### Read-only usage

From the workspace:

    python -m star.brain2_practice \
      --plan /path/to/owner-approved-practice-plan.json \
      --home /path/to/existing-private-star-profile \
      --suggest-learning

Or with a separate task catalog:

    python -m star.learning_accelerator \
      --ledger /path/to/brain2-practice.sqlite3 \
      --project my-roblox-project \
      --universe-id 123 --place-id 456 \
      --catalog /path/to/operator-capabilities.json \
      --minutes 30 --top 8

The catalog is a local JSON array with strictly data-only fields:

    [
      {"name":"Character animation", "domain":"animation", "value":2.0, "seconds":300},
      {"name":"Luau security checks", "domain":"scripting", "value":3.0, "seconds":600}
    ]

No catalog exists by default. An untested catalog entry is **not** a mastered
skill, evidence of execution, or permission to start a task. Calls with
--suggest-learning cannot be combined with --run or --acknowledge.
Missing ledgers fail closed rather than silently manufacturing progress.

## Performance gates before automatic operation

Establish a baseline and paired holdouts before integrating into a live loop.
Do not assume local inference speeds from a server paper.

- **Capability**: novel, sealed holdout success rate; regression rate; verified
  task completion; cross-project and cross-engine transfer.
- **Learning efficiency**: additional verified passes per test minute, measured
  against chronological and random-practice baselines on held-out projects.
- **Latency**: p50/p95 time-to-first-token, time-to-first-useful-artifact and
  tool-call overhead, with warm and cold caches separately reported.
- **Compute**: GPU peak VRAM, CPU available RAM, KV cache hit/miss, wall-clock
  and energy when readable. GPU/server measurements are kept per machine.
- **Quality**: fresh source/license provenance, failures fixed and stayed
  fixed, anti-regression gate results, security checks and human acceptance.
- **Safety**: no source-code execution during preview, no network calls,
  no model-created grader changes, no lessons silently approved.

A claim such as "learns 4x faster" requires a control group, comparable
difficulty, frozen prompts/holdouts and repeated runs. Do not advertise
algorithm-heuristic values as measured speedups.

## Research-backed next phases (NOT IMPLEMENTED HERE)

### 1. Verified experience reuse

Cache the *structure* of successful agent workflows:
 task conditions -> referenced tool/version -> required inputs ->
 artifacts -> verifier result -> expiry/invalidators.

On a new request, first test exact-reuse predicates. If stale, verify and
adapt; if irrelevant, perform fresh synthesis. Persist success and failure
procedures only from host-confirmed runs. Keep model-authored explanations
as candidates; never silently promote them to owner-approved lessons.

Evidence:
- APEX-EM, Findings of EMNLP 2026,
  https://aclanthology.org/2026.findings-emnlp.1996/
- CORTEX verified experience layer (preprint, September 2026),
  https://arxiv.org/abs/2609.33260
- AgentCL (preprint, June 2026) identifies memory-induced degradation,
  https://arxiv.org/abs/2606.02461

### 2. Prompt/skill reflection before costly fine-tuning

Connect a small, independent development evaluation to STAR's
skill_evolution_lab.py, compare candidate skill procedures and use a sealed
holdout owned by the evaluator. GEPA offers an example of targeted
error-driven prompt evolution with Pareto selection. Its paper reports fewer
rollouts on specific tasks, not universal superiority.

Evidence:
- GEPA (ICLR 2026), https://proceedings.iclr.cc/paper_files/paper/2026/hash/0e9e708b6f48e14fd0ac29e167413f76-Abstract-Conference.html
- DSPy GEPA instructions,
  https://github.com/stanfordnlp/dspy/blob/main/docs/docs/api/optimizers/GEPA/overview.md

### 3. Model and hardware strategy (conservative)

- Fast deterministic paths for file search, source citation, test checking,
  cached verified results and short routing decisions: avoid an LLM call.
- Quantized compact specialist for cheap tool choices and summarization,
  with larger reasoning models only for genuinely ambiguous hard tasks.
- Warm persistent model/KV prefix caches *only* when the backend supports
  safe identity/version checks. Allocate within measured available RAM
  rather than assuming all physical RAM is free.
- Test speculative decoding with matched model-specific draft heads and
  backend support; benchmark on the actual NVIDIA 8 GB machines.
  Published results on multiple datacenter GPUs are not transferable to
  one consumer GPU without measurement.
- Start Best-of-N at 1. Add candidates only when independent cheap checks
  show disagreement or significant uncertainty, and stop when a candidate
  passes all required gates. Enforce bounded attempts and wall-time.
- Train/fine-tune only after rights review, independent receipts, separate
  training consent and held-out evaluation. RL setups like Agent Lightning
  need much more than this read-only planner.

Evidence:
- Agent Lightning v1.0 (2026), https://github.com/microsoft/agent-lightning
- DFlash/SGLang (2026), https://www.lmsys.org/blog/2026-06-15-next-generation-speculative-decoding-dflash-v2/
- Qwen speed benchmarking caveats,
  https://qwen.readthedocs.io/en/latest/getting_started/speed_benchmark.html

### 4. Source and tool discovery

Only index permitted materials with provenance and freshness. Useful
categories: Roblox official Creator Hub/Open Cloud, Luau API reference,
public GitHub repos with known licenses, Blender/Godot docs, source-code
symbols, game test fixtures and other owner-authorized APIs.

Maintain a source record (URL, version, license, retrieval time, checksum,
trust level, relevant task), not a blanket "scraped the internet" claim.
Untrusted documentation cannot set policy, change permissions, approve
lessons, provide credentials or deploy code. Offline indexing and
read-only previews remain default until separately authorized.

### 5. Live autonomy last, not first

After the planner demonstrates improvement on sealed tasks, the operator
may attach it to a bounded practice queue through the existing host
resource planner and Studio/Roblox scope checks. There must still be a
trusted executor, independent grader, locked holdout, state journal,
cooldown, cancellation and explicit approval for privileged writes.

## Reproducibility

    python -m compileall -q star main.py
    python -m pytest -q tests/test_learning_accelerator.py tests/test_brain2_practice.py

All included tests use local synthetic ledgers; they do not call Roblox.
The new logic is off unless an operator explicitly runs a suggestion command.
