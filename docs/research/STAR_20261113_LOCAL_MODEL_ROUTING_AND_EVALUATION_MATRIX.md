# STAR 2026-11-13 — Local Model Portfolio, Routing, and Intelligence Evaluation

**Research date:** 2026-11-13  
**Purpose:** choose stronger and faster models without destabilizing STAR's realtime runtime  
**Status:** research and evaluation plan only; no model weights downloaded or defaults changed

## Executive recommendation

Do not replace STAR's current model simply because a leaderboard lists a higher score. Build a small, tested model portfolio and route each task to the least expensive model that meets its quality and latency target.

For the local 8 GB GPU target, the first controlled experiment should compare the current quick model against Qwen3.5-4B. A second experiment should test a stronger reasoning/tool-use model on the CPU/RAM server or with quantized/partial GPU offload. Keep one main model resident on the constrained GPU unless measurement proves that a second resident model is worth its VRAM cost.

## Official model candidates discovered

### Qwen3.5-4B — first local A/B candidate

The official Hugging Face model card identifies Qwen3.5-4B as a 4B-parameter multimodal model with a vision encoder, Apache 2.0 license, and native 262,144-token context (with longer extension described by the card). The card provides Transformers, vLLM, and SGLang usage and links to quantizations for llama.cpp/Ollama/LM Studio-compatible applications.

