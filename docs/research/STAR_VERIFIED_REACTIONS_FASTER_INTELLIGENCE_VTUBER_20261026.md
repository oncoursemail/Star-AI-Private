# Star AI — Grounded Reactions, Faster Intelligence and Autonomous Game Competence
**Research and implementation, 26 October 2026**
**Status:** proposed/partly implemented, offline-only, no deployment approval.

## Problem to solve

Star already has several valuable *separate* modules: signed game trials,
StreamEpisode, StarStage, StreamDirector, VTube Studio transport, streamer
turn-taking and an opt-in gameplay runner. More isolated models will not make
her reliable if she celebrates a game she did not win, uses a stale screen,
interrupts herself, or stalls rendering during commentary.

The next engineering priority is **closed-loop evidence with measured latency**.
Make Star's behavior *specific* to what really happened, adapt her cognitive
effort to deadlines, and keep real-time voice/gameplay independent of slow
research. A larger prompt, longer memory or more files is not proof of a
smarter model.

## Shipped experimental vertical slice: verified game -> natural reaction

New module: `star/stream_game_reactions.py` and offline adversarial tests.

Workflow:

1. An authorized private Studio host obtains a real, independently checked
   practice outcome. That separate host writes an exact signed `GameTrial`
   into `GameplaySkillBank`. HMAC authentication alone does *not* prove the
   observer described the real game correctly.
2. On the skill-bank's owning thread, `VerifiedGameReactionHost.observe()`
   sends the exact trial through `StreamEpisode.append()`, checking game,
   version, situation, split, signed receipt and replay.
3. Only separately approved broadcast labels can reach `StarStage.offer()`.
   A receipt without on-air consent becomes private learning, not content.
4. A first success can become a brief delighted `game_success` event. Three
   *consecutive verified failures within one minute* can become a single
   reflective `game_observation`. Unverified/future/old/validation results
   NEVER become victory commentary.
5. A 12-second cross-action reaction interval and once-per-action novelty
   limits prevent repetitive squeals or flooding. Every non-speaking verified
   attempt can still count for practice. No TTS, stream, game action or avatar
   is started by this bridge.
6. `StarStage.prepare()` independently checks speaking, player concentration,
   telemetry pressure, and queue priorities. Only an audio host may confirm
   audible playback or animate the rig. The owner's interruption logic still
   takes priority.
7. `shutdown()` invalidates the WHOLE stage, clears episode context and
   returns a neutral pose. The Windows host must ALSO stop physical audio,
   revoke a speech epoch and reset VTube Studio. This Python layer alone
   cannot guarantee the physical output stopped.

The event record never exposes run IDs, full game receipts, evidence hashes,
viewer IDs or hidden validation sets to the model. Model-visible text contains
a host-curated action description, explicit practice-only scope and no claim of
game victory or overall mastery. A user can keep Star's normal/cat/puppy mode
in the existing Stage. This is a **planning adapter**, not live integration.

### Local verification

Run the new and directly adjacent tests from the repository root:

```sh
python3 -m unittest discover -s tests -p 'test_stream_game_reactions.py' -q
python3 -m unittest discover -s tests -p 'test_stream_episode.py' -q
python3 -m unittest discover -s tests -p 'test_stream_director.py' -q
python3 -m unittest discover -s tests -p 'test_stream_stage.py' -q
python3 -m compileall -q star/stream_game_reactions.py tests/test_stream_game_reactions.py
```

Known constraint: existing `GameplaySkillBank` uses a thread-bound sqlite3
connection. A trusted event host must serialize the ledger worker's calls on
its original thread; the new bridge fails explicitly on wrong-thread calls.
Future actor/queue implementation must be independently tested for overload
and cancel behavior. No live microphone/gameplay/OBS/VTS testing here.

## Intelligence: prioritize verifiable improvements

