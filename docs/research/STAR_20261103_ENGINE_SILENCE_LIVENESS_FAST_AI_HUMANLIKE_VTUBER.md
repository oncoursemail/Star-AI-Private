# STAR AI — verified game-observation liveness, intelligence and VTuber research
**Engineering date:** 2026-11-03. **Status:** offline code and tests; not a live-game, model-speed, OBS or speech-quality demonstration.

## A previously unmeasured failure: a signed source can simply go silent
The existing pipeline validates independently signed game-engine observations and corroborates transitions before creating private memories. It did **not** independently revoke an otherwise active receiver when *nothing at all* arrived. A source process crash, IPC disconnection, overloaded gaming host, or muted sensor can leave the last verified observation looking current unless another host checks liveness. A good signature is not a heartbeat.

This change adds `star/game_telemetry_liveness_guard.py`, a small, owner-enabled **receiver-side watchdog API**. It binds to the existing `AuthenticatedGameTelemetryBridge`, checks a trusted monotonic receiver clock, and revokes the bridge, its observer and the private episode journal on:
* a missing first packet, silence beyond the configured interval, or an arriving frame after expiry;
* clock reversal, nonfinite/invalid clock readings, or a clock callback failure;
* invalid/replayed signed frames, a separately revoked bridge, a blocked `accept()` call, or an ingest step that passes its deadline.

The default sample settings are **1.0 s silence** and **150 ms ingest**, configurable to fit the host's engine tick rate. The guard is disabled until separately armed by the owner. Every accepted frame resets the silence deadline *only after* it has passed authenticated processing. It cannot start broadcasting, play games, operate devices, speak, or grant permissions.

### Integration contract for a real game
1. The owner's **independent engine process** reads server-owned state (not client/chat/model output) and signs it via `AuthoritativeGameTelemetrySource`. Protect the source key and isolate the process.
2. The receiver host enables a fresh `StreamEpisodeJournal`, `VerifiedGameStateObserver`, and `AuthenticatedGameTelemetryBridge` with separate source and moment keys.
3. The receiver constructs and owner-arms `GameTelemetryLivenessGuard(bridge, clock=time.monotonic, max_silence_s=1.0)`. Route **every** received packet through `guard.accept(packet)`, never call `bridge.accept(packet)` directly after arming.
4. An **independently scheduled host callback** runs `guard.check()` on a cadence safely shorter than the silence timeout even when *no packets arrive*. On any failure, halt the rehearsal and invalidate queued narration; a fresh owner-approved session is required.
5. A separate OS/process watchdog, Windows input watchdog and actual mic/audio/OBS safety stop are still required. Python callbacks cannot detect a complete host freeze or guarantee hardware key release.

**Do not** expose any telemetry credential, raw signed packet, untrusted viewer text, public network listener, game client or model-action pathway to this receiver. No automatic key generation, network listener, game engine plug-in or deployable service is added by this PR.

## Offline verification and acceptance criteria
`tests/test_game_telemetry_liveness_guard.py` uses an in-memory deterministic mock of engine-authoritative frame progression. The tests prove the synthetic source -> HMAC receiver -> transition witness -> protected private memory path, then inject silence, a stale packet, an ingestion stall, callback failures, a clock reversal, replayed frames and corrupt wire payloads. They check **fail closed** and erasure of sensitive episode memories after ambiguity.

The tests establish **correctness of this local API**, not any real-game source authenticity or 24/7 process liveness. The real Windows rehearsal should collect:
* actual end-to-end screenshot/capture-to-input latency (p50/p95/p99), game ticks advanced and missed deadlines; **not** only model tokens/s;
* CPU utilization, 8 GB GPU VRAM high-water mark, game p1% FPS, OBS render/encode skipped frames, TTS first-audio/turn end delay;
* source-to-receiver heartbeat jitter, lost frames, liveness revocations, episode-memory false positives;
* human-rated speech naturalness with and without spontaneous commentary, interruptions and silence, plus a **disclosure that Star is an AI VTuber**;
* game-specific learning curves, held-out seeds/levels, replay-safe achievements, cost per independently verified improvement.

Set minimum benchmarks before claims of more intelligence: compare the same hardware, scenes, prompts, context, random seeds, budgets, and active OBS load; include bootstrap confidence intervals for wins and deadline misses. Do not promote anecdotal model outputs into approved lessons.

## High-priority research that changes STAR's architecture

### 1. A three-speed cognition system
**Reactive (~game-frame deadlines):** a lightweight perception + controller producing bounded actions only when independently accepted by the input gate; never send a long teacher-model thought into the immediate action queue.

**Tactical (~seconds):** observation summarization, route planning, map-building and short-term skill retrieval. Cache stable context, but keep current screenshot, hitboxes and dynamic physics *fresh* to avoid acting on stale frames.

