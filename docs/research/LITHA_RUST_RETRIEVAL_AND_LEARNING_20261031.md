# Litha: implemented Rust retrieval, faster example reuse, and correct Rust verification

Date: 2026-10-31. Source baseline: `star/next` at
`9fcb2b257446ede0ca82d33e222e470a51bcc838`. The current `main` reference was inspected
at `d9b0876d6af2c9e2068ddba6286ff97204313d8f`; this work targets the owner's active
Litha integration branch, `star/next`, on a separate draft feature branch.

## Outcome

This change implements three improvements in the existing application:

1. An optional Rust extension accelerates dense documentation retrieval inside
   the running Python service.
2. The existing worked-example retriever reuses corpus statistics and visits
   relevant token postings instead of rebuilding and scanning the whole corpus
   for every question.
3. Rust generation, compilation, repair and answer-cache admission respect the
   requested edition and distinguish an unverified result from a clean compile.

The implementation has measured CPU retrieval gains and regression coverage.
Model weights, training, inference kernels and production services have not been
changed. The native backend remains explicitly opt-in. This is an implementation
and benchmark result, rather than evidence of a general intelligence increase.

## Measured performance

Measurements used synthetic data in an isolated Linux x86_64 development
environment, Python 3.12.14, and a release-built Rust 1.90.0/PyO3 0.27.2 extension.
No private corpus, external model, GPU, live application or recorded conversation
was involved. Final dense measurements ran after compilation finished.

| Operation | Previous median | Candidate median | Stage speedup |
| --- | ---: | ---: | ---: |
| Dense search, 2,000 vectors × 384 dimensions | 15.7790 ms | 1.3832 ms, Rust | 11.408× |
| Dense search, 10,000 vectors × 384 dimensions | 83.5567 ms | 5.8166 ms, Rust | 14.365× |
| Dense search, 10,000 vectors × 384 dimensions | 83.5567 ms | 77.4262 ms, Python heap | 1.079× |
| Warm worked-example ranking, 500 examples | 0.7418 ms | 0.2331 ms | 3.183× |
| Complete worked-example selection, including SQLite read and context construction | 2.0252 ms | 1.3725 ms | 1.476× |

Dense search uses `k=8`, 30 measured queries per corpus after warmup, and the
previous query implementation as the control, including Python 3.12's existing
native `math.sumprod`. All returned ranks and scores matched across the 60
measured queries; observed maximum score error was zero. At 10,000 vectors, p95
fell from 90.7617 ms to 8.9932 ms. Extremely close unequal floating-point scores
can still order differently on other inputs or interpreter versions; there is
no universal bit-for-bit arithmetic guarantee.

The isolated process peak RSS for the 10,000-vector run was 37,748,736 bytes for
the previous query method and 33,660,928 bytes for Rust, approximately 10.8%
lower on this workload. Both held 15,440,000 bytes of packed vector/ID payload.
These observations are not a universal RAM reduction or a process-memory cap.
Startup timings use the current validated Python loader in both Python arms;
they are not a historical before/after startup comparison.

Worked-example measurements use 12 queries and 160 repetitions per arm,
alternating arm order. The benchmark asserts exact equality of scores, returned
rows and rendered context. Initial corpus-index construction with warm term
data took 1.4922 ms, an up-front cost amortized by repeated queries.

Raw measurements and samples:
[litha-rust-retrieval-benchmarks-20261031.json](litha-rust-retrieval-benchmarks-20261031.json).
Reproduction scripts:
[`benchmarks/litha_dense.py`](../../benchmarks/litha_dense.py) and
[`benchmarks/worked_example_retrieval.py`](../../benchmarks/worked_example_retrieval.py).

## Rust implementation and memory behavior

`native/litha_search` supplies an immutable `DenseIndex`. Initialization consumes
the SQLite cursor once into packed float32 values and int64 passage IDs. Native
mode keeps no duplicate Python embedding corpus. A query sends one small query
vector to Rust, computes compensated float64 dot products while detached from
the Python interpreter, and retains a top-k heap. Equal scores keep corpus
order. No per-query process launch or extra worker pool is involved.

