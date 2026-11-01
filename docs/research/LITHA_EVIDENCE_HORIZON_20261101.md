# Litha Evidence Horizon — source-verifiable context and complex-work roadmap

**Date:** 2026-11-01
**Scope:** opt-in prototype for Litha. Baseline STAR star/next at eccc30961fd43a2b4f5913dc4c1a5007f43d9d8c.
**Status:** new SQLite evidence/retrieval module and offline tests; not wired to live model inference or autonomy.

## Decision

Do not feed entire repositories, websites, past conversations, and every prior investigation into one prompt. Maintain a durable evidence corpus far larger than any single model context; select relevant **original, revision-pinned** excerpts, track omitted sources, and recover exact originals before editing code or verifying claims.

This **increases effective information available across successive turns**, not the native context window or model weights. Success is higher pass rate on sealed held-out tasks, correct attributions and verified artifacts at a comparable compute/time budget, not merely more files ingested.

## Existing foundations to reuse

The codebase already has context_layout.py for stable llama.cpp cache prefixes; conversation and document compaction in docs/LONG_INPUT.md; research_session.py for bounded source investigation; resource_atlas.py for public resource metadata; omega_hyperindex.py for scoped reviewed-note retrieval; code_search_batch.py and the merged Rust retrieval acceleration; and mission_checkpoint.py for durable read-only workflow checkpointing. Litha's PR fixer/bug hunter and protected tests already distinguish an actual reproduced failure from an unsupported diagnosis.

The Horizon proposal deliberately does **not** replace these systems. It is an exact source-revision repository and bounded retrieval interface intended to join them in a later integration.

## Implemented

The isolated file litha/evidence_horizon.py adds a standard-library SQLite HorizonStore that archives an exact source revision scoped to project, source ID, revision, locator, kind, license and explicit independently supplied reviewed state. Its original UTF-8 contents are checked with SHA-256 upon recovery. New versions become active in retrieval; old versions remain readable by exact identity and are never silently overwritten.

One to eight lexical queries are token-sanitized before FTS5 lookup and ranked deterministically. When FTS5 is unavailable, a bounded scan of at most 1,000 active sources reports its limitation; when FTS5 becomes available, previously archived unindexed sources are backfilled. Excerpts carry source digest, locator, revision, line start, character offset, clipped status and license metadata. This is **keyword retrieval**, not semantic recall.

The context packet is JSON explicitly labeled untrusted reference data. A trusted application callback counts real tokens from the selected model's tokenizer. Sources that do not fit the packet budget are omitted and counted. The host must also reserve tokens for system instructions, tools, generated responses and multimodal material.

Bounds: 100,000 Python characters per original; 5,000 revisions per project; maximum 8 query strings of 600 characters; 32 candidates per query and 32 returned sources; 1,400 characters per excerpt. These are experimental caps, not memory or runtime SLA claims. No network, LLM, GPU, crawling, execution, agent dispatch, permission grant or lesson promotion is activated by this patch.

The tests in tests/test_litha_evidence_horizon.py cover persistence after restart, scope isolation, SHA mismatch and tamper detection, historical retrieval, inactive revisions, deterministic ranking, FTS injection, exact excerpt offsets, strict input limits, fallback disclosure, prompt injection as inert JSON, token admission and FTS backfill.

Run locally:

~~~sh
python3 -m unittest tests.test_litha_evidence_horizon -v
python3 -m compileall -q litha/evidence_horizon.py tests/test_litha_evidence_horizon.py
python3 -m benchmarks.litha_evidence_horizon --sources 300 --repeats 15
~~~

The new benchmark generates purely synthetic source text, records raw timing samples and an exact output fingerprint. It excludes indexing overhead, live-source retrieval, model inference, GPU, semantic recall and task-solving accuracy.

## Research findings (primary and project sources)

### Native context is not usable memory

NoLiMa (ICML 2025) shows that long-context models struggle to connect questions with passages when literal words are different. LongBench v2 (ACL 2025) studies realistic deep reasoning across large documents, code, dialogue and structured data. Large advertised token windows are therefore insufficient evidence of understanding. Our FTS5 prototype has the same lexical weakness as other keyword search; semantic/hybrid augmentation is a **future experiment**, not a deployed feature.

- https://proceedings.mlr.press/v267/modarressi25a.html
- https://aclanthology.org/2025.acl-long.183/

### Multi-hop context requires relationships and negative evidence

HippoRAG 2 pursues associative and multi-hop retrieval through relationships between documents. Litha should later join source revision identities with independently checked relation edges and conflicting claims, not just dump all retrieved paragraphs in a prompt. Reuse OMEGA's reviewed-source boundary; do not treat model-derived associations as verified facts.

- https://github.com/OSU-NLP-Group/HippoRAG

### Teaching complex tool workflows requires correction trajectories

