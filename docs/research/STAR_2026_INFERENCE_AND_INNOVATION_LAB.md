# STAR AI: Inference, innovation, and independent quality-gate research

**Researched:** 2026-10-18. **Status:** implementation blueprint plus the paired innovation review in star/innovation_gate.py (`python -m star.evals innovation`). This is NOT a deployed inference accelerator, trained frontier model, autonomous upgrade service, verified global speed claim, or replacement for owner review.

## 1. Start from the real STAR architecture

Extend the existing star/next branch rather than starting a competing AI system. Existing modules include star/model_fleet.py (bounded model roles and probes), star/brain_router.py, star/team_service.py (three local specialist perspectives and synthesis), star/agent_runtime.py (bounded DAG), star/learning.py and star/lessons.py (reviewed project memory), Night School, and the React/Qt desktop.

STAR's README reports automated Roblox blind holdout 8/24 on v0.9.0 and 9/24 on v1.0.0, an inconclusive difference. New tools or model counts are not evidence that STAR's task quality improved. All improvement claims need independently measured, repeated, task-specific comparisons.

Preserve the Windows installer, user chats, local preferences, project isolation, consent, keyring credentials, and the rule that no cloud provider or write capability is activated silently.

## 2. Existing infrastructure and resource isolation

**Prior authorized inspection only, NOT measured during this change:** Server 1 runs Ubuntu 24.04 on AMD EPYC 7451 (24c/48t) with roughly 125 GiB RAM and a CPU llama-server; it previously exhibited heavy swap/system load and little free root-disk headroom. Server 2 runs Ubuntu 24.04 on i7-9700 (8c/8t), roughly 15 GiB RAM and Docker/Wings. Metallic game services and Metallic MC are intended to have separately isolated containers and fair physical-host resource budgets.

Before tuning or training, refresh host telemetry and secure spare disk and memory. CPU memory bandwidth, NUMA locality, quantization, context length, prompt prefix stability and competitor service load determine usable real-world performance more than thread count alone. Setting CPU thread counts to the maximum can make decode slower under contention.

Measure warm/cold p50 and p95 time-to-first-token, prompt tokens/second, decode tokens/second, p95 task completion latency, success on a held-out task suite, model/quantization checksum, context length, swap, peak RSS, disk, errors, host load and p95 game-service latency. Alternate control/candidate order. Run resource-heavy work only in authorized maintenance windows.

Suggested incremental levers for existing CPU-first llama.cpp deployment: metrics endpoint and observability, model memory and quantization comparison, low-concurrency admission control, stable system-prompt KV cache/prefix reuse, batching/slots experiments, NUMA pinning tests, measured --threads and --threads-batch sweeps, prompt/context minimization, and optional speculative decoding where the particular GGUF/runtime supports it. These are experiments, not assertions of guaranteed speedups.

Reference: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md
Reference: https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md

## 3. Model competition instead of uncontrolled downloads

Candidate families to investigate only after checking current license, file checksum, quantization compatibility, tokenizer/tool-template compatibility and model-server version:

| Candidate | Why research | Known limitations |
| --- | --- | --- |
| Existing configured GGUF models | Reproducible baseline; already integrated | May be weaker on demanding coding/vision |
| Gemma 4 E2B/E4B, 12B | Explore compact reasoning, function calling and on-device multimodal roles | Exact variant, RAM needs and runtime support must be verified |
| Qwen3.5 compact variants and newer Qwen models | Multilingual, code and potential agent routing candidates | New architecture may require new backend; do not assume speed on EPYC |
| gpt-oss-20b | Compare open-weight reasoning and tool use | Published checkpoint size about 12.8 GiB; far too tight as a resident model for 15 GiB server 2 |

References: https://ai.google.dev/gemma/docs/core/model_card_4
https://github.com/QwenLM/Qwen3.8
https://deploymentsafety.openai.com/gpt-oss/architecture

Measure tool-call syntax validity, code/test outcome, multimodal accuracy and real-world speed separately. Successful text model probes do not establish image understanding, audio, video, browser use or successful Minecraft/Roblox development. Keep one resident model on constrained hardware until actual measurements justify more.

## 4. Novelty and improvement pipeline

