# Litha Harness Lab — Benchmark Plan

Date: 2026-11-01

## Purpose

Litha should distinguish:
- model intelligence;
- harness quality;
- tool/runtime speed;
- routing quality;
- verification quality.

A change is not called "smarter" until the appropriate metric improves without unacceptable regressions.

## Benchmark families

### 1. Edit mechanics

Dataset:
- 200–500 mechanically generated repairs across Python, TypeScript, Rust and Luau;
- frozen holdout set;
- mutations include wrong literal, condition, identifier, call, range, branch, import and multi-file reference.

Compare:
- full-file replace;
- patch;
- Anchors v2;
- AST edit;
- LSP rename where applicable.

Metrics:
- exact/semantic task pass;
- unchanged-region preservation;
- output tokens;
- input tokens;
- first-edit success;
- repairs required;
- stale-state false accept/reject;
- wall time.

### 2. Semantic debugging

Bug categories:
- type mismatch;
- unresolved symbol;
- async misuse;
- bad API call;
- wrong rename;
- runtime exception;
- state-machine bug.

Arms:
- prompt/text only;
- LSP diagnostics;
- LSP + DAP;
- LSP + DAP + verifier.

Metrics:
- solved;
- tool calls;
- elapsed time;
- tokens;
- wrong-file edits;
- regression count.

### 3. Workspace engine

Repositories:
- small (~1k files);
- medium (~20k);
- large (~100k+);
- Roblox project with generated/vendor/ignored directories.

Measure cold + warm:
- walk;
- glob;
- grep;
- fuzzy file find;
- AST project map;
- cache invalidation after 1/10/100 mutations.

Compare current Python/subprocess path vs native candidate.

Report p50/p95/p99 plus peak RSS.

### 4. Prompt/cache performance

Per model/backend:
- cold TTFT;
- warm TTFT;
- prefill tokens/sec;
- decode tokens/sec;
- prompt-cache hit behavior;
- context length scaling;
- 1/2/N concurrent requests;
- GPU VRAM and system RAM.

Test local RTX 4060 separately from Litha Server.

### 5. Tool-schema context

Arms:
- all schemas attached;
- core + lexical tool retrieval;
- core + hybrid BM25/embedding retrieval.

Metrics:
- prompt tokens;
- tool-selection accuracy;
- wrong-tool rate;
- extra discovery turns;
- TTFT;
- total task time.

### 6. Subagent/Best-of-N

Budgets:
- single;
- sequential retry;
- N=2;
- N=4;
- N=8 where hardware permits.

Metrics:
- verified pass rate;
- useful candidates / spawned candidates;
- duplicate-work ratio;
- token cost;
- RAM;
- VRAM;
- elapsed time;
- promotion/merge conflicts.

Always compare at both equal-candidate and equal-token budgets.

### 7. Provider routing

Inject:
- 429;
- 401;
- 400 bad model;
- 500/502/503;
- connect timeout;
- streamed-body stall;
- context overflow.

Assert:
- correct failure class;
- bounded retry;
- correct allowed fallback;
- no local/LAN/cloud trust crossing without explicit permission;
- cooldown;
- return to preferred route after cooldown.

### 8. Transaction/rollback

Fault injection:
- fail second write;
- kill process during staging;
- kill process during apply;
- disk-full;
- permission change;
- file concurrently modified.

Assert:
- canonical files either committed or restored;
- journal is recoverable after restart;
- exact affected paths reported;
- no false "success".

### 9. Memory/learning

Tests:
- retrieve relevant durable fact;
- reject stale project-state memory when live repo disagrees;
- malicious web text cannot become executable skill;
- lesson only promotes after evidence/gate;
- rollback restores previous behavior.

### 10. Roblox-specific verification

Suites:
- Luau syntax/type/API;
- client/server trust;
- UI responsive constraints;
- Studio object graph;
- playtest assertions;
- screenshot/visual checks;
- performance budget.

Compare:
- prompt-only;
- analyzer;
- analyzer + Studio;
- Best-of-N + Studio verifier.

## Scorecard

Each experiment records:

```json
{
  "commit": "...",
  "suite": "...",
  "hardware": "...",
  "model": "...",
  "harness_profile": "...",
  "pass_rate": 0.0,
  "ttft_p50_ms": 0,
  "ttft_p95_ms": 0,
  "wall_p50_ms": 0,
  "input_tokens": 0,
  "output_tokens": 0,
  "tool_calls": 0,
  "repair_turns": 0,
  "peak_rss_mb": 0,
  "peak_vram_mb": 0,
  "rollback_failures": 0
}
```

## Promotion gate

A harness feature may become default only when:
1. primary intended metric improves on development + holdout;
2. no security boundary weakens;
3. no meaningful regression appears in another core suite;
4. Windows packaging/smoke test passes for native changes;
5. results are reproducible from a clean checkout;
6. benchmark/evaluator code is not editable by the self-improvement candidate being judged.

## First experiments to run

1. Anchors v2 vs current replacement on 200 mutated files.
2. tool discovery vs full registry context.
3. Rust walker/cache prototype vs Python/subprocess search.
4. LSP-guided repair vs prompt-only.
5. 4-candidate isolated Best-of-N vs four sequential retries.
6. routing fault-injection table.
7. transaction rollback under injected second-file write failure.
