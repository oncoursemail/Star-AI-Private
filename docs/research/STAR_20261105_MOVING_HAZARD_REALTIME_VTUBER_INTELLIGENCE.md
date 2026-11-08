# Star AI — moving-hazard gaming, real-time intelligence and VTuber roadmap
**Research and implementation:** 2026-11-05 | **Scope:** offline, opt-in, synthetic gameplay only

## Verified code delivered in this change

- `MazeScenario.patrol` lets an independently controlled test engine evolve a cyclic moving hazard between frames. The simulator validates a bounded, adjacent, non-terminal movement schedule; **the navigator never receives the schedule**.
- Each fresh signed capture reports the hazard *only if locally visible* using existing `ObservedTile.risk_bps`. There are no new signing bypasses.
- A temporarily blocked corridor may be handled by an explicitly bounded **wait for a new authenticated observation**, rather than declaring failure at once.
- The engine, not the navigation advisor, evaluates whether a moving hazard collides with the player. Score receipts distinguish `moving_hazard_hits`, `moving_hazard_waits`, successful goals, hazardous-tile entries, and failed trials.
- Critically, a hazard can advance while Star is idle. A next-frame collision is a **loss**, not something silently rewritten into a successful path. This deliberately exposes the gap between turn-based symbolic planning and real-time competence.
- `patrol=()` is backward compatible with existing static-hazard mazes. No OS input, cameras, streaming, model weights, voice, real-game capture or production deployment is connected.

Reproduce focused tests:

```bash
PYTHONPATH=. python -m pytest -q \
  tests/test_signed_moving_hazard_lab.py \
  tests/test_signed_hazard_maze_lab.py \
  tests/test_signed_maze_lab.py \
  tests/test_game_navigation_memory.py \
  tests/test_game_navigation_source_bridge.py
```

## Prioritized architecture for materially smarter gaming

1. **Independent game-state bridge, not simulated omniscience.** Only approved private sandbox games can supply signed engine state; otherwise use a calibrated screenshot/OCR/vision observer with uncertainty and require game-window focus and explicit owner allowlisting. The existing bridge authenticates packets, not the underlying world. Never turn an LLM's assertion into `host_verified=True`.
2. **Realtime controller separate from planner.** A tight bounded-budget control loop (state machine, safety envelope, short-horizon planning) runs without blocking on a large LLM. A slower deliberation process can propose tactics and explain objectives but cannot hold down keys without the host's dispatch gate. Track action deadlines and decisions made on stale frames; treat expired decisions as misses.
3. **Learn hazard motion with predictions that can abstain.** This release shows a hazard returning and causing a genuine loss. Next: observe several authenticated frames, infer distributions over next-tick occupancy, account for hazard uncertainty and player movement duration, and choose WAIT/retreat/alternate routes. Use held-out patrol patterns and adversarial timing. Never credit offline pathfinding as real-game mastery.
4. **Independent curriculum and memory.** Start with maze/navigation and hazard avoidance, then platform timing, inventory, combat reactions, co-op objectives and unfamiliar rules. Store versioned evidence of wins, attempts, latency, failure causes and previously unseen test environments. Memory retrieval should cite the original frame/trial, decay unreliable lessons, and never promote a strategy based on the agent's self-report.
5. **Cross-game transfer.** Separate learned concepts (danger, safe cover, line of sight, timing, resources) from any game's proprietary action map. Track zero-shot success, adaptation cost, retained skill and transfer to genuinely novel layouts. Game telemetry and clips must respect privacy and platform/game rules.

**Research basis:** Gym-Anything-RT (posted 2026-10-27) evaluates 100 real-time minigames against paused counterparts, highlighting why an agent must continue acting while the world evolves: https://arxiv.org/abs/2610.37567 . SIMA 2 (2025-11-13) studies agents reasoning and learning across 3D environments: https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/

## Natural, responsive VTuber engineering

- **One cohesive character identity**: stable Star/mascot design, consistent preferences, respectful on-stream boundaries, episodic continuity, and separate fictional character lore from facts. Be clear that the performer is an AI, not a human. "Human-like" is defined by interaction quality, not a claim of consciousness.
- **Three independent latency domains**: (a) immediate event animation/reactive gestures; (b) short on-game commentary from observed moments; (c) richer multi-turn conversations and long-form explanations. Critical game actions must not wait for (b) or (c).
- **Turn-taking controller**: input VAD + diarization, don't talk over people unless appropriate, distinguish viewer address vs game audio, allow interruptions, brief acknowledgement/backchannels, per-viewer rate limits, silence when action needs attention, and a clear mute/kill control. Score perceived naturalness through blind playback evaluations alongside objective latency and incorrect-claim rate.
- **Avatar performance**: sound-to-viseme timing, eyebrow/blink/idle motion, accurate emotional intensity, blinking variation, head orientation cues, contextual pose gestures and reduced-motion option. No arbitrary expressive movements during critical game input.
- **Voice hardware choice**: investigate CPU streaming Pocket TTS (2026-10-20 models including ~18M/7M/2M English variants) against an accelerated local voice model; profile first-audio, audio interruptions, CPU load, stream synchronization and VRAM available to game. A 7B full-duplex voice model may exceed practical capacity when an 8GB GPU is concurrently gaming; measure rather than assume.
- **OBS stability**: authenticate obs-websocket, keep publish/live controls owner-gated, track dropped/late frames and audio sync, run 30+ minute private recording before a public stream. Avoid showing secrets, private messages, and desktop notifications.
- **Anti-repetition & social ability**: moment-scoped commentary with novelty filters, topic continuity, viewer opt-in names, emotional variety constrained by actual events, non-manipulative parasocial behavior and transparent moderation. A memory should quote what truly happened, not manufacture past streams.

