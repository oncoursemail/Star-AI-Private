# STAR research: embedding-space cache identity and capability routing

**Date:** 2026-11-09
**Scope:** STAR's opt-in embedding-based skill-pack router, retrieval correctness, and the next steps for general knowledge, game skills, and live VTuber operation.

## Executive finding

STAR's star/skill_routing.py caches document vectors on disk. Before this change, its cache key included only the configured model alias and the pack text. If the server replaced the weights behind the same alias (for example, a new star-embed-ft1 checkpoint), old document vectors could be compared with a query vector from a different embedding space. The code would still return a plausible cosine score, but the ranking would no longer be trustworthy.

A model name is a routing label, not an immutable model identity. The safest long-term identity is a host-published immutable model/checkpoint digest. Until STAR Server exposes that reliably to the desktop, this patch adds a **runtime canary fingerprint**: two fixed query-side probe texts are embedded in the same request as the user's query, and their rounded vectors namespace the persistent document-vector cache. On a cache miss, the probes are embedded again after the document batch; a changed fingerprint aborts the refresh rather than storing mixed-space vectors.

This is a correctness guard, not cryptographic attestation. A canary set can theoretically collide or miss a subtle model change. An immutable model SHA-256 from the trusted server manifest remains the preferred identity.

## What changed in code

- Add a versioned cache namespace containing the model alias, pack-document text, and live canary fingerprint.
- Batch the user's query and two small canaries in one embeddings request. A cache hit still needs only this one request.
- Recheck the canaries after a document-cache miss; if the embedding space changed during the refresh, discard the new vectors and fall back to the keyword path.
- Reject booleans, NaN, infinity, inconsistent vector dimensions, oversized vectors, malformed cached values, and oversized cache files.
- Bound the on-disk cache to 256 entries and 2 MB. A corrupt or unwritable cache only costs re-embedding; it never blocks normal chat.
- Keep keyword routing first. The embedding router remains opt-in, context-gated to Roblox/Godot/named engines, and does not run in Quick mode.

The extra work on a cache hit is two small canary vectors in the same query request. On a cache miss, one document batch and one canary confirmation are also required. No model weights are trained, no route is changed automatically, and no prompt or generated answer is written to the cache.

## Research findings and design implications

### 1. Query and document prompts are part of model identity

Google's EmbeddingGemma model card describes asymmetric retrieval prompts: queries use the prefix "task: search result | query: ...", while documents use "title: ... | text: ...". It also recommends including a real title when available. STAR already follows this convention in QUERY_PREFIX and pack_document(). Those prefixes must be included in the cache namespace/schema version: changing either changes the embedding space even when the checkpoint stays the same.

Sentence Transformers documents the same principle through separate encode_query() and encode_document() paths. Retrieval embeddings are not always interchangeable with symmetric similarity embeddings. A future STAR embedding adapter should make query/document roles explicit rather than accepting arbitrary strings with implicit prefixes.

### 2. Cache identity must include every transformation that changes vectors

A robust persistent key should ultimately include:
- immutable model/checkpoint digest (preferred);
- tokenizer and pooling revision, if they can change independently;
- query/document prompt-template version;
- requested output dimension and normalization policy;
- exact normalized document text;
- cache schema version.

The canary fingerprint is a compatibility layer until the server can provide the first item. It detects many same-alias weight swaps without adding a second request on ordinary cache hits. It does not prove which file ran.

### 3. Validate the vector contract before ranking

A vector cache is derived data, not trusted memory. Every live and cached vector should have finite numeric values, one consistent dimension, and a bounded size. Dimension mismatch must never be silently handled by zip() truncation. Invalid entries should be treated as cache misses and rebuilt; invalid live replies should trigger the existing safe fallback.

OpenAI's embeddings API reference documents that the response includes a model identifier and indexed vectors. STAR's OpenAI-compatible local server may expose less metadata, so the desktop should not assume an alias alone identifies immutable weights.

## How this connects to STAR's larger intelligence

### General knowledge and long-term memory

The embedding cache is not a knowledge base and does not make STAR smarter by itself. It only helps select a relevant skill pack. General knowledge still needs source attribution, timestamps, project scope, and a clear distinction between verified facts, user-provided information, experiences, and hypotheses.

MemTrace's October 4, 2026 paper is relevant to long-running development work: it anchors memories to repository files, symbols, tests, and evolving repository state, then checks whether recalled evidence is still valid before reuse. STAR should apply that principle to project lessons and generated skills: a remembered fix should be rechecked when the referenced API, file, test suite, or model revision changes.

### Gaming and game creation

