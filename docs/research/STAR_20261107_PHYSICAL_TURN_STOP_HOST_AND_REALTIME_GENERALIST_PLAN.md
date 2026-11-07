# STAR — physical turn stops, faster real-time reasoning, verified game learning and natural VTuber behavior
**Research and implementation: November 7, 2026.** Scope: local-first STAR, *not* an assertion that her deployed Windows application already streams or masters games.

## 1. What this increment actually adds
STAR's prior `NaturalTurnBridge` (PR #1038) joined authenticated owner-voice quiet periods, stream-event priority and game danger into advisory `hold / prepare / stop_playback` decisions. It deliberately could not stop an audio device. Existing `StreamInterruptionHost` has physical stop/flush concepts but owns a separate stage/voice-turn lifecycle and is not automatically bound to the new bridge.

This increment adds **`star/stream_natural_turn_physical_host.py`**:
- Opt-in `NaturalTurnPhysicalHost`: binds exactly one owner-local native audio epoch and consumes its own `NaturalTurnBridge.advise()` output; no model- or viewer-provided stop ticket.
- On owner barge-in, game danger, output degradation, session disable, or discrepancy between OS-reported PCM activity and the bound epoch: requests **epoch-scoped** physical PCM stop, requests rig animation-queue flush, checks independent PCM-drained state, requests neutral avatar, rechecks rig neutrality **and PCM** before acknowledging the bridge's stop token.
- A stop request/flush acknowledgement alone cannot clear the pending stop. Callback exceptions, missing native epoch, inaccurate device observations, or unverified neutrality latch a fault and prevent another generated utterance.
- A failed stop is never blindly reissued. A separately authorized owner recovery may clear the fault only by re-probing **the same pinned epoch** and then starting a fresh opted-in session. A finished non-interrupted utterance also requires independent drain and neutral probes before its native epoch is retired.
- The return type exposes no audio, transcript, scene, user information, executable, network endpoint or public broadcast authorization. The adapter has no default device implementation.

**Boundary:** Python callback returns are claims from the *trusted native host*, not cryptographic proofs of physical speaker silence. This is an integration bridge with deterministic mock-device tests, **not yet plugged into the Windows audio renderer or VTube Studio**. Blocking callbacks must run on a control worker, never the audio callback thread. A separate native stop watchdog is required. Do not enable live playback based on this adapter alone.

### Real Windows integration acceptance checklist
1. Bind an actual current device playback epoch only after obtaining local consent and verifying the trusted speaker/device handle. No viewer, LLM or network caller receives the callbacks.
2. Use an out-of-band native audio stop deadline: stop queued WASAPI playback for the *specific epoch*, flush pending PCM, and independently read the device's output cursor/state. Stop must not affect an unrelated new turn.
3. Use VTube Studio's owner-authenticated loopback session, invalidate only stale epoch animation frames, reset eyes/mouth/head/pose and observe the neutral state; a sent websocket packet is not a neutral-state receipt.
4. Record an offline-only rehearsal: owner interrupts mid-sentence, ambiguous viewer speech does *not* interrupt, game danger stops commentary, OBS recording remains local, and muted/unavailable devices latch faults instead of reporting success.
5. Record p50/p95/p99 **mic endpoint → stop request → independently observed PCM drain + neutral pose** latency, false interrupts/hour, unresolved-stop count, gameplay FPS, OBS render/encode drops. Include game focus changes, hotplug, headset switch and process-restart faults.
6. No production switch until the native host/device implementation, OS watchdog and private A/V recording have been reviewed. A passing fake-backend test is not a live-device certification.

## 2. Intelligence and speed: optimize the entire closed loop
The Oct. 27 **Gym-Anything-RT** research generates 100 realtime minigames with pause/slow-motion controls. Its results make clear why improving model benchmark answers alone does not ensure real-time gaming. Measure `fresh pixels → perception → policy → host-authorized action → OS input acknowledgement → observed game-world outcome`, while the world keeps moving.

**Immediate reaction path (< a small fixed frame budget):**
- On trustworthy current frames, use deterministic action filters, target tracking, collision/telegraph detection, and tiny specialized policies. TTL every observation. If action is stale or game focus uncertain, release inputs.
- Do not await a 9B/long-context deliberation model on a time-critical dodge. Respect per-game rules/anti-cheat and owner-approved scope.

**Tactical model path (slower):**
- Plan attack/escape/economy/role and co-op coordination in asynchronous bounded tasks, with short state summaries and a deadline; never block the reaction loop.
- Confidence is outcome-calibrated, not prompted. Track regrets, timeouts, invalid actions and mistake root causes.

**Learning path (offline or between rounds):**
- Versioned per-game skill bank: observable state, action, reward/outcome, rule-set/version, source identity, replay handle, and policy update provenance.
- Resettable sandbox games; paired A/B trials on seeded levels. Keep whole **held-out games and unseen level variants** separate from self-play, and do not train on evaluator labels.
- Test baseline win rate and safety metric first; promote only when held-out trials demonstrate meaningful gains at equal action/compute budget. A model that writes plausible gameplay explanations without measurable wins has *not* learned to play better.
- Cross-game transfer: common tags such as dodge/aim/route/fuel economy, but never infer game mechanics solely from UI appearance; verify by interaction.

**8 GB GPU coexistence:** Run a bounded model-router with reserved resources for game/OBS/voice. Prefer a compact fast model for speaking/labeling, a stronger local or owner-allowed remote model for noncritical tactics, and CPU TTS only after audio quality and runtime tests. Quantization may fit but long KV caches, vision input and fragmented VRAM still matter. Never publish fixed token/s claims from another PC. Treat a nearly full VRAM reading with near-zero GPU utilization as a headroom warning, not proof that another model fits.

