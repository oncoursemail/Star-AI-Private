# Star AI: adaptive visual intelligence, game-learning and natural VTuber research

**Research date:** 2026-10-26. **Status:** Engineering prototype, not a measured
model-quality/speed improvement, live autonomous gameplay or human-grade broadcast.

## What this change solves

Star already had `StudioVisualObserver`, `GameActionGate`,
`StudioPlaytestHost`, `StudioOutcomeBridge`, `GameLearningLadder`,
`GameTransferEval`, a stream telemetry class and a **read-only**
`advise_workload("vision")` recommendation. But the Studio visual sensor itself
could be repeatedly called as fast as the host attempted, regardless of game
frame rate, speech backlog, stream mode or whether the screenshot had changed.
That is unnecessary load, especially on a single 8 GB gaming GPU.

This branch adds `star/studio_vision_qos.py`: a **host-enforced read-only
vision sampling governor**. In the owner-approved private Studio use case,
`StudioVisionQoS.sample(host_measured_telemetry)` evaluates current resource
conditions *before contacting Studio*, and uses a monotonic completion-based
capture cadence and exponentially increasing cooldowns for unchanged scenes
and sensor failures. It does not launch any process, send any key input,
activate Studio, send viewer messages, store images or infer a success score.

### Engineering contract

1. The host independently approves a particular private Studio/game and
   arms `StudioVisualObserver` with its real focus/private-place attestation.
   Neither a game, chat, model response nor screenshot may approve access.
2. The host supplies `StreamTelemetry` measured from the current machine,
   **not** values suggested by the LLM. The governor refuses missing or
   inactive game telemetry.
3. **Live mode:** at most one normal observation per second; if measured free
   VRAM < 1536 MiB, game FPS < 45 or speech backlog > 350 ms, defer vision.
   These are conservative *starting policies*, not validated device optimums.
4. **Offline private practice:** normal cadence at most 4 captures/second.
   Also defer when game FPS < 30 or speech backlog > 350 ms. This mode is
   not an invitation to interact with public Roblox multiplayer servers.
5. Each identical frame doubles the next delay up to 4 seconds. Failed
   observations have an independent exponential retry delay up to 8 seconds.
   Both reset on successful changed evidence. **Cadence starts when analysis
   finishes**, avoiding bursty catch-up after a slow model.
6. A capture returns the original `VisualEvidence`, including the scoped
   screenshot digest, while actual RGB bytes are neither persisted nor logged.
   It does **not** turn a vision model's output into a trusted objective score.
7. The existing `GameActionGate` / `StudioPlaytestHost` must still recheck
   fresh input authorization and key-up. A duplicate image has zero actionable
   confidence, independent of what this governor says. Signed practice
   outcomes and hidden-game generalization scores remain separate.
8. Do not introduce an asynchronous image queue: old queued visual contexts
   are worse than skipping a redundant frame. The caller may poll based on
   its own timer; 1/4 Hz are maxima, not targets.

**Measured results this branch can truthfully claim:** tests demonstrate
cadence enforcement, pressure rejection, dedup backoff, bounded error retries,
recovery and concurrency serialization with fake Studio MCP. No comparative
game FPS, p95 speech latency, tokens/second or autonomous game mastery is
measured by these offline tests.

## 2026 source review (primary sources)

- Roblox's built-in Studio MCP tool catalog includes `list_roblox_studios`,
  `get_studio_state`, `screen_capture`, `user_keyboard_input` and
  `user_mouse_input`. Studio instance ID must be selected explicitly.
  Official docs: https://create.roblox.com/docs/studio/mcp .
  March 5, 2026 official announcement: https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643 .
  Read-only capture is not autonomous controller success.
- Roblox OpenGameEval evaluates agent behavior inside executable games, which
  motivates separate held-out gameplay evaluation rather than self-reported
  task completion: https://arxiv.org/abs/2610.02563 .
