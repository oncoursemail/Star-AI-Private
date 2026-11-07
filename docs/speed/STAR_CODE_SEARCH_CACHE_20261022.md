# STAR AI: Code Search Acceleration + Intelligence Research

**Research / measured development:** October 22, 2026

**Branch:** `feat/star-code-search-speed-20261022` (private STAR repository)

**Status:** Tested isolated opt-in development change. NOT enabled in the public Windows installer, not merged into `star/next`, and not proof that model answers are 2x faster.

## Executive decision

STAR does not primarily need another heavyweight model, more simultaneously running agent copies, or thousands of auto-loaded skill prompts. On the current hardware, prioritize (1) reducing repeated computation, (2) preserving llama.cpp prefix-cache locality, (3) dynamically assigning verification effort, and (4) improving task exploration and evidence collection. Each improvement must survive a realistic task-quality and latency gate, including contention with other models.

I inspected current `star/next` routing, memory, code navigation, cache banks and resource planners, reviewed recent performance/oracle PRs, checked the connected machine resource summaries, and ran isolated local benchmarks on the STAR server. The implementation in this branch addresses one directly observed pure-Python bottleneck: repeated workspace source reads and Python AST parsing.

## Current STAR architecture: do not duplicate

- `star/brain_router.py` routes requests deterministically without an extra classifier-model call. `star/instant_route.py` offers a conservative local-only fast path.
- `star/context_layout.py` preserves byte-stable request prefixes, and `star/turn_memory.py` retains sticky tool ordering for prompt-cache locality.
- `star/cache_banks.py` already has an opt-in, revision-pinned server-side stable-prefix KV snapshot mechanism; avoid untested alternative cache formats.
- `star/skill_routing.py` already has keyword-first and embedding fallback selection with opt-in disk caching.
- `star/cascade_router.py`, `star/agent_resource_planner.py` and `star/skill_evolution_lab.py` model routing, resource admission and bounded skill evolution.
- `star/code_navigation.py` scans user-authorized workspaces and parses Python ASTs on each query. Its `_files()` helper is shared by `star/repo_map.py`.
- Existing PR #545 measured hardware trials and did not switch the service: the reported speculative configuration improved single-stream generation by 3.9%, while CPU pinning lost 31%/55% under contention; the priority-proxy trial failed its user-latency rules and was reverted.
- Existing PR #546's oracle does not yet predict observed pass-rate changes reliably (its L2 sign matched 5 of 9 past tests and Spearman was -0.07), so do not let it auto-select "improved" models.
- Existing PR #554 explores mistake memory/fixers; treat verified task evidence and independent tests as a hard prerequisite for activating self-written repairs.

### Resource observation at time of inspection

- Brain server `starai`: 125 GiB RAM, about 59 GiB available, 8 GiB swap with ~3.3 GiB used; **15 GB disk available (93% filesystem usage)**; load average around 21. These are snapshots, not service-level trend measurements.
- Smaller server (server 2): 15 GiB RAM, ~2.2 GiB available, 4 GiB swap nearly fully used; running additional resident models may cause major swapping.
- Main Windows PC: 61 GB reported free on C:, and user-described NVIDIA RTX 3060 Ti with 8 GB VRAM; test actual GPU free memory during work before admitting heavy voice/image/video jobs.

These constraints argue against a "spawn every agent" configuration, speculative GPU offloads without capacity checks, and multiple concurrent heavy image/voice jobs.

## What research says in 2026

### Agent design: more copies is not smarter

Google Research reports experiments over 180 configurations: multi-agent coordination improves parallelizable tasks, but often worsens sequential tasks. STAR should use a **single principal agent for sequential work** and subdivide into parallel workers only where dependencies allow it, with explicit resource limits. Source: https://research.google/blog/towards-a-science-of-scaling-agent-systems-when-and-why-agent-systems-work/ (January 28, 2026).

### Llama.cpp: cache and speculation are workload-dependent

Current llama.cpp server documentation specifies `--cache-prompt`, `--cache-reuse`, slot management and model load modes. Its speculative decoding documentation includes draft-model, n-gram map and other approaches. These are promising only if the actual STAR model, history shape and simultaneous load benefit; a benchmark or blog claim on another GPU does not transfer.

- https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md
- https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md

vLLM reports that FP8 KV caching can increase concurrency/length in particular architectures, but do not confuse vLLM’s memory/attention kernel with llama.cpp’s implementation or quality. Source: https://vllm.ai/blog/2026-04-22-fp8-kvcache

### Model candidates: separate hardware tiers

