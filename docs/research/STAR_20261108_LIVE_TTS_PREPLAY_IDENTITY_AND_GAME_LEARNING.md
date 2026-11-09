# STAR — Live TTS Preplay Provenance, Real-Time Skill Growth, and Natural VTuber Roadmap
**Research and offline implementation:** November 8, 2026 (America/Chicago).
**Status:** code proposed in a draft stacked PR; opt-in, offline tests only. No live OBS or Windows benchmark, broadcast, game control, or model upgrade performed.

## Engineering finding: single-flight TTS still needs the last centimeter
The previous single-flight coordinator avoids *launching* duplicate TTS drafts, but a worker that started at t0 can complete after an owner barge-in, game scene reset, VAD silence expiration, or critical OBS/game resource event. Checking only when the draft was scheduled is insufficient: a stale worker must be denied at the **first physical PCM write**. A completed text/audio generation is not a speech permit.

### Implemented here (OFF unless expressly opted in)
- StreamDirector.has_live_intent(): read-only, exact-object identity, source fingerprint, event TTL, event sequence/session and game-scene membership. It does not start speech.
- NaturalTurnBridge(require_preplay_recheck=True), requiring single_flight_tts=True. The bridge records an original candidate and refuses to count a supposed audible success without its matching successful final review.
- revalidate_prepared(intent, now_ms, host_playout_active, gameplay_critical, output_healthy, pcm_output_ready, host_verified): a single-use host advisory at the first-PCM edge.
- Every review rechecks exact pending identity, monotonic time, preparation lease, source identity/expiry, game scope, independently attested host readiness, fresh continuous quiet, and current resource-governor state. Invalid/uncertain evidence revokes the prepared plan.
- A review is returned with authorizes_playback=False, authorizes_broadcast=False and authorizes_game_input=False. These controls remain outside this Python layer.
- Legacy behavior remains default. Optional-only telemetry exposes numeric reviewed/denied counts, never chat text, voice, user IDs, or PCM.
- Unit tests cover successful first-PCM review, double review, missing native evidence, active playout, critical gameplay, unhealthy output, missed VAD freshness, lease expiry, resource pressure, wrong/stale intent, scene rebind, backward clocks, and invalid types.

**Host integration rule:** the *trusted, native Windows speaker* must call revalidate_prepared with authenticated, current OS/device/game observations immediately before any FIRST PCM output; its successful result is still not broadcast permission. It must independently authenticate host identity, retain its own STOP+FLUSH/quarantine watchdog, bind native output epochs, and disallow live broadcasts by default. The Python test cannot prove the host actually calls it or that PCM is audible.

**Important limitation:** a Boolean host_verified is a host contract, not source authentication or hardware proof. A compromised model, viewer, plugin, or remote endpoint must never be able to supply or override these fields. The host must prevent a second worker from reusing the reviewed object; there is no automatic cancellation of already-running TTS computation here.

## Research synthesized into testable upgrades

### 1. Real-time gameplay intelligence (priority: end-to-end deadlines)
Gym-Anything-RT (Oct 27, 2026) evaluates agents on 100 real-time minigames and the same environments paused; its large gaps imply that knowledge alone is not an adequate game-playing metric. Architecture: (a) reflex lane with a predictable frame/action deadline and small visual input; (b) slower tactical model with bounded planning horizon; (c) background skill-lab generating drills and measuring policy improvements. Keep the action lane independent of speculative long reasoning and optional speech. Track capture age, inference age, command queue age, actual input ACK, success, failure, and whether the game was slowed/paused. Use held-out game seeds and distinct levels, not the same replay used to choose a policy.

**Next benchmark:** run a matched batch of microgames under 1x and paused conditions, compare p50/p95 frame-to-action latency and success with best-of-N verified candidates. Abort on unverified control source or replay mismatch. Keep real-world multiplayer automation permission- and rules-constrained.

