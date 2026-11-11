# STAR research: retrieval caching and measured capability growth

**Research date:** 2026-11-10  
**Implementation branch:** `feat/general-skill-bm25-retrieval-20261110-auto11`  
**Scope:** bounded installed-skill discovery, retrieval quality measurement, local inference, natural streaming, Roblox/game creation, and state-consistent learning.

## Executive finding

The previous BM25 change made installed Agent Skill retrieval relevant rather than catalog-order/substring based. Inspection of the new path exposed a second avoidable cost: every query reparsed each skill's frontmatter and rebuilt all document token counts and inverse-document-frequency statistics.

This follow-up caches only validated metadata and the derived BM25 index. It invalidates metadata from file stat signatures and invalidates the lexical index from the exact catalog identity. It does not cache or expose instruction bodies, does not bypass symlink/path checks, and does not auto-load a skill.

A local JSONL evaluator now measures retrieval quality and first/warm latency. This makes the next optimization evidence-driven instead of claiming that caching or a larger model is automatically faster or smarter.

## 1. Implementation: bounded, invalidatable retrieval caches

### Metadata cache

For each discovered `SKILL.md`, STAR still performs the existing directory, symlink, root-containment and regular-file checks. It then compares a compact signature:

- `st_mtime_ns`
- `st_ctime_ns`
- file size
- inode where supported

Unchanged files reuse the already parsed `name` and `description`. Changed files are re-read through the existing 8,007-character frontmatter bound. Invalid frontmatter can be cached as an invalid result for the same file signature; an I/O error is not cached as a permanent invalid result. Removed or undiscoverable paths are pruned from the metadata cache.

The cache is bounded by the existing 200-skill catalog limit. The `RLock` protects concurrent catalog/search calls.

### BM25 index cache

The lexical index is keyed by the ordered tuple of skill name, description, source and path. It stores title/description tokens, term-frequency counters, document frequency and average field lengths. A metadata edit, source-precedence change, path change, added skill or removed skill causes a rebuild.

This removes repeated tokenization and corpus-statistic construction while preserving deterministic ranking and the existing project/workspace/personal/bundled precedence.

### Trust boundary preserved

- Search returns only name, description, source, score and matched terms.
- Skill instructions are still loaded only through explicit `load(name)`.
- Reference files are still read only through explicit `read_reference(name, path)`.
- A skill is untrusted reference material, not executable code or a permission grant.
- A search score is not a confidence probability, quality judgment or authorization signal.
- No model, embedding server, network request, MCP connection, workspace permission or game-control permission is added.

## 2. Retrieval evaluation: separate ranking from downstream usefulness

New runner: `benchmarks/agent_skill_retrieval.py`

New tests: `tests/test_agent_skill_retrieval_benchmark.py`

The runner accepts a local JSONL file with exactly:

```json
{"query":"Roblox server-side RemoteEvent validation","relevant_skills":["roblox-secure-remotes","roblox-luau-review"]}
```

It reports aggregate-only metrics:

- Recall@K: fraction of gold skills retrieved.
- MRR@K: reciprocal rank of the first relevant skill.
- nDCG@K: ranking quality when multiple skills are relevant.
- First-query latency: includes initial metadata/index construction.
- First-pass p50/p95 latency.
- Warm-pass p50/p95 latency after the metadata and BM25 caches have been populated.
- Catalog size and query count.

Raw query text is not copied into the report. The input parser rejects duplicate JSON keys, unknown fields, invalid skill names, overlong lines and oversized datasets. The tool is offline, uses no model, does not download datasets and never opens skill bodies itself.

### What this evaluator does not prove

Retrieval quality is not the same as skill utility. It does not establish whether a skill was necessary, loaded, followed, or responsible for task success. The next SRA evaluation should compare skill-free, metadata-only, selected-skill, gold-skill diagnostic, and distractor arms with the same model, prompt, tool policy, grader and token budget. Host-observed load/use events and objective task graders are required; model self-report is not evidence.

## 3. Local inference: benchmark the serving system, not just token generation

Primary reference: [llama.cpp SPEED-Bench server benchmark](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md).

The upstream runner measures category throughput, latency and speculative draft acceptance against an already running `llama-server`. Its documentation recommends setting client concurrency to the server slot count (`--np`) when measuring throughput. STAR should keep separate measurements for:

- prompt processing / time to first token;
- time to first useful content;
- inter-token latency;
- end-to-end completion latency;
- tokens per second;
- output quality and task pass rate;
- queueing delay and cancellations;
- peak and sustained RAM/VRAM;
- GPU utilization and CPU contention.

