# STAR — independently witnessed risk-aware play and generalist VTuber research

**Research and implementation date:** 2026-11-05. **Scope:** private, offline, synthetic signed maze trial. **Deployment:** none; not connected to Windows input, OBS, Twitch/YouTube, live game telemetry, a model backend, or autonomous training. **Relation:** stacked on draft PR #1003 (signed closed-loop synthetic maze lab).

## 1. Why this code change matters

The prior maze lab measured reaching a destination and movement efficiency. A test agent could reach the goal after walking into *dangerous but legal* terrain, yet the score reported only movement count; it could also not rehearse engine-fatal terrain distinct from a solid wall. This is the wrong objective for learning to play survival, platforming, racing, or combat games: reaching a checkpoint while repeatedly losing health can be worse than a slower, safe route.

This patch adds two synthetic terrain types. `!` is traversable terrain with a lethal risk marker (`risk_bps=10000`) that the independent engine rejects as an action, while `~` is allowed but incurs **6,000 synthetic risk-exposure basis-point units per entry**. These are abstract test metrics, *not health points or observed harm*. The private engine keeps the whole map; STAR only receives the signed, local cross-view with risk flags. `GroundedNavigationMemory` already supports risk-aware Dijkstra routing and blocks risk >=7,500; this integration now exercises it in a real closed-loop synthetic scenario.

What is scored: separately witnessed objective, raw moves, BFS shortest path on engine-legal terrain, risk exposure, risky-tile entries, invalid moves, frame budget and source revocation. A longer but exposure-free route can score **lower geometric efficiency** and still be the **better survival policy**. We do not collapse these trade-offs into a single misleading 'intelligence' score. Individual failures remain visible in the batch API. `~` is optional; the old `# . S G` maze cases remain valid and preserve their legacy outputs apart from new zero-default score fields.

**Exact tests:** lethal trap hidden behind a visible corridor, risky shortcut avoided despite extra steps, unavoidable exposure reported, multi-trap alternate route, unreachable safe path rejection, invalid terrain glyphs, owner opt-in, bounded frames, synthetic score consistency, and no key/session in result objects. See `tests/test_signed_hazard_maze_lab.py`. This does not prove STAR can act in any real game, avoid moving enemies, or evaluate risk from screenshots. It also does not improve neural model weights or inference throughput.

## 2. Research-backed priorities (ranked by practical impact)

### A. Learn game mechanics from genuine action consequences

Google DeepMind's **SIMA 2 (November 13, 2025)** describes language-directed play, reasoning and iterative learning across 3D worlds. STAR's feasible local-first interpretation is a two-speed system: a *fast verified-control loop* for movement, health and collision avoidance, and an *asynchronous slower planner* for discoveries, long-term strategy and explanations. The slow loop must never block the fast controller from avoiding immediate hazards. The next game experiments should add moving hazard schedules, limited lives, death/retry costs, inventory constraints and enemy attacks in **independent game-state simulators**, not self-scored LLM text.

**GameWorld (April 8, 2026)** supplies a better reality check: 34 diverse games with 170 state-verifiable tasks; its GameWorld-RT variant allows the environment to continue evolving during inference. **Gym-Anything-RT (October 27, 2026)** specifically finds large gaps between paused and real-time minigames. Thus STAR should publish separate paused and real-time win/health/resource metrics plus p50/p95 action latency. *Do not* claim competence from a simulated paused puzzle alone.

**RT-SAFE (October 7, 2026)** is an embodied-safety benchmark, not a video-game benchmark. Its insight still transfers: when the world changes between observation and action, an apparently safe action may no longer be safe. The next signed lab must revalidate hazards at the action boundary rather than equate packet authenticity with freshness of all game objects. Add one-frame and multi-frame hazard motion with held-out seeds and clear death events. A cryptographic signature proves packet integrity under a trusted-key assumption; it **cannot** make a lying or compromised game reader trustworthy.

### B. Better Roblox game creation and verification

**Roblox OpenGameEval (October 2026)** evaluates changes to *actual Studio state* and simulated play sessions on 84 curated tasks, and reports higher success when agents inspect the relevant objects before acting. For STAR, define a gated loop: snapshot scene and output logs -> identify target instances -> generate Luau/Rojo edits -> static analyses (`luau-analyze`, Selene, StyLua) -> isolated Studio playtest -> run player assertions -> inspect screenshot and logs -> bounded repair -> only then promote an artifact. Record snapshots, diffs and test receipts locally in Star Core Forge; GitHub is a publication option, not the only state store.

**Roblox Studio MCP's November 4, 2026 expansion** adds Open Cloud actions such as asset imports, monetization, game settings, publishing, and analytics with permission controls. Treat read-only exploration, local staging writes, and production/publishing as distinct capabilities. An unattended experiment must never inherit publishing or monetization rights. Never enable new externally effective permissions by default.

### C. Actual responsiveness and hardware throughput

