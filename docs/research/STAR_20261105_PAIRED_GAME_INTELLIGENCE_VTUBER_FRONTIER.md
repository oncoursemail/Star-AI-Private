# STAR: paired intelligence evidence, autonomous gameplay, and grounded VTuber naturalness
**Research date:** 2026-11-05. **Status:** a verified offline reliability increment plus a gated engineering agenda, *not* a deployed intelligent model or successful livestream.

## The new finding: identical aggregate scores can conceal a worse assistant
PR #993 introduced speed/quality routing from matched 30-case evaluation *aggregates*. Aggregate 29/30 from two workers can conceal completely different errors. A faster candidate can regress on a known Studio project-safety test, viewer-interruption behavior, or difficult game mechanic and compensate by fixing a different, less consequential task. Both aggregate scores and Wilson intervals remain identical. This is especially problematic when STAR is asked to play or create games autonomously.

**Implemented this iteration:** `VerifiedPairedRouteCases` requires a separate trusted, ordered per-case receipt for each proposed nonbaseline route. It is keyed by the exact baseline/candidate model+runtime profiles, task kind, workload, held-out suite digest and freshness. It rejects mismatched per-case totals, unverified/stale proof, duplicate proof, regressions on previously passed baseline cases, and any failure on a preregistered critical case. Existing aggregates and live resource QoS remain required. No paired case evidence means **no fast-worker promotion**. The verified existing baseline remains available. This is a conservative manual advisory: not a model load, Windows input action, remote permission, OBS broadcast, or learning trigger.

### How to produce authentic receipts (not implemented here)
1. Trusted local evaluator freezes case IDs, order, rubric, baseline model digest, candidate digest, `critical_cases`, and suite hash *before* either worker runs. Use wholly separate unseen challenge tasks for future validation. Critical cases should include irreversible game edits, wrong Studio identity, anti-cheat boundaries, payment/chat moderation, game objective resets, and owner interruption handling.
2. Run both routes on the *same cases* with identical conditions; independently score observable outcomes (actual game state, compiled Luau, passed playtests, audible playback, OBS progress), not text claims. Store signed or access-controlled receipts in Star Core Forge. The Python `host_verified` flag is **not** an authentication mechanism.
3. Derive the two aggregate `verified_successes` from the exact boolean case vectors. Never assemble aggregates from handpicked trials. Bind evidence to the revision of every model, runtime, voice profile and evaluation procedure. Re-register after any change.
4. Compare p50/p95 first-audio, p95 end-to-end response, valid actions/second, OBS dropped-frame rate, game FPS, RAM/VRAM peaks, and critical-case pass rate while a real game and recorder run. Repeat on separate days and task sets, randomize the order to mitigate warming/cache effects.
5. Permit only owner-approved **private** pilot selection through `StreamBrainGovernor.admit_quality_pilot`. Route to the existing live QoS and fail back to baseline if any quality, freshness, identity, or resource gate is not satisfied.

### Statistical note
Zero observed regressions on 30 tasks does not prove global noninferiority, especially for rare failures or correlated tasks. Wilson bounds on each model's overall success probability do not replace a paired-case analysis. For rollout, add paired discordance statistics and multiple holdout suites with enough power for the chosen tolerances. Audit selection bias and leakage; never call a pilot "higher intelligence" solely from local tests.

## Priority architecture for STAR's real-time gaming and VTuber pipeline
```
Game frames + game telemetry + microphone/chat
          |
 trusted timestamp / privacy / provenance gateway
          |
  fast policy (input deadlines, interrupts, silence)
          +---------- gameplay controller --> bounded input action
          +---------- co-host director ------> speech queue --> avatar cues
          +---------- evidence journal ------> replay + skill verifier
                                  |
                    strategic planner / world model
                                  |
                     background practice Forge
                                  |
                    paired holdout + quality gates
```

**P0: a private 30-minute evidence-backed game + VTuber rehearsal.** Run on the actual Windows gaming host. Exercise real keyboard/gamepad input in an owner-approved test game, generate audible voice, move the avatar, record local OBS output, and capture host timestamps from capture, model generation, speech first chunk, avatar gesture, last audio byte, and OBS recording progress. Preserve a bounded local evidence manifest with hashes of *real* output artifacts. Never claim success from an OBS "recording active" flag alone. Do not initiate a public stream.

**P1: distinguish actions from claims of action.** Associate each input burst with screenshot/frame IDs and state-change receipts. Score objective success, unintended action rate, deadline misses, recovery after failure, and new-map generalization. Teach STAR to detect when she is stuck and choose safe inspect/retry/stop. Use Roblox Studio's *built-in* MCP server and playtest agent (beta) for scene read, Luau edit, test, assert, rollback. Bind every operation to a fresh project identity challenge and record scene-before/after.

