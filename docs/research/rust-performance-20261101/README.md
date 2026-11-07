# STAR Rust performance research and recovered experiments

**Prepared November 1, 2026. Research and isolated experiments only.**

This publication recovers the earlier unpublished Rust pilot and reviewed Lemonade/AnythingLLM bridge, preserves their evidence, and adds a source-backed mixed-language architecture plan. It does **not** rewrite STAR, activate a backend, merge a PR, restart services, change model weights, or publish an installer.

## Start here

- [Research report](RESEARCH.md): profiling, Rust/Python boundaries, memory, concurrency, inference, correctness, packaging, and an ordered plan.
- [36-source annotated register](SOURCES.md) and [machine-readable sources](sources.json): official documentation and primary repositories, with version caveats and concrete STAR decisions.
- [Benchmark protocol](BENCHMARK_PLAN.md) and [prioritized experiment backlog](EXPERIMENTS.json): comparable workloads, falsifiable hypotheses, stop conditions and rollback.
- [Recovered artifact index](../../../experiments/star-rust-20261101/historical/IMPORT_NOTES.md): reviewed adapter, Rust source, original benchmark harness, prior results and patch.
- [Experiment tools](../../../experiments/star-rust-20261101/README.md): advisory comparison utility, unit tests, and reproducible Rust parity checks.
- [Fresh validation](results/): this publication's reruns, kept separate from historical timing results.
- [Publication manifest](MANIFEST.sha256): hashes of the new publication files, excluding the manifest itself.

## Repository state, not historical assumptions

The old `oncoursemail/Star-AI-Private` name now resolves to **`oncoursemail/Star-AI-Project`**, whose inspected visibility is public. This package is based on development branch `star/next` at commit `e672fd7b76ad24dac8f5f7f1fd67cc167fa6c829`.

[PR #849](https://github.com/oncoursemail/Star-AI-Project/pull/849) is already merged. It added an optional resident Rust/PyO3 dense retriever under [`native/litha_search`](../../../native/litha_search/README.md). Its pinned PyO3 version is 0.27.2. Python remains the default in the inspected implementation. The recovered October 30 command-line rank-fusion pilot is a **different, older experiment**, not that backend and not a replacement for it.

The old audit's statements about missing Rust code, repository accessibility, separate project identity, or absent PRs are dated historical observations, not current repository facts. See the import notes before quoting them. Personal paths were redacted in three archival files; source and test bytes were preserved.

## Recommended decision

Keep Python orchestration and React/TypeScript UI. Retain the established native inference engine. Use resident, batched Rust extensions for demonstrated CPU bottlenecks, with visible Python fallback. First address redundant work, queue contention, resource budgets, cache validity and packaging. Replacing a language cannot by itself improve model knowledge, eliminate hallucinations or make an 8 GB GPU hold an unlimited model.

Do not launch a Rust process for every small rank-fusion call: the historical Windows pilot's process-boundary cost exceeded its kernel savings. Do not replace the existing native dense index with a second index merely to add Rust. Do not treat a microbenchmark ratio as a whole-agent speedup.

## Status and review boundary

Fresh Linux tests cover the recovered bridge and advisory comparator. Windows reruns and exact counts are recorded in the validation files. Historical measurements remain dated and have not been promoted into new claims. The existing production suite, live model latency, GPU behavior, the PyO3 Windows wheel and packaged STAR EXE are outside this isolated publication's validation.

The comparator is descriptive and can reject obvious regressions; it does not prove statistical significance, independently verify caller-provided flags, replace STAR's official evaluation gate, or authorize deployment. No new root GitHub Actions workflow is introduced. The archived nested workflow remains documentation within the experiment.
