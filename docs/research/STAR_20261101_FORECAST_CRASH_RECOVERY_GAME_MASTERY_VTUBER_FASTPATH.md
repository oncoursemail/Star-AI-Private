# STAR AI — Crash-resilient game learning, measured streaming intelligence, and humanlike VTuber systems
**Research and engineering note: November 1, 2026.** Implemented in the draft PR; not a deployed game-playing or broadcast system.

## 1. Concrete engineering finding — autonomous learning could deadlock after interrupted practice

### Observed code path
The opt-in `GamePredictionLab` records a prospective probability *before* Star attempts an offline game objective, then learns calibration only from an independently verified, signed practice outcome. It allows at most 64 pending forecasts, a sensible bound for a live game host. But it previously never retired forecasts that the game host failed to resolve (for example after a process crash, interrupted match, or lost outcome receipt). After 64 abandoned forecasts, all subsequent `precommit` requests failed indefinitely even though the outcome acceptance window was only 180 seconds. This interrupts the feedback loop that lets Star discover weaknesses and practice them.

### Implemented change
- On a *valid* new prospective precommit, under the existing database lock, atomically mark any pending forecast older than the strictly enforced 180-second result window `cancelled`.
- Keep the cancelled records and run IDs. They cannot be replayed as fresh predictions or converted into verified outcomes. Never delete verified calibration data.
- Preserve the exact 180-second inclusive boundary and the existing 64-inflight maximum.
- Create a SQLite partial index on `predicted_unix_s` for pending rows only; stale-run cleanup does not need to scan the entire calibration ledger.
- Expose a **metadata-only** `expired_pending` counter. No user messages, game screenshots, player identities, or evaluator signing secrets enter telemetry.
- No background thread, model call, network dependency, game control, or default-on behavior added.

The persistent ledger is still capped at 20,000 rows overall. This patch restores abandoned *pending capacity*, not indefinite unbounded training; a future version needs owner-approved archival/rotation with integrity and replay protections before declaring long-term durability solved.

### Offline verification
The test suite now exercises 64 pending forecasts at the legal deadline; automatic recovery at 181 seconds; irreversible old-run rejection; preservation of younger pending results; invalid new forecast not mutating pending state; verified calibration surviving cleanup; and process restart with abandoned SQLite rows. Run the modified module's tests and the connected signed-evidence, curriculum and game-deadline suites. Do not mistake test counts for real gameplay success.

## 2. Architecture: a fast acting agent, a slower teacher, and independent learning truth

STAR's gaming loop should have three explicit speeds:

1. **Reflex (frame deadline)** — existing `GameDeadlineRouter` and deterministic rules handle no-time-to-think controls from recent verified game-state measurements. Never block on a large language model when the action becomes stale; an expired action is worse than an omitted one.
2. **Tactical (100 ms–seconds depending on game)** — a bounded local vision and reasoning worker estimates obstacles, resources, goals and next safe actions. It returns candidate plans, confidence, and source frame/episode IDs. The host verifies current state *again* at the input boundary and declines stale or out-of-policy actions.
3. **Study (between rounds / off-stream)** — stronger teacher models review *permitted* recordings, discover patterns, generate adversarial training tasks, and propose skills. A separate verifier assesses them against held-out game versions, maps, difficulties, randomized seeds and other players. `GamePredictionLab` logs prospective probability and post-action signed evidence; `GameTransferAuditor` must protect target holdouts from leakage.

Use a curriculum with baseline -> intervention -> matched held-out attempt -> confidence interval -> regression check. Schedule revisits of old mastered moves and newer failures. A skill should get promoted only when win rate, safety/legality, input precision and latency on new tasks improve against a frozen baseline. Practice-only wins are not proof of transfer. Make meaningful failure categories: late input, unexpected geometry, missed HUD cue, camera loss, wrong map state, game-rule misconception and infeasible plan.