- llama.cpp's official speculative decoding documentation includes draft model,
  n-gram/cache and EAGLE approaches. The draft must be cheap enough and
  accepted frequently enough to beat decoding without it:
  https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md .
  There is no guaranteed speedup on Star's model or hardware.
- Kyutai's original Pocket TTS is an approximately 100M-parameter
  CPU-oriented streaming TTS option; the project also introduced much
  smaller English voice models in October 2026. Model runtimes and
  expressiveness depend on CPU and text/voice selection:
  https://kyutai.org/pocket-tts-technical-report/ and
  https://github.com/kyutai-labs/pocket-tts .
- Kyutai Moshi explores full-duplex speech perception and generation:
  https://github.com/kyutai-labs/moshi and
  https://arxiv.org/abs/2410.00037 .
  Any vendor latency number is not a prediction for Star's setup.
- VTube Studio documents authenticated local WebSocket plugin access and
  custom Live2D input parameters:
  https://github.com/DenchiSoft/VTubeStudio .
  Token handling and a suitable Live2D model remain real-device concerns.
- Twitch EventSub has at-least-once event delivery, a welcome/subscription
  deadline, reconnect-session semantics and no replay after disconnect:
  https://dev.twitch.tv/docs/eventsub/handling-websocket-events and
  https://dev.twitch.tv/docs/eventsub/websocket-reference/ .
  Chat must remain moderated and must not grant computer permissions.

## Next engineering experiments: intelligence that improves by evidence

### P0. Close the actual private-Studio observation/action/outcome loop

Host machine running Roblox Studio should connect to the built-in local MCP
server, discover *its current tool schema*, bind a named private Studio
instance, instantiate a trusted screen assessor, and capture actual frames
through `StudioVisualObserver`/this governor. The controller should use
`StudioPlaytestHost` solely for an owner-curated symbolic action set;
its independent physical key-up watchdog must be installed before dispatch.
Then record checkpoint, collision, health and completion outcomes using
**game-engine instrumentation**, not visual-model self-grading, and ingest
only independently signed PRACTICE trials through `StudioOutcomeBridge`.
Hold out unseen map variations through `GameTransferEval`.

Track per-game held-out completion rate, errors per level, interventions,
frames consumed per successful action, and total wall-clock time. A faster
plan that wins fewer games is **not** an intelligence improvement.

### P1. Build a two-speed perception stack

For actual game control, high-frequency inexpensive game-state telemetry and
short-lived event triggers (e.g. character grounded, nearest platform, HP,
collisions, reward delta) should drive immediate decisions; use expensive
vision snapshots sparingly for scene understanding and debugging. An
independent **low-latency input control path** must never wait for a slow
vision model, speech synthesizer, browser search or avatar animation.
Use fresh engine observations and deliberately degrade to safe inaction if
out-of-sync. Stream-safe `StudioVisionQoS` is a **slow perceptual layer**, not
an FPS-rate control loop.

### P1. General knowledge, transfer and learning to make games

Maintain three distinct memories: (a) source-backed factual knowledge with
retrieval source/version/date/license; (b) personally observed game actions,
tool outputs, failures and signed results; (c) fiction/persona lore.
Never blend fiction with claimed real history. Retrieval should be permissioned
and off by default where Star's established configuration requires it.

Use a difficulty-curriculum generator to invent harder but testable puzzles,
then run best-of-N candidates through independent executable or engine
verifiers. Preserve the failed attempts for targeted diagnosis, deduplicate
semantically identical tasks, and reserve inaccessible holdout challenges.
For Roblox building, combine spatial adjacency checks, collision/anchoring
checks, texture and prop-reference checks, multi-angle screenshots, UI overlap
checks, and avatar-scale movement playtests. A model's judgment of "beautiful"
or "perfect" should never substitute for a real test and human aesthetic
review. Reinforce Star's existing "no AI slop" requirement with concrete
screen-space and scene-graph checks.

### P1. Faster *effective* intelligence on constrained computers