Qwen3.5 provides small, natively multimodal 0.8B/2B/4B/9B variants; Qwen3.8-27B has official open weights (released August 14, 2026) but a 27B quantized checkpoint commonly needs substantially more than 8 GB GPU memory once KV/cache overhead is included.

- https://github.com/QwenLM/Qwen3.8
- https://qwen.ai/blog?id=qwen3.8
- https://huggingface.co/docs/transformers/main/model_doc/qwen3_5

STAR should benchmark a small PC-resident model for fast/private short tasks and treat larger reasoning/coding models on available servers or explicitly selected hosted providers as separate, user-configured capacities. **Do not silently route project files to hosted providers.**

### Learning: reflective optimization, but independent holdout

GEPA (Genetic-Pareto) reflects on failures and searches for improved prompt candidates with fewer trials than some reinforcement techniques in its published tasks. STAR already has a GEPA-inspired skill evolution lab, so adapt it, don't import a second agent harness wholesale. Success requires sealed holdouts, repeat runs, rollback and protection from evaluator modifications.

- https://arxiv.org/abs/2507.19457
- https://github.com/gepa-ai/gepa

### Game intelligence: inspect before editing

Roblox's official OpenGameEval evaluates actual scene edits and simulated play-mode behavior, not merely generated Luau text. Across 84 human-curated tasks, exploration behavior predicts success. The cited differences between inspected and uninspected runs are correlations conditional on task/model, **not guaranteed causal gains**.

- https://github.com/Roblox/open-game-eval
- https://arxiv.org/abs/2610.02563

### Security: tools and retrieved text are untrusted

An August 2026 study of indirect prompt injection found that some defenses reduce attack success while also reducing legitimate-task utility; report both. An ACL Industry Track paper describes threats from MCP tool outputs and recommends scoped validation. Never treat an imported skill, web page, Discord attachment or GitHub README as permission to use a tool or leak private context.

- https://www.mdpi.com/2073-431X/15/9/570
- https://aclanthology.org/2026.acl-industry.58/

## Implemented experiment: STAR source navigation micro-cache

### Mechanism

`star/code_navigation.py` now supports `STAR_CODE_SEARCH_CACHE=on` to reuse text/casefold and parsed Python symbols from repeated scans. The cache is only in process RAM: no saved source content, no background indexing, no subprocess, no network, no changes to the workspace, and no additional model calls.

- The original `Workspace.resolve` checks still run for **every** file and query; denied secrets, symlinks, generated directories and out-of-scope paths remain prohibited.
- A file's cache key includes canonical path, device ID, inode, byte size, nanosecond mtime and ctime. Normal edits and atomic replacements invalidate the snapshot. This is **not an adversarial cryptographic integrity guarantee** against forged filesystem metadata.
- Each cache has a 24 MiB estimated memory cap and at most 3,072 entries, with a 96 KB per-file size limit; raw-byte scan admission avoids thrashing on extremely large projects. The 24 MiB is a conservative estimated payload bound, not an exact Python heap limit.
- `_files(..., with_stat=False)` preserves the shared historical two-tuple API for `repo_map`. Search itself requests the optional stat object, avoiding a second filesystem stat on cache hits.
- Default remains **OFF** until full Windows tests, loaded-runtime validation and representative quality/performance evaluations. Normal behavior is byte-for-byte compatible when OFF.

### Measured timings

Tests run on an isolated checkout snapshot on the connected `starai` server. The AI model and live inference services were not restarted or benchmarked. Synthetic files contain Python classes and methods; benchmarks run repeated searches with identical output assertions.

| Workload | Cache OFF median | Cache ON warm median | Speedup |
| --- | ---: | ---: | ---: |
| Synthetic, 300 files, 10 repeated searches | 109.062 ms | 47.531 ms | 2.295x |
| Synthetic, 800 files, 10 repeated searches | 293.961 ms | 129.067 ms | 2.278x |
| Read-only STAR source snapshot, 847 code files, Python symbol search | 2086.07 ms | 1464.82 ms | 1.42x |
| Same STAR tree, text search stopping after 11 scanned files | 21.34 ms | 19.84 ms | 1.08x |

Important nuance: text search already exits early when the result budget is full, so caching often helps much less. The real STAR tree is a source snapshot, **not** the entire current worktree or a Windows package. Results are under current server load and are not a claim about chat completion latency. Cache outputs matched baseline for the measured queries.

The first implementation cached file text only and achieved about 1.058x in a 300-file test. Caching Python AST declarations improved that. A later 800-file benchmark exposed LRU thrashing at 512 entries (0.936x); scan-aware admission plus a larger bounded entry count corrected it. This iteration history is retained as negative evidence, not hidden.

### Validation

