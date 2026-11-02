# STAR — 2026-11-02: Completed-inference postflight, game intelligence and VTuber performance

Status: **a real offline bug was reproduced and fixed in this branch**. Research items below are proposals, **not** deployed capabilities. The host remains the authority over input, OBS, capture, secrets, and training. The code never launches a model or a stream.

## 1. Reproduced game-reaction latency bug

STAR's `RealtimeGameLoop.offer` asks `GameDeadlineRouter.advise` whether the *estimated p95 duration of a new inference* fits inside the frame's remaining lifetime. Correct at admission. On `finish`, the same estimation was applied **again**, even though that exact, object-identity-bound inference was already complete. A verified reply finishing at 1,280 ms for a frame captured at 1,000 ms was dropped as `reactive_p95_exceeds_scene_slack` when the 350 ms frame lifetime and 40 ms dispatch reserve still permitted action.

Reproduction:
- Profile: 5 independently host-measured 60 ms reactive samples; scene captured at 1,000 ms; initial offer at 1,100 ms.
- Lease expiry: 1,310 ms (frame expiry minus 40 ms reserve).
- Verified completion: 1,280 ms; **30 ms remains before lease expiry**.
- Previous behavior: rejects completed answer because a *second* projected 60 ms inference would not fit into 30 ms.
- Correct behavior: recheck scope, host clock, independent host evidence, actual scene expiration, resource pressure, live OBS governor, and the final game action gate. **Do not pretend a second inference must run.**

New `completed_inference` advisory mode retains default admission behavior for existing callers. Only the trusted, previously admitted `RealtimeGameLoop.finish` calls it after authenticating the original lease and frame by object identity. Both advisory modes grant **zero** permission to launch inference or press a game key. The host still has to pass `GameActionGate.request`, the one-shot permit claim, a fresh focus/owner permission check, and host-confirmed release. The fix is not a measured increase in neural tokens/sec; it prevents a known class of **unnecessary late-response rejection** while preserving timing fences.

Red → green regression: `test_completed_inference_must_not_pay_its_p95_cost_twice` failed on the parent with `reactive_p95_exceeds_scene_slack`; it passed after this fix. Additional cases confirm that expired scenes, absent host verification, CPU pressure, and untyped control flags remain blocked.

## 2. Architecture: faster real-time gameplay without compromising quality

**Three-clock design.** The input clock (frames and deadlines), speech clock (microphone and sound-device acknowledgements), and slower teacher clock (offline attempts/analysis) should be independently measured. Every action/reaction needs provenance: game/episode/scene, capture timestamp, source evidence, model dispatch/finish, final focus check, and key-up confirmation. Never treat fast model generation or a cached scene as proof that the action was delivered. Collect p50/p95/p99 *capture-to-permit* and *capture-to-key-up*, not just raw tokens/sec.

**Two-timescale reasoning.** Run a bounded low-latency gaming policy only during active play. A stronger multimodal teacher studies misplays, physics, objective sequencing, and failures **between** episodes; practice plans stay separate from held-out evaluation. Avoid changing a live policy merely because an LLM asserted it improved. `OmniGameArena` (2026-06-08) specifically evaluates improvement curves across repeated reflection and held-out task variants; implement its methodology, not assume its results transfer to STAR. RealtimeBench (2026-10) likewise motivates fast-student/slow-teacher experiments. Cite their authors' external results as research, never as local benchmarks.

**Skill promotion.** Prefer owner-curated practice seeds → paired AB/BA runs under verified reset states → independent sealed holdout across several *games* → signed outcomes → regression/uncertainty analysis → explicitly approved canary. Existing modules already cover much of this: `game_paired_study`, `game_transfer_eval`, `game_skill_gate`, `game_learning_ladder`, `gameplay_skill_bank`. Integrate these; do **not** create a competing, weaker scoring system. Track game win rate, progress per action, falls/damage, route coverage, and generalization to unseen maps. Ban validation/evaluation scenes from the training memory bank.

**Local model routing.** On a constrained 8 GB graphics card, prioritize measured GPU headroom for the actual game, avatar, and OBS. Profile small CPU teacher/router models and quantized GPU fast models by actual *whole-loop latency*, frame pacing, VRAM, VRAM growth at long context, game FPS, and task success. Cache only validated system/skill prefixes; never silently reduce context below required evidence. Benchmark speculative decoding against non-speculation at identical model, prompts, sampling, context, and GPU load. Speculation can be slower or require extra memory; published single-hardware gains are not universal.

**Next acceptance gate.** After this isolated fix, conduct a nonbroadcast Windows dry-run with the *real* host and OBS/VTube Studio attached. Reject the release unless it preserves safe focus/key-up behavior, raises or preserves successful valid-in-window actions, does not increase frame misses, and records no private viewer content. Separate performance gains from quality gains.

## 3. An expressive, humanlike AI VTuber: measurable functionality

