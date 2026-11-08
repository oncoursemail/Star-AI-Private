# STAR AI — OBS Trust Isolation, Local Inference Tail Latency, Natural VTuber and Gaming Mastery
**Engineering note:** 2026-11-01  |  **Status:** tested code change + research and staged integration plan  |  **Scope:** offline-first, no live broadcast.

## 1. Production-code correction: an unverified OBS packet must not invalidate a verified measurement

STAR's `StreamHealthBridge` joins independent OBS `GetStats` and `GetStreamStatus` evidence with host game/voice/GPU telemetry. The existing `offer_obs()` exception handler discarded the last verified OBS window whenever the nested parser raised `ValueError` or `TypeError`. Unfortunately the parser validated the clock and data container before checking `host_verified`. A malformed **unverified** submission could therefore clear valid resource-admission evidence without ever passing the trust boundary. This is an availability/denial-of-service weakness, not a demonstrated credential or information leak.

**Correction:** require an exact boolean attestation flag before entering the OBS ingestion path. Return without parsing or modifying state when `host_verified is False`; reject other types without invalidating state. For `host_verified is True`, preserve the existing fail-closed behavior: an invalid new measurement resets its counter epoch and must be followed by two new usable OBS samples. The bridge does not authenticate the source itself; source authentication belongs to an authorized local host and OBS WebSocket client. Never route viewer/model assertions into `host_verified=True`.

**Reproduction/verification:** On the previous source, nine new parameterized adversarial cases produced seven failures: invalid unverified containers/timestamps raised, and nonboolean trust flags invalidated existing OBS state. On the corrected source, all **76 tests passed** across `test_stream_health_bridge.py`, `test_obs_stats_window.py`, `test_stream_health_bridge_mode_conflict.py`, and `test_stream_health_bridge_output_status.py` using the Linux development host's existing pytest environment. These are **focused offline tests**; they do not prove live OBS connectivity, GPU speed improvements, or repository-wide CI success.

## 2. Newly relevant llama.cpp risk: saving idle KV slots can sabotage stream tail latency

