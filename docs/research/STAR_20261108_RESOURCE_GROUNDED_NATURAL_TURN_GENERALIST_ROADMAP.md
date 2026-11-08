# STAR — Resource-grounded conversational intelligence and measurable VTuber game learning
**Research checked:** 2026-11-08. **Branch:** `feat/star-natural-turn-resource-admission-20261108-auto166`.
**Status:** implemented opt-in planning integration and offline tests; not a Windows TTS, OBS, or streaming deployment.

## Discovery: a real integration gap, not another speculative model upgrade

`StreamLoadGovernor` already classified independently measured game FPS, OBS
render/encode/network drops, GPU VRAM and TTS first-audio delay. The
`StreamDirector.propose(load_advice=...)` method already suppresses lower-value
speech during congestion. But `NaturalTurnBridge.advise()`, the coordinated
VAD/event-priority/PCM-stop planning path, **never passed that advice**.
Consequently an embedding host using this bridge could still prepare needless
commentary during OBS overload and spend extra model/TTS resources.

This change adds optional **`load_governor: StreamLoadGovernor`** at bridge
construction. On each otherwise eligible speech decision the bridge asks the
trusted governor for a fresh recommendation, using the SAME host monotonic clock
(ms in bridge, s in governor), and supplies it to the existing director. Missing,
disabled, stale, warming, critical, or disconnected telemetry holds ordinary
viewer comments/questions and ambient narration according to director policy;
observed host *danger* and *owner interrupt* events remain candidates for review.
Constrained load filters ambient, viewer comments, and game observations. An
invalid/reversed resource clock fails quiet and invalidates the prepared plan.

The governor is passed as an actual host-owned object, never copied from model,
chat, webpage or game text. Neither this module nor the governor performs TTS,
OBS, keyboard, avatar or network operations; advisory decisions explicitly
**do not authorize playback or broadcast**. Legacy callers without a governor
keep their existing opt-in behavior. The trusted Windows host must supply
authenticated OBS/game observations and recheck every turn immediately before
TTS handoff. Physical audio stop/drain and avatar reset remain separate.

## Why this matters for latency, quality, and naturalness

During an active game + OBS session on an 8 GB VRAM GPU, adding an optional
vision/LLM/TTS task can worsen presentation time, delay game input, and drop
video frames. A good VTuber does not narrate continuously: **silence is a valid
result** when the player is reacting, the game is hard, or rendering is behind.
The goal is better **capture→decision→action** and **event→audible-response**
latency at stable game FPS, not to maximize generated words or tokens/sec.

This branch introduces no model speed claim. Savings are conditional: the
optional host must attach the governor and the stream must actually be under
pressure. Regression tests confirm the dispatch decisions but no measured
GPU, game FPS, audio, or streaming gains yet.

## Primary research, with engineering translation

1. **Gym-Anything-RT**, Aggarwal & Welleck, published 2026-10-27,
   https://arxiv.org/abs/2610.37567 — 100 real-time minigames; performance in
   paused environments should not be reported as actual live play. Build two
   test modes, paused and realtime, on the same novel seeds and report both.
   Shift fast actions to separately admitted, short-deadline workers; reserve
   long deliberation for safe off-game practice.
2. **Proact-VL**, Yan et al., 2026-03-03,
   https://arxiv.org/abs/2603.03447 — real-time companion evaluation must
   jointly score response *timing*, *quality* and *quantity*. For Star, test
   `speech-worthy event` vs silence, interruption timing, relevance and
   false narration, not just fluency.
3. **OpenGameEval**, Roblox research, published 2026-10-01,
   https://arxiv.org/abs/2610.02563 — 84 Studio tasks with executable checks;
   inspection-before-edit correlates with greater success. Maintain an
   inspect→patch→playtest→verify chain with immutable evidence per game version.
   Do not award self-authored reward for unverified edits.
4. **Roblox Studio agentic planning & testing**, official 2026-04-15,
   https://about.roblox.com/newsroom/2026/04/roblox-studio-going-agentic
   and official built-in MCP playtest tools,
   https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643 —
   plan/edit/playtest through authorized Studio instances, independent test
   assertions and a versioned rollback. Game-playing permission is distinct
   from publishing or editing public experiences.
5. **llama.cpp speculative decoding**, documentation checked 2026-11-08,
   https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md —
   draft and n-gram approaches are available; decode speed only matters if
   added VRAM/CPU cost does not worsen OBS/frame times. Pin exact model,
   quantization, context, batch parameters, backend and build for A/B trials.
6. **llama.cpp prompt-cache isolation report #27148**, opened 2026-08-15,
   https://github.com/ggml-org/llama.cpp/issues/27148 — an issue reports
   cross-conversation cache restoration in certain builds/configurations.
   This is *not* confirmed in STAR. Until locally verified, isolate public
   streamer context from owner/private context, and avoid shared-slot
   cross-tenant prompt caches; use a red-team canary test.
