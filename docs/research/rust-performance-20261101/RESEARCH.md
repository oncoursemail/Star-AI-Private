# STAR: Rust, mixed-language performance, and verified capability

**Research date:** November 1, 2026. **Disposition:** publish research and isolated experiments; do not replace or activate the live backend.

## 1. Decision and actual repository state

The best supported direction is a **Python + Rust + established native inference** architecture, not an immediate rewrite of STAR in one language. Keep the product UI, task semantics, permission checks, knowledge ownership, evaluation authority, and Core Forge history intact. Move sufficiently expensive, measured work across narrow native boundaries. Remove duplicate work before translating it.

The inspected development baseline is `oncoursemail/Star-AI-Project`, branch `star/next`, commit `e672fd7b76ad24dac8f5f7f1fd67cc167fa6c829`. The former `Star-AI-Private` repository name resolves to this public repository. PR #849 is **merged**, with merge commit `a5b2270f95b6b7d069edae0e5449050a75922596`. Therefore, the October 30 audit's statement that its inspected checkout contained no Rust is historical, not a current assessment of the development branch.

The existing `native/litha_search` implementation already uses an optional resident Rust/PyO3 dense index. Its manifest pins PyO3 `=0.27.2`, selects `abi3-py311`, declares Rust 1.83 and edition 2021, and uses thin LTO with one codegen unit. The implementation guide describes packed immutable float32 vectors, float64 scoring, bounded top-k, interpreter detachment, resource limits, and visible Python fallback. Preserve this implementation as the native baseline; do not create a second production index to duplicate it. See the pinned repository links in [SOURCES.md](SOURCES.md).

This publication restores the previously unpublished CLI rank-fusion pilot and the reviewed Lemonade/AnythingLLM bridge as **historical, isolated experiments**. It also supplies a current decision record, source register, benchmark protocol, implementation backlog, and a small advisory comparison tool. Nothing here turns a feature on, changes model weights, restarts a service, or modifies the official evaluation gate.

## 2. Separate five different meanings of “faster”

Measure at least five quantities: native kernel time, the complete foreign-language function call, the service request, first meaningful user-visible output, and time until a result actually passes the relevant checks. They answer different questions. A fast vector calculation can coexist with slow embedding requests, model swaps, tool retries, or an overloaded GPU. A stream can begin quickly but take longer to produce a correct answer.

For sequential work, a useful accounting identity is:

`T_accepted = T_queue + T_retrieval + T_context + T_model_load + T_prefill + T_decode + T_tools + T_verification + T_repair + T_delivery`.

For overlapping stages this sum is not a wall-time model: record a trace and measure the critical path, rather than adding nested or concurrent spans. Failed attempts and their elapsed deadlines must remain in the dataset. Otherwise an implementation can appear faster simply because its slow or incorrect runs were discarded.

Amdahl-style reasoning gives a useful upper bound before writing code. If only 5% of total sequential time is improved tenfold, the overall ratio is about 1.047x, not 10x. Improving 40% fivefold gives about 1.471x. These are hypothetical calculations, not STAR measurements. The important engineering question is the fraction of actual user waiting attributable to the proposed port.

The archived Windows pilot illustrates the distinction. It reported 4.25x–5.15x kernel speedups for rank fusion, yet creating a process for each request cost about 427–643 ms in that environment. At the smallest size, the kernel saving was only about 0.060 ms. The old measurements are retained, with their noise and scope warnings; they are not universal Windows costs or a current whole-app benchmark. The publication's fresh test records are kept separately.

Use the existing STAR benchmarks as the starting point. Criterion is suitable for native microbenchmarks, while `llama-bench` separates prompt processing and generation but explicitly excludes tokenization and sampling. Neither substitutes for accepted-task wall time. [CRITERION; LLAMA_BENCH]

## 3. Language responsibilities, not language purity

| Layer | Preferred starting point | Reason to change | Evidence required |
|---|---|---|---|
| Product UI and interaction | Existing React/TypeScript and desktop host | A measured UI/host bottleneck or packaging requirement | Input latency, rendering, accessibility, installer and update parity |
| Task planning, tools, experiments | Existing Python | Substantial repeated CPU work in measured traces | Full-call savings including conversion and error handling |
| Dense retrieval | Existing optional Rust/PyO3 backend | Corpus scale, memory or latency fails its target | Rank/score parity, memory peaks, cold start and concurrent load |
| LLM inference | Existing native inference engine | Another runtime wins for the same model and task | Same tokenizer/template/precision, quality, complete latency and memory |
| CPU batch parsing/indexing | Existing implementation, then selective Rust | Parsing dominates ingestion or interactive workloads | Throughput, allocation, cancellation, provenance and source spans |
| High-concurrency network gateway | Existing service first; Rust/Tokio only if justified | Network concurrency/lifecycle materially limits service | Tail latency, connection reuse, admission, cancellation and recovery |
| Untrusted generated plugins | Separate restricted execution boundary | Need to run code outside a trusted application | Explicit capabilities, resource limits, isolation and auditability |

