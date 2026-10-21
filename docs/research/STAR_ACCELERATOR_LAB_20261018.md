# STAR Accelerator Lab: speed comparison, animation motion check, scholarly sources

Research notes from PR #479 (2026-10-18), rewritten 2026-10-21 to match what was wired. Nothing here runs at startup;
the two new tools are off until the owner turns them on.

## What shipped and where

| Need | Where it lives | How to reach it |
| --- | --- | --- |
| Before/after speed verdict | `star/brain_benchmark.py` `compare_reports`, `--compare` | `python -m star.brain_benchmark --compare before.json after.json` (docs/PERFORMANCE_PROFILING.md) |
| Animation motion check | `star/animation_regression.py`, Blender MCP tool `star_blender_animation_motion_qa` | Settings > Images, voice & 3D > Blender > "Check animation motion" (needs "Use Blender on this PC") |
| Scholarly sources in deep research | `star/public_research.py`, `star/team_service.py` | Settings > Knowledge & search > "Add scholarly papers to deep research" (needs deep research on) |

Speed comparison reuses the eval gate's statistics (`star/eval_stats.py`: exact sign test, cluster bootstrap): sample i
of each report is a pair, lower time wins. Any run count works; below 5 pairs nothing can be significant at alpha 0.05,
so the verdict stays INCONCLUSIVE. Arms run one after the other, so drift between them is not cancelled.

The motion check samples the authored Euler keys linearly per frame and reports peak and p95 joint speed, peak
acceleration and the loop seam (velocity in versus out); with a reference clip of the same rig, fps and length it
also reports per-frame differences. It does not render Blender frames, apply Roblox joint transforms, IK or physics.

Scholarly sources: on the first query of a deep-research run, Crossref and OpenAlex are each asked for 2 works
(titles, years, DOI or OpenAlex links; no abstracts). Requests go through `star/web_fetch.fetch_page`, so the same
public-address, redirect, size and time limits apply as for any page. The research question is sent to both services.
Results are interleaved with web results and the linked pages are read like any other source.

## Directions not built (candidates, each needs its own measured experiment)

| Objective | Existing module | Candidate technique | Evidence needed |
| --- | --- | --- | --- |
| Faster first token | brain_benchmark, instant_route, prefill_warm | Fixed prompt prefixes; llama.cpp prompt cache and slot settings, one switch at a time | Paired TTFT with `--compare`, same hardware and model file |
| Throughput | model_fleet, STAR Server | llama.cpp continuous batching; vLLM prefix caching or SGLang only on a GPU host that fits them | Throughput at matched quality and quantization |
| Heavy concurrent jobs | agent_resource_planner, resource_planner_service | Reserved chat slots, CPU/RAM/VRAM leases, deadline and cancel propagation | Interactive p95 under background load |
| Animation depth | blender_animation, studio_test_farm | Blender background renders, rig mapping checks, foot contact, StudioTestService playtests | Real frames and playtests, owner review |
| UI motion | frontend MotionPolicy | Playwright snapshots with animations disabled plus separate timed checks | Traces, reduced-motion correctness |
| Durable long jobs | mission_checkpoint | Temporal-style durable workflows for long authorized tasks | Interrupted run resumes without duplicate writes |

On one GPU more parallel decoding can raise first-token latency or exhaust VRAM; measure total validated work per
minute while keeping chat responsive.

## Sources

- llama.cpp server, slots and caching: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md
- vLLM prefix caching: https://github.com/vllm-project/vllm/blob/main/docs/design/prefix_caching.md
- Ray Serve dynamic request batching: https://docs.ray.io/en/latest/serve/advanced-guides/dyn-req-batch.html
- OpenTelemetry Python metrics: https://opentelemetry.io/docs/languages/python/instrumentation/
- Temporal durable workflows: https://docs.temporal.io/develop/python/workflows
- Playwright screenshots: https://playwright.dev/docs/api/class-pageassertions
- Blender command-line background mode: https://docs.blender.org/manual/en/5.1/advanced/command_line/arguments.html
- Roblox StudioTestService: https://create.roblox.com/docs/reference/engine/classes/StudioTestService
- Crossref REST API: https://www.crossref.org/documentation/retrieve-metadata/rest-api/
- OpenAlex API: https://help.openalex.org/api/
