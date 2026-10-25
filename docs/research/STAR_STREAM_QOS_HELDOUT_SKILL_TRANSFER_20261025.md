# STAR research: realtime performance and trustworthy skill transfer
**Research snapshot:** 2026-10-25. **Status:** source-checkout prototypes, not deployed or merged.

## Why this increment

STAR already has draft components for VTuber moment memory, stream prioritization, movement navigation, and closed-loop toy-game rehearsal. Two gaps remain:

1. Gaming/voice/rendering/research can compete for limited GPU headroom. Without a real-time scheduler that honors observed pressure, running a larger reasoning model can make streams worse, not better.
2. A skill that succeeds repeatedly in practice may still be memorizing familiar situations. STAR must not market repeat attempts as independent generalization, or silently adopt an unvalidated strategy.

This PR adds both an offline QoS **advisory governor** and a separate held-out **skill promotion evaluator**. The two components are independent of the other open PR branches and can be reviewed on star/next. Neither is activated by default. They do not require new packages.

## Implemented A: StreamLoadGovernor

Module: star/stream_load_governor.py.

The host supplies one atomic StreamSample: a monotonically sequenced timestamp, whether game and stream are active, 10th-percentile game FPS, p95 time to spoken output, dropped OBS-frame percentage, free VRAM and audio underrun count. The client adapter must independently measure these; user text or model self-reports are NOT telemetry.

Observe immediately enters pressure mode for low FPS, slow speech, lost OBS frames, audio underruns or VRAM stress. Multiple healthy windows are required before recovery to avoid thrashing. Cold start, stale samples and replayed telemetry fail closed. A WorkRequest identifies only seven allowlisted workload classes. The governor recommends whether a host-approved job may run, reserves VRAM headroom and returns a coarse vision sampling stride and token ceiling. It never launches anything, touches OBS, calls a GPU backend, or grants access rights.

### Host integration contract

- An *already owner-approved* host adapter must decide which jobs exist and what permissions they have. The advisory boolean is not authorization.
- A monotonic clock and trusted, bounded telemetry are mandatory; sample and request timestamps must share the same monotonic epoch.
- During gaming/streaming, suppress research, night school and asset rendering (never kill unknown third-party processes). Host determines safe suspension/resume boundaries.
- Prioritize interactive voice, game control, game vision and chat; handle slowdowns by reducing *optional* vision frequency and the length of commentary, not by fabricating missing observations.
- Do not log video, chat transcripts, gameplay frames, microphone recordings, passwords or process names in the governor.
- The policy defaults are hypotheses, NOT calibrated to the user's 8-GB GPU or evidence of improved performance. Benchmark before selecting production thresholds.
- A missing/late telemetry heartbeat must stop admission. This can temporarily reduce availability but prevents silently scheduling expensive work based on old stats.
- Interactive job admission does not ensure frame deadlines are met. The actual scheduler needs real OS queues, quotas, cancellation and tracing.

### Proposed measurements and acceptance

Collect baseline vs governor **on the same scene, renderer, game seed, model and server**. Record median/p95 time-to-first-audible voice; OBS dropped frames and encoder lag; 1% low game FPS; GPU peak allocated/used VRAM; audio underruns; number/duration of delayed research tasks; chat reply omission rate; power and memory headroom. Measure the cost of extra telemetry samples. Use repeated interleaved A/B windows and publish confidence intervals. Reject rollout if responsiveness, visual fidelity or crash recovery regresses.

Suggested test matrix: no stream; game only; stream only; game + stream + avatar; cold start; disconnected second computer; microphone interruption; new gaming scene; high GPU load; full context cache; low VRAM; model error; excessive chat. For 8-GB cards, first benchmark small quantized voice/chat models before attempting simultaneous large vision and asset models.

## Implemented B: SkillPromotionGate

Module: star/game_skill_promotion.py.

The host submits an immutable SkillTrial containing game, skill, model/skill revision, session, environment, scenario digest, declared practice/holdout split, and independent pass/safety verdict. The gate permits only one trial per scenario and one per session for each version, and **forbids reuse of a scenario across revisions** for the same game/skill. It separately counts held-out trials across multiple environments and computes a conservative Wilson success lower bound.