Star's existing environment includes 8 GB-class NVIDIA GPUs and host RAM.
Experiment rather than promising to break physical VRAM limits:
- Compare 4-bit vs 5/6/8-bit quantization with **task accuracy**, VRAM,
  p50/p95 time-to-first-token and inter-token latency, not speed alone.
- Evaluate llama.cpp draft-model speculation against *non-speculative*
  inference, using exactly the same prompts, fixed sampling seeds when
  supported and measured draft acceptance, with overflow/reload costs.
- Cache verified, non-sensitive retrieval and repeated prompts under
  deterministic cache keys. Version/invalidate caches when tools/models or
  game scope change; never cache secrets or live chat as public answers.
- Keep game rendering, OBS encoding, mic capture and speech playback
  prioritized over bulk search, model training, video understanding or asset
  rendering. Move suitable TTS to CPU *only if* it improves whole-stream
  performance. A CPU TTS model can still contend for game threads.
- Report real host FPS/frame time and dropped frames, free VRAM, audible
  speech first-chunk latency, cancellations, audio underruns, stream dropouts,
  real game-task outcomes, energy/temperature and task throughput.

### P2. A warm, responsive, recognizable AI VTuber

Treat a game stream as an event-driven performance rather than a monologue.
Input sources: actual game outcome events, moderated Twitch chat questions,
Star's persistent but permissioned personality/continuity memory, speech
energy and voice playback position. Build a lightweight realtime director:

1. When a difficult game sequence needs focus, prioritize immediate input and
   short reactions; suppress unnecessary narration and expensive retrieval.
2. During downtime, choose one relevant viewer question, remember the
   conversational thread, and speak with natural turn lengths and silences.
   Support acknowledgments, self-correction, interruptions and occasional
   contextually appropriate laughter instead of laugh spam.
3. Drive VTube Studio mouth/blink/gaze/head/shoulder/hair/cat/puppy expression
   controls from actual *heard* audio and gameplay context, with gesture
   coherence, collision-safe hair and ear/tail physics in the rig. Revoke
   obsolete frames on interrupted speech.
4. Keep Star's distinctive wholesome chibi gold-star design, expressive
   cat/puppy transformations and playful personality, while disclosing her
   AI nature; generated autobiographical stories should be labeled fictional
   lore unless grounded in actual recorded events.
5. On unexpected chat harassment, do not improvise computer commands,
   financial transactions, keypresses, privacy disclosures or moderation
   privileges. Use owner-configured moderation/consent boundaries.

Test with genuine recordings **kept private**: conversational naturalness,
word interruption artifacts, mouth-audio lag, laughter quality, memory
precision, viewers' ability to understand Star, false claims about game events,
and steady game FPS. Human-sounding is a perceptual quality target, not a
claim of consciousness or legal human identity.

## Delivery and trust boundaries

GitHub is an **optional publication/review mirror**, not Star's mandatory
self-improvement database. Her Star Core Forge/local-first work should own
experiments, reproducible build metadata, result evaluation, rollback and
backups. Publish only reviewed, secret-free snapshots as draft PRs. Do not
merge or deploy on the basis of simulated tests.

The repo called `Star-AI-Private` currently reports **public** GitHub visibility:
its name does not provide confidentiality. Never upload stream recordings,
chat logs, access tokens, signing keys, screenshots, identity documents or
hidden holdout answers to this repository.

## Acceptance before enabling any live gameplay or stream

- Run real Studio version-specific MCP capture and private-focus tests.
- Measure idle/crowded game FPS and voice backlog with QoS enabled/disabled,
  after warm-up and repeated runs; compare confidence intervals.
- Show a successful controller action with verified key-up and independent
  checkpoint-change evidence; repeat on unseen levels and report failures.
- Show successful VTube Studio authenticated session, synced playback on an
  actual audio device, safe interruption and reconnection.
- Keep owner authorization, local-only control, multiplayer restrictions and
  independent recovery unchanged. Failure must result in no new actions.