Skill retrieval should eventually be environment-aware. A Roblox DataStore skill, a movement skill for a racing game, and a turn-taking skill for a livestream are different procedures with different preconditions and action spaces. A future skill record should identify its environment/game version, observation source, allowed actions, prerequisites, evidence suite, and last verified revision.

Gym-Anything-RT (October 27, 2026) shows why reasoning quality and real-time gameplay competence must be measured separately: the same minigames can be tested in live time and in paused/slowed conditions. OpenGameEval provides a complementary Roblox Studio workflow with executable scene and play-session checks. STAR should use these as separate evaluation tracks:
- game-playing: capture-to-action latency, deadline misses, objective progress, and held-out scenario success;
- game-building: project inspection, code correctness, scene structure, visual review, and simulated playtest outcomes.

### Natural VTuber streaming

The embedding router must not become a blocking dependency in the live speech path. Keep the keyword fast path, keep embedding retrieval opt-in, and prewarm stable skill documents during idle time where practical. The live loop should prioritize current game state, turn-taking, interruptions, and audio/OBS health; deeper research and skill retrieval belong in cancellable background work.

TurnBench (August 25, 2026) evaluates end-of-turn and interruption detection across different conversational styles and reports that interruption false positives vary substantially with backchannel density. STAR should therefore measure end-of-turn recall, false interruptions, barge-in stop latency, correct yielding, and appropriate silence separately. A single "conversation naturalness" score would hide important failure modes.

## Prioritized next steps

1. **Expose immutable embedding identity from STAR Server.** Add a read-only model manifest field containing a SHA-256 of the actual embedding weights and the embedding adapter/prompt revision. The desktop should prefer that digest; retain canaries as a fallback and drift check.
2. **Build a held-out retrieval evaluation.** Measure top-1 accuracy, recall@k, MRR, wrong-scope rate, fallback rate, latency, and downstream task success. Keep development and holdout queries separate; do not tune MIN_SIMILARITY on the holdout.
3. **Add a cross-game skill registry.** Store skill preconditions, game/environment version, observation modality, action schema, cooldown/deadline assumptions, and independent outcome evidence. Keep game-playing skills separate from Roblox Studio creation skills.
4. **Connect skill evidence to versioned memory.** When a skill depends on a changed API, file, model, game build, or test suite, mark the old evidence as needing revalidation instead of silently reusing it.
5. **Keep the streaming path deadline-aware.** The reflex loop handles immediate gameplay and interruption; a tactical loop selects strategies; a background learner researches and updates candidate skills. Optional retrieval must be cancellable and must not delay owner speech, danger reactions, or audio stop.
6. **Benchmark the complete workload on the actual Windows host.** Compare the same model, embedding revision, and held-out tasks while idle, gaming, gaming+OBS, and gaming+OBS+TTS/avatar. Record TTFT/first-content, inter-token latency, first-audible latency, FPS/frame-time, VRAM, OBS drops, and task quality. Do not infer a speedup from a CPU-only development host or an isolated token-rate number.

## Rollout boundaries

- skill_pack_embeddings remains off by default.
- Keyword routing remains first and unchanged.
- A canary match is not proof of model provenance; prefer an immutable model digest from the trusted host.
- No model switching, training, game input, OBS control, avatar output, or broadcasting is authorized by this change.
- A cache miss or invalid embedding response falls back safely; it does not fail ordinary chat.
- Retrieval correctness must be shown on held-out queries and downstream tasks before changing the similarity threshold or enabling the feature by default.

## Sources

- Google Gemma, [EmbeddingGemma model card v2](https://github.com/google-gemma/docs/blob/main/docs/models/embeddinggemma/model-card-v2.md) — query/document task prefixes and title-aware document formatting.
- Sentence Transformers, [Retrieval usage](https://www.sbert.net/docs/sentence_transformer/usage/usage.html) — separate query/document encoding paths.
- OpenAI, [Vector embeddings guide](https://developers.openai.com/api/docs/guides/embeddings) and [Create embeddings API](https://developers.openai.com/api/reference/resources/embeddings/methods/create) — embedding vectors, model identifiers, dimensions, and similarity.
- Xu et al., [MemTrace: State-Consistent Memory for Long-Horizon Coding Agents](https://arxiv.org/abs/2610.04838), October 4, 2026.
- Aggarwal & Welleck, [Gym-Anything-RT](https://arxiv.org/abs/2610.37567), October 27, 2026.
- Roblox, [OpenGameEval](https://github.com/Roblox/open-game-eval) — executable Roblox Studio and simulated-play evaluation.
- Jiang et al., [TurnBench](https://arxiv.org/abs/2608.25218), August 25, 2026.
- NVIDIA, [AIPerf streaming metrics](https://docs.nvidia.com/aiperf/reference/ai-perf-metrics-reference) — first-token, inter-token, and end-to-end measurement definitions.