CXX can help implement a narrow Rust/C++ interface; it is not a reason to rewrite a well-tested native model engine. NAPI-RS applies to a Node.js host, not directly to arbitrary React code running in a browser view. Adding Node to a Python desktop application's hot path solely to reach Rust would create another boundary without an established benefit. [CXX; NAPI]

A native implementation can remove interpreter overhead and enforce useful ownership constraints, but it does not repair an incorrect algorithm or model answer. Conversely, a Python API may already execute its expensive work in native SQLite, NumPy, or an inference engine. Profile beneath the API surface before attributing time to the language. [SQLITE_FTS; NUMPY; RUST_FFI]

## 4. The highest-value Rust boundary is resident and batched

For trusted CPU work, extend the existing in-process approach. Load large immutable state once, keep ownership clear, pass a compact query, compute without calling back into Python, and return only the bounded results the caller needs. Avoid converting every document to a Python dictionary on every request. Record load time and retained memory separately from query time.

A suitable conceptual contract is `Index.build(validated_snapshot)`, followed by `Index.search(query, k, scope)`, plus a versioned health/status contract. This is an architectural sketch, not a newly implemented public API. An index handle should identify the corpus revision, embedding model, vector dimension, dtype, normalization policy, scope and schema. Construct a replacement snapshot off the request path and publish it atomically; requests already using the old snapshot must finish against the matching metadata.

PyO3's performance guide describes conversion/allocation overhead and detachment for Rust-only work. The relevant metric is the complete Python-to-Rust call, including input conversion and output construction. Keep Python objects out of detached work unless the pinned API explicitly permits the intended use. Avoid repeated small calls, per-token native callbacks, and acquiring locks in an order that can deadlock with interpreter attachment. [PYO3_PERF; PYO3_PIN]

Use three benchmark variants when evaluating a native port: the unchanged baseline; an improved Python algorithm; and Rust implementing the same improved algorithm. Otherwise an O(N log N) to O(N log k) algorithm change can be incorrectly advertised as a language-only gain. The existing dense implementation already uses bounded top-k in its Python fallback, which makes this comparison especially important.

Choose a persistent worker process only when crash isolation, incompatible runtimes, or privilege separation justifies IPC. Benchmark serialization, framing, copying, queueing and process health separately. A long-lived process removes launch-per-request overhead, but it still requires request IDs, bounded queues, cancellation behavior, restart policy, and protection against duplicate side effects. Keep the archived CLI as an experiment, not a request-time production adapter.

## 5. CPU and RAM: data layout and algorithms before more threads

Packed float32 vectors require approximately `N * D * 4` bytes before IDs, capacity, metadata and temporary buffers. For 10,000 vectors of dimension 384, the vector payload is 15,360,000 bytes, about 14.65 MiB. For one million such vectors it is 1,536,000,000 bytes, about 1.43 GiB. These are calculated payload sizes, not process RSS measurements. Python object overhead, SQLite buffers, allocator capacity, source text and a simultaneous index rebuild can make the process much larger.

The native guide correctly distinguishes its packed-payload limit from a process memory limit. Preserve that distinction. A rebuild that temporarily holds old and new indexes can exceed the steady-state budget. Track peak working set/RSS, build scratch space, page faults and total headroom. A memory cap must fail visibly rather than silently serving an arbitrary prefix of the corpus.

The existing exact search remains O(ND). Rust can improve constants, but it does not remove this scaling law. Keep exact search for small or medium authorized corpora where it is fast enough. Evaluate an approximate index such as USearch only in a separate experiment with recall, deletion, metadata filtering, update cost and memory measurements. Its Rust binding does not imply every feature or performance property of another binding is identical. [USEARCH]

Likewise, SQLite FTS5 is already a native lexical index. Review query plans, column weighting, tokenization, query bounds and maintenance before replacing it. Tantivy becomes interesting when a measured lexical-search workload requires its features or scale, not merely because it is written in Rust. Maintaining two indexes adds rebuild, deletion and consistency work. [SQLITE_FTS; TANTIVY]

