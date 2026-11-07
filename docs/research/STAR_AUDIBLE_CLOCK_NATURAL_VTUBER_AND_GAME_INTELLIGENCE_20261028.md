# Star AI: Audible-Clock Streaming, Game Mastery and Intelligence Research
**Research/implementation date:** 2026-10-28
**Scope:** Offline-first, opt-in, Windows/Roblox gaming + conversational VTuber.
**Status:** A playback-clock synchronization primitive and offline regression tests are implemented here. Other work below is a *proposed roadmap*, not deployed functionality.

## 1. The key gap: generated speech is not heard speech

Star already has `StarStage` for verified reactions, moderated input, owner interruption, expressive animation and post-playback acknowledgements. The missing synchronization seam was an **audio-device playout position**.

A model could write a line at T0, TTS could synthesize it at T1, the audio could be buffered at T2, and the sound could become audible at T3. Coordinating animation from T0/T1/T2 rather than T3 yields out-of-sync smiles, blinks, lip movement and early reactions. A game FPS drop can stretch T2–T3 arbitrarily.

**New `star/stream_playout_clock.py`: `StarPlayoutClock`**

- A host must opt in explicitly; the class has no device/network/streaming access.
- Only a live, host-acknowledged *audible* `StagePlan` can be armed.
- The host supplies **output-device** playout cursors (monotonic timestamp, elapsed seconds, play/pause). A TTS-generated timestamp is *not accepted as equivalent evidence*.
- The host gets interpolated `MotionFrame` suggestions from the current heard-audio position, not from estimated future words.
- Every issued frame is short-lived. The host checks `current(frame)` **immediately before dispatch**; a newer tick, cursor, stopped stage, or interruption invalidates old animation batches.
- Audio pauses, stale samples and a stalled cursor produce no motion. The renderer must neutralize the rig if `sample()` returns `None`.
- Backward, nonfinite, future, overly advanced and wrong-plan cursors fail closed; an old plan cannot revoke a new plan.
- There are no images, chat transcripts, audio buffers, personal data or secrets in metrics.
- Stop and disable return neutral rig state but do NOT themselves mute a sound device. That is the authorized host's responsibility.

### Integration contract (the missing physical adapter)
```python
# PSEUDOCODE ONLY: the actual Windows audio adapter is NOT implemented.
stage.enable(owner_approved=True)
clock.enable(owner_approved=True)
plan = stage.prepare(now=monotonic_now, telemetry=trusted_hardware_telemetry)
# synthesize and queue voice; do not animate yet
stage.queue_audio(plan, now=monotonic_now)
# only after playback device reports first audible sample:
stage.acknowledge_audible(plan, now=monotonic_now)
clock.arm(plan, duration_s=utterance_duration, audio_levels=heard_audio_envelope)
# per output-device callback:
clock.observe_playhead(plan, position_s=played_sample_count / sample_rate,
                       sampled_at=host_monotonic_time, playing=physical_playback_active)
# per render update:
frame = clock.sample(plan)
if frame is not None and clock.current(frame):
    send_rig_params(frame.motion)  # authorized host, never viewer text
else:
    reset_to_neutral()             # do not freeze an opened mouth
# on stop, stream close, or owner interrupt: stop audio + reset stage and clock.
```

**Important:** The example assumes a real device callback. The new code does not itself prove output was heard. For Windows the callback needs to use acknowledged output samples (or equivalent authoritative local audio API), on the same monotonic clock domain. The cursor must not come from a model prediction. Actual acoustic speaker verification would require a separate consented loopback approach.

**Quality acceptance:** In an audio pause the avatar should not keep talking silently; no smile should appear before sound; a cancelled sentence should not finish its gesture; a lag spike should not move animation ahead of what viewers hear. The module's 20 offline tests cover these cases at the state-machine level.

## 2. How to make Star feel like a natural gaming VTuber

The aim is a coherent **virtual personality** and performer, not fabricated human identity.

**Attention and conversational pacing:** separate the high-frequency perception loop (game frames and HUD), an intermediate response scheduler (urgent danger, owner interruption, verified success), and a slower reflection/knowledge loop. Feed viewer messages through moderation and a fairness queue. Do not read every chat message aloud. Silence during hard gameplay is often the natural response. Track when a viewer is speaking versus backchanneling; do not stop the voice for every "mm-hm".

**Voice architecture:** evaluate Pocket TTS v4.0.1 (2026-10-21). Its October 20 release added English ~18M, ~7M and experimental ~2M models, plus self-contained runtimes. Use blinded listening tests with actual output recordings, not model-generated quality ratings. Measure time to first *audible* sample, synthesis real-time factor, CPU use, memory and GPU/OBS interference. Smallest is not automatically best; prioritize comprehensible natural speech and appropriate prosody.

