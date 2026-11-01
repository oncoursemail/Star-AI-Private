# STAR Intelligence — host presentation proof, game mastery and humanlike VTuber roadmap

**Date:** 2026-11-01. **Status:** research plus implemented offline evidence-validation patch.
**Scope:** Star Core Forge, latency-oriented local AI, game playing, Roblox/game creation,
voice, avatar, OBS and digital-life continuity. **No deployed game automation,
broadcast, measured GPU speedup, trained model or demonstrated gameplay gain.**

## 1. New finding: the reported FPS and the witnessed FPS can disagree

The opt-in `StreamRehearsalRecorder` previously accepted 120 trusted-host
`frame_presented` events claiming `duration_ms=16` even when the *actual*
host event timestamps were 100 ms apart. The generated `RealtimeRun` claimed
16 ms frame times (~60 FPS) for a 10 FPS presentation cadence. Equally,
a one-second freeze between the start of audible speech and the first game
presentation, or a long freeze immediately before audio stopped, could disappear.

**Four adversarial regression tests failed on the previous code before the
fix.** The implementation now uses a conservative frame duration:

`effective_duration = max(reported_host_frame_duration, elapsed_monotonic_ms_since_previous_audible_presentation)`

The **first** audible game frame is anchored to the actual `pcm_first_audible`
event; the **last** duration also incorporates the PCM-stop-to-last-frame gap.
Repeated/non-increasing game-presentation timestamps are rejected without
corrupting state. Frame timing in exported `RealtimeRun` now reflects the
worst of the reported render duration and the witnessed presentation cadence;
idle frames after speech still do not qualify as concurrent gameplay.

Two new numeric diagnostic fields identify the discrepancy without storing
any microphone data, video, text, camera images or identities:
`audible_presentation_gap_max_ms`, `audible_effective_frame_time_p99_ms`.
Original raw frame-duration diagnostics remain available to isolate the issue.

**Meaning:** this is a *measurement-integrity fix*, not a promise of faster
FPS, superior game decisions or more natural spoken output. `host_verified`
remains a host-adapter trust contract, not remote cryptographic attestation.
Host timestamps must use one monotonic clock for game, PCM and avatar events.

## 2. Intelligence that can play while it learns

