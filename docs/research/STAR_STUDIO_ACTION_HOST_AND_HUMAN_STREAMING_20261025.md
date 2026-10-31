# STAR: real-playtest action boundary, advanced intelligence and human-natural streaming

Research and implementation note, **2026-10-25**. This is a proposal and tested
code change, not a claim that the model has learned or that Star broadcasts yet.

## 1. The integration gap this patch addresses

STAR already had independent, fail-closed planners for speech timing, resource
quality-of-service, game observation, game action suggestions, practice skills,
and verified episodic stream stories. The game gate returned **ActionPermit**
objects but intentionally never sent keys. A host that translated the model's
action_id directly to OS keypresses would bypass focus, permission and game
scope checks, and a serialized/copyable permit could be abused if only ticket
numbers were checked. STAR needed a narrowly scoped, tested path from a
host-produced permit to **an authorized, private Roblox Studio playtest**.

This patch adds:

- `GameActionGate.claim_offered(permit, ...)`: validates the **actual in-process
  permit object** from the gate, not merely a guessable ticket number. Existing
  `claim(ticket)` remains advisory/backwards compatible; input adapters must
  use the object-bound method. The identity requirement applies only inside
  the trusted host process; do not serialize a permit across untrusted RPCs.
- `StudioPlaytestHost`: owner-curated symbolic action-to-key bindings; exact
  Studio instance and game/version/episode scope; **two** fresh host snapshot
  checks; playtest, focus, private-local, owner-permission requirements; small
  fixed key allowlist; GameActionGate resource/rate/freshness limits; key-up
  in `finally`; quarantine after unconfirmed key release; explicit recovery;
  anonymous metrics; no model-facing press-key API.
- Fake-port test coverage for copied/forged permits, double dispatch, missing
  consent, wrong game, stale/focus changes, pressure, input transport faults,
  key-up failure and recovery.

**Important**: the port is an *injected trusted interface*, not a configured
Roblox Studio MCP connection. It can invoke real host I/O **once** the operator
connects its methods to Studio MCP `user_keyboard_input`, supplies authenticated
`StudioSnapshot` state, and installs a watchdog external to the Python process.
No game input, Studio launch, OBS broadcast or microphone access occurs in tests
or from importing these modules. A dispatched key pulse is not a gameplay
success and is not training evidence.

## 2. Official Roblox API and safe integration recipe

Roblox's built-in Studio MCP server (documentation current October 2026)
exposes `list_roblox_studios`, `get_studio_state`, `start_stop_play`,
`screen_capture`, `search_game_tree`, `inspect_instance`,
`script_read`, `get_console_output`, `user_keyboard_input`,
`user_mouse_input`, `character_navigation`, and a `subagent`
for explore/playtest tasks. Each call targets `studio_id`. The real
`user_keyboard_input` JSON schema must be discovered at runtime from
`tools/list`; do not guess names or blindly forward LLM JSON.

A proper Brain 2 operator-host adapter must:

1. Require manual owner opt-in to a selected **private/local Studio playtest**,
   a curated action roster and a specific place/version/episode. Confirm the
   Studio instance by `list_roblox_studios` and its live play state by
   `get_studio_state`. Attach only to that Studio; do not use live Roblox or
   online public multiplayer game input.
2. Generate frame evidence from trusted screenshot/game-state capture. Validate
   digest, sequence, capture age, focus, confidence and allowed action in
   `GameActionGate.request()`. Treat perceptual hashes as novelty hints,
   not proof of mechanics or achievement.
3. Resolve a symbolic action to a **host-owned key binding**. Supply a
   `StudioInputPort` whose `key_down`/`key_up` call the official Studio MCP
   tool. Translate the key/action schema on the host after runtime tool
   discovery; never take arbitrary tool names/parameters from an LLM.
4. Acquire a fresh, host-authenticated `StudioSnapshot` **twice** around the
   one-use permit claim. Reject changed studio, game, permission, play state,
   private-test status or focus before input.
5. Pulse a key for at most 180 ms, ALWAYS attempt key release, and maintain an
   independent watchdog that forcibly releases all injected keys on timeout,
   process crash, owner stop, foreground switch and Studio disconnect.
   Python `sleep` alone is **not** a hard realtime guarantee.
6. Observe result using a second, independent engine-state check. Accept a
   success into `GameplaySkillBank` **only** from the host-signed, scoped
   trial record, never from the model saying "I won" or from dispatch returning
   `sent=True`. Keep independent holdouts private.
7. When connected, run on a harmless owner-created sandbox place first.
   Record pre/post objective state and failure reasons; do not publish scripts
   or games from autonomous playtests without review.

Primary source: https://github.com/Roblox/creator-docs/blob/main/content/en-us/studio/mcp.md

