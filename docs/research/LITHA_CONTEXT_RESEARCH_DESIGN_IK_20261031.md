# Litha: context, research, design and motion engineering

## Research and implementation review - October 31, 2026

Prepared for Litha / STAR. This report investigates Repomix, Claude and Claude Code, Crawl4AI, ccusage, Caveman, awesome-design-md, awesome-ai-tools, and inverse kinematics. It combines current primary documentation, selected implementation files, original IK literature, and inspection of Litha's actual repository. Recommendations are explicitly distinguished from tested code and measured outcomes.

### Executive decision

The strongest combined upgrade is a disciplined creation loop: collect trustworthy evidence, assemble only the context needed for the task, choose a capable worker, execute the work, measure the actual result, repair concrete defects, and retain the verified example. The tools in this request contribute different parts of that loop. Installing all of them would not itself establish an improvement.

For Litha's local-first architecture, prioritize reusable context and verified outcomes. Keep interactive model inference responsive while background acquisition, indexing, asset validation and motion analysis use bounded CPU/RAM capacity. Engine-native animation should run the character every frame; the language model should author and inspect the system around it.

| Area | Recommended decision | Expected mechanism | Evidence required before activation |
|---|---|---|---|
| Repomix | Pilot selective maps and exact-source recovery | Less repeated source exploration | Equal or better repair success with lower accepted-task latency/cost |
| Claude | Optional specialist worker through supported interfaces | Escalation for difficult reasoning or review | Better outcomes including provider cost, latency and transfer boundaries |
| Crawl4AI | Isolated, bounded documentation acquisition worker | Fewer manual browsing steps and model extraction calls | Correct retained facts, fresh/stale labeling, bounded resources |
| ccusage | Read-only usage import plus Litha's own task ledger | Identify waste, retries and cache misses | Reconciled events, honest missing prices and no double-counting |
| Caveman | Study recoverable compression; test terse status separately | Less repetitive output and tool-context volume | Semantic fidelity and whole-task savings against a concise baseline |
| awesome-design-md | Curated references for existing design tools | Consistent tokens/states and fewer design retries | Rendered behavior and native-platform checks |
| awesome-ai-tools | Unverified discovery leads | Find a missing capability | Current primary-source qualification of each selected tool |
| Inverse kinematics | Native solvers plus trace and visual validation | Correct grips, grounded contacts and stable motion | Real rig/trajectory measurements and motion review |

These are recommendations, not a benchmark ranking. No result in this report establishes that Litha has surpassed another general-purpose AI.

## 1. Grounding in the existing Litha code

The inspected repository is `oncoursemail/Star-AI-Project`. The inspected development revision on `star/next` is `a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f`. The repository metadata reports `main` as the default branch; this work follows the owner's established development base, `star/next`, and uses a separate draft branch. No source was pushed to the separate `oncoursemail/Star-AI` distribution repository.

Several important capabilities already have source-level foundations. Their presence is not proof of deployment or native execution:

| Existing component | What was observed | Consequence for this research |
|---|---|---|
| `server/mesh/docs/service.py` | Compact docs blocks, exact API entry endpoint, dense retrieval switches; defaults include a 500-token approximate budget and zero guide passages in automatic blocks | Extend precise retrieval rather than prepend every downloaded guide |
| `server/mesh/docs/index.py` | SQLite queries, exact API names, BM25/dense search and a character-based token estimate | A future admission layer should use the selected model's tokenizer |
| `star/context_layout.py` | Explicit reference-data boundaries and conversation assembly | Preserve separation between external evidence and owner instructions |
| `star/repo_map.py` | Existing repository map | Avoid another competing map cache |
| `star/design_md.py` | Substantial parser, token validation, contrast logic, rendering and workspace I/O | Improve evidence and coverage within this design system |
| `star/resource_atlas.py` | Discovery adapters and a local candidate store | Add qualified source records, not another tool directory service |
| `star/scene_integrity.py` | Geometric scene/shell diagnostics | Extend with motion observations where static checks are insufficient |
| `star/animation_regression.py` | Authored Euler-value sampling; explicitly excludes IK, physics, contact and rendered frames | Add an independent trace diagnostic instead of relabeling existing checks as native IK validation |

