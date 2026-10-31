# STAR: OMP, Mobbin, and the next improvements that can earn their cost

Research date: **22 October 2026, America/Chicago**. Implementation baseline:
`oncoursemail/Star-AI-Private`, `main` at
`80bf8540b75633c065437036baf75614afe68f74`.

## Decision

Use **Oh My Pi (OMP)** as a candidate coding worker and **Mobbin** as an optional,
on-demand design-reference source. Keep STAR's chat, project context, provider
selection, design identity, verification and reviewed learning as the product's
control layer. Measure completed work before making any claim of greater speed
or intelligence.

The practical goal is a connected workflow: understand the task and project,
retrieve the right evidence, propose a scoped change, run the relevant checks,
inspect the actual result, and retain only supported lessons from eligible
material. A larger list of installed agents does not establish that workflow.

This branch is a **candidate implementation and research package**. It is not a
desktop release, a live Mobbin account connection, a model upgrade, or an enabled
general-purpose OMP editing service. See the implementation and validation
sections below for the exact boundary.

## Existing STAR capabilities to reuse

The inspected source already contains these foundations:

| Foundation | Current code | Integration implication |
|---|---|---|
| External-agent discovery | `star/agent_ecosystem.py` | Add OMP here; catalog membership does not launch a process. |
| Dependency and ownership planning | `star/orchestration.py`, `star/agent_runtime.py` | Reuse task IDs, dependency failure handling, budgets and resumable records. |
| Real model workforce | `star/conductor_fleet.py` | Already makes bounded provider calls with receipts; its workers have no tools. |
| Resource planning | `star/agent_resource_planner.py` | Account for shared hardware before adding simultaneous workers. |
| MCP discovery and curated calls | `star/mcp_registry.py`, `star/mcp_connections.py` | Current connector intentionally excludes OAuth and image responses. |
| Portable skill references | `star/agent_skills.py` | Read selected skill text as reference; do not execute downloaded scripts. |
| Design identity and checks | `star/design_system.py`, `star/design_md.py`, `star/design_db.py` | Preserve STAR tokens, hierarchy and contrast checks. |
| Actual browser inspection | `frontend/scripts/visual-audit.mjs` | Already uses Playwright and axe-core; extend scenario coverage. |
| Learning and verification | `star/lessons.py`, `star/skill_evolution_lab.py`, existing evaluation gate | New tools do not authorize their own lessons, grades or promotion. |