**P1: turn practice into transferable skills.** Introduce a curriculum: menus/navigation -> inventory -> platforming/aim -> cooperation -> unfamiliar mechanics -> multi-goal planning -> constructing and repairing Roblox games. For each task, store observation, proposed action, witnessed game effect, uncertainty, and a reusable lesson only after independent verification. Evaluation uses held-out levels, novel objectives, and a new game not used for practice. SIMA 2 (November 2025) supports the general *direction* of self-improving game agents; its reported outcomes do **not** transfer automatically to STAR. OpenGameEval (October 2026) is a concrete 84-task Roblox Studio research benchmark with executable scene/play results.

**P1: lower latency without degrading gameplay.** Preserve separate quick-response, speech and heavier reasoning worker pools. Run the heavier task off the critical gameplay path; use deadline-aware cancellation, bounded queues, fixed model/context identities, and idle-time/offline background learning. The 8 GB GPU constraint makes loading a second speculative draft into VRAM especially risky. Benchmark llama.cpp SPEED-Bench on the exact deployed model and hardware. Compare cold/warm cache, context lengths, prompt prefill, p95 end-to-end latency, and simultaneous OBS FPS rather than tok/s alone. Treat promising third-party speed claims as *hypotheses*, not known gains.

**P2: natural but transparent VTuber identity.** Use persistent persona traits (hobbies, recurring jokes, speaking rhythm, self-described goals) alongside a grounded event memory that explicitly distinguishes witnessed events, viewer assertions, generated fiction, and uncertainty. Avoid fictional first-hand experiences presented as real. STAR should be free to say "I haven't tried that yet" or "I'm not sure." Use contextual spontaneity: a short gasp after a surprising death, silence during tight combat, then a considered debrief; remember a returning viewer only when permitted and with retention limits. Naturalness should not require pretending to be human.

**P2: conversation and avatar coupling.** Implement an explicit full-duplex state machine with Idle/Listen/Speak/Wait/Dual, barge-in priority, truthful playback acknowledgements, no self-interruption loops, viewer chat cooldown, and variable-length speech. Drive eye contact, blink, facial expressions, and gestures from *confirmed spoken phonemes*, witnessed game events, and attention priorities, never just imagined text. Kyutai's Pocket TTS offers October 2026 CPU-friendly 18.2M/6.9M/1.9M English models; A/B their naturalness and first-audio lag against the installed voice, never blindly deploy. NVIDIA PersonaPlex and DyaPlex illustrate approaches to duplex voice and aligned motion; they are research references, not free 8-GB-GPU integrations. Proact-VL (ICML 2026) directly studies **when** a game companion should comment vs remain silent.

**P2: broader knowledge and creativity.** Let STAR retrieve original docs and reputable web information with provenance, cache expiry, and untrusted-text boundaries. Build executable knowledge packs for Luau, Rust, Blender, animation, lighting, sound, 2-D platformers and networked games. Reward finished playable experiences and user-rated creativity, not the size of her notes. Provide an on-device skills planner that schedules constrained experiments and preserves full rollback in Forge; publishing via GitHub remains optional.

## Measurable acceptance criteria (targets, not achieved results)
| Gate | Target before enabling |
| --- | --- |
| Real-time play | p95 input decisions within the game's configured deadline; no unacknowledged action claims |
| Skill learning | objective success increases on *held-out* maps; no regressions on preregistered critical cases |
| Voice | p95 audible first chunk and interruption cancel delays recorded, not inferred from text |
| Avatar | expression/gesture timestamps correlate with confirmed audible words or gameplay events |
| OBS | sustained 30-min local recording with measured bytes, frame drops, audio and video independently reviewed |
| QoS | memory/frame pressure defers low-priority jobs, does not sacrifice game control or viewer answer |
| Identity | no confusion between game/project, viewer statements, AI-generated text, and witnessed experience |
| Autonomy | offline sandbox tasks reversible with resource quota and owner-approved permissions |

### References checked 2026-11-05
- Google DeepMind, SIMA 2, published 2025-11-13: https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/
- Roblox, Studio Going Agentic, 2026-04-15: https://about.roblox.com/en-nz/newsroom/2026/04/roblox-studio-going-agentic
- Roblox, Studio MCP playtest agent beta, 2026-04-09: https://devforum.roblox.com/t/studio-beta-studio-assistant-mcp-playtest-agent/4566767
- OpenGameEval, 2026-10-01: https://arxiv.org/abs/2610.02563 and https://github.com/Roblox/open-game-eval
- Microsoft/PMLR, Proact-VL, ICML 2026: https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/
- NVIDIA, PersonaPlex, 2026-01-15: https://research.nvidia.com/labs/adlr/personaplex/
- NVIDIA, DyaPlex, June 2026: https://research.nvidia.com/labs/amri/publication/nagano2026dyaplex/
- Kyutai Pocket TTS October 2026 small CPU models: https://github.com/kyutai-labs/pocket-tts
- llama.cpp SPEED-Bench reproducible server comparisons: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md