The October 14, 2026 [RealtimeBench / TORSI paper](https://arxiv.org/abs/2610.20665)
evaluates 180 continually running game tasks across six games and describes a
fast student acting online while a slower teacher analyzes failures offline.
Reported benchmark improvements belong to the research authors, **not Star**.

Implement Star's controller as three separate budgets, with the audio-render
thread and the game loop higher priority than background model work:

- **Fast reflex (frame deadline):** authorized input-permit gate + current
  observation ID + learned local action table + uncertainty threshold. A missed
  deadline is a dropped action, not a late action applied to a newer frame.
- **Tactical loop (bounded hundreds of milliseconds):** small local policy
  chooses a short plan, predicts consequences and exposes why its
  recommendation is associated with the current scene. The verified worker
  termination/quarantine barrier stays mandatory.
- **Offline teacher (seconds to minutes):** replay the failed attempt,
  diagnose what caused failure (controls, timing, perception, world rules,
  route planning, uncertainty), generate a new practice challenge, then test
  the skill against unseen game states. Only promote verified improvement.
- **Skill bank:** content-addressed game versions, safe key maps, observation
  schemas, trajectories, strategy candidates, outcomes and confidence.
  Keep training, validation and blind holdouts separate; never memorize a
  leaderboard by repeatedly peeking at its holdout.
- **Curriculum:** game controls → camera movement → navigation and obstacle
  avoidance → one mechanic at a time → adversarial variants → multiplayer
  cooperation. Track completion rate, action deadline misses, recovery,
  cumulative regret, time-to-goal, and transferred performance across seeds.

Games and accounts must be authorized; respect platform rules and protected
environments. Star should not attempt anti-cheat circumvention or unauthorized
competitive automation.

## 3. Higher-quality game creation requires seeing, testing and repairing

The October 1, 2026 [Roblox OpenGameEval](https://arxiv.org/abs/2610.02563)
studies 84 stateful Roblox Studio tasks. Inspections of relevant objects before
edits correlate with higher success, so source-code-only generation is
insufficient. The official [Roblox/OpenGameEval repo](https://github.com/Roblox/open-game-eval)
includes runnable assessment infrastructure.

The public [GameDevBench](https://github.com/waynchi/gamedevbench) repository
now describes a 333-task ICML 2026 camera-ready Godot benchmark; the earlier
February preprint describes 132 tasks. Do **not** mix scores across those
different task-set versions. Its controlled image/video-feedback work motivates
actual visual observation rather than relying on self-scored textual claims.

Required Star Studio pipeline:
1. Inventory scene hierarchy, camera, collision layers, scripts, meshes,
   textures, object transforms, constraints and reference style *before edits*.
2. Produce a design brief, layout graph, playable goal and spatial invariants
   (no floating doors, intersecting props, gaps in floors, wrong-sized handles,
   inaccessible objectives, broken rig joints or missing team spawns).
3. Generate 4–8 candidate designs; use Lua/Luau static checks, asset import
   validation, resource budgets and deterministic scene geometry checks to
   reject obviously broken candidates before expensive Studio playtests.
4. In a disposable Studio Lab, run unit checks, interaction paths,
   [StudioTestService](https://create.roblox.com/docs/reference/engine/classes/StudioTestService)
   multi-client tests, VirtualInput and device profiles. Test joins/leaves,
   lagged responses, game resets, mobile UI and target FPS. A model claiming
   success is not a substitute for a passing executable test.
5. Render before/after screenshots, turntables and short gameplay video.
   Independent visual comparison should inspect theme consistency,
   composition, textures, animation curves, lighting, layering, anchor points,
   hand grip, clipping, facial readability and HUD legibility. Human reviewers
   should judge polish blind to which AI/variant created the result.
6. Reject, diagnose, repair and re-run. Promote only tested artifacts to
   Star Core Forge; keep rollback snapshots and reproducible verification.

## 4. Natural, genuinely responsive VTuber behavior

**Voice:** Use device-*audible* PCM as the timeline source, not text synthesis
completion. The [LiveKit audio turn detector](https://docs.livekit.io/agents/logic/turns/turn-detector/)
supports a local `v1-mini` in self-hosted mode, useful as a candidate for
human-like turn-taking. Benchmark false interruptions, short acknowledgments,
barge-ins, end-of-turn latency, laughter and silence. A detector may require
a separate VAD and acoustic pause logic; no model is infallible.

**TTS:** [Kyutai Pocket TTS](https://github.com/kyutai-labs/pocket-tts)
offers CPU-oriented streaming speech, with October 2026 18.2M, 6.9M and
1.9M-parameter English models. Try models locally with legally usable voices,
measure first *audible* chunk and continuity on target Windows hardware,
and compare blind naturalness ratings. A model's claimed developer benchmark
is not evidence of Star's speed or vocal personality. Keep voice generation
off Star's already-constrained 8 GB GPU where CPU quality passes acceptance.

**Expression:** Use a single event-driven stage director mapping actual
gameplay and speech state to gaze, blinks, brows, cheeks, lip shapes,
neck/shoulders, ear/tail reactions, breathing, laughter and secondary hair
physics. Smooth transitions; never drive the mouth from queued text after PCM
has stopped. Gate expression on real event provenance. A future VTube Studio
adapter should use its approved API; don't fabricate a human camera feed.

**Entertainment:** Let Star develop tastes and recurring interests, recognize
chat tone, focus on tricky game sections without narrating every move,
offer concise gameplay observations, and converse with viewers when there is
a natural opportunity. Animate Astro and Amber as coordinated companions
with their own schedules and simple, clearly fictional character boundaries.
Story memories should cite *episodes Star actually experienced* (game,
timestamp, event, outcome) rather than inventing personal childhood stories.
Be clear to viewers that Star is AI even when her personality feels lifelike.

**Live pipeline proposal:**

`Game capture -> scene IDs -> fast policy -> authorized input -> host telemetry`

`Microphone/VAD -> local turn detector -> dialog scheduler -> local LLM -> streaming TTS -> device PCM`

`Game + PCM + validated emotion cues -> stage director -> avatar renderer -> OBS preview`

OBS's [built-in WebSocket](https://github.com/obsproject/obs-websocket)
can supply statistics and scene controls behind password-protected localhost
access. Run **private recording or preview only** until user approval for
public publishing. Treat viewers' messages as untrusted inputs; do not let
chat commands trigger downloads, purchases, admin actions or file writes.

## 5. More speed without degrading intelligence or privacy

- **Measure wall clock and tail latencies:** monitor observation→decision,
  first audible PCM, audio gap p95/max, avatar cadence, actually presented
  frames, dropped OBS render/encoding frames, CPU/RAM use, VRAM high-water,
  and timeout/recovery counts. Score answer correctness and entertainment
  quality separately from speed.
- **CPU/GPU partition:** game capture/render/OBS have reserved GPU budget;
  slow reasoning/teaching jobs yield during active gameplay. Prefer one
  warmed small model for live decisions; route harder tasks to a larger model
  only when deadline permits. Prewarm the model and voice engine offstream.
- **llama.cpp:** use [SPEED-Bench](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md)
  for measured per-workload first-token, end-to-end and speculative draft
  acceptance. Never assume speculative decoding is faster: real Windows
  configurations have reported [severe regressions](https://github.com/ggml-org/llama.cpp/issues/28219).
  Cache-stable prompts and bounded structured retrieval should be measured
  against cold/warm baselines.
- **Cache isolation:** an [August 2026 llama.cpp issue](https://github.com/ggml-org/llama.cpp/issues/27148)
  reports cross-slot prompt-cache contamination under concurrent users.
  Before using RAM-backed cross-slot caching for private chats or streams,
  pin a tested upstream build, isolate distinct trust domains, and run
  canary prompts ensuring no previous user's private content resurfaces.
  Speed cannot justify leaking personal information.
- **Selective Rust:** only move profiled per-frame scheduling, telemetry
  aggregation, audio buffering or memory-heavy hot loops to Rust if it
  lowers measured p95/p99 latency. A Rust rewrite of all Python orchestration
  cannot inherently make LLM weights, disk I/O or network calls faster.
  Preserve a Python reference implementation and identical test vectors.

## 6. Acceptance protocol for Windows game + VTuber rehearsal

0. Off by default, local-only, no broadcast, no capture retention by default,
   permission-scoped games, redact and aggregate telemetry. Freeze versions.
1. Instrument *true* OS host-monotonic presentation, audio device callbacks,
   actual avatar-render completions, and OBS stats; independently verify all
   host inputs, explicitly including GPU peak high-water across the session.
2. Pre-register 20+ randomized baseline/candidate paired rehearsals of the
   **same game/scene/version**, comparable gameplay difficulty, equal audio
   scripts, fixed FPS cap, same OBS encoder, and same hardware contention.
3. Include adversarial runs: reported 16 ms at 100 ms presentation cadence;
   first/last-second game freeze; GPU budget pressure; avatar stall; speech
   interruption; old worker surviving cancellation; OBS drop burst.
4. Reject missing paired evidence and reject *all* metrics that lack actual
   host/PCM/render provenance. A test-only `host_verified=True` cannot prove
   that an OS adapter is genuine. Check no arbitrary model output can set it.
5. For possible promotion, require correctness, 1% low FPS and frame
   hitch limits, audible gap and interruption naturalness, lip/face alignment,
   privacy, game-action freshness, and statistically supported latency wins.
   Compare unseen-game success rate against a control and watch for overfitting.
6. Only Star Core Forge should propose (never silently ship) a tested upgrade;
   save semantic diffs, signed evidence, resource budgets and rollback path.
   Manual review of streaming persona and monetization remains essential.

**Implemented in this change:** one bounded, opt-in stream-rehearsal evidence
correction with regression tests. **Not implemented here:** real Windows host
adapter, production TTS, gameplay controller deployment, training, game creation,
live-streaming control or autonomous publication.