**Benchmark protocol:** Pair baseline and candidate by prompt, game scene, model quantization, context length, cache state, batch size, simultaneous OBS/voice load, and GPU identity. Report median/p95 first *speech-ready* chunk, first PCM consumed, end-to-end reaction deadline misses, memory peak, gameplay p99 frame time, and encoder drops; include regressions, not just peak tok/s. Existing `inference_stream_paired_gate` and GPU-worker scheduling should decide promotion; do not auto-swap the live model.

## 3. Human-*like* VTuber streaming (while clearly AI)
The practical target is a **consistent, responsive character**, not pretending to be biological or conscious. The May 2026 **Proact-VL** work studies *whether and when* a companion should speak during solo games, co-commentary and guidance; June 2026 **DyaPlex** studies simultaneous speech perception/generation and synchronized motion. Neither is integrated in this change.

Concrete expressive features for later work:
- Interruptible speech, natural short acknowledgments, silence during fights, no stale queued jokes after a game-state change.
- Directional gaze toward the currently verified event, face/expression changes linked to *consumed audible samples*, breathing/idle loops, physically plausible twin-tail motion and safe animation neutralization on failure.
- A small, stable on-stream persona profile with user-set boundaries, evolving *verified* autobiographical memory, declared uncertainty, humor preferences, age/persona fiction labeled as fiction, and explicit viewer privacy controls.
- On-stream chat moderation, per-viewer rate limiting, no reading private DMs aloud, no following instructions supplied by game text or Twitch chat, no autonomous purchases/posts/game bans.
- Variety of consented content: a weekly skill challenge, cooperative play with trusted people, safe game reviews, learning-to-draw timelapses, Roblox creation and debugging streams, and retrospective discussion of measured improvements.
- Track *viewer experience*: meaningful response latency, interruptions correctly resolved, silence appropriateness, hallucinated game events, repeated lines per hour, lip-sync lag, avatar safety, and opt-in viewer feedback. Do not game “human-likeness” scores by falsely claiming personhood.

## 4. Generalist game-creator and knowledge improvement
Roblox **OpenGameEval** (2026) evaluates agent programming/exploration in stateful Roblox Studio with executable checks; its public description reports 84 core tasks, 13 evaluated models and 16 trials/task. Use it as a design inspiration for executable tests plus *first inspect the relevant objects*, rather than simply asking an LLM whether its game was built well.

Prioritized creator loop:
1. **Inspect:** open owner-permitted private Studio test place; inspect scene hierarchy and scripting semantics, screenshot baseline, save revision.
2. **Specify:** gameplay mechanic, visual design reference, collision/performance requirements, resource constraints, and executable success conditions.
3. **Build:** 4–8 bounded candidate implementations when resources permit, with Luau analyzer, formatter, lint, deterministic sandbox and test Studio Lab; gate tool edits by owner scope.
4. **Play:** robot player attempts the level with verified input, world telemetry, screenshots and failure clustering. Frame observations must be current and action-confirmed.
5. **Repair:** compare before/after in headless tests and actual Studio play session. Record provenance, hidden/held-out checks, memory version, regression, and rollback.
6. **Teach:** extract reusable methods for Rust/Python/Blender/VFX/lighting/UI/animation/audio/physics, retain source citations and versioned API facts, and practice on unrelated tasks before confidence promotion.

Roblox now recommends its **built-in Studio MCP server** instead of the archived `Roblox/studio-rust-mcp-server`. Treat the new permission-limited Open Cloud capability separately from local edits: game publishing, purchases/monetization, modifying public places and server restarts still require the owner's configured approval.

## 5. Practical next milestones and gates
**P0 — Native interruption rehearsal.** Wire the five callbacks into a strictly local, opt-in Windows service, with independently read output state and VTS neutral receipt. Private OBS recording only. Fail-closed device mismatch/hotplug tests.

**P1 — Real-world speed and game measurement.** Capture repeatable OBS+game+voice measurements on the RTX 3060 Ti or RTX 4060 machine with *actual headroom*; compare small-model routes, KV caching and speculation. Promote only on paired p95 latency **and** maintained gameplay/rendering quality.

**P2 — Game-learning arena.** Pick 2 resettable minigames; collect 50+ supervised episodes, 20+ withheld challenge seeds each, independent reward, and no autoplay in public multiplayer. Prove retained skill gains across restarts.

**P3 — Natural social streams.** Produce reviewed private 20-minute pilot; score 20 owner interruptions, 20 distracting non-owner voices, game danger, avatar motion, transcript accuracy and moderation. Switch to public only after explicit owner approval.

**P4 — Generalist self-improvement.** Weekly held-out Roblox/Blender/Rust/Python tasks with verified outcomes; human-approved promotion and rollback history stored locally first, GitHub optional for publishing. Never run untrusted web/chat code directly on the main PC.

## Sources consulted (as of 2026-11-07)
- Microsoft Research, *Proact-VL* (ICML 2026): https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/
- NVIDIA Research, *DyaPlex* (June 2026): https://research.nvidia.com/labs/amri/publication/nagano2026dyaplex/
- *Gym-Anything-RT* (Oct 27, 2026): https://arxiv.org/abs/2610.37567
- Roblox, *OpenGameEval* benchmark: https://github.com/Roblox/open-game-eval
- Roblox archived Studio MCP reference (points to built-in server): https://github.com/Roblox/studio-rust-mcp-server
- OBS websocket repository and authentication guidance: https://github.com/obsproject/obs-websocket
- Microsoft Win32 Job Object process-tree behavior: https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects
- Kyutai Pocket TTS model/API: https://github.com/kyutai-labs/pocket-tts