Suggested controlled architecture:

    Trusted source registry / official documentation / versioned releases
       -> Evidence scout with citation and timestamp
       -> Duplicate and dependency checker against current STAR code
       -> Brainstorm at least two approaches plus a simple baseline
       -> Independent critic: failure modes, cost and test oracle
       -> Owner-reviewed experiment proposal, expected outcome, rollback
       -> Isolated non-production branch/worktree runner
       -> Independent tests, measurement, human visual/game evaluation
       -> Offline innovation gate recommendation
       -> Human PR review, standard CI and release workflow
       -> Approved project knowledge with provenance and undo

Starry should remember why each idea was accepted or rejected, not treat all retrieved text as trusted instructions. Competing agents should get bounded read/write scopes from a trusted host, deadlines, token budgets, explicit capabilities, structured outputs and isolated temporary workspaces. Never give a tool privileges because the model text claims they are needed.

MCP is useful for explicit tool/resource contracts; A2A may be useful for authenticated long-running task handoffs across processes. Prefer adapters to the existing STAR scheduler over replacing its safety boundary.

Source: https://github.com/a2aproject/A2A/blob/main/docs/topics/a2a-and-mcp.md
Source: https://github.com/modelcontextprotocol/modelcontextprotocol

Grok Bot-like reusable specialist templates are interesting: research scout, code reviewer, UI animation reviewer, Roblox simulator, Minecraft resource pack validator, server performance investigator, procurement analyst. A template must declare owner, project, triggers, inputs, outputs, tool scopes, model budget, hardware demand, retention policy, version, approval points, forbidden side effects and an audit trail. These are proposals, not running features. Grok's vendor-reported procurement savings do not validate STAR.
Source: https://x.ai/news/introducing-grok-bot
Source: https://x.ai/news/grok-bot-procurement
Source: https://x.ai/bot/marketplace

## 5. Implemented component: paired innovation review (wired 2026-10-21)

star/innovation_gate.py reads the result files `python -m star.evals run` already writes, one per sample, both arms
run in one session (the same input as `python -m star.evals gate --paired-session`):

    python -m star.evals innovation --objective quality|speed --baseline b1.json b2.json --candidate c1.json c2.json

Quality comes unchanged from star/eval_gate.compare_paired (exact sign test, bootstrap, MDE, canaries, suite and
grader identity checks, one-session rule). Time uses each task's recorded `seconds` (median over the arm's samples),
compared task by task with the exact sign test from star/eval_stats.py.

Recommendations: review_candidate (exit 0), reject_regression (1), invalid_evidence (2), needs_more_evidence (4).
Quality objective: the eval gate must PROMOTE and tasks must not be significantly slower by more than 15 % total time.
Speed objective: the eval gate must not find a regression and tasks must be significantly faster by at least 10 %.

