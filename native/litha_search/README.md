# Litha dense retrieval accelerator

An optional, CPU-only Rust/PyO3 implementation of exact dense passage search.
Python remains the default. This module does not change the language model,
enable GPU work, contact a provider, or enable dense passages in the chat block.

## What changes

The current docs service reads normalized float32 embeddings from SQLite. The
native backend reads that cursor once into a packed immutable index. Each query
copies only its own vector across the Python boundary. Search releases Python's
GIL, computes float64 dot products, and retains a bounded top-k heap rather than
allocating and sorting a result tuple for every passage. No worker pool or
per-query subprocess is created. The Python fallback also uses bounded top-k.

The native backend retains no second Python copy of the embedding corpus. It
does retain its own IDs and float32 values; this is not a memory-mapped index or
an approximate nearest-neighbor implementation. Query cost remains O(N × D),
with O(k) result storage and O(N log k) heap work in the worst case.

## Build and enable

Use Rust 1.83 or newer and Python 3.11 or newer in a build environment. PyO3 is
pinned and Cargo.lock is checked in. Maturin is a build dependency only; it is
not added to Litha's runtime requirements.

```bash
cd native/litha_search
python -m pip install 'maturin>=1.9,<2'
maturin build --release --locked
python -m pip install target/wheels/<platform-specific-wheel>.whl
```

Build wheels on each target platform. The verified Linux wheel does not prove
Windows packaging or Windows performance. A debug build is inappropriate for
performance measurement. Do not enable unsafe compiler fast-math options.

In the existing docs service JSON configuration, explicitly set:

```json
{
  "dense_backend": "rust",
  "dense_max_vector_bytes": 536870912
}
```

Restart that docs service after installing the wheel/configuring the backend.
`GET /health` reports the requested and active backend, fallback reason, vector
count, dimension, invalid-row count, and packed vector payload bytes. If the
extension is missing or ABI-incompatible, the service uses Python and reports
`native_unavailable`; an incompatible module API reports `native_api_mismatch`.
Switch `dense_backend` back to `python` to roll back without rebuilding the
database. Nothing in this package deploys or restarts a live service.

## Limits and numerical behavior

- A valid row contains 1..65,536 native-endian float32 values. This preserves the
  existing builder's storage format; databases are not portable across endian
  formats. The first valid row establishes the dimension.
- Malformed, nonfinite, or dimension-mismatched stored rows are skipped and
  counted. Query dimension mismatch/nonfinite values produce no dense results;
  exact lookup and BM25 can still answer.
- At most 1,000,000 stored vector rows are inspected. The configured payload
  limit counts packed vectors plus 8 bytes per ID. Exceeding either limit disables
  the entire dense index, with a visible `vector_resource_limit` reason, instead
  of serving a partial index. The service then avoids embedding requests.
- The payload budget is **not an RSS cap**. Python, SQLite, temporary query
  buffers, allocation capacity and startup allocation peaks require additional
  memory. Provision headroom and measure on the target host.
- IDs are loaded in SQLite primary-key order. Exact equal-score ties retain
  corpus order, including all-zero query vectors.
- Normalization remains in Python and yields float32 query values. Native dot
  products use compensated float64 accumulation. This limits drift relative to
  Python 3.12 `math.sumprod`, but does not promise bit-for-bit equality for every
  floating-point input or interpreter version. Extremely close unequal scores
  can change order; acceptance tests check score tolerance and actual ranks.

## Verify and benchmark

From the repository root, with the optional release wheel installed:

```bash
python -m pytest -q tests/test_litha_dense.py tests/test_mesh_docs.py
python -m benchmarks.litha_dense --rows 10000 --dimension 384 --repeats 20
```

The benchmark uses seeded synthetic normalized embeddings and the exact prior
query method as its control, including `math.sumprod` when present. It starts
one isolated process per backend, warms each query path, records all latency
samples, and checks rankings and scores. Index startup uses the current loader
for both Python variants, so its startup measurement is not a historical
before/after startup comparison. Linux/macOS peak RSS is reported separately
from packed payload; unsupported platforms report null.

Run the benchmark without concurrent compilation or other heavy workloads.
Results apply to this retrieval stage on the measured host. They are not model
token throughput, GPU utilization, learning speed, or full-agent latency.

```bash
cd native/litha_search
cargo test --locked
cargo fmt -- --check
cargo clippy --locked --all-targets -- -D warnings
```

Some relocated Python distributions require their actual libpython directory in
the linker/runtime search path for `cargo test`. Building an extension wheel
does not normally link libpython on Linux, whereas a standalone Rust test binary
does. Configure the build environment instead of changing the runtime package
to hardcode a machine-specific path.