Arrow's columnar design is useful when exchanging substantial typed batches between systems. Do not add it for a few IDs and scores. A zero-copy interface needs compatible layout, alignment, lifetime and mutation rules; shared bytes are not automatically safely shared mutable state. The smallest maintainable representation that meets the workload is preferable. [ARROW]

For ranking correctness, test equal-score ordering, near ties, empty inputs, dimension mismatch, malformed encodings, NaN/infinity, zero vectors, duplicate IDs and resource-limit boundaries. A numerical tolerance alone is insufficient when small score changes alter which source enters a small context window. Record actual top-k IDs and grounded-answer consequences.

## 6. Concurrency should protect interactive work

Rust async is not a CPU accelerator. Tokio is appropriate for concurrent I/O, but blocking a runtime worker with long computation can delay unrelated requests. `spawn_blocking` tasks that have started are not stopped merely by aborting their async handle. Use bounded admission and cooperative cancellation inside trusted long computations, or a disposable process for work that needs a hard kill boundary. [TOKIO]

Rayon provides configurable CPU pools. Treat the pool size as part of a system budget, not a separate maximum for every component. NumPy's BLAS, ONNX Runtime's intra/inter-op pools, inference, asset tools and Rust workers can all compete for the same physical cores and memory bandwidth. Benchmark one, two and four concurrent jobs before increasing defaults, and record foreground P95 as well as batch throughput. [RAYON; NUMPY; ORT_THREADS]

Proposed scheduling classes are interactive text/voice, owner-requested tools, and background ingestion/practice. Reserve headroom for the first class. Background jobs should yield or pause when interactive work arrives. Admission should account for expected memory, active model residency and queue age; priority alone does not guarantee that work already occupying a GPU can be preempted.

The older bridge fix bounds waiting on its client-instance semaphore. That is useful but not a device-wide governor. Several clients or processes can still overload the same inference service. One authoritative admission layer should issue leases for the relevant resource, with deadline, cancellation and cleanup tests. This is a proposed next experiment, not a feature enabled by the archive.

The October 30 profile also suggested Python event-loop lifecycle costs. Python's documented runner behavior provides a plausible lower-risk investigation: reuse an appropriate loop/client lifetime before designing an entire replacement service. Qt/thread ownership, shutdown and cancellation still need tests. A future Rust HTTP service should likewise reuse a Reqwest client rather than recreate its pool for every operation. [ASYNCIO; REQWEST]

## 7. Cache useful work without caching mistakes or leaking scope

Proposed cache keys should include the work's semantic identity, not just the user's text. For retrieval, include authorization scope, corpus/index revision, embedding model, normalization and query parameters. For tokenized prompts, include tokenizer and template identity. For compiled verification, include source hash, language/edition, compiler/dependency identity and verifier version. These are design requirements; inspect each existing cache before changing its format.

A stale authorization or deletion decision is not an acceptable performance trade. Cache tests should cover a document edit, deletion, replacement with the same filename, permission change, model change, process restart and rollback. A cached document title is not proof that the returned excerpt belongs to the current version. Preserve exact evidence spans and source identity through ranking, truncation and answer generation.

Prefer request-scoped reuse first. It can eliminate repeated parsing or digest calculations without introducing long-lived invalidation machinery. Use a persistent content-addressed cache only where the version key and storage lifecycle are trustworthy. Keep immutable published snapshots, and make the difference between requested and active backend observable.

STAR's prompt-layout work and the model server's prefix cache are related but not identical. The server must actually see a compatible prefix under the same template and cache state. A changing tool list, history truncation or model switch can invalidate reuse. The llama.cpp server documentation also cautions that different batching paths may not yield bit-identical logits. Evaluate task quality rather than assuming cache reuse is semantically invisible in every backend. [LLAMA_SERVER]

## 8. GPU memory and inference are separate optimization problems

A Rust orchestration rewrite does not multiply GPU VRAM or automatically improve model kernels. Treat the requested 8 GB GPU / 32 GB system-memory class as a target scenario to validate, not as fresh telemetry from every connected machine. Budget model weights, KV cache, scratch buffers, graphics/streaming and other models together. Host-memory offload is a tradeoff involving transfer and memory bandwidth, not free extra VRAM.

For a simplified unquantized dense attention cache, a useful estimate is `2 * layers * kv_heads * head_dim * context_tokens * bytes_per_element`, per resident sequence before implementation overhead. Grouped-query attention uses KV head count, not necessarily query head count. As a hypothetical illustration, 32 layers, 8 KV heads, head size 128, 8,192 tokens and two-byte values produce 1 GiB of raw K/V storage. Real model architecture, quantization, packing, allocation and shared prefixes change the result; inspect the installed runtime rather than making a capacity promise.

