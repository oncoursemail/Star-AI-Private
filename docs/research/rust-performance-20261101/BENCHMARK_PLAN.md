# Reproducible performance and quality protocol

This is a proposed protocol, not a claim that production acceptance has passed. Keep STAR's official independent evaluation gate authoritative. The small helper in this package supports review only.

## 1. Freeze the comparison

Record the repository commit, candidate diff, compiler and flags, Python interpreter and GIL flavor, native extension version, inference server revision, model file checksum, quantization, prompt template, context limit, generation settings, embedding model, corpus revision, checker revision, OS, power mode, CPU/GPU and memory. Identify background workloads. Do not change model, precision, context, quality rubric and language implementation at the same time.

Name the baseline precisely. For dense search compare the earlier algorithm, the improved Python algorithm and the native candidate separately. This prevents attributing bounded-top-k algorithm improvements to Rust. Preserve rejected variants and failed runs.

For a deployment-shaped experiment, include client conversion, metadata lookup, native call, returned-source assembly, queue admission and persistence where applicable. Keep a separate microbenchmark for diagnosing the kernel. Avoid claiming an inference-only number includes tokenization, tool execution or UI delivery.

## 2. Define independent workloads before tuning

Use at least 30 distinct representative cases as an initial review floor, not as a proof of statistical power. Repeated runs of one query do not create independent tasks. Increase independent sessions and workload coverage when variance is large. Reserve held-out cases and do not tune on them.

Cover short chat, long histories, exact API lookup, lexical/vector hybrid retrieval, stale-document removal, multimodal attachment handling, verified coding, missing-source questions and cancellation. Include the user's actual foreground chat/voice plus night-school contention pattern in a separate authorized staging environment. Synthetic vectors and mocked responses are useful for isolation but cannot establish visual/game quality.

Run cold and warm regimes separately. For cold runs define whether the process, model, filesystem cache, connection pool and index have been restarted; do not drop operating-system caches on a live machine. For warm runs declare warmup count and cache state. Randomize or alternate variant order, collect independent sessions, and report all raw observations rather than only best runs.

## 3. Measure the critical path

For each request capture monotonic spans for admission wait, retrieval, prompt assembly, model load/switch, prefill, first meaningful output, decode, tool execution, verification, persistence and UI delivery. Nested spans overlap; do not add their cumulative times as if disjoint.

Report median and empirical P95 with the sample count and an uncertainty analysis appropriate to the sampling design. Bootstrap or other intervals, when used, should resample independent sessions/cases rather than treating correlated tokens or retries as independent. The included helper deliberately does not estimate such intervals.

Count failed and timed-out requests. Record timeouts at their actual terminal deadline; do not discard them or replace their duration with a successful retry. Report success and timeout rates alongside latency. An optimization that returns early with an incorrect or empty answer is not a successful latency improvement.

Capture peak process RSS, allocation peaks, index payload, VRAM usage and contention separately. Payload bytes are not RSS; system RAM is not VRAM; NVENC or UI workloads can share device resources. Hardware budgets in examples are scenarios, not freshly measured telemetry.

## 4. Boundary and failure matrix

Test zero/one/maximum sized input, duplicates, stable ties, near-ties, nonfinite values, wrong dimensions, malformed serialized data, missing corpus metadata, index replacement during queries, stale caches, unauthorized scopes and cancellation. Compare exact IDs, ordering, evidence provenance and numerical tolerance, not only result count.

For PyO3, exercise import on each supported interpreter/OS, missing/incompatible extension fallback, clean startup without Cargo, visible backend health, and correct GIL detachment. Do not assume a plain `abi3` wheel supports a free-threaded interpreter. For a sidecar, include transport/framing, version negotiation, process lifetime, backpressure, crash recovery and orphan cleanup.

