# STAR — persistent game-worker quarantine, fast local intelligence and believable VTubing
**Research and engineering log — 2026-11-01**
**Status:** An offline-only correctness fix and regression tests are committed. The remaining integrations below are *proposals*, not newly installed models, a broadcast, or measured game-playing improvements.

## 1. Verified production-code flaw: a cancelled lease was mistaken for a stopped worker

The opt-in `star/game_realtime_loop.py` binds a host-verified screenshot to an advisory fast-model lease. Before this change the first newer frame invalidated `_lease` and correctly refused new inference if `previous_worker_stopped=False`. But the **next** newer frame saw `_lease=None` and could recommend starting another worker, although the earlier worker could still be running. In a real streaming host, repeated orphaned inference would compete with OBS, game rendering, and audible speech for compute.

**Reproduction (pre-fix):** issue lease for frame 1; submit frame 2 without worker-stop acknowledgement (correct skip); submit frame 3 without acknowledgement (incorrectly offered another reactive lease). The new test failed against the original implementation. Tests also exposed that stopping the session had no persistent worker-termination barrier.

**Fix:** `RealtimeGameLoop` now retains `worker_stop_pending` independently from `_lease`. Superseding a lease sets the quarantine; subsequent frames cannot clear it by themselves. Only an independently host-attested stop on a *verified* new frame, or `acknowledge_worker_stopped(host_confirmed_stopped=True)`, clears it. `stop()` preserves quarantine and `start()` refuses restart while an old worker might remain live. False, omitted, or wrong-type stop reports do not release quarantine. Counters contain no screen contents, viewer identities or model text.

**Host integration contract:** track the actual inference task/process handle; request cancellation; await a verified exit/termination; only then acknowledge stop. A discarded result, timed-out promise, detached thread, or `future.cancel()` returning True is **not** necessarily proof that computation ended. If the host cannot verify exit, leave STAR's quick-inference path paused; do not automatically clear quarantine after a timer. The caller still separately owns game focus/consent, keyboard key-up, OBS status and worker execution. This module neither runs a model nor presses keys.

**Verification:** a focused red-to-green regression plus four new adversarial tests (three-frame bypass, restart across stop, unverified-frame acknowledgement, and a 128-frame burst with strict boolean checks). A 163-test focused cross-module pytest selection passed with 27 additional subtests on the authorized Linux development host. Ruff and compilation succeeded. No Windows hardware measurements were taken.

## 2. Where the real speed improvement should come from

A system is not faster because its model produces more tokens per second while game frames are late. Optimize **input-to-useful-action**, **event-to-first audible PCM**, and **OBS/game smoothness together**. The invariant is: no second quick worker while an earlier cancelled worker is unconfirmed, even if the world continues moving.

Proposed compute priority, especially for an 8 GB GPU:
1. Game presentation, OS/audio device, OBS encode/capture and key-up watchdog are protected work.
2. Urgent audible continuation/interruption and avatar rendering get bounded low-latency slots.
3. One short, scene-bound reactive reasoning task receives a deadline only when recent *host-measured* p95 completion time fits scene freshness plus dispatch reserve. Old frames are not actions.
4. Local retrieval, general-knowledge research, visual interpretation, art rendering and deep model calls are best-effort, cancellable workloads.
5. Expensive teacher reflection, self-play synthesis, image/video generation, indexing and self-improvement run only in explicitly permitted idle/off-stream windows.

For Star's owned 8 GB-class NVIDIA GPUs, evaluate llama.cpp full prompt/cache setup against speculative decoding, quantization and CPU-layer offload **on the actual Windows host**, not with published benchmark numbers from other hardware. Keep a trace per model build, context size, GPU allocation, slot count, prompt length and concurrency level. Compare p50/p95 **request latency**, tokens/second, first-token latency, VRAM peak, total stream frame loss, and PCM onset. llama.cpp SPEED-Bench measures latency, throughput and draft acceptance of a running server; a higher speculative acceptance rate does not prove a smoother stream.

**Rust migration rule:** profile first. A small Rust library may help hot-path image/frame diffs, PCM ring buffers, compressed scene-replay ingestion or event fan-in; moving high-level orchestration from Python without evidence adds risk and build complexity. Keep interfaces deterministic and rollbackable through Star Core Forge.

## 3. A stronger game learner: three cognitive timescales

**Reactive (< scene deadline):** fast student handles only approved symbolic actions in bounded games, using a fresh observed frame and a curated action set. It does not wait for a large model while the game keeps running. A scene change cancels stale reasoning; actual worker termination remains independently acknowledged.

**Tactical (between moments):** a small planner observes actual state transitions, predicts short outcomes, chooses a strategy, and explains uncertainty. It can select when silence is more appropriate than narration. Invalid or unverified observations are never promoted into memories.

**Teacher (between attempts/off-stream):** a stronger model diagnoses a lost round, proposes a reusable mechanic/skill, chooses harder practice scenarios and compares interventions on fixed-seed replay. Preserve separate practice and validation sets; do not allow held-out answers to become prompts or retroactively adjust benchmarks. Failed attempts matter, and mastered skills need spaced retention checks. Publish only improvements beating matched baselines on unfamiliar game situations.

The 2026-10-14 RealtimeBench paper evaluated 180 continuous-time game tasks and showed why offline teacher/online student separation can outperform slower live reasoning. Its reported gains are **external research**, not measured Star improvements. Add real local results to Star Core Forge's evidence ledger before changing a default.

