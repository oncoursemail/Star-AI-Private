# Litha × OMP Deep Dive — Source-Level Research

Date: 2026-11-01  
Status: research/design on the existing OMP harness branch; not shipped  
Upstream snapshot studied: `can1357/oh-my-pi` around commit `686b5e2fb542848dc3ff1a9e36a42a8fefdd2278`

## Executive conclusion

OMP is one of the strongest public examples of a **coding-agent harness** being treated as a systems-engineering problem instead of a prompt wrapper. Its most useful ideas for Litha are not "use more agents" or "use a bigger model." They are:

1. reduce the amount of text/model work needed to make a correct edit;
2. make semantic program state available through LSP/DAP instead of guessing;
3. move hot filesystem/edit/search primitives into native code;
4. isolate parallel workers so bad candidates cannot damage the canonical workspace;
5. expose tools on demand instead of attaching every schema to every turn;
6. route models by explicit role and failure class;
7. measure harness latency, edit success, retries, cache behavior and rollback—not only answer quality.

The source audit also finds places Litha should deliberately **not** copy: short edit snapshot tags, broad default approvals, project-local executable extension loading, very high task concurrency, and in-process native failure domains on Windows.

The goal is therefore **OMP-inspired, Litha-owned primitives under Litha's stricter policy and verification layer**.

---

## 1. OMP architecture that actually matters

OMP combines a TypeScript/Bun coding-agent runtime with substantial native Rust infrastructure.

Important native areas include:

- `pi-shell`: shell/process/PTY and in-process command behavior;
- `pi-natives`: N-API bridge for search, syntax, diff, token and desktop primitives;
- `pi-walker`: ignore-aware parallel traversal, glob/search and directory-listing cache;
- `pi-ast`: tree-sitter/ast-grep structural operations;
- `pi-edit`: edit protocols including hashline and preview/apply paths;
- `pi-iso`: task workspace isolation backends;
- native/platform-specific pieces for desktop/voice and other capabilities.

The important pattern is the **boundary**: expensive/repetitive filesystem and text operations are not repeatedly delegated to external processes. The agent runtime receives compact structured results.

### Litha implication

Keep React for the UI and Python for the conductor/policy layer. Introduce a native core only for measured hot paths.

Recommended first native boundary:

```text
Litha Python conductor
      |
      +-- litha_native
            +-- workspace walk/cache
            +-- grep/glob
            +-- AST summary/query
            +-- diff
            +-- anchored edit prepare/apply
            +-- optional process/PTY supervisor later
```

Use PyO3 or a small supervised local service. For Windows stability, a process boundary is worth benchmarking against an in-process extension because a native panic/OOM should not kill the whole desktop app.

---

## 2. Hashline: excellent idea, imperfect implementation

OMP's default edit protocol, hashline, is a major reason it is relevant.

A read produces path/snapshot metadata and line anchors. An edit references those anchors rather than asking the model to reproduce an entire file. The runtime validates what the model saw, detects stale state and can attempt guarded recovery.

Relevant source:

- `crates/pi-edit/src/modes/hashline/*`
- `crates/pi-edit/prompts/hashline.md`
- `docs/tools/edit.md`

### Why this works

A model is better at saying "change this small thing at this known location" than regenerating a large file perfectly. Anchors reduce:
- copied context;
- unchanged-token generation;
- accidental deletion;
- line-number drift;
- edit ambiguity.

Stencil's published harness experiment compared edit mechanisms on synthetic React repair tasks across 16 models, 180 tasks, three runs. Their results report hashline outperforming patch on 14/16 models and sometimes sharply reducing output tokens. The most important finding for Litha is not any one score: **changing the harness altered model success dramatically without changing the model**.

Research article:
https://stencil.dev/blog/improving-llms-coding-harness

### Where Litha should go beyond OMP

OMP's file tag is only **four hexadecimal characters**. Its own issue tracker documents collision behavior. A 16-bit-style display fingerprint is too small to use as Litha's primary stale-state identity.

