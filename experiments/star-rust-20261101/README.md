# Isolated STAR Rust experiments

Nothing in this directory is imported by STAR's runtime or automatically activates a provider. The historical Rust CLI is not the merged PyO3 dense backend.

- `historical/`: recovered October 30 audit package, corrected bridge, patch, Rust source, benchmark harness and prior logs. Read `historical/IMPORT_NOTES.md` for three privacy redactions and dated claims.
- `advisory_compare.py`: standard-library, bounded-input descriptive comparison of paired runs. It flags observed quality/authorization/time-out regressions and never authorizes deployment.
- `tests/test_advisory_compare.py`: synthetic contract tests, not AI benchmarks.
- `check_rust_parity.py`: rerun the archived 40 comparison cases without rerunning or relabeling the historical timing experiment.

The official STAR evaluation gate remains independent and unchanged. This directory does not install third-party applications, download a model, execute model-generated code, or change user settings. Test bridge HTTP traffic is to loopback mocks.

See [the research index](../../docs/research/rust-performance-20261101/README.md) and [protocol](../../docs/research/rust-performance-20261101/BENCHMARK_PLAN.md) for commands, input schema, baseline and limitations.
