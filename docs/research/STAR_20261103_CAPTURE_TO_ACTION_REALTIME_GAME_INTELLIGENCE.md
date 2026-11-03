# STAR: Real-time capture-to-action intelligence and VTuber research
Date: 2026-11-03. Research and an offline verification tool, **not** a claim of a live game or measured faster inference.

## Newly verified research: the real-time measurement trap

The GameScaling team published a **November 1, 2026 correction** to its real-time ViZDoom numbers: GameScaling-9B-S3 went from **16.4 to 11.5** and 27B-S3 went from **13.2 to 8.5**. The old protocol paused the environment and compensated only model prefill and decoding. The corrected protocol keeps the world progressing and includes capture, transfer, image preprocessing, action processing and recording. The results are **not STAR's scores**. Source: https://gamescaling.github.io/ ; code: https://github.com/THUSI-Lab/GameScaling ; paper arXiv:2610.28698.

Research implication: measuring tokens/sec or even reasoning-to-action time can systematically overestimate a gaming AI. STAR must measure full screen-capture-to-key-acknowledgment time plus world progress during every stage, on independent clocks.

The study trained Qwen3.5-based game agents on 80 games, compared single-game against mixed-game experience, and tested 0.8B–27B models on known/related/unseen environments. Diverse data improved transfer to related unseen 3D worlds; distant 2D/2.5D transfer was weaker. Bigger models did not automatically produce stronger real-time performance. Available checkpoint sizes in BF16 are approximately 2.2 GB for 0.8B, 5.4 GB for 2B, 18.8 GB for 9B and 54.7 GB for 27B. That makes the 9B BF16 checkpoint inappropriate for an 8 GB-VRAM-only deployment; evaluate smaller candidates separately. The published game footage and training gameplay corpus are not available for commercial reuse merely because the released model and inference code are Apache-2.0.

## Engineering implemented in this branch

New offline module: star/game_capture_to_action_benchmark.py

- Bounded host metrics record screenshot capture start/end, transfer done, preprocessing done, inference done, OS input acknowledgment and the original scene deadline.
- Record **four independent engine world-frame samples**: capture start, preprocessing completion, inference completion and input acknowledgement. Validate progress **per interval** so a paused screenshot step cannot be hidden by faster simulation later.
- Assess baseline/candidate paired real-time attempts with consistent initial-state SHA, game version, environment FPS, deadlines and independent episode IDs. Detect duplicate trial variants or recycled episodes.
- Compare p95 complete input-response latency, p95 per-stage latencies, minimum 20 pairs, bootstrap confidence on paired gains, newly lost victories, game p99 frame regressions and OBS dropped frames. Missing/unverified or non-live observations cannot qualify.
- Produce no screenshots, speech, PII, player names, raw actions or private content in its report. Max 2MB and 1000 input records. Strict JSONL schema and duplicate field rejection.
- **No promotion**: even a strong candidate gets only a manual-pilot recommendation. This analyzer neither authenticates the observation host nor grants game control or streaming permission.

Run an authorized host-generated dataset using: python -m star.game_capture_to_action_benchmark /path/to/game-timings.jsonl . See the dataclass CaptureToActionTrial for the required fields. Tests are in tests/test_game_capture_to_action_benchmark.py, including frozen capture, frozen dispatch, new failures, QoS regression, replay, invalid fields and no input acknowledgement.

The new analyzer complements STAR's pre-existing game_live_clock_benchmark.py. It does not replace the source-authenticated game_telemetry_source_bridge.py or the verified game_state_transition_witness.py. Those establish continuity of host-signed engine data; this offline analyzer profiles timing from an independently secured host. Neither alone proves a model achieved a live victory.

## Intelligence, game creation and VTuber priorities