The native search remains an exhaustive scan: O(N × D) dot-product work, with
O(k) result memory and O(N log k) heap work in the worst case. The improvement
comes from eliminating Python iteration/object traffic and avoiding a full
result sort. The default Python implementation also gets bounded top-k result
selection.

The default packed payload budget is 512 MiB, configurable by the service host.
Dimension, row, finite-value and query checks are explicit. Malformed stored
vectors are skipped and counted. Budget exhaustion disables the dense corpus
as a whole, allowing exact API lookup and SQLite BM25 to continue. The service
avoids embedding requests when no usable dense corpus exists. The payload
budget excludes interpreter, SQLite, allocator capacity and temporary memory;
operators should size it with actual process headroom.

The wheel is optional, with a pinned dependency and Cargo.lock. Python remains
the default backend. Missing/incompatible native installations fall back to
Python, and `/health` exposes the requested backend, active backend, fallback
reason, vector count/dimension and packed bytes. Build, enable, rollback and
platform details are in the
[native package README](../../native/litha_search/README.md).

## Faster reuse of worked examples

`star/worked_examples.py` already token-cached individual examples. It still
rebuilt document frequencies, lengths and other corpus statistics on every
query. The new two-entry cache keys those statistics by exact ordered content
and uses token postings to identify eligible rows.

Every `select()` call still reads the current SQLite rows and applies the
existing project/expiry rules. The cache stores scoring data; returned IDs,
metadata and answer text come from the current rows. Edits, additions, removals
and ordering changes produce a different key. Oversized corpora bypass this
extra cache. API-term extraction now stops at its existing first-50-match bound
without materializing all later regex matches.

This makes learned-example reuse cheaper. It does not train the language model
or change which examples are approved. Existing provenance labels, prompt
budgets, import limits, expiry, opt-in setting and review policy remain intact.

## Rust coding and verification corrections

The previous generation note and compiler recipes hard-coded the 2021 edition.
Explicit 2015, 2018, 2021 and 2024 targets now propagate through the note, verifier
and isolated compiler/test-run recipe. The unspecified default remains 2021.
Unsupported or conflicting targets stay unverified. Edition selection does not
install or silently upgrade a toolchain.

Compiler errors continue to drive repair. Timeouts, missing external crates and
failed invocations with no usable diagnostics now produce an unchecked result.
The previously hard-coded `rustc 1.99` tool label is removed. A Rust repair whose
candidate cannot be checked is rejected.

Two additional correctness problems were found during independent review:

- Rust source strings/comments could look like an edition request. Raw typed
  source and Markdown fences, including unfinished, tilde and longer-backtick
  fences, are now excluded from edition inference. A real Cargo TOML edition
  declaration remains usable context.
- The threaded verifier shared a context-free memoization dictionary. Two
  requests compiling identical code under different editions could reuse one
  another's outcome. The cache is now thread-local and keyed by language, code
  and context. Mixed-language work still runs in one shared parallel compiler
  batch, with appropriate context per language.

The router now forwards the original question during cache admission and
revalidation, rejects incomplete/malformed Rust verification, and identifies
Rust-targeted raw or unlabelled code instead of treating it as unchecked prose.
Rust-language and edition conflicts prevent inappropriate semantic reuse. An
upstream body timeout closes its connection. Normal prose answers retain their
existing behavior.

**Historical cache qualification:** stricter checks apply to new admissions and
new verification attempts. Previously stored Rust answers do not gain compiler
provenance automatically. Background revalidation still serves existing rows
first and leaves inconclusive rows until their existing expiry. Before relying
on a deployed cache as fully compiler-verified Rust knowledge, independently
revalidate legacy Rust rows and quarantine failed/inconclusive entries using
the existing authenticated administration path. This patch does not delete
user data or perform that migration.

## Verification and operational status

