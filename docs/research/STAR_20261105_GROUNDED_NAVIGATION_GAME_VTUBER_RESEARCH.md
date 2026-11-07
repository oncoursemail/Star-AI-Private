# Star AI: grounded navigation, measured gaming, fast cognition and natural VTubing

**Research audit:** November 5, 2026. **Implementation:** `star/game_navigation_memory.py` with offline adversarial tests. **Status:** experimental, advisory-only; no independent Windows game/OBS/VTube Studio rehearsal or demonstrated neural-model speedup.

## Concrete change — stop inventing a route through unseen game space

Before this branch Star had extensive game-action safety gates, timing labs, signed practice/evaluation receipts and stream-turn arbiters, but no small episode-local spatial navigation memory in this part of the stack. A reasoning model's proposed direction cannot safely stand in for knowledge of the actually observed map. The new `GroundedNavigationMemory`:

- Holds a bounded, per-episode map of **only** host-witnessed grid cells; accepts up to 128 cells/observation and 4,096 cells/episode.
- Uses positive episode scope, strictly increasing observation sequence/capture clock and a configurable short freshness limit. Rejects stale, unverified, future, reversed, wrong-episode and duplicate-cell observations.
- Computes risk-weighted, four-direction shortest paths on **known traversable tiles**. Blocked / sufficiently high-risk cells are excluded; unknown space is never a drivable shortcut.
- Selects a reachable frontier when a verified route to the goal is unavailable. It avoids stationary re-observation loops when a different reachable frontier exists. A repeated request on the same frame is held until a newer host capture.
- Outputs **advisory symbolic** `up/down/left/right`, `observe`, `await_observation`, or `abstain`. It cannot open Roblox, launch a model, press a key, publish OBS, promote a skill or authorize input.
- Deletes episodic spatial memory on stop. No screen pixels, voice, player names, secrets, or model-generated game narrative are stored.

**Measured offline local test scope:** 13 unit/integration-style tests including four previously unseen zigzag maze configurations (different wall gaps), host-trust failure, replay protection, boundary/clock checks, dynamic wall changes, hazard avoidance and a simple blind-greedy comparison. This proves only *deterministic synthetic-grid competence*, not success on real games.

**Host integration contract:** Capture game state through an authorized Studio playtest or a permitted game-observation adapter. Convert observations to a calibrated world grid with confidence/uncertainty and scope, then verify the observation independently. Call `ingest(..., host_verified=True)` only within that trusted host. Treat `NavigationAdvice.action_id` as a suggestion and pass it through existing `GameActionGate`, `RealtimeGameLoop`, live focus/permission checks, OS key-up/stop confirmation and OBS epoch fences. Do not connect it to uncontrolled public game play or anti-cheat bypasses. A flag alone is not proof of host authenticity.

## Intelligence: optimize verified completed goals, not self-reported smartness

**Multi-rate plan for a gaming companion:**

1. **Fast motor path:** deterministic deadline-aware controllers/interruptions with observed frame age; no long LLM thought process in the keypress critical path.
2. **Spatial/task reasoner:** maintain verified maps, inventory, visible HUD objectives, hazards and a short working plan. The new grid memory is one small step, not a world model.
3. **Learning teacher (offstream):** generate bounded private practice problems, record trials from independent game observers, compare against baseline on preregistered seed/map sets, then test genuinely withheld games and difficult scenarios. A failed episode must not disappear from metrics.
4. **General-knowledge retrieval:** cite current authoritative sources; preserve source/provenance and confidence; separate ephemeral web facts from signed project/game evidence. Apply retrieval to unfamiliar rules, in-game mechanics, Studio API changes and factual chat questions.
5. **Owner-governed self-improvement:** design→test→review→rollback. Never allow a language model to define its own hidden benchmark results, invent device permissions or auto-broadcast.