ToolForge (EMNLP 2026) examines multi-hop, multi-turn tool-use trajectories and correction. The Tool Illusion (COLM 2026) warns against assuming a higher tool count necessarily improves agents. Better Litha data would link **question -> source IDs -> proposed decision -> authorized tool outcome -> independent verification -> corrected hypothesis**, keeping unverified tool text separate from scored experience.

- https://aclanthology.org/2026.emnlp-main.1250/
- https://www.microsoft.com/en-us/research/publication/the-tool-illusion-rethinking-tool-use-in-web-agents/

### Long-horizon code generation needs pristine external evaluation

SWE-Bench Pro (ICML 2026) targets professional repository work; the September 22, 2026 V2 revision corrected task/evaluator mismatches and checks candidate patches on pristine environments. Litha should run candidates in isolated worktrees, preserve hidden graders, and never allow a generated patch to edit or mark evaluation fixtures.

- https://proceedings.mlr.press/v306/deng26f.html
- https://labs.scale.com/leaderboard/swe_bench_pro_public_v2?tab=full

### Prefill cache is not persistent knowledge

llama.cpp prompt cache reuse can make byte-stable prefixes cheaper in a reused server slot. It does not store exact source libraries across projects or make model attention unbounded. Put changing evidence late in prompts and independently benchmark model prefill and KV memory pressure.

- https://multigrid.ai/learn/llamacpp-prompt-caching

## Proposed integration pipeline — not yet wired

~~~
User goal / autonomous permitted objective
  -> independent requirement contract and dependency DAG
  -> task-specific search facets and known uncertainty
  -> existing research session / Resource Atlas / code or document retrieval
  -> host source and license/scope qualification
  -> HorizonStore immutable revision archiving
  -> ranked evidence candidates, plus future measured semantic adapter
  -> full exact original recovery and SHA check
  -> token-budgeted untrusted evidence injection
  -> fast model / separately authorized deep model
  -> isolated generation of code, UI, geometry, animation, assets
  -> independent compile, typecheck, scene, visual and runtime verification
  -> durable task checkpoint, source attribution and repair of specific failures
  -> hidden sealed A/B gate before default activation
~~~

Litha can tackle wider problems by decomposing work into independently verifiable units, selectively revisiting original evidence and resuming by checkpoints. Parallel agents may work only on independent non-overlapping tasks with memory/compute admission; more concurrent model instances on an 8GB GPU can make output slower. Use CPU/RAM/SQLite indexing and minimize resident GPU footprint. Benchmark on the actual RTX 4060 target before making performance claims.

## Next implementation sequence and acceptance criteria

| Phase | Engineering | Required independent evidence |
| --- | --- | --- |
| A. Collector adapter | Safe ingestion from approved code, research sessions and documents; host source IDs and scope | Source identity, privacy, licensing and disabled-mode tests |
| B. Search quality | Add optional existing dense+lexical fusion, conflict and missing-evidence detection | Held-out multi-hop/source recall versus FTS-only; query time, RAM |
| C. Mission continuity | Extend existing checkpoint and orchestration plans with source dependencies | Restart without source corruption, duplicated writes or authorization drift |
| D. Complex artifact generation | Typed acceptance contract across Roblox scene, VFX, animation, UI and code | Real engine outputs, geometry/layout checks, screenshots, exact tests |
| E. Learning and solver | Verified failure trajectories, bounded best-of-N candidates, counterexample discovery | Better sealed success rates with stable latency/cost/regression gates |
| F. GPU/CPU tuning | Measure actual prefill, KV cache, RAM and token rate under mixed loads | Interactive latency and VRAM/RAM on owner's Windows hardware |

The first integration should be **default OFF** with a reversible adapter. No background crawling, new dependencies or model upgrades are justified by the current prototype alone.

## Critical failure modes

**External text is always data**, not instructions; a retrieved webpage cannot turn on permissions, approve downloads, run remote code or choose privileged tool actions. Scope and user consent must be enforced by a trusted host, not a prompt.

**Source text is not enough to prove learning.** Only independent executed tests, live model A/B measurements and an immutable verifier receipt can show improvements. No self-generated test suite should grade its own untrusted changes.

**Loss and uncertainty must be visible.** Summaries lose details; keyword retrieval misses paraphrases; cap-limited search misses sources; original sources can change on the web. Recover the original pinned bytes or report unavailable evidence. Accurate source-attribution is a requirement, not a decorative citation.

**Do not publish private data.** The STAR repository is public; personal files, confidential chat history, secrets, third-party copyrighted source archives and model weights must remain outside tracked files.

**Current capability boundary:** this patch is a research-grade evidence archive and synthetic retrieval harness. It does not increase the neural context window, run a live model or research session, make Litha independently smarter, change deployment/permissions, or establish a production quality/speed gain. A later tightly scoped integration and real held-out measurements are necessary.