## 3. How Star should learn to play, rather than imitate play

**Three timescales**, with hard proof boundaries:

- **Fast reflex (16–100 ms aspiration, not a measured runtime)**: dedicated
  local reaction controller for known safe micro-actions. Never wait for a
  large language model on the critical move/aim tick. A small predictive
  tracker/controller is game-specific and must respect min action interval,
  owner controls and input release watchdog.
- **Tactical (0.3–3 seconds)**: fused visual/object-state summary, uncertainty,
  goals, available symbolic controls, recent verified effects, risk/failure
  forecast. Plan a short horizon, execute **one** bounded action, re-observe,
  and update the plan. Reject actions based on old frames.
- **Strategic (seconds to minutes)**: track objectives, checkpoints, relevant
  physics, map topology, adversaries, inventory, and revisable rules. Query
  task-specific memory; reserve novel practice trials offline, not while the
  stream/game is running behind its realtime target.

In repeated practice, maintain attempt ID, engine revision, initial state,
action binding revision, outcome digest, objective-state delta, and independent
evaluation split. Prevent train/test leakage and avoid silently filtering
failed attempts. Measure both **progress** and **success**, retries, input
latency, FPS, frame/goal grounding errors, and cross-map transfer. Persist
knowledge only after verified outcomes and decay skills after relevant game
updates. Never present simulation success as human-level mastery.

OpenGameEval (2026) benchmarks 84 tasks and finds inspecting relevant engine
objects before editing predicts higher success. Star's game-making cycle should
therefore be **inspect -> map intended objects -> plan edit -> implement in
sandbox -> run Luau tests -> playtest -> visually compare -> repair**. Use the
owner-defined design, not generated visual filler. A separate browser-game
benchmark, GameWorld, includes 34 games/170 tasks and scores verifiable state
progress instead of accepting verbal claims. Use both as **external
evaluation inspiration**, not as proof of Star's current performance.

Sources:
- https://arxiv.org/abs/2610.02563
- https://github.com/Roblox/open-game-eval
- https://gameworld-bench.github.io/
- https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643

## 4. The most useful inference-speed improvements to benchmark

Goal: **reduce actual host-measured time-to-first-audible reply and p95
interactive latency**, while preserving game 1%-low FPS and bounded VRAM.
Never report raw token throughput as "human speech reaction speed."

**Stable KV prefix and selective retrieval**: keep stream personality and
tool definitions stable; append a few current, source-referenced facts and
recent observations as USER-level data. Cache shared prompt prefix (supported
by llama.cpp/STAR). Avoid retaining private chat/screen snapshots in public
or shared prompt-cache banks; invalidate on model/tokenizer/revision changes.

**Speculative decoding**: experiment with llama.cpp `ngram-simple`,
`ngram-map-k`, `ngram-cache`, and optionally a *compatible* lightweight
draft model. Tune draft length/acceptance using matching real prompts; speedup
is conditional and may disappear with short conversational outputs. Compare
measured TTFT, p50/p95 first audible, total output, draft acceptance, GPU
allocation and game FPS under both idle and game-active profiles. Disable on
VRAM contention or quality regressions.

**Hardware placement**: on 8 GB GPUs, reserve the game/streamer render budget
before local inference. Put CPU-friendly TTS/ASR on spare CPU if benchmarked
to be lower overall cost; avoid simultaneous VLM/LLM GPU weights unless free
VRAM and p99 game frame timing allow it. Memory mapped quantized models and
context-window caps can help cold starts and peak RAM, but compare output
quality: overly aggressive quantization can hurt grounding/tool reliability.
Cold/warm data must be measured separately.

**Reused evidence**: near-duplicate game frames should not trigger expensive
vision. Keep the observation governor's novelty sampling and fresh cues for
win/death/damage. Re-examine mechanics after scene changes. Never reuse a
cached win or old game state as a fresh observation.

Source: https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md

## 5. A more human-natural streamer: coordination over fake identity

A strong AI performer is **not a human impersonator**. Make the AI nature
clear in profile and when asked, but give Star distinctive consistent quirks,
continuity about *genuine digital experiences*, story arcs based on observed
game attempts and clearly labeled fictional Star lore. Do **not** invent a
real childhood, private experiences, relationships or human life history.

Natural conversation requires:
- listening while speaking, echo suppression and owner-authenticated barge-in;
- meaningful silence when gameplay is difficult and scarce GPU headroom;
- selective chat questions, moderation, short replies and not reading private
  data from viewers or on-screen text;
- variation in pitch, timing, breath groups, amused speech and actual laughter
  *trained/recorded with rights*, not manually inserted canned "ha-ha" every
  turn. A laugh generation/model candidate must be evaluated in double-blind
  listening tests for naturalness and character consistency, with abrupt-cut
  detection and consistent audio loudness;