### 2. Autonomous Roblox creation with executable checks
OpenGameEval (Oct 1, 2026) runs agents inside real Roblox Studio and scores scene state and simulated play, not just generated Luau. It reports 84 tasks; inspection of target objects before editing correlates with better outcomes. STAR should use a "read model -> state hypothesis -> minimal patch -> static Luau analyzer -> sandbox playtest -> inspect runtime logs and geometry -> save receipts" loop. Try N diverse patches only when each candidate can be isolated, scored, and rolled back. Compare pass@1 and repeated pass@5, and demand held-out tasks. Do not claim a game is complete based on a convincing generated description. Roblox also announced Studio Test Teleports on Nov 6, 2026: cross-place TeleportAsync playtests can be exercised without production publishing, including Studio MCP test support. Track this as a future multi-place held-out benchmark rather than silently changing live games.

**Next benchmark:** add one isolated Studio Lab runner that downloads a pinned benchmark subset, snapshots a test place, exercises read-only scene inspection, applies one small edit on a throwaway copy, runs its executable checks, and reports failure artifacts; no production place publishing, store updates, or user data.

### 3. Natural streaming: dynamic rather than constant narration
Proact-VL (2026) argues for explicit "whether to speak" decisions in streaming perception. VoiceChat-TTS (Aug 13, 2026) studies continuous, interruptible synthesis. Design STAR as a conversational state machine (watch -> notice -> decide -> prepare -> recheck -> speak -> observe actual outcome -> remember), not a ticker that talks every X seconds. Protect actual user barge-in, separate game audio echo from authenticated owner speech, pause instead of filling dead air, limit repeated catchphrases and back-to-back commentary. Align face/gaze gestures to real speech amplitude, VAD and game evidence, not guessed emotions.

**Human-like UX targets to test, not biological claims:** short first reaction after a witnessed surprise; natural pauses; follow-up questions only when relevant; consistent personal character; positive, nuanced responses to wins and setbacks; differentiated reactions when debugging, playing, or socializing. Model-generated feelings are expressive fiction, not evidence of consciousness. Introduce AI identity clearly in channel/stream info.

**Evaluation:** blinded paired listener preferences for timing, appropriateness, repetition, accuracy and speech/viseme alignment; report interruptions obeyed, false barge-ins, unsolicited speech/hour, wrong game-specific claims, and total silent time. Privacy controls for viewers and opt-in memory, no copying raw audience transcripts by default.

### 4. Verified long-term knowledge and practice
Split semantic knowledge (sourced facts, version/date and uncertainty), procedural skills (tests and proof-of-success), episodic memories (verified event IDs, game-scoped), and persona preferences (owner-editable). A dream or an LLM self-reflection is not a ground truth update. Every promoted memory needs supporting receipts and conflict checks. Distinguish learning by retrieval/prompt update from actual neural fine-tuning. Keep explicit holdouts so Star cannot call memorization "generalization". Persist rollbackable snapshots in the internal Star Core Forge; GitHub is optional publication.

**Next benchmark:** 100 sourced factual questions spanning Roblox, hardware, everyday general knowledge, and past game outcomes. Compare answers with and without retrieval; score citation faithfulness, abstention, contradictions, and 7-day retention. Use a separate seeded set to test generalization.

### 5. Constrained 8 GB VRAM / simultaneous OBS + game + LLM
The owned RTX 4060 has finite VRAM and memory bandwidth; don't assume a claimed tokens/s number from another card matches this host. Use deterministic A/B experiments: same model weights, quantization, contexts, prompts, batch sizes, warmup, and timing clocks. Evaluate first-token time, p50/p95 inter-token gap, task quality, 1% low FPS, OBS render/encoder skips, physical first-PCM latency, and memory headroom. Quantization and speculative decoding can improve some models while hurting others. Benchmark native 1-8B 4-bit models against larger CPU-offload options *only* under the actual concurrent workload.