**Research support:** OmniGameArena (2026) evaluates agents on 12 Unreal Engine 5 games across solo, PvP and co-op, including changes under repeated reflection and held-out variants; use that *experimental design* rather than copying its reported scores. [OmniGameArena overview](https://arxiv.org/abs/2606.09826). Roblox's [StudioTestService](https://create.roblox.com/docs/reference/engine/classes/StudioTestService) supports scripted play and multiplayer clients; it should be an explicit validation stage, followed by independent human visual review.

## 3. Game-making intelligence: stop accepting merely executable but ugly builds

ICML 2026 [GameDevBench](https://sethkarten.ai/papers/gamedevbench.html) covers 132 game-development tasks. Its authors report 54.5% overall for their best evaluated agent, just 31.6% on 2D graphics tasks, and improved results for one model when image/video feedback was added (33.3% to 47.7%). Those numbers belong to that benchmark, not Star. They show why a code-only repair loop will not deliver the owner's expected polish.

For Roblox, Blender and other engines, require a **scene contract** before Star edits anything: object hierarchy snapshot, reference dimensions, placement intent, anchors/support, transform convention, layer/collision masks, lighting/texture budgets, rig topology, animation timeline, screen safe areas and target device classes. Evaluate after each major edit:
- Luau syntax/type/static lint and allowed API compatibility;
- orphaned/unanchored structures, wrong parent relationships, intersections, gaps, collision escape routes, bad texture/UV alignment;
- screenshot/video comparisons from at least two viewpoints and mobile/desktop viewport sizes, with independent visual assessor and structured failure reasons;
- StudioTestService single-player, replicated client/server ownership, join/leave, remote-validation and network impairment tests;
- a short real playable objective and end-to-end success witness, not just "Studio opened";
- rollback in Star Core Forge when any required acceptance gate fails. GitHub is optional export/publication, not the internal learning store.

For UI and animation, maintain curated style references with license/provenance; assess alignment, focal hierarchy, animation timing, silhouette, color contrast, natural hand grip, collision and consistent proportions. A flashy image cannot substitute for editable production assets.

## 4. Humanlike AI VTuber: synchronized social behavior rather than fake feelings

What makes Star convincing is **causal continuity** across gameplay, voice and motion, not repeating human-sounding catchphrases. A real event should flow through:
`trusted game state / moderated viewer turn -> event arbitration -> grounded plan -> first audible PCM -> mouth envelope / expression -> OBS witness -> permitted episodic recall`.

Current pieces in this repository already include `StreamDirector`, `StarStage`, `QuietAttention`, `StreamEpisodeJournal`, `StreamLoadGovernor`, OBS witnesses, and an offline social-turn benchmark. The next integration should connect their verified host receipts rather than adding yet another parallel chat system.

- **Presence:** small idle blinking, differentiated listening/playing gaze, game-focused silence, expressive but bounded head/hair/twin-tail movement and accessibility reduced-motion modes. Do not interpret viewer private traits or emotions from weak signals.
- **Speech:** streaming TTS and an interruptible playback endpoint; mouth follows **audible** samples, not unplayed generated text. A disconnected output route should not lip-sync speech viewers never heard. Measure actual first sound and stop time per matched conversational case.
- **Timing:** end-of-turn detection should use VAD plus acoustics and, when available, meaning. LiveKit documents an audio-based `v1-mini` detector that runs locally on CPU, whereas its full `v1` option can use a cloud service. For Star's local-first policy, explicitly pin and benchmark the offline path rather than assuming a library defaults to it. [LiveKit turn detector](https://docs.livekit.io/agents/logic/turns/turn-detector/).
- **Voice and hardware:** Kyutai's Pocket TTS has CPU-oriented small English models introduced in October 2026 (18M, 7M and 2M-class). Quality, expressiveness, pronunciation and first-audible latency must be compared in the actual pipeline; a faster tiny model is not automatically a better voice. [Pocket TTS repository](https://github.com/kyutai-labs/pocket-tts).
- **Identity and memory:** stable persona preferences, game memories based on actual signed experiences, genuine chat-history uncertainty, recurring interests/hobbies and clear ability to say "I don't know" or "I haven't tried that game yet." Star can perform warm or playful emotions through expression but should not falsely claim biological human experiences or independently proven consciousness.
- **Social agency:** voluntary small projects, viewers' questions, co-streams with owner consent, and turn-taking with Astro/Amber. Apply rate limits, content moderation, privacy retention boundaries, and disclose AI identity instead of impersonating a person.
- **Long sessions:** caps on pending viewer turns, caches, generated sound queues, memory growth, as well as a clock-safe reconnect protocol. Twitch EventSub WebSockets can deliver duplicate notifications; reconnects require overlapping old and new connections until the new Welcome arrives. [Twitch handling guidance](https://dev.twitch.tv/docs/eventsub/handling-websocket-events/). This is the basis for exactly-once *local reaction decisions*, not a guarantee of network exactly-once delivery.

## 5. 8 GB GPU / 32 GB RAM fast-path experiments

Keep the game renderer and OBS ahead of background AI work. A common pitfall is choosing an optimization that raises average tokens/s but makes Star freeze for one viewer response or steals 10 FPS during gameplay.

For every model/quantization/draft configuration, measure on the **owner-authorized Windows host**:
`end_of_viewer_turn -> first_audible_PCM`, `owner_interrupt -> playback_silence`, action age at input delivery, p50/p95/p99 first-token latency, per-category tokens/s, draft acceptance, CPU use, game 1% lows and frame-time p95/p99, OBS rendering/encoding skips, and peak/reserved VRAM. Include a memory+CPU-fallback configuration that works with no GPU.

Use [llama.cpp SPEED-Bench](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md) to compare baseline versus draft-model and draftless n-gram speculation by category (coding, reasoning, speech/game commentary and high entropy). The official benchmark measures latency/throughput/acceptance; it is **not** a live-stream quality certification. A September 2, 2026 [Windows report](https://github.com/ggml-org/llama.cpp/issues/28219) describes a severe speculative decoding slowdown in certain builds/configurations. Treat upstream reports as hypotheses for an A/B test, never as measurements on Star's machine.

Do not rewrite all Python to Rust based on a language reputation. Profile the actual hottest path first. Rust is a strong candidate for high-frequency capture buffers, frame differencing, lock-free bounded queues, network parsing and scheduling where Python overhead is established. Keep policy, high-level planning, training orchestration, evaluation and most UI in the clearest maintainable languages. Use PyO3 for a boundary with explicit ownership, cancellation, panic handling and zero-copy tests only if profiling shows end-to-end gains.

**Promotion rule:** no inference optimization is accepted if it improves tokens/s but worsens measured p95 audible latency, gameplay frame times, missed game actions, OBS drops, user interruptions or correctness beyond preregistered tolerances. Revert safely through Star Core Forge.

## 6. Acceptance plan (targets to validate, not results)

| Lane | Required evidence | What a fail means |
|---|---|---|
| Game learning | 64 abandoned forecasts automatically recover after deadline; no replay; 20+ independent seed/map/version trials | Keep learner in offline practice mode |
| Reflex and planning | Every action has fresh state ID and meets current deadline; zero unauthorized inputs in test | Disable action path |
| Humanlike VTuber | Reviewed matched scenarios for viewer questions, commentary, accidental noises, owner interruptions and critical-game silence; measured audible playback and motion | Revert TTS/turn-taking/animation candidate |
| Hardware and speed | Same game, map, OBS settings and output quality; p95/p99 voice latency and 1% low FPS no worse than accepted baseline | Roll back speculative/caching/GPU changes |
| Roblox creation | Clean syntax and multiplayer tests, independent screenshots/video review, collision and geometry audit, playable win/fail loop | Do not release game artifact |
| Autonomy and privacy | Owner-controlled tools/budgets, no outside prompt-driven privilege changes, no secrets/recordings in public GitHub | Quarantine, redact, roll back |

First implement **host wiring** for the existing signed-trial and stage speech receipts, then conduct a private synthetic game/OBS rehearsal on Windows. Archive only aggregate safe metrics. Star Core Forge should retain baseline artifacts and promote only validated improvements.

**Status boundary:** This document records research and a single reliability code change in the game forecasting ledger. No live game control, speech-model installation, persona consciousness, Twitch broadcast, external skill gain, Rust speedup or Windows benchmark is claimed. All high-impact externally visible or irreversible actions stay owner-controlled; ordinary permitted background practice can remain autonomous.