A skill can reach status ready_for_owner_review only after enough distinct held-out trials and environments, adequate conservative success, and zero observed unsafe trials. This status does NOT mean automatic promotion, general intelligence, or a guarantee of success. A failed or unsafe held-out attempt cannot be edited away. Any new skill revision must establish new evidence.

### Critical trust boundaries

- Holding out is a real process, not a string label. Independently reserve scenario IDs *before* the model sees them; prevent model access to seeds, outcomes and holdout prompts until the fixed revision is frozen.
- Verify observed outcomes with host scoring, not model narration or chat. A SHA-256 digest identifies a scenario but is not an authenticity certificate.
- Use independent test sessions and multiple environments; watch for test-distribution shortcuts, seed overfitting, shortcut learning and too many correlated runs.
- The trial register is bounded in memory, not crash-safe, tamperproof, append-only on disk, or distributed. Build a host-authenticated durable evidence journal with structured schema migration before live use.
- If the owner changes the skill code or the model revision, retest before recommendation. A holdout audit must require sealed source-of-truth run logs.
- This is a *candidate selection gate*, not RL, model fine-tuning, a trainer or proof of general-game competence.

## Near-term STAR intelligence architecture

A working full game player requires an evidence-carrying loop:
  Host video/game events -> state hypotheses with uncertainty -> bounded action proposals -> permissioned host execution -> independent next-frame verification -> outcome journal -> isolated practice curriculum -> held-out skill gate -> owner review -> versioned skill library.

Design each link as a separately testable adapter. No claim of "eyes" should depend only on an LLM saying it saw something. For perception, compare visual detection against host telemetry where possible, track occlusion and uncertain positions, and abstain rather than invent an action. Use controlled practice places and games where automation is permitted, not uncontrolled public games.

For game making, pair builder output with constraints: object ownership and coordinate frames; collision/overlap checks; walls connected to foundations; props placed within bounds; texture UV/material checks; style consistency; render screenshots inspected from multiple cameras; deterministic test-place playtests; performance budgets; and human evaluation of visual polish. Favor editable native Roblox UI and well-structured meshes over random placeholder parts. Keep all changes in sandbox places until verified.

For general knowledge, keep three stores distinct: (i) cited source facts with provenance/date/license and validity windows, (ii) verified executable skills with tests and tool versions, and (iii) per-session memories with expiry and privacy controls. Route retrieval on demand rather than stuffing every source into the model prompt. Disagreeing sources should retain separate claims instead of being averaged into an invented answer. Use a held-out question set with time-split topics, answer-with-citations scores and abstention accuracy. More documents in a cache do not change model weights or imply higher reasoning intelligence.

For autonomous learning, use a candidate-generation phase and an independent verifier, then compare new vs baseline on unseen tasks. Track first-pass task success, corrected success, error recovery, real tool cost, tokens, wall-clock latency and VRAM. Keep feedback loops offline/default-off, never train on the protected holdout test set, and never auto-merge into main. For source-license compliance, inventory permitted datasets, art, music and video inputs before ingest.

## Humanlike but transparent VTuber

Treat STAR as a fictional AI character with a stable persona, not as a human impersonation. The distinction improves trust: she can be lively, spontaneous, embarrassed, funny and emotionally expressive while clearly identifying herself as AI. Fictional backstory/lore should be distinguishable from real-life experience.

### Realtime voice and conversation

- Use a full-duplex audio pipeline with interruption and backchannel detection, echo cancellation, foreground/background acoustics, tight VAD/ASR/TTS chunking and cancelable playback.
- Stream-first objective: low audible response latency **and** intelligible audio without game-FPS drops. Measure p50/p95 by room noise and speaking overlap; benchmark on actual local hardware.
- PersonaPlex research supports role- and voice-conditioned full-duplex behavior, but size, licensing, hardware support and quality require inspection before any integration. Do not claim its reference demonstration runs on an 8-GB card.
- Make commentary grounded in recorded game events: failures, clutch wins, recovered mistakes, chat callbacks. Never announce a victory before authoritative success is observed. Allow silence during concentrated gameplay.
- Maintain consent boundaries for voice and audience interaction; no disclosure of private server messages, owner secrets or direct-person impersonation.

### Expressive avatar, animation, production

