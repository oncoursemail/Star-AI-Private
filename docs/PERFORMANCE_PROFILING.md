# Measuring STAR inference speed without guessing

STAR's interactive latency has at least four parts: time waiting for a model slot,
prompt prefill/reprocessing, decoding, and network/display overhead. Increasing
agent count can **increase** latency when those agents share a memory-bandwidth-
limited CPU or the same model slots. The normal short benchmark measures
time-to-first-visible-text (TTFT), not server queue time on its own.

## Opt-in measurements

No code in this guide is run automatically. These commands use fixed synthetic
prompts and the model/provider you explicitly choose; they do not read chats,
source files or Roblox places, and do not change model settings.

For an already running loopback llama.cpp server on the PC:

```powershell
python -m star.brain_benchmark --model YOUR_MODEL_ID --scenario chat --runs 4 --parallel 1
python -m star.brain_benchmark --model YOUR_MODEL_ID --scenario chat --runs 4 --parallel 2
```

For STAR Server (private LAN), with its address/key already saved in STAR Settings
or provided through `STAR_SERVER_API_KEY`:

```powershell
python -m star.brain_benchmark --server --model star-fast --scenario roblox --runs 4 --parallel 1
python -m star.brain_benchmark --server --model star-fast --scenario roblox --runs 4 --parallel 2
```

Use `--parallel 1..4` and no more parallel requests than `--runs`. Start with 1
and 2, not 4. Run only while the server is free of other test/evaluation jobs,
or **explicitly record** the competing load. A benchmark is a real inference
workload: it competes with interactive chat, and therefore should not be launched
during a live latency incident.

## Comparing two runs (before/after a change)

Save each run's output to a file, change one thing, run again with the same model,
scenario, target and `--parallel`, then compare. No request is sent by `--compare`:

```powershell
python -m star.brain_benchmark --model star-fast --scenario chat --runs 8 > before.json
python -m star.brain_benchmark --model star-fast --scenario chat --runs 8 > after.json
python -m star.brain_benchmark --compare before.json after.json
```

Sample i of each file is paired and scored with the exact sign test and bootstrap
interval from `star/eval_stats.py` (the eval gate's statistics). `decision` is
`PROMOTE` (faster, exit 0), `REJECT` (slower, exit 1) or `INCONCLUSIVE` (exit 4);
unusable or unlike files exit 2. Fewer than 5 runs per arm can never be
significant at alpha 0.05. The arms run one after the other, so check that the
machine was otherwise idle both times. This is speed evidence only; answer quality
still needs the eval gate.

## Reading the output

- `median_ttft_ms` and `p95_ttft_ms`: elapsed before the first visible text.
  These **include** queueing, prompt work and first-token decode, but cannot
  separately attribute them.
- `median_total_ms`, `p95_total_ms`: full streaming reply time.
- `requests_per_second` and `aggregate_output_tokens_per_second`: measured over
  the wall clock for the whole group (the latter only if every response reports a
  completion-token count). Use both TTFT and throughput to decide whether adding
  slots helps or merely slows each interaction.
- `median_prompt_tokens_evaluated`, `median_prompt_tokens_cached`,
  `median_prompt_eval_ms`: **optional** server-reported counters from llama.cpp
  `timings`. Absent fields are omitted, never assumed zero. They depend on the
  server version, request shape, and model template. A lower prompt-token count
  on repeated requests suggests prefix reuse but doesn't demonstrate that the
  user-facing answer got faster or became more correct.
- `output_chars_per_s` is **not** model token generation rate.

For a defensible before/after result, preserve model/quantization/template,
prompt, token budget, host, concurrent background workload, and slot configuration.
Use at least 3 repetitions and compare p95 TTFT, total throughput, and content
quality. Since repeated prompts may benefit from server caching, also benchmark
fresh conversation prefixes with the existing session tests before declaring
a cold-start win.

## Release gates

1. For responsiveness work, require repeatable improvement in interactive p95
   TTFT **without** new errors or regressions in long-request throughput.
2. For changing which model answers a Roblox task, do **not** infer quality
   from timing or static Luau success. Run the evaluation suite and use the paired
   quality gate in [evals.md](evals.md), with a blind holdout that was never used
   to select a routing policy.
3. For background scheduling, preserve the interactive capacity reservation and
   compare with offline jobs active. Do not automatically alter CPU affinity,
   models, permissions or network destinations based on this report.

Relevant local studies: `docs/agents/chat-speed-20261013.md`,
`docs/agents/brain-performance-20261013.md`, and
`docs/research/multi-model-20261014.md`.
