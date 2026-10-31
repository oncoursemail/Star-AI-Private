# Star AI: grounded VTuber recollection, low-latency gameplay and verified intelligence

**Research and implementation snapshot:** October 30, 2026. This is an engineering plan, not a claim that a real game or broadcast was run. No model weights changed. Code is a draft-PR, OFF-by-default addition.

## 1. What this revision actually changes

The previous `StreamEpisodeJournal` could only return a tuple of host-attested facts. It was not connected to voice planning, so Star could not actually receive these facts while answering a question. Now `StarStage.prepare` can optionally accept a trusted `StreamEpisodeJournal`, a canonical game-scope ID, and a **separate explicit broadcast approval flag**. Only **viewer questions**, outside gameplay-critical/telemetry-overload conditions, receive up to two short, recent, game-scoped journal facts in a data-only user-level prompt. A journal alone does not trigger speaking, motion, OBS, or I/O. A disabled journal returns nothing. No viewer chat or personally identifying information is stored. A host's `host_observed=True` is still an assertion, not independent proof or an actual signature.

This bridges a concrete missing link between game-observation memory and natural VTuber responses without fabricating a biography. Examples of appropriate behavior: "Earlier I reached the bridge checkpoint"; when no reliable memory exists: "I can't confirm that." The text model must remain transparent that it is AI; humanlike timing and personality do **not** require deceiving viewers.

The new opt-in integration is distinct from `StreamEpisode` (signed practice aggregates) and `StreamContinuity` (sealed historical episodes). It does not authorize or supersede either; it does not confer permissions to train or promote models.

## 2. Benchmark Star as an entire real-time system

Run a reproducible host-controlled 20-minute OBS rehearsal, with the normal Windows desktop hardware and no public broadcast. At least three repeats per configuration, with paired game seeds and identical project versions. Capture *per-process* CPU, GPU, VRAM, frame time, host-attested audio start, TTS queue lengths, frame-to-decision and end-to-end action latency. Separately confirm audible audio exists in an OBS recording; a playback callback is not sufficient.

**Proposed gates, not measured results:**

| Scenario | Proposed threshold to inspect | Failure response |
| --- | --- | --- |
| Game rendering during gameplay + VTuber | sustained game FPS >= 50, monitor 1% lows | pause background Forge/research |
| Critical gameplay speech | no nonurgent speech when gameplay-critical; interrupt remains eligible | cancel new TTS/motion proposals |
| GPU headroom | preserve >= 1.5 GiB free when live; log load at p95 | reduce model offload and concurrency |
| Voice queue | backlog <= 250 ms target before commentary | withhold optional comments |
| Latency | compare matched p50/p95 host playback start; no >10% p95 regression | revert configuration |
| Game learning | >= 20 paired holdout cases across >= 2 scenarios, no previously successful case becoming a failure | reject advisory candidate |
| Memory | only host-observed, current-session facts with specific scope + public permission | omit all recollections |
| Persona | human listeners label responses relevant, non-repetitive and coherent without fabricated life claims | revise policy/pacing |

These numbers are *acceptance targets for experimental tuning*, not universal production limits. Existing stage pressure control already uses some of these signals; actual Windows/OBS evidence is the missing piece.

## 3. Fast and deliberate intelligence, not only token throughput

- **Game fast path:** deterministic control loop and lightweight perception operate without waiting for full LLM completion. Use the reasoning model for *tactics and explanations*, not for every frame. A strategic plan can be invalidated when new ground-truth state arrives.
- **Workload admission:** reserve OS, game rendering, audio playback, avatar rig and input loop first. Background Star Core Forge experiments are preemptible, bounded and default OFF while live. On an 8 GB card, a second loaded model may cost more responsiveness than it adds intelligence.
- **Prompt caching:** hold stable prefix text for Star's role, rules, and tool contracts; append short variable session facts at the end. In llama.cpp, `cache_prompt` reuses unchanged KV prefixes when possible but can be nondeterministic across prompt batching; verify accuracy, not merely cache hit rate.
- **Speculative decoding:** test draft-model/ngram proposals using llama.cpp SPEED-Bench and a matching quality suite; compare first-audio latency, p95 generation, accepted draft rate, RAM and 1% game FPS. Decline any optimization with measurable quality or responsiveness regressions.
- **General knowledge:** ingest licensed/public documents into a versioned retrieval index with URL, date, author, topic, content hash and freshness policy. Use source ranking + contradiction checks, cite provenance, and say when evidence is missing. Avoid training directly on fabricated anecdotes or treating more stored text as intelligence.
- **Forge self-improvement:** generate difficult tasks; preregister tests; use independent holdouts; run baseline/candidate in isolated sandboxes; promote only after executable quality gates, security and latency gates; keep immutable local snapshots, differential reasoning, rollback and audit.