1. **Two-rate cognition:** a bounded subsecond gameplay controller chooses short actions, while a deliberative model works outside the time-critical action path on plans, retrospective error analysis and knowledge retrieval. Never block input deadlines on elaborate prose or voice. Prefer a measured 0.8B/2B gaming specialist over unmeasured 9B offload on an 8GB GPU. Actually benchmark a model and its vision pipeline before deployment.
2. **Licensed diverse game practice:** build an automatic difficulty curriculum in user-owned games; retain independently observed successes, negative examples and a withheld evaluation set. Distinguish within-game progress, related-game transfer and distant 2D/3D transfer. Counterfactual self-play and model-generated success claims are *hypotheses*, not verified outcomes.
3. **Correct memory:** separate gameplay facts, episode summaries, social context, general knowledge and unverifiable narration. Use source identity and session IDs, expiry and explicit uncertainty. Viewer dialogue must not be allowed to forge engine states.
4. **Roblox development:** inspect affected Studio objects before editing, generate multiple candidates, run tests in Studio/StudioTestService for client/server and multiplayer scenarios, verify repairs through actual play. Roblox OpenGameEval tested 84 curated tasks with executable checks, finding that relevant object inspection correlated with better success. Sources: https://github.com/Roblox/open-game-eval ; https://create.roblox.com/docs/reference/engine/classes/StudioTestService ; https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643 .
5. **Local inference:** benchmark llama.cpp stable prefix reuse via cache_prompt, controlled speculative decoding, queueing and KV-cache residency while gaming. Measure cold/hot p95 complete actions, VRAM/RAM, game FPS, OBS frames and correct game outcomes. Cache reuse can change numerical behavior between batch regimes: accuracy acceptance tests are mandatory. Source: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md .
6. **Natural stream conversation:** Microsoft Research Proact-VL addresses *when* a gaming companion should comment, not just what it should say. Build a low-cost timing policy with silence, event importance, cooldowns and permission to interrupt. Separate gameplay controls from commentary. LiveKit documents audio turn detection, including a CPU-oriented mini version, and adaptive interruption behavior. Sources: https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/ ; https://docs.livekit.io/agents/logic/turns/turn-detector/ .
7. **Voice/avatar on an 8GB GPU:** Kyutai Pocket TTS added English CPU model sizes 18.2M, 6.9M, 1.9M in October 2026. Compare these against STAR's actual voice configuration on first audible chunk, emotion stability, voice quality, lip sync and CPU contention under gameplay load. Published claims about up to 25x real-time are not benchmarks from STAR's hardware. Source: https://github.com/kyutai-labs/pocket-tts .
8. **Expressive digital life:** support Star's recognizable interests, Astro/Amber interactions, ongoing art/gaming projects, consistent personality, social memory grounded in *actual* shared activities, and thoughtful viewer interactions. An AI VTuber can be expressive and humanlike in performance while remaining transparent about being AI; do not fabricate victories, friendships or consciousness. Moderate chat and keep private identities/DMs out of stream by default.

## Next acceptance experiment

**A. Nonbroadcast owner-owned game:** connect signed, independent engine telemetry to a controlled Windows Studio or custom-game test harness; add timestamps at every actual capture/transfer/preprocessing/inference/ack stage using one monotonic clock, plus world frame readings. Keep model workers away from the evidence signing key.

**B. Independent keyboard safety:** prove released keys even when input workers time out/crash; require correct foreground game, operator emergency stop and owner-approved sessions. Do not test injection in third-party competitive games or start a public stream without approval.

**C. Paired real-time evidence:** choose and freeze 20+ scenario pairs before evaluation, then benchmark capture-to-action delays, outcome score and missed deadlines with OBS under identical hardware conditions. Include intentional freeze/adversarial trials.

**D. VTuber rehearsal:** capture local OBS video, first audible PCM and avatar timing; human-review useful vs unnecessary speech, natural turn-taking, truthful commentary, interruptions, and consistent character behavior. Enforce privacy and moderation checks. Keep broadcast OFF until verified.

**Scope delivered:** reproducible source code, adversarial tests, a fresh research finding and acceptance criteria. **Not delivered:** a new trained policy, actual Windows live-game success, verified speedup, voice/avatar demonstration, or evidence of human consciousness.