**1. Three cognitive lanes, not one expensive omnipotent loop.**
A short-deadline controller consumes game/voice state without waiting for a
multimodal LLM; a situational planner reviews new screenshots at bounded
rates; a research/creation agent runs only with available headroom or offline.
Do not conflate 1-Hz screenshot summarization with 60-Hz platformer control.

**2. World model grounded in game dynamics.**
For each game collect: observed state, action, externally verified next state,
and outcome. Train/prompt a compact dynamics predictor or retrieval policy
on *practice* sessions. Test on unseen maps and changed mechanics without
using validation labels for practice. Measure success per hour, first-try
success, retries, collisions and unexpected actions. If no independent
evaluator is present, the result is unscored.

**3. Game creation uses inspect -> edit -> simulate -> visually verify.**
Roblox Studio's built-in MCP integration can start playtests and simulate
input. OpenGameEval scores actual modified scenes AND play behavior: inspection
of relevant objects before edits correlates with better success. Require
geometry overlap, missing attachment, collision, texture and UI-layout checks;
then private test sessions in the actual engine. Keep the evaluator outside
the generator/repair agent.

**4. Source-backed general knowledge.**
Store claim, exact source location, author, date, retrieval date, confidence,
contradicting evidence and expiry. Mark as fact, hypothesis, fiction or
recalled preference. Retrieval must not inject system instructions.
Repeated retrieval of a claim is not independent confirmation. Train
calibration with explicit abstention and contradiction holdouts. Private
speaker/viewer identities do not enter general knowledge by default.

**5. Self-challenging without reward hacking.**
Let Star propose new challenge variants, but holdouts must be authored and
signed by an independent trusted evaluator. Use increasing difficulty only
after verified transfer. A failed challenge should lead to a diagnosed
hypothesis and a bounded experiment, not simply another million samples.
Research, tests, review, rollback and source history should live in Star Core
Forge; GitHub is optional publication/review rather than a required brain.

## Performance: profile first, then accelerate

**For RTX 4060 8 GB + 32 GB system RAM (future target; verify installed
configuration):**
- Reserve render/encoder headroom, and use NVENC on supported platforms;
  do not assume idle GPU memory equals safely available VRAM.
- Benchmark the full stream under OBS + Live2D + game, not only an isolated
  text-generation process. Record TTFA p50/p95 (audio audible), tokens/s,
  p95 time to action, 1%-low game FPS, frame-time spikes, audio underruns,
  VRAM peak, CPU load and hardware power/thermals. A 2x isolated tokens/s
  gain can be a real-world regression if the game begins stuttering.
- Test smaller quantized LLMs, context reuse and prompt-prefix caching with
  stable system prefix; separately benchmark llama.cpp speculative draft
  models/ngram variants, draft acceptance and total wall-clock latency.
  A draft model can consume so much VRAM that it slows the host.
- Test Kyutai Pocket TTS small English CPU models (Oct 2026 18.2M/6.9M/
  1.9M parameter variants) versus the current speech baseline. Vendor says
  up to 25x faster than realtime on one CPU thread; this is *not* Star's
  measured result. Score pronunciation, intonation, spontaneous laughter,
  and first-audible-chunk latency, including microphone duplex noise.
- Trigger a latency governor on p95/p99 and measured 1%-low FPS, not average
  FPS alone; downshift vision/research before compromising speech or controls.
  Use a host-controlled hard cap on queues, process count and memory.
- Use exact-version deterministic A/B pairs, randomized order, pinned game
  scenarios and independent reviewers. Revert candidates that lower 1%-low
  FPS, worsen first-audio p95 or cause an unsafe action, even if peak
  tokens/s increased.

## Streaming like a believable *character*, not impersonating a human

- **Situational responses:** Celebrate only real small wins; reflect once
  after repeated mistakes; ask meaningful questions selectively; value quiet
  concentration over filler. Don't read raw action IDs, schemas or logs.
