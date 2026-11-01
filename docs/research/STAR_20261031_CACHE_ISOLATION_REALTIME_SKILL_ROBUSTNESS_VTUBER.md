# STAR: cache isolation, robust game learning, and natural VTuber responsiveness
Date: 2026-10-31. Status: researched design + two focused Python corrections, a synthetic opt-in local inference cache-isolation probe, and regression tests in draft PR #845. No Windows/OBS execution, model replacement, or performance gain claimed.

## Current-state inventory (inspected branch `feat/stream-cooperative-motion-cancel-20261030`)
- `star/stream_brain_governor.py` already connects trusted telemetry, `AdaptiveQoS`, and `StarStage`. Do **not** add a second independent scheduler. Keep the real FPS/CPU/VRAM/audio sensors as the only authority for work admission.
- `star/game_learning_ladder.py` already derives practice choices from a signed practice bank; `star/game_skill_gate.py` checks matched unseen scenarios; `star/game_action_gate.py` and `star/game_action_freshness.py` are advisory game-action controls. None independently presses game keys.
- `star/stream_turntaking.py` already has echo-aware owner/guest VAD hints. `star/stream_realtime_quality_gate.py` and `star/stream_workload_quality_matrix.py` already demand independent OBS and task-quality evidence. Do not replace these with self-reported model scores.
- Existing general-knowledge benchmark covers only ten **development** tasks. Its source-inventory/format checks are not a verified increase in general intelligence.

## New finding A — local KV/prompt caching can trade correctness for speed
**Urgent verification item, not a blanket claim about every llama.cpp build.** On Aug 15, 2026, ggml-org/llama.cpp issue #27148 reported a reproducible case where RAM-backed prompt/slot caching allowed a later response to continue unrelated previous context. It remained shown as open on Oct 31. A reporter tested `--no-cache-idle-slots --cache-ram 0` together as a mitigation on their specific build; they warned that either option by itself was insufficient. Their examples included a two-slot, non-unified-KV configuration. Issue: https://github.com/ggml-org/llama.cpp/issues/27148 . There is also a separate slot-local cache-reuse inefficiency discussion, #22942: https://github.com/ggml-org/llama.cpp/issues/22942 .

**Practical STAR rule:** treat caches as containing potentially private context. Prior to enabling RAM-disk/shared-prompt caches across independent persona, viewer, code, research, and game sessions:
1. Pin and record the exact server binary hash/build, GPU backend, model/quantization, `--parallel`, KV mode, prompt-caching and idle-slot flags.
2. Verify a *negative control*: run two distinct canary system prompts and long unrelated turns in parallel and sequentially. Canary A content must **never** appear in B. Repeat at realistic context lengths and reload/eviction patterns. Never use actual viewer messages or secrets as canaries.
3. Verify **positive** acceleration: same-session, same-prefix warm requests should actually lower prefill/TTFT under contention. Record output accuracy, tokens/s, p50/p95 TTFT, RSS, VRAM, game-frame p99, dropped PCM, and audio latency; cached-token accounting alone is not sufficient evidence.
4. If the build fails cross-context isolation, quarantine caching immediately for that build. The *reported* flag pair is a candidate mitigation requiring revalidation on STAR's own binary; it is not an authenticated upstream fix or a proven universal solution.
5. Keep each persona/game/project trust context isolated even if that costs cached-token hit rate. Do not silently reuse KV across unrelated identities or confidential work.

**Decision policy:** speed wins only count when memory isolation, factual correctness, and stream QoS stay within bounds. A 30% tokens/s gain is **not** an upgrade if it sometimes produces a previous viewer's response.

## New finding B — real-time gaming should learn on two timescales
Pan et al., *The World Won't Wait* (arXiv:2610.20665, Oct 14, 2026) report RealtimeBench: 180 tasks in six continuously running game types. Their TORSI teacher studies mistakes between attempts and writes reusable instructions for a faster student to use while live; their experimental student rose from 13.51 to 24.19/100 over two rounds. These are **reported paper results**, not STAR measurements. Source: https://arxiv.org/abs/2610.20665 .