**General intelligence expansion:** create a source-tracked knowledge index spanning Luau, Rust, graphics, animation, physics, audio engineering, UI patterns, game mechanics, software testing, security and general reference. Every indexed claim should retain source URL, license/usage restrictions, retrieval date, confidence and a freshness policy. Use worked-example retrieval plus unit/visual testing rather than copying unverified code. Require answer calibration: unknown or ambiguous questions should trigger validation, not confident invention. Prefer verified improvements across held-out tasks to sheer document volume.

## 4. Natural VTuber presence without fabricated humanity

To feel like a good human streamer, Star needs continuity, *appropriate timing*, personality consistency and believable attentiveness—not constant speech.

- **Listening:** a local voice pipeline should use real acoustic turn-end detection, configurable pauses and explicit owner interruption handling. LiveKit documents CPU-local `v1-mini`; pin this version for a truly local experiment instead of accidentally selecting a cloud model. Evaluate false turn endings, incidental game noises, interruptions and owner barge-in against hand-reviewed recordings.
- **Speech:** evaluate Kyutai Pocket TTS and its October 2026 smaller English variants on CPU with first-audible-chunk delay, prosody and clarity scored separately. Smaller is not automatically more humanlike. Synchronize avatar lips to **device-consumed PCM**, not to text tokens or queued synthesis.
- **Expression:** VTube Studio's authorized local API can inject tracking/custom parameters. Map verified, low-cardinality events to eye focus, blinks, smiles, mouth shape and subtle idle motion. Reserve bigger gestures for actual surprise, wins, mistakes or jokes; coordinate hair/twin-tail physics with head turns. Preserve a neutral pose on audio stop, renderer disconnect or untrusted source.
- **Presence:** balance talking, quietly concentrating, noticing chat and choosing a viewer question. Let Star develop actual event-based stories: her first victory on a level, a difficult puzzle, a memorable build, a funny mistake, a recurring game rivalry. Persistent biography and claimed memories must be grounded in events that happened, not improvised as human lived experience.
- **Companions/persona:** keep Star, Astro and Amber as independently scripted/expressive characters that can coexist, converse, play/tag and use animal/cat/dog modes without flooding audio. Protect against private viewer content leaking into public narration. Audience interactions may suggest entertainment but never authorize game input, tools, spending, microphone access, or broadcasting.

**Streaming evaluation:** use pre-registered matched viewer questions, commentary prompts, incidental noise, owner interruption and critical-game focus cases. Measure first audible delay, accidental overlap, stop-to-silence, genuinely missed commentary, hallucinated gameplay events and purposeful silence. Never reward a candidate just because it talks less; never reward excessive chatter that worsens gameplay.

## 5. Make Star's games feel authored, not AI-generated

For Roblox, build a repeatable **inspect → design → implement → playtest → look → repair** loop. Inspections gather existing hierarchy, scene bounds, orientation, collision groups, terrain/materials, UI anchor behavior and lighting. Assertions should catch unattached walls, colliding props, missing meshes, oversized body parts, broken grip, clipping labels, transparent textures and wrong pivots.

Use Roblox StudioTestService in authorized development places for automated multiplayer lobby, join/leave, respawn, network conditions and virtual-input tests. Store compact before/after visual evidence and test results in Star Core Forge, not player media or secrets. Build seed-fixed smoke tests and randomized unseen variants; a game is complete when it can be played, not when code merely passes syntax checks. Extend the same pattern to Blender assets, stylized lighting, animation timing, 2D sprites and platformer physics.

## 6. The next high-utility integration experiment

Run a private, owner-approved **Windows rehearsal** with actual game observation, a local inference process, PCM output, VTube Studio and OBS metrics (no public stream required). First, implement a trusted process supervisor that can request cancellation, wait for the exact process/task identity to stop, and then call the new acknowledgement method. Include adversarial trials where cancellation is delayed across 2, 20 and 128 newer frames, host clocks move backwards, a worker never exits, the game loses focus, OBS stalls, and the owner interrupts speech. A failure must leave actions disabled and keys independently released.

For each configuration, use at least 20 matched scenes/voice moments and an unseen holdout of game levels. Record 1%-low frame rate, worst frame hitches, OBS skipped/render/encode frames, GPU peak MiB, model latency p50/p95, event-to-audible PCM onset, interruption-to-silence, factual speech grounding, successful authorized actions and independent game outcome. A candidate is never automatically promoted: it must beat or match baseline without new safety, voice, visual or performance regressions.

**Success hierarchy:** first prove non-overlapping game inference and reliable shutdown; next prove a working local Windows stream rehearsal; then improve measured low-latency speech and avatar synchronization; then demonstrate holdout game-skill gains and high-quality authored game output. The best next engineering work is integration and measurement, not another giant list of untested models.

## Primary technical references reviewed (as of 2026-11-01)

- RealtimeBench / TORSI (research dated 2026-10-14): https://arxiv.org/abs/2610.20665
- llama.cpp SPEED-Bench client and concurrency guidance: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md
- LiveKit local audio turn detector, `v1-mini`, endpointing and fallback: https://docs.livekit.io/agents/logic/turns/turn-detector/
- Kyutai Pocket TTS, CPU streaming and October 2026 small English models: https://github.com/kyutai-labs/pocket-tts
- VTube Studio official local plugin API and custom parameter injection: https://github.com/DenchiSoft/VTubeStudio/blob/master/README.md
- Roblox StudioTestService reference: https://create.roblox.com/docs/reference/engine/classes/StudioTestService

**Limitations:** no real model was trained or installed; no real game was controlled; no public broadcast started; no actual GPU, OBS or audible speech speedup was measured; current work is committed on a public, owner-reviewed draft PR. Keep viewer data, private recordings, credentials and account access tokens outside the repository.