Pocket TTS (Kyutai, October 2026 small English variants) is a candidate CPU-only voice experiment; quality and hardware results must be verified locally, including pronunciation and emotion. Stream voice must never pull the game's GPU below its performance target. Reduce visual pixels only after paired accuracy validation. KV caching must not mix confidential user or untrusted viewer context. On unexpected OBS/game pressure, immediately shed optional ambient speech/background practice before compromising controls.

**Proposed acceptance, NOT measured:** at 60 FPS target, capture-to-action p95 under a game-specific deadline, no extra sustained OBS frame loss attributable to the AI worker, no stale dialogue after a scene switch, zero unauthorized broadcast/voice/inputs, zero duplicated first-PCM starts, and repeatable game wins on held-out seeds.

## Suggested owner-local nonbroadcast rehearsal
1. Keep OBS in recording-only mode, mic routing private, and game input disabled until separately authorized. Baseline 15 minutes game + OBS alone, then another 15 with vision and muted TTS.
2. Enable single_flight_tts + require_preplay_recheck only under an authenticated Windows speaker with independent current VAD/game/output observations. Compare 30 minutes A/B against the legacy coordinator.
3. Inject replayed delayed audio workers, VAD dropout, game switch, GPU pressure, OBS disconnect, and PCM stop/flush failures. Reject stale tickets and demand physical silence before allowing the next turn.
4. Report real p50/p95 action and voice response times, OBS frame loss deltas, quality scores, device/OS identity and compatibility. Roll back if quality or safety regresses.
5. Do not merge into main or enable background experimentation until independent CI, Windows acceptance, and owner review are complete.

