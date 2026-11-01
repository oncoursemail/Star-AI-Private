# Litha × OMP research and integration plan

Date: 2026-11-01
Status: implementation research branch; not a shipped feature
Upstream studied: https://github.com/can1357/oh-my-pi (OMP / Oh My Pi)

## Why OMP matters to Litha

OMP is useful less as a product to embed and more as evidence for how a coding-agent harness can become dramatically faster and more reliable when the hot path is engineered around deterministic native primitives rather than repeated shell-outs and prompt-only orchestration.

Current OMP claims/implements a large Rust-native core, an embedded shell, ignore-aware parallel filesystem walking, tree-sitter AST support, atomic edit application, LSP/DAP operations, isolated subagent workspaces, multi-provider routing, browser/desktop tools, memory/skill primitives, and a harness benchmark layer.

Litha should preserve its existing local-first security model, project-scoped permissions, prompt-cache-aware context layout, Roblox/Studio specialization, Best-of-N verification and explicit owner gates. The recommended direction is therefore **OMP-inspired primitives under Litha's policy layer**, not replacing Litha with OMP.

## Highest-value ideas to adopt

### 1. Rust-native hot path

Build a small native core behind Python first, then move only measured bottlenecks.

Priority crates/modules:
- parallel ignore-aware workspace walker and shared scan cache;
- fast grep/glob/file metadata;
- tree-sitter AST summaries for supported languages;
- atomic patch application;
- optional PTY/process supervisor;
- diff primitives;
- token/counting helpers only when they beat current implementations.

Do not rewrite the whole app in Rust. Keep React/TypeScript UI and Python orchestration until profiling proves a boundary is hot enough to justify migration.

Target:
- one workspace scan reused by search, glob, project map and retrieval;
- no repeated subprocess startup for basic file operations;
- cancellation propagated through every native operation;
- safe baseline binary plus AVX2-optimized Windows build when packaging supports it.

### 2. Hash-anchored / line-anchored edits

Litha currently needs stronger edit conflict resistance for long-running coding agents.

Adopt an edit protocol where a proposed replacement is anchored to:
- path;
- expected line/hash fingerprint;
- local context;
- replacement text.

Before apply:
1. re-read the target region;
2. verify fingerprint/context;
3. stage a preview;
4. reject on ambiguity or stale content;
5. atomically write;
6. return exact changed ranges and new fingerprint.

This is much safer than asking a model to emit an entire replacement file.

### 3. LSP as a first-class tool

For supported languages, Litha should expose semantic operations instead of repeatedly asking the model to infer structure from text:
- diagnostics;
- go-to-definition;
- references;
- document/workspace symbols;
- rename preview;
- code actions;
- hover/type information.

For Luau specifically, preserve the existing Luau analyzer/lsp work and normalize it behind the same semantic-tool interface.

Verification loop:
edit -> format -> LSP diagnostics -> language-specific tests -> targeted repair.

### 4. DAP/debugger loop

Add a debugger adapter boundary for languages/runtimes that expose DAP:
- launch/attach;
- breakpoints;
- continue/step;
- stack;
- scopes/variables;
- evaluate;
- terminate.

The model should receive structured debugger state, not raw terminal noise.

### 5. Parallel subagents with workspace isolation

OMP's isolation concept is especially relevant to Litha's Best-of-N goal.

Desired model:
- each candidate/worker gets an isolated copy/reflink/overlay of the workspace;
- workers may not mutate the owner's canonical tree;
- evaluation runs inside the candidate workspace;
- only the winner's semantic diff is promoted;
- promotion still passes Litha policy and review gates.

On Windows, investigate projected filesystem/reflink/copy-on-write options; fall back to bounded copy when unavailable.

### 6. Structured agent-to-agent state

Subagents should return typed results, not prose blobs.

Minimum schema:
- task id;
- status;
- findings;
- touched paths;
- tests executed;
- test outcomes;
- unresolved risks;
- candidate score;
- artifacts;
- evidence links.

This allows a conductor to compare candidates deterministically and prevents context bloat.

### 7. Better provider failover

OMP's provider routing suggests adding explicit, policy-safe fallback chains to Litha.

Requirements:
- configured by role (fast, reasoning, vision, coding, judge);
- never silently cross local/private -> cloud boundaries;
- credential availability checked before a run;
- quota/rate-limit/transient failures may advance within an allowed chain;
- auth/config/context errors fail closed unless a specifically compatible fallback exists;
- cooldown state avoids hammering a failing provider;
- preserve conversation cache affinity where the backend supports it.

