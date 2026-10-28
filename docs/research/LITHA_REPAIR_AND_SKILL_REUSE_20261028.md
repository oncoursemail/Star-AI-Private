# Litha repair and procedural reuse

Research/design snapshot: 2026-10-28. This note proposes improvements to `server/mesh`, not launcher UI.
The parallel repair candidate is under implementation. This note reports no candidate test results, deployment, performance measurements or model-quality gains.

## What the sources actually implement

| Source | Implemented mechanism | Limit on applying it to Litha |
| --- | --- | --- |
| Nous Research Hermes Agent | On-demand procedural documents; metadata listing, selected skill body and optional reference loading. `skill_manage` creates or changes skills. An optional write-approval setting stages writes for review; it is separate from content scanning. | Saving instructions does not establish that the procedure worked. These mechanisms do not establish weight training, human understanding or correct game creation. |
| Voyager | A reusable code library, description-based retrieval, iterative execution feedback and an LLM success critic before adding skills. | Minecraft simulation results and the critic's judgment do not prove arbitrary program correctness. |
| LILO | Synthesis, symbolic compression and documentation of reusable abstractions, evaluated in constrained program-synthesis domains. | Matching input/output examples does not guarantee unseen behavior or transfer to a production game engine. |
| GEPA | Reflection over execution/evaluation traces, proposed text updates and evaluation-based candidate selection. | An optimizer can overfit its feedback or optimize an incomplete metric. Prompt changes require STAR's existing independent gate. |

Sources: [Hermes skills](https://hermes-agent.nousresearch.com/docs/user-guide/features/skills),
[Hermes write-approval implementation](https://github.com/NousResearch/hermes-agent/blob/main/tools/write_approval.py),
[Voyager, sections 2.2-2.3](https://arxiv.org/html/2305.16291),
[LILO, sections 2-3](https://arxiv.org/html/2310.19791),
[GEPA paper](https://arxiv.org/abs/2507.19457) and [official implementation](https://github.com/gepa-ai/gepa).
These are existing research directions. Litha should describe an adaptation rather than claim to invent procedural memory, library learning or reflective optimization.
Hermes's documented features above already exist upstream; the Litha roadmap below is our proposal, not an announced Nous roadmap.

## Existing Litha boundary

`server/mesh/instant.py` already supplies an answer cache and reference-answer grounding.
Its request filters deliberately exclude owner code and error text. Broadening that answer cache into an automatic code replacement mechanism would change its contract.
`server/mesh/verify/core.py` already checks blocks and performs bounded model-assisted repair, retaining placeholder checks and rechecking replacements.
Coverage varies: Python compilation checks syntax/context without execution; JSON checks grammar and duplicate ambiguity; Luau/API, C# and Minecraft checks have their own limits.
`syntax_checked`, legacy domain `checked`, errors and warnings must remain distinct. A clean report is evidence only for the checks actually performed.

## Current candidate: bounded multi-block repair

Parallel model calls remain opt-in. The default worker count is one; operators may configure one to four workers.
The candidate shares a capacity limit across requests and times out capacity acquisition rather than creating unlimited remote work.
Only generation runs concurrently. Workers return outcomes and timings; the coordinator validates every replacement against its original block in deterministic order.
It preserves local filename/pack context, source bounds, placeholders, rejection of non-improving repairs and final whole-answer rechecking.

Within one request and one round, identical complete model messages and generation settings may share one model call.
Each recipient block still receives its own validation. Coalescing by code alone or diagnostic category is insufficient.
The next round starts fresh, including after failure: stochastic or failed answers must not become a cross-round response cache.
This design does not persist owner source or share repair content across users.

A timeout or cancelled future does not prove that an already running `urllib` request stopped remotely.
Capacity must remain owned until the underlying call finishes, with cleanup in `finally`; late results must not alter a completed response.
Report model-call count, coalesced-block count, elapsed repair time and summed model-call durations separately.
Concurrent calls can make summed durations exceed elapsed time without implying faster generation.

Client concurrency does not create additional GPU capacity. llama.cpp exposes inference slots and continuous batching; its server shares a decode batch across slots.
With a single inference slot on an RTX 4060, extra requests can queue. More slots can change memory demand and per-request latency.
Keep the serial default until measurements on the actual model, server settings and workload justify another choice.
Sources: [official server options](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)
and [server batching architecture](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README-dev.md).

## Testable next steps for game scripts

1. Validate the repair coordinator with synthetic failures: duplicate prompts, different filename contexts, out-of-order replies, capacity exhaustion, timeouts, partial failures and fresh later-round attempts. Compare serial and parallel outputs under an injected deterministic model. Use new standalone checks; leave protected evaluation fixtures and baselines unchanged.
2. Measure complete multi-block repair on an owner-authorized backend. Record workload, model revision, serving slots, concurrency, token counts, elapsed time, memory observations and unresolved diagnostics. Compare equal workloads; a shorter fake delay is not native inference evidence.
3. Add behavior evidence separately. An authorized engine adapter should report engine/version, exact artifact hash, checker identity and concrete outcomes. Examples include server/client authority for a Roblox interaction, bounded reward application, Unity scene lifecycle, or Minecraft command behavior. Compilation alone cannot establish these outcomes.
4. Review the result in the target engine using owner-selected test projects and existing permissions. Check startup, missing assets, lifecycle cleanup, persistence and multiplayer behavior where relevant. Keep generated Luau within STAR's authorized server sandbox; this proposal adds no unrestricted local execution.
5. Review visuals separately: layout, animation, camera, readable UI and approved asset identity. Record the reviewed artifact and conditions. Visual approval does not substitute for behavior checks, and behavior checks do not establish artistic quality.
6. After those boundaries work, consider request-local reuse of successful repairs. Revalidate each reuse under the receiving block's context. A later persistent library needs explicit owner retention settings, project isolation, bounded storage and provenance before capture or retrieval is enabled.

For a future stored recipe, retain its source, language, engine/API version, artifact hashes and exact coverage receipt.
Separate a syntax-checked candidate from a behavior-tested procedure. Recheck stale recipes and treat retrieved bodies as untrusted reference data with no authority to grant permissions.
Use compact metadata to choose relevant recipes, then load a bounded body only when needed, following Hermes's progressive disclosure pattern.
Any broader learning or prompt optimization remains a separately reviewed candidate under STAR's existing evaluation/promotion rules.
No stage in this roadmap establishes a perfect game, universal coding ability, consciousness or guaranteed correctness.

## Reuse and licensing

This note cites mechanisms; it imports no upstream code, packages, models, skills or datasets.
[Hermes](https://github.com/NousResearch/hermes-agent/blob/main/LICENSE),
[Voyager](https://github.com/MineDojo/Voyager/blob/main/LICENSE),
[GEPA](https://github.com/gepa-ai/gepa/blob/main/LICENSE) and
[llama.cpp](https://github.com/ggml-org/llama.cpp/blob/master/LICENSE) publish permissive MIT license terms requiring notice preservation when applicable.
The inspected [LILO repository](https://github.com/gabegrand/lilo) did not expose a root `LICENSE` or `LICENSE.md` at the queried paths; do not infer permission to copy its code.
Review the exact pinned revision, submodules, datasets and model terms independently before redistribution. A paper's availability does not license every associated artifact.
