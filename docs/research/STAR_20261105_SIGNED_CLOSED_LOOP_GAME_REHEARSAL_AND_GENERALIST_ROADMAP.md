# STAR AI — signed closed-loop game rehearsal and generalist VTuber roadmap
**2026-11-05** · Status: offline synthetic implementation + researched architecture; NOT a real game/stream deployment.

## 1. What changed in executable code

A previously missing *end-to-end offline integration* now connects:
**private synthetic game truth -> bounded local capture -> engine-side HMAC signed packet -> AuthenticatedNavigationBridge -> GroundedNavigationMemory -> symbolic hint -> synthetic engine legality check + state update -> independent goal scorer.**

`star/signed_maze_lab.py` supplies:
- `MazeScenario`: small, validated, reachable ASCII game maps; walls and shortest paths are owned by the simulator, NOT by the advisor.
- `run_signed_maze_trial`: each trial generates a fresh ephemeral HMAC key and 128-bit session ID, accepts strictly sequential fresh observation packets, consumes at most 512 symbolic steps, and counts **executed synthetic movements** rather than imagined suggestions. No OS inputs, Roblox/OBS, network or external game process.
- `MazeTrialScore`: engine-witnessed success, actual moves, independently computed BFS optimum, hints without movement, invalid actions, source revocation, efficiency with failure scored zero.
- `run_maze_benchmark`: bounded independent per-scenario results; it does not average away a failed episode or claim model weight improvement.
- Regression tests on fresh corridors and hidden zigzag partitions, owner-gate, malformed maps, duplicate manifests, strict budgets, and secret-free scorecards.

**Key distinction:** signing inside a local test harness exercises packet integration; it does NOT attest a real game's honesty, process identity, window focus, or physical input. The source signing key must NEVER be exposed to the model or a game's untrusted scripts. This fixture must not be promoted to a real-game input adapter or to autonomous publication.

### Developer-only verification
```bash
python -m pytest -q tests/test_signed_maze_lab.py tests/test_game_navigation_source_bridge.py tests/test_game_navigation_memory.py
ruff check star/signed_maze_lab.py tests/test_signed_maze_lab.py
```
Host tests should use Star's existing project venv; no runtime dependencies or model downloads were added.

## 2. Near-term intelligence improvements: learn from reality, not optimistic text

Source: GameWorld (April 8, 2026), **34 games / 170 outcome-verifiable tasks**, evaluates objective state, also offers a real-time mode in which the game progresses during reasoning:
https://arxiv.org/abs/2604.07429
https://gameworld-bench.github.io/

Proposed path:
1. **Hidden train/holdout separation.** Build 50+ authorized private offline challenges with sealed map layouts, hazards, timing and unseen rules; holdout seeds must stay out of prompts, model context, and memory writes.
2. **Closed-loop receipts.** Independently record observation ID, symbolic action, engine acceptance/denial, post-action position and actual objective state. A planned movement or TTS statement is not a witnessed movement.
3. **Curriculum learner.** Group failures into navigation, perception, latency, tool misuse, planning, and irrecoverable-state categories. Generate one constrained hypothesis at a time; re-run a matched control and candidate across heldout tasks.
4. **Skill bank with provenance.** Save only objectively successful action recipes with map/version, confidence, failure modes, expiry, and retrieval tags. Do NOT auto-promote synthetic scores to real-game skill proficiency.
5. **Transfer.** After offline maze skills, test first real authorized game in a **private Windows rehearsal** with independently grounded game-state observations; measure win rate, time-to-completion, action legality, near-miss recovery and system latency.

Potential extra skills: inventory handling, NPC dialogue, timing/dodging, platforming, cooperative goals, UI navigation, multiplayer moderation and creator-tool execution. These are planned skills, not current capabilities.

## 3. Faster AI on 8 GB graphics cards: prioritize end-to-end latency

STAR currently targets affordable 8 GB GPUs for gaming + VTuber + local AI workloads. Model throughput alone is misleading if inference starves the game or voice.

**Workload-separated scheduler:**
- Reflex loop: deterministic safety/collision/stop and navigation logic with short bounded tick; never block on a large language model.
- Tactical loop: asynchronous vision/strategy proposals consume timestamped game evidence. If stale, abstain rather than act.
- Streaming loop: small event-based speech director with speech cooldowns, prioritized viewer replies, genuine interrupt/cancel handling and no speech during critical mechanics.
- Offline/night-school loop: heavier coding, research, multi-candidate verification and training only when GPU/CPU headroom is verified.
- Hysteretic hardware governor: avoid rapid model swaps; reserve VRAM and CPU capacity for game, avatar, OBS and TTS. Pause background tasks on rising game frame-time or recording drops.

Baseline repeated trials: **TTFT p50/p95, correct-action p95, game FPS/1% lows, TTS first audible chunk, audio dropouts, OBS dropped frames, CPU/VRAM/RAM peaks, error and abort rate**. Compare identical model files/prompts/context, thermal conditions and workload duration. Record test host & timestamps. No benchmark numbers are inferred from marketing.