The development environment built and installed a release ABI3 Linux wheel.
The final affected Python regression run completed with **529 passed and 4
skipped in 30.60 seconds**. All four skips are existing sandbox cases requiring
an unavailable Luau runtime. The two Rust unit tests, Clippy with warnings
denied, rustfmt, Python compilation, Ruff on changed Python files and
`git diff --check` also passed. Python tests cover ranking parity, corruption,
fallback, resource bounds, concurrent requests, exact text cache freshness,
edition handling, incomplete verification and repair behavior.
Two trusted fixtures invoke the actual Rust 1.90 compiler in metadata-only mode:
the same let-chain construct succeeds under edition 2024 and fails under 2021.

Reproduce the affected Python suites from the repository root, with the release
wheel and Rust compiler available:

```bash
python -m pytest -q tests/test_mesh*.py tests/test_litha*.py \
  tests/test_worked_examples*.py tests/test_learned_week.py \
  tests/test_learning_bundle_validation.py -rs
python -m benchmarks.litha_dense --rows 10000 --dimension 384 --repeats 30
python -m benchmarks.worked_example_retrieval --rows 500 --repeats 160
```

Publication is a draft PR. Live services, models and settings were not changed.
The connected-device tool reported its monthly usage limit; Windows EXE,
target-machine GPU/CPU, live inference and production deployment tests could
not be performed in this session. Build and verify the native wheel on each
target platform before considering activation. `dense_in_block` remains off,
preserving the earlier decision about harmful broad guide injection.

## Research decisions and next measurements

The chosen boundary follows PyO3's guidance to detach substantial Rust-only
work and batch crossings into native code. Maturin supplies release wheels
without changing the main Python application. Rust ownership helps manage
lifetimes and packed data, but the algorithms and explicit limits determine
actual allocation behavior.

llama.cpp already implements inference in C/C++. Rewriting its Python caller
does not establish faster model decoding. Further inference work should measure
the installed backend's actual supported prefix caching, context/slot sizing,
KV-cache types, batching and offload behavior against a fixed task set. Record
first-token latency, complete accepted-answer latency, RAM/VRAM and pass rate
under representative foreground workloads. A retrieval-stage speedup cannot be
applied as a multiplier to an entire turn.

Faster learning should be measured as verified new tasks solved per unit of
time/compute, with transfer to held-out tasks and checks for regressions. Indexed
knowledge, reused examples, successful practice and model-weight training are
distinct outcomes. The present work improves the retrieval and verification
parts of that loop; it supplies no evidence of accelerated weight training.

### Primary sources reviewed

- [PyO3 parallelism](https://pyo3.rs/main/parallelism): interpreter detachment and native concurrency.
- [PyO3 performance](https://pyo3.rs/main/performance.html): native boundary costs and substantial Rust-only work.
- [Maturin tutorial](https://www.maturin.rs/tutorial): Python extension wheels and release builds.
- [Rust ownership](https://doc.rust-lang.org/book/ch04-01-what-is-ownership.html): ownership/lifetime semantics.
- [Rust 2024 edition](https://doc.rust-lang.org/edition-guide/rust-2024/index.html): edition and toolchain distinction.
- [Rust let chains](https://doc.rust-lang.org/edition-guide/rust-2024/let-chains.html): the edition-specific compiler fixture.
- [rustc JSON diagnostics](https://doc.rust-lang.org/rustc/json.html): structured diagnostics and compatibility handling.
- [llama.cpp server](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md): native inference and backend configuration.
- [llama-bench](https://github.com/ggml-org/llama.cpp/blob/master/tools/llama-bench/README.md): separate prompt/decode measurements.
- [SQLite FTS5](https://www.sqlite.org/fts5.html): the existing native lexical search alternative.
- [Tokio blocking work](https://docs.rs/tokio/latest/tokio/task/fn.spawn_blocking.html): bounded CPU work and cancellation limits; no Tokio pool was added.

These are upstream references checked during implementation. Installed versions
remain authoritative for supported APIs/flags; links to upstream development
branches can change.
