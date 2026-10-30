# STAR: faster CPU VTuber lip envelopes and verified learning architecture
**Research and implementation:** 2026-10-29 (America/Chicago; UTC publication may be 2026-10-30)  
**Status:** PCM acceleration implemented and measured. The rest of this document distinguishes research priorities from deployed features.

## Executive decision
STAR already contains independent parts for Studio playtests, witnessed game outcomes, stream stage/interruptions, audio-to-rig envelopes, learning records, and resource admission. The highest-value improvements now come from *closing measured loops* instead of adding unrelated agents and models.

This change makes one real hot path cheaper: PCM16LE TTS audio -> RMS windows -> avatar lip-motion input. Use the saved CPU time for audio deadlines, game control, and low-latency responses. Do **not** interpret this as increased neural-model intelligence, better speech expressivity or verified gaming skill.

## Implemented CPU optimization
- Previous converter updated Python attributes and checked a window boundary for *each audio sample/frame*.
- New converter consumes a **bounded view of each frame-aligned 10/20/40ms window**, sums squared samples with exact integer arithmetic and emits the same frame-end timestamp. Python 3.12+ uses `math.sumprod` in C, with a scalar-compatible built-in fallback for older interpreters.
- Preserves both stereo channels' independent energy, including phase-inverted stereo; never sums the channels into a false silent waveform.
- Preserves across-chunk partial audio frames, sub-window carry-over, 15-second cap, maximum 1500 audio points, at-end timestamps, existing gains/noise gate, explicit empty/truncated rejection, and a one-way `finish()` boundary.
- No new packages, network calls, OBS connections, source audio retention, inference worker, streaming permission, or automatic configuration change.

**Measured on authorized STAR Linux development computer (Python 3.12.3):**
```
python3 -m scripts.benchmark_pcm_envelope --seconds 5 --repeats 9
5 seconds, 48,000 Hz, two PCM16 channels, 251 output RMS points
legacy scalar median: 103.878 ms
window fast-path median: 26.552 ms
ratio: 3.91x
```
Each arm is warmed up; median of nine runs; identical deterministic synthetic audio. Reproduction can vary with CPU contention, Python build, and background jobs. This measures **only PCM conversion CPU wall-time**; it does not measure end-to-end TTS, frame rate, audio-device latency, voice quality, memory bandwidth, gaming, OBS, or language-model speed. No production service was switched to this branch.

**Correctness evidence:** The new test suite compares samples to the old independent scalar algorithm across 6 sample rates (8k to 192k), both channel counts, all three window sizes, exact ±32768 samples, odd byte-split fragmentation, partial final windows, non-divisible frame boundaries, and forced older-Python fallback. Existing playout/device-cursor tests protect the rule that mouth motion cannot start before audible playback.

## Cross-cutting architecture: integrate, benchmark, graduate
### 1. Live-time priority lanes
- Hard-real-time-ish / highest-priority: device audio callback, consumed sample clock, avatar parameters, game controls, OBS capture. Never put LLM generation or disk research on their callback thread.
- Interactive: turn detection, speech and gameplay context selection, tiny bounded commentary. Restrict queue depths and cancel stale work.
- Reasoning: larger model for puzzles, scene/design planning, troubleshooting. Preserve context locality and route *tasks*, not individual tokens, to the right model.
- Background: Studio experiments, verified memory maintenance, skill curriculum, Blender rendering, benchmarks; suspend admission under measured hardware contention, rather than allocated swap alone.

Measure **P50/P95 latency per complete user request**, P95 audible first chunk, mouth/audio alignment, missed game input deadlines, OBS dropped frames, gameplay FPS and task correctness *together* before accepting a route as better. Check local llama.cpp's documented `--metrics` Prometheus endpoint for request deferrals, prompt throughput, generation throughput and KV usage (never expose metrics publicly without authorization).

