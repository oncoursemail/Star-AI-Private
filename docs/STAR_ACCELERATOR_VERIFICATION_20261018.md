# STAR Accelerator Lab — measured latency, animation QA, and public-data research

**2026-10-18 | Experimental review-branch implementation; not a new AGI model or public release.**

This patch extends STAR's existing Python components without replacing model selection, security policy, resource planner, inference service, Studio Test Farm, Blender bridge, or evaluation gates. All modules are opt-in, do not run at app startup, and do not auto-modify settings or publish assets. Dashboard and agent-tool wiring are subsequent reviewed tasks.

## What is already in STAR and what to do next

| Objective | Existing module | Evidence-grounded upgrade | Proving it worked |
| --- | --- | --- | --- |
| Fast first token | star/brain_benchmark.py, star/instant_route.py, star/prefill_warm.py | Use fixed prefixes and benchmark supported llama.cpp cache, prompt reuse and slot settings independently | Real p50/p95 time-to-first-token (TTFT), warm/cold response, memory footprint and failures |
| High model throughput | star/model_fleet.py, STAR Server | Try llama.cpp continuous batching. Compare vLLM prefix caching or SGLang on a **different compatible GPU host**, not automatically on a small 8GB consumer GPU | Quality-matched throughput at same model/quantization and hardware |
| Heavy concurrent jobs | star/agent_resource_planner.py, star/resource_planner_service.py, star/team_service.py | Reserve chat slots, control CPU/RAM/VRAM leases, queue independent work, propagate deadlines and cancellation. Avoid loading duplicate large models | Interactive p95 under competing background workload and batch throughput |
| Repeatable speed gate | star/brain_benchmark.py | **Added star/performance_gate.py**: validates recorded timing summaries against measured samples, compares identical benchmark configurations, marks candidate regressions/improvements | Needs at least 10 measured samples per condition and separate independent task-quality evaluation |
| Animation test depth | star/blender_animation.py, star/studio_test_farm.py | **Added star/animation_regression.py**: linearly samples editable Euler joint values, computes peak/p95 speed, acceleration and loop tangent gaps, and compares approved reference recipes | Offline diagnostic only; later review native Blender frames, imported Roblox rig and true Studio playtests |
| Broader public information | star/web_search.py, scoped knowledge & tool_discovery.py | **Added star/public_research.py**: bounded opt-in queries to official Crossref and OpenAlex metadata APIs with source provenance and untrusted-data labels | Real HTTP result only after external-network consent; licensing, rate limits and data freshness still apply |
| Browser UI, animations and craft | frontend/src/MotionPolicy.tsx and existing visual smoke checks | Use Playwright visual snapshots with animations disabled for stable layout, plus distinct timed animation and interaction checks | Browser traces, actual frames, responsiveness, reduced-motion correctness and owner approval |
| Durable, complex workflows | star/mission_checkpoint.py and fleet planner | Research Temporal or equivalent durable orchestration only for authorized long-running tasks. Persist task state, idempotent retries, artifact hashes and evidence receipts | Interrupted run resumes correctly with no duplicate external writes |
| Stronger general reasoning | existing specialist agent fleet and eval gate | Route small tasks to measured small models; challenging coding, research, design, audio and motion to competent measured specialists, with independent verifier | Held-out cross-domain task success, citations, human acceptance and cost, not self-awarded confidence |

The fastest system is not necessarily the most agents or the most parameters. On one GPU, too much parallel decoding may increase first-token latency or exhaust VRAM. Optimize total validated work completed per watt/minute while preserving foreground responsiveness and output quality.

## Trusted source starting points

- llama.cpp server, slots and caching: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md
- vLLM prefix caching: https://github.com/vllm-project/vllm/blob/main/docs/design/prefix_caching.md
- Ray Serve dynamic request batching: https://docs.ray.io/en/latest/serve/advanced-guides/dyn-req-batch.html
- Hugging Face Text Embeddings Inference: https://github.com/huggingface/text-embeddings-inference
- OpenTelemetry Python metrics: https://opentelemetry.io/docs/languages/python/instrumentation/
- Temporal durable workflows: https://docs.temporal.io/develop/python/workflows
- Playwright page screenshots: https://playwright.dev/docs/api/class-pageassertions
- Blender command-line background mode: https://docs.blender.org/manual/en/5.1/advanced/command_line/arguments.html
- Roblox StudioTestService: https://create.roblox.com/docs/reference/engine/classes/StudioTestService
- Crossref API policies: https://www.crossref.org/documentation/retrieve-metadata/rest-api/access-and-authentication/
- OpenAlex API and authentication: https://help.openalex.org/api/ and https://help.openalex.org/api/authentication/

These are candidate techniques, not claims of local installations. Evaluate versions, licenses, available hardware, provider terms, VRAM, bills, and service quotas before adoption.

## How to run in a STAR checkout

Performance: Run the **existing actual server** twice at identical settings, before and after a separately authorized configuration experiment. It generates actual JSON; there are no fabricated hardware results.

    python -m star.brain_benchmark --model star-fast --scenario chat --runs 10 --parallel 1 > before.json
    python -m star.brain_benchmark --model star-fast --scenario chat --runs 10 --parallel 1 > after.json
    python -m star.performance_gate before.json after.json

Animation: Input must be an approved STAR R15/R6 JSON recipe, not an arbitrary executable Blender script.

    python -m star.animation_regression candidate_clip.json
    python -m star.animation_regression candidate_clip.json --reference approved_clip.json --tolerance-deg 5

Public research: No HTTP is performed without the explicit command flag; these are public metadata lookups, not free full-text or unrestricted web access.

    python -m star.public_research --catalog
    python -m star.public_research "procedural character animation evaluation" --source both --limit 3 --allow-network

Focused mocked checks, followed by repo-level checks:

    python -m pytest -q tests/test_performance_gate.py tests/test_animation_regression.py tests/test_public_research.py
    python -m compileall -q star
    python -m pytest -q

Benchmark files may include private LAN endpoints and should remain outside the Git repository. All synthetic tests only prove bounded pure logic and mocked transport handling, not production accuracy, real server speed, native Blender, or multiplayer correctness.

## How to grow safely after review

1. Extend the existing measured analytics dashboard with an honest per-model TTFT, p95, throughput, per-workload CPU/VRAM headroom, queue depth, cancellation and independently verified task-success indicators. Display unavailable measurements as unavailable.
2. Add model configuration experiments on actual installed hardware using paired quality/latency gates. Compare one server switch at a time and revert regressions. Preserve reserved interactive slots and owner preferences.
3. Add native animation evidence using an installed Blender background render, reference screenshots, glTF/rig mapping checks, foot-contact inspection, timed event alignment, real StudioTestService multiplayer sessions, and human review of final style. Fake/static jobs must never be labeled native tests.
4. Connect scholarly metadata via existing host policy and explicit per-source user grants rather than silently adding an unrestricted agent tool. Cache only permitted public metadata by provenance and timestamp; do not copy copyrighted abstracts and do not bypass rate limits.
5. Evolve toward broad general-purpose competence with multimodal tool adapters, independently measured specialist models, task-state recovery, project-scoped retrieval and verified eval suites. No system component can make a foundation model become artificial general intelligence through configuration alone.

**Safety boundary:** No unattended training, hidden credentials, privileged new MCP execution, provider spend, unlimited data access, repo auto-merge, release, or Roblox publication is authorized by this change. Neither a performance boost nor human-level general intelligence is claimed until established by real independent evidence.