7. **Kyutai Pocket TTS**, October 2026 smaller CPU models,
   https://github.com/kyutai-labs/pocket-tts — official README lists 18.2M,
   6.9M, 1.9M English variants and streaming CPU inference. Benchmark with
   the game+OBS already running; compare voice naturalness and CPU frame-time
   cost, not just synthetic first chunk speed.
8. **VRM 1.0 expressions**, official specification,
   https://github.com/vrm-c/vrm-specification/blob/master/specification/VRMC_vrm-1.0/expressions.md —
   supports expressions, five lip-sync phoneme presets, blink and gaze;
   overrides prevent mouth/eye geometry conflicts. A visually natural Star
   needs PCM-timed phonemes, subtle gaze/saccades, blink variance, gesture
   holds, reaction backpressure, and reduced-motion settings.
9. **Roblox September 2026 creation roadmap**,
   https://about.roblox.com/newsroom/2026/09/rdc-2026-the-world-needs-more-play —
   orthographic cameras, sprite-sheet import and animated image containers
   are relevant to Star's 2D/pixel-game generation practice. Verify feature
   rollout status against the specific Studio build rather than assuming
   each announced capability is enabled.

## Sequenced engineering plan (scope and acceptance measurements)

### Stage A — live resource admission (this branch)
- Wire a real `StreamLoadGovernor` from the trusted Windows host into
  `NaturalTurnBridge`; confirm OBS stats are recent interval deltas, not
  counter totals or model-reported FPS. Match monotonic clock epochs.
- Record host-only aggregates: normal/constrained/critical transitions,
  prepared-to-canceled turn counts, optional TTS launch count, speech
  first-audio p50/p95, game FPS p1/p5, OBS render misses/encode skips,
  GPU/CPU headroom, discarded stale VLM frames and owner interrupt latency.
- A/B offline: same gameplay replay and predeclared trace under governor ON vs
  OFF, ≥30 minutes *private, nonbroadcast* per arm, alternate run order.
  Verify expected gating, no starvation of legitimate owner/danger events,
  no regressions of VAD/PCM physical-stop barriers, and no unexpected speech.
  Treat performance improvements as unproven until hardware results exist.

### Stage B — real game mastery, not hypothetical mastery
- Reset one whitelisted Studio game to independent scenario IDs; randomize
  strategy assignment before outcomes using the existing
  `game_paired_study` and signed `GameplaySkillBank` rather than
  grading STAR's own descriptions of success.
- Track first-action latency, key-release confirmation, game-state receipts,
  success, deaths, unverified trials, collisions and unseen-seed win rate.
  Keep evaluation holdout hidden until all actions and predictions freeze.
- Train/retrieve skills only from independently authenticated practice
  observations, require unseen-game-version transfer before promoting.
  A model guessing a win does not count. No public-game automation that
  violates a game's terms; prefer private/test realms and owner games.

### Stage C — genuinely convincing, AI-transparent streaming
- Keep an explicit personality/style sheet plus editable per-show goals,
  a consented stream-memory journal and verified audible speech ledger.
  Do not label intended TTS as spoken until native device playback confirms.
- Tie reaction priority to trusted game states; only give victory gestures
  on signed game outcomes. For visual-only cues use uncertainty language.
  Leave room for quiet, avoid reading every chat line, and timestamp delayed
  responses so stale events are not narrated as immediate.
- Drive blink, gaze, head tilt, smile, mouth/visemes and idle motion from
  actual audio and game events. Cap movement; respect reduced-motion.
  Never claim Star is biologically human or has verified consciousness.
- Include moderation, personal-data redaction, viewer boundaries, copyright
  and disclosure that Star is an AI character.

### Stage D — generalist intelligence and autonomous game creation
- Build separate dated, attributable document knowledge; episodic memories;
  verified motor skills; and executable code/tool skills. Retrieval must
  distinguish `observed`, `source-supported`, `inferred`, `unknown`.
- Allocate coding/model-thinking budget adaptively: small fast planner for
  simple routing, stronger model for difficult design/reasoning outside game
  deadlines, and test-and-repair with code/Luau static checks and Studio
  screenshot/playtest verification.
- Expand private creativity exercises: Roblox scenes/2D pixel games, Blender
  props, lighting, animation, procedural sound, UX and stream production.
  Assess artifacts through build/tests, geometry and render comparisons and
  randomized human assessment, not model self-praise.

## Explicit limitations / release gate

These changes were verified by deterministic Linux offline unit tests only.
No local 8 GB GPU inference benchmark, Windows audio/OBS integration, visible
VTuber animation or real game-skill improvement was carried out by this patch.
Do not merge chained draft branches to `main` or enable broadcast implicitly.
Accept a live trial only after a human-reviewed private rehearsal and actual
measurement of rendered-frame health, voice latency, player input safety,
memory privacy and held-out task success.