OMP's multi-file edit path also parses/prepares before writing, but an operating-system failure during later writes may leave an earlier prefix of files already modified. That is not a full multi-file transaction.

Litha should implement **Anchors v2**, specified separately in `docs/LITHA_ANCHORED_EDITS_V2.md`.

Core differences:
- 64/128-bit snapshot identity;
- path + range + local-context fingerprints;
- strict seen-range provenance;
- staged writes;
- transaction journal;
- rollback on partial failure;
- model-specific edit protocol selection based on benchmark evidence.

---

## 3. AST edits should complement—not replace—anchored text edits

OMP exposes both:
- `ast_grep` for structural queries;
- `ast_edit` for structural rewrites with preview/apply semantics.

Its AST edit flow can preview a rewrite, require an explicit resolve/apply step, rerun the rewrite at apply time and detect a stale preview.

This is useful because different tasks want different edit primitives:

| Task | Best first primitive |
|---|---|
| one localized fix | anchored text edit |
| rename symbol | LSP rename |
| repetitive syntax rewrite | AST edit |
| format-only change | formatter |
| new file | write/create |
| refactor across modules | LSP + AST + tests |

Litha should route by task shape rather than force one universal edit format.

---

## 4. LSP should become a mandatory semantic verification layer

OMP's LSP tool is much more than diagnostics. It exposes navigation, hover, symbols, rename, code actions and file-rename lifecycle.

One particularly good design is file rename:
1. ask relevant servers for `workspace/willRenameFiles`;
2. merge reference edits;
3. apply semantic edits;
4. perform filesystem rename;
5. roll back reference edits if the filesystem move fails;
6. notify servers.

The LSP implementation also propagates request cancellation.

### Current OMP weakness to avoid

OMP's active issue surface shows multiple LSP lifecycle problems around:
- server/root discovery in polyglot or nested repositories;
- external file-change watcher propagation;
- push vs pull diagnostics;
- server reload/termination;
- code-action applicability;
- raw request edge cases;
- indexing/readiness visibility.

This is normal for a fast-moving project, but it tells us exactly what Litha's abstraction needs.

### Litha semantic layer

Create one semantic service with:

```text
SemanticServer
  diagnostics(file/project)
  definition(location)
  references(location)
  hover(location)
  symbols(scope)
  rename(symbol, new_name, preview=true)
  code_actions(range)
  format(file)
  readiness()
  notify_file_change(...)
```

Requirements:
- file-aware server selection;
- multi-root workspace graph;
- dynamic registration;
- explicit indexing/readiness state;
- merged diagnostics from all relevant sources;
- every Litha mutation path emits file-change events;
- cancellation and timeout propagation.

Luau should plug into this abstraction through luau-lsp/luau-analyze while Roblox Studio-specific state remains a separate adapter.

---

## 5. DAP is a large intelligence multiplier for debugging

OMP implements a broad Debug Adapter Protocol surface including launch/attach, breakpoint variants, stepping, stack/threads/scopes/variables, evaluate, memory, modules, loaded sources, custom requests and child sessions.

The important design lesson is **structured runtime state**.

Instead of:

```text
model -> terminal -> giant debugger log -> model guesses
```

prefer:

```text
model
  -> debug.pause
  -> stack[]
  -> frame
  -> scopes[]
  -> variables[]
  -> targeted evaluate
  -> repair
  -> rerun
```

Litha should add DAP for Python/TypeScript/Rust/server workloads. Roblox can expose analogous structured playtest/debug state through Studio rather than pretending Roblox uses ordinary DAP everywhere.

---

## 6. Isolated subagents are more important than raw agent count

OMP's task system supports:
- batch spawning;
- concurrency limits;
- structured output schemas;
- background jobs;
- saved output via `agent://`;
- isolated worktrees;
- several copy-on-write/isolation backends;
- capture/apply of successful changes;
- parent/child lineage and metrics.

