# Star AI: paired-harm isolation, real-time gaming intelligence and credible VTuber quality
**Research and engineering update:** 2026-11-02. **Scope:** tested offline evaluation correction plus a prioritized, *unimplemented* research/engineering roadmap. **Base:** GitHub PR #908. New features remain OFF unless a trusted owner-controlled host enables them.

## Reproduced defect and implemented correction

`star/stream_quality.py` evaluates matched synthetic/host-reviewed baseline-versus-candidate opportunities before considering a faster VTuber configuration for **independent owner review**. Existing aggregate gates protected totals for missed viewer replies, unexpected speech, speech overlap and game frame stalls. However, unchanged global totals could conceal a newly harmed moment.

Three independent red tests demonstrated that the previous comparator returned `candidate_for_independent_review` despite these regressions:

1. **Unexpected speech relocation:** both routes produce one unsolicited utterance, but the candidate speaks in a *different* moment that should have stayed silent.
2. **Viewer talk-over relocation:** both routes overlap for 100 ms overall, but the candidate interrupts a previously uninterrupted moment.
3. **Gameplay stall relocation:** both routes contain one >50 ms frame stall, but the candidate stalls a different game moment.
4. A fourth green test confirms that a *lower* aggregate overlap of 20 ms versus 200 ms still cannot erase a new talk-over incident on an independently matched case.

**Correction:** after the aggregate checks, compare the *same exact* cases for newly introduced unsolicited speech, newly significant talk-over (above a conservative max(10 ms, 10%) jitter deadband), and newly crossed >50 ms game-stall threshold. Any such event adds a reason for `do_not_promote`; per-harm anonymous counts appear in the offline review report. All existing speed, grounding and preservation checks remain in force.

This change **does not** alter the live microphone, OBS, TTS or game control paths; it cannot certify host measurements, authorize broadcasting, issue game input, or prove humanlike conversational ability.

### Reproducible check

- `PYTHONPATH=. /home/star/.cache/star-verification-venv/bin/pytest tests/test_stream_quality.py -q` (or `python3 -m unittest discover -s tests -p test_stream_quality.py`)
- The three relocation tests failed **before** implementation, each previously reporting `candidate_for_independent_review`; after the correction, all focused tests pass.
- Required pre-merge gates: full repository regression suite, Ruff lint, `python3 -m compileall -q star`, `git diff --check`, GitHub Actions, and a nonbroadcast Windows A/B rehearsal with real host-aligned audio/video evidence.

## Architecture proposal: make Star smarter *without* damaging real-time experiences

Star has separate components for signed practice outcomes (`gameplay_skill_bank`), prospective probability prediction (`game_prediction_lab`), a curated practice curriculum (`game_learning_ladder`), independently sealed multi-game holdouts (`game_transfer_eval`), real-time game inference leases (`game_realtime_loop`), host-authorized game actions (`game_action_gate`), and streaming resource admission (`stream_brain_governor`). **Do not duplicate these components or silently promote their advisory outcomes to live capabilities.**

**Directly relevant experimental evidence:** the October 14, 2026 RealtimeBench/TORSI paper evaluates 180 continuously running tasks across six games. Its teacher-in-paused-games/student-in-live-games approach raised the authors' fast student's mean progress from 13.51 to 24.19 after two learning rounds. This is **not** Star's performance and is not evidence that blindly adding agent loops makes a model smarter. The proposed benefit depends on controlled evaluation, low latency and withholding test cases. Source: https://arxiv.org/abs/2610.20665

**Fast/slow split:** the live game loop should receive a compact, timestamped observation plus an approved symbolic action menu; it must choose under a strict capture-to-act deadline or abstain. A distinct offline coach can use larger models, simulation playback and retrieval to diagnose failures and propose strategies. Only prospectively signed practice outcomes may update the practice store; independent withheld evaluation seeds and keys remain unreadable to the learning agent. Model weight changes require separately approved controlled training and paired held-out trials.

**Memory and general knowledge:** provide project-scoped, provenance-tagged notes with source date, confidence, expiration and *specific on-air publication approval*. Separate autobiographical **verified session events** from owner-provided fictional character lore and unverified model inferences. Build game-specific procedural skill cards with versioned action maps and prerequisites. Retrieval must never become a backdoor for viewer instructions to run tools.

**CPU-first voice option:** Kyutai's Pocket TTS repository now documents three small English October 2026 models of approximately 18.2M, 6.9M and 1.9M parameters, standalone Windows x86 binaries and streaming audio. Published speed measurements are hardware/voice dependent; do not substitute the fastest tiny voice without subjective intelligibility/prosody testing and exact first-playout timing on the Windows host. Source: https://github.com/kyutai-labs/pocket-tts

**Speed and reliability:** profile *completed correct outputs*, p50/p95 first visible token, first speakable phrase, first audible PCM, action decision age, GPU VRAM, game p95 frame time, OBS dropped/render-skipped frames and quality of the human-reviewed response. Try caching stable prompts and read-only retrieval prefetch, and compare small-game/large-coach model routing under identical synthetic **mixed** workloads. Speculative decoding and longer contexts are experiments, not assumed wins; they may consume scarce VRAM or reduce throughput on specific hardware. Require A/B randomization, unchanged game scene and tests on at least two independent game situations.

**Safety and integrity:** keep worker stop acknowledgment, key-up watchdog, session-scoped/scene-bound action leases, host-measured timestamps, immutable evaluation receipts, hidden holdouts, viewer text isolation and automatic low-VRAM degradation. Leave novel features opt-in. Do not bypass anti-cheat or automate online multiplayer in violation of game rules; practice in private, approved environments.