- Use aligned phonemes/visemes, eye gaze, blinks, micro-head motion, breaths and emotion intensity curves; hair, ears and tails should use spring/damping physics rather than random oscillation. Cat/puppy variants retain the same character identity.
- Connect only a permissioned local animation adapter to VTube Studio's injected parameters. A genuine rig with actual art/meshes is still required; parameter events alone do not construct a rig.
- DyaPlex research explores synchronized bidirectional speech-motion, but it is not integrated here. Evaluate deterministic procedural animation first to preserve FPS.
- For OBS, prefer authenticated obs-websocket stats and only locally approved commands. Keep broadcast start/stop/manual privacy guards independent of the model.

### Stream director behavior design

During high action: game and voice essential, optional comments short, chat sampling sparse. During safe downtime: longer conversation, stories about **documented in-stream** events, and chat participation. During an interruption: cancel stale audio/captions/animation, acknowledge briefly and resume context. During failure: note uncertainty, do not pretend to understand unseen events. Reactions should be expressive and varied without excessive forced laughter or repetitive filler.

## Hardware and inference research priorities

- Model routing: a small low-latency chat/voice model for reactions, a stronger slower reasoner for off-stream planning, and periodic vision at a rate controlled by actual GPU pressure. Parallelism is useful only if the processors and memory budgets permit it.
- Prefix/KV caching: benchmark repeated system prompts, static style guides and skill-index prefixes; invalidate cache on tool change or scope/permission change. KV caching can reduce redundant prompt computation, not improve reasoning by itself.
- On 8-GB GPUs, quantize carefully and measure loss on game understanding; avoid assumptions that INT4/FP8 optimizations for newer accelerators will be available on RTX 3060 Ti or 4060.
- The owner-directed Brain 1 server and Brain 2 Studio machine should communicate through authenticated, scoped services with backpressure, not shared mutable raw prompts or permissive shell commands. Reconnect/replay idempotently after outages and keep jobs cancelable.
- Avoid over-promising zero-latency speech, "smarter than every model" or simultaneous 3D rendering and high-FPS gaming. Prove each improvement on reproducible real tasks.

## Reproduction and review

    PYTHONPATH=. python -m unittest discover -s tests -p test_stream_load_governor.py -v
    PYTHONPATH=. python -m unittest discover -s tests -p test_game_skill_promotion.py -v
    python -m compileall -q star/stream_load_governor.py star/game_skill_promotion.py

Both modules are pure Python 3.11+ and are **not wired to live OBS, Roblox, GPUs or the model** in this PR. Locally, 49 deterministic targeted tests passed, covering hysteresis, stale telemetry, replay, vRAM reserves, authorization assertions, skill data leakage, conservative lower bounds and skill version isolation. Full-repository CI, hardware benchmark, owner adapters, persistency and actual streaming tests are separate release gates.

## Verified external research references

- Google DeepMind, SIMA 2 (Nov 2025): https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/
- Google DeepMind, AI games research (Aug 2026): https://deepmind.google/blog/from-atari-to-eve-online-building-on-15-years-of-ai-research-in-games/
- Voyager / automatic curriculum and skill library: https://arxiv.org/abs/2305.16291
- DreamerV3 world models: https://github.com/danijar/dreamerv3
- NVIDIA TensorRT-LLM attention, batching, cache: https://nvidia.github.io/TensorRT-LLM/features/attention.html
- NVIDIA PersonaPlex full-duplex audio: https://research.nvidia.com/labs/adlr/personaplex/
- NVIDIA DyaPlex speech-motion synchronization: https://research.nvidia.com/labs/amri/projects/DyaPlex/
- OBS WebSocket and authentication: https://github.com/obsproject/obs-websocket
- VTube Studio parameter API: https://github.com/DenchiSoft/VTubeStudio
- Roblox official Studio MCP documentation: https://create.roblox.com/docs/studio/mcp

**Next development milestone:** integrate an authenticated telemetry collector and non-executing QoS log in a private offline rehearsal; independently capture p95 audio latency, p10 FPS and encoder drop rate; prototype a host-scored, genuinely sealed gameplay holdout suite. No merge to main, no default-on control, no broadcast or owner-PC deployment without review.
