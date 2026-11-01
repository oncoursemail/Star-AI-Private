# Litha — RTX 4060 8 GiB inference research and measured rollout plan

**Date:** 2026-11-01  
**State:** candidate implementation and offline tests, **not** an inference speedup, model installation, Windows measurement, Litha release, or an approved runtime change.  
**Scope:** an RTX 4060 8GB desktop used for Litha/STAR development, sometimes simultaneously gaming/VTubing. Existing STAR `star/local_runtime.py` uses llama.cpp; Ollama is an optional comparative backend. Litha's repository automation lives in `litha/` and is separate from the STAR application in `star/`. Model changes and automation settings remain **off by default**.

## Executive finding: investigate fit, not just a parameter threshold

The RTX 4060 has **8GB** GDDR6, **128-bit** interface and **272GB/s** nominal memory bandwidth (board vendor specification). These constrain memory-resident model size and bandwidth-bound token generation. They do **not** impose a fixed 4–6 token/s rate for every 12B+ model. Generation depends on quantization, active tensor placement, attention/KV/state memory, CPU and RAM bandwidth, PCIe traffic, CUDA kernels, batching, speculative acceptance, prompt processing and application contention. A MoE's smaller *activated parameter count* reduces arithmetic but does **not** erase its inactive experts' storage footprint.

In this repository, merged **PR #772** reports an RTX 4060 experiment with Gemma-4-12B QAT q4_0, CPU FFN placement, and an MTP drafter: 36 tokens/s in an older tested arrangement, 51–57 tokens/s in tuned normal configurations and 77 tokens/s in idle boost. These are **PR-reported results**, not independently reproduced here, and cannot be transferred to Qwen/LFM, different prompts, Windows GPU competition or another 4060 without retesting. Use its evidence and avoid repeating the failed experiments it documents. https://github.com/oncoursemail/Star-AI-Project/pull/772

## Verified model IDs and advertised download sizes (2026-11-01 snapshot)

| Model/official Ollama tag | Advertised download GB (decimal, approx) | Vision? | Role to A/B test | 4060 caveat |
| --- | ---: | --- | --- | --- |
| `qwen3.5:4b-q4_K_M` | 3.3 | yes | gaming + VTuber interaction, quick code draft | best provisional headroom; accuracy must be tested |
| `qwen3.5:4b-q8_0` | 5.2 | yes | higher-fidelity 4B candidate | **not** 4.3GB; less room for games |
| `qwen3.5:9b-q4_K_M` | 6.6 | yes | quality-first local coding / visual reasoning | not a guaranteed 32K GPU fit |
| `lfm2.5:8b-a1b-q4_K_M` | 5.2 | **no** (text-only Ollama variant) | fast tool calling / structured agent steps | 8B *total* parameters, ~1B activated; full weights still require storage |