Implement in stages, reusing Star's existing components:
- **Fast path (live):** fresh visual observation -> relevant verified game strategy snippet -> bounded symbolic action proposal -> host focus/consent/anti-cheat rules -> freshness check at physical dispatch. No slow teacher inference in the critical path.
- **Slow path (offline):** signed practice trajectory -> mistake taxonomy (bad observation, late action, wrong mechanic, strategy, UI/game bug) -> one preregistered hypothesis -> paired practice trial with controlled seed/scene reset -> external verified holdouts. The teacher may propose rules but cannot self-attest a win.
- **Promotion gate:** compare baseline/candidate in the same live-clock mode and game version. Require independent unseen scenes, no newly failed wins, no per-case or per-scenario skill regressions, no p95 action delay regression, and separate safety/quality review. Preserve earlier version in Star Core Forge for rollback. Never count paused-game improvement as real-time evidence.
- **Curriculum:** start with camera/menu controls, learn movement and jump timing, then platform mechanics, route-planning, puzzles, teamplay and combat on user-authorized/private test servers. Test transfer to new maps and altered mechanics; do not train on hidden evaluation seeds.
- **Gaming personalities:** Star can be playful, competitive, focused, proud of a confirmed win, or frustrated by repeated mistakes; reactions should be generated from **observed** facts, not invented achievements.

This run strengthened the existing skill gate: many small `<2.5%` per-case losses on one map can no longer be hidden by a large aggregate gain on another map. It adds a per-scenario mean-regression block (>1 percentage point). This is a *test-quality* improvement, not proof that Star now plays better.

## New finding C — humanlike speech needs reliable interruption semantics
LiveKit documents a local CPU `v1-mini` turn detector, with VAD and endpointing constraints, including a 250ms minimum VAD silence setting: https://docs.livekit.io/agents/logic/turns/turn-detector/ . This is a **candidate** model, not currently wired into Star's host. Test it against Star's current host-VAD logic on locally consented conversational turns, with short acknowledgments, mid-sentence pauses, background game audio, and real owner interruptions.

During a live game, use a bounded attention policy:
- **Action-critical:** short utterance or silence; never chatter over dodges, jumps, raids or complex team comms.
- **Viewers speaking:** delay until turn end; respect chat moderation, queue fairness, and speaker priority; use natural but measured response variation.
- **Star speaking:** allow verified owner interruption; local audio and animation must stop/flush before a replacement plan; do not allow duplicate speech workers to overlap.
- **After actual events:** choose a small expression/emote from actual game evidence and voice prosody; keep timing correlated to PCM, not just text tokens.
- **Between rounds:** share accurately grounded reflections, recurring jokes, progress, interests, and episode memories. If no verified memory exists, say so instead of inventing an off-camera human life.
- **Character animation:** blinking, deliberate gaze, ear/tilt/cat mode, smile/laugh, breathing, secondary hair/twin-tail motion, response to success and failure, and reduced-motion support. Keep a consistent four-point star/hair/black-gold identity.

This run corrected `TurnTakingGate` owner-yield **telemetry**: polling the same confirmed utterance repeatedly no longer inflates its `owner_yields` counter. Importantly, the advice `should_interrupt` remains actionable until the host actually stops playback; the change does NOT suppress repeated safety requests or claim physical interruption worked.

## VTube Studio / OBS integration findings
- VTube Studio's documented plugin system permits custom parameter injection into a Live2D model; use locally authorized model-specific parameter allowlists for gaze, blush, ear, smile, hair oscillation and expression. Do not expose unrestricted plugin permissions to viewer text. Source: https://github.com/DenchiSoft/VTubeStudio/wiki/Plugins .
- OBS Studio includes obs-websocket from OBS 28 onward. The official project recommends password authentication; put OBS on localhost (or authenticated private transport) and never expose broadcast-start controls as unsanitized model tools. Source: https://github.com/obsproject/obs-websocket .
- Build a **rehearsal mode** first: local, unlisted capture; OBS output and device-loopback audio timestamps; VTube rig output; game FPS/frametimes; VRAM; temperature; and spoken-word alignment. A TTS queue callback is not proof that viewers heard a sentence.