The goal is a convincing *fictional character*, not the claim that STAR is biologically human or has a human life history.

- **Conversational rhythm:** stream microphone VAD + end-of-turn model + verified audio device playout. Compare false interruptions, p50/p95 end-of-turn delay, muted-mic recovery, echo, overlapped speech, and viewer queue fairness. LiveKit's EOT benchmark highlights why choosing the cheapest/smallest EOT detector by size alone can increase awkward false cuts. The existing `stream_endpointing_eval` gives a base to adapt to genuine user speech captures with permission.
- **Speech performance:** compare Pocket TTS v4.0.1 (released 2026-10-21, correcting v4.0.0) with current speech in an **offline** A/B test using fixed audio, short gaming interjections, proper nouns, English emotion, and jitter. Track first audible sample, continuity/glitches, intonation consistency, CPU %, GPU headroom, and codec/virtual-microphone latency; no unsanctioned voice cloning.
- **Avatar and stage:** drive VTube Studio custom parameters only from verified affect/state signals (surprise, concentration, curiosity, pause, speech mouth level, idle micro-movements). Keep time-aligned audio/expressions; use bounded motion to avoid uncanny constant movement. Respect reduced motion and user-approved social/collaboration settings.
- **Personality continuity:** persistent persona with transparent AI identity, episodic signed memories of actual gameplay, user-safe preferences, game-state provenance, a consistent style of humor, and the ability to say *“I don't know”*. Never fabricate viewer relationships, real-life autobiographical events, victories, or emotions as facts.
- **Social guardrails:** rate-limit unsolicited replies, opt-in viewer memory, profanity and age-sensitive moderation, redaction by default, explicit broadcast approval, robust anti-prompt-injection separation between chat text and device control. Define a graceful silent mode on CPU/VRAM stress. Never interpret Twitch/chat commands as device authorization.

## 4. Game creation and general intelligence backlog

1. **Roblox production:** capture Studio object tree and constraints; generate alternatives; typecheck and format Luau; run tests using `StudioTestService` (up to 8 simulated clients) and `VirtualInput`; inspect actual scene geometry, anchoring, collision, placements, and resolution-specific UI; automatically detect and repair regressions with independently reviewed artifacts.
2. **Game mastery:** curate physics/movement/shooting/platforming lessons from multiple games; build an ability graph (observation, aiming, movement, timing, crafting, navigation, dialogue) and promote verified subskills only when independent holdouts improve.
3. **General knowledge:** verified source retrieval, confidence/uncertainty, citation tracing, temporal freshness and personal-data partitioning. Test ability on unseen user questions, tool errors, and adversarial webpage text, not just self-generated trivia.
4. **Self-improvement infrastructure:** session-bound worker cancellation, rollbackable immutable experiments, reproducible benchmark manifests, owner-reviewed promotions, signing keys outside agent process, and scoped rollback if FPS/voice quality/safety gates regress. Local-first storage remains canonical; GitHub is optional publication.
5. **OBS rehearsal:** secure authenticated obs-websocket for **read-only stats first**; evaluate game FPS, encoder skipped frames, audio playout, virtual microphone, VTube Studio parameter stability, memory pressure, and process-identity isolation simultaneously. Do not auto-start a broadcast.

## 5. Independent research sources (checked 2026-11-02)

- OmniGameArena / Improvement Dynamics Curve, research released 2026-06-08: https://arxiv.org/abs/2606.09826 — focus on held-out variants and repeated-reflection evaluation.
- Roblox Creator testing modes: https://github.com/Roblox/creator-docs/blob/main/content/en-us/studio/testing-modes.md — scripted multiplayer, virtual input, device emulation.
- llama.cpp performance flags (external experiment, **hardware-specific**, not STAR evidence): https://graphometer.ai/speculation-gate/ — speculative gate defaults and paired tests.
- Long-context speculative decoding with compressed draft memory (preprint 2026-08-31): https://arxiv.org/abs/2608.30252 — memory/acceptance trade-off.
- LiveKit reproducible end-of-turn benchmark: https://github.com/dlange-aai/livekit-eot-bench — false-cut vs response-delay trade-offs.
- Pocket TTS releases, 2026-10-20 and 2026-10-21: https://github.com/kyutai-labs/pocket-tts/releases — smaller CPU candidates.
- VTube Studio API plugin/custom parameters: https://github.com/DenchiSoft/VTubeStudio/wiki/Plugins — explicit local plugin authentication and controlled facial parameter injection.
- OBS WebSocket: https://github.com/obsproject/obs-websocket — OBS 28+ bundled WebSocket; protect with password, no automatic broadcast.

**Scope limits:** this patch is purely offline Python advisory logic with tests; it does not run gameplay, tune a model, synthesize speech, access the Windows host, or stream. No new speed or win-rate claim without measured dry-run results.