Relevant tools:
- llama.cpp SPEED-Bench measures server throughput, latency, category results and draft acceptance. Treat speculative decoding as conditional; extra models may compete for memory and decrease total throughput: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md
- Kyutai Pocket TTS (October 20, 2026) added 18.2M, 6.9M and 1.9M English CPU models. Their published performance is not a STAR result. Benchmark quality/CPU contention and consent rights before selecting one: https://github.com/kyutai-labs/pocket-tts
- Cache immutable project instructions and verified tool outputs by content hash; don't let long-context memory contain secret keys or stale game state. Stream partial responses without converting low-confidence text into OS actions.

## 4. Humanlike, expressive but honestly AI VTuber

Goal: high-quality **natural social behavior**, not a claim that STAR is biologically human or conscious. Maintain consistent fictional persona and persistent projects, while labeling autonomous synthetic performance honestly.

Natural interactive pipeline: capture -> game/chat relevance -> interruptible response scheduler -> streaming ASR/TTS -> audio-anchored mouth/eyes/gesture timing -> OBS/virtual microphone. Separate gameplay action scheduling from speech timing so a witty line never delays a dodge.

Research anchors:
- Microsoft Proact-VL (ICML 2026) demonstrates deciding *when* to speak and limiting generated commentary under real-time constraints: https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/
- NVIDIA DyaPlex (June 2026) studies streaming synchronized speech/body motion and responsive partner backchannels; research reference, NOT suitable-for-8GB evidence: https://research.nvidia.com/labs/amri/publication/nagano2026dyaplex/
- NVIDIA PersonaPlex studies full-duplex interruptible dialogue, but its actual resource requirements and license need a separate host evaluation: https://github.com/NVIDIA/personaplex

Humanlike behaviors to implement incrementally: expressive pause distribution; reactive laughter only when context justifies; short backchannels; stop-talking on game danger; believable eyes/blinks and voice-to-viseme mapping; consistent ongoing interests; memory of actual witnessed game events; viewer turn-taking; playful comments with context; optional human-host handoff; cooldown on speaking. Avoid hallucinated achievements, fabricated relationships and unauthorized voice cloning. Streamer mute, emergency stop, consent, safety moderation and **never public broadcast during a rehearsal**.

## 5. Game development and broader knowledge

Roblox OpenGameEval's **October 2026 paper** studies 84 curated Studio tasks and independently checks both edits and simulated play; inspection before editing correlates with higher success:
https://arxiv.org/abs/2610.02563
https://github.com/Roblox/open-game-eval

Roblox **November 4, 2026** Studio MCP update adds permission-scoped Open Cloud functionality to the same client (analytics, assets, products, settings and publishing). This is a potential external-action risk, not implicit permission:
https://devforum.roblox.com/t/studio-mcp-server-updates-open-cloud-access-in-your-mcp-client-and-asset-import-workflows/4975849

Recommended STAR creator pipeline: inspect place and dependency map -> generate *multiple* Luau/scene candidates -> run luau-analyze/selene/StyLua/Jest-Lua where relevant -> choose individually passing builds -> execute Studio playtests and visual QA -> preserve semantic diff and rollback -> require owner approval for publishing, monetization, user communications, or irreversible external writes. Feed approved independently verified examples to a local searchable skills vault with dated provenance. Use Star's local Core Forge as source of truth and GitHub for review/export.

Broaden the skill tree to **Rust/Python/TypeScript/Luau**, Blender/Blockbench asset workflows, 2D/3D composition and rendering QA, audio/animation/VFX, web development, desktop productivity, debugging, privacy-aware knowledge retrieval, moderation, social conversation, and general educational Q&A with citation/freshness checks. Multi-agent workers should share bounded immutable job specs, resource budgets, and a verifier; a conductor must not mark an item complete from a worker's claim alone.

## 6. Honest next acceptance milestones

1. **This PR (offline):** signed-movement rehearsal on hidden synthetic grids, independent scorecards and adversarial tests. It is not a real game, model training or streaming.
2. **Private process-separated game host:** source-signed ground truth from a pinned, owner-controlled engine, authenticated IPC peer, and post-action movement receipts. Simulate corruption, input denial, lost focus, and stale frames; require fail-closed stop.
3. **Windows private (no broadcast):** test actual game + OBS recording + Star avatar + audible TTS on target GPU. Measure synchronized end-to-end timestamps and stable FPS under 15+ minutes of load.
4. **Verified improvement:** compare to fixed baseline on heldout tasks, including mistakes and dropouts; promote improvements only if reliable accuracy and end-to-end latency meet preregistered thresholds.
5. **Public streaming later:** separate explicit permission and moderation review; no autonomous public go-live from private lab success.

### Strictly not established
These changes do not increase model weights/intelligence, install a new TTS model, deliver a neural speedup, make STAR conscious, prove a real win, press real game keys, or operate OBS. They provide a necessary measurable integration step toward those goals.
