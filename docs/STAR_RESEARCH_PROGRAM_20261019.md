# Star AI responsiveness and quality program

Prepared 19 October 2026 by ChatGPT. This is an engineering proposal, not a measured model-quality result or a deployment instruction. Existing routing, resource-planning, cache/context and current research/repair branches were inspected; this work improves the existing page-reader path and does not replace them.

### The integrated improvement

The old reader created a 15-second deadline, but awaited DNS outside it and parsed HTML on the event loop. A stalled resolver could keep a caller waiting beyond the stated budget; extraction could delay unrelated async work. The candidate patch propagates the same monotonic deadline through DNS, redirects, HTTP reading, decoding and extraction. Four dedicated DNS workers and two dedicated parser workers bound submitted blocking work; admission fails clearly when a pool is occupied. The underlying concurrent future retains its slot until the blocking operation actually finishes.

This ownership detail matters: cancelling a coroutine does not kill a running OS resolver or parser. Releasing its slot immediately would let successive timed-out calls accumulate hidden work. Python documents running-future cancellation and timeout cleanup behavior, and HTTPX's per-operation timeouts are distinct from one cumulative application deadline. [R02-R04]

The public-address checks, destination pinning, TLS SNI/Host handling, redirect checks, byte/type limits, and untrusted-page framing remain intact. The focused tests use mocked HTTP and deterministic blocking events. They establish deadline/cancellation behavior and continued event-loop progress; they do not measure real websites, model tokens per second, or a percentage increase in intelligence. An ordinary GIL-enabled Python worker thread also does not turn parsing into unrestricted CPU parallelism.

### The next quality and speed program

1. Record queue time, time to first useful output, input/prefill tokens, output tokens, tool latency, retry work, and final task success separately. A fast first token can still precede a slow or wrong completed task.
2. Route short classification, extraction and UI work to the configured fast model; reserve deeper reasoning for tasks that need it. Use uncertainty and evaluator outcomes to escalate. Avoid routing every message to every model.
3. Reserve foreground capacity. Pause or admit indexing, batch experiments and long research according to observed CPU, memory, disk and game-quality budgets. Scheduling policy must account for both Star and Metallic on shared machines.
4. Reuse stable prefixes and scoped retrieval results where their identities match. Cache keys need project/user scope, source revision/content, model/tokenizer version, policy and relevant settings. Revalidate time-sensitive evidence. Prefix reuse primarily reduces prefill work, not the cost of generating every new output token. [R05-R06]
5. Make research auditable: fetch source pages, attach observation dates, distinguish claims from inferences, record conflicts, and stop when key questions have enough evidence. More parallel searches do not automatically mean a better answer.
6. Use parallel agents for independent bounded investigations, with one synthesis owner. Measure the additional token/tool cost and latency. Published multi-agent research reports benefits and substantial overhead in its own workload; its results are not a Star benchmark. [R07]
7. Repair incrementally: keep the working checkpoint, identify the smallest failing boundary, modify it, run relevant checks and preserve rollback. Recreating a whole feature after a small error wastes time and increases regression risk.
8. Evaluate on fixed tasks with objective acceptance criteria, held-out cases, security-boundary checks and human GUI review. Star must not rewrite the tests or answer key to certify itself. Track regressions by task type and device as well as aggregate scores.

Before tuning inference concurrency, compare one and two simultaneous foreground requests with realistic prompts and sustained background load. Measure p95/p99 completion and total resource use, not only aggregate throughput. Test context and cache budgets rather than assuming maximum values help. Existing llama.cpp features are candidates to evaluate on the actual host; switching to vLLM or SGLang is not an automatic improvement for a CPU-oriented deployment. [R05-R06]


## Validation and rollout

See `STAR_FETCH_RESPONSIVENESS_20261019.md` for the precise implementation and regression evidence. Root independently reran the documented focused suite: 61 passed, 2 deselected. The two broader agent integration tests remain outside the partial inspection checkout. Existing test fixtures were preserved; the new file tests the added deadline/worker behavior. The change requires normal PR review and application-level validation before release. No model service was restarted and no provider settings were changed.

## Primary sources

- R01: Linux pressure-stall information — https://docs.kernel.org/accounting/psi.html
- R02: Python async tasks, timeout and cancellation — https://docs.python.org/3/library/asyncio-task.html
- R03: Python concurrent futures — https://docs.python.org/3/library/concurrent.futures.html
- R04: HTTPX timeouts — https://www.python-httpx.org/advanced/timeouts/
- R05: llama.cpp server capabilities — https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md
- R06: vLLM automatic prefix caching — https://docs.vllm.ai/en/latest/features/automatic_prefix_caching/
- R07: Anthropic multi-agent research system — https://www.anthropic.com/engineering/multi-agent-research-system