## VTuber systems: humanlike delivery while clearly AI

- **Speech:** authenticated host VAD, actual echo cancellation, conservative end-of-turn decisions, quick but safe owner interruption, expressive local TTS, pauses and emotionally appropriate prosody. Evaluate false cut-offs and first audible response, not only first model token.
- **Avatar:** align lip and expression cues to the **consumed audio device cursor**, not queued/generated TTS. VTube Studio custom parameters can represent blink, eye focus, smile, body movement and cat/dog modes. Real physics, eye contact, idle gestures and natural reaction timing belong in the tested renderer integration. Never imply the model has biological perception or lived human experiences.
- **Gameplay and spontaneity:** speak less during combat or precision jumps; spontaneous commentary should arise from verified objective outcomes, stage context and genuine mistakes, not random canned emotional events. An authentic character can have enduring interests, evolving preferences and bounded, consistent personal history without misrepresenting herself as a human.
- **Social:** track chat turn fairness, moderation, recognition of recurring permitted topics, permission for public names, graceful admissions of uncertainty and game-to-chat context switching. Never claim a stream was live if only in rehearsal.
- **Friends and companions:** Star, Astro and Amber can share a host-orchestrated stage/scene with clear speaking priority, audio identity and separate persona states. Simulate character relationships as narrative expression, not evidence of human consciousness.

### Credible metrics and rehearsal acceptance

A useful A/B release must **not** claim speed improvement from fewer responses, host timestamps alone or newly damaged viewer interactions. Pre-register case IDs. Include all matched conversational opportunities, end-to-end audio timing, per-case talk-over and silence, game frame stalls, independent grounding judgments, decoded video lipsync and actual OBS counter windows. **Any newly harmed matched case should veto the candidate regardless of equal or lower aggregates.** Reviewer attestation must be external to the candidate model.

On the connected Windows **Main** host, a read-only NVIDIA query on 2026-11-02 reported **RTX 3060 Ti, 8192 MiB total, 7587 MiB used, 438 MiB free, 18% utilization**. This is one snapshot, not a game/OBS measurement; a stream-capable setup with GPU inference must first free or redistribute substantial VRAM and verify sustained headroom. No processes were stopped and no broadcast was started.

## Game creation: use executable evidence, not visually plausible guesses

Roblox OpenGameEval evaluates agents inside stateful Roblox Studio, with executable scene and simulated-play checks rather than code-only assertions. Its 2026 benchmark has **84 curated tasks** and reports a correlation between inspecting relevant objects before editing and higher task success. Star should therefore: **inspect existing hierarchy/assets -> plan semantic scene change -> generate 4-8 constrained alternatives -> lint/typecheck Luau -> automated Studio playtest -> compare observed scene geometry/collisions -> visual review -> repair or rollback**. Report actual tested passes and failures, not self-rated aesthetics. Extend this pattern later to Blender rigging, texture seams, character grip, VFX timing, multiplayer physics and other engines.

## New feature candidates, ranked by expected practical value

| Priority | Candidate | Acceptance evidence; do not call it implemented |
| --- | --- | --- |
| P0 | Windows private integrated game + voice + VTube Studio + OBS **nonbroadcast** rehearsal | Named real game process and stable GPU identity, separately measured audio/playout, FPS, missing-frame and avatar proof |
| P0 | Two-speed gaming loop with stale-action abstention and coach after play | Lower p95 valid action age, unchanged game FPS, verified wins on unseen seeds |
| P0 | Memory/CPU/GPU allocation profiles for 8 GiB VRAM | No new gaming or encoding stutters; no benchmark-only repeat-prompt speed claims |
| P1 | Natural expressive turn-taking + silence | Human-reviewed balanced false-cutoff/latency, no new matched-case talk-over |
| P1 | Multi-game practice/teacher/holdout transfer | Matched seeded trials across distinct games, independent signer/hidden evaluation, no leak |
| P1 | Studio build/run/repair loop and visual validators | Executable play-mode game tests, collisions/anchors, screenshots and human review |
| P2 | Curated/general knowledge with public visibility permissions | Citation correctness, freshness, prompt-injection tests, strict broadcast allowlist |
| P2 | Avatar expression library and companion stage | Recorded audible-frame/face alignment, operator review, accessibility/reduced motion |
| P2 | Optional Rust real-time capture/IPC hot paths | Profiling demonstrates material CPU/latency improvements; preserve proven Python policy logic |

## Primary research checked 2026-11-02

1. llama.cpp SPEED-Bench, throughput/latency/draft acceptance measurement: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md
2. llama.cpp field report in which speculative decoding **reduced** throughput on some configurations (not proof of a current universal defect): https://github.com/ggml-org/llama.cpp/issues/10664
3. Roblox OpenGameEval, executable Studio tests and benchmark: https://github.com/Roblox/open-game-eval and paper https://arxiv.org/abs/2610.02563 (published 2026-10-01).
4. VTube Studio API and plugin custom parameters, authentication and model mappings: https://github.com/DenchiSoft/VTubeStudio and https://github.com/DenchiSoft/VTubeStudio/wiki/Plugins
5. RealtimeBench / two-timescale gaming under a live clock (2026-10-14): https://arxiv.org/abs/2610.20665
6. Kyutai CPU-oriented Pocket TTS with October 2026 smaller English models: https://github.com/kyutai-labs/pocket-tts
7. STAR internal source modules named above and the existing `tests/test_stream_quality.py`; regression verified locally on 2026-11-02.

**Boundary:** these references motivate engineering proposals. No new model weights, benchmarked live-game wins, Windows OBS session, actual TTS improvements, or demonstrated increase in general intelligence resulted from this offline evaluation change.
