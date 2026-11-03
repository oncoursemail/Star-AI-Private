# STAR: measuring game intelligence on a real, advancing game clock

Research review: 2026-11-02 (America/Chicago).
Status: offline evaluator with synthetic tests implemented; no real Windows game trials, trained models, or OBS/TTS measurements in this update.

## Research, verified sources, and implications

1. **GameWorld / GameWorld-RT (2026):** Pausing the game while a model reasons and allowing the game to continue are different benchmarks. Score successes and normalized progress from serialized game state (position, coins, checkpoints), not an LLM's claim. Never merge their results. https://gameworld-project.github.io/ and https://arxiv.org/abs/2604.07429
2. **Roblox OpenGameEval (October 2026):** 84 curated stateful Roblox Studio tasks, 13 models, 16 attempts each; executable checks evaluate scenes and simulations. Inspecting objects affected by a proposed edit was associated with higher success. Require project inspection before generating/editing Luau and verify playable gameplay rather than just compilation. https://github.com/Roblox/open-game-eval
3. **llama.cpp SPEED-Bench:** Compare speculative decoding against baseline using identical workload, prompts, output length, and concurrency; measure completed request latency, prompt/decode throughput and draft acceptance. A speculative draft can be slower if memory bandwidth or draft acceptance are poor. https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md
4. **Pocket TTS 4.0 (October 20, 2026):** New 18M, 7M and experimental 2M English models suggest CPU-friendly speech options. Test expressive quality and actual first-*audible* PCM latency on the owner's machine before adopting. https://github.com/kyutai-labs/pocket-tts/releases
5. **LiveKit turn taking:** Endpointing, false-interruption recovery, preemptive generation, and speech playback are separate controls. Preemptive TTS can waste computation after a false turn boundary. https://docs.livekit.io/agents/logic/turns/tuning/
6. **LTS-VoiceAgent (January 26, 2026):** Research proposes background semantic listening and fast foreground responses. This is a candidate architecture, not proof STAR has become faster. https://arxiv.org/abs/2601.19952

## Implemented now: bounded live-clock game outcome evaluator

New Python module: star/game_live_clock_benchmark.py.
New offline tests: tests/test_game_live_clock_benchmark.py.

The trusted capture host independently resets the same game state for each baseline/candidate attempt. STAR does not get to choose hidden holdout scenarios or grade its own objective completion. Each record contains only opaque episode/case IDs, initial state SHA-256, game scope, host monotonic timestamps (observation, inference start/finish, input acknowledgement, action deadline), separately measured world-clock advancement during inference, normalized game-state progress, independently scored success, game p99 frame time, OBS dropped-frame percentage, and an independent-scorer flag.

Safeguards: matched scenario, identical initial state and relative deadline; unique episode IDs; bounded finite numeric values; no pooling unrelated game versions; 1000-record limit. Late/unacknowledged input never counts as an on-time action. A paused game world (or implausibly accelerated simulation) cannot support a live-clock win. Paired bootstrap intervals concern actual state progress. A candidate's extra OBS drops, frame hitches, lost successful scenarios, or greater missed-action count block positive evaluation. Incomplete or unscored pairs cannot enable a positive verdict. A favorable result means only *eligible for a manually supervised pilot*, NEVER permission to control the computer, broadcast, retrain, merge, or publish.

Run offline, after an independently trusted host generates a statistics-only JSONL file:

    python -m star.game_live_clock_benchmark path/to/host-metrics.jsonl

The reader rejects unexpected fields, refuses files over 2 MB and records over 4096 chars; aggregate JSON output contains no viewer identifiers, transcripts, screenshots, raw game state or model text. This CLI is a benchmark analyzer, not a capture/driver implementation.

## Roadmap sorted by impact

**P0 — complete actual Windows nonbroadcast rehearsal.** Connect OBS read-only witness, game capture, VTube Studio, synthesized voice and a dedicated game-input watchdog that independently verifies key release. First do a zero-input dry run, then (with owner authorization) instrument isolated permitted game input. Record game clock advancing during inference; compare pre-registered identical initial game states and deadlines in randomized A/B order. The existing host safety code and this evaluator should be linked only after hardware validation.

**P1 — model/hardware Pareto sweep on the 8 GB GPU.** Benchmark CPU-only fast models, local GPU models, cached prefixes, smaller contexts, batch sizes and speculative drafts under actual OBS+game+avatar+voice loads. For every variant: p50/p95 observation-to-acknowledged-action, late decisions, real game success/progress, game p99 frame time, OBS render/encode/network drops, VRAM, CPU/RAM and first-audible speech delay. Preserve user gaming FPS above throughput vanity metrics. Suspend background teacher/model training when streaming and game pressure spikes. Do not assume a 9B model plus OBS can share 8 GB VRAM without measurements.

**P1 — two-timescale learning.** A bounded reactive agent makes immediate decisions; an offline teacher reviews mistakes, generates graded practice scenarios, develops skills, and tests holdout/generalization. Existing signed-game evidence must remain independent across practice/validation; the model must never hold signing secrets. Validate unseen maps, game versions and genres before accepting skill transfer or changing the live reactive policy.

**P1 — playable games, not code-only demos.** For Roblox: inspect project -> plan -> best-of-N code/scene proposals -> Luau/styling checks -> Studio Lab play tests -> multiplayer client/server tests -> visual and animation checks -> full save/quit/relaunch player journey. The external independent game scorer judges whether the experience actually functions. OpenGameEval can provide repeatable reference tasks.

**P1 — naturally expressive AI VTuber.** Synchronize lip/eye/gesture animation to actual audible playout, not queued TTS. Condition commentary on genuine observed events, chat-turn relevance, game intensity and uncertainty; explicitly allow silence. Use adaptive turn-taking, false-interruption recovery, and consistent personality. Maintain genuine memories of games she truly played, including Astro/Amber interactions; do not pretend AI has human identity or unobserved personal experiences.

**P2 — general knowledge + long-horizon autonomy.** Add version-aware, provenance-backed retrieval for Roblox docs, software references, and verified lessons. Better task decomposition, checkpointing, semantic code diffs, bounded autonomous self-generated tests, rollback and independent validation. Keep private internal self-improvement functional without GitHub; publish to GitHub selectively for owner review.

## Acceptance and limits

The success criterion is measured improvement in deadline-valid game outcomes on a live advancing game, without worse OBS/voice/frame performance, rather than simulated tokens/sec or self-rated intelligence. The current implementation has only synthetic unit tests and no live host traces. An 'independently_scored' Boolean is metadata, not cryptographic authentication; host correctness and episode provenance still require a trusted recorder. No part of this update starts OBS, operates a game, makes a model smarter by training, or turns the AI into a literal human.