Reference: [llama.cpp MoE cache documentation](https://github.com/ggml-org/llama.cpp/blob/master/docs/moe-cache.md).

The upstream MoE tuner performs real runs at multiple cache sizes and CPU shares, then fits measured upload and CPU speeds. It recommends a setting within 5% of the measured fastest option. This is a better pattern than copying a configuration from another GPU: cache behavior depends on model routing, host memory speed, PCIe, pinning, batch size and available VRAM.

### STAR experiment plan for the RTX 4060 8 GB system

Use a fixed prompt/request corpus and compare one variable at a time:

1. Baseline current model/backend.
2. Prefix/prompt caching on and off.
3. KV-cache type and context size.
4. Speculation disabled vs each viable draft/MTP mode.
5. CPU/GPU layer split and thread count.
6. MoE cache size/share where the selected model is MoE.
7. Single interactive slot vs controlled background concurrency.

Run each arm in two conditions: inference-only and mixed live workload (game + OBS + avatar + ASR/TTS + background agents). Reject a configuration that improves isolated tokens/s but worsens first-audio latency, p95 voice delay, game frame time, OBS drops, audio underruns or quality.

No tokens/s improvement is claimed by this PR.

## 4. VTuber: natural conversation is a timing and social-understanding problem

Primary references:

- [LiveKit end-of-turn benchmark](https://github.com/dlange-aai/livekit-eot-bench)
- [LiveKit audio turn detector documentation](https://docs.livekit.io/agents/logic/turns/turn-detector/)
- [Full-Duplex-Bench v3](https://www.full-duplex.ai/benchmarks/fdb-v3)

The open EoT benchmark uses real human-to-agent conversations with annotated mid-turn pauses across 14 languages. The current LiveKit documentation describes audio-detector endpointing defaults of 300 ms minimum and 2.5 s maximum, requires VAD silence of at least 250 ms, and notes that without STT language metadata the detector defaults to English thresholds. These are reference defaults, not thresholds to copy blindly into STAR.

STAR should optimize the false-cutoff/response-delay Pareto frontier per language and microphone/noise cohort. Measure:

- false interruption / false cutoff rate;
- missed turn rate;
- p50/p95 time to first audible PCM;
- time from true turn end to first audio;
- interruption stop latency;
- audio underruns;
- response accuracy;
- silence preservation;
- multi-party addressee accuracy;
- stop-after-human-resolution rate.

The social director should distinguish direct address, group address, side conversation, quoted speech, uncertain speaker, already-answered request and silence. Do not infer a viewer's real-world identity from a temporary speaker slot. Keep viewer content untrusted and separate it from tool/permission control.

For a live VTuber, prioritize the critical path:

`capture -> VAD/EoT -> addressee/floor -> short response plan -> first audio -> cancellable playback`

Long research, coding and asset generation belong in a separately budgeted background lane.

## 5. Gaming and creation: observe before mutating; evaluate on a live clock

Primary reference: [Roblox OpenGameEval](https://github.com/Roblox/open-game-eval).

OpenGameEval evaluates agents in reproducible stateful Studio sessions, with observation tools separated from editing tools. Its published README describes 84 human-curated core tasks, 13 frontier models and 16 attempts per task. It scores executable checks on edited scenes and simulated play sessions. Its exploration analysis supports a concrete STAR policy: inspect the objects and scripts relevant to a task before the first mutation.

Required STAR creator loop:

1. Inspect the current hierarchy, scripts, properties, constraints and selection.
2. Capture visual state, output and relevant runtime evidence.
3. Build a minimal plan tied to observed objects/symbols.
4. Request only the required edit capability.
5. Apply the smallest reversible change.
6. Launch a private/disposable test place.
7. Run deterministic checks and a simulated playtest.
8. Inspect screenshots, runtime state and logs.
9. Repair and independently retest.
10. Preserve evidence with the exact project/build identity.

Star Gamer should use the same separation between perception, state estimation, planning, authorized action and independent outcome scoring. Train on movement, camera control, timing, physics, aiming, navigation, objectives, resource decisions and team play. Promote skills only on held-out maps/seeds/game versions; a memorized route is not transferable mastery.

### Roblox Studio permissions

Current first-party reference: [Roblox Studio MCP/Open Cloud permissions](https://create.roblox.com/docs/studio/mcp-open-cloud).

Permissions are per game and per person. The user controls scopes, approved upload folders and network domains; Studio enforces them on every request. Full access includes high-risk capabilities such as monetization, player restrictions, secrets/Luau execution and publishing. DataStore/MemoryStore writes can affect live player data. STAR must not request broader access as a fallback: keep Safe/Custom least privilege, use a separate private test experience for data-store work, and require explicit review for publication, monetization, player consequences or live data mutation.

## 6. Memory and general knowledge: retain evidence, invalidate stale conclusions

Primary references:

- [Microsoft Research: MemGym](https://www.microsoft.com/en-us/research/publication/memgym-a-long-horizon-memory-environment-for-llm-agents/)
- [MemTrace](https://arxiv.org/abs/2610.04838)

MemGym evaluates memory across tool-use dialogue, deep research, coding and computer-use regimes, and explicitly isolates memory contribution from the backbone's reasoning/tool-use ability. MemTrace motivates immutable execution traces anchored to files, symbols and tests, with state checks before historical evidence is reused.

STAR should preserve knowledge with provenance:

- project/repository/build identity;
- source and revision/content digest;
- observed time and session epoch;
- tool/model version;
- task, action and test result;
- dependency links;
- validity predicate;
- invalidation reason.

A remembered test pass becomes stale when the relevant code, dependency, model, fixture or test changes. Revalidate before relying on it. General knowledge should be assessed through explanation, application, transfer and calibrated abstention—not only recall.

## 7. Unified Star runtime priorities

| Priority | System | Live/background policy | Acceptance evidence |
|---|---|---|---|
| P0 | Voice capture, EoT, playback and owner interruption | Live, reserved | first-audio p95, false cutoff, interruption stop |
| P0 | Game input and state perception | Live, reserved | action latency, objective success, held-out transfer |
| P0 | OBS/avatar render path | Live, protected | dropped frames, render latency, audio sync |
| P1 | Social director and viewer-comment selection | Live, bounded | addressee accuracy, silence preservation, response quality |
| P1 | Model routing and KV/prompt cache | Shared, admission-controlled | quality/latency Pareto under mixed load |
| P2 | Skill retrieval and memory recall | Fast indexed read | Recall@K, MRR, nDCG, warm p95 |
| P2 | Studio/game creation and playtesting | Background or scheduled | OpenGameEval-style pass rate and visual inspection |
| P3 | Deep research, indexing, Blender/video renders | Preemptible background | completed verified artifacts without P0 regression |

Do not run every specialist model concurrently by default. Admit work based on measured CPU, RAM, VRAM, queue age, deadlines and expected preemption cost. When resources become constrained, pause research/rendering first, not the live voice/game loop.

## 8. Acceptance gate before changing defaults

1. Retrieval benchmark has a versioned, held-out gold-label file and reports Recall@K/MRR/nDCG plus first/warm latency.
2. Cache tests prove reuse, metadata invalidation, removal invalidation and bounded reads.
3. Pyright, Ruff and all offline regression tests pass.
4. Windows target tests verify file invalidation behavior and concurrent calls.
5. Inference arms are paired and preserve exact model/config/prompt digests.
6. Streaming tests use human-annotated conversations and per-language holdouts.
7. Game tasks run in disposable environments with observation/action traces and independent graders.
8. A 60-minute private mixed-load rehearsal reports FPS p10, voice p95, first-audio latency, OBS dropped frames, audio underruns, CPU/RAM/VRAM, game objective success and background-job preemption.
9. Any improvement must be compared against a fixed baseline; no automatic model, memory, permission or production-setting promotion follows from a development score.

## References

- llama.cpp SPEED-Bench: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md
- llama.cpp MoE cache: https://github.com/ggml-org/llama.cpp/blob/master/docs/moe-cache.md
- LiveKit EoT benchmark: https://github.com/dlange-aai/livekit-eot-bench
- LiveKit turn detector: https://docs.livekit.io/agents/logic/turns/turn-detector/
- Full-Duplex-Bench v3: https://www.full-duplex.ai/benchmarks/fdb-v3
- Roblox OpenGameEval: https://github.com/Roblox/open-game-eval
- Roblox Studio MCP/Open Cloud: https://create.roblox.com/docs/studio/mcp-open-cloud
- MemGym: https://www.microsoft.com/en-us/research/publication/memgym-a-long-horizon-memory-environment-for-llm-agents/
- MemTrace: https://arxiv.org/abs/2610.04838