Use the existing model engine as control. Compare context length, quantization, GPU offload, prompt-cache behavior, attention implementation, batching and speculative decoding one change at a time where supported. Draft-model work can consume resources that would otherwise serve the target model; measure accepted tokens and complete-task latency, not only the nominal generation rate. Keep model identity and evaluation tasks fixed. [LLAMA_SERVER; LLAMA_BENCH]

Lemonade is useful as an optional runtime/provider boundary. Its own FAQ says the same model and quantization on its llama.cpp backend have similar performance to llama.cpp. A different HTTP wrapper alone is not evidence of faster reasoning. Its last-request statistics also must not be attributed to an arbitrary concurrent caller without correlation. [LEMONADE]

## 9. Rust ML runtimes: evaluate by model, not by brand

Candle is a credible Rust-native ML candidate for a narrowly defined embedding, vision, audio or model-serving workload. Burn supplies another Rust ML architecture with explicit device/backend support. Neither should replace STAR's existing LLM engine without demonstrating the required model architecture, tokenizer/template behavior, operators, precision, quantization, context, cancellation and deployment support. A benchmark with a different model or smaller output is not a runtime comparison. [CANDLE; BURN]

ONNX Runtime is especially worth evaluating for supported embedding, reranking and vision models. Its documentation shows that input/output placement and thread settings can materially affect where work happens. Language bindings alone do not eliminate copies; I/O binding and persistent sessions address a different layer. Validate the actual execution provider and measure transfer/synchronization costs with the same model export. [ORT_IO; ORT_THREADS]

Hugging Face Tokenizers is already Rust-backed. Reusing a compatible implementation can be more sensible than writing a new tokenizer. Token IDs, offsets, normalization, special tokens and the chat template must match the inference engine. Character limits in the archived bridge are protective bounds, not accurate token budgets. [TOKENIZERS]

SafeTensors addresses a tensor-storage boundary. It does not turn arbitrary repository code, custom model loaders, or downloaded binaries into trusted execution. Keep a model manifest with hashes and approved runtime choices; avoid automatic downloads or cloud fallbacks as a side effect of a benchmark. [SAFETENSORS]

## 10. Fewer software mistakes require stronger contracts

Prefer a small safe-Rust core with typed values, bounded input sizes, explicit errors and deterministic tests. However, foreign libraries, unsafe code, concurrent state and semantic mistakes still require review. A native crash can terminate the Python host; a language boundary is not process isolation. Decide which work is trusted enough to run in-process before optimizing it. [RUST_FFI]

Define panic and error behavior at the boundary. Do not assume Python exception handling can recover from arbitrary native aborts, memory faults or an externally terminated process. Avoid unchecked narrowing, unchecked byte-to-number casts, implicit endianness, unbounded allocation, and assuming serialized data has the right dimension. Keep fallback behavior visible and bounded; never silently change privacy or authorization policy when the fast path fails.

Property and differential tests should compare optimized output to a clear reference implementation across generated inputs. Retain stable ties and use realistic near-tie fixtures. Fuzz externally influenced parsers and framing. Miri can detect classes of undefined behavior in supported Rust tests, but it does not replace testing real FFI/driver execution. cargo-deny can inspect dependencies; a stale or unavailable advisory source must not be logged as a clean security result. None of those audits is claimed to have run merely because it is recommended here. [FUZZ; MIRI; DENY]

For generated plugins, keep native acceleration of trusted host code separate from executing untrusted generated native code. Wasmtime is one possible restricted plugin runtime, subject to explicit host capabilities, memory and execution limits, and its documented assumptions. A WASI filesystem/network grant is still authority. Do not equate WebAssembly packaging with an automatic permission policy. [WASMTIME]

## 11. Build, interpreter and packaging discipline

The current PyO3 pin and wheel target are the compatibility baseline. Current PyO3/CPython documentation now distinguishes `abi3` and `abi3t`; ordinary `abi3` does not establish free-threaded compatibility. Do not copy newer feature names into an older pinned crate or claim a shared wheel works across interpreter flavors because it imports on one machine. Test the actual interpreter, extension, packaging tool and GIL state after imports. [PYO3_CURRENT; PYO3_PIN; PYTHON_ABI; PYTHON_FT]