## 4. Gameplay skill and creator quality

Use GameWorld's state-verifiable success/progress and its **GameWorld-RT** continuously running track as separate metrics. An agent that solves a paused puzzle cannot claim real-time fighting or platforming skill. Avoid unapproved automation in protected multiplayer games.

For Roblox:
1. Inspect relevant instances and hierarchy before editing; log which objects were viewed, changed and verified.
2. Generate multiple constrained candidates with Luau API checks, type/lint, a deterministic repair budget, and short Studio playtests. Prefer passing examples over unchecked output.
3. Check the entire scene in edit mode: collisions, intersections, material consistency, anchoring, rig/hand grips, lighting, camera clipping, character scaling and expected object positions.
4. Verify **server and client** play behavior with StudioTestService; it supports up to **8 simulated clients**. Include late joining, disconnects, latency, and UI state synchronization. A polished screenshot does not prove game functionality.
5. Validate visual/UI fidelity via image comparisons and human review using fixed camera shots, not the LLM's assertion that the scene looks finished.

Roblox OpenGameEval (October 1, 2026) assesses 84 curated Studio tasks and shows a positive association between pre-edit inspection and task success; use it as an external repeatable benchmark, not as a guarantee that Star has mastered Roblox.

## 5. Conversation and character authenticity

A more believable Star should have consistent viewpoints, callbacks to *real* episodes, correct conversational pauses, expressive listening, nonverbal gaze to the game, a realistic ratio of silence to chatter, interruptible speech, head/hair physics and calibrated excitement. Avoid random canned squeals or imaginary personal history. Cat and puppy modes should subtly alter performance without changing factual grounding.

Investigate Kyutai Pocket TTS **v4.0.1 (October 21, 2026)** on a CPU sidecar alongside the current voice. Small October English variants can reduce compute needs, but they are not guaranteed to be expressive enough. Blind A/B testing should rate intonation, natural laughter, pronunciation, and perceived repetition while also recording CPU core occupancy, audio chunk latency and stream desynchronization. Only switch voices after evidence.

Do not train on a real performer's voice or clone an identifiable person without rights and explicit consent. Preserve the Star design identity rather than an imitation of a particular real streamer.

## 6. Reproducible release discipline

Before declaring a measurable intelligence/streaming improvement:
- GitHub Python, React and Pyright checks must succeed at the **same exact head SHA**; do not trust earlier runs on a parent commit.
- New behavior must have negative tests for forged/unverified memory, public approval OFF, cross-game scopes, chat injection and game-critical silence.
- Run Python isolated tests in an offline CI environment; log test counts and failures with workflow links.
- Perform at least three real Windows/OBS rehearsals and publish anonymized counters; no private recordings, chats or API keys in this **currently public** repository.
- Keep pull requests draft and unmerged until verified, with no direct production changes. GitHub is optional release/export infrastructure; Star Core Forge remains the intended local-first system.

## Primary evidence

- Roblox OpenGameEval (October 1, 2026): https://github.com/Roblox/open-game-eval and https://arxiv.org/abs/2610.02563
- Roblox StudioTestService API (up to 8 test clients): https://create.roblox.com/docs/reference/engine/classes/StudioTestService
- GameWorld and GameWorld-RT ground-truth evaluation: https://gameworld-project.github.io/
- llama.cpp SPEED-Bench benchmark: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md
- llama.cpp server API and prompt cache behavior: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md
- Kyutai Pocket TTS v4.0.1, October 21, 2026: https://github.com/kyutai-labs/pocket-tts/releases/tag/v4.0.1
