# STAR — signed gameplay-to-input interlock and fast VTuber research
**Date:** 2026-11-03
**Status:** Offline implementation + tests, not a Windows/OBS or live-game acceptance test.

## Finding and improvement

STAR previously had a signed, multi-sample game-state observer, an authenticated telemetry receiver, a liveness thread and an OBS-epoch-fenced input adapter. But the protected memory receiver and the native input path could run independently. A model might have an old OBS-approved action permit after the engine stopped sending facts.

**Implemented: star/game_telemetry_actuation_interlock.py.** This opt-in, owner-only, single-use component composes the existing signed telemetry supervisor with the existing OBS-guarded GameActuationRehearsal. It requires:
- An already-enabled trusted observer and game session, an armed liveness guard and an already-started OBS-guarded game episode.
- The **same immutable canonical game ID** across authenticated telemetry and OBS action episode. Read-only game-scope properties now let the trusted host enforce that binding.
- At least one valid, authenticated source frame, and a fresh receiver health check before any action.
- The original one-time OBS/game/focus/permission permit and independent key-up confirmation from the input adapter.
- A second liveness check AFTER an action returns. If the source dies during input, an otherwise good key-up result is not counted as a safe completed game action.
- **Cross-failure cancellation:** bad/replayed/silent game telemetry requests input stop independently of new packets. Failed actuation terminally shuts down telemetry and clears private memory.
- No automatic restart, hidden action authority, speech approval, game launch or stream-start action.

A signed packet proves only that a pinned host reported a state, not that the host is honest. The new interlock does not itself provide physical Win32 key-up guarantees, OS-process crash recovery, focus monitoring or microphone/OBS control. An independent native process watchdog and real Windows testing remain essential.

**Offline tests:** 16 new cases cover disabled startup, no-frame action refusal, signed source to verified checkpoint/private journal, real permit + confirmed key-up, cross-game rejection, corrupt/replayed frames, independent silence detection, blocked input during source loss, expired postflight, actuation failure, terminal stop and invalid constructors. Simulated components are not hardware acceptance.

## Speed: make decisions before the game changes

A small RTX 4060 with 8 GB VRAM should be treated as a **resource-constrained mixed workload**, not an isolated AI inference benchmark. Budget game engine FPS, GPU encoder, OBS and the desktop compositor BEFORE allocating inference memory. Model quantization and context affect KV and vision caches; do not assume every 9B model fits at a fixed context.

| Priority | Workload | Policy |
| --- | --- | --- |
| P0 | OS cancellation, key-up, telemetry health | Always active during authorized game input; never wait for a model |
| P1 | Reactive model | Only admit fresh frames when measured full-path p95 plus dispatch reserve fits before scene deadline |
| P2 | Tactical model | Small plans at calm points; cancel when a fresher urgent frame arrives |
| P3 | Strategic teacher, self-play, code generation | Off-stream or between rounds; only ship changes passing independent held-out tests |
| P4 | Speech and avatar | CPU speech where quality permits; prioritize first audible chunk, turn-taking and game FPS over tokens/sec |

Benchmark the **full capture -> transfer -> preprocess -> infer -> input ACK** path while the game world remains continuously advancing. Keep failed actions, timeouts, dropped OBS frames, p99 frame time, peak GPU memory and audio first-audible latency in the denominator. Use paired seed/reset state and software version; no claims of speed gains without measurements. Existing STAR module game_capture_to_action_benchmark.py is relevant. For llama.cpp, compare warm/cold prompt caching, parallel slots, speculative decoding and RAM KV swap under the actual game+OBS+voice workload; roll back if GPU contention or p95 latency worsens. Official caching discussion: https://github.com/ggml-org/llama.cpp/pull/16391 .

Kyutai Pocket TTS offers CPU-oriented and new small English model variants (October 2026) as a candidate for preserving GPU resources, but hardware-specific prosody and latency should be evaluated; faster than real time on a different CPU is not a STAR measurement: https://github.com/kyutai-labs/pocket-tts .

## Smarter gameplay and game creation

**Fast agent + offline teacher:** The fast model should output bounded symbolic action proposals, never raw uncontrolled keypresses. Tactical memory stores current objective, uncertainty and permitted environment facts. Between sessions a stronger teacher reviews actual signed practice outcomes, proposes 4–8 strategy candidates, and only transfers skills that survive independent paired game resets, new maps and held-out challenges.

**Curriculum:** Reuse existing game_practice_curriculum.py, game_learning_ladder.py and gameplay_skill_bank.py for progressively more difficult exercises. Require practice recency and independent evaluation before promotion; do not train on held-out validation or interpret a signed receipt as an objectively true fact from a dishonest source.

**Roblox game builder:** Inspect live DataModel and script dependencies, propose best-of-N changes, run Luau static/style tests, launch Studio playtests, verify visual/screenshots and simulate multiplayer join/leave and latency scenarios. Roblox announced the official built-in Studio MCP on **March 5, 2026**: https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643 . StudioTestService supports programmable multi-client testing: https://create.roblox.com/docs/reference/engine/classes/StudioTestService .

**General knowledge:** retrieval of versioned, dated sources; source-trust and contradiction checking; clear distinction between proven memories, tentative guesses and fictional character backstory. Self-improvement should be gated by reproducible tests and should not modify its own evaluator without independent review.

## Humanlike VTuber presence, without fabricated humanity

Naturalness requires a **speech director**, not just a friendly prompt. Rank moments for salience, recognize when to stay silent, avoid talking over important gameplay, pause when viewers interrupt, use short spontaneous interjections and richer post-round reflections. Only narrate verified events the host has decided are public. A genuine private journal entry never grants permission to broadcast it.

Speech/audio measurements: latency from viewer turn to first audible phoneme; barge-in to audio stop; false interruption rate; cut-off tails; voice consistency, emotion/prosody and accent clarity; language content grounded in actual current gameplay. Avatar measurements: mouth-motion/audio sync, blink/head motion timing, GPU impact and idle behavior. LiveKit documents configurable adaptive vs VAD interruptions, false interruption recovery and speech endpointing (Cloud support differs from self-hosted): https://docs.livekit.io/reference/agents/turn-handling-options/ and https://livekit.com/blog/turn-detection-and-interruption-handling .

STAR can maintain a consistent fictional persona, hobbies, remembered projects and social style, but should remain transparent that she is AI and should not pretend to be a biological human or invent real relationships/achievements. Moderation, opt-in viewer memory, privacy and separate permission to speak, publish and control the game remain independent gates.

## Next acceptance milestone: supervised, nonbroadcast Windows rehearsal

1. Bind the signed source to a real **owner-controlled test game** or Studio private test; verify process/IPC peer, strict session, trusted OS monotonic clock and fresh game state independent of STAR's model.
2. Run this new interlock through a native Windows action adapter, independent key-up watchdog and OBS epoch witness. Fault-inject minimized/focus-lost game, source process exit, stopped telemetry, hung model, OBS disconnect, blocked input and key-up failure.
3. Inspect actual OS key state and reverify stream status; synthetic tests and SendInput returns alone are insufficient.
4. Compare full-path paired benchmarks and record game FPS, OBS dropped frames, p99 frame time, VRAM, CPU, TTS first-audio and avatar A/V alignment in a **local recording**. Do not broadcast.
5. Pass independent playability / learning / personality naturalness reviews before enabling broader autonomy.

**Not established in this increment:** faster neural inference, greater game win rate, Windows physical release guarantees, new model weights, working real-game autonomy, live VTuber speech or human consciousness.