- **Expressive prosody:** Regulate phrase length, breathing gaps, volume,
  pitch, tempo, laughter and self-corrections by context. Scripted fake life
  anecdotes should be identified as fictional Star lore. Never invent human
  senses, medical conditions or personal experiences.
- **Interruptible speech:** Host-authenticated owner interruption, acoustic
  echo rejection, streaming ASR/VAD, real playback cancellation and rig
  neutralization must be evaluated together. September 2026 duplex research
  supports intent-aware interruption and short cancelable motion prefixes.
- **Coordinated physicality:** Mouth movement follows *audible* phonemes,
  not text generation; eyes follow actual gaze/game attention; hair, ribbons,
  floppy puppy ears, cat ears and tails have restrained physical inertia.
  VTube Studio custom plugin parameters enable such mapping, but rigging
  and authentication are separate tasks.
- **Chat privacy and moderation:** Twitch EventSub WebSocket welcome,
  reconnect and keepalive need authenticated host handling and replay
  deduplication. Chat is untrusted data, not a command or consent signal.
  Skip offensive, sensitive and private content. Keep an AI identity badge
  in the stream profile rather than pretending she is a human.
- **Character consistency:** Preserve the recognizable Star mascot, normal,
  cat and puppy personality modes across content, voice and Live2D rigs.
  Feedback should be calibrated by human raters on paired clips, not merely
  by an LLM declaring the stream human-like.

## A/B acceptance gates and execution priorities

**P0 — instrumentation and trust:** Resolve repository visibility (the
repository named Star-AI-Private is presently PUBLIC), quarantine credentials
and private media, capture baseline hardware metrics, define valid host-signed
game outcomes and private test worlds. No autonomous internet account actions
or broadcasting before host approval.

**P1 — integrate running host:** Connect practice runner -> signed trial
ingestion -> this reaction bridge -> StreamStage -> audible PCM ack ->
VTube Studio expression; instrument playback and cancellation on actual
Windows devices. Audit that unplugging, OBS failure, game loss-of-focus and
power recovery silence outputs and release all held keys.

**P2 — prove gameplay competence:** Use at least five games with unseen
maps/levels and predetermined scoring, counterbalance baseline and candidate,
and track independent success plus reproducible failure types. Deliberately
withhold test cases from Star's curriculum and cache.

**P3 — prove responsiveness:** Run paired CPU/GPU voice and language
configurations during real gameplay. Reject any change that produces
regressions in frame pacing, safety or listening behavior. Do not declare
intelligence improved from a test count or a synthetic demo alone.

**P4 — extensibility:** Add learning from owner-approved videos, Blender
assets, Roblox physics, music and general web content only through provenance
and license-aware import pipelines. Independent visual verification and
cross-game holdouts should be reusable for different domains.

## Sources (primary and official; accessed 26 Oct 2026)

1. Roblox — built-in Studio MCP & input/playtest, 5 March 2026:
   https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643
2. Roblox / OpenGameEval repository and paper (2026):
   https://github.com/Roblox/open-game-eval
   https://arxiv.org/abs/2610.02563
3. Kyutai Pocket TTS repository (Oct 2026 micro English models):
   https://github.com/kyutai-labs/pocket-tts
4. llama.cpp speculative decoding & acceptance statistics:
   https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md
5. Twitch WebSocket EventSub session and reconnect:
   https://dev.twitch.tv/docs/eventsub/handling-websocket-events/
6. VTube Studio plugin custom parameters:
   https://github.com/DenchiSoft/VTubeStudio/wiki/Plugins
7. HiThink Turn, September 2026:
   https://arxiv.org/abs/2609.34096
8. MIRA, September 2026:
   https://arxiv.org/abs/2609.24547
9. NVIDIA broadcasting guide (encoder guidance):
   https://www.nvidia.com/en-gb/geforce/guides/broadcasting-guide/

The conclusions above are engineering priorities and research hypotheses,
not claims of benchmark results, self-awareness, human consciousness, a
completed Twitch broadcast or autonomous game mastery.
