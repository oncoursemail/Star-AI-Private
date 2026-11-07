# Litha × Ornith-1.5 deep research — 2026-11-01

## Decision

Integrate Ornith as an **evidence-gated model family**, not as a new hard-coded
brain. The strongest immediate experiment for the owner's RTX 4060 8 GB class
machine is **Ornith-1.5 9B Q4_K_M**. Larger Ornith variants are useful as
workstation/server candidates, not local defaults.

This change deliberately does **not** download weights, change the active model,
or edit protected evaluation files.

## What is verified from primary/public sources

### Ornith-1.5 exists and materially changes the training loop

The Ornith project describes 1.0 as jointly optimizing a task scaffold and its
solution rollout. Ornith-1.5 extends that loop so the system also generates new
training tasks, constructs task-specific scaffolds, produces solution rollouts,
and reinforces the policy from the resulting rewards. This is more interesting
for Litha than copying a prompt: the reusable idea is a **closed improvement
loop with generated tasks + generated harness/scaffold + independently measured
outcomes**.

Sources:
- https://github.com/ornith-ai/Ornith-1
- https://ornith.ai/ornith_1_5.html
- https://huggingface.co/ornith-ai
- https://ollama.com/library/ornith-1.5

### Current public lineup

Public model cards/registries expose Ornith-1.5 9B, 35B, 122B and 397B
variants. The Ollama registry currently reports:
- 9B: Qwen3.5-derived dense model, ~8.95B parameters, Q4_K_M package around
  6.6 GB, with vision/tools/thinking metadata.
- 35B: Qwen3.5 MoE-derived model, ~35.5B parameters, Q4_K_M package around
  23 GB, with vision/tools/thinking metadata.
- 122B: released 2026-10-20, positioned by the project as a more efficient
  frontier-scale MoE option.
- 397B: flagship large MoE research/server model.

Do not confuse Ornith-1.0 package sizes with 1.5. Ornith-1.0 9B is commonly
listed around 5.6 GB; Ornith-1.5 9B is currently around 6.6 GB in Ollama.

### Context

The public registry advertises a **256K native context** for the family. Some
project material discusses longer-context scaling, but Litha must not convert a
model's theoretical/advertised maximum into an automatic runtime allocation.
On an 8 GB GPU, weights, KV cache, projector, graph/work buffers and backend
overhead compete for memory. For the 9B model, Litha should begin at 32K,
measure, and expand only after memory + TTFT + throughput remain acceptable.

## Claims that should NOT be copied into Litha as facts

1. **"Self-improving" does not mean the downloaded GGUF rewrites its own
   weights while Litha uses it.** The self-improvement refers to the model
   development/training methodology.
2. **Benchmark screenshots are not enough to promote a route.** Litha needs
   paired local measurements on its own coding, tool-use, Roblox, debugging,
   vision and long-horizon agent tasks.
3. **256K native context is not 256K practical context on every machine.**
4. **A 35B MoE model being sparse does not make a ~23 GB quant fit inside an
   8 GB GPU.** Active parameters affect compute; total stored weights still
   affect memory/storage and offload.
5. **Do not assume 122B/397B are sensible desktop choices.** Treat them as
   remote/server candidates until measured.
6. Public issue reports for Ornith-1.0 include tool-loop behavior. Litha must
   explicitly score loop termination, repeated tool calls, recovery and bounded
   retries before promotion.

## What Litha should borrow from Ornith

### 1. Task generator -> scaffold generator -> rollout -> verifier -> promotion

Litha already has night-school, best-of-N, regression tests and promotion
gates. Ornith suggests making the generator itself part of the improvement
loop:

1. Mine real failures and capability gaps.
2. Generate a new task family around each gap.
3. Generate multiple candidate scaffolds/harnesses.
4. Run N solution rollouts under fixed resource budgets.
5. Verify with executable tests, scene checks, tool receipts or human-approved
   rubrics.
6. Compare against the current baseline using paired evidence.
7. Keep only improvements that pass quality + latency + safety thresholds.
8. Store failed approaches too, so Litha stops rediscovering bad scaffolds.

Crucially, the model must not be allowed to edit the hidden holdout, scorer or
promotion rule it is trying to pass.

### 2. Scaffold search, not giant static prompts

For difficult coding/agent tasks, represent a scaffold as structured policy:

- decomposition strategy
- tool ordering
- retry limits
- context retrieval policy
- verifier choice
- candidate count
- stopping conditions
- repair strategy
- resource budget

Search over this compact policy object, then cache successful scaffold families
by task signature. This is cheaper and more inspectable than endlessly growing
the system prompt.

### 3. Failure-aware agent loops

A coding model should be rejected as a preferred route if it:
- calls the same tool repeatedly without new evidence,
- exceeds retry/repair budgets,
- edits unrelated files,
- claims tests passed without receipts,
- widens permissions,
- or keeps reasoning after the task is already complete.

Add "agent_loop_termination_rate" and duplicate-tool-call rate to model
promotion.

### 4. Multi-model division of labor

Recommended experimental roles:
- Ornith-1.5 9B: local coding agent / tool-use candidate.
- Existing fastest small model: voice and instant chat.
- Existing deep route or hosted opt-in model: judge for exceptionally difficult
  cases only when configured.
- Deterministic tools/tests: final authority for executable correctness.

Litha should not make Ornith judge its own promotion.

## RTX 4060 8 GB plan

Start with Ornith-1.5 9B Q4_K_M only.

Initial experiment envelope:
- context: 32K
- concurrency: 1
- no automatic CPU fallback for interactive chat
- vision tested separately from text/tool calling
- flash attention when supported by the chosen backend
- prompt/KV-cache changes benchmarked independently
- measure cold and warm TTFT separately
- compare against the current 4B/9B candidates on identical prompts

Promote only if the 9B route gives a material coding/agent-quality improvement
without unacceptable TTFT or memory pressure. If it is slower but much more
reliable, use it for difficult coding/debug tasks rather than all chat.

## 35B / 122B / 397B strategy

### 35B
Useful on a 24 GB+ GPU or a high-RAM system where slower offload is acceptable.
Because the current Ollama Q4_K_M artifact is about 23 GB, an 8 GB RTX 4060
cannot keep the full model resident. CPU offload may still be worthwhile for
batch/night-school experiments, but never treat it as "fast" without measured
numbers.

### 122B
Candidate for powerful single-node/server inference. Before integration:
- verify the exact quant/backend,
- measure resident memory,
- validate tool schema compatibility,
- compare quality per joule and per second against 35B and existing routes.

### 397B
Research/multi-GPU route only. Litha gains more from smart routing and
verification than from forcing the largest checkpoint onto unsuitable hardware.

## Required benchmark matrix

For every candidate model, record:
- model/revision/quant/backend/build
- context and KV precision
- GPU layers/offload split
- cold load time
- warm first-token latency
- prompt tokens/s
- generation tokens/s
- peak VRAM
- peak system RAM
- tool-call schema accuracy
- duplicate/looping tool-call rate
- coding pass rate
- debugging repair rate
- Roblox/Luau pass rate
- long-context retrieval accuracy
- vision accuracy where supported
- cancellation/recovery behavior
- output quality under concurrent background load

A model cannot become a preferred route from one aggregate benchmark score.

## Code added with this research

- `litha/ornith_profiles.py`: evidence-bounded Ornith capability/deployment
  metadata plus conservative hardware recommendation logic.
- `tests/test_litha_ornith_profiles.py`: regression tests for profile facts,
  consumer-GPU selection, context conservatism and promotion requirements.
- `server/brain/models-ornith.example.ini`: opt-in llama.cpp/router example;
  deliberately not active.

## Follow-up experiments

1. Add Ornith-1.5 9B to the existing RTX 4060 model lab branch rather than
   duplicating that PR's probing/runtime code.
2. Run the same fixed suite across current Qwen, Ornith and any other 8 GB
   candidate.
3. Add a scaffold-ablation benchmark: direct answer vs fixed scaffold vs
   searched scaffold vs best-of-N + verifier.
4. Add adversarial tool-loop tasks and stop-condition tests.
5. If Ornith wins paired coding/agent quality, route only matching workloads to
   it first; expand scope gradually.

## Bottom line

Ornith is valuable to Litha for **two separate reasons**:

1. The 9B release is a credible local coding/agent model candidate for an 8 GB
   GPU, subject to real local benchmarking.
2. The more important architectural lesson is end-to-end improvement of tasks,
   scaffolds and rollouts under an external verifier.

The correct move is not "replace Litha with Ornith." It is to make Litha able to
measure Ornith, borrow the self-scaffolding ideas, and keep whichever strategy
wins under Litha's own evidence gates.