**Research basis:** Proact-VL studies proactive decisions about when to speak in streams (https://proact-vl.github.io/); NVIDIA PersonaPlex (2026-01-15) studies full-duplex speech turn-taking (https://research.nvidia.com/labs/adlr/personaplex/); DyaPlex (June 2026) studies synchronized speech and motion (https://research.nvidia.com/labs/amri/publication/nagano2026dyaplex/); Pocket TTS releases https://github.com/kyutai-labs/pocket-tts/releases; OBS auth guidance https://github.com/obsproject/obs-websocket.

## Intelligence and speed on constrained hardware

- **Measure correct goals per wall-clock minute** as primary optimization target. Also report p50/p95 capture-to-action, dropped frames, model first token, sustained tokens/sec, voice first audio, VRAM high-water, game FPS, OBS late frames, stalls, 95th-percentile CPU latency and retry/failure rates. Every performance comparison needs paired held-out tasks.
- **Local tiering**: deterministic fast-path for simple status/action checks; 4B–9B quantized local coder/vision model when GPU permits; stronger remote/cloud reasoning only with owner-enabled network route and data protection. Do not claim a 9B always fits 8GB at all context lengths; KV cache competes with game textures and OBS.
- **Cache and decode**: use stable-prefix prompt caching, retrieval from verified work examples, speculative decoding when target/draft acceptance justifies the extra compute, token limits and early stop. Run llama.cpp's server SPEED-Bench with concurrent game/OBS/TTS workload, not just standalone offline tokens/sec: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md .
- **CPU/GPU admission control**: reserve render/game resources; shed background tasks before latency-critical work; never silently overcommit GPU VRAM, repeatedly load models, or perform training mid-stream. Publish a resource ledger for each model and a rollback path when end-to-end performance regresses.
- **Truthfulness and general knowledge**: identify factual uncertainty, provenance-check external retrieval, perform unit/e2e tests on generated code, use targeted search when allowed and keep security/privacy protections on. More retrieval and self-generated practice do not imply better underlying weights without verified gains.

## Making full games, not only scripts

- Use Roblox Studio's supported MCP with a structured `inspect -> plan -> edit -> playtest -> visual compare -> repair` pipeline, plus Luau analyzers, deterministic test worlds, benchmarks, and rollback.
- Roblox's OpenGameEval (2026-10-01 updated research version) has 84 curated tasks and evaluates both scene and playable behavior: https://arxiv.org/abs/2610.02563 . CEGame-Bench (2026-10-19) evaluates cross-engine complete games and finds the gap between code compilation and genuinely playable endings: https://arxiv.org/abs/2610.26098 .
- New Studio MCP Open Cloud access has scoped, per-game permissions and can change assets, products, game passes, settings and more. Keep those writes explicitly approved, not automatically unlocked in an agent's exploratory loop: https://create.roblox.com/docs/studio/mcp-open-cloud .
- Milestones: produce a complete playable vertical slice; independent bot completes core loop; verify saving, multiplayer, controls, perf, economy, UI; only then consider deployment.

## Explicit next acceptance gates

1. **Real-time hazard adaptation:** held-out scripted patrols, sudden reversals, delayed perception, collisions and success vs baseline; aim for fewer hits **without** increasing timeouts or hiding failures.
2. **Signed private Windows host:** a real-game reader and separate independent evaluator on an owner-approved sandbox; demonstrate source attestation, input focus, no desktop notification leaks and full key-release watchdog.
3. **Concurrent Windows VTuber rehearsal:** private recording with game, voice, avatar and OBS under representative load; compare baseline and candidate p95 reaction latency, stable FPS, first-audio latency and human-judged naturalness.
4. **Automated Roblox playtest repair:** one reproducible Studio game mechanic changed and validated in edit/play mode with no unrelated live publishing.

**Limitations:** This PR adds synthetic moving hazards and accurate outcome accounting only. It does not demonstrate a neural-intelligence improvement, faster tokens/sec, safe real-time game control or human-level streaming.