Source: [Qwen/Qwen3.5-4B model card](https://huggingface.co/Qwen/Qwen3.5-4B).

Why it is worth testing:

- Similar parameter class to STAR's small local fast path.
- Native image-text input may help visual UI/game observation without a separate always-resident vision model.
- Official quantization links provide a route to test local inference formats.
- It is small enough to be a plausible candidate for constrained local hardware, but actual VRAM, KV-cache, Windows backend, and multimodal support must be measured.

Do not assume every Qwen3.5 feature or chat template is supported by STAR's current llama.cpp build. Pin the exact model revision, tokenizer, template, quantization, and backend before benchmarking.

The Qwen3.5-4B card also says the model was trained with multi-step prediction (MTP) and documents speculative MTP serving recipes: SGLang uses a NEXTN configuration and vLLM uses its Qwen3.5 MTP method. This makes it a particularly useful candidate for testing native MTP before adding a separate resident draft model. The recipes require current/main inference-framework builds; pin the exact framework commit and verify model support, memory overhead, acceptance, TTFT, time-per-output-token, and first-audible latency before use.

The model card's own reported comparison gives Qwen3.5-4B vs Qwen3.5-9B: MMLU-Pro 79.1 vs 82.5, GPQA Diamond 76.2 vs 81.7, LiveCodeBench v6 55.8 vs 65.6, BFCL-V4 50.3 vs 66.1, and TAU2-Bench 79.9 vs 79.1. These are publisher-reported scores from the model card, not independent results or a substitute for STAR's own held-out tasks.

### Qwen3.5-9B — higher-capability multimodal candidate

The official card identifies Qwen3.5-9B as an Apache 2.0 multimodal image-text model and provides Transformers, vLLM, and SGLang serving paths.

Source: [Qwen/Qwen3.5-9B model card](https://huggingface.co/Qwen/Qwen3.5-9B).

Use it as a candidate for a higher-memory server or a measured quantized/offloaded setup. Do not assume a 9B model, its KV cache, and STAR's game/OBS/voice workload fit comfortably in 8 GB VRAM.

### IBM Granite 4.2-8B — deliberate reasoning/tool-use candidate

The official IBM Granite card describes an 8B dense reasoning model, Apache 2.0 licensed, with 128K native context and a longer-context extension. It documents full-thinking, non-thinking, and low-effort modes, plus reasoning-oriented tool calling and vLLM/SGLang serving.

Source: [ibm-granite/granite-4.2-8b model card](https://huggingface.co/ibm-granite/granite-4.2-8b).

Use it as a candidate for longer planning, repository analysis, and multi-step tool tasks on the CPU/RAM server or a quantized/partial-offload configuration. The model card's BF16 configuration is not a claim that it fits in an 8 GB GPU.

## Recommended STAR model roles

| Role | Work | Preferred behavior | Admission policy |
|---|---|---|---|
| Realtime responder | Short chat, backchannels, immediate stream reactions | Low latency, concise, no unnecessary deliberation | Highest priority; strict token/deadline budget |
| Social/voice planner | Conversation floor, interruptions, corrections, multi-turn grounding | Stronger dialogue reasoning when needed | Reserved voice budget; cancellable |
| Strategic reasoner | Research plans, complex decisions, long-horizon tasks | Deeper reasoning, evidence and uncertainty | Background/interactive queue |
| Coding specialist | Repository edits, Luau/Python/TypeScript, test repair | Tool-call correctness and test-driven edits | Isolated workspace and test gate |
| Vision observer | HUD, scene, UI, avatar/game state | Event-driven frame analysis, structured state | Sample on scene changes; not every frame |
| Gamer controller | Immediate movement, aim, dodge, interaction | Small fast policy plus deterministic controller | Hard realtime budget; no large LLM per frame |
| Knowledge/retrieval | General facts, documentation, research | Retrieve, cite, resolve conflicts, track freshness | Bounded retrieval and context budget |
| Speech components | VAD, ASR, TTS, speaker/turn timing | Dedicated low-latency audio components | Separate audio scheduling and cancellation |

A single large model should not be called for every frame, every chat line, every keystroke, and every background research task. The gamer controller should use deterministic state machines and short action policies for high-frequency control; use a reasoning model for strategic decisions and unfamiliar situations.

## Model manifest: pin everything that changes behavior

Every tested model entry should record:

- Provider/repository and immutable model revision.
- Weight-file SHA-256 and quantization.
- License and commercial-use constraints.
- Architecture and supported modalities.
- Tokenizer and chat-template hashes.
- Context length and effective context actually tested.
- Inference backend, exact version/build, and hardware path.
- GPU layers/offload, CPU threads, batch threads, slot count, and KV-cache type.
- Reasoning mode/parser and tool-call parser.
- Maximum output tokens and per-task reasoning budget.
- Cold-start load time and warm first-token latency.
- Peak VRAM, RAM, CPU, and throughput under mixed workload.
- Held-out task outcomes and benchmark harness revision.

A model name alone is not a reproducible deployment. Different quantizations, templates, parsers, context lengths, and backends can materially change correctness and latency.

## Intelligence improvements beyond swapping weights

1. **Capability-aware routing:** classify task type, deadline, risk, context size, confidence, and resource budget before choosing a model.
2. **Adaptive reasoning budget:** short/low-risk tasks use low effort; complex research, code, and planning can request deeper reasoning when admitted.
3. **Retrieval before long prompts:** fetch only relevant verified docs, project facts, API signatures, and approved skills; keep stable prefixes cacheable.
4. **Tool verification:** validate schemas before calls, validate outputs after calls, and require task-specific tests before accepting results.
5. **Independent critics:** use a verifier or deterministic checker for code, game state, citations, and structured outputs. A second model opinion is not proof by itself.
6. **Memory-to-action evaluation:** measure whether episodic/procedural memories improve future held-out tasks; include no-memory controls and stale-memory tests.
7. **Skill compilation:** convert successful repeated workflows into versioned, executable skills with compatibility and failure conditions.
8. **Parallelism only for independent work:** split research or code analysis when sub-tasks are independent; avoid multi-agent overhead and shared-resource contention for simple requests.
9. **Uncertainty and abstention:** when evidence is weak, ask for a tool result or report uncertainty instead of fabricating confidence.
10. **Post-task learning:** store the outcome, error class, correction, and verified reusable lesson—not raw private stream content by default.

## 8 GB local GPU deployment strategy

1. Keep the realtime path's working model and audio/graphics headroom protected.
2. Start with one GPU-resident general model; use CPU/RAM for larger specialist workers when necessary.
3. Test Qwen3.5-4B first as a controlled local candidate, using a short practical context before testing long contexts.
4. Test Qwen3.5-9B or Granite 4.2-8B only as quantized/partial-offload or server-side candidates.
5. Measure KV-cache growth separately from model-weight memory. A long context can exhaust memory even when the quantized weights fit.
6. Bound prompt-cache RAM and evict by measured reuse, not unbounded retention.
7. Keep vision sampling event-driven: scene changes, HUD changes, target changes, objective transitions, or explicit user requests.
8. Do not load a draft model or second specialist into VRAM until its measured latency benefit exceeds its memory and contention cost.
9. Preserve CPU/RAM offload as a first-class path so the system remains useful without relying on the GPU.
10. Re-run all candidates with the real combined workload: STAR + game + OBS + VTube Studio + audio + background tasks.

## Evaluation matrix

Use the paired evaluator in 'star/stream_variant_eval.py'. The same sealed cases and host/game/harness fingerprint must be used for baseline and candidate.

| Track | Quality outcomes | Performance/pressure |
|---|---|---|
| Voice | task accuracy, turn-taking, groundedness, correction handling | TTFT, first audible, cancellation-to-stop, audio underruns |
| Social | direct-address detection, appropriate silence, no duplicate answers | first audible, overlap/interruption rate, long-context cost |
| Coding | build/test success, correct edits, no regression | time-to-first-action, total completion time, CPU/RAM/VRAM |
| Gaming | objective success, held-out skill transfer, action validity | reaction latency, frame-time p99, dropped input, VRAM |
| Creator | playability, mechanic correctness, actual game completion, save/reopen | iteration time, build time, frame-time p99, memory |
| Knowledge | factual correctness, source support, freshness, uncertainty calibration | retrieval latency, prompt tokens, total answer latency |
| Mixed stream | all required task outcomes | first audible, frame-time p99, audio/OBS loss, CPU/RAM/VRAM |

Use separate cold-start and warm-cache cohorts. Randomize or counterbalance baseline/candidate order. Keep the case set sealed after it becomes a holdout. Never compare runs across different hardware/driver/game/harness environments as if they were paired.

## Research and implementation order

### P0 — reproduce the baseline

- Export the current model/runtime manifest.
- Record the exact Windows build, GPU driver, game build, OBS settings, audio device, and model server version.
- Run a mixed workload with at least 30 paired cases and multiple domains.
- Preserve raw measurements in the trusted host, but upload only opaque IDs, bounded aggregates, and digests to the evaluator.

### P1 — local quick-model comparison

- Compare current local model vs Qwen3.5-4B.
- Confirm the exact Windows backend and multimodal path.
- Compare Q4/Q5 quantizations only if available and compatible.
- Test context 4K/8K/16K before long-context experiments.
- Evaluate voice, tool calling, code, image understanding, and general knowledge separately.

### P1 — stronger reasoning worker

- Test Granite 4.2-8B on the server/CPU-RAM path and one quantized/offload configuration.
- Test Qwen3.5-9B as a separate candidate.
- Compare quality gain against queue delay, model load time, RAM/VRAM, and mixed-stream frame/audio impact.
- Keep the stronger worker on-demand; do not make it the default voice responder unless it meets first-audible and stream-stability gates.

### P2 — specialist routing

- Add coding, vision, embedding/reranking, ASR, and TTS roles only when their held-out tests show a measurable benefit.
- Use model adapters behind a stable OpenAI-compatible or internal capability interface.
- Do not expose provider keys or silently switch to paid endpoints.
- Keep web research and external actions behind explicit opt-in/approval policies.

### P3 — continuous model lifecycle

- Store model manifests, benchmark runs, and accepted/rejected candidates.
- Re-run the holdout suite after backend, model, prompt, memory, or scheduler changes.
- Automatically flag regressions, but keep model promotion and production rollout manual.
- Retain a rollback-ready known-good model/runtime manifest.

## Sources

- [Qwen3.5-4B official model card](https://huggingface.co/Qwen/Qwen3.5-4B)
- [Qwen3.5-9B official model card](https://huggingface.co/Qwen/Qwen3.5-9B)
- [IBM Granite 4.2-8B official model card](https://huggingface.co/ibm-granite/granite-4.2-8b)
- [llama.cpp server capabilities](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)
- [vLLM Automatic Prefix Caching](https://docs.vllm.ai/en/latest/features/automatic_prefix_caching/)
- [OpenTelemetry GenAI metrics](https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-metrics.md)

## Limits

This document recommends controlled model experiments; it does not download, install, fine-tune, or switch any model. Model-card claims are not independent benchmark results. Quantized artifact compatibility, Windows support, VRAM/RAM use, tool-call correctness, and actual STAR workload performance must be measured locally before a candidate is adopted.