Keep three separable build profiles: a debuggable development/test profile, a portable release baseline, and experimental tuning profiles. The existing manifest already selects thin LTO and one codegen unit, so presenting those settings as a newly applied optimization would be inaccurate. Cargo documentation specifically recommends measurement rather than assuming every higher optimization level wins. [RUST_PROFILES]

Do not ship a generic Windows binary built only for the build machine's CPU feature set. An unsupported instruction can fail on an older owner machine. Use a portable baseline and carefully tested runtime dispatch or explicit architecture variants when needed. Preserve symbols in a suitable diagnostic artifact rather than making crashes untraceable. PGO can help after a stable profile exists, but train it on representative development work and verify separately on held-out workloads. [RUST_CODEGEN; RUST_PGO]

Maturin wheel tags and platform-library checks are part of correctness, not just packaging convenience. Validate a clean Windows installation, Linux compatibility for the intended distribution, missing-extension fallback, incompatible-ABI fallback, startup with no compiler, and uninstall/rollback. A wheel built in one Linux environment is not proof of Windows EXE packaging. [MATURIN]

Prefer an optional prebuilt wheel with a tested Python fallback. Ordinary users should not need a Rust compiler to start the application. Keep compiler toolchains, Cargo caches and build dependencies out of runtime paths. Review dependency lockfiles and upstream/model notices separately; this report does not grant redistribution permission for arbitrary downloaded components.

## 12. Make saved time increase verified capability

The proposed quality strategy is to allocate more of a fixed resource budget to useful checking, not simply to generate more tokens. For a simple request, use the least expensive model/path that meets the task requirements. For a difficult coding or game-building request, generate a bounded number of candidates, run independent checks, and stop when an acceptable candidate is found. Parallel candidates on one saturated GPU can worsen latency, so compare sequential, small-batch and parallel policies empirically.

Measure verified results per unit time together with success rate. A faster failed answer is not an improvement. Relevant checks include compilation and Rust edition compatibility, Luau analysis/runtime tests, exact API validity, source-backed claims, scene geometry/placement checks, visual review and actual Studio playtests where applicable. Synthetic text-only checks must not be relabeled as game quality or visual polish.

Keep the official evaluation fixtures and promotion authority independent from generated candidate code. Core Forge should record the baseline, change, source provenance, test results, failed trials, resource use and rollback point. Retrieved facts, executable skills, episodic memory and model-weight training are different forms of learning and should have different evidence requirements. This package changes no model weights and makes no claim that Rust itself increases reasoning ability.

The new advisory comparison utility is deliberately not a replacement gate. It checks input comparability, paired case coverage, observed correctness regressions and descriptive latency thresholds. It cannot establish that a caller's `verified` flag is true, detect all benchmark bias, prove statistical significance, or authorize deployment. Independent evidence and the existing review process remain necessary.

## 13. Concrete next steps and stop conditions

The ordered backlog is in [EXPERIMENTS.json](EXPERIMENTS.json), with a runnable protocol in [BENCHMARK_PLAN.md](BENCHMARK_PLAN.md). Start with full-request tracing and native fallback/Windows packaging, then request-scoped reuse, shared admission and memory-bounded retrieval. Evaluate a different search algorithm or model runtime only when the current one demonstrably fails the target workload.

A reasonable proposed promotion target is at least 10% better representative warm P95 without observed correctness or scope regressions, plus acceptable cold-start and memory behavior. It is a configurable engineering target, not an observed gain or a statistical guarantee. Use independent sessions, predeclared workloads and enough repetitions to characterize variability. Keep tiny microbenchmark wins classified as local optimizations, not intelligence breakthroughs.

Stop or roll back an experiment when it loses required sources, changes authorization scope, silently uses a remote provider, increases timeout/OOM rates, or worsens interactive tail latency to improve a background throughput score. Rollback should select the prior backend without mutating the stored corpus or deleting evidence. Maintain a simple Python path that can still start when the optional extension is absent.

## 14. Publication and evidence boundaries

The historical archive includes the full reviewed bridge, original-to-reviewed patch, Rust source and harness, synthetic measurements, prior test logs and audit notes. Personal filesystem paths were redacted in three historical files; original and current manifests are distinguished. The archived nested workflow is not a new root GitHub workflow. No secret, user conversation, model weight or compiled binary belongs in this publication.

Fresh validation is recorded in `results/`. Historical Windows timing ratios and PR #849's retrieval results remain labeled as historical reports, not independent replications in this follow-up. New source checking does not establish live Lemonade/AnythingLLM compatibility. This draft is a research and experiment publication, not a full Rust rewrite, automatic merge, runtime activation or release.