### 2. Learning to play games, not memorizing game descriptions
Use an explicit, supervised research sequence on authorized private games:
1. Observe the actual game state and identify uncertainty (screen, HUD, legal action space, pause/loading state).
2. Hypothesize mechanics (jump timing, hitbox, cooldown, objective path) and predict success.
3. Act through a narrow, rate-limited Studio playtest-control interface; no global game exploits or live competitive automation.
4. Independently verify game outcome (checkpoint, health, score, objective) and connect it to exact build/run IDs.
5. Update a versioned gameplay skill **only after independent evaluation**, logging mistakes/strategies and uncertainty.
6. Retry unfamiliar held-out games/levels; compare success percentage, attempts, interventions, performance and statistical uncertainty.

Roblox **Studio's built-in MCP server** (announced March 5, 2026) supports AI-assisted playtest and input automation. `StudioTestService` (announced December 4, 2025) supports test-run control and multiple clients. These are a safer, reproducible starting point than unbounded desktop input. See sources.

### 3. Real general knowledge and episodic memory
Memory should contain provenance, time, confidence, privacy classification and the difference between model assertions and **independently observed facts**. For public facts, retrieve/source-verify at query time, cache with dates, and mark stale knowledge as unknown instead of inventing. For gameplay experiences, store compact objective trajectories (what STAR observed, attempted and verified) with expiration and provenance. Do not automatically train on viewer identities or private chats.

**EMemBench (EMNLP Findings 2026)** creates answerable questions with ground truth from interactive game trajectories; it exposes spatial and inductive memory as continuing weaknesses. STAR should adopt the *method*: held-out memory questions spanning temporal order, spatial layout, cause/effect and uncertainty. Check for regressions before graduate-to-production. Retrieval wins are not evidence of upgraded base-model intelligence.

### 4. Game development that can actually ship
Tie visual inspection, geometry/collision audits, scene script tests and whole-player journey tests to the **same immutable build ID**. Sequence: understand user brief -> inspect current scene -> generate 4-8 diverse candidate solutions under resource budget -> run Luau lint/tests -> run private Studio playtest -> view screenshots and engine errors -> verify completion/save/reopen -> promote only passing candidate for human review. Keep failures as diagnostic practice, not leaked training holdouts. Test native UI readability and animation independently of script correctness.

OpenGameEval's October 2026 study includes 84 developer tasks in Studio and distinguishes code edits, scene exploration and executable outcomes. Its evaluation *design*, not a published score as a promise for STAR, is the useful takeaway.

### 5. Humanlike VTuber presence without pretending to be human
Target a coherent original character, grounded in real experiences, not forced random emotes:
- **Attention model:** During difficult gameplay, allow silence and focused gaze. Outside critical sequences, answer selectively instead of reading every message.
- **Conversation:** separate speech activity, actual end-of-turn, backchannels and authenticated owner interruptions. LiveKit documents adaptive interruption with explicit caveats for self-hosted pipelines. A VAD spike must not instantly cancel a spoken thought.
- **Audio/face:** derive initial mouth envelope from actual PCM using this optimized converter, then seek phoneme/viseme synchronization only if blind quality evaluation and resource measurements justify it. Animate eyes, brows, shoulders and twin-tail hair from the same grounded moment; enforce reduced-motion preference.
- **Voice:** benchmark locally viable CPU-oriented TTS candidates. Pocket TTS v4.0.0 (October 20, 2026) introduced small English models; the October 21 v4.0.1 release repaired small-model text pronunciations. Validate voice likeness, consent/licensing, streaming first-audio latency, conversational naturalness and CPU contention on *STAR's* machines, not a marketing benchmark.
- **Persona:** stable interests, humor, playful cat/puppy modes, and stories arising from actual verified in-game activities. Disclose that STAR is an AI VTuber; never manufacture human relationships or personal history as fact.
- **Safety and production:** independent moderated chat ingress; source/content boundaries; no open-ended account access, money spending or public streams from these evaluators. Broadcasting, gameplay and memory retention require their own owner-authorized gates.