The key principle is **workers do not need write access to the owner's canonical tree**.

OMP also has speculative subagent launch: a child can start as soon as a streamed task item is complete instead of waiting for the full parent tool call.

### Failure modes found in OMP

The issue history shows why Litha needs stronger resource and environment preflight:
- earlier Git state could leak from isolated work into the parent;
- multi-gigabyte workspace baseline handling could create severe memory pressure;
- isolated workspaces can miss required ignored/generated files;
- isolation configuration can be misunderstood by users.

### Litha design

Parallel coding workers should be isolated by policy:

```text
canonical project
    |
    +-- snapshot A -> worker A -> tests -> score
    +-- snapshot B -> worker B -> tests -> score
    +-- snapshot C -> worker C -> tests -> score
    +-- snapshot D -> worker D -> tests -> score
                                      |
                               verifier/judge
                                      |
                           promote one semantic diff
```

Before spawning:
- discover required generated/ignored dependencies;
- estimate snapshot size;
- choose backend;
- reserve RAM/CPU/model slot budget;
- refuse excess concurrency.

For the user's local 8 GB GPU target, model parallelism should normally be conservative. Litha can still parallelize native scans, tests and read-only specialists while serializing GPU-heavy model generations.

---

## 7. Structured subagent output is better than prose delegation

OMP has structured subagent support and saved result artifacts.

Litha should standardize every worker result:

```json
{
  "task_id": "...",
  "status": "passed|failed|partial",
  "summary": "...",
  "findings": [],
  "touched_paths": [],
  "diagnostics_before": {},
  "diagnostics_after": {},
  "tests": [],
  "artifacts": [],
  "patch": "...",
  "risk": [],
  "confidence": 0.0,
  "score_components": {}
}
```

The parent should compare evidence, not rely on a child saying "done."

---

## 8. Tool discovery is one of OMP's best context ideas

OMP can keep many extension tools out of the top-level model tool schema and expose discoverable tools through an internal `xd://` mechanism. The model can inspect a tool only when it needs it.

This attacks a major hidden tax in agent systems: **tool schemas consume context on every turn**.

### Litha design

Keep only a tiny stable core attached:

- read;
- search;
- edit;
- execute/test;
- semantic/LSP;
- delegate;
- discover_tool.

Everything else:
1. filtered by policy/capability;
2. indexed by name/description/input shape;
3. retrieved just-in-time;
4. schema loaded only for the active task.

Discovery must never grant authority. It can only reveal a capability already enabled by Litha's policy layer.

---

## 9. Persistent code kernels + tool callbacks

OMP's Eval environment keeps persistent Python and Bun workers, and code running inside those environments can call back into agent tools.

This allows analysis/data manipulation to stay in one execution context rather than repeatedly serializing huge intermediate results through the language model.

### Litha use cases

- analyze benchmark CSV/JSON without stuffing the full data into prompt context;
- inspect game telemetry;
- compare candidate test outputs;
- run geometry/statistical checks;
- build plots/reports;
- transform asset metadata;
- execute deterministic scoring logic.

Keep kernels sandboxed and project-scoped. Tool callbacks must still pass Litha policy; a Python cell must not be a permission bypass.

---

## 10. Provider roles and fallback chains

OMP has model roles such as default/fast/slow/vision/plan/advisor/memory/judge and configurable fallback chains.

This is the correct conceptual direction, but Litha has an existing advantage: provider types are already separated into local/LAN/cloud and private endpoint handling is strict.

### Litha model-role layer

Recommended roles:

- `chat`
- `fast`
- `code`
- `reasoning`
- `vision`
- `research`
- `judge`
- `memory`
- `image`

Fallback is based on **failure class**, not "model answered badly":

| Failure | Same route retry | Fallback |
|---|---:|---:|
| transient network / 5xx | bounded | yes |
| 429/quota | usually no | yes |
| auth | no | no |
| invalid config/model id | no | no |
| context overflow | no | only explicit compatible context route |
| policy refusal | no automatic route shopping | no |
| malformed tool output | repair same role / verifier | policy dependent |