Measure full *event-to-action* and *chat-to-audible-response* latency, not just tokens/sec. Separate queue wait, vision capture/preprocess, small policy decisions, large reasoning, TTS first audio, avatar cue, and OBS output. At the 8 GB GPU class, choose testable budgets: a single resident model during gaming, CPU-optimized voice if quality is sufficient, smaller context windows and prefix caching. Run each model with a warmed and cold cache, and alternate gameplay/social/coding tasks to detect benchmark leakage. Keep FPS, VRAM pressure, VRAM headroom, dropped OBS frames and task correctness alongside p95 latency.

**llama.cpp SPEED-Bench** supports category-specific OpenAI-compatible server timing, throughput and speculative-decoding acceptance; improvements should be gated on complete-task outcomes. Speculative decoding may be slower depending on model, draft acceptance, VRAM pressure and hardware; turn it on only after paired testing.

**Kyutai Pocket TTS update (October 20, 2026)** reports smaller 18.2M, 6.9M and 1.9M parameter models with measured single-thread CPU speed/quality tradeoffs. This is a useful *candidate*, not a measured benefit on STAR's Windows machines. Benchmark audible latency and naturalness in a private local recording, and avoid reallocating VRAM from the game on assumption alone.

### D. Natural, humanlike-but-truthful VTuber behavior

**Proact-VL (ICML 2026)** demonstrates that a companion must decide *when* to comment, not simply continuously produce text. **NVIDIA PersonaPlex** researches full-duplex voice including interruptions, backchannels and conversational rhythm; **NVIDIA DyaPlex (June 2026)** adds coordinated speech-motion research. These do not establish that their particular implementations will run fast on STAR's GPU. STAR should stage a private demo that measures interruptions, silence, hallucinated game claims, speaking over important gameplay, and mouth/eye/gesture delay.

Maintain a persistent **persona and preference model** with user-editable boundaries and episode-scoped memories of *verified* achievements, corrections, jokes and other events. STAR can express excitement, surprise, uncertainty, curiosity, jokes and playful social rituals without pretending to be a literal human or inventing memories. Require a witnessed game event for claims such as 'I won that match'; otherwise use uncertain wording. Viewer moderation, per-user consent, anti-spam/rate limits, license-compliant voice samples, and secure chat integration are part of a professional VTuber, not optional polish.

### E. General knowledge and autonomous skill growth

Use a verified retrieval and practice loop across Python, Rust, Luau, C#, Blender, video, editing, history, math and general knowledge. Each learned lesson needs source attribution, testable worked examples, a confidence/freshness score and failure cases. For programming, prefer run-and-repair and passing tests; for factual claims, cite primary sources and let knowledge expire if time-sensitive; for 3D/visual art, use image inspections and geometry checks. Never promote self-generated text directly into long-term authoritative facts. Track retention on held-out tasks and regression failures, not number of notes generated. Schedule intensive practice when streaming is idle and GPU/CPU admission checks pass.

## 3. Reproducible evaluation and next real milestone

1. **Offline:** run `PYTHONPATH=. python -m pytest -q tests/test_signed_hazard_maze_lab.py tests/test_signed_maze_lab.py` with no network/keys. Confirm separate geometric efficiency and risk exposure results, plus failed runs at small frame budgets.
2. **Host integration:** trusted Windows capture reads game events and signs *only approved, verifiable observations*. Validate episode/version/source identity, freshness, monotonic sequence, action acknowledgments and revocation on session change. Reject unsigned screenshots as hard evidence of wins.
3. **Private exercise:** approved test game + input worker + OBS **recording only** + avatar + low-cost TTS; collect 10+ minutes of game FPS, audio timing, OBS dropped frames and GPU load. Do not go live or edit production games.
4. **Blind evaluation:** train/tune on development maps; evaluate held-out games and maps with novel hazards, moving entities and resource constraints. Report number of successes *and* deaths, risk exposure, response latency and work skipped due to resource pressure. Failures cannot disappear from averages.
5. **Promotion:** require an independently witnessed paired improvement with no regressions in critical tasks, explicit version pinning, existing signed/cohort-once evaluation controls, and rollback. Manual owner approval for high-impact deployment or broadcasting; low-risk lab research can remain autonomous under established controls.

### Primary references and release dates

- Google DeepMind SIMA 2, 2025-11-13: https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/
- GameWorld, 2026-04-08: https://arxiv.org/abs/2604.07429 ; project: https://gameworld-project.github.io/
- Gym-Anything-RT, 2026-10-27: https://arxiv.org/abs/2610.37567
- RT-SAFE, 2026-10-07: https://arxiv.org/abs/2610.09294
- Roblox OpenGameEval, 2026-10-01: https://arxiv.org/abs/2610.02563 ; https://github.com/Roblox/open-game-eval
- Roblox Studio MCP update, 2026-11-04: https://devforum.roblox.com/t/studio-mcp-server-updates-open-cloud-access-in-your-mcp-client-and-asset-import-workflows/4975849
- llama.cpp SPEED-Bench README (retrieved 2026-11-05): https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md
- Kyutai small Pocket TTS, 2026-10-20: https://kyutai.org/blog/2026-10-20-pocket-tts-small/
- Proact-VL, ICML 2026: https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/
- NVIDIA PersonaPlex (2026): https://research.nvidia.com/labs/adlr/personaplex/
- NVIDIA DyaPlex, 2026-06: https://research.nvidia.com/labs/amri/publication/nagano2026dyaplex/