Dropped from the 2026-10-18 draft: its own JSON experiment format, the separate sign test, the 40-case minimum (the
eval gate's MDE note says what the task count can resolve) and the peak-memory check (runner files record no memory).
These are screening rules, not proof of production fitness; reusing a holdout for tuning contaminates it.

## 6. Human-standard quality evidence is domain-specific

| Domain | Objective checks | Human acceptance needed |
| --- | --- | --- |
| Python/Java/Luau/TypeScript | Builds, tests, types, security, integration, mutation/property checks | Correctness and maintainability of real project edits |
| Desktop/web UI | Playwright Chromium/Firefox/WebKit flows, responsive snapshots, accessibility and keyboard, JS console errors | Visual polish, animation timing, consistency, usability |
| Roblox / Metallic | Replication validation, scripted multiplayer, stability, low-end performance and latency | Game feel, physics, social UX and realistic real-device testing |
| Minecraft plugins/assets | Java build, Paper runtime, permissions, Java client resource pack import, pack model/format checks | Blockbench models, particle/VFX feel, GUI fidelity, real-client compatibility |
| Audio/video/image | Segmentation, alignment, transcription, source attribution and task accuracy | Fidelity, synchronization, rights and creative judgment |
| Server | API p95/p99, memory/swap, recovery, authorization, disaster recovery and soak testing | Verified operational recovery and tenant isolation |

A candidate must not grade only its own answer. Require test oracles controlled by the harness, independent reviewers, blinded A/B reviews when practical, reproducible artifact references and real application testing.

For browser operations, Playwright and Chrome DevTools automation on owned/authorized sites can be used for inspection/testing; bypassing third-party anti-bot barriers is not part of the quality plan.
Source: https://github.com/microsoft/playwright
Source: https://github.com/vibheksoni/stealth-browser-mcp

## 7. Engine and infrastructure evaluation map

| Layer | Fits today's CPU deployment | Consider only for future supported accelerators |
| --- | --- | --- |
| Inference | llama.cpp, bounded request queues, caching, observed tuning | vLLM / SGLang, paged KV and continuous batching comparison |
| Context | stable prefixes, explicit retention and small contexts | LMCache reusable tiered KV where supported |
| Agents | Existing bounded STAR DAG and policy | OpenHands Software Agent SDK, LangGraph durable checkpoint concepts, A2A adapters |
| Jobs | Opt-in bounded worker with audit, cancellation and low priority | Durable/idempotent queue, execution receipts and backpressure |
| Telemetry | systemd, kernel/node metrics, llama-server metrics, quotas | OpenTelemetry traces and request/agent cost attribution |

References: https://github.com/vllm-project/vllm
https://github.com/sgl-project/sglang
https://github.com/LMCache/LMCache
https://github.com/OpenHands/software-agent-sdk
https://github.com/langchain-ai/langgraph

## 8. New hardware: comparison, not shopping commitment

| Platform | Published accelerator memory | Considerations |
| --- | --- | --- |
| NVIDIA DGX Spark | 128 GB coherent unified system memory | Single compact developer desktop; check model/runtime support and thermal limits |
| RTX PRO 6000 Blackwell Server Edition | 96 GB ECC GDDR7 | High power draw (up to 600W); server power, chassis, airflow, driver compatibility |
| AMD Radeon AI PRO R9700 | 32 GB | ROCm software/platform support, cost, driver matrix, desired kernels |
| AMD Instinct MI350 | 288 GB HBM3E | Enterprise/datacenter investment; not a drop-in consumer server upgrade |
| NVIDIA Vera Rubin | Rack-scale announced enterprise platform | Not a practical fix for an EPYC CPU inference bottleneck without substantial capital/infrastructure |

Official references: https://www.nvidia.com/en-us/products/workstations/dgx-spark/
https://www.nvidia.com/en-us/data-center/rtx-pro-6000-blackwell-server-edition/
https://www.amd.com/en/products/accelerators/instinct/mi350.html
https://rocm.docs.amd.com/en/develop/reference/gpu-specs.html
https://investor.nvidia.com/news/press-release-details/2026/NVIDIA-Vera-Rubin-Ramps-Into-Full-Production-to-Power-Agentic-AI-Factories-Worldwide/default.aspx

Before even recommending purchases, check motherboard PCIe slots/lanes, BIOS, power/cooling, physical enclosure, PSU, CPU/RAM pressure, model mix, hardware amortization, rights to use each model, and $/verified successful task, not peak FLOPs.

## 9. Screenshots: risk/benefit assessment

How to Train Your GPT (https://github.com/raiyanyahya/how-to-train-your-gpt): excellent learning reference for transformers, RoPE, attention and training loops; no evidence it makes a production foundation model by itself.

Grok Bot (https://x.ai/bot/marketplace): useful agent skill templates, evidence trail, scheduled repeatable actions, owner approvals. Company-reported savings are not benchmark data.

Stealth Browser MCP (https://github.com/vibheksoni/stealth-browser-mcp): relevant Chrome DevTools integration for authorized browser research and UI QA; defeating third-party access restrictions should not underpin STAR's architecture.

Heretic (https://github.com/p-e-w/heretic): studies modifying refusal behavior through model parameter ablation; reducing refusals is not the same as higher correctness, code quality or security. Do not use safeguard removal as STAR's intelligence objective.

## 10. Staged rollout and explicit non-claims

Start with safe read-only host measurements and CPU/cache/queue optimization. Then run a controlled model contest with immutable fixtures and blinded scoring. Add human-reviewable idea proposals and domain-specific verified tool traces. Only after repeated quality gains consider extra GPUs, constrained fine-tuning and more autonomous research workers.

Before considering merge: run STAR-wide Python tests, lint and compile; frontend typecheck, Vitest and Vite build; Windows/Qt installer smoke tests; auth/SSRF and secret exposure audit; CPU and memory-soak tests while Metallic tenants operate. Re-test any regression. Owner review remains mandatory.

Not implemented in this branch: new models installed, GPU purchased, public product launched, cloud fallback, self-modifying production code, hosted research scout, automated merge, human validation of actual generated apps, or any measured global "fastest" ranking.