Default: never cross local/LAN/cloud trust boundaries silently.

The first transport-independent version of this logic already exists in this branch at `star/harness_routing.py`.

---

## 11. Advisor/watchdog architecture

OMP can run a second advisor model against the primary transcript and inject concerns/blocks.

This is useful, but Litha should use it selectively.

For local hardware:
- don't run an expensive critic after every tiny tool call;
- invoke critic at design boundary, before risky mutation, after candidate completion, and before final promotion;
- prefer a different model/family when available;
- keep critic read-only;
- require evidence references.

A critic that cannot point to a file/diagnostic/test is weak evidence.

---

## 12. Memory: OMP has useful layering; Litha has the stronger promotion gate

OMP explicitly treats retrieved memory as heuristic/background rather than authoritative live repository state. It supports project-scoped memory and durable lessons/skills.

That separation is good.

Litha should preserve its stronger existing self-learning idea:

```text
episode/evidence
   -> durable fact
   -> candidate lesson
   -> repeated evidence
   -> regression test
   -> holdout/statistical gate
   -> review/trial
   -> promoted skill
```

Untrusted web/project text can contribute evidence but can never directly become an executable skill or grant permissions.

---

## 13. Filesystem walker/cache: copy the architecture, benchmark the policy

OMP's `pi-walker` uses long-lived workers, a shared directory queue and a shared directory-listing cache. It retains directory listing information and reapplies traversal policy to each walk.

Important nuance: OMP does **not** simply cache every search result. Some search paths deliberately remain fresh/streamed.

### Litha design

Build one workspace metadata service:
- ignore-aware traversal;
- file type and size metadata;
- directory listing cache;
- invalidation after writes/renames/deletes;
- bounded TTL/memory;
- cancellation;
- streaming early stop;
- per-consumer freshness policy.

Consumers:
- project map;
- file picker;
- grep/glob;
- AST discovery;
- retrieval index;
- skill/project-rule discovery.

Do not cache raw grep results across mutations unless the cache key/version proves validity.

---

## 14. Benchmark infrastructure is a feature, not QA leftovers

OMP includes benchmark tooling for:
- TTFT;
- prefill;
- decode;
- p50/p95;
- prompt-cache workloads;
- parallel scaling.

Its edit research also measures harness correctness/token efficiency.

Litha should add a permanent **Harness Lab**. See `docs/LITHA_HARNESS_BENCHMARKS.md`.

The critical rule:

> Never call an infrastructure change an intelligence improvement until it wins a reproducible task-level metric.

---

## 15. Security: Litha should intentionally diverge from OMP

OMP has a capable approval/policy framework, but its product defaults and project extensibility are much more permissive than Litha should use.

Research found:
- a default `yolo` approval mode in OMP's documented approval system;
- project-local settings/extensions/hooks/skills/rules/MCP surfaces loaded by design;
- headless subagents treating parent task authorization as their boundary;
- issue reports warning about malicious-repository startup code paths.

This does not make OMP "unsafe" in every deployment; it reflects a different product trust model.

### Litha rules

- cloned/opened project is untrusted data by default;
- project-local code never executes merely because the folder was opened;
- skills/rules are reference data until explicitly enabled/trusted;
- no subagent gets broader authority than the parent;
- no web/project text can elevate capability;
- credentials live outside the model context and outside untrusted child processes;
- risky executors are process-isolated;
- every mutation has provenance;
- cloud use remains explicit.

This is an area where Litha should be **safer than OMP by architecture**, not configuration.

---

## 16. Windows-specific lessons

OMP's issue/changelog history includes Windows-specific native problems:
- Windows Defender Application Control/native addon blocking after updates;
- memory/commit exhaustion during concurrent native/subagent work;
- native runtime worker-thread startup failures on constrained systems;
- high callback pressure from chatty subprocess output.

