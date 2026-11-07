# STAR performance audit, bridge fixes, and Rust pilot

**Date: October 30, 2026.**

## Decision

Use a hybrid architecture, not an immediate full Rust rewrite. Keep STAR's existing Python orchestration, React/TypeScript UI, local inference engines, knowledge ownership and Core Forge lifecycle. Port a bounded computation into Rust only when a profile and an end-to-end benchmark show a worthwhile gain. Keep an ordinary Python fallback.

This session produced a corrected standalone Litha bridge and a tested Rust experiment. **Neither was installed into STAR's live runtime, merged into GitHub, or demonstrated to make live model responses faster.** Litha and STAR remain separate projects.

## 1. What was actually checked

The original archive contained 14 files. Its SHA-256 is `5e0e8f07008db2d2e5b3df2ac4e48ce7cccca0a00242a83963e6d1fb6d96f082`. The Python source, configuration, proposed workflow, documentation and tests were inspected. The original 25 tests were rerun successfully in the assistant's Linux environment using Python 3.13.5. These are mock-service tests, not live Lemonade or AnythingLLM integration tests.

The connected private STAR repository's README, `star/context_layout.py`, and `server/knowledge/starkb/search.py` were read. The actual local Core Forge checkout was also inspected on `starai`:

- Checkout: `<CORE_FORGE_CHECKOUT>`.
- Branch: `feat/star-core-forge-local-20261025`; observed revision: `e941c121`.
- No tracked `.rs` or `Cargo.toml` files were returned by the targeted Git listing.
- The working tree was clean before inspection and after the isolated Python benchmark.
- Existing benchmarks already include chat-turn overhead, imports, persistence, code-search caching, skill routing and Luau linting. A second competing performance framework is unnecessary.

The checked STAR code already contains prompt-prefix-aware message layout and hybrid lexical/vector retrieval. The latter uses SQLite FTS5 and NumPy-backed vector operations. Do not assume everything beneath a Python function is interpreted Python, or replace an existing knowledge system with a duplicate merely to add another product.

## 2. Reproduced bridge defects and fixes

| Finding | Original behavior / risk | Change in reviewed candidate |
|---|---|---|
| Unbounded chat admission wait | The semaphore context manager had no timeout. A request remained waiting after the configured network timeout; that timeout never applied to admission. | Separate configurable `queue_timeout_seconds`, default 5 seconds. Expiry fails before this call sends provider requests. Permits are released in `finally`. |
| Evidence trace mismatch | A controlled probe sent a 1,200-character excerpt to the model but returned a 5,000-character source object. The extra text had not been supplied as evidence. | Returned source text now matches the exact excerpt supplied to the model, without mutating the original hit. |
| Malformed model metadata | `labels=None` raised an uncontrolled `TypeError`; a string label could be checked using substring membership rather than capability-list membership. | Validate label arrays and recipe types, returning a sanitized provider error before generation. |
| Loosely typed settings | Programmatic `lemonade_enabled="false"` was truthy. Fractional or boolean values could enter integer settings. Environment boolean parsing was already stricter. | Strict boolean and integer validation; finite numeric timeout checks. |
| Aggregate prompt growth | Per-message limits permitted many large messages in one request. | Aggregate character ceiling, default 50,000; checked before provider I/O. This is not a model-token budget. |
| Citation parser robustness | Converting an arbitrarily long citation ID to an integer could raise an exception. Noncanonical IDs could normalize into an accepted number. | Compare bounded-source identifiers as strings; invalid or huge identifiers trigger review rather than integer conversion. |

The revised candidate passes **42 offline tests**, including 17 new test methods. Some methods exercise multiple invalid-input cases. This does not establish production security, live interoperability, Windows compatibility of the bridge, or answer quality. The proposed GitHub CI was not run.

### Important limits that remain

The adapter's generation path is still **non-streaming**. It must not replace STAR's interactive streaming provider unchanged. It still requests the installed-model catalog before every generation and creates a new urllib opener for requests. Those are optimization candidates, not defects to remove blindly: cached model metadata can become stale or misrepresent a changed routing policy.

Queue admission is bounded **per client instance**, not across all instances, processes or devices. Socket inactivity timeouts are not strict total-request deadlines. A complete host integration needs a shared resource governor, cancellation and request deadlines; this patch does not claim those features.

Workspace authorization remains the host application's responsibility. A developer API key may span several workspaces. A `[S1]` string is still only a mechanical citation check, not evidence that the source supports the claim. Feature flags remain OFF by default. No remote cloud fallback, download, tool execution or model installation was enabled.

## 3. Actual STAR Python-side timing

The repository's existing `benchmarks/bench_chat_turn.py` was run on the `starai` machine. It uses a fake model, a private temporary app-data folder, 200 synthetic current-chat history messages and 20,000 synthetic messages in other chats. Outbound Python socket connections were blocked for these runs. BLAS/OpenMP thread counts were limited to one, and the process ran at a lower scheduling priority. There was one warm-up followed by 12 timed turns.

