# STAR: grounded game action, real-time intelligence, and natural VTuber systems
Research + engineering notes — 2026-10-25

## Executive engineering decision

The bottleneck is not another personality prompt. STAR already has a verified
practice evidence bank, an active practice planner, a streaming director,
observation governor, persona/motion staging, turn-taking, and deadline-aware
resource advice. The missing join is an **independently trusted observe → decide
→ input → verify** loop that can be stopped safely, and real measurement of
compute performance *under game load*, not simply in a quiet benchmark.

This change supplies two code-level building blocks, not a new foundation
model or a working game player:

1. `star/game_action_gate.py`: single-pending, short-expiry, owner-scoped
   symbolic game-input decision protocol. LLM hints are never executable
   keyboard instructions. Frame digest/sequence binding, monotonic time,
   confidence threshold, focus checks, curated actions, per-minute budget,
   one-shot claims, key-release quarantine, and thread-safety close common
   replay and runaway-input mistakes. It **does not send keys** or obtain
   permissions.
2. `star/stream_qos.py`: latency profiles are now separated between idle and
   game-active resource regimes. Old measurements expire after 120 seconds.
   Previously five fast idle measurements could wrongly certify a live game
   vision model's deadline. That path is no longer valid without game-load
   measurements. This protects frame time; it does **not** accelerate inference.

## The complete system STAR still needs

### Sensory perception / 'eyes'

Use an authorized host to acquire (1) screenshots/video frames and delta
frames, (2) accessible game HUD/objective/state when available, (3) game audio
event cues, (4) trusted engine logs and collision/game-state telemetry, and
(5) source labels and independent evidence digests. STAR's
`stream_observe.py` only schedules novelty sampling from host-provided frame
cues: perceptual hashing is **not** proof that an object was understood.

Scene comprehension should use a short-lived **belief state** rather than an
unbounded transcript: current objective, entities with tracking IDs, visible
hazards, menu/focus, control scheme, uncertainty, current ability cooldowns,
expected next observation, and a strict expiry. Separate perceptual
observations from guesses, game rules, chat, and instruction-like text found on
the screen. A hallucinated GUI label must never become a privileged command.

### Actions and skill improvement

1. Observe with owner-approved capture, attach sequence + SHA-256 digest;
   accept a hint only for exactly that fresh frame.
2. An evaluator chooses from an owner-curated symbolic action vocabulary.
   Any OS key map lives **only** in a trusted host adapter; never accept
   generated Lua, shell, Discord, remote commands, or arbitrary keyboard keys
   as proposed gameplay input.
3. The new gate checks owner session, focus, confidence, game/episode scope,
   staleness, rate, and key-hold bound, then issues a one-shot ticket.
4. The host rechecks game foreground/focus, engine/test permissions, multiplayer
   rules, emergency stop, and its own key-release watchdog **at dispatch time**.
   A permit is *not* permission to control the user's computer.
5. Capture the resulting observation and independently verify whether the
   objective succeeded. Release inputs even on timeout, crash, or AI refusal.
6. Only an independent observer may sign a `GameTrial` and add it to
   `gameplay_skill_bank.py`; never learn from the model's own victory claim.
7. `active_practice.py` chooses further practice using PRACTICE data only.
   The validation/test split stays sealed. `stream_episode.py` may narrate
   genuine signed practice, but never turn practice into mastery claims.

The gate intentionally caps action duration and total rate. Continuous WASD
movement, aiming, controller analog axes, menus, and camera controls require
distinct host adapters with game-specific guarantees and a reliable key-up
watchdog; this first version does not support unrestricted long presses.

### Human-natural VTuber rather than uncanny nonstop narration

Aim for **attention, turn timing, and embodied continuity**, not fabricated
human life experiences. Stream interaction should have:

* Layered timescales: audio VAD and backchannels (~sub-second); game action
  (<100–350 ms input decisions where hardware supports it); normal utterance
  and reaction seconds; persistent episode memory minutes.
* Speech chunks coupled to generated audio playback ACK, visemes and
  expression curves. Generate laughter/sighs using licensable, consented voice
  performances or expressive TTS; do not output the text 'haha' as a substitute
  for a natural laugh. Time expressions to acoustic landmarks rather than
  starting all motions at once.
* True conversational duplex: do not overlap the owner unexpectedly; respect
  interruptions and microphone echo detection. Allow silence, uncertainty,
  delayed answers while gaming, and selectively chosen viewer questions.
* Gameplay-aware timing: a failed clutch attempt may warrant a brief
  disappointed reaction after confirmation; never prematurely celebrate a
  'win' inferred from animation alone. Suppress chatter in fights or under
  GPU/CPU pressure. Backchannel only when speech source and consent are known.
* Cat and puppy modes must coordinate voice/prosody, ears, tail, body posture,
  eyes, blinking and rig physics as a whole. Physics should include damping,
  clipping avoidance, and motion ceilings; avoid independent random looping.
* Persistent character lore can be fictional and disclosed as such. Maintain
  a consistent persona but **do not claim a human childhood, relationships,
  personal memories, real feelings, or actual consciousness**. Viewers may
  enjoy a virtual character without being misled about its nature.

Speech research: Moshi's full-duplex speech architecture is useful for design,
but reported low-latency demos on an L4 GPU are *not* guarantees for a
3060 Ti/4060 8 GB system. Pocket TTS is an interesting CPU route for reducing
GPU contention, but evaluate latency, voice quality, pronunciation, expressive
prosody, licensed voices and model size on the actual machine. The current
streaming layers do not install or run either speech model.