## Practical hardware scheduling for an 8 GB gaming GPU
- Preserve at least the existing live GPU reserve; actual game frametimes, VRAM, audio backlog, CPU busy and pressure drive admission. Do not interpret an ideal synthetic tokens/s benchmark as streaming quality.
- Warm a **small** fast-path model for live cues. Route complex research/game design to stronger background teacher when not live and when owner-approved resource telemetry allows it. Prefer single live inference lease unless actual hardware shows another concurrency setting improves p95 without harming FPS.
- Do not move a hot subsystem to Rust solely for language choice. First profile the CPU flamegraph and timeline; consider Rust only for a measured bottleneck such as capture/RPC/cross-process copying, with ABI, rollback and test requirements. Python should remain orchestration-friendly.
- Use prompt prefix stability, task-level retrieval, cache isolation, selective scene crops, diffed visual updates and bounded TTS chunks. Separate cache correctness tests from performance tests.

## Game creation + general knowledge expansion
- Roblox generation: inspect scene graph before edits; compile/type-check Luau; check object anchors, collisions, mesh scale, PBR/texture seams, lighting, rigs and animation joints; run StudioTestService multiplayer exercises; capture screenshots and measure mismatches; repair and rerun. A correct Luau script alone does not prove a good game.
- General knowledge: source-linked retrieval separated into durable verified facts, time-sensitive external facts, hypotheses, private memories, and persona fiction. Evaluate on unseen questions in STEM, visual reasoning, legal research (with appropriate disclaimers), maps, software, mechanics, math, history, digital audio, media literacy, and design. Include abstention quality and source aging.
- For VTubing, use truthful episodic memories as distinct from general knowledge. Mood/expressiveness can be humanlike; Star should identify as AI when relevant rather than fabricate human experiences or consciousness.

## Reproducible staged acceptance criteria
| Gate | Evidence needed | What does not count |
|---|---|---|
| Cache safety | No cross-session canary leakage across concurrent + sequential long turns on pinned build | Cached-token rate alone |
| Gaming student | Paired unseen real-clock game objectives, map-by-map progress, no holdout leakage, p95 action delay | Paused-game wins |
| Streaming naturalness | Consent-based listening panel blind A/B, verified interruption stop timing, transcript/PCM agreement, independent OBS audio + A/V | TTS enqueue or self-reported naturalness |
| Speed | Game p99 frame time, inference TTFT, CPU/VRAM, audio underruns, 1%-low FPS across actual game load | Idle tokens/s only |
| Game creation | Roblox executable tests, screenshot/object audit, multiplayer interactions, genuine gameplay review | Generated code length |
| General knowledge | Fresh unseen source-grounded tasks, calibration, source provenance, no answer contamination | Ten public development cases |

## Honest status and next experiment
This run modified `star/game_skill_gate.py` and `star/stream_turntaking.py`, and added `star/llama_cache_isolation_probe.py` with `tests/test_llama_cache_isolation_probe.py`, in addition to the relevant regression tests.

For a pinned, locally hosted llama-server already running **off-stream**, an authorized operator can exercise the synthetic probe:

```bash
python -m star.llama_cache_isolation_probe --endpoint http://127.0.0.1:8080/v1/chat/completions --pairs 4 --opt-in-local
```

By default this probe performs **sequential** synthetic A/B requests. The `--concurrent` flag also dispatches each pair in two worker threads to exercise a two-slot server. It compares outputs against current and earlier synthetic markers, but **does not guarantee cache eviction**, exercise very-long-context states, or inspect internal KV state. Run the variants separately and repeat with different `--filler-blocks` values on a pinned build. A positive leak indicator is actionable; a clean report is merely `no_leak_observed_not_proven_safe` and must never be called a security certification. Do not send real viewer or private context to an unverified server. No new model, LiveKit, VTS, OBS, Rust engine, game controller, or unsafe cache workaround was deployed. Next prioritize a **pinned build and cross-context canary test** for llama-server (before accelerating cached context), followed by a locally authorized Windows rehearsal. If it cannot be measured, do not report a speed or intelligence improvement.