These are valuable warnings for Litha's Windows-first target.

### Litha requirements

- baseline x64 build first; optional AVX2 selected after CPU feature detection;
- sign native binaries when distribution pipeline supports it;
- resource governor for worker/thread/process counts;
- bounded output queues with chunk coalescing;
- native crash isolation where practical;
- explicit pagefile/commit diagnostics;
- packaged Windows smoke tests, not Linux-only CI claims.

---

## 17. What to copy / outperform / avoid

| Area | Copy | Outperform | Avoid |
|---|---|---|---|
| Edits | anchored small edits | stronger fingerprints + transaction journal | 4-hex identity |
| AST | preview/apply structural rewrites | combine with LSP/test verifier | AST as universal hammer |
| LSP | semantic tools + cancellation | multi-root, file-watch, readiness | brittle root-marker-only activation |
| DAP | structured debug state | unified Litha debug evidence | dumping raw debugger logs into context |
| Tasks | isolation + structured outputs | resource-aware Best-of-N promotion | huge default concurrency |
| Native core | Rust hot paths | recoverable Windows boundary | rewrite-everything-in-Rust |
| Tools | lazy/discoverable schemas | capability-filtered semantic retrieval | giant static tool list |
| Models | roles + chains | trust-aware failure routing | silent local->cloud fallback |
| Memory | project-scoped heuristic memory | gated lesson/skill promotion | memory as live truth |
| Reviewer | independent advisor | evidence-backed verifier | critic on every micro-step |
| Security | explicit policy framework | untrusted-project default | project auto-exec / blanket yolo |
| Benchmarks | harness measurements | permanent regression lab | anecdotal "feels smarter" claims |

---

## 18. Priority roadmap for Litha

### P0 — reliability per token
1. Anchored Edits v2.
2. Tool-schema discovery.
3. deterministic failure-aware routing.
4. structured subagent result schema.
5. harness benchmarks.

### P1 — semantic coding intelligence
6. normalized LSP layer.
7. edit -> diagnostics -> test -> repair loop.
8. AST project map and structural edit preview.
9. verifier/judge role.

### P2 — parallel verified execution
10. isolated Best-of-N workspaces.
11. resource governor.
12. deterministic candidate scoring/promotion.
13. DAP structured debugging.

### P3 — native speed
14. Rust walker/cache.
15. native grep/glob/AST summaries/diff.
16. supervised native process option on Windows.
17. adaptive CPU feature builds.

### P4 — adaptive harness
18. learn routing/edit-mode choices from benchmark history.
19. per-project capability profile.
20. automatic regression suite selection.
21. measured self-improvement proposals.

---

## Primary upstream material reviewed

- https://github.com/can1357/oh-my-pi
- https://github.com/can1357/oh-my-pi/blob/main/README.md
- https://github.com/can1357/oh-my-pi/blob/main/docs/tools/edit.md
- https://github.com/can1357/oh-my-pi/blob/main/docs/tools/lsp.md
- https://github.com/can1357/oh-my-pi/blob/main/docs/tools/debug.md
- https://github.com/can1357/oh-my-pi/blob/main/docs/tools/task.md
- https://github.com/can1357/oh-my-pi/blob/main/docs/tools/eval.md
- https://github.com/can1357/oh-my-pi/blob/main/docs/approval-mode.md
- https://github.com/can1357/oh-my-pi/blob/main/docs/fs-scan-cache-architecture.md
- https://github.com/can1357/oh-my-pi/blob/main/docs/natives-text-search-pipeline.md
- https://github.com/can1357/oh-my-pi/blob/main/docs/advisor-watchdog.md
- https://github.com/can1357/oh-my-pi/blob/main/docs/memory.md
- https://github.com/can1357/oh-my-pi/issues
- https://stencil.dev/blog/improving-llms-coding-harness

Research conclusions should be rechecked against upstream before implementation because OMP is changing rapidly.