- Focused new + existing code navigation tests: 22 passed.
- Broader integration including repo map, workspace validation and protected paths: **86 passed**.
- First broader run caught a breaking change to `_files()` used by `repo_map.py`; fixed by restoring the old default iterator contract, followed by the 86/86 pass.
- Compilation via `compileall` succeeded. Tests are not proof of production performance, full suite compatibility or security review.

Reproduce without touching production:
```bash
python -m benchmarks.code_search_cache --files 300 --repeats 10
python -m benchmarks.code_search_cache --files 800 --repeats 10
```

## Original next-stage ideas (proposals, not shipped features)

### 1. STAR Proof-Per-Millisecond

For each task, select the cheapest **independent verification** expected to eliminate its likely failure class: Luau static checks for script syntax; a Studio play-mode test for replicated gameplay; visual screenshot checks for UI; numerical checks for math; transcript-alignment checks for video. A higher-cost verifier is invoked only on uncertainty or disagreement. This is an *allocation policy*, not a shortcut around required safety or completion criteria. Calibrate from observed task failures rather than agent self-confidence.

### 2. STAR Task Shape Compiler

Convert an owner goal into a typed DAG: `inspect -> modify -> build -> run -> compare -> report`, marking each operation’s tool scope, input artifact, output artifact, verification proof and dependency. Sequential edits keep one worker; independent tasks can parallelize only when resource admission says they will not starve real-time chat. Reuse `star/agent_resource_planner.py` and `star/agent_runtime.py` rather than creating unbounded independent agents.

### 3. STAR Symbol Graph with Change Journal

Evolve the opt-in in-memory source cache into a project-scoped, incremental symbol/reference graph with content hashes and editor-file-change signals. This would avoid rescanning hundreds of files when only one module changes. A stale or ambiguous graph should fall back to the original bounded scanner. Evaluate on real Python/Luau/TypeScript repos, rename/move/symlink attacks and generated-file exclusion, not only synthetic test files.

### 4. STAR Evidence Receipts

Each "completed" task must link to an actual output and a minimal proof set: commit SHA/diff, build command/exit code, runnable test, screenshot/video capture, artifact checksum, or an explicit "not tested" flag. No self-generated rating can replace a programmatic verifier. Skill lessons update only after confirmed fixes.

### 5. STAR Cache Locality Covenant

Keep system prefixes, tool schemas, and accepted project facts stable within each conversation to preserve llama.cpp KV cache. Group tool acquisition by capabilities and add tool schemas only at deliberate boundaries. **Do not compress/reorder active tool schemas without paired quality and prompt-cache tests**, because Qwen templates place tools before the system message.

### 6. STAR Reversible Performance Tournament

Produce baseline + candidate config runs on the *same* model, prompt lengths, context and workload, both single-user and under contention. Gate on p50/p95 first-token latency, prompt tokens/s, generation tokens/s, memory pressure, task pass rate, prompt-cache reuse, and failure rates. A change that wins synthetic decode but loses owner-interactive latency should be rejected automatically. Keep existing pretrial config and restore it after experiments.

### 7. STAR Memory Evidence Pyramid

Separate **observed source evidence**, **user-approved project decisions**, **validated reusable lessons** and **untested ideas** in storage and retrieval. Retrieved notes carry revision, source, scope and confidence metadata. Avoid turning model guesses into "things STAR learned." The LLM should see only small, directly relevant evidence, not a huge flat transcript.

### 8. STAR Media Budgeter

Before processing images, audio or videos, calculate GPU memory and job dependencies. On the 8 GB GPU, serialize conflicting heavy model workloads, prefer CPU-light preprocessing (FFmpeg/transcription/scene cuts) and send only the necessary timed evidence to the selected vision model. Voice calls receive real-time priority over batch rendering when the owner explicitly enables that behavior. No silent cloud fallback.

## Experimental promotion gates

1. Verify current-source integration and Windows + Linux tests. Run a real edited-file freshness test where Star writes one file and immediately asks search to find it.
2. Validate correct outputs and lack of any protected-source exposure. Add a full-source code map regression and multi-workspace scenario.
3. Compare OFF and ON on several real project sizes, including cold and warm search, contentions and filesystem-change storms. Admit only statistically supported gains with no correctness regression.
4. Check end-to-end agent tasks: search -> choose file -> read -> edit -> test. Record time saved vs unchanged content quality. A 2.3x search speedup does **not** imply a 2.3x coding-agent speedup.
5. Review and merge privately; public release only after separate package acceptance and owner approval.

**Decision:** keep the cache experimental and opt-in, do not change production models, scheduler flags, user files, or public release in this PR.
