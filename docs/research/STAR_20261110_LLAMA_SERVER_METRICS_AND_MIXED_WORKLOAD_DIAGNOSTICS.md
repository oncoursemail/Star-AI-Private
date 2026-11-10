# STAR — llama.cpp server telemetry and mixed-workload inference diagnostics

**Date:** 2026-11-10  
**Status:** implemented as an opt-in, read-only diagnostic; no runtime defaults changed.

## Why this matters

STAR already has a mixed-workload client benchmark and a paired model comparator. Those tools measure the time at which the client receives its first non-empty text chunk, end-to-end request time, and gaps between chunks. That is useful user-experience evidence, but it is not the same as the inference engine's internal prompt-processing and decode rates. Client timings also include HTTP scheduling, transport, server queueing, and chunk delivery.

The next useful step is to capture the model server's own documented counters during the same controlled experiment. This makes it easier to distinguish:

- prompt prefill pressure from token-generation pressure;
- queue contention from slow model execution;
- a speculative-decoding configuration with useful accepted drafts from one that adds overhead without enough accepted tokens;
- a client-visible delay from an engine-side throughput regression.

It still does not identify a single request or prove a GPU speedup. The llama.cpp counters are cumulative server observations and can include other clients.

## Primary-source findings

### llama.cpp metrics endpoint

The current upstream server documentation states that GET /metrics is available only when the server is started with --metrics. In router mode, the request must include ?model={model_id}. The documented series include:

- prompt tokens and prompt-processing seconds;
- generated tokens and generation seconds;
- average prompt and generation throughput gauges;
- requests currently processing and deferred;
- the maximum context-token high-water mark;
- decode-call and busy-slot averages;
- speculative draft-token, accepted-token, and draft-step counters.

Source: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md#-metrics-prometheus-compatible-metrics-exporter

The same README shows that /slots can expose request parameters and generation-prompt fields. STAR intentionally does not call /slots; the new adapter reads only the aggregate /metrics text and retains only a small allowlist of numeric series.

### AIPerf measurement semantics

NVIDIA AIPerf distinguishes request latency, time to first token (TTFT), inter-token latency (ITL), token counts, and derived throughput. Its documentation notes that client-observed TTFT includes queueing, prompt processing, transport, and first-token delivery, while ITL measures the generation interval after the first token. STAR's client-side first_content_ms remains explicitly labelled as first-content, not tokenizer-level TTFT. The new server counter rates are separate measurements, not substitutes for AIPerf's per-request traces.

Sources:
- https://docs.nvidia.com/aiperf/reference/ai-perf-metrics-reference
- https://docs.nvidia.com/aiperf/dev/server-metrics/ai-perf-server-metrics-reference

### Generalist and game-development evaluation

Speed must be paired with task quality. Roblox's OpenGameEval evaluates agents in reproducible, stateful Studio sessions and scores both scene changes and simulated play; it also separates observation from editing so exploration can be measured. This supports STAR's existing inspection-first, execute-and-verify approach rather than selecting a model from latency alone.

Sources:
- https://github.com/Roblox/open-game-eval
- https://arxiv.org/abs/2610.02563

## Implemented

New module: star/llama_server_metrics.py.

### Read-only collection

- Derives /metrics only from the configured http://127.0.0.1:<port>/v1 or http://localhost:<port>/v1 endpoint.
- Uses direct loopback HTTP only: no proxy, redirects, credentials, arbitrary host, query string, or fragment.
- Uses GET only and sends no authorization header.
- Limits response size to 128 KiB, 2,048 lines, and 4,096 characters per line.
- Parses only documented, unlabelled scalar metrics; unknown series are ignored, duplicate or malformed supported series are rejected.
- Rejects non-finite and negative values, malformed UTF-8, and oversized bodies; detects counter regressions and invalidates affected rates.
- Supports the router's optional model query, validated with STAR's existing model-alias validator.
- Does not store prompts, completions, audio, screenshots, viewer identities, credentials, or raw server responses.

### Window analysis

Two snapshots produce a bounded aggregate report with:

- prompt tokens/second from counter deltas;
- generated tokens/second from counter deltas;
- speculative accepted-draft / draft-token ratio when the needed counters are present and consistent;
- before/after processing, deferred-request, throughput, and busy-slot gauges;
- counter-reset and missing-counter lists;
- context-token high-water mark;
- explicit scope and attribution warning.

A server restart or counter reset invalidates that counter's rate instead of producing a negative or misleading result. Missing metrics remain missing; the tool does not invent a fallback rate.

### CLI

Run the monitor in one terminal while the already-running local benchmark runs in another:

~~~powershell
python -m star.llama_server_metrics --endpoint http://127.0.0.1:8080/v1 --duration-seconds 120 --output artifacts/llama-metrics.json
~~~

For llama.cpp router mode, pass the exact router model ID:

~~~powershell
python -m star.llama_server_metrics --endpoint http://127.0.0.1:8080/v1 --model star-fast --duration-seconds 120 --output artifacts/star-fast-metrics.json
~~~

The server must already have been started by the owner with --metrics. If it has not, STAR reports the optional diagnostic as unavailable; it does not restart the server or change its command line. The monitor does not launch the paired benchmark itself, so start the two commands close together and avoid unrelated requests during the measurement window.

## How to interpret the measurements

| Observation | What it can suggest | What it cannot prove |
|---|---|---|
| Low prompt tokens/s with healthy generation tokens/s | Prompt prefill, context length, or prompt-cache reuse may be the bottleneck | Which individual prompt was slow |
| Low generation tokens/s | Decode/runtime/model placement may be the bottleneck | GPU utilization or a specific kernel bottleneck |
| requests_deferred above zero | The server had queued work at the snapshot | Queue wait duration or which client queued it |
| requests_processing above one | Multiple requests were active at the snapshot | Whether concurrency helped or hurt a particular user turn |
| Higher speculative acceptance ratio | More proposed draft tokens were accepted in that window | Net speedup; draft generation and verification still have costs |
| Higher n_tokens_max | The server has seen a larger context during its lifetime | Current slot occupancy or remaining context capacity |

Do not tune the RTX 4060's GPU-layer count, context, parallel slots, quantization, KV cache, or speculative decoding from one window. Compare repeated paired runs with identical model files, runtime builds, settings, and workloads. Then check general-knowledge, reasoning, Luau, game-strategy, and tool-use quality on held-out tasks.

## Next integration priorities

1. Join server metrics, client paired timings, and a privacy-scrubbed Windows run manifest using a single experiment ID and monotonic window boundaries.
2. Add native Windows GPU/VRAM, CPU/RAM, game frame-time, OBS render/encode drops, audio underruns, and avatar reaction timing from separately authorized host adapters.
3. Compare idle, game-only, game+OBS, and full game+OBS+TTS+avatar workloads on the actual Windows target.
4. Keep general-knowledge and game-development quality gates paired with every speed experiment; do not promote a faster but materially less capable model.
5. Use real Roblox Studio inspect/build/playtest checks and unseen game scenarios before claiming creation quality or game mastery.

## Limits

This change is a diagnostic and evaluation improvement, not a runtime scheduler, model router, model-weight update, training system, or GPU optimization. It does not enable --metrics, start a server, change inference settings, run a Windows benchmark, read GPU telemetry, launch OBS, capture audio, control an avatar, play a game, or broadcast. Server counters are aggregate and may be affected by concurrent clients or server-version behavior. A real RTX 4060 measurement and a private full-stack Windows rehearsal are still required before claiming any measured speed or streaming improvement.
