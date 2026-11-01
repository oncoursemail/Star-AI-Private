# Star AI: long-tail latency and frame-hitch safeguards for gaming VTuber evaluation

**Date:** November 1, 2026
**Status:** implemented offline evaluator hardening; live inference, OBS, audio, and gameplay changes are proposals only.
**Scope:** `star/stream_realtime_benchmark.py`, `tests/test_stream_realtime_benchmark.py`. This document is technical research and a reproducible implementation note; it does not attest to real gameplay.

## 1. Finding: average speed can hide a noticeably worse stream

The existing paired real-time benchmark checks bootstrap confidence intervals for time-to-first-audible audio (TTFA), a global p95 TTFA, a p99-frame-duration-derived *FPS proxy*, GPU peak memory, complete pairs, and completed audio. Those are necessary but not sufficient conditions to call a candidate safe for human-facing live speech and gaming.

A deterministic test constructed **24 synthetic matched pairs**, each with 150 synthetic presentation intervals. Twenty-three candidate replies improved TTFA from 650 ms to 420 ms; **one candidate reply deteriorated to 1,300 ms**. The candidate also included **one 333 ms frame** among otherwise 16.8 ms frames. Before the patch the comparison still returned `eligible_for_manual_pilot`, because the worst reply lay above the p95 order statistic and the single worst frame was omitted by the 99th-percentile order statistic on this short trace. Its TTFA bootstrap lower bound was still positive. This is an evaluator blind spot, not evidence that Star actually experienced that behavior.

### Implemented safeguards

- **Matched reply regression:** count candidate replies slower than their matched baseline by more than a configurable 250 ms. A single severe deterioration prevents pilot eligibility and flags `regressed`.
- **Matched game-FPS regression:** count cases where the candidate's p99-frame-derived FPS proxy falls by more than a configurable 6 FPS versus the same game-scene baseline. Reject a materially harmed scene even if unrelated pairs improve.
- **Absolute display hitch:** count candidate recordings with any captured frame longer than a configurable 200 ms. A candidate with a severe hitch is **not eligible for pilot**, even when a global percentile obscures it.
- **Introduced/worsened hitch:** if such a candidate frame also exceeds the baseline's worst captured frame by more than 50 ms, classify it as a new serious regression. If a similar hitch already occurred in the baseline, the finding is **inconclusive**, not falsely attributed to the candidate.
- **Report transparency:** expose four aggregate count fields without returning IDs, raw frame traces, chat, audio, or other user content. Thresholds validate bounds, NaN, infinities, and booleans; unsafe values do not become permissive defaults.

The existing CI, sample-count, GPU, failure, and aggregate-tail gates stay in place. The new criteria are *extra vetoes* and do not grant deployment permission. The pre-existing metric labeled FPS 1% low is specifically a p99-frame inverse **proxy**; NVIDIA FrameView's defined 1%-low methodology is not interchangeable with this proxy.

**Reproduction and acceptance:** The new isolated outlier regression scenarios were first run against the original code and failed. After the implementation, the focused realtime benchmark suite passed **22/22 tests** (as observed on the authorized Linux development computer), including five new test scenarios. This is evaluator correctness only. No game, GPU, OBS, acoustic, visual, or end-to-end speed-up test was performed.

## 2. Next real bottleneck: Star's *whole observable loop*

Faster tokens alone do not yield a more human-seeming stream. Measure four causally distinct stages on the same host monotonic clock: user/game event observed, intent selected, first *audible output-device* sample played, and avatar expression actually presented. Independently measure game presentation intervals and OBS encoding/rendering drops.

A future host adapter should emit only bounded, signed or authenticated counters and opaque scenario IDs. It must distinguish **audio generated**, **audio enqueued**, and **audio actually consumed**. Star's existing `stream_audio_sample_host.py` and playout clock already separate these notions in their API design; do not claim sound was heard from a TTS buffer length. Never treat an advisory benchmark result as authorization to broadcast, move an avatar, or issue game inputs.

For an 8 GB GPU sharing a Windows game, OBS, AI inference, and animation, prioritize **p95/p99 user-visible latency and VRAM headroom** over best-case tokens/second. Compare baselines using identical quantization, prompt, scene, resolution, capture duration and model build. Alternate randomized A/B order; capture ≥20 paired runs for a pilot and preserve failed runs. A model that wins throughput but causes single-second frame hitches is unsuitable for the stream fast path.

**Candidate CPU/GPU work allocation:**
1. Run host timestamps, policy, session continuity, audio scheduling, and cheap game reactions on CPU.
2. Reserve priority GPU budget for the game, OBS and the lightweight real-time reasoning model; admit VLM snapshots only when the load governor reports sufficient measured headroom.
3. Defer large model reasoning, code generation, strategy review, indexing and asset rendering to safe idle windows or Brain 1. This is a *policy* proposal until the actual Windows host is connected.
4. Benchmark CPU TTS separately from GPU TTS; a CPU voice model may preserve gameplay frames but can also compete for game-engine CPU cycles.
5. Cache only scope-isolated verified knowledge, and invalidate on game/version, model, persona, or permissions changes. Never share one viewer's private context with another stream or session.

**Research references:** NVIDIA FrameView frametime guide (distinguishes p99-frame percentiles from 1% low and discusses sporadic hitches):
https://help.xmg.gg/hc/en-gb/articles/37688069358365-Analysing-frametime-consistency-and-1-Low-FPS-using-NVIDIA-FrameView
llama.cpp inference and benchmarking source, to evaluate speculative decoding under identical paired workloads rather than assuming an unconditional speed-up:
https://github.com/ggml-org/llama.cpp