Pinned examples: [docs service](https://github.com/oncoursemail/Star-AI-Project/blob/a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f/server/mesh/docs/service.py), [docs index](https://github.com/oncoursemail/Star-AI-Project/blob/a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f/server/mesh/docs/index.py), [animation diagnostics](https://github.com/oncoursemail/Star-AI-Project/blob/a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f/star/animation_regression.py), [design tools](https://github.com/oncoursemail/Star-AI-Project/blob/a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f/star/design_md.py).

Open work was checked before choosing the implementation scope. [Draft PR #854](https://github.com/oncoursemail/Star-AI-Project/pull/854) covers batched context search and shared map caching; [draft PR #855](https://github.com/oncoursemail/Star-AI-Project/pull/855) covers UI evidence and contrast diagnostics. Their changed-file lists were inspected. This work does not duplicate those changes or treat unmerged proposals as deployed features.

## 2. Claude: separate the model, coding product and agent runtime

The user's term "Claude" can refer to the model/API, Claude Code, or the Claude Agent SDK. All three matter here. The SDK supplies an agent loop and tooling; Claude Code exposes workflow features; the model supplies reasoning. None is a downloadable local replacement for Litha's own model weights. The official SDK documentation also distinguishes supported API-key integration from using a consumer claude.ai login/rate limit for a third-party product. [SDK overview](https://code.claude.com/docs/en/agent-sdk/overview).

### Recommended relationship with Litha

Keep Litha's task state, source snapshots, verification results, learned examples and rollback history in her local system. Offer Claude as one optional worker behind a provider-neutral job contract. A worker can propose a patch, critique a design, inspect an error trace or compare repair strategies. Litha should validate the returned artifact through the same independent checks used for local workers. A stronger worker's confident prose should not bypass those checks.

A useful worker request specifies the goal, exact snapshot, selected evidence, writable scope, output schema, time/token/cost allowance and acceptance criteria. The result includes artifacts, executed checks, observed failures, uncertainty and source references. In a multi-worker task, assign ownership of files and explicit dependencies before execution. Parallelize independent research or candidate generation; serialize competing edits and integration.

This is an architectural proposal. No Claude worker was installed, authenticated, invoked from Litha or benchmarked in this task.

### Context isolation and skills

Official Claude Code documentation describes isolated subagent contexts and task-specific skills that load when relevant. These are useful patterns for Litha because one research worker can read many sources without filling the main coding context with every page. The coordinator still needs a self-contained handoff: objective, constraints, exact evidence locations, conclusions and unresolved questions. References omitted from a handoff may have to be fetched again. [Subagents](https://code.claude.com/docs/en/sub-agents), [skills](https://code.claude.com/docs/en/skills).

For Litha, use small task-relevant reference packs: Roblox API facts for a Roblox repair; a rig contract for a motion task; a design specification for a UI task. Keep enduring project rules short. Avoid loading all skill bodies in every turn. A skill document describes a procedure; an executable validator checks whether the procedure succeeded. Those roles should remain distinct.

Hooks can make selected lifecycle actions deterministic, such as recording a tool result or invoking a local formatter. Their behavior depends on event and configuration, and they execute real operations. Review hooks as code, scope their inputs, and do not import arbitrary repository hooks as trusted instructions. [Hooks reference](https://code.claude.com/docs/en/hooks).

### Four different efficiency techniques

Anthropic distinguishes tool discovery, programmatic tool calls, prefix caching and context editing. Discovery reduces upfront tool definitions; batching reduces repeated tool round trips; prefix caching reduces repeated-prefix processing/billing; context editing removes obsolete history. These techniques solve different costs and should be measured independently. [Tool-context guidance](https://platform.claude.com/docs/en/agents-and-tools/tool-use/manage-tool-context).

Prompt caching requires identical eligible prefix content. It does not compress the logical context window or accelerate output-token generation itself. Put stable tool definitions and stable project context before changing task data; keep timestamps and volatile status out of the reusable prefix. Record cache reads and writes rather than assuming a cache hit occurred. [Prompt-caching documentation](https://platform.claude.com/docs/en/build-with-claude/prompt-caching).

The same general design idea can inform local prefix/KV reuse, but an API cache and a local inference cache are different implementations with different capacities and invalidation rules. Do not report an Anthropic cache saving as a measured llama.cpp or Qwen speedup.

## 3. A practical learning architecture

This section is a proposed architecture derived from the research; it is not an existing deployed subsystem.

### Evidence records, not undifferentiated text

Keep three layers. First, immutable source snapshots retain original code/docs and provenance. Second, extracted facts retain exact source spans, engine/version and confidence. Third, verified examples retain an input, constraints, implementation, execution evidence and failure boundaries. A summary may be regenerated; original evidence must remain recoverable. A source update should invalidate affected facts/examples for rechecking without silently rewriting history.

Represent a useful motion lesson as more than "use IK": engine version, rig/rest-pose identity, units, joint limits, target trajectory, solver settings, contact policy, evaluated trace, rendered clip and known failure cases. Represent a UI lesson similarly: component contract, state coverage, viewport/input modes, approved reference, measured defects, repair and verification.

This structure turns information into reusable task knowledge. It does not modify model weights by itself. Fine-tuning is a separate experiment requiring suitable data rights, held-out evaluation, reproducibility, and a demonstrated benefit over retrieval or procedural reuse.

### Retrieve by task and uncertainty

Start with the smallest useful evidence set, then expand when a concrete uncertainty appears. Exact API identifiers should retrieve exact contracts. A stale or conflicting claim should trigger verification. A failed test should retrieve related failure examples and the relevant implementation, not an entire unrelated guide. An evidence pack should state omissions, representation and source identity so the model knows when it is looking at an outline.

Original design proposal: rank candidate evidence by estimated relevance, reliability, freshness, uncertainty reduced, and token cost. This is a heuristic to test, not a proven formula. Preserve mandatory contracts even when their token efficiency looks poor. A single negation or type annotation can matter more than several pages of broad explanation.

### Learn from failures without training to the grader

Keep failure cases with their original observations. Label why a change failed: stale API, wrong coordinate system, missing source, malformed tool call, unsupported rig, contrast error or unverified assumption. A later successful repair can be linked to the failure. Separate development examples from held-out acceptance cases, and keep independent grader ownership. A system that edits its own pass criteria has not demonstrated improvement.

Candidate generation should adapt to uncertainty and resources. Start with one candidate for straightforward repairs; use several independently varied candidates for ambiguous or high-value tasks. Stop when evidence is sufficient. Parallel candidates consume memory and can queue behind the same local model, so an unconditional eight-worker policy may increase latency. Compare accepted-result time and quality at equal resource budgets.

## 4. Measuring speed and quality together

Use an end-to-end measurement boundary from accepted user task to verified artifact. Include acquisition, context preparation, queueing, prompt evaluation, decoding, tool execution, retries and validation. Record first-token delay separately from completion time. A faster answer that requires two extra repair rounds can be a slower task.

| Measure | Why it matters | Interpretation rule |
|---|---|---|
| First-pass acceptance | Shows whether the initial solution is useful | Keep task difficulty and checks fixed |
| Accepted tasks per wall-clock hour | Reflects practical throughput | Include failed attempts and queue time |
| Total cost per verified task | Connects ccusage/provider data to outcomes | Include cache writes, retries and all workers |
| End-to-end p50/p95 latency | Distinguishes typical speed from slow tails | Separate interactive/background and warm/cold cache |
| Peak RAM/VRAM and allocation/raycast counts | Identifies resource bottlenecks | Measure actual target hardware; do not infer from language choice |
| Evidence coverage and freshness | Detects unsupported confident answers | Missing observations remain unmeasured |
| Grip/contact maximum error | Reveals brief visible motion failures | Keep maximum and time-series evidence, not only averages |
| Visual/state coverage | Detects UI failures hidden by one screenshot | Exercise loading, error, empty, long-content and input modes |

For an A/B study, pin model, task set, source revision, runtime parameters and validation conditions. Randomize run order; isolate warm/cold caches; repeat stochastic runs. Report uncertainty rather than declaring victory from a single lucky sample. Use a predefined quality floor and then compare speed/cost among variants that satisfy it. A tolerance such as a 5% slowdown or a 1% contact error is a project decision to calibrate, not a universal industry standard.

### Where Rust belongs

Use profiling to choose Rust work. Good candidates include large batches of geometry checks, retrieval/ranking hot loops, parsing, trace processing and a shared custom animation kernel. Keep inference in its optimized backend and engine-native IK in its engine. Batch crossings of Python/native boundaries; avoid a new process per small vector or joint. Account for initialization, serialization and memory copies when measuring improvements. A faster kernel is valuable only when it improves the user-visible task or a real resource constraint.

## 5. Implementation delivered with this research

The accompanying draft adds an original, standard-library-only `star/ik_trace_quality.py`. It fills the specific observation gap identified in the existing animation diagnostics. It reads a bounded supplied JSON trace and produces measurements; it does not generate animation or claim that a supplied file came from a real engine.

Its API and CLI calculate position residual relative to rig scale, quaternion orientation error, displacement, timestamp-derived speed and acceleration, angular motion, support-local contact residual, contact drift and slip speed. Equivalent quaternions q and -q represent the same rotation. Contact measurements reset on gaps, release or a support-frame change. Missing optional channels remain null with observation counts rather than becoming perfect zero scores.

Inputs reject unsupported fields, malformed vectors, non-finite values, booleans masquerading as numbers, invalid unit quaternions, duplicate chain names, non-increasing timestamps, changing anchors within an uninterrupted contact span and excessive trace sizes. The CLI also rejects duplicate JSON keys and non-finite JSON constants. It does not add a provider, crawler, cloud transfer, network permission, model, automatic skill or promotion rule.

The schema, example and exact validation results are documented in the accompanying IK trace guide and validation record. Existing tests, stored evaluation fixtures and activation defaults are unchanged. The proposed acceptance cases in the research package are plans, not reported passing tests. A real Studio/Blender capture adapter and native Windows acceptance remain future integration work.

### Recommended next changes, in order

1. Review the diagnostic and capture a real stationary grip, planted foot and moving-platform trace in a private Studio test scene. Confirm coordinate frames and observed values before adding thresholds.
2. Extend existing context infrastructure with exact target-model budget admission and full-source recovery. Reuse the map/search work in PR #854.
3. Reconcile provider/imported usage with task/attempt results. Keep unknown prices visible; enforce concurrency reservations in the orchestrator rather than retrospectively through a report.
4. Pilot Crawl4AI on one approved documentation family, with pinned runtime, bounded concurrency and explicit freshness behavior. Test the OFF state independently from cache settings.
5. Add a small number of reviewed design principles to existing DESIGN.md tooling. Reuse PR #855's evidence work and validate native Roblox interfaces in Studio.
6. Add motion challenges, unseen target paths and rig variations. Store passing measured examples and labeled counterexamples; retain independent acceptance checks.

Each change should be evaluated independently before combining them. GitHub remains a review/export channel; the source snapshots, execution history and learning artifacts can live in Litha's local Forge system.

## Reading the detailed research chapters

The following chapters provide source-level evidence, exact caveats, solver choices, operational recipes, source snapshots and proposed validation cases. Source inspection and literature recommendations should not be confused with target-machine measurements. The final appendix records what was actually executed in this task.

# Detailed chapter A - Repomix, ccusage and Caveman

Research date: October 31, 2026, America/Chicago. All recommendations below are proposals, not claims of installation or measured Litha improvements. Public source code was read through the GitHub connector. No fetched code was installed or executed.

## 1. Snapshot and highest-value findings

| Project | Source snapshot inspected | Package metadata inspected | License evidence |
|---|---|---|---|
| Repomix | `yamadashy/repomix` at `2050e90141b01a1fa40bb278f170057ff67eb157`; commit 2026-10-31 16:34 UTC | root package version 1.18.1; Node >=22 | MIT in package and repository |
| ccusage | canonical repository is now `ccusage/ccusage`; old `ryoppippi/ccusage` redirects; `1c1bb1e1bfe327dad6ef056e725f8d4a9cfaa709`; 2026-11-01 01:20 UTC, still October 31 in Chicago | `apps/ccusage/package.json` version 20.0.46 | MIT, root LICENSE |
| Caveman | `JuliusBrussee/caveman` at `9b68f7ed12b05e7efaff18e65c5a3fc2849fd0a4`; 2026-10-25 07:57 UTC | installer package 4.0.1; depends on `@caveman-ai/cli` ^4.0.0 | root/engine/proxy Apache-2.0; other files include MIT licenses; component audit required when copying |

The three solve different problems. Repomix packages selected source context; ccusage reports recorded usage; Caveman now includes several compression, routing, and integration components. None alone trains Litha or establishes an intelligence gain. Their useful shared principle is to spend computation on evidence that changes an answer, then measure success per unit of cost.

Two findings matter especially for Roblox work:

1. **Repomix's inspected AST-compression language registry contains Python, TypeScript, Rust, and other languages, but no Lua or Luau.** Unsupported files fall back to uncompressed text. It can still pack Luau source; it cannot be advertised as Luau AST compression at this snapshot.
2. **Repomix's secret scanning does not sanitize included Git diffs/logs.** `validateFileSafety.ts` filters suspicious ordinary files, but warns and continues to include suspicious diffs/logs. Keep those sections disabled in exported context, or independently scan and block the final artifact.

Primary code: [language registry](https://github.com/yamadashy/repomix/blob/2050e90141b01a1fa40bb278f170057ff67eb157/src/core/treeSitter/languageConfig.ts), [parser fallback](https://github.com/yamadashy/repomix/blob/2050e90141b01a1fa40bb278f170057ff67eb157/src/core/treeSitter/parseFile.ts), [safety filtering](https://github.com/yamadashy/repomix/blob/2050e90141b01a1fa40bb278f170057ff67eb157/src/core/security/validateFileSafety.ts).

## 2. Repomix: adopt as a context builder, with exact-source recovery

### What is verified

Repomix combines source files, structure, and optional metadata into one output. Its experimental Tree-sitter compression retains structural information while omitting implementation logic. That makes an outline useful for selecting files, but insufficient to verify a bug fix. [Official compression documentation](https://repomix.com/guide/code-compress).

The current config schema adds useful controls beyond a simple whole-repository dump: `output.patterns` selects full text, compressed text, or directory-only entries by ordered globs; first matching rule wins. `output.tokenBudget` has no default limit. The default counting encoding is `o200k_base`. These facts were confirmed in [configSchema.ts](https://github.com/yamadashy/repomix/blob/2050e90141b01a1fa40bb278f170057ff67eb157/src/config/configSchema.ts), not inferred from a screenshot.

The budget flag fails with a nonzero exit status **after output is generated**. A caller must check process success and its own target-model count before publishing or sending the file. Splitting output by byte size does not make all chunks collectively fit one context window. [CLI reference](https://repomix.com/guide/command-line-options); [budget tests](https://github.com/yamadashy/repomix/blob/2050e90141b01a1fa40bb278f170057ff67eb157/tests/cli/actions/defaultAction.tokenBudget.test.ts).

Configuration is also an execution boundary. JS/TS configuration and file processors can run commands; instruction/include paths can reference outside a repository. Remote configs are untrusted by default; keep that behavior. For downloaded source, pass an explicit reviewed data-only config and avoid enabling arbitrary processors. Secretlint is useful defense, not proof that an export contains no private data. [Security documentation](https://repomix.com/guide/security).

### Litha design recommendation

Use three separately addressable context layers:

- **Stable project map:** repository/Forge snapshot, folder roles, exported names, relevant architecture and exact source references. Regenerate when covered files change, not every model turn.
- **Task evidence:** full source of likely edit targets, callers, tests, type contracts, relevant docs, and failures. Keep implementation bytes intact for patching.
- **Optional expansion:** retrieve source windows by path + content hash when the model needs more detail. Fetch full original files before a semantic edit or final review.

Do not treat the compressed map as authoritative code. Do not globally strip comments: comments can carry invariants, ownership, licensing, coordinate conventions, or warnings needed for a correct change. For Luau, use full relevant scripts initially. A separate Luau-aware symbol index is a better future extension than regex deletion of function bodies.

Content identity should include repository or local Forge snapshot, path, SHA-256, representation (`full`, `outline`, `path-only`), tokenizer identity, packer/config version, and whether source is stale. A pack manifest can be stored outside the model-visible prefix; volatile timestamps embedded in the prefix can defeat reuse. Disable Git change-frequency sorting for a cache-oriented stable pack and use a deterministic ordering policy.

The true context limit is:

`available_evidence = model_context - system_and_tools - live_history - reserved_generation - safety_margin`.

Retokenize with the actual inference tokenizer. The Repomix default provides an estimate for some model families, not exact Qwen/Llama/Claude accounting. For cloud calls, use returned usage as billing evidence; for local inference, use the runtime's tokenizer and prompt-evaluation timings.

### Proposed configuration, to adapt to the actual repository

This is an illustrative config matching the inspected schema, not an installed artifact or measured optimum:

```json
{
  "input": {"maxFileSize": 1048576},
  "output": {
    "filePath": "context-map.xml",
    "style": "xml",
    "parsableStyle": true,
    "compress": true,
    "removeComments": false,
    "showLineNumbers": true,
    "copyToClipboard": false,
    "tokenBudget": 24000,
    "git": {"sortByChanges": false, "includeDiffs": false, "includeLogs": false},
    "patterns": [
      {"pattern": "**/*.luau", "compress": false},
      {"pattern": "**/*.lua", "compress": false},
      {"pattern": "tests/**", "compress": false},
      {"pattern": "**/LICENSE*", "compress": false}
    ]
  },
  "include": ["star/**/*.py", "frontend/src/**/*", "tests/**/*", "**/*.luau", "**/*.lua", "README.md", "LICENSE*"],
  "ignore": {
    "useGitignore": true,
    "useDotIgnore": true,
    "useDefaultPatterns": true,
    "customPatterns": ["**/.env*", "**/*.pem", "**/*.key", "**/credentials*", "**/node_modules/**", "**/dist/**", "**/build/**", "**/models/**", "**/checkpoints/**", "**/logs/**"]
  },
  "security": {"enableSecurityCheck": true}
}
```

The 24k number is only a starting envelope. The wrapper should use the actual task/model budget. Files excluded by size, encoding, or policy must be listed as omitted so Litha cannot mistake an incomplete pack for the complete repository.

### Acceptance checks

Create controlled fixtures with a secret in a normal file and a separate secret only in a diff; confirm neither enters a provider request. Confirm token overflow never forwards the generated output. Test unsupported Luau, BOM text, very large files, symlinks that escape the workspace, and parse failure. Require stable content hashes for unchanged inputs. For coding quality, compare full-repository packing, retrieval-only, and layered context on the same bug tasks with hidden tests; measure missing-evidence errors as well as tokens.

## 3. ccusage: useful accounting, not the authority for spending control

### Current implementation findings

The current repository is a Rust-backed multi-adapter system, distributed through platform packages and an npm-facing package. Describing it as only the original TypeScript Claude log script would be stale. Source adapters normalize recorded events; the Claude adapter reads project/session JSONL. The public docs now include multiple coding agents and unified reporting. [Repository](https://github.com/ccusage/ccusage), [Claude adapter](https://github.com/ccusage/ccusage/blob/1c1bb1e1bfe327dad6ef056e725f8d4a9cfaa709/rust/adapters/claude/README.md).

Cost modes have different semantics: `auto` uses stored costs where present, otherwise calculates; `calculate` derives costs from usage and pricing; `display` uses stored costs and returns zero when missing. Therefore zero is not evidence of free execution. Unknown prices also produce zero-valued estimates, with `unpricedModels`/`missingPricing` flags in JSON. [Cost modes](https://ccusage.com/guide/cost-modes), [JSON output](https://ccusage.com/guide/json-output).

The core code keeps uncached input, output, cache-read, and cache-creation buckets separate. It distinguishes cache creation durations, historical price lookup, and model-specific long-context tier behavior. Do not flatten those buckets into `total_tokens × one_price`. [cost.rs](https://github.com/ccusage/ccusage/blob/1c1bb1e1bfe327dad6ef056e725f8d4a9cfaa709/rust/crates/ccusage-core/src/cost.rs).

Deduplication is materially complex: copied transcripts, content blocks, missing request IDs, sidechain replay, and gateway IDs can otherwise double-count. The source documents different handling for message+request identifiers and sidechain copies. Malformed JSONL is skipped, so a successful report need not mean every source event was valid. [Claude source notes](https://github.com/ccusage/ccusage/blob/1c1bb1e1bfe327dad6ef056e725f8d4a9cfaa709/rust/adapters/claude/src/README.md).

### Litha integration recommendation

Use ccusage as a read-only importer for external Claude/other agent activity. Litha's own orchestrator should emit a compact immutable event ledger directly, so it can reserve budget before work starts and reconcile actual usage afterward. A retrospective log reporter cannot stop several simultaneous workers overspending a limit already committed elsewhere.

Each event should capture task/run/attempt, provider and model identity, price-snapshot identity, input/output/cache buckets, billed or estimated amount, pricing status, elapsed wall time, local prompt/decode timing when available, success/failure, and validation outcome. Avoid storing source code or full prompts in a usage ledger.

Show three separate values: actual provider-billed cost when known; API-equivalent estimate for subscription usage; local hardware usage. Subscription API-equivalent cost is not an additional invoice. Local inference may have no per-token vendor charge, but still consumes time, energy, memory, and capacity.

Prefer an offline command for a pinned reviewed installation, for example `ccusage daily --json --offline --timezone America/Chicago`, then map its output into a versioned adapter. Confirm the selected version's JSON shape; do not assume every historical ccusage output has today's fields. [CLI options](https://ccusage.com/guide/cli-options).

Most useful dashboard measures: verified tasks completed, first-pass acceptance, total cost including retries, latency p50/p95, cache reuse, malformed or unpriced-event counts, and context tokens per successful change. Tokens alone can reward wrong answers or failed attempts that terminate early.

### Meaningful tests

Use known fixtures for duplicates, sidechain replay, cache-write/read separation, missing prices, malformed final JSONL lines, historical price changes, timezone rollover, and unknown-model usage. Compare the imported normalized total against the reporter and the provider where available. The budget ledger should test concurrent reservations and release/refund on failure independently of ccusage.

## 4. Caveman: distinguish response style from recoverable input compression

### What changed and what the evidence supports

The current project is larger than a short speaking-style skill. Its README presents output style, input compression, model/effort routing, reusable scripts, cache-related optimization, and browsing. These have different data flows and evaluation evidence. Installing its current bundle also changes host-agent integrations, so it should not be treated as adding a harmless prose instruction. [README](https://github.com/JuliusBrussee/caveman).

The project's own `HONEST-NUMBERS.md` provides the most useful correction to the headline: the response skill itself compresses neither input nor thinking tokens. Against a plain concise-answer control, its committed ten-question, single-run older-rule measurement reports a 3% median output reduction for ordinary Caveman and 35% for Ultracave. It says token length does not prove semantic fidelity and no reviewed fidelity snapshot was committed. These are not Litha benchmarks. [Honest Numbers](https://github.com/JuliusBrussee/caveman/blob/9b68f7ed12b05e7efaff18e65c5a3fc2849fd0a4/docs/HONEST-NUMBERS.md).

The skill text explicitly preserves negation, numbers, units, and code/commands/paths/errors, and favors clarity if compression conflicts. This is the right invariant to borrow. A promise in instructions is still not a mechanical guarantee that a model preserves every fact. [Skill source](https://github.com/JuliusBrussee/caveman/blob/9b68f7ed12b05e7efaff18e65c5a3fc2849fd0a4/skills/caveman/SKILL.md).

The README reports a 33.2% whole-session input reduction in its selected compression experiment, with HTML losing and fixture limitations disclosed. It also reports an interim model/effort-routing cost result; that is a separate intervention. Do not add output reduction, input reduction, and routing reductions together. Do not present any of those numbers as guaranteed throughput, intelligence, or hardware gains.

### The strongest technical idea in the implementation

The Anthropic proxy code distinguishes the mutable live tail from a frozen cached prefix. It saves emitted compressed replacements and reuses identical bytes when the source block returns later inside the frozen region. This addresses an easy-to-miss failure: compressing a block on one turn and sending its original on the next can destroy prefix-cache reuse. [content_compress.go](https://github.com/JuliusBrussee/caveman/blob/9b68f7ed12b05e7efaff18e65c5a3fc2849fd0a4/proxy/providers/anthropic/content_compress.go).

The engine also summarizes facts computed from elided repeated records: constants, complete small enumerations with counts, numeric extrema using original strings, and bounded coverage metadata. It avoids claiming partial enumerations are complete. This is more useful to Litha than generic summaries like 'many similar logs omitted.' [invariants.go](https://github.com/JuliusBrussee/caveman/blob/9b68f7ed12b05e7efaff18e65c5a3fc2849fd0a4/engine/compressors/invariants.go).

### Recommended narrow experiment

Start with deterministic local test/log summaries that preserve exit codes, test totals, failing names, first actionable error, exact paths/line numbers, and an original-content hash. Store complete output locally and provide an expansion handle. For code, numbers, API fields, negation, coordinates, or executable commands, require exact recovery before an edit or final decision that depends on omitted content.

Use a short plain-English style rule for routine status messages, keeping Litha's intended friendly personality for conversation. Do not impose caveman speech on technical explanations, design work, or the user's request for depth. Benchmark against a concise-control prompt, not only a verbose default.

The Caveman security document explicitly says recovery cannot prove that a model will ask for missing detail. It also distinguishes local processing from model-provider transfer; Auto routing can send request context to Caveman Cloud. For Litha's local-first design, a useful experiment can be entirely local with optional cloud routing disabled. [Security/privacy](https://github.com/JuliusBrussee/caveman/blob/9b68f7ed12b05e7efaff18e65c5a3fc2849fd0a4/docs/technical/security-and-privacy.md).

Test preservation of `not`, `only`, `except`, inequalities, units, negative values, rare failing records, duplicate counts, and original recovery; require byte-stable output for identical inputs. Include counterexamples where every row matters and compression should decline. Measure billed totals, wall time, correctness, and number of recovery requests. A shrinking stage that causes extra model turns may be a net loss.

## 5. Small implementation with the best expected value

Build one **context admission and provenance layer** around existing inference/tool interfaces, not a new agent framework. It accepts candidate evidence blocks, rejects unsafe or stale exports, records full-source hashes and representation, counts using the selected model tokenizer, and fits evidence to a task budget while reserving space for a response. Large tool outputs get deterministic summaries and expansion handles. External ccusage reports feed observability; Litha's own event ledger records actual runs.

A reproducible evaluation compares: current behavior; retrieval plus exact selected files; that system with Repomix maps; that system with deterministic log compression. Use the same model, tasks, checkout, seed settings where supported, hardware, and acceptance tests. Randomize run order and record warm/cold cache separately. Measure total work through accepted completion, including retries. Only promote variants that meet quality gates and improve a chosen latency/cost/resource objective.

This layer fits the local Forge direction: GitHub can supply source snapshots or receive reviewed work, but is not required to store context, usage events, recovery originals, or learned validation results.


# Detailed chapter B - Crawl4AI, design and resource qualification

Research date: 2026-10-31 (user-facing date, America/Chicago). Read-only inspection of official documentation, current public repository trees, code, README files, licenses, and advisories. No fetched code was executed, no package was installed, and no performance result below is presented as measured on the owner's machines.

## Main recommendation

Extend the existing Litha/STAR modules rather than install a second research or design framework. Repository inspection identified `star/design_md.py`, `resource_atlas.py`, and `scene_integrity.py`; active PR #855 already addresses design contrast/evidence coverage. This chapter supplies integration guidance for that existing architecture. Crawl4AI is useful as a bounded acquisition worker. DESIGN.md is useful as inspectable reference material. The AI-tools list is useful as a lead list that must pass independent revalidation. None changes model weights or proves improved intelligence by itself.

## 1. Verified repository snapshots

The following were retrieved through GitHub's read-only API on this research pass:

| Repository | HEAD inspected | Commit date (UTC) | Observations |
|---|---|---|---|
| `unclecode/crawl4ai` | `888299fb5f0b82181897dc0e61bfb4b036f0aea5` | 2026-10-26 08:41:46 | Latest published release returned by `/releases/latest`: v0.9.5, published 2026-10-14 10:25:39; Apache-2.0 LICENSE. |
| `VoltAgent/awesome-design-md` | `fcc70284932276d085f01ef9f83edde90b1258cb` | 2026-10-28 15:45:37 | Complete recursive tree: 260 entries, 84 files ending in `/DESIGN.md`, no `.html` preview files; MIT LICENSE. |
| `AI-Tools-Inc/awesome-ai-tools` | `2feac57be856d522b07f879f317668a2966c373f` | 2024-08-25 00:31:29 | Complete tree has only README.md, ai_tools_banner.png, link_icon.svg; no repository LICENSE or contribution rubric found. |

Exact API evidence URLs:

- https://api.github.com/repos/unclecode/crawl4ai/commits/888299fb5f0b82181897dc0e61bfb4b036f0aea5
- https://api.github.com/repos/unclecode/crawl4ai/releases/latest
- https://api.github.com/repos/VoltAgent/awesome-design-md/commits/fcc70284932276d085f01ef9f83edde90b1258cb
- https://api.github.com/repos/VoltAgent/awesome-design-md/git/trees/84becd0fc3b6c3646093fcf65d4d62637e09aabc?recursive=1
- https://api.github.com/repos/AI-Tools-Inc/awesome-ai-tools/commits/2feac57be856d522b07f879f317668a2966c373f
- https://api.github.com/repos/AI-Tools-Inc/awesome-ai-tools/git/trees/6065aee30033e38465ad358f6ec0a574807ebd85?recursive=1

## 2. Crawl4AI: what to use

### Acquisition without paying an LLM to parse every page

Official extraction documentation describes CSS, XPath, and regex strategies that do not call a model. Use these for stable documentation templates, release tables, symbol references, headings, and structured examples. An LLM can help propose a selector/schema during onboarding, but a reviewed deterministic extractor should perform routine collection. A broken selector should produce a detectable missing-field failure, not invite the model to fabricate the missing field. Source: https://docs.crawl4ai.com/extraction/no-llm-strategies/.

Recommended Litha/STAR route: prefer authoritative Git/API/raw Markdown when already available; use an ordinary HTTP fetch for static pages; spend browser memory only on content that actually requires JavaScript. That routing is our design recommendation, not a claim that the default Crawl4AI browser automatically makes this choice. Neither headless browsing nor deterministic extraction requires Litha's main LLM on the 8 GB GPU.

### Bounded parallelism instead of maximum parallelism

The dispatcher implementation exposes memory-adaptive concurrency and fixed semaphore concurrency; the current MemoryAdaptiveDispatcher constructor defaults to 90% memory pressure, 95% critical pressure, 85% recovery, and 20 maximum sessions. Those are implementation defaults, not recommendations for a desktop also serving an LLM, Roblox Studio, voice, and streaming. Official documentation describes per-domain pacing and backoff for 429/503, plus streaming results. Sources: https://docs.crawl4ai.com/advanced/multi-url-crawling/ and https://github.com/unclecode/crawl4ai/blob/888299fb5f0b82181897dc0e61bfb4b036f0aea5/crawl4ai/async_dispatcher.py.

Proposed initial operating profile (tune through measurement): one browser worker during interactive use, at most two concurrent browser pages, bounded pages/depth/bytes/time, and a queue that yields to interactive jobs. Begin with a 70% memory threshold, 80% critical threshold, and 60% recovery threshold if using the memory dispatcher; explicitly set all three coherently. Record whole-machine available RAM and worker RSS because percent alone can hide page spikes and OS reserve pressure. Treat cancellation as a real test: cancelled work must close active pages and stop queued work. Do not infer that memory-adaptive dispatch imposes a hard memory limit; use a process/container cap as well where supported.

The deep-crawl documentation exposes BFS, DFS, BestFirst, domain filters, max_depth, and max_pages. The max_pages default is unlimited in the documented strategy. Always set it. A documentation update job might initially cap at 50 pages/depth 2, but this is a proposed experiment setting, not an empirically optimal value. Source: https://docs.crawl4ai.com/core/deep-crawling/.

### Cache semantics: documentation conflict found and resolved from code

Some text in the complete SDK page says BYPASS writes results, while the cache-modes page only says it skips cache. Actual `cache_context.py` permits reads for ENABLED/READ_ONLY and writes for ENABLED/WRITE_ONLY. Therefore, in the inspected implementation:

| Explicit mode | Read cache | Write cache | Appropriate use |
|---|---|---|---|
| ENABLED | Yes | Yes when a crawl is needed | Reuse known snapshots, subject to freshness policy |
| READ_ONLY | Yes | No | Reuse without saving; **not** an offline-network guarantee |
| WRITE_ONLY | No | Yes | Deliberate fresh fetch and refresh of cached content |
| BYPASS | No | No | Fresh operation without ordinary cache use |
| DISABLED | No | No | No ordinary cache use |

Sources: https://github.com/unclecode/crawl4ai/blob/888299fb5f0b82181897dc0e61bfb4b036f0aea5/crawl4ai/cache_context.py and https://github.com/unclecode/crawl4ai/blob/888299fb5f0b82181897dc0e61bfb4b036f0aea5/crawl4ai/async_webcrawler.py. Note constructor `CrawlerRunConfig.cache_mode` defaults to BYPASS in this snapshot; passing None is normalized to ENABLED inside the crawler. Set the intended mode explicitly rather than rely on contradictory doc defaults.

`check_cache_freshness` is opt-in. The current validator tries conditional HTTP requests and a fingerprint of the HTML head; a matching head can be considered fresh, and validation errors can fall back to cache. Sources: https://github.com/unclecode/crawl4ai/blob/888299fb5f0b82181897dc0e61bfb4b036f0aea5/crawl4ai/cache_validator.py and `async_webcrawler.py` above.

Our inference: an unchanged head does not prove an unchanged article body, code example, or API contract. For Litha, preserve separate `fetched_at`, `validated_at`, `validation_method`, and `content_sha256` fields; do not advance `fetched_at` on a head-only check. Mark error fallback as stale/unverified. Schedule full content revalidation based on source volatility and pin repository sources to commits. Keep retained originals so extracted claims can be reconstructed. Configure the worker's OFF state outside the library and verify zero network traffic; READ_ONLY is not that switch.

### Provenance is more than Markdown link numbering

CrawlResult can return raw/cleaned HTML, raw Markdown, Markdown with link citations, a references section, and optional filtered/fit Markdown. Link preservation helps citations, but it does not independently establish that each sentence is accurate. Aggressive pruning can drop a negation, exception, version label, table header, or adjacent code block. Sources: https://docs.crawl4ai.com/core/crawler-result/, https://docs.crawl4ai.com/core/markdown-generation/.

Recommended storage contract: source URL, final URL, fetch timestamp, canonical URL when trustworthy, commit/version if known, extraction version, content hash, local content pointer, source class, license status, source span/heading, and validation outcome. Store raw evidence separately from summaries and verified lessons. Summaries are regenerable derived artifacts. Deduplicate equivalent content using hashes while retaining multiple provenance references. Retrieve concise spans for the model; provide a path back to original context when a task needs exactness.

### Security findings that change the integration choice

v0.9.5 is the current inspected release baseline. It fixes further issues beyond v0.9.4, including cache freshness requests bypassing the egress proxy and Chromium TLS verification defaults. v0.9.4 had fixed robots.txt and link-preview fetch paths, but was still affected by the cache-check advisory. Sources: https://github.com/unclecode/crawl4ai/releases/tag/v0.9.5, https://github.com/unclecode/crawl4ai/security/policy, https://github.com/unclecode/crawl4ai/security/advisories/GHSA-w4xc-px5p-c32w.

Crucial code distinction: the plain Python library intentionally has no egress policy by default. `crawl4ai/egress_policy.py` says unset proxy state means direct requests; the Docker server installs the pinning proxy. Installing the pip package alone does not inherit Docker's request/config protections. Source: https://github.com/unclecode/crawl4ai/blob/888299fb5f0b82181897dc0e61bfb4b036f0aea5/crawl4ai/egress_policy.py.

Litha should expose a narrow request (`approved source id`, `bounded extraction profile`) to an isolated worker, not arbitrary browser flags, scripts, model names, local paths, hooks, proxy addresses, output paths, or provider credentials. Enforce approved HTTPS hosts and public destinations at the actual connection and every redirect/subresource path; a string URL check alone is insufficient. Put document contents in the evidence channel, never promote web instructions into the worker's execution policy. Enable robots checks explicitly: the inspected constructor defaults `check_robots_txt=False`. Keep the existing research/tool OFF-by-default preference. Retain authentication and TLS verification if choosing the Docker API. These are direct responses to documented integration risks, not reasons to abandon the tool.

### Meaningful acquisition acceptance tests

1. Fixed local corpus: static docs, JS-rendered docs, nested tables, code fences, version badges, repeated navigation, redirect chain, and duplicate article URLs. Verify exact required-field retention and source spans.
2. Cache matrix: cold, warm, WRITE_ONLY refresh, body-only change with unchanged head, 304, timeout, redirect, and extraction-version change. Stale fallback must remain explicitly stale.
3. Worker boundaries: unapproved hostname, private/link-local/loopback target, redirected forbidden destination, local-file URL, untrusted code/config field, oversize response, timeout, and cancellation.
4. Record valid documents/sec, p50/p95 latency, peak RSS, bytes downloaded, duplicate percentage, evidence coverage, and extraction accuracy. A faster parser that loses a negation or API parameter fails.
5. Compare against existing ingestion with identical corpus/hardware. Enable the adapter only if quality holds and a meaningful bottleneck improves.

## 3. awesome-design-md: use its structure, verify its claims

The current snapshot contains 84 design analyses. The README still says each site includes preview.html and preview-dark.html, but the complete repository tree contains neither; per-site README files direct previews/downloads to getdesign.md. This mismatch is a useful illustration of why Litha should inspect artifacts, not trust the README alone. Sources: repository tree above; https://github.com/VoltAgent/awesome-design-md/blob/fcc70284932276d085f01ef9f83edde90b1258cb/design-md/linear.app/README.md.

The inspected Linear analysis is substantive: YAML front matter with semantic color/type/component tokens, rules for surfaces and spacing, button/input states, responsive behavior, and known gaps. It explicitly notes unavailable proprietary fonts and proposes substitutes. Known gaps include absent form error/validation examples. It is a third-party analysis of a marketing surface, not the official complete Linear product specification. Sources: https://github.com/VoltAgent/awesome-design-md/blob/fcc70284932276d085f01ef9f83edde90b1258cb/design-md/linear.app/DESIGN.md, https://github.com/VoltAgent/awesome-design-md.

The repo is MIT licensed, requiring its notice on substantial reused portions, while the README disclaims ownership of brands' identities. Treat fonts, logos, screenshots, art, and trademarked identities separately. Extract useful design principles and create Litha's own OLED black/gold specification; do not call copied brand work original. Exact license: https://github.com/VoltAgent/awesome-design-md/blob/fcc70284932276d085f01ef9f83edde90b1258cb/LICENSE.

### Extend Litha's existing parser/linter

Recommended additions only where absent after checking existing code and PR #855:

- Add provenance and confidence per rule: observed, inferred, or project-authored; source snapshot; evidence location; unknown states. A token document cannot establish all states merely by listing them.
- Preserve a canonical project design specification with semantic roles (canvas/surface/text/primary/error/focus), component states, keyboard/controller/touch behavior, motion settings, density, and edge cases.
- Generate web CSS variables and native Roblox token values from the same semantic specification. Keep platform-specific implementation and layout rules explicit.
- Treat design references as input to a proposal, then render and compare the actual output. Prevent a reference document from overwriting unrelated branding or behavioral requirements.
- Retain failures as compact lessons: long translated label clipped; selected controller item invisible; gold button uses unreadable pale text; tween ignores reduced-motion preference; inventory panel collides with safe area.

The desired speed improvement comes from fewer design retries and reusable validated components, not from feeding all 84 references into every prompt.

### Native Roblox mapping

| Design concept | Roblox implementation family | Verification |
|---|---|---|
| Semantic colors/type | Color3, font/type tokens in a Luau module | Rendered contrast and readable text in real backgrounds |
| Content-driven layout | AutomaticSize, UIListLayout/UIGridLayout, UIPadding | Long labels, translated strings, empty/full inventory |
| Responsive sizing | UDim2 scale/offset, AnchorPoint, UISizeConstraint/UIAspectRatioConstraint | Small/large/mobile viewports; avoid accidental distortion |
| Scrollable content | ScrollingFrame with AutomaticCanvasSize | Reach final item; preserve selection; no hidden actions |
| Focus and selection | GuiObject selection configuration, GuiService selected object | Controller navigation and visible focus under all states |
| Reduced motion/text preference | GuiService.ReducedMotionEnabled and PreferredTextSize | Change preference while UI is open and verify response |

Sources: https://create.roblox.com/docs/ui/size-modifiers; https://create.roblox.com/docs/ui/position-and-size; https://create.roblox.com/docs/reference/engine/classes/GuiService. The mappings are implementation recommendations; web CSS is not drop-in Roblox UI.

### Quality gates

For web text, WCAG 2.2 AA's contrast criterion specifies 4.5:1 normal text and 3:1 qualifying large text, with stated exceptions. Pointer targets have a 24 CSS pixel minimum under SC 2.5.8 with exceptions; a 44-pixel touch target can be Litha's stronger product target, but do not falsely label that the AA minimum. Sources: https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html, https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html.

Automated gates should detect contrast regressions, missing component states, clipping/overlap, unreachable controls, absent focus, broken actions, loading/error/empty states, and ignored motion preferences. Screenshot differences detect visual changes, not whether an interface is tasteful; use an approved reference rubric and owner acceptance for taste. Roblox output requires actual Studio/device tests, not a passing HTML preview.

## 4. awesome-ai-tools: discovery only

The inspected main branch has not changed since August 2024. Its README spans coding, marketing, sales, image, video, audio, and legal tools, mostly as short marketing descriptions. It includes third-party commercial services and some direct/referral-style URLs; no tested compatibility matrix, local-resource requirements, API contract, quality benchmarks, or list-wide licensing evidence is supplied. A directory's “10x” copy is not an experimental result. This is not a list of uniformly open-source or free integrations. The absence of a repository license also means it should not be bulk-vendored as if permissively licensed. Source: https://github.com/AI-Tools-Inc/awesome-ai-tools/blob/2feac57be856d522b07f879f317668a2966c373f/README.md; commit/tree links above.

For resource_atlas, store these entries as unverified leads. Promotion requires a current primary source, correct canonical project identity, deployment mode, software/model/asset license separately, resource budget, data flow, pinned integration contract, and a small representative evaluation. Preserve last-checked timestamps; reject stale or dead endpoints instead of learning their sales copy as fact. Rank tools by the specific missing capability and measured improvement, not stars or directory order.

## 5. Twelve stronger adjacent candidates

These are independently selected complements, not a claim that all appear in the submitted directory. Most should be connected to existing services rather than added as permanent daemons.

| Priority | Tool | Concrete use for Litha | Practical limit / test | Primary source |
|---|---|---|---|---|
| P0 | ripgrep | Exact local file/symbol/error search before asking a model to read files | Fast lexical search does not understand meaning; benchmark retrieval recall on real repair tasks | https://github.com/BurntSushi/ripgrep |
| P0 | Tree-sitter | Incremental syntax trees and symbol-aware context boundaries | A syntax tree is not type resolution; verify grammar/language coverage and fallback behavior | https://tree-sitter.github.io/tree-sitter/ |
| P0 | SQLite FTS5 | Local keyword/BM25 evidence index with no service or GPU | Verify build includes FTS5; evaluate vocabulary mismatch before adding embeddings | https://www.sqlite.org/fts5.html |
| P0 | Playwright | Actual web interaction + reproducible visual regressions | Pin OS/browser/fonts/viewport; baselines require review; does not validate Roblox native UI | https://playwright.dev/docs/test-snapshots |
| P0 | axe-core | Automated web accessibility checks integrated into render verification | Automated checks are partial, and incomplete results need manual review | https://github.com/dequelabs/axe-core |
| P0 | luau-lsp | Standalone `analyze` with API types and Rojo resolution before Studio run | DataModel diagnostics resolve to any by default unless strictDatamodelTypes is enabled; choose deliberately and pin API definitions for reproducibility | https://github.com/JohnnyMorganz/luau-lsp |
| P0 | StyLua | Consistent Luau formatting with `--verify` reparse/AST comparison | Formatting is not behavioral validation; continue type/runtime tests | https://github.com/JohnnyMorganz/StyLua |
| P1 | glTF-Validator | Check exported assets' references, buffers, quaternions, animation input/output, and format validity | Cannot prove natural animation, correct grip, contact, or scene composition; pair with the IK trace diagnostic/scene_integrity | https://github.com/KhronosGroup/glTF-Validator |
| P1 | OpenTelemetry conventions/SDK | Common task, model, and tool latency/usage traces; find bottlenecks before optimizing | GenAI conventions are evolving; pin schema and keep prompt bodies off unless explicitly needed; log cache/input/output correctly | https://opentelemetry.io/blog/2026/genai-observability/ |
| P1 | promptfoo | Fixed task/evaluation matrix and regression comparisons across prompts/providers | Local eval does not imply zero network: configure every provider/grader/embedding path, disable sharing/telemetry, and enforce egress; remote-only features are unsuitable for offline tests | https://github.com/promptfoo/promptfoo; https://www.promptfoo.dev/docs/faq/; https://www.promptfoo.dev/docs/red-team/troubleshooting/data-handling/ |
| P2 | whisper.cpp | Local transcription of user voice and approved training clips | Benchmark chosen model/language/audio on owned hardware; CPU use competes with Studio/LLM; confidence/VAD still matter | https://github.com/ggml-org/whisper.cpp |
| P2 | ComfyUI | Reproducible, pinned image/texture workflows and reusable generation graphs | Model and custom-node licenses are separate; external nodes execute code; VRAM admission must prevent contention with LLM/streaming; CPU compatibility does not mean interactive speed | https://github.com/Comfy-Org/ComfyUI |

Additional exact details verified: luau-lsp's standalone analysis and strict DataModel option appear in README; StyLua's `--verify` reparses output and compares AST; glTF-Validator emits JSON issues and asset statistics; OpenTelemetry's former gen-ai-spans page says the GenAI specifications have moved, so do not freeze implementation against an unmaintained landing page.

## 6. Integration order and measurable outcome

1. Preserve the existing offline defaults and existing design/atlas/scene modules. Add source provenance/freshness only where absent; land independent diagnostic work without touching unrelated in-flight PR changes.
2. Build a fixed evaluation set from Litha's own past failures: broken Roblox type usage; UI overlap under mobile/large text; absent loading/error state; foot slide; hand grip drift; stale docs; wrong cache hit; malformed extraction.
3. Establish current quality, wall time, prompt/output tokens, retries, peak RAM/VRAM, and verification coverage.
4. Pilot the crawler against one approved documentation family. Prove correct retention and stale-state handling, then enable additional sources selectively.
5. Convert a small number of accepted design principles into the existing design system, check rendered output, and store passing examples with their evidence.
6. Promote additional tools one at a time when they remove a measured bottleneck. Keep rollback possible and compute budgets explicit.

Success is higher passing-task rate and lower total time to a verified result. A larger reference database, shorter answer, smaller token count, or prettier screenshot alone does not establish that Litha is smarter. None of these research findings is evidence that Litha's deployed runtime changed during this read-only investigation.


# Detailed chapter C - Inverse kinematics and motion engineering

Research date: October 31, 2026 (user timezone). Recommendations and proposed thresholds below are engineering proposals, not measured improvements to Litha. No Roblox Studio, Blender executable, or target Windows machine was exercised in this research.

## 1. Main finding

Give Litha a motion engineering subsystem, with engine-native solvers and independently checked examples. Do not put language-model inference in the frame-by-frame pose loop. Litha should select the rig, describe the intended interaction, author constraints, test the motion, and diagnose failures. Roblox, Blender, or a small native animation runtime should calculate the joint updates.

IK is the mapping from desired hand/foot/head targets to joint configurations. It does not by itself provide believable locomotion, collision avoidance, cloth/hair physics, hand geometry, balance, or an animator's timing. Those need separate constraints and evaluation. This distinction is essential for the user's existing goals of correct grips, grounded feet, expressive VTuber motion, and avoiding visibly broken generated animation.

Highest-return initial capabilities are (1) weapon/tool grips with orientation and elbow poles, (2) contact-aware feet on slopes and stairs, (3) gaze with neck limits and eye/head coordination, and (4) reproducible Blender-to-engine rig validation. Start with these before a general-purpose whole-body optimizer.

## 2. Solver selection

The selection below is a recommendation, informed by the original FABRIK and DLS literature and maintained engine implementations. It is not a universal speed ranking.

| Method | Best first use | Advantages | Failure modes and additional work |
|---|---|---|---|
| Analytic two-bone | Shoulder–elbow–wrist and hip–knee–ankle | Fixed work for a simple limb; bend plane is explicit | Degenerate targets, inner/outer unreachable regions, pole flips, joint limits, wrist orientation |
| Aim/look-at | Eyes, neck, weapons, sensors | Small local operation | Needs yaw/pitch/twist bounds; must distribute large turns through body |
| FABRIK | Tails, tentacles, multi-joint reach, chains where endpoint position dominates | Positions solved with repeated forward/backward passes and length preservation | Twist/orientation and anatomical constraints are additional design work; close-root targets may zig-zag |
| CCD | Hinged chains and constrained procedural chains | Simple coordinate updates, usable with per-joint limits | Joint ordering, oscillation, local minima, sudden flips, and Euler-limit complications |
| Damped least squares / task-space optimization | Multiple simultaneous targets, whole-body pose fitting | Combines multiple task errors and regularizes near singularities | Cost, weighting and damping choices; posture, limits and collision constraints must be supplied |
| QP-based differential IK | Future robotics-style whole-body constraints | Explicit velocity/position limits and collision inequalities in suitable implementations | Larger dependencies; kinematic feasibility is not dynamic balance or a complete motion planner |

FABRIK's original author describes solving by placing points on lines instead of using rotational matrices in its positional iteration. The author's report also explains that constraints should be incorporated during iterations, rather than clamping everything only after solving. This does not mean a production skeletal animation implementation can ignore rotations: local joint transforms and skinning still need reconstruction. Sources: [FABRIK author page](https://www.andreasaristidou.com/FABRIK), [author's technical report](https://andreasaristidou.com/publications/papers/CUEDF-INFENG%2C%20TR-632.pdf).

Buss and Kim's DLS/SDLS work is useful for understanding singularities and unreachable-target oscillation. Damping reduces unstable amplification, but it introduces an accuracy/reactivity tradeoff. The reported convergence results belong to the paper's configurations, not to Litha's hardware or rigs. Source: [Buss research page](https://mathweb.ucsd.edu/~sbuss/ResearchWeb/ikmethods/), [survey](https://math.ucsd.edu/~sbuss/ResearchWeb/ikmethods/iksurvey.pdf).

### A small analytic foundation

For two segments of lengths a and b, root r, desired target t, and pole p:

1. Compute d = ||t-r||. A position is reachable only when |a-b| <= d <= a+b, before additional joint limits.
2. Choose a safe direction u toward the target; use the prior/rest direction when d is nearly zero.
3. Clamp the solve distance to a supported interval. Keep an explicit `unreachable` result for the original target.
4. Compute x = (a²-b²+d²)/(2d) and h = sqrt(max(a²-x², 0)).
5. Project the pole into the plane perpendicular to u, normalize to v, and place the elbow at r+x*u+h*v.
6. If the pole projection is degenerate, preserve the prior valid bend plane or use a deterministic rest-plane fallback. Do not normalize a zero vector.
7. Convert the resulting directions into rotations relative to the rig's rest transforms. A position-only solution still needs wrist/ankle orientation, twist distribution, and anatomical constraints.

This derivation explains why robust edge handling matters more than replacing one programming language with another. Zero-length bones, a target at the root, unequal bone lengths, mirrored rigs and poles crossing the target direction should all be fixtures.

## 3. Roblox: use IKControl, and test the actual semantics

Roblox officially supports IKControl on Humanoid or AnimationController rigs with Type, EndEffector, Target and ChainRoot. Position is appropriate for positional reach; Transform includes both position and orientation and is the better starting point for a rigid grip. Roblox also exposes Rotation and LookAt. Source: [Creator Hub overview](https://create.roblox.com/docs/animation/inverse-kinematics), [IKControlType](https://create.roblox.com/docs/reference/engine/enums/IKControlType).

Important source-verified details from the official API YAML:

- A Pole controls the intermediate bend direction. Supply it explicitly for custom rigs; automatic limb inference assumes recognizable arm/leg configurations.
- SmoothTime is a critically damped target smoother; the documented default is 0.05 seconds and zero disables smoothing.
- Weight=0 does not completely disable the control because smoothing and pole effects can remain. Set Enabled=false for full deactivation.
- Offset and EndEffectorOffset let the desired grip/contact point differ from a part's pivot.
- Priority documentation contains an inconsistency: its summary and first explanation say higher values have higher priority and solve later, then a sentence recommends a lower priority for the more important control. Store this as a documentation conflict and verify interacting controls in Studio before making it a trusted lesson.

Source: [official IKControl YAML](https://github.com/Roblox/creator-docs/blob/main/content/en-us/reference/engine/classes/IKControl.yaml). Retrieved directly through GitHub with blob SHA `5bd5ecf2ed1ac4ab0b3ef646880495c4ef7cd9ae`. The priority inconsistency is in the retrieved file, not an inferred engine defect.

### Recommended weapon/tool grip recipe

Use an asset-local primary grip frame and secondary grip frame. The primary hand/weapon relationship must have one clear owner, so the weapon is not driven by the hand while the same hand is simultaneously trying to chase the weapon through a circular transform dependency. The support hand tracks the secondary frame. Store wrist alignment and palm offsets per rig/weapon pairing, plus stable elbow-pole direction. Reach limits should trigger an alternate pose or reduced correction, not stretched limbs.

Test idle, walk, run, crouch, jump, reload, weapon change, near-wall aim, target behind character and different avatar proportions. Evaluate both the palm contact point and orientation; measuring hand-pivot distance alone misses visibly rotated grips. Finger curl/contact remains a separate authored or procedural layer.

### Recommended character lifecycle

Build controls once per character/rig instance and cache validated joint references. Rebuild on respawn/rig change and clean up connections. Keep procedural presentation separate from authoritative game outcomes. Test with two Studio clients, not just one local viewport, before deciding what intent/targets must be replicated. Do not assume every local bone update has the desired network behavior.

## 4. Foot placement requires contact state

The maintained ozz foot-IK sample is a useful reference because it explicitly identifies its limits. It combines downward raycasts, leg IK, ankle alignment and pelvis-height adjustment; it also states that a complete implementation requires activation/deactivation, unreachable-ground handling and additional animation. Source: [ozz foot IK sample](https://guillaumeblanc.github.io/ozz-animation/samples/foot_ik/).

Proposed Litha pipeline:

1. Obtain contact intent from animation curves/events or a tested locomotion state. During a swing phase the foot should travel; indiscriminate planting breaks the gait.
2. Probe plausible support using heel/toe/sole samples or a small shape query when one ankle ray is insufficient. Exclude the character's own geometry.
3. Reject steep, distant or transient support. Use separate acquire/release thresholds to prevent contact flicker.
4. When contact is acquired, store the planted transform in the support object's local coordinates. Reconstruct its world transform each frame. This handles moving platforms without making the foot slide through the platform or stay frozen in world space.
5. Adjust pelvis within a limited range to keep both legs within reach. Large discrepancies should select a different animation or a step, not force extreme knees.
6. Solve legs, align the sole to the surface, and preserve a plausible toe-forward direction. Ground normal alone leaves an arbitrary yaw.
7. Blend out during lift-off, jumps and lost support. Clear anchors on teleport/respawn or abrupt platform changes.
8. Measure slip, penetration, knee flips and pelvis jitter over a sequence. A single good screenshot proves little.

A minimal contact controller can use `swing -> acquiring -> planted -> releasing -> swing`, with a separate invalid state for teleports or missing rig data. Contact intent and support detection are different signals. A foot may be visually close to ground while the animation intends it to lift.

For hard contacts, generic pose blending after IK can reintroduce slip. Blend the targets/weights carefully and perform the final contact correction at the appropriate stage. Overlapping whole-body controls require explicit ordering or a joint optimization; two individually correct solvers can fight over the same shoulder or pelvis.

## 5. Blender authoring and export

Use Blender's existing rigging infrastructure rather than reimplementing its solver in Python. The pinned 4.5 LTS manual documents target, pole, chain length, iterations, stretching, rotation tracking and influence. It also warns that IK is special: it runs after other constraints on affected bones regardless of stack placement; a copied transform chain can be needed for constraints intended after IK. The manual's iTaSC section includes a pole/influence limitation. Source: [Blender IK constraint manual](https://docs.blender.org/manual/en/4.5/animation/constraints/tracking/ik_solver.html).

Recommended automation rules:

- Detect installed Blender version and use its matching API/documentation; do not treat a `current` manual as a universal schema.
- Validate rest pose, parent hierarchy, bone names, local axes, lengths, scale and mirrored side conventions before adding constraints.
- Specify chain length explicitly; zero can mean all parent bones and unintentionally pull the torso into the solve.
- Disable stretch for rigid/anatomical limbs unless the style calls for it; make exaggeration explicit.
- Generate clear pole/control bones outside the deform chain, with a stable transform convention.
- Separate control and deformation rigs when necessary. Bake evaluated motion for engines that cannot reproduce Blender constraints directly.
- Round-trip a small export into the target engine and compare contact positions and orientation over time. A valid Blender render does not establish equivalent Roblox or custom-engine behavior.

The iTaSC manual describes DLS/SDLS options and the tradeoffs between tracking precision and continuity. Use that as an advanced authoring option after a baseline rig works, rather than assuming it is automatically superior for all assets. [Pinned manual](https://docs.blender.org/UATEST/manual/en/4.5/animation/armatures/posing/bone_constraints/inverse_kinematics/introduction.html).

## 6. Native and web implementations worth studying

### ozz-animation (C++, MIT)

The IK documentation describes model-space input and local quaternion corrections; model transforms must be recomputed when a parent joint changes. Its two-bone job supports pole, twist, softening, blend weight and reachability. Source: [IK docs](https://guillaumeblanc.github.io/ozz-animation/documentation/ik/), [license](https://github.com/guillaumeblanc/ozz-animation/blob/master/LICENSE.md).

Direct header inspection adds practical details: the middle-joint axis must be normalized; a pole aligned with/crossing the target direction can flip the chain, which is the caller's responsibility to avoid. Softening intentionally sacrifices exact reach near full extension. `reached` is false with partial blend weight. These are valuable behavior contracts for a custom solver interface. Header: [ik_two_bone_job.h](https://github.com/guillaumeblanc/ozz-animation/blob/master/include/ozz/animation/runtime/ik_two_bone_job.h), blob `ded310fdc182af82daad22978c11e502808d0280`.

### Three.js CCDIKSolver (JavaScript, MIT repository)

Useful for an interactive Litha rig debugger or browser preview. Its official addon works on SkinnedMesh and exposes per-link constraints, iteration count and blend factors. [Documentation](https://threejs.org/docs/pages/CCDIKSolver.html), [repository](https://github.com/mrdoob/three.js/).

Source inspection found reused vector/quaternion scratch objects, explicit avoidance of repeated world-matrix getters in the tight loop, and world-matrix updates after joint modification. These are concrete CPU engineering patterns. The source also has edge handling for angle clamping, tiny rotations and angle-limit wrapping. It remains a CCD example, not a full contact or physics system. [Code](https://github.com/mrdoob/three.js/blob/dev/examples/jsm/animation/CCDIKSolver.js), blob `fb3bd8c12e9f7efaabd286bced40471a22cd3e94`.

### Godot native modifiers (version-specific)

Current official documentation includes TwoBoneIK3D, FABRIK3D, CCDIK3D and JacobianIK3D under IKModifier3D/SkeletonModifier3D. This is more relevant for new Godot work than copying old SkeletonIK3D tutorials. The official introduction ties the newer system to Godot 4.6. [Article](https://godotengine.org/article/inverse-kinematics-returns-to-godot-4-6/).

Godot's individual docs candidly describe solver-specific limits: FABRIK can zig-zag near the root; CCD can flip/oscillate; its JacobianIK3D is a Jacobian-transpose solver and converges more slowly. Do not conflate that class with damped least squares. TwoBoneIK3D requires a pole target. [FABRIK](https://docs.godotengine.org/en/stable/classes/class_fabrik3d.html), [CCD](https://docs.godotengine.org/en/stable/classes/class_ccdik3d.html), [Jacobian](https://docs.godotengine.org/en/stable/classes/class_jacobianik3d.html), [two-bone](https://docs.godotengine.org/en/stable/classes/class_twoboneik3d.html).

### Mink / MuJoCo (advanced research, optional)

Mink's repository describes differential IK with joint-position/velocity limits, collision avoidance, closed-chain constraints and native C optimization of some hot paths, under Apache-2.0. This makes it useful for experimenting with whole-body constraints and understanding what a simple arm solver omits. It should not become a mandatory dependency for ordinary Roblox posing. [Repository](https://github.com/kevinzakka/mink).

## 7. Rust and performance strategy

Rust is a reasonable implementation language for a future shared geometry/animation kernel, but rewriting already-native Roblox/Blender solvers would not establish a speed benefit. Keep the engine's native update loop where possible. Benchmark a custom Rust kernel only where profiling identifies a real bottleneck: batch pose validation, retargeting many clips, repeated geometry checks, or a standalone avatar runtime.

Recommended optimizations before a rewrite:

- Precompute hierarchy order, rest transforms, bone lengths, inverse bind transforms and rig mappings.
- Keep frame buffers contiguous and reuse them; avoid per-frame object allocation and string/name lookup.
- Solve short limbs analytically, with bounded iterations/early exits for longer chains.
- Warm-start from a valid previous pose when appropriate, but reset after discontinuities and avoid history-dependent nondeterminism in offline regression tests.
- Update only affected descendants and avoid redundant full-skeleton matrix traversals.
- Separate static geometry preprocessing from dynamic raycasts.
- Use distance/visibility-based update rates for secondary actors; keep first-person hands and nearby hero contacts on a high-quality path.
- Profile raycasts, scene traversal, IPC and serialization separately from IK arithmetic. The solver might not be the main cost.
- Batch calls across Python/Rust boundaries, rather than one call per joint.
- Do not claim that GPU acceleration is useful for one short limb. A GPU option needs enough batched work and measured transfer/dispatch costs to justify it.

At 60 Hz the total frame is about 16.67 ms. Define a smaller measured animation budget within that frame. No speedup or Windows compatibility result was measured in this research.

## 8. Quality gates that make Litha better at motion

The following are proposed starting tests, not industry standards or results already achieved:

| Test group | What to record | Initial acceptance idea |
|---|---|---|
| Finite math | NaNs, invalid quaternions, zero-length input | Never propagate non-finite output; explicit invalid-input result |
| Reachability | Targets inside, at and outside reach shell | Correct status; bounded stable fallback |
| Limb integrity | Relative segment-length drift | Custom fixed-length math within chosen floating-point tolerance |
| Hard grip | Position error normalized by chain length, angular error | Start with <=1% length and <=2 degrees for held-contact fixtures, then tune |
| Planted feet | Slip relative to support, penetration, contact transitions | No growing drift; report RMS and maximum error across the planted phase |
| Temporal quality | Angular speed/acceleration, bend-plane sign changes | No discontinuous flips for continuous target motion away from declared singularities |
| Rig diversity | R15/custom, short/long/chibi proportions, mirrored limbs | Same behavior contract with per-rig calibration |
| Scene diversity | Slope, stair, moving/rotating platform, jump, teleport | Stable contact acquisition/release; no stale anchors |
| Performance | Median/p95/p99 CPU time, allocations, rays, iterations | Budget agreed from baseline on target CPU; retain quality under the same budget |
| Integration | Animation changes, respawn, export/import, two-client playback | Clean lifecycle and matching evaluated behavior |

Metrics should be normalized by rig size so chibi and realistic proportions are comparable. Keep maximum errors as well as averages; a single knee snap can ruin a clip whose mean error is excellent. Evaluate unseen target paths and new rig proportions to prevent overfitting examples. Human review of motion rhythm, appeal and silhouette remains necessary even when numerical contact tests pass.

## 9. How Litha should learn this material

Create verified motion lessons, not just embeddings of documentation. Each lesson should contain engine/version, source URL/commit, rig/rest-pose hash, coordinate and unit conventions, constraints, target trajectory, solver settings, tests, numeric results, a short demonstration clip, known failure cases and permitted reuse/license metadata.

Suggested first challenge suite:

1. Reach for 20 seeded targets around a stationary torso.
2. Hold three tools with different primary/secondary grip spacing.
3. Stand and walk on five slopes and a moving platform.
4. Look at moving targets while respecting head/neck limits.
5. Retarget a walk and reach onto three different body proportions.
6. Deliberately submit degenerate poles and unreachable targets; require a stable fallback and truthful diagnostic.

Generate candidates, run geometry/animation checks, inspect short clips from multiple views, repair the identified defect, and store only the validated result as a preferred example. A failed attempt can be retained as a labeled counterexample. This connects the user's desired self-improvement loop to observable animation quality instead of unmeasured claims of intelligence.


# Implementation appendix - IK trace schema and examples


The new `star.ik_trace_quality` module is an opt-in offline diagnostic tool. It summarizes observations supplied by the caller. It does not capture Roblox/Blender frames, solve IK, prove animation quality, pass the repository's evaluation gate, promote a candidate, or change runtime settings.

## Invocation

```sh
python -m star.ik_trace_quality trace.json
```

The pure API is `report_ik_trace(payload)` and raises `ValueError` on malformed input. The CLI prints a JSON report and exits 0 for a valid trace; that exit code means validation and reporting succeeded, not that the animation passed a quality threshold. Invalid input exits 2 and produces no report on stdout.

## Complete version-1 schema

| Level | Field | Meaning |
|---|---|---|
| Trace | `schema_version` | Integer 1, not boolean or floating-point 1.0 |
| Trace | `rig_scale` | Finite positive normalization length in the same units as coordinates, within 1e-6..1e6 |
| Trace | `chains` | 1..64 objects with distinct names |
| Chain | `name` | Printable string of 1..128 characters |
| Chain | `samples` | 1..10000 samples, with at most 20000 across the trace |
| Sample | `t` | Seconds in 0..86400, strictly increasing within a chain, with at least 1e-6 seconds between samples; one timestamp ULP is allowed at that boundary |
| Sample | `effector`, `target` | Required xyz arrays, measured in the same consistent coordinate frame |
| Sample | `effector_q`, `target_q` | Optional pair of xyzw quaternions, unit length within 0.001; accepted quaternions are normalized for angular calculations |
| Sample | `contact` | Optional strict boolean; missing means unobserved |
| Sample | `contact_frame` | Optional stable support-local coordinate-frame identifier, string 1..128 printable characters |
| Sample | `contact_position`, `contact_anchor` | Optional xyz observations in that SAME support-local coordinate frame |

The three contact observation fields must either all be present or all absent. They may be present only with `contact: true`. True contact without coordinates is allowed and remains unmeasured for contact geometry. The anchor must remain fixed across adjacent measured samples of a continuous contact on the same support frame. A missing observation, absent/false contact, or changed frame identifier starts a new measured span. Reacquisition can use a different anchor. Never change the frame identifier every sample to hide slip; the module cannot establish the truth of a caller's capture data.

Coordinates must be finite numbers within +/-1e9. Booleans are not numbers. Unknown keys are rejected. The CLI rejects duplicate JSON object keys and NaN/Infinity constants, accepts regular files only, and reads at most 8 MiB. Engine/version/capture provenance belongs in a separate capture record; the schema deliberately does not accept arbitrary opaque metadata.

## What the metrics mean

Distances are divided by `rig_scale`; rates also divide by elapsed seconds. A scale of one meter means a residual of 0.01 is one centimeter. With a character height used as the scale, the same number means 1% of that height. Callers must record their scale convention alongside the capture.

Position residual compares effector and target at each observation. Quaternion residual is the shortest rotational geodesic in degrees; q and -q represent the same rotation. Step displacement, speed, velocity change and acceleration measure the effector in the supplied position frame. They are world-relative only if world-space positions were supplied. They cannot by themselves separate actor motion from support motion.

Contact residual compares the support-local position with its fixed anchor. Drift compares each later observation with the first observed contact position in the current continuous span. Slip speed uses adjacent support-local positions and the actual timestamp interval. One measured contact sample has a residual but cannot measure drift or slip speed. Missing contact geometry produces null metrics, not zero.

Velocity uses each actual adjacent time interval. Acceleration compares consecutive interval velocities divided by the separation between those intervals' midpoints, so unequal sampling intervals are handled explicitly. Angular speed also uses the actual interval, and no angular rate is bridged across a missing quaternion observation.

Angular displacement follows the shortest arc between sampled orientations. Sparse observations can hide a rotation greater than 180 degrees or a complete revolution; the module cannot recover motion that was not captured. Sampling coverage and engine provenance remain separate requirements.

Each metric reports `samples`, `mean`, `rms`, `p95` (nearest rank), and `max`. Statistics weight observations equally; they are not time-weighted integrals. Missing metrics have `samples: 0` and null numeric fields. The report always includes `engine_capture_verified: false` and `quality_proven: false`.

## Synthetic example 1: translating platform, planted foot

```json
{
  "schema_version": 1,
  "rig_scale": 1.0,
  "chains": [
    {
      "name": "left_foot",
      "samples": [
        {
          "t": 0.0,
          "effector": [0.0, 0.0, 0.0],
          "target": [0.0, 0.0, 0.0],
          "contact": true,
          "contact_frame": "platform_A_local",
          "contact_position": [0.0, 0.0, 0.0],
          "contact_anchor": [0.0, 0.0, 0.0]
        },
        {
          "t": 1.0,
          "effector": [1.0, 0.0, 0.0],
          "target": [1.0, 0.0, 0.0],
          "contact": true,
          "contact_frame": "platform_A_local",
          "contact_position": [0.0, 0.0, 0.0],
          "contact_anchor": [0.0, 0.0, 0.0]
        }
      ]
    }
  ]
}
```

Expected: positional residual 0; supplied-frame speed 1 rig unit/second; contact residual, drift and slip speed 0; orientation and acceleration unmeasured. This distinction prevents a correctly planted foot on a moving platform from being counted as sliding solely because it moves through world space.

## Synthetic example 2: irregular sampling of quadratic motion

With `rig_scale: 1`, times `[0, 1, 3]` and effector x positions `[0, 1, 9]`, interval speeds are `[1, 4]`. Velocity midpoints are at `[0.5, 2]`, so estimated acceleration is `(4-1)/(2-0.5) = 2` rig units/second squared. An assumed fixed frame rate would give a different and incorrect diagnostic for this trace.

## Synthetic example 3: contact reacquisition

| Time | Contact | Support-local position x | Anchor x | Interpretation |
|---:|---|---:|---:|---|
| 0 | true | 0 | 0 | First measured span starts |
| 1 | true | 0.1 | 0 | Drift 0.1 |
| 2 | false | omitted | omitted | Contact ends |
| 3 | true | 100 | 100 | New span starts, new anchor permitted |
| 4 | true | 100.2 | 100 | Drift 0.2 in the new span |

Expected: two measured spans and maximum within-span drift approximately 0.2. There is no 99.9-unit contact slip measurement across the swing/reacquisition gap. If time 2 instead says `contact: true` but omits all support observations, coverage is missing and the measured spans are likewise separate; the module cannot establish what happened during the gap.

## Validation completed in this environment

`benchmarks/verify_ik_trace_synthetic.py` ran 41 synthetic check groups successfully, including normalized positional error, nulls for missing observations, unequal timestamps, analytic acceleration, quaternion equivalence and angular rates, moving-platform coordinates, contact reacquisition, malformed input, numeric bounds, duplicate JSON keys and the byte-limited CLI. The script does not modify repository tests or evaluation fixtures. The independently authored `benchmarks/verify_ik_trace.py` contains 34 unittest methods. Both suites were rerun successfully on the final module. Their coverage overlaps; do not add the counts as unique cases. The independent script includes 25 seeded translation/scaling trials.

The independent `research/ik_independent_review.py` passed 34 unittest methods, including 25 seeded coordinate translation/scaling trials. Its report is `research/ik_review.md`. It also verified that a microsecond interval at a high timestamp is accepted within the stated ULP tolerance, a half-microsecond interval is rejected, and a FIFO input is rejected immediately.

No engine frame capture, real avatar, Roblox multiplayer session, Blender rig, packaged Windows executable or sealed evaluation was tested. These results establish only the exercised mathematical/schema behaviors of this new diagnostic module.

## Reproduce the committed developer checks

```sh
python benchmarks/verify_ik_trace.py -v
python benchmarks/verify_ik_trace_synthetic.py
python -m star.ik_trace_quality docs/research/examples/ik-moving-platform.synthetic.json
```

The example is deliberately synthetic. The checks are isolated developer validation of this diagnostic; they do not replace protected repository graders or activate a runtime feature.


# Validation record

The final diagnostic was validated with two independently written offline check scripts. Coverage overlaps, so counts are reported separately. These are mathematical/schema checks on supplied or synthetic data, not native engine measurements.

```json
{
  "research_date": "2026-10-31",
  "timezone": "America/Chicago",
  "repository": "oncoursemail/Star-AI-Project",
  "base_branch": "star/next",
  "base_commit": "a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f",
  "module": "star/ik_trace_quality.py",
  "module_sha256": "a2d29c57eea272770c41610837cd4fcd0f21b55b64f27c8fa1457c301f0defa2",
  "independent_check_script": "benchmarks/verify_ik_trace.py",
  "independent_check_script_sha256": "cef3e36be9ca9af3e29bb577301b0a7f4d456b1d3a9397e089c59ecd2db475e1",
  "environment": {
    "python": "3.12.14",
    "system": "Linux",
    "machine": "x86_64"
  },
  "executed": {
    "independent_unittest_methods": 34,
    "seeded_translation_scale_trials": 25,
    "independent_suite_result": "passed",
    "independent_suite_seconds": 0.427,
    "implementation_author_synthetic_check_groups": 41,
    "synthetic_suite_result": "passed",
    "coverage_overlaps_do_not_sum_counts": true,
    "targeted_python_compilation": "passed",
    "python_module_cli_synthetic_example": "passed",
    "moving_platform_example": {
      "supplied_frame_speed_rig_per_second": 1.0,
      "contact_slip_speed_rig_per_second": 0.0,
      "orientation_unmeasured": true,
      "engine_capture_verified": false,
      "quality_proven": false
    }
  },
  "review_fixes": [
    "ULP-aware microsecond timestamp boundary while requiring positive elapsed time",
    "regular-file checks with nonblocking open and descriptor recheck to reject FIFOs"
  ],
  "not_run": [
    "Full repository test suite (sparse inspected snapshot; pytest and application dependencies unavailable)",
    "Roblox Studio capture or multiplayer acceptance",
    "Blender rig/export acceptance",
    "Windows packaged executable smoke test",
    "Sealed model evaluation",
    "Target-machine inference or animation performance benchmark"
  ],
  "runtime_changed": false,
  "dependencies_added": false,
  "protected_existing_tests_or_baselines_changed": false,
  "timing_scope": "Developer check duration in this environment; not Litha inference, IK solving, or native frame latency",
  "synthetic_check_script": "benchmarks/verify_ik_trace_synthetic.py",
  "synthetic_check_script_sha256": "4f36d8405e9dadd2aab0e10680d7e1ced4e06d48ba0cbc8ebc34f308753edb41"
}
```