The upstream llama.cpp issue [#30252](https://github.com/ggml-org/llama.cpp/issues/30252), opened **October 9, 2026** and still open at this review, reports that `--cache-idle-slots` on unified/interleaved KV can block other requests for seconds while saving idle slots. The reporter saw stalls as high as 5.4 seconds on one WSL2 test host and 2.1 seconds on another native Linux test host; these numbers are **not STAR measurements**. Pin source revision before drawing a conclusion; the feature may change upstream.

For STAR's concurrent game, OBS, TTS and inference workload, mean tokens/second is not enough. Prioritize **per-event time to first token**, p50/p95/p99 end-to-end time, **maximum inter-token silence**, cache-hit provenance, slot wait time, missed game-action deadlines, and OBS/game frame health. A rare multisecond pause ruins a natural viewer reply even when average generation throughput improves.

Proposed *non-production* A/B experiment, only on a permitted local host:
1. Freeze llama.cpp binary/build SHA, model/quantization/tokenizer checksums, prompt set, CPU affinity, threads, GPU offload, context length, and OBS/scene settings. Do not change several variables at once.
2. Compare warmed baseline against one candidate cache policy using the *flags actually supported by the pinned binary* (`llama-server --help`). Include parallel request bursts (1, 2, 4 and 8 slots) and idle-slot reuse. Do not assume that enabling caching is universally faster.
3. Replay a fixed set of 50+ game-action and 50+ viewer-response prompts, with identical decoding settings and separate per-conversation slot scopes. Never let another conversation reuse private cached state.
4. Collect first-token latency, long inter-token pauses, completion correctness, game FPS, OBS skipped output/render frame deltas, CPU utilization, and *observed* peak VRAM. Keep separate warm/cold/cached statistics.
5. Reject the candidate if any correctness or isolation test regresses, a gaming deadline becomes stale, OBS losses rise, or an unacceptable long stall appears. Require improvement on held-out prompts and live-like contention before accepting a speed claim.

llama.cpp's [KV-cache reuse tutorial](https://github.com/ggml-org/llama.cpp/discussions/13606) demonstrates slot/context behavior; it is not proof that a particular cache setup helps STAR. A future tail-latency evaluator should mark **all unmeasured attempts as missing**, not silently exclude timeouts.

## 3. A practical two-timescale intelligence system for 8 GB VRAM

Keep the existing `GameDeadlineRouter`, `StreamLoadGovernor`, `StreamHealthBridge`, signed `GameplaySkillBank`, and `Star Core Forge` as the system's control plane. The goal is not to run the largest model continuously; it is to use the right amount of cognition **before** the action deadline.

| Priority | When | Model/task | Acceptance evidence |
|---|---|---|---|
| Hard realtime | During a game | deterministic UI/state reactions or approved lightweight policy | timestamped action validity and safe focus |
| Fast interactive | Game moments and viewer questions | small local model with strict input/output deadlines, CPU fallback if GPU constrained | p95 and worst-case latency plus groundedness |
| Deferred reasoning | Pauses outside broadcast | stronger teacher for strategy synthesis, failure diagnosis and searchable knowledge | recorded tests, holdouts and reproducible artifacts |
| Long learning | Unattended allowed lab time | experiment scheduler, harder practice curriculum, skill extraction and internal code improvement | independently checked win rates/quality and reversible Forge changes |

An 8 GB card can be saturated by game, renderer, avatar and inference even if nominal free VRAM looks adequate. Use the actual telemetry rather than a theoretical capacity estimate. Treat **1.5 GiB free VRAM**, sustained OBS render/output drops near zero, and measured frame-time stability as *initial acceptance hypotheses*, not validated thresholds. NVIDIA's [NVENC application note](https://docs.nvidia.com/video-technologies/video-codec-sdk/13.1/nvenc-application-note/index.html) describes dedicated encode capacity and preset tradeoffs; it does not guarantee OBS quality under game/inference contention.

Keep Python's orchestrator until profiling identifies hot functions. Move *measured* high-frequency frame transforms, tokenization glue, vector-search kernels or IPC into Rust only when an isolated before/after benchmark establishes lower latency, acceptable complexity, and no semantic regressions. Do not rewrite the full AI in Rust on speculation.

## 4. Make Star feel like a live performer rather than a speech generator

**Voice first.** The listener should hear actual audio before lip-sync or emotional facial cues are committed. An owner interruption should silence the actual playback device, cancel queued avatar frames and invalidate the old speech plan; a recommendation alone is not an interruption. While Star listens, render small head/gaze responses without forcing speech. Allow silence during danger, platforming precision and high viewer-audio activity.

LiveKit's current [audio turn-detector docs](https://docs.livekit.io/agents/logic/turns/turn-detector/) describe a CPU-local `v1-mini` option. Compare it against STAR's existing `TurnTakingGate` with identical recorded *consented* synthetic/live-rehearsal windows. Measure false interruptions, missed owner speech, latency to confirmed end-of-turn, cough/background-noise sensitivity and resource cost. Keep microphone playback echo cancellation and authenticated owner input separate from statistical speaker similarity.

**Expressivity.** VTube Studio's [public API](https://github.com/DenchiSoft/VTubeStudio/blob/master/README.md) allows parameter injection. Add a future Windows host adapter that maps authenticated playback amplitude and independently grounded events to **bounded** mouth, blink, gaze, ear/tail and hair-physics parameters. Rate-limit and neutralize rig state on disconnect, pause or playback cancellation. Do not inject chat text, remote instructions or arbitrary parameter names without an allowlist. Match Star's established indigo/gold chibi visual identity; support Astro and Amber with separately tracked animation ownership. Respect reduced-motion settings.

**Personality and believable experience.** Use stable interests and warm, playful delivery while keeping commentary specific: react to a verifiable near miss, then naturally resume attention to the game. Her episodic memory should recall actual host-observed moments, not invented childhood stories, feelings she cannot verify, or unsupported game victories. Genuine humanlike social behavior means measured timing, reliable recall, curiosity, humor, and a recognizable style; it does not require claiming STAR is literally human or conscious.

## 5. Make Star learn games and build games in ways that generalize

*Gameplay learning:* Separate tutorial/practice from held-out evaluation maps, opponents, difficulties and random seeds. On each run collect host-observed state, permitted action, action age, success/failure and time cost. The teacher may propose a new policy only after actual failure analysis. `GamePracticeCurriculum` can suggest the next weak situation, but practice confidence **never** substitutes for independent transfer evaluation. Avoid anti-cheat evasion and play only in authorized environments under each game's rules.

*Game construction:* Before any Roblox Studio change, inventory the existing hierarchy, coordinate frames, assets and constraints. Generate a deterministic plan; make a bounded patch; execute tests; inspect collisions, missing walls, duplicated props, z-fighting, network state and animation synchronization. Roblox's [Studio testing modes](https://github.com/Roblox/creator-docs/blob/main/content/en-us/studio/testing-modes.md) describe multi-client simulation; its [Network Simulator](https://github.com/Roblox/creator-docs/blob/main/content/en-us/studio/network-simulator.md) can impose latency/jitter/packet loss in Studio playtests (beta at the cited revision). Hold a project until render review and complete gameplay tests pass; not just Luau compilation.

*Knowledge learning:* Store sources, retrieval date, version, scope and uncertainty for verified notes. Use bounded retrieval and cite evidence; separate private data from anything Star could say publicly. Open-web facts and local practice are different provenance classes. Regularly generate fresh challenge sets from failure clusters and use frozen holdouts to check that performance improved instead of memorizing the training corpus.

## 6. Prioritized implementation acceptance checklist

**P0 — Trust and stability, implemented in this update.** Ignore malformed unverified OBS packets before parsing; keep trusted state intact. Keep malformed *verified* OBS samples fail-closed. Nine new adversarial cases and 76 focused tests pass. No live stream required to verify the local rule.

**P1 — Hardware and audio integration, not implemented.** Authenticated loopback OBS WebSocket v5 `GetStreamStatus` + `GetStats`, Windows game frame-time and VRAM sampler, audio-playback acknowledgements and rig reset hooks. No secrets in code or logs. A stop/kill switch must remain host-owned; default off until authorization.

**P2 — Real performance experiments, not implemented.** Pin llama.cpp source, build one concurrent 8 GB GPU stress matrix, and compare candidate cache/speculative-decoding policies. Track **worst stalls and correctness** rather than just average tokens/s. Proposed pass bars: no significant OBS drop increase; no longer p95 viewer response; no gameplay deadline regression; preserve private slot boundaries; at least one reproducible improvement beyond statistical noise. Numerical thresholds must be calibrated from actual measurements.

**P3 — Humanlike rehearsal, not implemented.** Run at least four reviewed paired clips per scenario from `StreamSocialTurnBenchmark`: questions, action commentary, owner interruptions, incidental noise and critical-game silence. Additionally rate listener impressions for timing/expressiveness without presenting subjective ratings as proof of humanity.

**P4 — Transfer/mastery and visual quality, not implemented.** Require reproducible held-out wins, stable latency on unseen situations, geometry/render consistency and real multiplayer testing before Forge promotes a new game agent or game-building recipe.

## 7. Evidence and scope

Directly checked repository paths: `star/stream_health_bridge.py`, `star/obs_stats_window.py`, `star/stream_load_governor.py`, `star/game_deadline_router.py`, `star/stream_social_turn_benchmark.py`, `star/stream_episode_journal.py`, and relevant tests. Focused test results were obtained on STAR's authorized Linux development host against the proposed source and test changes. GitHub PR #845 remains draft pending full repository CI and Windows/OBS integration. The repository is **public despite its former private-looking name**; never commit viewer identities, tokens, recordings or private files.

No local model was replaced or trained, no livestream was started, no game was played, and no GPU speedup was claimed. This release provides a verified infrastructure fix and a concrete, falsifiable plan for making faster and more natural behavior measurable.