[Google DeepMind SIMA 2 (Nov 13, 2025)](https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/) explores general-purpose game skills and self-directed experience; **it is not a ready-made local dependency**. [GameWorld (2026)](https://gameworld-project.github.io/) benchmarks 170 tasks in 34 sandboxed games with independently verified state; its realtime track keeps the world moving during inference. These motivate two separate scorecards: paused reasoning ability and *deadline-constrained real-play success*. Compare with static/deterministic baselines, blinded seeds and hardware-identical runs.

**Suggested acceptance experiment:** 50 or more held-out private maps/games, separately reset baseline/candidate attempts, exact objectives scored from engine state. Report success/normalized progress, episode time, missed-deadline rate, action-reversal/stall rate and time-to-recovery; compare per game (not just pooled attempts). Add variety: platforming, combat, navigation, puzzle and cooperation. The suggested sample count is a trial design, not a measured result.

## Roblox game creation: turn scripts into playable verified experiences

Roblox announced the [built-in Studio MCP server and automated playtesting (Mar 5, 2026)](https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643). The [April 15, 2026 Roblox Studio update](https://about.roblox.com/newsroom/2026/04/roblox-studio-going-agentic) explains agentic plan/build/test and a beta playtesting agent. [OpenGameEval](https://github.com/Roblox/open-game-eval) tests agents through real Studio scene edits and simulated play, not simply pretty text. In October 2026 its research reported an 84-task curated core benchmark; distinguish that from the **47-case initial December 2025 release**, rather than implying these counts are simultaneous.

**Implementation order:** Studio inspector snapshot → validate Rojo/Luau/instance references → bounded diff → Studio playtest + virtual input → network simulator and multiplayer checks → capture real state assertions/screenshots/console → visual QA and repair → rollback if failed. For UI/lighting/animation, compare captured rendering against owner-defined visual acceptance references and use reproducible camera/lighting seeds. Never claim a generated asset works until loaded and exercised.

## Faster gaming + streaming on 8 GB VRAM

The current practical constraint is concurrent gaming + avatar render + OBS + local inference, **not just model tokens per second**. Treat the earlier 3060 Ti measurements as samples, not stable machine specifications or guaranteed capacity.

- Record 60-second or longer paired traces of p50/p95 request completion, prefill and decode rates, scene-to-action delay, frame p99, VRAM peak/headroom, OBS dropped frames and first **audible** PCM sample.
- [llama.cpp SPEED-Bench](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md) compares compatible model configurations/speculative decoding. Its server/client benchmark does **not** measure a game's real-time responsiveness by itself.
- Preserve hot model and prompt-prefix cache only when actual cache-hit and response tests justify it; avoid duplicating a large speculative draft model on the busy GPU.
- CPU-schedule background research, code validation, caching and lightweight TTS separately from the graphics-critical path. Try [Kyutai Pocket TTS](https://github.com/kyutai-labs/pocket-tts): October 20, 2026 v4.0.0 introduced 18M, 7M and experimental 2M English models; v4.0.1 corrected sub-20M defaults. Benchmark pronunciation, voice naturalness and actual audible startup. Small does **not** imply best perceived voice.
- Admit heavy model work only with sufficient measured GPU/CPU headroom. Give gameplay input/release and spoken interruptions priority; allow low-value prefetch to cancel, and move teacher/training work to offstream windows.

### Humanlike VTuber behavior without misleading viewers

Humanlike streaming is about **timing and grounded personality**, not claiming Star is literally a person. The promising direction is purposeful silence, natural short acknowledgements, interrupts, spontaneous but context-relevant reactions, a consistent expressive identity, and a transparent AI disclosure.

[Microsoft Proact-VL (ICML May 2026)](https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/) specifically studies when a game companion should respond and commentary volume. [NVIDIA PersonaPlex (Jan 15, 2026)](https://research.nvidia.com/labs/adlr/personaplex/) studies live full-duplex role/voice conversation, but its size and integration may be impractical on an 8 GB shared graphics card. [NVIDIA DyaPlex (June 2026)](https://research.nvidia.com/labs/amri/publication/nagano2026dyaplex/) demonstrates synchronized streaming speech+motion research; it should inspire measurable lip/gesture alignment, not be described as already running on Star.

**Private rehearsal rubric:** locally record with OBS *without broadcast*; align trusted game events, actual audio-device consumed PCM, captions and VTS animation on a single monotonic timebase. Score conversation interruption response latency, accidental overlaps per minute, game-relevant commentary precision, factual grounding, context-correct emotion, voice/animation skew and drops/stutters. Retain only consented private artifacts and redact chat/player information. No autonomous public stream until owner-approved production gate and safety checks pass.

## Gaps, dependencies and next gates

- This PR adds **grounded navigation advisory logic**, not real screen perception. Its host observations are trusted only if the separate host adapter actually verifies them. Future work: derive calibrated symbolic tiles from Studio telemetry or screenshots, compare them against ground truth, and abstain on uncertainty.
- No new model weights, neural intelligence benchmark or live game win rate is asserted. The small maze tests validate algorithm behavior but cannot establish broad transfer.
- Do the first non-broadcast Windows rehearsal when GPU/OBS/voice/game processes have sufficient capacity and necessary permission. Preserve running workloads; do not terminate a user's inference job just to obtain a benchmark.
- For production, keep new functionality **OFF by default**. The signature of any "host_verified" flag is not authentication, and a host must not delegate it to a model.