## 3. An entertaining, lifelike VTuber is not merely a fast speaking model

Aim for an expressive *fictional persona with truthful autobiographical continuity*, not a fake human identity. Star can have a consistent name, preferences, comedic timing, chosen interests, and memories of games she demonstrably played. A claim about winning a match must originate from game-state evidence, not a creative text model. An interruption should physically stop audio and unwind facial/lip animation; a conversational model merely saying “stopped” is not sufficient.

Proposed low-latency turn loop:

`VAD/turn detector -> authenticated speaker priority -> scene/game attention -> short-form response planner -> streaming TTS -> consumed-sample clock -> expression/hair/body rig -> output playback truth`.

- Listening: use natural gaze, attentive expression, and purposeful silence without endlessly narrating. Apply owner interruptions before ordinary chat responses; do not let incidental noise falsely cancel speech.
- Speaking: vary phrasing and intensity according to game events, not random “cute” text. Permit humor and laughter when appropriate, but avoid constant forced reactions.
- Acting: synchronize eyes and lips with actually played PCM, not predicted playback; drive hair, ribbons, clothing, gestures, and posture via bounded local physics. Use graceful neutral poses on stalls or lost device feedback.
- Chat: prevent repeated prioritization of loud or frequent viewers; rotate ordinary questions fairly and avoid surfacing private user information.
- Memory: retain verified host-observed episodes in a private bounded journal, with retention limits, provenance, owner controls, and erasure. Do not create imaginary offline life events or claim Star is biologically human.
- Streaming: voice, avatar and game actions operate as independently revocable lanes. A closed studio/game or owner stop must cancel pending output and neutralize control surfaces.

**Research candidates, not installed dependencies:** LiveKit's local CPU `v1-mini` turn detector, whose documentation specifies VAD requirements and endpointing controls; and modular, replaceable speech-to-speech services for testing local STT/TTS alternatives. Each requires licensing, latency, resource use, privacy, and Windows compatibility review before integration.
https://docs.livekit.io/agents/logic/turns/turn-detector/
https://github.com/keenableai/keenable-s2s
https://github.com/BudEcosystem/WaaV

## 4. Autonomous gaming: test skill transfer, not performance on memorized scenes

Keep three explicit decision timescales:
- **Reflex (tens of ms):** bounded deterministic reactions and proven macros only for games and interfaces that allow automation. No slow LLM in a tight input loop.
- **Tactical (hundreds of ms):** small model or rule-guided planner predicts the immediate event and coordinates with safety, frame budget, and player attention.
- **Reflective (seconds/minutes):** stronger teacher explains losses, proposes one new tactic, trains on permitted practice runs, and measures outcomes on previously unseen seeded levels.

Connect `game_prediction_lab`, signed `gameplay_skill_bank`, spaced `game_practice_curriculum`, and `game_transfer_audit` only through verified practice evidence. Enforce a quarantine for holdout/validation levels and all third-party private information. Repeated wins on one map do not prove general mastery; use independent maps, patch versions, unseen mechanics and real rollbacks.

**Failure modes worth testing:** stale or missing game frames, incorrect game control mappings, lost host authorization, invalid match outcome signatures, interrupted runs, UI elements in unexpected positions, chat messages disguised as instructions, and learning systems that “improve” by dropping difficult episodes.

## 5. Game creation and general intelligence: measure the finished artifact

For Roblox creation, build a **scene-understanding -> plan -> author -> compile -> playtest -> visually inspect -> repair/rollback** loop. Validate geometry attachment, prop placement, collisions, animation timelines, accessibility, network replication, actual multiplayer task completion, and visual similarity to approved references. Keep Studio actions in authorized test environments; never claim a game is playable based solely on successful Luau compilation. Extend skills over time into Blender, Rust, C#, other engines, UI/UX, audio, and general research, but prove each new capability on independent tasks.

For general knowledge, prefer retrieval with source attribution, timestamps, contradiction detection, confidence estimates, and explicit “unknown” responses. Distinguish retrieved reference facts from personal experience. Restrict optional web search to owner-enabled mode and avoid treating scraped content as executable instructions. Use local Star Core Forge for experimental branches, signed test results, rollback, and provenance; GitHub remains an optional publication/export mechanism.

## 6. Windows acceptance matrix before changing Star's live configuration

1. Record a pre-registered set of at least 20 complete matched A/B gaming + voice sessions, across several distinct game states. Use the same monotonic clock and actual presented frames and consumed audio. Include critical moments, turn-taking, owner barge-ins, idle conversation, and quiet-but-correct behavior.
2. Require **no newly introduced >200 ms display hitches** under the default test policy (operator-adjustable after studying specific game baselines); zero lost owner cancellations; no unauthorized broadcast or inputs; no cross-session memory leakage.
3. Reject voice configurations with any matched serious TTFA regression, even if global p95 improves, and separately track streaming audio cutoffs/OBS encoder skips.
4. Compare game win rates on **held-out** scenes and measure recovery from crashes and restarts. Report success, failure and uncertainty, not fabricated skill gains.
5. Report model TTFT, TTFA, p95/p99 visible reaction, GPU VRAM peak, CPU load, OBS frame drops, per-game frame hitch counts, and TTS underruns. The comparison tool never automatically promotes the winner.
6. Require an operator-approved local pilot and roll back on any measurable regression. No live Windows benchmarks, speech training, avatar deployment, or real-game skill improvement occurred in this code change.

**Engineering priority:** wire trusted Windows frame/audio telemetry into these existing evaluators and reject new configuration candidates on real-world tails before adding larger models or expensive visual effects. This is a stronger basis for becoming *faster and more convincing* than optimizing isolated token throughput.