Sources: [Qwen3.5 official Ollama tags](https://ollama.com/library/qwen3.5/tags); [LFM2.5 official Ollama tags](https://ollama.com/library/lfm2.5/tags); [Liquid AI technical release](https://www.liquid.ai/blog/lfm2-5-8b-a1b). The names, sizes and packaging can change; inspect `ollama show` and the active model digest before each controlled comparison.

**Corrections to the input brief:**

- `ollama run qwen3.5:9b-instruct-q4_K_M` is not the published canonical 9B Q4 tag above. Start from `ollama run qwen3.5:9b-q4_K_M` if that tag is still available.
- The official DeepSeek-R1-Distill checkpoints include **Qwen 7B** and **Llama 8B**, **not Qwen 8B**. Official list: https://github.com/deepseek-ai/DeepSeek-R1 . The 7B is a comparison candidate only after identifying an exact usable package and model digest.
- No controlled, externally verified 4060-desktop protocol here substantiates universal **54–58 / 75 / 118 tokens/s** for these particular models. An independent **4060 laptop** Qwen3.5-9B Q4 study reported **23.77 tok/s Ollama** and **37.73 tok/s llama.cpp**, but its tools followed distinct benchmark paths, so it is not an apples-to-apples engine ranking: https://www.nidhiyashwanth.com/blog/local-ai-benchmark . A different 3090 test measured 6.7 GB at 32K and ~79.8 tok/s; **a 3090 is not an 8GB 4060**, and its reported 6.7 GB measurement does not prove fit during Windows gaming: https://localagentbench.com/models/qwen3.5-9b/ .
- Qwen3.5 9B is a **dense 9B** text+vision hybrid model with three Gated DeltaNet layers per full-attention layer; it is not an 8B MoE, and its memory growth is not captured by a generic transformer KV-cache formula. Source: https://huggingface.co/Qwen/Qwen3.5-9B and https://github.com/huggingface/transformers/blob/main/docs/source/en/model_doc/qwen3_5.md .

## A model is not 'GPU fit' until measured on the actual host

A model's Ollama disk/download size is **not** peak runtime VRAM. Account for CUDA context/workspace buffers, vision projector and image tokens, text state, KV cache, context length, concurrent slots, GPU display compositor, game assets, OBS buffers, other local GPU models, drivers and fragmentation. Don't assume a 6.6GB download occupies only 6.6GB at 32K. A machine that reports "8GB installed" might have much less *dedicated GPU memory free* while running Litha plus a game.

The new `litha.gpu_model_catalog` **only screens rough weight size** against current user-reported free VRAM minus a configurable safety reserve. It always returns `gpu_fit_verified: false`. A tentative candidate is not a safe activation signal. Even its `candidate_needs_live_fit_test` status can still OOM. Avoid *automatic* model swaps or forced GPU saturation based on that estimate.

Example, read-only:

```powershell
nvidia-smi --query-gpu=memory.free,memory.used,utilization.gpu,temperature.gpu --format=csv,noheader,nounits
python -m litha.gpu_model_catalog --free-vram-mib 6500 --reserve-mib 1536 --workload gaming
python -m litha.gpu_model_catalog --free-vram-mib 7800 --reserve-mib 1024 --workload quality
```

The numbers above are **illustrative parameters**, **not measurements** of the owner's PC. For Litha, recheck available VRAM immediately before any chosen load and again under worst-case real workload. Treat `ollama ps`'s processor column and `nvidia-smi`'s *dedicated* memory observations as necessary checks, not sufficient performance proof. If observed runtime dedicated VRAM exceeds the budget, reject that profile; do not silently spill into Windows shared memory. Hardware-probe errors mean "unknown," not "free".

## Ollama: opt-in memory and scheduling research

Ollama documentation states that (a) supported backends automatically use Flash Attention, with `OLLAMA_FLASH_ATTENTION=1` forcing it where supported, (b) `OLLAMA_KV_CACHE_TYPE=q8_0` quantizes the **KV portion** to approximately half of f16 KV memory, **not** half of total VRAM, and may affect accuracy, and (c) parallel request handling multiplies active context allocations. Official FAQ: https://github.com/ollama/ollama/blob/main/docs/faq.mdx .

**Proposed one-model-at-a-time Windows test profile** — set variables in the same PowerShell session *before* starting a dedicated Ollama server; first stop an already running Ollama service to avoid measuring the wrong process:

```powershell
$env:OLLAMA_FLASH_ATTENTION = "1"
$env:OLLAMA_KV_CACHE_TYPE = "q8_0"
$env:OLLAMA_NUM_PARALLEL = "1"
$env:OLLAMA_MAX_LOADED_MODELS = "1"
$env:OLLAMA_CONTEXT_LENGTH = "8192"
ollama serve
```

These are **bench candidates, not a recommended permanent OS-wide change**. Q8 cache compression is global to this Ollama server, so compare f16/q8 *separate server runs* using the same model, prompt suite, context, GPU free memory, temperature, warmup and request order. Benchmark **4096 → 8192 → 16384** only if the prior stage fits; use 32768 only after a high-water mark confirms stable headroom. No fixed 8K/16K setting proves a 9B full-GPU fit. During gaming, try the 4B Q4 profile first. If an agent needs large contexts, retrieval and selective prompt summaries are typically safer than increasing context blindly.

For explicit synthetic Ollama probes (the model must be installed already and the local server running):

```powershell
python -m litha.ollama_probe --model qwen3.5:4b-q4_K_M --context 4096 --repeats 2
python -m litha.ollama_probe --model lfm2.5:8b-a1b-q4_K_M --context 4096 --repeats 2
```

`ollama_probe` binds exclusively to `127.0.0.1` on a numeric port, sends **fixed public synthetic prompts**, reports per-case observed first-visible output time, wall time and Ollama's nanosecond engine counters, and does **not** log output text. It rejects partial streams/missing counters rather than inventing zero-latency successes. It does not download, enable or reconfigure a model; a CLI invocation initiates the inference work. It can prove neither correctness nor full VRAM residency; model digests, clock, driver, memory and workload must be recorded **outside** the probe by the responsible host for a fair A/B.

Ollama API's `eval_count / eval_duration * 1e9` is **generation throughput**, not the same as tokens divided by complete wall time; `prompt_eval_count / prompt_eval_duration` is **prefill throughput**; durations are nanoseconds. Source: https://github.com/ollama/ollama/blob/main/docs/api.md . First-visible-token time must be separated from speculative *thinking* tokens and from speech output latency, where relevant.

## Existing llama.cpp runtime (preferred default): an optional KV experiment

`star/local_runtime.py` already launches explicitly selected `llama-server.exe`, on `127.0.0.1`, using `--ctx-size`, `-ngl`, `--jinja`, and optional n-gram speculation; `star/model_fleet.py` limits the router to one loaded model. `star/compute_frontier.py` already compares repeated matched llama-bench outputs; `star/inference_ab.py` already has a mixed synthetic SSE benchmark. **Do not replace these mature paths with Ollama, or change defaults, without a matched quality and latency gate.**

For a separate owner-chosen llama.cpp experiment, current upstream accepts `-fa on`, `-ctk q8_0`, and `-ctv q8_0` for compatible builds; context and slots are set via `-c` and `-np`. The new optional arguments to `Runtime.arguments`, `Runtime.router_arguments`, `Runtime.start`, and `Runtime.start_router` are default-preserving: `flash_attention='auto'`, `kv_cache_type='f16'`. They emit no additional flags by default. Only `flash_attention='on', kv_cache_type='q8_0'` enables compressed KV. Incompatible pairs raise locally before launch. This does **not** guarantee support or performance on any specific installed llama.cpp binary.

References: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md and https://github.com/ggml-org/llama.cpp/blob/master/tools/llama-bench/README.md .

## Higher-leverage improvements beyond model selection

### 1. Treat GPU scheduling as an admission-control problem

Keep one primary GPU language model resident in interactive sessions; enqueue or delegate CPU-only retrieval, file indexing, text diffing, unit tests and Luau analysis. Before expensive image processing, verify active game FPS and voice backlog. Do **not** have a small agent, vision worker, video generator and game each reserve their maximum GPU memory simultaneously. Use the existing `star/stream_hardware_telemetry.py` and GPU helper rather than new GPU polling inside the render/audio thread. Prefer switching model only after a stable idle period (hysteresis) to avoid swap thrashing. CPU offload is an experiment, not automatically inferior: PR #772's measured FFN placements are a valuable case study, while attention movement is often much more expensive.

### 2. Control prompt-processing cost before searching for more bandwidth

Use stable system prefixes and reuse approved, project-scoped retrieval; include only relevant Roblox API symbols and concise verified examples. Keep retrieval and embedding on CPU when the GPU is already busy. Cache exact immutable facts but never share one user's/private project's prompt cache across boundaries. Measure *uncached* prefill tokens and total wall time, not just decode tokens. A shorter well-grounded prompt may beat a much larger raw context without losing verified quality. Existing STAR code includes retrieval routing, code search cache, and prompt context machinery; extend existing interfaces instead of parallel duplicate frameworks.

### 3. Investigate speculative decoding without exhausting VRAM

Try n-gram speculation **off by default** and compare actual accepted tokens/sec. A second 2–4B draft model may not fit next to 9B on an 8GB GPU; speculative proposals can lose time if their acceptance is low. Built-in compatible MTP or expert-on-CPU strategies can outperform naive two-model setups on particular models, but must be tested under the same 4060 workload. PR #772 documents a working measured MTP configuration and failed combinations. If changing the inference engine version, benchmark again: CUDA graph, backend kernels, quant support and GPU allocations can change.

### 4. Improve *correct* development throughput, not only tokens/sec

For Litha's Rust/Roblox/Blender/game development: (a) first generate a minimal plan with compact model, (b) retrieve verified reference code/API documentation, (c) generate bounded candidate solutions, (d) compile/lint/type-check/test in the appropriate sandbox, (e) repair the failing case only, (f) compare final build/visual screenshot against explicit rubric, (g) record approved lessons with source provenance. Existing `litha/pr_fixer.py`, `star/compute_frontier.py`, quality evaluation and local Rust components already cover some steps; **don't claim a model is smarter because it is more verbose or faster**. In a verified A/B compare build pass rate, regression introduction, test pass on unseen examples, meaningful tool use, Studio scene integrity, and total time to *passing* output.

### 5. Preserve the GPU for the VTuber/game workload

RTX 4060 NVENC/AV1 support is useful for streaming, but encoding still requires input/output GPU buffers and coexists with rendering, voice and inference. Prefer a 4B Q4 model during live sessions, 9B quality-first when the game is closed or observed headroom permits, and schedule larger quantized/CPU-assisted models for idle/off-hours experiments. Measure actual rendered frame interval, audible speech latency, GPU allocation and temperature, not theoretical peak compute alone.

### 6. Quantization is a quality–memory frontier

Q4_K_M is a useful starting point, **not** a universal optimum. Test Q8_0 4B against Q4 9B and LFM text-only MoE on the *same* held-out coding and tool tasks. The quality gap between model families is workload-dependent; more bits on a weaker model are not automatically better. If trying IQ/quants/special CUDA kernels, pin the exact GGUF hashes, llama.cpp build commit, quantizers, architecture support and acceptance results. Never make 4-bit precision silently count as proof of accurate Luau/game building.

## Required paired quality/performance gate before any default change

1. **Reproduce a baseline:** record GPU/CPU/driver, exact installed engine build and model digest, free/peak dedicated VRAM, active game/OBS/VLM load, quantization, context, sampler, seed, parallel slots, K/V type and temperature. Separate cold-load, warm-load and warm-cache trials.
2. **Run 20+ balanced paired trials per workload** across quick chat, long prompt, tool-call JSON, real Rust compilation, Luau type checks, Studio UI hierarchy/scene verification, image understanding and simultaneous game/OBS speech. Randomize A/B order while preserving identical inputs; no exposing private artifacts in benchmark files.
3. **Measure P50/P95** first visible output, complete request, uncached prefill TPS, decode TPS, correct answers per second, peak dedicated VRAM, memory/pageouts and interruption of game FPS or voice. A 20% throughput gain with doubled TTFT or corrupted tool JSON is a regression for the owner.
4. **Fail closed** on bad JSON, cached-answer contamination, silent CPU layer fallback when forbidden, missing memory measurements, incomplete response, unacceptable gameplay FPS, visual defects or held-out correctness loss. Streaming or kernel support failures revert to previous configuration.
5. **Approve before enablement:** inspect `star.compute_frontier`, `star.inference_ab`, existing sealed evaluation gates and the Litha-specific code/CI checks. Until the actual owner's Windows 4060 is measured, everything above remains a candidate. No model, auto-updater, cloud provider, scope policy or `main` promotion is changed by this PR.

## Specific integration and maintenance notes

- **`litha/gpu_model_catalog.py`** is an offline planning aid, not a model router. It takes observed available dedicated GPU VRAM as an argument. Do not use its rough size estimate to bypass any existing GPU/scheduling gate.
- **`litha/ollama_probe.py`** is a new optional Ollama measurement path, while the existing STAR code remains on llama.cpp. It is intentionally single-threaded so a 4060 can be tested without memory-multiplying parallelism. It requires a running loopback Ollama instance and an explicitly installed model. No automatic model downloads or config mutations.
- **`star/local_runtime.py`** gains only opt-in validated Flash Attention and cache-type flags. The existing default argv is byte-for-byte equivalent for old callers. A caller that uses the optional flags should do so only for a supervised experiment and restore default after. If the local llama.cpp executable doesn't support the flags, startup may fail normally.
- **Tests** cover fake Ollama JSONL streams, fail-closed counters, malformed/partial results, no output text, model-name/path sanitization, plan bounds and default-preserving llama.cpp argument behavior. All tests are offline synthetic and do **not** establish 4060 throughput.

## Evidence and source index (primary where available)

- RTX 4060 VRAM/memory specifications: https://www.pny.com/pny-geforce-rtx-4060-8gb-verto-dual-fan ; https://www.nvidia.com/en-us/geforce/news/ultimate-guide-to-4060/
- Qwen model tags and official model architecture: https://ollama.com/library/qwen3.5/tags ; https://huggingface.co/Qwen/Qwen3.5-9B
- Liquid MoE model card and Ollama packaging: https://www.liquid.ai/blog/lfm2-5-8b-a1b ; https://ollama.com/library/lfm2.5/tags
- Official DeepSeek checkpoints: https://github.com/deepseek-ai/DeepSeek-R1
- Ollama server settings and API counters: https://github.com/ollama/ollama/blob/main/docs/faq.mdx ; https://github.com/ollama/ollama/blob/main/docs/api.md
- llama.cpp runtime flags and benchmark identity: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md ; https://github.com/ggml-org/llama.cpp/blob/master/tools/llama-bench/README.md
- RTX 4060 laptop 9B engine observation (not same GPU as desktop): https://www.nidhiyashwanth.com/blog/local-ai-benchmark
- 3090 32K 9B performance/VRAM observation (not portable): https://localagentbench.com/models/qwen3.5-9b/
- Project's earlier measured 4060 FFN/MTP PR: https://github.com/oncoursemail/Star-AI-Project/pull/772
- Existing STAR A/B integrity candidate: https://github.com/oncoursemail/Star-AI-Project/pull/712

**Evidence status:** Research claims above are source-attributed; new Python checks are synthetic/offline. No claim of RTX 4060 measured improvement, model installation, Windows native execution, Litha self-improvement, GPU fit verification, or deployed routing is made in this change.
