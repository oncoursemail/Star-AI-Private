# Litha: Freebuff research and bounded code context implementation — 2026-10-31

Research snapshot: `CodebuffAI/freebuff` at `a51a3d5dce5c3d511cd3aa148e361085a700293d`, authored 2026-11-01 00:33 UTC (October 31 in America/Chicago). Read through the connected GitHub tools. No upstream software, install script, agent template, or hosted account was executed. This document distinguishes inspected upstream code, changes in this draft, and later experiments. It does not claim deployment or improved model intelligence.

## This draft's implementation status

Repository: `oncoursemail/Star-AI-Project`. Baseline: `a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f` on `star/next`. Task branch: `feat/litha-freebuff-context-20261031`. The older STAR module names remain the actual code paths. The separate Rust upgrade in draft PR [#849](https://github.com/oncoursemail/Star-AI-Project/pull/849) is not part of this change.

This draft implements two local, experimental improvements:

| Change | Implementation and behavior | Activation |
| --- | --- | --- |
| Batched workspace investigation | `star/code_search_batch.py::batch_search_workspace` accepts 1–8 text/symbol queries in one scan. Files are read at most once per batch; text hits share enclosing-declaration inspection and symbol queries share parsed declarations. It returns path/line evidence and explicit incompleteness fields. | `workspace_search_batch` is advertised and dispatched only when `STAR_CODE_SEARCH_BATCH=on`. |
| Repository-map cache reuse | `star/repo_map.py` reuses `star/code_navigation.py`'s existing bounded source/Python-declaration LRU. It still walks, resolves and stats eligible files on each call. It does not cache an entire map across changes or introduce another index. | Requires both `STAR_CODE_MAP_CACHE=on` and `STAR_CODE_SEARCH_CACHE=on`. |

All switches default to off. Batch search can operate without the source cache; setting `STAR_CODE_SEARCH_CACHE=on` permits the existing cache to serve eligible batch reads. An internal Python helper can be called directly by trusted code; the opt-in switch is enforced at the model-facing workspace-tool boundary. No Freebuff account, API, SDK, model, background process or telemetry service is added. No third-party implementation was copied.

The batch result has a 16,000-byte serialized UTF-8 JSON ceiling, shared across queries using round-robin result admission. A 24,000,000-byte source-scan ceiling adds to the existing directory, file-count and per-file limits. Per-query hit limits remain bounded. `omitted_matches` counts collected hits removed to fit the output, while `limit_reached` and `scan_limited` indicate unknown additional results; the tool does not pretend it knows an exhaustive total after stopping. These are application work/output limits, not model token limits or process-memory measurements.

The shared LRU uses device, inode, size, nanosecond modification time and change time to decide reuse. It also checks metadata after reading before caching a snapshot. This is metadata-based invalidation, not cryptographic content verification or protection against concurrent hostile filesystem replacement. Existing workspace path checks and exclusions remain necessary. Python declarations use the AST; other supported languages use heuristic signatures. This draft does not introduce a Rust or Luau parser.

A model-facing example, after the batch switch is enabled:

```json
{
  "queries": [
    {"query": "workspace_search", "mode": "text"},
    {"query": "search_workspace", "mode": "symbols"},
    {"query": "test_workspace", "mode": "text"}
  ]
}
```

This reduces repeated host work within one investigation by construction. It does not yet establish lower end-to-end LLM latency, improved task success or better reasoning. Validation and benchmark evidence must be reported with the exact fixture, settings and limitations.

## Decision

Adapt the selective-context, bounded-work, proposal-before-apply, and verification practices inside Litha's existing Python runtime. Do not replace Litha with Freebuff or make its hosted service a mandatory dependency. Litha already has stable prompt layout, shared resource accounting, context limits, offline evaluation, and scoped tooling; changes should extend those components.

The largest surprise is that Freebuff's current code backs away from indiscriminate coding-agent fan-out. The useful result is not “run more agents”; it is reducing redundant reads, keeping a cacheable prefix, choosing independent work carefully, and verifying the final combined change.

## What the public project actually includes

Freebuff is a TypeScript/Bun monorepo with CLI, SDK, shared contracts, agent definitions, provider shims, parsing helpers, and agent runtime. `CONTRIBUTING.md` identifies the public repo as a mirror of a private source of truth and excludes backend, database, billing and deployment code. A clone is therefore not evidence of a complete self-hostable equivalent of every hosted product.

Sources:

- [AGENTS.md](https://github.com/CodebuffAI/freebuff/blob/a51a3d5dce5c3d511cd3aa148e361085a700293d/AGENTS.md)
- [CONTRIBUTING.md](https://github.com/CodebuffAI/freebuff/blob/a51a3d5dce5c3d511cd3aa148e361085a700293d/CONTRIBUTING.md)

## 1. Selective parallelism, with a documented negative result

`agents/base3-fast.ts` describes a root that delegates deterministic context searches and reserves model workers for large, mechanical changes across independent files. Its comments report five 62-task runs in which split tasks were the worst-performing portion and no faster than base3. The same file says the fan-out harness is not used by current surfaces since October 30, while released older clients and an evaluation arm may retain it. The separate `base3-fast-free-deepseek-flash.ts` confirms that the current fast-mode definition calls `createBase3CliRoot` rather than the fan-out factory.

The source also describes exclusive file ownership, a root-written shared interface before work is split, final reconciliation, and withholding terminal/test execution from workers to avoid running the suite N times concurrently. These are design choices worth adopting. The cited benchmark directories are absent from the public tree, so the reported experiment is upstream commentary, not independently reproducible performance evidence.

Sources:

- [agents/base3-fast.ts](https://github.com/CodebuffAI/freebuff/blob/a51a3d5dce5c3d511cd3aa148e361085a700293d/agents/base3-fast.ts)
- [agents/base3-fast-free-deepseek-flash.ts](https://github.com/CodebuffAI/freebuff/blob/a51a3d5dce5c3d511cd3aa148e361085a700293d/agents/base3-fast-free-deepseek-flash.ts)

Litha application: keep model generation serial or narrowly bounded on the shared 8 GB GPU; overlap cheap file searches, retrieval and independent CPU checks. The existing resource planner already accounts for shared RAM/CPU pools and foreground priority. Add task-shape evidence and runtime measurements before widening model concurrency.

## 2. Deterministic search helpers are often better than extra model calls

`agents/file-explorer/code-searcher.ts` is a programmatic generator. It loops through supplied ripgrep queries and returns structured results; it does not yield a model step. Despite declaring a model field, this path does not require model inference to execute the searches. Individual queries run sequentially inside that helper; parallelism comes from independent helpers or the tool runtime, so do not claim this file parallelizes every query.

The file-picker is different: it spawns one file-lister, deduplicates returned paths, reads them, then invokes a model for a concise report. It advertises up to 12 files normally or 20 in max mode. That is an optional semantic discovery tool with additional model/context cost.

Sources:

- [agents/file-explorer/code-searcher.ts](https://github.com/CodebuffAI/freebuff/blob/a51a3d5dce5c3d511cd3aa148e361085a700293d/agents/file-explorer/code-searcher.ts)
- [agents/file-explorer/file-picker.ts](https://github.com/CodebuffAI/freebuff/blob/a51a3d5dce5c3d511cd3aa148e361085a700293d/agents/file-explorer/file-picker.ts)

Litha application: retrieve definitions, callers, tests and configuration together; deduplicate before adding text to the model. Reserve model-based file selection for cases in which deterministic discovery is insufficient. Search snippets should preserve file paths and line ranges for later exact reads.

## 3. Context windows and batching need model-specific measurement

`agents/lean-context.ts` suggests whole-file reads only for roughly 100-line files and 100–250-line windows around relevant code in larger files. It explicitly preserves task scope and verification while reducing context. Remaining todos and source outlines help resume after compaction. The code's claimed evaluation effect is again an upstream comment, not a Litha result.

`agents/base3.ts` includes batch-search/read/edit guidance, but enables its full batching configuration only for a tested model allowlist. Comments say the same prompt bought no time on another model and harmed score on a third. They also explain that replacing an ephemeral step reminder can change the request prefix and lose caching on some providers. The active code conditionally adds a step reminder on lanes believed to cache partial prefixes. This reinforces that a prompt tweak is not universally faster.

Sources:

- [agents/lean-context.ts](https://github.com/CodebuffAI/freebuff/blob/a51a3d5dce5c3d511cd3aa148e361085a700293d/agents/lean-context.ts)
- [agents/base3.ts](https://github.com/CodebuffAI/freebuff/blob/a51a3d5dce5c3d511cd3aa148e361085a700293d/agents/base3.ts)

Litha application: preserve `star/context_layout.py`'s stable system prefix and append-only layout. Add bounded, exact read windows instead of changing prompts globally. Measure first-token latency, total completion time, task success, prompt tokens and cache hits together. A smaller prompt that misses a needed caller can be a regression.

## 4. Current base3 compaction is asynchronous structured summarization

`conversation-summary.ts` prepares a summary with the agent's own model using its normal request prefix plus a trailing instruction. It starts at the smaller of 40,000 tokens or 20% of the context window, then after growth of the smaller of 30,000 tokens or 15%. The requested summary target is the smaller of 2,000 tokens or 10%. Full history remains in use while warm; the prepared summary is substituted on an idle return after five minutes or at the context limit. It rejects incomplete/unrecognized output, uses a message fingerprint anchor to check applicability, and retains live user messages verbatim through a caller-supplied keep predicate. Background summaries are held separately from history and have a persistence callback.

Source:

- [packages/agent-runtime/src/conversation-summary.ts](https://github.com/CodebuffAI/freebuff/blob/a51a3d5dce5c3d511cd3aa148e361085a700293d/packages/agent-runtime/src/conversation-summary.ts)

Litha application: prepared summaries can reduce interruption, but a local background model call competes with the foreground model. Use existing admission/idle mechanisms and never copy a cloud provider's five-minute timer into llama.cpp as a universal cache lifetime. Preserve exact user words and retain the original transcript locally.

## 5. Mechanical working-set preservation offers a useful smaller component

The older mechanical compaction support in `compaction-working-set.ts` carries the newest affordable read for each path, adds outlines/stubs for others, and marks reads stale after edits or agent delegation. Its default allocation is 40% of remaining history room with a 40,000-token cap; stubs have their own 3,000-token ceiling. These constants belong to its own workload, not Litha's much smaller local contexts. The module explicitly does not invalidate reads after arbitrary shell commands, so Litha should prefer a content digest or change journal if using this idea.

`compaction.ts` separately checks whether shrinking can create enough headroom: automatic compaction should leave context below 85% of its trigger threshold. Otherwise it avoids repeatedly compacting nearly the same summary and eventually reports a hard budget failure with history preserved.

Sources:

- [packages/agent-runtime/src/compaction-working-set.ts](https://github.com/CodebuffAI/freebuff/blob/a51a3d5dce5c3d511cd3aa148e361085a700293d/packages/agent-runtime/src/compaction-working-set.ts)
- [packages/agent-runtime/src/compaction.ts](https://github.com/CodebuffAI/freebuff/blob/a51a3d5dce5c3d511cd3aa148e361085a700293d/packages/agent-runtime/src/compaction.ts)

Litha application: exact read-only context slices with digest freshness and clear continuation offsets are low-risk, testable improvements. Prefer them before adding extra summarizer calls. Test stale reads, changed files, oversized fixed prompt, repeated compaction and original-user-text preservation.

## 6. Best-of-N exists, but its selector is not a test harness

`editor-multi-prompt.ts` spawns one implementor per strategy. Implementors return proposed tool calls and unified diffs. A selector receives the proposal diffs, chooses a candidate, and the coordinator converts only the selected proposal operations into real file edits. The selector has only `set_output`, no tools, and judges correctness, simplicity, maintainability and convention adherence. It therefore cannot execute candidate tests or independently inspect missing evidence. The available reviewer also has no tools and returns critique from inherited context.

Sources:

- [agents/editor/best-of-n/editor-multi-prompt.ts](https://github.com/CodebuffAI/freebuff/blob/a51a3d5dce5c3d511cd3aa148e361085a700293d/agents/editor/best-of-n/editor-multi-prompt.ts)
- [agents/editor/best-of-n/best-of-n-selector2.ts](https://github.com/CodebuffAI/freebuff/blob/a51a3d5dce5c3d511cd3aa148e361085a700293d/agents/editor/best-of-n/best-of-n-selector2.ts)
- [agents/reviewer/code-reviewer.ts](https://github.com/CodebuffAI/freebuff/blob/a51a3d5dce5c3d511cd3aa148e361085a700293d/agents/reviewer/code-reviewer.ts)

Litha application: preserve candidate isolation, but rank only after trusted syntax/type/runtime checks. Generate candidates sequentially when VRAM is constrained; independent CPU validation can still overlap. A model review is additional evidence, never the pass/fail authority. Existing Luau/Roblox and sealed-evaluation gates should remain the authority.

## 7. Hard concurrency caps live below the prompt

The spawn schema caps a call at six agents; the handler rechecks this before starting any work. Ordinary subagents share a live cap of 20 per root scope, including nested agents. Reservations happen before the first await and are released in `finally`. Per-agent failures are returned using `Promise.allSettled`, while costs from failed partial runs also count. Projects subagents have separate buckets and their own helper allowance, so 20 is not a universal whole-product global limit.

Sources:

- [common/src/tools/params/tool/spawn-agents.ts](https://github.com/CodebuffAI/freebuff/blob/a51a3d5dce5c3d511cd3aa148e361085a700293d/common/src/tools/params/tool/spawn-agents.ts)
- [packages/agent-runtime/src/tools/handlers/tool/spawn-agents.ts](https://github.com/CodebuffAI/freebuff/blob/a51a3d5dce5c3d511cd3aa148e361085a700293d/packages/agent-runtime/src/tools/handlers/tool/spawn-agents.ts)

Litha application: use measured local limits and retain a single physical-resource budget across roles. Existing `star/agent_runtime.py::run_plan` already executes bounded async task plans with dependency and ownership checks. Any further scheduler integration must enforce physical slot reservations in code and release after failure/cancellation. A dry-run admission plan alone is not evidence that those reservations are enforced by every execution path.

## 8. Preserve cache structure without treating it as authority

`run-agent-step.ts` allows children to inherit a parent's exact system prompt and advertised tools for prefix reuse; assignment text is appended. Tests assert matching inherited prompt content and require custom system prompts and inheritance to be mutually exclusive. Actual allowed tools still need host enforcement; cache-sharing configuration is not a permission grant. Reusing a prefix requires the same compatible model/tokenization/template and a server that supports the needed cache behavior.

Sources:

- [packages/agent-runtime/src/run-agent-step.ts](https://github.com/CodebuffAI/freebuff/blob/a51a3d5dce5c3d511cd3aa148e361085a700293d/packages/agent-runtime/src/run-agent-step.ts)
- [packages/agent-runtime/src/__tests__/prompt-caching-subagents.test.ts](https://github.com/CodebuffAI/freebuff/blob/a51a3d5dce5c3d511cd3aa148e361085a700293d/packages/agent-runtime/src/__tests__/prompt-caching-subagents.test.ts)

## 9. Agent definitions and skills have a real execution boundary

`docs/agents-and-tools.md` and `agent-publisher-trust.ts` explicitly state that `handleSteps` source strings are evaluated in-process without isolation. The publisher trust gate blocks untrusted remote executable templates; it does not sandbox, sign, or pin them. Local executable `.agents` imports and MCP configuration also need deliberate trust. Markdown skill content can still carry malicious instructions even when it is not executable itself.

The SDK project-confinement helper checks both lexical paths and resolved symlinks, including the nearest existing ancestor for a new path. It is opt-in. SDK `.env` read filtering is likewise not terminal-command or edit isolation. Litha should retain its stronger existing tool boundary and use pinned, data-only manifests when importing ideas.

Sources:

- [docs/agents-and-tools.md](https://github.com/CodebuffAI/freebuff/blob/a51a3d5dce5c3d511cd3aa148e361085a700293d/docs/agents-and-tools.md)
- [sdk/src/agent-publisher-trust.ts](https://github.com/CodebuffAI/freebuff/blob/a51a3d5dce5c3d511cd3aa148e361085a700293d/sdk/src/agent-publisher-trust.ts)
- [sdk/src/tools/project-confinement.ts](https://github.com/CodebuffAI/freebuff/blob/a51a3d5dce5c3d511cd3aa148e361085a700293d/sdk/src/tools/project-confinement.ts)
- [sdk/README.md](https://github.com/CodebuffAI/freebuff/blob/a51a3d5dce5c3d511cd3aa148e361085a700293d/sdk/README.md)

## 10. Refuse incomplete mutations

`truncated-write-guard.ts` rejects incomplete JSON for mutating tool calls rather than repairing and executing it. It also heuristically rejects a rewrite when an existing file has at least 30 lines, the replacement is less than 60% of its character length, and the replacement introduces unclosed brackets while the old file balances. The bracket counter does not understand syntax, comments or strings, so it is a useful warning/guard, not proof of correctness. Prefer targeted edits, strict schema validation and syntax checks; do not claim bracket balance validates a program.

Source:

- [packages/agent-runtime/src/util/truncated-write-guard.ts](https://github.com/CodebuffAI/freebuff/blob/a51a3d5dce5c3d511cd3aa148e361085a700293d/packages/agent-runtime/src/util/truncated-write-guard.ts)

## 11. Language support and deployment choices

The Tree-sitter language table includes Rust, Python, TypeScript/TSX, JavaScript/JSX, Java, C#, C++ headers, Ruby and Go. Lua/Luau are absent from the inspected table. A separate Luau grammar/LSP/API pipeline remains necessary for Litha. Parsing a Rust file also does not grant an agent Rust reasoning expertise or accelerate its model inference.

The official SDK documentation describes a Codebuff API key, `previousRun`, custom agents/tools and event callbacks. Freebuff's consumer no-key/free-access headline must not be extended into a promise of unrestricted free SDK inference or fully local operation. A Node/Bun sidecar is an optional integration approach if the owner wants that service later; it is unnecessary for transferring useful architecture into Python.

Sources:

- [packages/code-map/src/languages.ts](https://github.com/CodebuffAI/freebuff/blob/a51a3d5dce5c3d511cd3aa148e361085a700293d/packages/code-map/src/languages.ts)
- [www.codebuff.com/docs/advanced/sdk](https://www.codebuff.com/docs/advanced/sdk)

## 12. Privacy and license facts

The inspected README states that text advertising supports included hosted models and that availability depends on tier/capacity. Its privacy notes describe per-model/feature AI-training notices. The linked privacy page is dated October 18 but explicitly effective November 12, 2026: as of this report it is a published forthcoming policy. It describes advertising profiling and data sharing/licensing/sale for models/features identified for training, with separate rules for repository evaluation. Do not generalize this into “every connected repository is sold” or silently send Litha code to the hosted service.

The source is Apache-2.0 and carries a Codebuff NOTICE. If any upstream source is copied or modified, retain relevant license and attribution and mark modifications. Original reimplementations should still record their research provenance. Licensing the code does not provide hosted access, model weights or trademark rights.

Sources:

- [README.md](https://github.com/CodebuffAI/freebuff/blob/a51a3d5dce5c3d511cd3aa148e361085a700293d/README.md)
- [freebuff.com/privacy-policy](https://freebuff.com/privacy-policy)
- [LICENSE](https://github.com/CodebuffAI/freebuff/blob/a51a3d5dce5c3d511cd3aa148e361085a700293d/LICENSE)
- [NOTICE](https://github.com/CodebuffAI/freebuff/blob/a51a3d5dce5c3d511cd3aa148e361085a700293d/NOTICE)

## Mapping the findings onto Litha

These modules already exist at the inspected baseline unless the status explicitly says this draft. Repository links are relative to this document.

| Concern | Existing Litha implementation | Decision and status |
| --- | --- | --- |
| Deterministic code retrieval | [`star/code_navigation.py`](../../star/code_navigation.py), [`star/workspace.py`](../../star/workspace.py) | Extend the scoped scanner with [`star/code_search_batch.py`](../../star/code_search_batch.py) in this draft; reuse its language set, path checks and hit limits. |
| Compact repository context | [`star/repo_map.py`](../../star/repo_map.py) | Existing bounded identifier graph is a navigation aid, not a language-server dependency proof. This draft adds opt-in reuse of the existing source/declaration cache. |
| Prompt prefix stability | [`star/context_layout.py`](../../star/context_layout.py), [`star/agent.py`](../../star/agent.py) | Preserve current stable system prefix, append-only history layout and block trimming. New batch tool schemas appear only with explicit activation. |
| Compaction and original history | [`star/memory.py`](../../star/memory.py), [`star/agent.py`](../../star/agent.py) | Existing checkpointing has bounded model work and describes summaries as lossy reference. Further working-set and prepared-summary changes remain future work. |
| Task dependencies and resources | [`star/orchestration.py`](../../star/orchestration.py), [`star/agent_resource_planner.py`](../../star/agent_resource_planner.py), [`star/resource_planner_service.py`](../../star/resource_planner_service.py) | Reuse dependency/ownership planning, shared physical resources and host leases. The generic planner is not proof of a running autonomous coding-worker scheduler. No new scheduler is added here. |
| Existing plan execution and replay | [`star/agent_runtime.py`](../../star/agent_runtime.py), [`star/mission_checkpoint.py`](../../star/mission_checkpoint.py) | Bounded async execution already exists. Revision-bound replay refuses automatic reuse of write-capable tasks. No duplicate executor or new replay policy is added. |
| Existing candidate verification | [`star/best_of_n.py`](../../star/best_of_n.py), [`star/candidate_code_team.py`](../../star/candidate_code_team.py) | Candidate sampling and real checks already exist; the research recommends improving evidence/compute efficiency, not substituting a model's vote for those checks. |
| Verified candidate selection | [`star/verify_ladder.py`](../../star/verify_ladder.py), [`star/eval_gate.py`](../../star/eval_gate.py), [`star/sealed_eval.py`](../../star/sealed_eval.py) | Keep executable checks and protected grading authoritative. No model-only selector or grading-policy change is introduced. |
| Scoped execution | [`star/policy.py`](../../star/policy.py), [`star/workspace.py`](../../star/workspace.py), [`star/eval_sandbox.py`](../../star/eval_sandbox.py) | Preserve existing scopes; this change does not install executable agent templates or grant shell access. |
| Knowledge and learning | [`star/knowledge.py`](../../star/knowledge.py), [`star/lessons.py`](../../star/lessons.py) | Research remains attributed reference material. Agent observations are not automatically promoted into approved facts, permissions or model weights. |

## Related primary-source research

### Aider: budget the map and keep it fresh

Aider's documentation describes ranking repository symbols and relationships within a token budget, then using that map to select full file reads. Its caching documentation groups stable system instructions, read-only files, the map and editable files to encourage cache reuse. This reinforces Litha's existing repository map and context layout rather than requiring another indexing framework.

Inspection of `aider/repomap.py` at `5dc9490bb35f9729ef2c95d00a19ccd30c26339c` also reveals freshness tradeoffs: declaration/render caches use modification times, while whole-map reuse depends on file sets, budget, mentions and refresh mode. Automatic mode can reuse a costly previous map. Consequently, an old map is useful navigation evidence but not proof of current source. Litha's draft reuses only the existing validated source/declaration entries and rebuilds map relationships on each call.

Sources: [repository-map documentation](https://aider.chat/docs/repomap.html), [prompt-caching documentation](https://aider.chat/docs/usage/caching.html), [pinned implementation](https://github.com/Aider-AI/aider/blob/5dc9490bb35f9729ef2c95d00a19ccd30c26339c/aider/repomap.py).

### OpenHands: condense complete interactions and require progress

The inspected OpenHands SDK condenser uses the strictest applicable configured/model input limit, protects initial context including the system message, selects forgetting ranges on permitted manipulation boundaries and rejects reductions that make insufficient progress. Its event-property modules separately protect action/result matching and complete tool loops. These are relevant when Litha later changes checkpointing: deleting arbitrary messages can orphan a tool result or break a provider's signed reasoning/tool sequence.

This draft does not install OpenHands or replace Litha's compaction. A later implementation should test complete call/result preservation, current-user-text retention, archived-source retrieval, and useful recovered room under a deliberately small context budget.

Sources at `98de8bf3aca7e59eedebd7a97c423986ea1c4c05`: [condenser](https://github.com/OpenHands/software-agent-sdk/blob/98de8bf3aca7e59eedebd7a97c423986ea1c4c05/openhands-sdk/openhands/sdk/context/condenser/llm_summarizing_condenser.py), [tool-call matching](https://github.com/OpenHands/software-agent-sdk/blob/98de8bf3aca7e59eedebd7a97c423986ea1c4c05/openhands-sdk/openhands/sdk/context/view/properties/tool_call_matching.py), [tool-loop atomicity](https://github.com/OpenHands/software-agent-sdk/blob/98de8bf3aca7e59eedebd7a97c423986ea1c4c05/openhands-sdk/openhands/sdk/context/view/properties/tool_loop_atomicity.py).

### llama.cpp: measure reused tokens and slot contention

The inspected server documentation explains that `cache_prompt` can reuse a previous request's KV prefix and evaluate only its differing suffix. Its response timing fields include cached prompt tokens, newly processed prompt tokens, prompt-processing time and generated-token counts. Parallel slots also have context-memory implications. This supplies measurements for later Litha experiments: compare cached/new prompt work and foreground latency, not just CPU helper time.

The pinned upstream revision is newer than some installed engines. Validate options and response fields against the actual installed llama.cpp build before changing configuration. This draft changes neither the model server nor its GPU/slot allocation.

Source: [server documentation at a91eab67d8389d979d29fdf6633b2edd0718eb4b](https://github.com/ggml-org/llama.cpp/blob/a91eab67d8389d979d29fdf6633b2edd0718eb4b/tools/server/README.md).

### Anthropic: multi-agent breadth has a real resource price

Anthropic's June 2025 engineering report describes benefits on independent, breadth-heavy research, but reports roughly 15 times ordinary-chat token use for its multi-agent system and notes that tightly coupled coding offers fewer independently parallel tasks. These are observations from its own system, not a universal overhead factor or a Litha benchmark. Together with Freebuff's later source commentary, the evidence favors task-specific admission and deterministic retrieval before broad model fan-out.

Source: [How we built our multi-agent research system](https://www.anthropic.com/research/multi-agent-research-system).

## Further adoption roadmap

| Priority | Proposed change | Existing integration point | Evidence required before enabling |
| --- | --- | --- | --- |
| 1 | Evaluate the new batched retrieval and shared map cache | `code_search_batch`, `code_navigation`, `repo_map`, `Workspace.call` | Equivalent useful source evidence, bounded Unicode output, deletion/change invalidation, scoped paths, source-cache-disabled/warm timings and representative task traces. |
| 2 | Exact source windows and fresh working-set recovery | `workspace_read`, `context_layout`, `agent` | Correct offsets/line ranges, clear incompleteness, unchanged original files, freshness after edits and robust behavior after compaction. |
| 3 | Prevent compaction loops and preserve atomic tool exchanges | `memory`, `agent` | Meaningful reclaimed context, bounded summarizer work, preserved request/IDs and an explicit failure when fixed context cannot fit. |
| 4 | Choose parallel work by task shape and measured capacity | `orchestration`, `agent_resource_planner`, host leases | No overlapping ownership, no multiplied suite execution, clean cancellation, foreground priority and whole-task quality/latency comparison. |
| 5 | Prepared summaries during admitted idle work | `memory`, resource-planner service | Foreground latency remains acceptable; stale/failed summaries are rejected; exact archived data remains retrievable. |
| 6 | Candidate proposals with executable grading | `verify_ladder`, candidate pool, sealed evaluation | Candidates isolated, original solution preserved, trusted tests run, no grading-fixture modification and useful gain per unit compute. |
| 7 | Optional provider adapter only for a concrete need | Existing provider boundary | Explicit data-use choice, request budgets, failure fallback and no requirement for hosted access in local workflows. |

Priorities 2–7 are proposals, not delivered features of this draft. No full Rust rewrite, hosted Freebuff integration, autonomous multiagent scheduler, new trained weights or default setting promotion is claimed.

For all claims, distinguish implementation correctness from actual model quality/speed. Offline tests can prove bounds, state transitions, exact reads and cancellation behavior. They cannot establish faster inference, stronger intelligence, a working Windows package or successful Roblox Studio operation. Those need measurements on the target runtime.

## Measured implementation results

The reproducible driver is [`benchmarks/freebuff_context.py`](../../benchmarks/freebuff_context.py).
The [raw measurements](litha-freebuff-benchmarks-20261031.json) include every timing sample,
environment/dependency versions, result parity, read counts and SHA-256 fingerprints of the measured source.
Measurements used Python 3.12 on isolated Linux x86_64, with eight sparse discovery queries alternating
between text and Python symbols. Both paths called the actual `Workspace.call` dispatcher, including schema
validation. Result comparisons ran outside the timing interval. The measured order alternated; warm runs
populated the shared source/declaration cache first. No model or network request was part of a measurement.

| Workload | Existing separate calls, median | Batched calls, median | Ratio |
| --- | ---: | ---: | ---: |
| 60 files, source cache disabled, 8 queries | 50.3213 ms | 9.2465 ms | 5.44× |
| 300 files, source cache disabled, 8 queries | 206.7108 ms | 30.5943 ms | 6.76× |
| 60 files, warm source cache, 8 queries | 43.8095 ms | 7.7073 ms | 5.68× |
| 300 files, warm source cache, 8 queries | 177.2104 ms | 26.2260 ms | 6.76× |

| Map workload | Existing uncached map, median | Shared warm-cache map, median | Ratio |
| --- | ---: | ---: | ---: |
| 60 files | 27.5624 ms | 13.7512 ms | 2.00× |
| 300 files | 129.9423 ms | 66.6691 ms | 1.95× |

All query match lists and map outputs were equal in these fixtures. The 60-file workload used seven timing
samples per condition; the 300-file workload used nine. With the application cache disabled, source reads
fell from 480 to 60 and from 2,400 to 300 respectively. This confirms one read per file instead of one read
per file per query. It does not mean eight fewer model reasoning steps are guaranteed: the model must choose
the batch tool, and adaptive questions that depend on earlier results still need later calls.

These are synthetic navigation-stage timings. “Uncached” means the application source cache is disabled;
filesystem pages were already warm from fixture creation and parity checks. They are not cold-disk results.
Broad/noisy queries, Unicode-heavy output, different project languages, smaller batches, storage devices,
larger trees and model behavior can change the ratio. A 176 ms saving in this 300-file uncached search fixture
is not evidence of a 6.76× whole-agent speedup. No model-quality, first-token, memory-RSS, GPU or Windows
performance gain is claimed.

Reproduce from a source checkout with the project's test dependencies installed:

```bash
python -m benchmarks.freebuff_context --files 60 --repeats 7
python -m benchmarks.freebuff_context --files 300 --repeats 9
```

### Validation and review

The consolidated focused suite completed with **229 passed, 0 failed, 0 skipped**. It covers batch search,
existing navigation/cache/map behavior, the actual agent catalogue and dispatcher, flag revocation, workspace
path rules, editing and syntax feedback, incremental repair, agent answer statistics and Windows package-data
declarations. Python source compilation and Ruff on all changed Python files passed. The pinned Pyright
checker reported zero errors for `code_search_batch.py`, `repo_map.py` and `workspace.py`.

Independent review exercised 400 additional uncapped batch/single-query comparisons and checked output
bounds. It found a flag-revocation race between catalogue selection and dispatch; static schema lookup and
a second flag check fixed it, with a regression test. The new same-sized-edit test explicitly advances file
mtime to avoid an accidental Windows clock-granularity dependency.

Two broader limits remain visible. The large existing `agent.execute` function reports a Pyright complexity
diagnostic; this change does not refactor it or claim a clean whole-repository type check. The additional
desktop catalogue test `test_the_acceptance_prompt_is_offered_the_agent_skills_catalogue` timed out in
`asyncio` default-executor shutdown in this environment, on both the unchanged baseline and this candidate.
The baseline reproduction used a clean detached checkout and a 25-second timeout (exit 124). That test is
not counted as passed. The new direct agent-loop integration tests and the existing static catalogue test
did pass. No test fixture, stored evaluation outcome or default gate was changed to hide a failure.

### Activation and rollback after review

The change is a draft for `star/next`, with all experimental switches off by default. It has not been merged
or deployed by this work. For an explicitly enabled source-checkout pilot, set `STAR_CODE_SEARCH_BATCH=on`
before starting Litha to expose the batch tool. To test cached maps, set both `STAR_CODE_SEARCH_CACHE=on`
and `STAR_CODE_MAP_CACHE=on`. The batch switch does not require either cache switch.

Unset `STAR_CODE_SEARCH_BATCH` to remove the extra tool and refuse later batch dispatch. Unset
`STAR_CODE_MAP_CACHE` to restore the original uncached map path while preserving any independently chosen
source-search cache setting. Process restart or `code_navigation.clear_source_cache()` clears resident cache
entries. No database migration, hosted credential, model download or source rewrite is needed. A live pilot
still needs representative task success, first-token/whole-task latency and target Windows acceptance before
any default promotion.