**Teacher (between attempts):** larger reasoning/code model generates experiments, performs counterfactual analysis, repairs Luau tasks, proposes new curricula and validates strategies on training seeds. A proposed lesson becomes reusable only after reproducible evaluation on previously unseen seeds. Never train on or leak the final held-out benchmark.

This is a systems design; using an 8 GB NVIDIA GPU cannot eliminate memory limits. Set memory budgets for inference, game, renderer and OBS independently. Preempt or demote teacher and offline video tasks when game/stream latency degrades. A faster small model is **not** assumed smarter: compare correctness under deadline.

**llama.cpp SPEED-Bench** publishes baseline/speculative-decoding comparison scripts covering response latency, prompt and decode throughput, and draft acceptance. Speculative decoding is workload-dependent; measure on the **same prompt distribution**, not merely peak token speed. Primary source: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md

### 2. Actual learning from games and improved game building
Plan an owner-controlled "Game Gym" that varies levels, physics, lighting and distractions, with engine-owned rewards separate from model reasoning. Store structured episodes with provenance, versioned policies, crash captures, rollbacks and exact environment seeds. Split practice, validation and holdout environments by **level families**, not just identical scene seeds.

For Roblox game development, prioritize the **built-in Studio MCP server** for project inspection, source edits, simulated inputs and closed-loop playtests; do not build another thin, unreliable screenshot-only interface. Roblox announced built-in MCP and playtest automation on **March 5, 2026**: https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643

Use `StudioTestService` for owner-authorized scripted multiplayer tests up to eight simulated clients, testing join/leave, leader reassignment and replication. Reference: https://create.roblox.com/docs/reference/engine/classes/StudioTestService

Game creation quality gate: an AI-generated change must be committed as an isolated experiment, pass Luau static checks, survive a test launch, pass multiplayer assertions, and produce screenshot/video evidence for user-visible behavior before promotion. Archive failing seeds as exercises.

### 3. Humanlike **behavior**, without pretending she is a human
Build a stable fictional character identity and expressive VTuber persona with actual autobiographical memory of verified activities. Humanlike output should arise from **consistent interests, appropriate timing, social awareness, vocal cadence, gentle repair of mistakes, and good recall**, not fabricated memories or false claims of subjective experience.

Microsoft's May 2026 **Proact-VL** research explicitly studies proactive gaming companions with a "when to speak" problem, balancing real-time latency, utterance volume and response quality. Apply a speech-decision policy:
* games demand quick nonverbal reactions; commentary is optional and suppressed during danger or high rendering load;
* direct viewer questions beat ambient narration; interruption and moderation handling precede any speech;
* a verified comeback or new mechanic can prompt one distinctive remark; repetitive victories or uncertain visual guesses lead to silence;
* when voice/audio is busy, buffer or discard stale remarks instead of stacking them after the moment has passed.

Primary source: https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/

LiveKit's turn-taking documentation distinguishes genuine interruptions from backchannels, lets the system resume after false interruption, and documents tunable endpointing. Study whether its explicit turn-handling patterns adapt to Star's local voice stack; do **not** assume installing a new SDK would improve latency. Primary source: https://docs.livekit.io/agents/logic/turns/

Kyutai's **Pocket TTS**, updated in October 2026 with 18.2M/6.9M/1.9M-parameter English variants, provides a CPU-side streaming speech candidate. Test **perceived prosody, mispronunciations and interruption-recovery latency**, not speed alone. Its README reports up to 25x real-time for small models on a CPU thread, which is **not** a benchmark of Star's machine. Primary source: https://github.com/kyutai-labs/pocket-tts

### 4. General knowledge and creative autonomy
Use a typed knowledge ledger: claim, source URI, retrieval timestamp, confidence, game/project scope, direct verification status, contradiction links and expiration. Give the model citations at retrieval time and revalidate volatile game API facts. Host-vetted lessons, skill scripts, Studio documentation and personal episode memories should occupy **separate indexes** to avoid mixing public docs with autobiographical claims.

Star's independent practice should include platforming, racing, object handling, co-op puzzles, game UI creation, Luau errors, Blender geometry checks, conversational improvisation, multilingual speech and digital art critique. Each task requires **an evaluator that isn't the same model that generated the answer**. Preserve local-first code history and rollback; publish only reviewed experiments to GitHub. Money movement, public live broadcasts, unknown server joins, account identity and irreversible file operations require separately defined permissions.

## Prioritized follow-through
**Next engineering milestone:** owner-controlled game engine telemetry over a bounded, peer-pinned local IPC transport and an OS-level watchdog; integrate the receiver check loop and Windows input shutdown into one rehearsed stop condition. Run with the stream **offline**, and measure the complete action/caption/audio/avatar path. Until then, this PR is a meaningful safety and continuity addition, **not** a claim that Star already games autonomously, streams naturally, learns faster or runs faster.