| Measurement | Unprofiled run | Separate cProfile run |
|---|---:|---:|
| Median turn overhead | **35.15 ms** | 39.83 ms |
| Reported P90 | 38.83 ms | 43.07 ms |
| Minimum | 29.63 ms | 35.67 ms |
| Import `desktop_core` | 617.2 ms | 691.2 ms |

These numbers are **not** live AI answer latency, full application startup, a production RAG benchmark, or streaming time-to-first-token. The short sample does not establish a stable production percentile. It does establish that this tested fast-mode fixture does not spend seconds in its Python orchestration.

The profile recorded 0.507 seconds across the timed fixture. Relevant cumulative entries included event-loop runner exit/close (~0.137/0.136 seconds), `chat_history_snapshot` (0.107 seconds), and `source_digest` (0.093 seconds). These are overlapping cumulative timings, not additive categories. Investigate lifecycle reuse and repeated checkpoint validation before rewriting broad modules. Do not skip source validation: use request-scoped reuse or a trustworthy revision identifier, with tests for edits, deletions, restoration and cross-project isolation.

No change to those STAR functions was made in this session. Their timing suggests candidates for a targeted follow-up, not a proven optimization.

## 4. Rust experiment on the user's Windows machine

The pilot reimplements the rank-fusion semantics of STAR's `merge_facets(..., how="rrf")`: weight two for the whole query, weight one for each facet, reciprocal-rank constant 60, and stable first-seen tie ordering. It is a standard-library-only program with `unsafe` code forbidden. It bounds input bytes, ranking count and entry counts. It is **not** a replacement model, vector database, or production Python binding.

Environment: Windows 11, Python 3.15.0, rustc 1.99.1. Rust was already installed. No new toolchain or model was installed. The test files are isolated under `<USER_HOME>\star-speed-review-20261030`; no STAR service was stopped or reconfigured.

**9 Rust unit tests passed. 40 deterministic/randomized cross-language cases matched ranking order and numerical scores within the specified tolerance.** The archive's Rust and Python harness hashes match the exact files tested on Windows.

Five measurement samples were taken per workload, alternating measurement order. Each workload contains seven ranking lists. These are synthetic sizes, not measurements of actual STAR query frequency.

| Entries per ranking | Total input entries | Python median | Rust kernel median | Kernel-only ratio |
|---:|---:|---:|---:|---:|
| 50 | 350 | 0.0788 ms | 0.0185 ms | 4.25x |
| 500 | 3,500 | 0.9472 ms | 0.2033 ms | 4.66x |
| 5,000 | 35,000 | 11.5308 ms | 2.2400 ms | 5.15x |

**These ratios are not STAR speedups.** The smallest case saves only about 0.060 milliseconds inside the computation. A microbenchmark can have a large ratio and almost no visible application effect.

Starting a separate process for each request was dramatically worse in this observed environment: median wall times were approximately **427, 454 and 643 milliseconds**, respectively. These measurements include subprocess launch, pipe I/O, native parsing/formatting, scheduling and execution. They do not identify the cause of the high launch/transfer cost. Even the experiment's amortized subprocess measurements were slower than the Python computation for these batch sizes. The machine was not isolated from other workloads, and some samples show substantial noise; do not treat these as universal Rust/Windows constants.

**Decision: do not install this command-line prototype as a per-request replacement.** A future production experiment should use an in-process batch interface such as PyO3, or a persistent worker when process isolation is genuinely needed, and measure conversion/IPC overhead. Neither option was implemented or timed here. For small rank lists, retaining Python may be the best engineering choice.

## 5. Recommended STAR architecture

Keep the React/TypeScript UI and Python task orchestration. Keep inference in a proven native engine such as the existing llama.cpp setup; its model computations are not Python loops. Add Rust extensions only for profiled, sufficiently large work such as indexing, parser-heavy processing, batched ranking, evidence processing or sustained media preparation where end-to-end measurements justify it.

PyO3 supports native Python extension modules and detaching from the Python interpreter during Rust-only work. Its documentation also highlights boundary allocation and conversion costs. Batch work rather than crossing the boundary for each token or tiny chunk. Maturin can package mixed Python/Rust projects into wheels, but supported target interpreters, OSes, architectures, crash behavior and fallback installation still need explicit testing. [1,2]

Tokio is a candidate for a justified high-concurrency I/O service, not a generic way to make CPU loops faster. Its documentation recommends considering dedicated CPU executors for CPU-heavy parallel work. Blocking tasks need bounded concurrency, and already-running `spawn_blocking` work is not automatically cancelled by aborting the async handle. Avoid adding a Rust sidecar merely because it sounds faster. [3,4]

### Priority A — eliminate avoidable waiting

Instrument one trace from submission to usable answer: queue wait, retrieval, prompt assembly, model load/switch, prompt processing, first output, decoding, validation, persistence and UI delivery. Reuse STAR's existing benchmarks rather than invent another disconnected scorecard. Preserve streaming and measure first meaningful output, not just the first SSE packet.

Use one admission policy per model/device and prioritize foreground chat/voice over bulk indexing and night-school work. A per-client semaphore is not sufficient as a system-wide limit. Bound concurrency by measurements and memory headroom, not the number of desired agents. Benchmark one, two and four active jobs before changing defaults.

