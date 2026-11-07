# Primary-source register

Checked November 1, 2026. This register records what a source supports and how it affects STAR. Marketing speed claims are not STAR measurements. Versioned project manifests and installed service specifications take precedence over moving documentation.

## PYO3_PERF

[PyO3 performance](https://pyo3.rs/main/performance.html)

**Supports:** Boundary allocations and conversions matter; detach for Rust-only computation.

**STAR decision:** Batch operations and measure the complete Python call, not just the kernel.

## PYO3_CURRENT

[PyO3 current ABI features](https://pyo3.rs/main/features)

**Supports:** Current documentation distinguishes abi3 and abi3t.

**STAR decision:** Do not apply moving-documentation features to the pinned 0.27.2 dependency without an explicit upgrade.

## PYO3_PIN

[PyO3 0.27.2 features](https://pyo3.rs/v0.27.2/features.html)

**Supports:** Version-specific extension-module and abi3 feature documentation.

**STAR decision:** Use this versioned reference with the existing Cargo manifest.

## MATURIN

[Maturin distribution](https://www.maturin.rs/distribution.html)

**Supports:** Wheel portability depends on platform libraries, tags and build environment.

**STAR decision:** A successful local build does not establish clean-machine Windows or Linux compatibility.

## PYTHON_ABI

[CPython C API and ABI stability](https://docs.python.org/3/c-api/stable.html)

**Supports:** abi3 and the Python 3.15 abi3t stable ABI have different compatibility rules.

**STAR decision:** Test interpreter/build flavors separately; stable ABI is not a cross-OS binary format.

## PYTHON_FT

[CPython free-threading guide](https://docs.python.org/3/howto/free-threading-python.html)

**Supports:** Unsupported native extensions can re-enable the GIL.

**STAR decision:** Record the actual runtime GIL state after imports; never assume an interpreter label proves parallelism.

## RUST_PROFILES

[Cargo profiles](https://doc.rust-lang.org/cargo/reference/profiles.html)

**Supports:** Release optimizations, LTO and codegen units are configurable; higher optimization is not universally faster.

**STAR decision:** Keep existing thin LTO as a baseline and compare controlled profiles.

## RUST_PGO

[rustc profile-guided optimization](https://doc.rust-lang.org/rustc/profile-guided-optimization.html)

**Supports:** PGO uses instrumented execution profiles in a subsequent optimized build.

**STAR decision:** Train profiles on representative development workloads, then validate on held-out workloads.

## RUST_CODEGEN

[rustc code generation options](https://doc.rust-lang.org/rustc/codegen-options/index.html)

**Supports:** Target CPU/features and code generation choices affect generated binaries.

**STAR decision:** Separate portable release builds from machine-specific experiments.

## TOKIO

[Tokio spawn_blocking](https://docs.rs/tokio/latest/tokio/task/fn.spawn_blocking.html)

**Supports:** Running blocking tasks are not stopped by abort; CPU tasks need bounded concurrency.

**STAR decision:** Use cooperative deadlines or isolated processes for hard termination, and separate CPU from I/O scheduling.

## RAYON

[Rayon ThreadPoolBuilder](https://docs.rs/rayon/latest/rayon/struct.ThreadPoolBuilder.html)

**Supports:** A configurable worker pool can bound CPU parallelism.

**STAR decision:** Use a shared measured CPU budget instead of one unrestricted pool per agent.

## REQWEST

[Reqwest Client](https://docs.rs/reqwest/latest/reqwest/struct.Client.html)

**Supports:** The client maintains a connection pool and is intended for reuse.

**STAR decision:** A future Rust network service should reuse clients and retain privacy/URL policy.

## ASYNCIO

[Python asyncio runners](https://docs.python.org/3/library/asyncio-runner.html)

**Supports:** asyncio.run manages a loop and executor lifecycle; Runner supports reuse.

**STAR decision:** Profile lifecycle overhead before proposing a Rust service rewrite.

## SQLITE_FTS

[SQLite FTS5](https://www.sqlite.org/fts5.html)

**Supports:** FTS5 provides native full-text indexing, BM25 and maintenance controls.

**STAR decision:** Optimize current native SQL queries before adding a parallel search engine.

## SQLITE_WAL

[SQLite write-ahead logging](https://www.sqlite.org/wal.html)

**Supports:** WAL enables concurrent readers and a writer with checkpointing and same-host requirements.

**STAR decision:** Do not treat WAL as unlimited multiwriter concurrency or place its shared-memory design on a network filesystem.

## NUMPY

[NumPy global configuration](https://numpy.org/doc/stable/reference/global_state.html)

**Supports:** Linear algebra may use threaded BLAS beneath Python.

**STAR decision:** Coordinate BLAS, native search and inference thread budgets.

## ARROW

[Apache Arrow columnar format](https://arrow.apache.org/docs/format/Columnar.html)

**Supports:** Contiguous typed buffers support data locality and shared-memory access.

**STAR decision:** Use explicit ownership and schema/version metadata; zero-copy is not a universal promise.

## TANTIVY

[Tantivy repository](https://github.com/quickwit-oss/tantivy)

**Supports:** Rust full-text search library with a Lucene-inspired design.

**STAR decision:** Candidate only when the existing FTS5 index fails measured scale or feature requirements.

## USEARCH

[USearch repository](https://github.com/unum-cloud/USearch)

**Supports:** Native similarity search with multiple bindings, including Rust.

**STAR decision:** Candidate for a separate approximate-search experiment; compare recall and binding-specific features.

## TOKENIZERS

[Hugging Face Tokenizers](https://huggingface.co/docs/tokenizers/index)

**Supports:** Rust-backed tokenization with alignment tracking.

**STAR decision:** Reuse compatible native tokenizers rather than reimplementing a model-specific tokenizer.

## SAFETENSORS

[SafeTensors repository](https://github.com/safetensors/safetensors)

**Supports:** Tensor storage format designed for safe tensor loading and efficient access.

**STAR decision:** Treat tensor parsing separately from executable model repositories and trusted model identity.

## LLAMA_SERVER

[llama.cpp server](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)

**Supports:** Native inference with prompt-cache, scheduling and decoding controls.

**STAR decision:** Benchmark installed-version features with fixed model, template and quantization.

## LLAMA_BENCH

[llama.cpp benchmark](https://github.com/ggml-org/llama.cpp/blob/master/tools/llama-bench/README.md)

**Supports:** Separates prompt-processing and generation tests; tokenization and sampling are excluded from its timings.

**STAR decision:** Use engine benchmarks alongside, not instead of, end-to-end accepted-task latency.

## CANDLE

[Hugging Face Candle](https://github.com/huggingface/candle/blob/main/README.md)

**Supports:** Rust ML framework with native CPU and GPU backends.

**STAR decision:** Evaluate narrow model-serving deployments, not an automatic replacement for a mature LLM backend.

## BURN

[Burn backend/device guide](https://burn.dev/books/burn/building-blocks/backend.html)

**Supports:** Supports device/backend selection through supported Cargo features.

**STAR decision:** Require model/operator/precision equivalence before comparing runtime implementations.

## ORT_IO

[ONNX Runtime I/O binding](https://onnxruntime.ai/docs/performance/tune-performance/iobinding.html)

**Supports:** Input/output placement and binding can avoid unnecessary device transfers.

**STAR decision:** Measure copies and synchronization for embeddings, rerankers and vision workloads.

## ORT_THREADS

[ONNX Runtime threading](https://onnxruntime.ai/docs/performance/tune-performance/threading.html)

**Supports:** Intra-op and inter-op thread pools are separate performance controls.

**STAR decision:** Avoid nested oversubscription during concurrent local model tasks.

## CXX

[CXX Rust/C++ bridge](https://cxx.rs/)

**Supports:** Typed Rust/C++ interop with generated boundary checks.

**STAR decision:** Reuse established C++ engines through narrow bindings when justified; it does not prove arbitrary foreign code safe.

## NAPI

[NAPI-RS getting started](https://napi.rs/docs/introduction/getting-started)

**Supports:** Native Rust extensions for a Node.js host.

**STAR decision:** Use only for a real Node-hosted compute bottleneck, not directly from STAR browser React components.

## WASMTIME

[Wasmtime security](https://docs.wasmtime.dev/security.html)

**Supports:** Documents the runtime sandbox and its security assumptions.

**STAR decision:** Consider restricted untrusted plugins with explicit host capabilities and resource limits, not native in-process execution.

## FUZZ

[Rust Fuzz Book](https://rust-fuzz.github.io/book/cargo-fuzz.html)

**Supports:** cargo-fuzz integrates coverage-guided fuzzing through libFuzzer.

**STAR decision:** Fuzz parsers and boundary validation with bounded fixtures; fuzzing is not a proof of correctness.

## DENY

[cargo-deny](https://embarkstudios.github.io/cargo-deny/)

**Supports:** Checks dependency advisories, sources, bans and licenses.

**STAR decision:** Record database freshness and distinguish an unavailable advisory check from a clean result.

## MIRI

[Rust Miri](https://github.com/rust-lang/miri)

**Supports:** Interpreter-based detection of certain undefined behaviors.

**STAR decision:** Apply to supported pure Rust tests; native FFI and driver paths still need separate checks.

## CRITERION

[Criterion.rs](https://bheisler.github.io/criterion.rs/book/)

**Supports:** Statistical microbenchmarking with repeated measurements.

**STAR decision:** Keep kernel measurements distinct from full-call and application measurements.

## LEMONADE

[Lemonade FAQ](https://lemonade-server.ai/docs/guide/faq/)

**Supports:** Documents comparable llama.cpp performance for the same model and quantization, and last-completion statistics.

**STAR decision:** Treat runtime management as the integration benefit until target-host benchmarks establish a speed benefit.

## RUST_FFI

[Rustonomicon foreign function interface](https://doc.rust-lang.org/nomicon/ffi.html)

**Supports:** Foreign ownership, representation and unwinding need explicit boundary contracts.

**STAR decision:** Avoid ad hoc raw pointer interfaces and panic/exception propagation assumptions.

## Repository evidence

- [Inspected development snapshot](https://github.com/oncoursemail/Star-AI-Project/tree/e672fd7b76ad24dac8f5f7f1fd67cc167fa6c829).
- [Merged Rust retrieval PR #849](https://github.com/oncoursemail/Star-AI-Project/pull/849). Its measurements are historical PR evidence, not independently rerun full-native benchmarks in this package.
- [Pinned native manifest](https://github.com/oncoursemail/Star-AI-Project/blob/e672fd7b76ad24dac8f5f7f1fd67cc167fa6c829/native/litha_search/Cargo.toml): PyO3 =0.27.2, abi3-py311, Rust minimum 1.83, edition 2021, thin LTO, one codegen unit.
- [Existing native implementation guide](https://github.com/oncoursemail/Star-AI-Project/blob/e672fd7b76ad24dac8f5f7f1fd67cc167fa6c829/native/litha_search/README.md).

## Access limitations

The AnythingLLM API documentation page returned HTTP 403 during this follow-up. The archived bridge research retains its previously inspected source snapshot and API contracts. Live interoperability was not inferred from that historical source. A cargo-audit repository page could not be retrieved in this follow-up; cargo-deny documentation supports the dependency-check recommendations without claiming a fresh audit ran.
