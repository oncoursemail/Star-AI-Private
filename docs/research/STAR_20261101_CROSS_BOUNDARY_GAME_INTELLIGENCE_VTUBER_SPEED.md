# STAR — Live-game cognition bridge, humanlike VTuber behavior and measurable speed
**Research and engineering:** November 1, 2026. **Status:** offline component and tests; no Windows game/OBS/device deployment.

## Concrete improvement in this revision

STAR already has a measured fast-model deadline router (star/game_deadline_router.py) and a separate owner-gated symbolic action controller (star/game_action_gate.py). Neither alone ties a model's **pre-inference** recommendation to its **post-inference** proposal when the game changes while the model is thinking.

This revision adds star/game_realtime_loop.py with RealtimeGameLoop and GameThinkLease, plus tests/test_game_realtime_loop.py. The new module composes the existing controllers into a two-phase host-only protocol; it loads no model, uses no OS keys, reads no screen, sends no stream and authorizes no gameplay.

1. Owner approves an exact game/version/episode and 1–32 symbolic action IDs. The coordinator derives a session-bound SHA-256 scope key for the router.
2. Trusted host records completed **measured** fast-model durations and timeouts, not self-reported/model-invented timings. Cold or stale profiles are not assumed fast.
3. Trusted host submits capture sequence/time, evidence SHA-256, calibrated confidence, active focus, and independently observed game/audio/OBS telemetry.
4. The coordinator checks that the **measured p95** fast route can finish within the frame deadline. A successful offer yields one identity-bound, short-lived advisory lease. The host alone decides if its model has permission to execute.
5. A newer host-verified scene revokes the old lease. Another expensive model inference is not suggested until the host confirms the prior worker was **actually stopped**; ignoring a stale result is not proof of cancellation.
6. When the model completes, the host passes the **same lease and same trusted frame object**, its untrusted symbolic action hint, and new telemetry. The coordinator consumes the lease, rechecks time and pressure, then offers the hint to the existing action gate.
7. The host still independently checks app/process ownership, current focus, game rules and user permission at dispatch, and must present the **actual issued permit** to claim it. The host confirms key-up before the action slot is reusable. Stopping the session never waives this obligation.

The 350 ms scene age and 40 ms dispatch reserve currently inherited from/compatible with the existing controllers are policy defaults, not proven optimal for every game. A model that completes too late is skipped even if its action recommendation was reasonable at capture. This is a systems-integration upgrade; it does not claim model intelligence gains, real keypresses or faster inference.

## Primary research and recommended design decisions

**Realtime interactive learning:** RealtimeBench/TORSI (published October 14, 2026) tests 180 tasks across six continuously evolving games. It demonstrates why a more capable but slower model may perform worse when the world does not pause. Separate a fast reactive student from an offline teacher that diagnoses failures and writes *tested* corrections between attempts. Adopt only if fresh unseen holdout scores improve. https://arxiv.org/abs/2610.20665

**Measuring speed instead of guessing:** llama.cpp SPEED-Bench reports client latency, decode/prefill throughput and speculative-token acceptance, and supports plain-vs-speculative paired experiments. Benchmark identical prompts, model, quantization, generation settings and real device load; restart servers when changing decoding modes. A throughput increase without stable p95/p99 first-audible and action deadlines is not a win. https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md

**8 GB GPU scheduling:** gaming frame delivery, OBS encoder and audible speech get priority. Offload large research, Blender rendering, training, heavy video generation, large-scale indexing, and teacher study to idle/other computers or off-stream windows. Sample real GPU VRAM, host CPU, game FPS, OBS render+encode frame-loss counters and audible TTS queue depth. Do not attempt to simultaneously load multiple large models merely because theoretical tokens/sec looks attractive.

**Selective Rust acceleration:** profile PCM buffers, frame transport, inference scheduler overhead and animation loops; only consider Rust+PyO3 for hot paths whose verified CPU/latency wins justify FFI cost. Retain a Python oracle and semantic tests. A broad Rust rewrite does not improve underlying neural network reasoning by itself. https://github.com/PyO3/pyo3