For scheduling, evaluate concurrency 1, 2 and 4 only within measured memory headroom. Record foreground tail latency and background throughput independently. Do not multiply Tokio, Rayon, BLAS, ONNX and model-runtime thread pools without a host-level budget. Running blocking work needs cooperative cancellation or appropriate process containment; aborting an async handle is not proof it stopped.

## 5. Quality and privacy acceptance

Use independently maintained checks: Rust compile/test plus correct edition, Luau analysis and execution in the authorized sandbox, API validation, retrieval recall and cited-span support, and geometry/visual/playtest checks where needed. Keep source attribution, corpus version, project/workspace scope and deletion behavior unchanged.

Any newly unauthorized access, silent remote fallback, missing required evidence, correctness regression, OOM increase or unacceptable timeout increase blocks promotion. Even a faster native implementation must preserve the old backend selection and rollback path. Promotion remains separately reviewed and operator-controlled.

A suggested target is at least 10% better representative warm P95 with no quality or scope regression and acceptable cold-start/memory behavior. This is a proposed policy parameter, not a universal rule or observed result. Require uncertainty evidence before interpreting a small numerical difference as a reliable win.

## 6. Runnable isolated checks

From the repository root, without installing the bridge or touching a live service:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=experiments/star-rust-20261101/historical/litha-bridge-reviewed/src \
  python -m unittest discover -s experiments/star-rust-20261101/historical/litha-bridge-reviewed/tests -v
python -m unittest discover -s experiments/star-rust-20261101/tests -v
```

PowerShell uses `$env:PYTHONPATH='experiments/star-rust-20261101/historical/litha-bridge-reviewed/src'` before the bridge command. The bridge suite uses mock loopback services, not live model APIs.

Build the recovered Rust pilot into a disposable directory, not into the source tree:

```bash
rustc --edition=2021 -O --test experiments/star-rust-20261101/historical/rust-pilot/rrf_pilot.rs -o /tmp/star-rrf-tests
/tmp/star-rrf-tests
rustc --edition=2021 -O experiments/star-rust-20261101/historical/rust-pilot/rrf_pilot.rs -o /tmp/star-rrf-pilot
python experiments/star-rust-20261101/check_rust_parity.py --exe /tmp/star-rrf-pilot
```

Use `.exe` paths in a temporary Windows directory. This validates the historical CLI experiment only. Production `native/litha_search` has its own existing build and test instructions; they are not silently replaced here.

## 7. Advisory comparison schema

Save one baseline JSON file and one candidate JSON file with identical workload, environment, checker and cold/warm identifiers. Include every paired `(case_id, trial)` observation. Example structure (illustrative, not a measurement):

```json
{
  "schema_version": 1,
  "workload_id": "held-out-taskset-and-corpus-revision",
  "environment_id": "host-runtime-model-config-fingerprint",
  "quality_gate_id": "independent-checker-revision",
  "mode": "warm",
  "variant": "baseline",
  "rows": [
    {"case_id": "case-001", "trial": 0, "elapsed_ms": 100.0,
     "verified": true, "authorization_violations": 0, "timed_out": false}
  ]
}
```

One row is intentionally insufficient for the default review floor. The candidate uses `"variant": "candidate"`. `verified` means the declared independent checker accepted the completed result; a timed-out or unauthorized row cannot be marked verified. Include terminal elapsed time for unsuccessful attempts.

```bash
python experiments/star-rust-20261101/advisory_compare.py baseline.json candidate.json
```

The tool rejects inconsistent schemas, nonfinite durations, duplicate JSON fields, unpaired observations and mismatched metadata. It reports `reject` for observed authorization issues, newly timed-out cases or a paired correctness loss; `inconclusive` for insufficient cases/no verified work/no descriptive target gain; and `review_candidate` only when descriptive thresholds are met. Exit zero means a report was generated, never that deployment is approved. The result always records `deployment_authorized: false` and `statistical_significance_established: false`.

The tool cannot verify the truth of metadata or flags, enforce workload representativeness, or detect all timing bias. Keep source logs, external checker evidence and manual review. Do not automate a deployment from its status.
