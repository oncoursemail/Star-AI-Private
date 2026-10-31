# STAR Compute Frontier — optimize with evidence, not guessed speedups

This is an **offline, non-deploying hardware optimizer** for STAR's CPU server and
8 GB-class desktop GPU. It analyzes repeated official llama.cpp llama-bench JSON
measurements on the same physical machine and weights. It can identify candidates
worth a second test but never changes the live model, priority, policy or model
endpoint.

## Why

An LLM can be memory-bandwidth bound, CPU synchronization bound, VRAM limited,
prompt-processing bound, or constrained by other jobs. Setting 48 threads does
not guarantee an advantage over 24. Filling RAM to 100% can cause swap stalls,
and offloading to GPU only helps when the memory and transfer budget works.
Optimize the **measured work completed per second without quality regression**.

## Use, with owner-selected quiet benchmarking window

1. Ensure no active desktop chat, background practice, game server load or
   duplicate model worker would be disrupted. Use the existing STAR planner
   quiet-lock procedure. Do not run a second model if free RAM is insufficient.
2. Use the same GGUF model, build, hardware, quantization and KV configuration
   for all trials. Example commands are illustrative only:

       llama-bench -m /owner/model.gguf -t 24 -p 512 -n 128 -r 5 -o json > baseline.json
       llama-bench -m /owner/model.gguf -t 12,16,24,32 -p 512 -n 128 -r 5 -o json > candidates.json

3. If an external read-only memory probe is used during the *same* trial,
   append peak_ram_mib and peak_vram_mib per benchmark row; these keys are
   optional, and the evaluator does not fabricate values.
4. Compare:

       python -m star.compute_frontier baseline.json candidates.json \
         --min-gain 0.05 --max-ram-mib 24576

   Only pass --max-vram-mib when there is a measured VRAM budget and per-row
   peak_vram_mib; otherwise the output cannot establish VRAM headroom.

## Decision rules

- Reject different model files, builds, hosts, backend, quantization or KV types.
- Every baseline workload must have a matching candidate workload.
- Detect individual prompt/generation workload regressions before considering
  the geometric mean. Flag noisy/low-margin results for retest.
- Use mean +/- 2 standard deviations only as a conservative **variability
  heuristic**. This is NOT a confidence interval or statistical acceptance gate.
- An accepted candidate is only "worth_latency_and_quality_gates": next test
  whole-turn p95 first-token latency, requests/second under contention, actual
  memory peaks, and the sealed STAR holdout-quality evaluation. No automatic
  deployment, main-branch merge, runtime reconfiguration or GPU workload starts.

## Higher-impact candidate experiments, in priority order

1. **CPU thread/NUMA sweep.** Compare 12/16/24/32 generation threads on the
   real server, with one prompt and one decode test. Verify both throughput and
   p95 during simultaneous retrieval. Do not assume max logical threads wins.
2. **Memory-aware MoE placement.** Keep always-active attention and nonexpert
   layers on the faster device when possible; compare controlled n-cpu-moe and
   -ngl variants on a GPU host. This is not applicable to the CPU-only server.
3. **KV cache reuse.** Reuse identical trusted prefixes without treating cached
   user content as common cross-project data. Cache success is a measured input
   token reduction, not added model knowledge.
4. **Speculative decoding.** For compatible models, compare verified accepted
   tokens/second with n-gram or MTP draft modes; turn off when acceptance
   overhead outweighs the benefit.
5. **Background scheduling.** Protect foreground interaction with STAR's
   existing resource planner; use idle capacity for parallel candidate
   generation, isolated test cases and off-hours learning. Never let parallel
   jobs starve the main model or Roblox Studio.

## Boundaries and sources

The tool does not assert that hardware has more VRAM than physically installed,
or that a faster, lower-bit quantized model is equivalent in quality. GGUF filename
equality alone cannot verify weight bytes. The release gate and held-out test
suite remain independent.

- Official llama-bench formats and throughput definitions:
  https://github.com/ggml-org/llama.cpp/blob/master/tools/llama-bench/README.md
- llama.cpp server: offloading, KV, MoE and speculation controls:
  https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md
- SGLang speculative decoding documentation:
  https://docs.sglang.ai/advanced_features/speculative_decoding.html
- vLLM chunked prefill throughput/latency trade-offs:
  https://docs.vllm.ai/en/stable/configuration/optimization/