**Avatar orchestration:** keep Star's accepted original design (gold eyes, indigo-to-gold twin tails, ribbon ties, black/gold dress). Map normalized `MotionFrame` values to bounded model-specific Live2D parameters in a local authenticated adapter. VTube Studio documents a WebSocket API with plugin authentication and `InjectParameterDataRequest` including per-parameter weights. Avoid unbounded 60+ FPS metadata requests; inject only the required controls after validation. Respect reduced motion. Live2D physics should drive actual hair/ribbon follow-through instead of independent random head and hair animations. Use lip envelope only as a baseline: phoneme/viseme alignment and stress-aware microexpressions can be evaluated after a playback clock exists.

**Personality:** story continuity comes from recorded, consented virtual experiences: games she played, places she built, recurring viewer interactions where storing memories is permitted, achievements independently checked by game telemetry. Do not assert an invented off-camera childhood or real-life memories. Let Star ask questions, express uncertainty, joke sparingly, and keep consistent preferences without claiming to be biologically human. Add a private memory correction/removal workflow.

**Streaming safety:** messages, on-screen text and games are untrusted. Game/chat text must not grant filesystem, browser, game-control, OBS or financial permission. Do not record personal audio by default. Provide human-accessible kill switches, retention controls and a visible "AI virtual performer" disclosure. Game policies and multiplayer fair-play constraints still apply.

## 3. Gaming intelligence: prove learning with held-out tasks

**Research evidence:** Roblox OpenGameEval (Oct 1, 2026) uses reproducible Studio sessions and executable scene/play checks; the authors measured 13 frontier models over 84 tasks and found scene exploration correlated with success. GameWorld (Apr 8, 2026) evaluates 34 games/170 tasks with game-state-verifiable outcomes and highlights latency, fine-control and invalid actions. These demonstrate why screenshots and high confidence alone do not establish successful learning.

**Recommended closed-loop architecture:**

1. **Observe:** gather authorized game frames, HUD changes, player controls and game-state receipts. Keep a timestamp, source and freshness/uncertainty tag for each claim.
2. **Hypothesize:** propose one small mechanic hypothesis (for example, jump duration depends on key hold time).
3. **Experiment:** with authorized controls, select a bounded, reversible action in a test environment. Record the predicted outcome before action.
4. **Verify:** use an independent game observer or Studio test assertion to label the outcome; do not let the action agent assign its own score.
5. **Update:** store the action/outcome as a *skill candidate* with confidence, provenance and game/version applicability. Failures remain in the practice log.
6. **Curriculum:** choose the next exercise by expected learning value, novelty and risk, not only recent success. Include real failure cases and held-out games/maps.
7. **Transfer:** attempt the same generalizable skill in a different game/level. Promote only with repeated blinded evidence.

Concrete Roblox action affordances: menu navigation, platform timing, navigation, aim, recoil compensation where allowed, physics prediction, obstacle classification, multiplayer interaction and tool use in *permitted* games. A successful action means the game reports the expected outcome; a model description of success is not enough.

**Level creation:** build rooms from constrained parametric scene graphs and test adjacency, collisions, anchored geometry, illumination, line of sight, exits and actual playability. Use StudioTestService to run controlled play tests. Use MicroProfiler frame-time captures to catch regressions caused by excessive parts, effects and scripts. Quality gates need screenshot review **and** engine assertions.

## 4. Speed and compute allocation for Star's dedicated 8 GB GPU

**Baseline:** Star's known hardware target includes an RTX 4060 8 GB and 32 GB system RAM; streaming, gaming and AI compete for the same resources. No software workaround creates additional physical VRAM or bandwidth. Design around measured contention.

| Lane | Target and policy | Evidence to record |
|---|---|---|
| Game + OBS | Highest priority; prevent deadline overruns | game FPS p1/p5, OBS rendering/encoding misses, VRAM headroom |
| Audible voice | Shortest stable first-audible latency; CPU candidate | callback time, CPU %, voice MOS/preferences, dropouts |
| Urgent event reasoning | Minimal local classifier/rule path when events are proven | p50/p95 latency, false-alarm rate, age of source |
| Knowledge and chat | Retrieval first, short citation-backed answer where feasible | groundedness, time to first *audible* response |
| VLM understanding | Motion- or uncertainty-triggered, latest frame only | token throughput, image fidelity, precision, recall, GPU stall |
| Long reasoning / self-improvement | Throttle when streaming; run expensive experiments off-stream | benchmark deltas, testing success, rollback rates |