Open work was inspected before editing. In particular, the `star/next` merge
train (#514) contains an ACP adapter and agent fleet, debugger work (#502),
research work (#494), and other ongoing capabilities. New bulk-task (#512),
speed (#556) and Night School evidence (#558) work also remains relevant.
Those branches are not debris and their capabilities must not be represented
as already shipped. The initial files here avoid modifying their active
desktop, authentication, workflow or evaluation paths.

## What OMP offers

OMP is the MIT-licensed Oh My Pi coding-agent project from Stencil Labs, derived
from Pi. It exposes a CLI, TypeScript embedding, ACP, and JSONL RPC. The inspected
release is **v18.12.6**, commit
`45c35e40c46166dc726ccc52f5d27f40f2449f99`. The optional Python package is
`omp-rpc` (import `omp_rpc`), version 0.1.0, Python 3.11+, currently classified
Alpha. Pin the CLI and client together. [O1] [O2]

### Why it is a good candidate for STAR

**Symbol-aware work.** OMP can ask installed language servers for definitions,
references, diagnostics, renames and file-move fixes. That is useful when a change
affects a real declaration across Python or TypeScript files. Start at the
correct project root and verify the actual language server is installed. [O3]

**Structural changes.** Its editing tools can stage syntax-based transformations
and protect edits against stale content. Structural matching still cannot prove
that two same-spelled functions have the same identity; use language-server
information when bindings matter. After any change, inspect the diff and run
the relevant compiler or tests. [O4]

**Runtime debugging.** DAP support can drive installed debug adapters, including
Python and Node adapters, to stop a reproduction and inspect state. A debugger
launch or expression evaluation executes code; it needs the same deliberate
development-process boundary as other execution. [O5]

**Local model compatibility.** Official custom-provider documentation covers
Ollama, llama.cpp and LM Studio, plus explicit compatible endpoints. STAR can
retain its local-first behavior. Model quality, real context capacity and
hardware throughput remain separate questions that require measurement. [O6]

**Worker roles.** OMP distinguishes model selection from reusable specialist
behavior. This fits STAR's existing planner: investigation, implementation and
review can have different budgets and routes. A specialist name itself is not
evidence of competence or independent review. [O7]

### Integration contract

Prefer the official Python RPC client over implementing a second framing and
request-correlation stack. Its release documentation covers protocol-v2
negotiation, a correlated `prompt_result`, and `session_settled`. A prompt
acknowledgement means it was accepted; it does not mean background work is done
or tests passed. Rolling website examples and release code differ here, so
the pinned release is the contract for this candidate. [O2] [O8]

The host should eventually expose one bounded worker result with distinct
fields for transport completion, model output, tool observations, verified
checks, elapsed time and upstream version. Tool reports from an agent are
claims until STAR independently observes the relevant files or test process.
Do not count two reports of the same run as independent evidence.

There are concrete integration hazards to resolve before full editing:

- OMP's documented default approval mode is `yolo`; an integration must choose
  an explicit mode and actual capability boundary. [O9]
- Built-in tool selection does not prove that extensions, hooks, MCP discovery,
  local configurations and child processes are absent. [O9] [O10]
- A profile or a Git worktree separates configuration or edits; neither is an
  operating-system sandbox.
- The inspected Python client's process launch merges its provided environment
  over `os.environ`. Passing a short mapping therefore does not remove ambient
  credentials. A clean-environment supervisor must own that boundary. Its
  Windows cleanup also needs separate descendant-process verification. [O2]

The release code makes the tool-selection gap specific: `main.ts` maps
`--no-tools` to `toolNames=[]`, while `sdk.ts` can still enable MCP when
`restrictToolNames` is false and `enableMCP` is unspecified. The CLI does not
expose the SDK's hard MCP-disable/restricted-session controls. A live worker
therefore needs a reviewed supervisor, explicit discovery controls and a
validated zero-tool inventory for its initial text-only mode. This branch
does not include that launcher. The next implementation must either obtain an
upstream-supported RPC control for those settings or enforce them through an
SDK-based host; existing CLI flags cannot be assumed to provide it. [O12] [O13] [O14]

Do not solve these by silently weakening STAR policy or adding a blanket
permission callback to the existing ACP pilot.

## What Mobbin offers

The official organization has two relevant maintained integration repositories:
`mobbin/skills` and `mobbin/mobbin-mcp-server`. The `cmdk` and `sonner` forks shown
in that organization are archived. The skills repository includes
`best-practices`, `search`, `redesign-screen` and `plain-writing`. Its pinned
revision for this research is
`1eda2331cecc3f0e55a9c82ae375a8313652d01e` (plugin 1.5.0). [M1]

The useful design method is to understand the screen's job, choose relevant
references, preserve the product's own visual language and inspect the rendered
result. STAR should adapt that method to its existing components. The upstream
skills are reference material, not authority to change STAR permissions or to
require a new interaction script from the owner. [M2]

### MCP and REST are different access paths

| Route | Access | Contract | State in this branch |
|---|---|---|---|
| Hosted MCP | Pro, Team or Enterprise; per-user OAuth | `https://api.mobbin.com/mcp`, Streamable HTTP | Design for follow-on OAuth/image integration; not connected. |
| REST screen search | Team or Enterprise; workspace API key | `POST https://api.mobbin.com/v1/screens/search` | Separate opt-in client candidate with offline request/response tests. |

MCP exposes screen, flow and website-section searches, plus saved collections.
Returned items include visual previews and expiring image URLs. An MCP Apps
gallery requires supporting client functionality; merely listing the endpoint
in STAR does not create a gallery. [M3] [M4]

Custom-app OAuth uses resource/authorization metadata discovery, Dynamic Client
Registration, PKCE S256, an `openid` authorization request, and per-user tokens.
Mobbin recommends an MCP SDK for the flow. This should be implemented as a
reviewed authentication change with secure token storage and revocation, not
an unvalidated token field in a chat prompt. [M5]

REST requests explicitly select `mode: standard` and `image_quality: optimized`.
The public REST schema otherwise defaults mode to deep. The initial client uses
small result/query budgets and performs no retries automatically. The provider
documents 60 requests per 60 seconds per MCP user or REST workspace and supplies
`Retry-After` on HTTP 429. The client budget is per instance; it is not a
workspace-wide rate limiter. [M6] [M7] [M10]

Open-source repository licensing does not make the hosted catalog free. Mobbin
documents paid plan access; its website/MCP credit guidance distinguishes
standard searches from credit-consuming deep searches. This report does not
claim REST calls are free or that beta overage terms are permanent. [M5] [M8]

### Reference use and learning must remain separate

Mobbin's current terms allow proprietary-product API/MCP integrations while
restricting model training/testing/indexing/benchmarking and standalone mirrored
repositories of its content. This implementation uses on-demand references with
attribution, not a training corpus or a local copy of Mobbin. [M9]

The reference client retains no disk cache and does not fetch images. Its
provenance fields identify returned material as untrusted and ineligible for
training, indexing and evaluation. Those fields are a contract for downstream
consumers, not magic enforcement if a future caller discards them. Full desktop
integration must preserve that boundary when displaying, saving or logging
responses. The developer CLI prints results, so redirecting its output can
persist them even though the adapter itself does not write a cache.

STAR's personal taste memory should use the owner's own authorized work and
explicit feedback: original STAR/Metallic screens, approved component decisions,
and statements about spacing, alignment, density, color and motion. Do not
launder third-party reference screens into a lesson by summarizing them.

## The design workflow STAR should gain

This is a proposed product workflow, not an already enabled tool recipe.

1. **Describe the job.** For example: understand a server's health, pick a
   project, stop a running task, or read a long chat. Name the specific problem.
2. **Inspect the current screen.** Retain its real layout, components, available
   states and existing design tokens. A screenshot alone does not describe all
   interactions.
3. **Retrieve a small reference set.** Search by task and platform. Record what
   each source helps answer; omit irrelevant results.
4. **Make a STAR-owned decision.** Specify hierarchy, density, alignment,
   typography, state transitions and the main action. Use STAR's OLED black and
   restrained warm gold where appropriate. Avoid ornamental circles, generic
   dashboard cards and extra text that serves no task.
5. **Implement with existing components.** Feed tokens and decisions into
   `DESIGN.md` checks. Keep editor outputs editable. References inform the
   structure; STAR's product identity determines the result.
6. **Render and interact.** Inspect real screens with long labels, error/loading
   states, keyboard input, scrolling, resizing and reduced motion. Capture
   failures with actionable context.
7. **Learn from eligible evidence.** Store the owner's explicit preference and
   verified results of STAR's own work through the existing lesson process.

Automated contrast and layout checks can find defects. A passing screenshot
comparison establishes consistency with a chosen baseline, not artistic quality
or usability. Human visual judgment remains relevant. [V1] [V2]

## Ten additional improvements, in implementation order

These are proposals to evaluate. They are not claims that the features below
were enabled by this branch or that nobody has proposed similar ideas before.

### 1. Finish the actual visual feedback loop

Extend the existing Playwright/axe audit with task-specific empty, loading,
error, long-content, cancellation and keyboard states. Keep browser, fonts and
viewport consistent for comparisons. Record both screenshot defects and
interaction defects. Retain a trace on failure so the next repair sees actions,
DOM state and console/network evidence. [V1] [V2] [V3]

For the owner, this means STAR should notice an incorrectly aligned icon or a
clipped control before presenting the result. For developers, the metric is
defects caught and time to reproduce, not an invented aesthetic score.

### 2. Read documentation for the installed dependency version

Read the project's lockfile, identify the exact package/API question, retrieve
versioned official material, then compile or test the proposed usage. Context7
is a useful optional source, with `resolve-library-id` and `query-docs`; its API
also supports version requests. Missing or unverified version coverage must be
recorded rather than treated as an exact match. [D1] [D2]

Keep the existing Roblox documentation/API-dump path for Roblox questions. Add
general library grounding beside it. Measure wrong-version errors and first
attempt API correctness. Retrieval can still return incomplete or wrong
material; source presence alone is not verification.

### 3. Use the correct edit mechanism

Choose plain-text edits for a small known location, AST matching for a syntactic
pattern, and language-server operations for symbol identity. Combine those
with base hashes and file ownership to prevent another worker's newer changes
from being overwritten. ast-grep can help with structural migrations, but its
FAQ explicitly excludes type/scope/data-flow analysis. [S1] [S2]

A useful trial is a deprecated React prop migration with similarly named local
symbols deliberately present. Success means the intended uses change, unrelated
symbols remain correct, and the existing tests/types pass.

### 4. Investigate failures with a real reproduction

Connect OMP's DAP support to STAR's existing debugger evidence work. Capture a
specific failing input, bounded stack and relevant values, state the hypothesis,
then rerun that same reproduction after the fix. Compare Microsoft DebugMCP as
an alternative implementation reference before adding another persistent
debugging service. [O5] [G1]

Measure time to a verified fix and recurring defects. Do not let a debugger
attach automatically to production services or treat evaluated expressions as
read-only observation.

### 5. Show where the time goes

Extend existing local analytics with a connected trace across queueing,
retrieval, first-token delay, generation, tools, repair and verification. An
optional OpenTelemetry exporter can connect these spans to an owner-controlled
collector. Its GenAI guidance treats content capture as opt-in; use bounded
metadata by default. [T1]

This lets STAR explain a slow task and optimize the actual bottleneck. A faster
model does not help if most of the time is queue wait or repeated tool retries.
Track p50/p95 verified-task time and foreground delay under background load.

### 6. Route by observed task performance

Build on the existing router, provider receipts and resource planner. Keep a
local scorecard by task family, model version and tool configuration. Compare
candidate routes in shadow runs before promotion. Use inexpensive local routes
for tasks they reliably solve and escalate only where measured benefit justifies
the time or cost.

RouteLLM is relevant research, but its documented default matrix-factorization
and ranking routes use OpenAI embeddings. It should not be installed with that
default and described as entirely local. Its reported savings are not evidence
about STAR's workload. [R1]

### 7. Remember why an approach failed

Extend the reviewed lesson record with the attempted approach, failure evidence,
verified correction and applicability conditions. On a similar task, retrieve
the failure and its scope before repeating the same operation. Distinguish
"the checker was unavailable" from "the code failed"; retries on one task are
not independent demonstrations of transfer.

Use the existing Night School and evidence work instead of a parallel memory
database. An old failure is a hint to investigate, not a prohibition against a
technique that may now be appropriate.

### 8. Preserve design preferences at the affected part

An owner-approved screen should support region-level feedback such as "keep
this compact composer" or "the button label is too faint". Store the original
artifact, the owner's words and the relevant component/version. Retrieve a
small set when that component is changed later.

This is more useful than a global instruction to "make it premium". Track
repeated preference violations and first-draft acceptance without treating one
accepted screen as permission to restyle every project.

### 9. Give every specialist a narrow task package

The planner should send the exact question, relevant files/symbols, applicable
constraints and a completion check. Preserve dependency findings and source
links. Limit overlapping writes and keep one foreground model slot available
when background work competes for the same machine.

Extra workers are justified by independent work, not by a target agent count.
A second model that repeats the first model's unsupported assertion is not
independent verification.

### 10. Recover with evidence after interruption

Bind checkpoints to task ID, input revision, proposed diff and observed command
status. After a crash, reconcile actual process/file state before resuming.
Preserve an unknown outcome when the host lost contact during a write. Repeating
a mutating action without reconciliation can duplicate work or damage state.

OMP session support is useful infrastructure, but STAR still needs task-level
recovery logic and process supervision on its actual Windows/Linux hosts. [O11]

## Acceptance plan

Run the same eligible tasks against baseline STAR and each candidate separately:
baseline, OMP assistance, reference-backed design workflow, then the combined
workflow. Keep model, input revision and budget explicit so changes can be
attributed. Use STAR-owned or appropriately licensed tasks and original designs;
do not use Mobbin catalog content as evaluation data.

| Task family | Evidence to collect |
|---|---|
| Python bug repair | Original reproduction, changed diff, independent test result, time. |
| TypeScript refactor | Target symbol, impacted references, compiler/test results, unwanted changes. |
| STAR UI correction | Original and resulting STAR screen, interaction results, owner's judgment. |
| Roblox/Luau work | Existing API/static checks and authorized Studio evidence where available. |
| Recovery/cancellation | Acknowledged stop, remaining processes, file state, resumed-task status. |
| Performance | First useful output, full verified-task duration, retries, tokens, resource pressure. |

Keep protected evaluation fixtures, graders, baselines and promotion logic under
their existing ownership. The repository's `AGENTS.md` requires evaluation
approval before activating changed tool/prompt/routing recipes and independent
review for authentication/policy/workflows. Offline adapter tests cannot replace
that gate or a real Windows and model-backed trial.

## Implementation and validation

| File | Implemented behavior | Boundary |
|---|---|---|
| `star/agent_ecosystem.py` | Adds OMP to the optional agent catalog. | Discovery does not install or launch a worker. |
| `requirements-omp.txt` | Pins the official Python SDK to the inspected upstream commit. | Optional dependency file; the SDK and matching CLI were not installed. |
| `star/omp_worker.py` | Checks installation metadata, prepares bounded explicit-text requests, and inspects supplied dechunked RPC captures. | No process launcher, transport, file access or live model call; results explicitly say `executed_by_star=False`. |
| `star/mobbin_reference.py` | Executes opt-in REST screen searches with an explicit key, fixed endpoint, bounded response and query limits. | No OAuth, desktop gallery, automatic image fetching, disk cache or learning ingestion. |
| `tests/test_omp_worker.py` | Exercises preparation, correlation, completion, interruption, tool rejection and malformed captures. | Offline protocol-boundary checks. |
| `tests/test_mobbin_reference.py` | Exercises exact requests, errors, limits, cancellation and malformed responses. | HTTP transport is mocked; no account entitlement or live availability claim. |

The candidate does not activate new desktop tools or alter model routing,
authentication settings, learning gates, release workflows or live services.

### Developer usage

OMP preparation is deliberately explicit and offline:

```python
from star.omp_worker import OmpReviewConfig, preflight, prepare_review

config = OmpReviewConfig(enabled=True, provider="ollama", model="your-installed-model")
status = preflight(config)
request = prepare_review("Review this supplied code: ...", config)
assert status.runtime_available is False
assert request.runtime_available is False
```

The provider/model strings above are placeholders for a future caller's actual
configuration. This code does not invoke them. `inspect_capture()` consumes a
single-prompt lifecycle capture window after SDK startup/configuration, already
dechunked by the official SDK. It rejects unsupported command responses, so an
entire startup transcript is not a valid input. It does not connect to OMP or
authenticate the origin of a supplied capture. Even a `completed` result is
captured model output, not evidence that STAR ran a check. Truncated responses
remain incomplete even when upstream reports that the prompt has finished.

Mobbin's developer CLI remains disabled without an explicit flag:

```bash
python -m star.mobbin_reference --query "developer settings screen" --platform web
```

That command returns a structured `disabled` result without sending a request.
For an intentional live request, supply the Team/Enterprise workspace key in
`STAR_MOBBIN_API_KEY` through the caller's credential mechanism and add
`--enabled`. Do not put a key in source or in the query. The library form accepts
an explicit key and does not read the environment on import. Each client permits
one in-flight request, counts attempts against its budget and does not retry.
Authentication, permission and rate-limit refusals latch that instance closed.

### Verification recorded for this candidate

```text
python -m pytest -q tests/test_agent_ecosystem.py tests/test_mobbin_reference.py tests/test_omp_worker.py
176 passed

ruff check star/agent_ecosystem.py star/mobbin_reference.py star/omp_worker.py tests/test_mobbin_reference.py tests/test_omp_worker.py
All checks passed!
```

These commands used an isolated Python 3.12 environment with HTTPX 0.28.1,
pytest 9.1.1 and Ruff 0.17.2. The targeted tests cover 27 existing catalog tests,
67 new Mobbin tests and 82 new OMP tests. They are regression evidence for the
candidate code, not a measurement of intelligence, design quality or latency.

The repository's pinned Pyright 1.1.414 check was also run against a separate,
empty Python 3.12 environment. Its existing baseline gate passed with **433
known errors, none new**. An initial CI finding about narrowing the validated
`mode` string to its literal type was fixed in the source. The baseline and
type-checking configuration were not changed.

The final PR description records commands actually run and their results. Live
Mobbin authentication/entitlement, native Windows behavior, full OMP editing,
model quality improvement and end-to-end speed gains remain unverified unless
explicit evidence is added in a later review.

## Primary sources

- [O1 — OMP repository and installation](https://github.com/can1357/oh-my-pi)
- [O2 — Python SDK at the inspected release](https://github.com/can1357/oh-my-pi/tree/45c35e40c46166dc726ccc52f5d27f40f2449f99/sdk/python/omp-rpc)
- [O3 — Code intelligence](https://omp.sh/docs/code-intelligence)
- [O4 — Structural editing](https://omp.sh/docs/editing)
- [O5 — Debugging](https://omp.sh/docs/debugging)
- [O6 — Local and custom models](https://omp.sh/docs/custom-models)
- [O7 — Agents and model roles](https://omp.sh/docs/agents-and-roles)
- [O8 — RPC](https://omp.sh/docs/rpc)
- [O9 — Tool approvals](https://omp.sh/docs/approvals)
- [O10 — MCP integration and discovery](https://omp.sh/docs/mcp)
- [O11 — Sessions](https://omp.sh/docs/sessions)
- [O12 — CLI session options at inspected release](https://github.com/can1357/oh-my-pi/blob/45c35e40c46166dc726ccc52f5d27f40f2449f99/packages/coding-agent/src/main.ts)
- [O13 — SDK MCP defaults at inspected release](https://github.com/can1357/oh-my-pi/blob/45c35e40c46166dc726ccc52f5d27f40f2449f99/packages/coding-agent/src/sdk.ts)
- [O14 — CLI arguments at inspected release](https://github.com/can1357/oh-my-pi/blob/45c35e40c46166dc726ccc52f5d27f40f2449f99/packages/coding-agent/src/cli/args.ts)
- [M1 — Official Mobbin organization](https://github.com/mobbin)
- [M2 — Official Mobbin skills at inspected revision](https://github.com/mobbin/skills/tree/1eda2331cecc3f0e55a9c82ae375a8313652d01e)
- [M3 — Official remote MCP server](https://github.com/mobbin/mobbin-mcp-server)
- [M4 — MCP tools and images](https://docs.mobbin.com/mcp/features)
- [M5 — Custom integration and OAuth](https://docs.mobbin.com/mcp/build-an-integration)
- [M6 — REST quick start](https://docs.mobbin.com/api/quickstart)
- [M7 — Rate limits](https://docs.mobbin.com/rate-limits)
- [M8 — AI credit behavior](https://docs.mobbin.com/ai-credits)
- [M9 — Content-use terms](https://mobbin.com/terms)
- [M10 — Exact REST search schema](https://docs.mobbin.com/api-reference/screens/search-screens-with-natural-language)
- [V1 — Playwright visual comparisons](https://playwright.dev/docs/test-snapshots)
- [V2 — axe-core](https://github.com/dequelabs/axe-core)
- [V3 — Playwright traces](https://playwright.dev/docs/trace-viewer)
- [D1 — Context7 API guide](https://context7.com/docs/api-guide)
- [D2 — Context7 version verification behavior](https://context7.com/docs/api-reference/search/search-documentation-in-one-request)
- [S1 — ast-grep rewrites](https://ast-grep.github.io/guide/rewrite-code.html)
- [S2 — ast-grep limits](https://ast-grep.github.io/advanced/faq.html)
- [G1 — Microsoft DebugMCP](https://github.com/microsoft/DebugMCP)
- [T1 — OpenTelemetry GenAI observability](https://opentelemetry.io/blog/2026/genai-observability/)
- [R1 — RouteLLM implementation and evaluation](https://github.com/lm-sys/RouteLLM)