### 8. Tool discovery instead of giant tool payloads

Litha should avoid attaching every tool schema to every model turn.

Introduce:
- a tiny stable core tool set;
- searchable tool catalog;
- BM25/embedding retrieval of relevant tool schemas;
- deterministic allowlist filtering before retrieval;
- optional promotion of frequently used project tools.

Security rule: discovery can only reveal tools already allowed by policy; it never grants capability.

### 9. Memory + learned skill separation

Keep three layers distinct:
- episodic memory: what happened;
- durable facts/preferences: compact retrievable state;
- executable skill: reviewed procedure with tests and permissions.

Never turn untrusted web text directly into an executable skill.

Promotion path:
observation -> candidate lesson -> repeated evidence -> regression test -> reviewed skill -> measured rollout.

### 10. Harness benchmarks

Litha needs harness-level benchmarks, not only model-answer benchmarks.

Measure:
- edit success under concurrent file changes;
- tokens/context used per task;
- first-token latency;
- workspace scan latency;
- semantic navigation latency;
- repair-loop convergence;
- tool-call count;
- subagent useful-work ratio;
- wall-clock time;
- pass@1 and verified Best-of-N;
- rollback correctness.

Keep blind holdouts that the self-improvement loop cannot edit.

## What NOT to copy blindly

- Do not make every capability enabled by default.
- Do not route to cloud providers without explicit owner configuration.
- Do not let browser/web content authorize tools.
- Do not give subagents unrestricted writes to the canonical workspace.
- Do not rewrite the complete Python core in Rust before profiling.
- Do not adopt third-party vendored code without preserving licenses/notices.
- Do not treat OMP feature count or repository size as evidence that a design is automatically better.

## Litha target architecture

```text
React desktop UI
    |
Python conductor / policy / project state
    |
    +-- model router
    |     +-- local GPU
    |     +-- Litha server
    |     +-- explicit hosted providers
    |     +-- role-scoped fallback chains
    |
    +-- semantic tools
    |     +-- LSP
    |     +-- Luau analyzer/LSP
    |     +-- DAP
    |     +-- tree-sitter project map
    |
    +-- verified workspace engine
    |     +-- Rust walker/cache
    |     +-- anchored edit staging
    |     +-- atomic apply
    |     +-- diff
    |     +-- process supervisor
    |
    +-- isolated worker pool
    |     +-- candidate A
    |     +-- candidate B
    |     +-- candidate C
    |     +-- judge/verifier
    |
    +-- memory / lessons / skills
          +-- typed evidence
          +-- regression tests
          +-- promotion gate
```

## Implementation phases

### Phase A — low-risk foundation
- Add deterministic failure classification/fallback policy helper.
- Add harness benchmark definitions.
- Specify structured subagent result schema.
- Add anchored-edit format and golden tests.
- Add capability-aware tool catalog interface.

### Phase B — native performance core
- Create Rust workspace under `native/`.
- Implement walker + scan cache first.
- Expose through PyO3 or a small local IPC boundary.
- Benchmark against current Python/subprocess path before adopting.

### Phase C — semantic coding loop
- Normalize LSP operations.
- Add DAP adapters.
- Route edit verification through diagnostics/tests.
- Add AST summaries to retrieval/project maps.

### Phase D — isolated Best-of-N
- Workspace snapshot/isolation layer.
- Parallel candidate scheduler aware of CPU/RAM/VRAM.
- Judge based on tests, diagnostics and semantic diff quality.
- Promote only passing candidate.

### Phase E — adaptive harness
- Tool retrieval.
- Role-scoped provider chains.
- learned routing from measured task outcomes;
- per-project capability profiles;
- automated harness regression dashboard.

## Acceptance gates

A feature only moves toward default-on when:
1. it wins a reproducible benchmark;
2. it does not weaken existing security boundaries;
3. failure behavior is explicit and recoverable;
4. tests cover cancellation, stale edits and malformed tool output;
5. Windows packaging is exercised for native components;
6. regression holdouts do not degrade;
7. rollback is trivial.

## Immediate experiments

1. Anchored edits vs full-file replacement on 100 mutated files.
2. Shared scan cache vs repeated Python glob/grep on large game repos.
3. LSP-guided repair vs prompt-only repair on Python/TS/Luau bugs.
4. 4-way isolated Best-of-N vs sequential retry at equal token budget.
5. tool-schema retrieval vs attaching the full tool registry.
6. deterministic fallback policy under injected 429/5xx/timeouts.