**More natural voice:** LiveKit's self-hosted v1-mini audio turn detector can run locally on CPU, using speech acoustics beyond VAD to distinguish thinking pauses from true turn ends. Verify SDK version, CPU cost, voice/game noise and false interruptions under streaming load. Do not silently use cloud-only features in STAR's offline path. https://docs.livekit.io/agents/logic/turns/turn-detector/

**Low-GPU speech candidates:** Kyutai Pocket TTS published English 18M/7M/2M variants on October 20 and v4.0.1 corrections October 21, 2026. Compare real first audible chunk, pronunciation, laughter expressiveness, sustained CPU use, interruption stopping and naturalness against STAR's current voice; upstream model-speed numbers are not measurements on STAR hardware. https://github.com/kyutai-labs/pocket-tts/releases

**Truthful avatar expressiveness:** VTube Studio's authenticated local WebSocket plugin API can inject facial parameter data, but plugin authorization grants significant control and should be narrowly scoped. Preserve Star's final playback-device clock to lip-sync guard, stop mouth movement on canceled/stalled audio, and respect reduced motion. An AI VTuber should express remembered **real** gaming moments and stable personal interests; it should not invent a human personal history or simulated victories. https://github.com/DenchiSoft/VTubeStudio

**Better games and general knowledge:** Roblox's October 1 OpenGameEval evaluates stateful in-engine editing, actual inspection and executable playtests; Roblox Studio supports simulated clients, VirtualInput and StudioTestService. Combine true scene inspection, structural checks, multiplayer conditions and screenshots/video checks before approving a game. SkillLearnBench and SkillScriptBench suggest testing new/revised skills on fresh holdouts and measuring regressions. Sources: https://arxiv.org/abs/2610.02563 ; https://create.roblox.com/docs/studio/testing-modes ; https://github.com/cxcscmu/SkillLearnBench ; https://arxiv.org/abs/2610.04008 .

## Measurable Windows acceptance plan

Real intelligence is winning **unseen** games more consistently, not merely producing longer reasoning. STAR Core Forge should freeze at least 20 independently approved holdout episodes per game, compare baseline/candidate on identical seeds, stratify mechanical difficulties, track signed outcomes, and reject failures masked by aggregate scores. Keep training/validation/holdout separate, and avoid overfitting through repeated reruns.

Real speed is measured at boundaries: game frame captured → model admitted → model finished → host permit claimed → physical key state changed → next game state observed, plus OBS rendered/encoded dropped frames, game frame-time p95/p99, CPU/GPU pressure and first/last audible speech samples. Sample both warm and cold inference configurations while a representative game and OBS session run. Report timeouts and canceled workers, never just successful fast calls.

Real streaming naturalness is an independently rated ability to respond to viewers without talking over them, stop voice on actual owner interruption, leave purposeful silence during hard gameplay, align mouth/eyes/gestures with audible audio, remember actual experiences without hallucination, and stay entertaining without repetitive monologues. Test microphone/noise, Twitch delayed messages, speaker/device output interruptions and multi-avatar interaction.

Run a 10–30-minute owner-authorized Windows rehearsal before public deployment: check real app focus, read-only OBS GetStats/GetStreamStatus, GPU VRAM budget and host-clock continuity; do not start a livestream or a real online game automatically. Keep features OFF by default and continue to require the trusted host's explicit scope/permission checks.

## Verification boundaries and next build

The new deterministic tests cover owner authorization, cold model profiles, one-use lease identity, copied/replayed hints, newer scene preemption, **confirmed old-worker shutdown** before another model suggestion, expiration, hardware pressure changes after a model returns, OBS-state inconsistency, symbolic action gating, host focus claim, real key-up confirmation, clock rollback, concurrent duplicate frames and session restart quarantine.

These are **synthetic checks only**. No neural model, game engine, voice model, OBS broadcast, Twitch account, GPU profiler or Windows input adapter was exercised. The next development step is connecting this bridge to an owner-approved Windows game-capture/OBS/physical-input witness, instrumenting full-path latency and evaluating real unseen task outcomes. Avoid any merge to production until GitHub CI and host-rehearsal gates are satisfied.

STAR's private experiment/rollback/benchmark evidence belongs in Star Core Forge. GitHub is optional code review and export. The GitHub project repository is public; never commit raw chat, viewer identities, recordings, model tokens, passwords or API keys.