## Sequenced technical experiments and acceptance
**Experiment A — audio CPU path (this PR):** exact old/new envelopes at multiple rates and chunking, measured speed on Linux; repeat on Windows Python 3.12+ and Python 3.11 fallback. Only graduate when PCM equality, audible cursor, stage interruption, OBS/game FPS and TTS total latency remain non-regressed.

**Experiment B — joined streaming latency:** run a *private offline recorded* Windows rehearsal with OBS, synthesized speech and original rig. Measure audible first chunk, lip-sync offset, late/phantom mouth motion, frame drops, CPU/GPU queues, and recovery after interrupts. A shorter converter time does not prove these other measures improve.

**Experiment C — held-out gaming practice:** instrument five authored private Studio scenarios (movement, aiming, objective detection, multiplayer events, save/reopen). Each has independent state-based success proof and at least one unseen variant. Compare 20+ paired episodes baseline/candidate on complete success, safety, time and learning-transfer performance; pre-register outcomes.

**Experiment D — episodic knowledge:** create provenance-safe memory questions after each verified episode; evaluate delayed recall, temporal order, spatial/causal inferences, confidence calibration, and privacy deletion. Synthetic self-reported goals do not count as mastery.

**Experiment E — TTS model routing:** A/B current Star voice vs Pocket TTS 18m/7m variants where permitted, measure CPU usage, first audio latency, real-time-factor, paired blind naturalness, voice identity and listener interruptions under simultaneous gameplay.

**Release gates:** independent held-out evaluation; owner-approved private rehearsals before public streaming; no regression in existing gameplay, speech, identity transparency, moderation, privacy or reduced-motion behavior; runnable rollback via Star Core Forge. GitHub is an optional publication mirror rather than the runtime improvement engine.

## Priority after this change
1. Integrate Windows Studio's witnessed playtest events into the already-built game-journey verifier; don't accept a signed receipt without independently establishing actual game state.
2. Wire existing stream turn-taking, stage, PCM converter and OBS/Windows capture into one offline rehearsal with a saved *metrics-only* report.
3. Run baseline and candidate local inference/TTS models on real workloads with reserved gaming resources.
4. Build a verified episodic-skill curriculum and score unfamiliar challenges, then use errors to choose the next practice task.
5. Only after integration: enrich laughter, breathing/hesitations, expressive eye/rig motion and stream social intelligence based on actual gameplay events.

## Source references (retrieved 2026-10-29)
- Roblox, *Assistant Updates: Studio Built-in MCP Server and Playtest Automation* (March 5, 2026): https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643
- Roblox, *Introducing StudioTestService* (December 4, 2025): https://devforum.roblox.com/t/introducing-studiotestservice/4116257
- *OpenGameEval: Benchmarking Agentic Programming and Exploration in a Stateful Game Engine* (October 2026): https://arxiv.org/abs/2610.02563
- *EMemBench: Interactive Benchmarking of Episodic Memory for VLM Agents*, EMNLP Findings 2026: https://aclanthology.org/2026.findings-emnlp.905/ and https://github.com/InternLM/EMemBench
- LiveKit, *Turns overview* and *Interruption Handling*: https://docs.livekit.io/agents/logic/turns/ and https://livekit.com/blog/turn-detection-and-interruption-handling
- llama.cpp HTTP server documentation (metrics): https://github.com/ggml-org/llama.cpp/tree/master/tools/server
- Kyutai Pocket TTS v4.0.0 (October 20, 2026) and v4.0.1 (October 21, 2026): https://github.com/kyutai-labs/pocket-tts/releases

**Limitations:** STAR's new PCM hot path is faster on the measured host. There is no evidence here of more capable foundation-model reasoning, increased game mastery, better broadcast quality or human-equivalent cognition. Those remain separate measurable engineering goals.