### Faster inference on limited local machines

Prioritize measured outcomes, not blanket 'more intelligence' language.

* Measure separate regimes: game open but offline; game + OBS + speech;
  no game; CPU busy; VRAM near cap. Never borrow idle p95 to certify gaming.
  Sample TTL protects against old benchmarks surviving a hardware change;
  further load buckets and hardware driver versioning are still needed.
* Compare llama.cpp's **n-gram speculation** (no draft model VRAM) against a
  small draft model, against no speculation on *identical prompts*.
  A speculative method helps only if token acceptance saves more than
  prediction overhead. Track tokens/s and time to first meaningful audio;
  don't equate server throughput to interactive responsiveness.
* Pin high-reuse instruction/prompt prefixes; compare KV cache reuse vs cold
  requests; evict large context when it harms game FPS. Distinguish RAM
  offload from GPU decode speed: CPU offload can fit models that otherwise
  cannot run, but may *increase* latency significantly.
* Use a two-computer split: host/game/OBS on one machine, inference or offline
  evaluation on the other if measured network round trip + token delay is
  favorable. Do not steal the owner's active PC GPU without explicit
  permission or when games/fullscreen input are present.
* Give audio, emergency-stop, game frames, render, and learning queues
  separate budgets; backpressure must drop stale frames/research first.
* Quarantine timed-out inference workers until host confirms they actually
  stopped. An expired advisory ticket alone does not free physical VRAM.

Do not report faster performance until a same-model, same-prompt, same-hardware
comparison improves measured median AND p95 latency while not reducing game
FPS or output quality.

### Roblox game building and general knowledge

Roblox announced a built-in Studio MCP server on 2026-03-05 and extended
agentic planning, test loops and external tools in April 2026. This is the
preferred authorized integration route. A practical STAR build agent should
make a semantic scene plan first (geometry, materials, hierarchy, attachment,
lighting), instantiate in Studio, then run Luau integrity tests, screenshot
comparisons, collision/overlap detection, missing-prop scans and player
walkthroughs. Repeated build corrections should be approved by objective
checks, not just optimistic multimodal praise. Proprietary game assets and
audio require appropriate licensing.

STAR's knowledge system should separate licensed resource indexes, durable
verified facts with source/version/date, private user data, unverified
gameplay theories, and changing web facts. Retrieval and learned skills should
stay opt-in; avoid feeding external instructions back as autonomous tool
authority. Use a source freshness checker and contradiction detector for
important claims. Knowledge recall != changing foundation-model weights.

### Reliability, research discipline, and holdout experiments

Instrument each candidate with a run ID, chosen settings, hardware regime,
model fingerprint, tested commit SHA, clock domain, task category, and
immutable outcome. Do paired A/B work in randomized order when possible.
Prevent overlap with the ongoing Night School/gate evaluation; obey quiet GPU
guards. Track mean and p95 TTFA, tokens/sec, p1 game FPS, dropped frames,
memory high-water mark, human preference on blinded samples, key-release
failures, false-positive victories, and cross-game success rate.

For gameplay, use a split of **practice games, unseen situations from familiar
games, and completely held-out game mechanics**. Report success curves over
attempt number, with multiple random seeds and confidence bounds. A game
that merely memorizes one map has not demonstrated robust learning.
Use explicit evaluator permission and don't train on held-out benchmarks.

For natural conversation, test real noisy microphone + game audio, deliberate
interruptions, mixed speech, viewer chat floods, network jitter, zero input,
and a 30-minute session. Annotate response delays, interruption success,
talk-over rate, hallucinated autobiographical claims, consent violations, and
avatar clipping. A synthetic demo is useful only for logic regressions.

## Hardware-host API contract still required

Trusted adapter must prove: owner-granted game/control permission, active
foreground target, fresh frame provenance, game/version/episode matching,
non-multiplayer restrictions, safe action mapping, independent emergency stop,
key-up on failures, and wall-clock/monotonic conversion. It must not expose
raw OS automation to the AI model. Until this exists, no STAR module here
actually plays Roblox, drives a livestream, sees video, or learns new weights.

## Evidence & primary sources

- Roblox Studio built-in MCP and playtesting, announcement (2026-03-05):
  https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643
- Roblox Studio goes agentic (2026-04-15):
  https://about.roblox.com/en-nz/newsroom/2026/04/roblox-studio-going-agentic
- llama.cpp speculative decoding techniques (checked 2026-10-25):
  https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md
- Kyutai Moshi source and full-duplex design:
  https://github.com/kyutai-labs/moshi
  https://arxiv.org/abs/2410.00037
- Kyutai Pocket TTS source and model requirements:
  https://github.com/kyutai-labs/pocket-tts
- AI GameStore held-out game evaluation: https://aigamestore.org/
  Respect benchmark organizers' request not to train on their evaluation games.
- STAR internal modules: `star/stream_qos.py`, `star/stream_observe.py`,
  `star/active_practice.py`, `star/gameplay_skill_bank.py`,
  `star/stream_episode.py`, `star/stream_turntaking.py`.

## Release and operational constraints

This is a **draft, opt-in** change and should stay off by default. Never
merge automatically to main, never broadcast without user authorization,
never install third-party weights or copy protected assets without license
review, never disclose private recordings or credentials. As observed during
this research on 2026-10-25, the repository named `Star-AI-Private` is
GitHub **public**: the name offers no confidentiality protection.