Review event-loop/client lifetimes and repetitive history checks. Reusing a persistent loop or connection pool may help, but cancellation, shutdown, thread ownership and Qt integration must remain correct. Test these changes without simultaneously changing the model.

### Priority B — improve the inference and context path

Keep stable instruction/project prefixes and append volatile per-turn evidence after stable content. STAR already has code for this. Measure actual cache reuse, cold versus warm loads, context length, model switches, and inference settings; do not assume a cache flag means every request benefits.

The llama.cpp server documents native CPU/GPU inference, parallel decoding, continuous batching, speculative decoding, and prompt-cache controls. These are candidate experiments with the installed engine/model, not guaranteed wins. Fix model, quantization, request length, output length, hardware and correctness criteria while comparing. [5]

Lemonade is useful as an optional inference/runtime management provider. Its own FAQ states that performance is similar to llama.cpp when using the same model and quantization. Merely adding another HTTP layer is not an intelligence or speed multiplier. Retain the existing provider when it wins. [6]

### Priority C — spend saved time on verified capability

Keep STAR's knowledge, memory, permissions and Core Forge authoritative. AnythingLLM can be evaluated as an optional external retriever or as a source of design patterns; do not automatically duplicate chat state, agent execution, model routing and vector storage.

Use retrieved, versioned, approved evidence and small task-relevant tool sets. For coding/game-building, allocate extra candidates only when task difficulty and the resource budget justify them; run executable checks and visual/playtest checks, stop when an acceptable candidate passes, and escalate when tests fail. This is a proposed quality-per-time strategy, not a new capability claimed from this session.

Core Forge should keep the baseline, experiment, evidence, version history and rollback locally. GitHub is optional for publication, not a prerequisite for improvement. Keep native acceleration off until it passes an agreed gate, and retain a tested Python fallback.

## 6. Proposed promotion gate

A useful gate is a material end-to-end improvement, for example at least 10% better warm P95 on the selected representative workload, with no meaningful task-quality regression and no privacy or authorization failures. That percentage is a proposed engineering threshold, not an observed result.

Compare source retrieval, grounded answers, Luau tests and visual/playtest checks as appropriate, not just tokens/second. Separate cold load, warm inference, short requests, long context, single-user latency and concurrent throughput. Keep held-out tasks out of optimization/training. Repeat enough trials for uncertainty estimates; five microbenchmark samples and twelve synthetic chat turns are not sufficient for a production promotion.

Windows and Linux packaging, restart, cancellation, peak RAM/VRAM, cache invalidation, model/version pinning, fallback correctness and rollback are still required before shipping a Rust component.

## 7. Files and reproduction

- `litha-bridge-reviewed/`: standalone candidate, version 0.1.1; no runtime dependencies; features off.
- `bridge-review.patch`: reviewable changes against the original package, excluding generated bytecode.
- `rust-pilot/rrf_pilot.rs`: bounded standard-library Rust experiment.
- `rust-pilot/benchmark.py`: parity tests and synthetic benchmark harness.
- `results/`: original and revised test logs, reproduced defects, STAR fixture results, profile summary, Windows measurements and provenance.
- `probe_original.py --source /path/to/original/src`: reproduce the original bridge defects without cloud calls.
- `MANIFEST.sha256`: package file checksums.

Run the reviewed bridge tests from its directory:

```sh
PYTHONPATH=src python -m unittest discover -s tests -v
```

On PowerShell, set `$env:PYTHONPATH='src'` before the same unittest command. The bridge was tested in the assistant's Linux environment; no claim is made that its GitHub workflow or Windows test matrix ran.

The Rust pilot was compiled and tested on Windows; see its README for commands. No Rust compiler was available in the assistant container or on the inspected `starai` PATH, so no Linux Rust build is claimed.

## Primary references

[1] PyO3 performance and interpreter detachment: https://pyo3.rs/main/performance.html

[2] Maturin mixed Python/Rust packaging: https://www.maturin.rs/

[3] Tokio's intended uses and CPU-bound caveats: https://tokio.rs/tokio/tutorial

[4] Tokio blocking concurrency and cancellation: https://docs.rs/tokio/latest/tokio/task/fn.spawn_blocking.html

[5] llama.cpp server features and controls: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md

[6] Lemonade performance comparison: https://lemonade-server.ai/docs/guide/faq/

Inspected repository code: https://github.com/oncoursemail/Star-AI-Private/blob/main/star/context_layout.py and https://github.com/oncoursemail/Star-AI-Private/blob/main/server/knowledge/starkb/search.py . Local Core Forge snapshot hashes are in `results/provenance.json`.

## Status boundary

**Completed:** package audit, reproduced failures, targeted bridge fixes, 42 offline bridge tests, Windows native pilot, 9 Rust tests, 40 parity cases, synthetic timings, actual STAR offline fixture and profile, and this review package.

**Not completed or claimed:** live inference speedup; better model weights or intelligence; live Lemonade/AnythingLLM interoperability; in-process Python/Rust integration; production security certification; a full Rust migration; GitHub commit/PR/CI; installation into either Litha or STAR; packaged STAR Windows release changes. The active Core Forge working tree remains unchanged.
