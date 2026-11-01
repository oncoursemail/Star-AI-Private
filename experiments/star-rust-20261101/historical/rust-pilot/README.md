# Rank-fusion Rust pilot — not production integration

This is a bounded, standard-library-only experiment, not a new STAR backend. It uses no downloaded crates, models, network requests or tool execution. The CLI accepts newline-separated rankings of comma-separated signed 64-bit IDs. The first ranking receives weight 2; later rankings receive weight 1. Exact score ties preserve first occurrence order.

The tested source and benchmark SHA-256 values are recorded in `../results/provenance.json`. Windows results are in `../results/windows-rust-benchmark.json`. Nine Rust tests and forty cross-language cases passed. No Linux Rust build or Python extension build was performed.

## Reproduce on Windows PowerShell

```powershell
rustc --edition=2021 -O --test rrf_pilot.rs -o rrf_tests.exe
.\rrf_tests.exe
rustc --edition=2021 -O rrf_pilot.rs -o rrf_pilot.exe
python benchmark.py --exe .\rrf_pilot.exe --output windows-benchmark.json
```

Equivalent Linux commands (provided, not tested here):

```sh
rustc --edition=2021 -O --test rrf_pilot.rs -o rrf_tests
./rrf_tests
rustc --edition=2021 -O rrf_pilot.rs -o rrf_pilot
python benchmark.py --exe ./rrf_pilot --output linux-benchmark.json
```

Use release optimization as shown. The benchmark deliberately measures both kernel time and subprocess wall time. It does not include Python payload construction or result parsing in the subprocess-wall timer, so a fully integrated subprocess call would cost more, not less.

**Do not invoke this executable separately for every STAR request in production.** That route was slower in the measured environment. A potential future PyO3 batched interface must be benchmarked with conversion costs and tested against a Python fallback. Small real workloads may not justify a Rust dependency at all.