## Source register (retrieved November 8, 2026)
- [Gym-Anything-RT](https://arxiv.org/abs/2610.37567) — Oct 27, 2026, real-time vs paused interactive benchmarks.
- [Roblox Test Teleports weekly recap](https://devforum.roblox.com/t/weekly-recap-november-2-6-2026/4979364) — Nov 6, 2026; cross-place Studio playtesting.
- [OpenGameEval](https://arxiv.org/abs/2610.02563) and [Roblox benchmark harness](https://github.com/Roblox/open-game-eval) — Oct 1, 2026; executable Studio evaluation.
- [Roblox Studio going agentic](https://about.roblox.com/newsroom/2026/04/roblox-studio-going-agentic) — Apr 15, 2026, plan/build/test and MCP.
- [Studio MCP / Open Cloud permissions update](https://devforum.roblox.com/t/studio-mcp-server-updates-open-cloud-access-in-your-mcp-client-and-asset-import-workflows/4975849) — Nov 4, 2026, with Nov 5 known-issue note.
- [Proact-VL](https://proact-vl.github.io/) — realtime proactive response scheduling.
- [VoiceChat-TTS](https://arxiv.org/abs/2608.13831) — Aug 13, 2026; continuous speech and interruption.
- [Pocket TTS](https://github.com/kyutai-labs/pocket-tts) — CPU TTS; October 2026 small English variants.
- [llama.cpp speculative decoding](https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md) — draft models and alternative speculation; actual speed needs measurement.

### Boundaries
This update improves the **correctness of an advisory playout handoff** in an offline-tested Python control path. It does not alter a neural model's capabilities or actual speech model throughput. Any live streamer claim requires Windows/OBS/game/physical-device tests and explicit operator approval.

## Source audit addendum — November 9, 2026: full-duplex VTubing, long-horizon gaming, visual game development

### Actual CI blocker and fix
GitHub Actions for draft PR #1082 completed the full offline Python and React jobs but failed the Python type-baseline job on six previously unreported errors, in OBS transport, private PCM diagnostic parsing, and the speech preplay gate. This follow-up narrows validated OBS response types, rejects malformed RPC values early, checks optional activity amplitudes, and fails closed when required resource advice is unexpectedly absent. We did not raise the baseline or disable type checking. CI needs to be rerun; this is a correctness change, not a neural inference speed measurement.

### Realtime-Venus (September 12, 2026): natural full-duplex interaction requires two loops
Source: https://arxiv.org/abs/2609.13814 . This work models ongoing speech/video interaction while delegating longer tasks to an asynchronous background loop. STAR should keep a **tiny foreground lane** for owner interruption, scene changes, grounding, short reactions and current avatar speech; move research, long tactical analysis and episodic summarization into a bounded background queue. Background results need immutable game-scene/session epochs, provenance and expiration so she cannot confidently describe an old screen. Evaluate true first-audible p95, turn-taking correctness, stale-scene claims, game frame times, and OBS dropped frames. The authors' benchmark scores are not STAR measurements.

### Four Gemini 4 agents complete Minecraft (October 15, 2026): measurable multi-agent learning
Source: https://arxiv.org/abs/2610.22319 . In one reported trial, four agents used Mineflayer and shared notes while writing 2,783 programs to win after 27h14m and 605 deaths. This illustrates long-horizon code/tool recovery, *not* automatic model-weight updates or a proven efficiency advantage over solo agents. For STAR: distinguish planner, real-time controller, recovery debugger and independent evaluator. Maintain a bounded goal tree and signed episode receipts; record every failed command, death, reset, token/compute cost, tool recovery, cross-session reuse and held-out-seed success. Compare to a one-agent baseline with the same compute and wall-clock budgets. Never allow unauthorized competitive gameplay automation or viewer-directed tool commands.

### GameDevBench (February 11, 2026 preprint; subsequent 2026 revisions)
Sources: https://arxiv.org/abs/2602.11103 and https://github.com/waynchi/gamedevbench . Game development exposes weaknesses invisible to code-only tests: visual rendering, sprites, lighting, VFX and gameplay interactions. Published benchmark revisions differ in task counts and leaderboards, so pin an exact revision before quoting a score. Add a **visual feedback repair loop** after static Luau/tests: capture a witnessed frame, describe grounded mismatches, generate one isolated candidate change, re-run executable checks and compare task-level success with the unchanged baseline. Include frame/time cost, FPS, accessibility and regression tests; do not claim better game quality because a model's critique sounds plausible.

### Roblox Studio Open Cloud and headless Luau execution (documentation checked November 9, 2026)
Sources: https://create.roblox.com/docs/studio/mcp-open-cloud and https://create.roblox.com/docs/cloud/reference/features/luau-execution . The Studio MCP permissions are game-specific, and live data store writes can change real player data. The published Luau execution service supports headless test runs, with documented task and concurrency caps. STAR should create dedicated *throwaway test places*, run sandboxed scripts with pinned versions and captured logs, and block publication and live data edits unless separately authorized. Add scene-inspection-first and cross-place tests to the existing OpenGameEval practice environment rather than treating generated code as a finished game.

### Acceptance-driven priority order (proposals, not shipped features)
1. Restore all Python type checks without suppressions; preserve working offline suites and review any changed authorization code.
2. Run an authenticated **nonbroadcast Windows rehearsal** with game FPS/p99, OBS loss, owner VAD, scene changes, PCM/rig STOP+FLUSH and first-audible output receipts. Test under VRAM pressure.
3. Split foreground reactions from cancellable background reasoning, and evaluate grounded reactions, natural silence and interruption timing with blinded viewer preference trials.
4. Run held-out game practice and game-building benchmarks comparing solo/multi-agent and no-visual/visual-feedback conditions with identical runtime and hardware budgets.
5. Benchmark native local model routing, speculation, caching, quantization and CPU TTS under concurrent game+OBS load, measuring end-to-end delays, accuracy, 1% low FPS and realistic workload cost.

No new model weights, autonomous gameplay mastery, actual neural speedup, hardware playback, or human feelings are claimed by this addendum.