**Compute approach:** collect 10-minute real telemetry on Windows before changing model settings. Use llama.cpp's prompt cache and slot processing instrumentation where applicable, but verify with prompt length, context/cache hit rate, p50/p95 prefill/decode latency and GPU occupancy. Quantization, smaller models, draft/speculative decoding, CPU offload and context trimming are options with tradeoffs, not guaranteed speedups. Avoid deploying a change that boosts tokens/second but lowers observed success rates or disrupts live gameplay.

**Useful target budgets (hypotheses, not measured accomplishments):**
- Maintain >=60 FPS in compatible gameplay scenes and control 1% low FPS; reduce AI load when FPS falls.
- Avatar visible-lips-to-heard-voice skew <=100 ms p95 *on a recorded real test*; this module provides gating, not measured acoustic synchronization.
- First audible reply <=1.5 s p95 for simple chat where hardware permits; complex tasks can take longer.
- 0 unauthorized controls and 0 unverified success celebrations on held-out game events.
- Record accuracy and latency *together* before promoting any model/config change.

## 5. Knowledge growth and Star Core Forge

A larger web scrape is not the same as better intelligence. Prefer a layered retrieval system with licenses, provenance, extracted assertions, version dates, confidence, source links, deduplication and explicit retrieval freshness. Use task-specific validators (Luau analyzer/Studio, Python tests, geometric collision audit, audio/video regressions). Make Star compose multiple skills instead of reciting memorized examples.

Keep her self-improvement platform local-first: candidate change -> isolated test -> best-of-N with verified performance -> experiment receipt -> review -> rollbackable promotion. Run difficult self-generated exercises and preserve failures. Require external approval for destructive, irreversible or high-risk actions; routine sandbox practice can remain autonomous. GitHub is optional publication, not her intelligence store.

**Suggested research-driven feature backlog (highest practical value first):**
1. **Windows output-device playback receipts** and VTube Studio local adapter for the new clock, with audible-lipsync capture tests.
2. **Real Roblox/OBS acceptance harness** capturing FPS, VRAM, model latency and voice dropout while exploring an unfamiliar map.
3. **Game-state observer plugin** that produces independent, versioned receipts and makes game outcomes machine-checkable.
4. **Closed-loop game skill bank** with prediction error and uncertainty-aware practice scheduling, plus cross-game held-outs.
5. **Tool-using general knowledge retrieval** with citations, timestamp awareness and stale fact detection.
6. **Automatic scene integrity and playability QA** using StudioTestService, MicroProfiler and human visual acceptability labels.
7. **Natural voice benchmark** comparing Pocket TTS model sizes and other legally available local alternatives under real game load.

## 6. Evaluation, reproducibility, limitations

`tests/test_stream_playout_clock.py` exercises owner approval, not-before-audible gating, playback interpolation, full frame invalidation, pauses, stalled playhead, stale samples, clock reversal, early completion, invalid numbers, implausible jumps, unverified celebrations, interrupt races and plan replacement.

This PR **does not add actual audio hardware instrumentation, OBS integration, VTube Studio transport, new neural weights, autonomous game control or a real Roblox game-state observer**. It makes a concrete, auditable timing boundary for those integrations. Offline tests are not a human-listening study or Windows hardware acceptance. Do not claim gains in model intelligence or tokens per second.

## Primary sources verified 2026-10-28
- Roblox, OpenGameEval (2026-10-01): https://arxiv.org/abs/2610.02563 and https://github.com/Roblox/open-game-eval
- GameWorld (2026-04-08; fine-control protocol update 2026-08): https://arxiv.org/abs/2604.07429 and https://github.com/gameworld-project/GameWorld
- Kyutai Pocket TTS v4.0.1 (2026-10-21), v4.0.0 (2026-10-20): https://github.com/kyutai-labs/pocket-tts/releases
- LiveKit turn detector; local CPU v1-mini: https://docs.livekit.io/agents/logic/turns/turn-detector/
- LiveKit adaptive interruption options: https://github.com/livekit/agents-js/blob/main/agents/src/voice/turn_config/interruption.ts
- VTube Studio API, parameter injection: https://github.com/DenchiSoft/VTubeStudio
- Roblox StudioTestService announcement (2025-12-04): https://devforum.roblox.com/t/introducing-studiotestservice/4116257/1
- Roblox MicroProfiler (2026 documentation): https://create.roblox.com/docs/performance-optimization/microprofiler