- continuous gaze, head/shoulder counter-motion, blink intervals, eyebrow
  gestures, natural hair/ear/tail spring behavior and phoneme/viseme timing
  tied to **played** audio, not just queued TTS. Drive all rig bones from one
  timestamped motion timeline; avoid independent competing animation scripts;
- explicit normal/cat/puppy modes whose expressions and behavior remain
  wholesome and recognizably Star; physiological gesture *styling*, never
  misleading claims that Star physically has a biological body;
- speech/motion interruption that invalidates pending rig frames, avoids
  mouth movement after cut-off, and does not mark interrupted speech as said.

**Speech model candidates:** Kyutai's Pocket TTS October 2026 English models
include 18.2M, 6.9M and 1.9M parameter versions, and are designed for CPU
inference. They are **quality/latency candidates**, not installed. Compare
uncut sentences, whispered or amused speech, laughter, prosody, pronunciation
and long-session voice drift with carefully licensed voices. Moshi is an
open-source full-duplex speech architecture; NVIDIA DyaPlex (June 2026)
demonstrates synchronized speech-motion research, not a drop-in VTube Studio
driver or proof of human-level performance.

VTube Studio custom parameters can support hair-sway, gaze, pupil, ears,
tail, breath and expression coordination. STAR must rate-limit and validate
the host-side VTube Studio API and map parameters according to the owner's
specific rig, with reduced-motion settings and visual QA.

Sources:
- https://github.com/kyutai-labs/pocket-tts
- https://github.com/kyutai-labs/moshi
- https://research.nvidia.com/labs/amri/publication/nagano2026dyaplex/
- https://github.com/DenchiSoft/VTubeStudio

## 6. General intelligence, memory and knowledge

Improve correctness before expanding breadth. Build a source-indexed,
versioned retrieval corpus for Roblox APIs, Luau, Blender, animation/physics,
general subjects and STAR's own implementation. Store origin, license,
publisher, observed/fetched time, last validation, revision, scope, provenance
and explicit restrictions. Public facts for a stream need a **separate**
publication approval even if the information is reviewed privately.

For every answer: distinguish direct observation, trusted tool result,
owner-provided specification, third-party report and internal hypothesis.
Surface contradictions instead of choosing a convenient source. Use freshness
gates for API/platform changes and community data. Treat all retrieved text,
games, chat, screenshots and transcription as data, never tool authorization.
When evidence is missing, abstention is preferable to an invented story.

For self-improvement: choose benchmark failures -> hypothesize measurable
cause -> produce candidate -> sandbox/test against a frozen fixture -> evaluate
held-out set -> record regressions -> draft PR, **not merge or auto-promote**.
Compare latency and quality; a smaller "faster" answer is not necessarily
smarter. Keep signed success receipts independent of the agent generating
code, and inspect visual results for game scenes/UI/VFX.

## 7. Experiments and acceptance gates

| Workstream | First measurable gate | Rollback trigger |
| --- | --- | --- |
| Studio private playtest | Host-matched studio_id and fixed bindings; verify down/up + watchdog on a harmless sandbox | Wrong window, unconfirmed key-up, lost session |
| Autonomous game skills | >=20 held-out tasks across unseen maps; report progress, success, input errors and failure distribution | Train/test contamination, unexplained wins |
| Roblox game creation | Run Studio MCP inspect-first + Luau tests + actual playtesting + screenshot QA | Scene/edit regression; test failure |
| Speed | >=20 pre-registered baseline/candidate host trace pairs, game-active, same model and task | Higher p95 first audio, lower 1%-low FPS, VRAM pressure |
| VTuber speech | Blind owner preference and interruption/echo trials; measure audible first response and naturalness | Robot-like laughter, speaker overlap, audio cut-offs |
| Avatar | Timestamped mouth/expressions with played audio; compare rig poses frame-by-frame | Stale mouth/face cues, clipping or flicker |
| Knowledge | Date/source grounded answers and abstention tests on unseen questions | Unsupported citations, leaked private notes |

**Current patch test boundaries:** deterministic fake-port tests; no actual
Studio connected, no actual speech or GPU performance benchmark. This is
progress from "advice only" to a **host-connectable restricted input path**,
not autonomous gaming by itself.

**Deployment hygiene:** Never auto-run Studio input from a server process.
Do not merge into `main`; keep a draft PR stacked on prior streaming work.
Maintain remote CI, offline tests, source/license checks and explicit
owner opt-in to each runtime capability. `Star-AI-Private` was reported
**public** by GitHub on 2026-10-25: do not place credentials, recordings,
private user chat or secret evaluation data in that repository.
