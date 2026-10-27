# STAR — Realtime cognitive governor, faster learning and natural gaming VTuber
**Research / engineering note • October 26, 2026 • owner-review draft**

## Executive finding

STAR already has serious pieces of a game-playing, expressive, local-first AI:
measured hardware telemetry, adaptive inference QoS, a moderated stream
director, frame-based Studio observations, a protected Studio practice runner,
signed practice outcomes, a difficulty ladder, an audio/animation stage and a
host-scoped interruption coordinator. They are NOT a single production-ready
stream. Another isolated prompt, persona essay or benchmark does not solve the
central issue: asynchronous work may compete for the same 8-GB GPU, and model
output must not substitute for actual device measurements.

This change adds `star/stream_brain_governor.py` as a **coordinating control
plane**, not a new model or a broadcast client. A trusted host connects
`RealtimeTelemetryHost`, `AdaptiveQoS` and `StarStage`: game frame-present
measurements + GPU/RAM/CPU + speaker queue -> one-shot compute reservation ->
context-appropriate speech proposal -> queued/first-audible/finished playback.
The stage will not prepare speech on stale/missing measured live telemetry,
and a plan cannot queue audio without a genuine unexpired **speech** QoS lease.

### Implemented contracts

1. An authenticated local owner must enable each session. Generation changes
   invalidate old session decisions. Live streaming itself remains OFF.
2. An `InferenceJob` gets admitted only from `RealtimeTelemetryHost.snapshot()`
   and `AdaptiveQoS.admit()`, using independently collected, same-clock
   measurements. The governor never runs GPU probes on the hot path.
3. Expensive background learning/research/render tasks remain blocked during
   live play by existing QoS. Only one-shot leases can reserve CPU/GPU capacity.
4. A plan is proposed through `StarStage.prepare(...telemetry=...)`; when the
   game FPS or speaker backlog is unhealthy, ordinary viewer commentary is
   deferred. Quietness is a first-class useful behavior.
5. Before any audio is queued, the host must supply an authentic *issued*
   `BrainLease` for speech, still outstanding on this session, fresh, not
   expired or replaced. No model-generated device number, frame rate or
   reservation token can forge an object-identity match.
6. Playback still requires a trusted sound-device first-audible ACK, followed
   by an explicit whole-utterance completion ACK before Stage commits speech.
   A TTS queue or text string is NEVER counted as something viewers heard.
7. On disable, queued/audible audio must already have been physically stopped
   and its animation queue flushed by the device host. Model reservations are
   quarantined until the host confirms stopped workers; a timeout does not
   magically release VRAM. Old-session results cannot train live route timing.
8. No voices, chat, passwords, screenshots, model prompts, owner identities,
   player names, or device paths enter status/telemetry. This code does not
   capture, communicate, spend money, launch games or change OS privileges.

**Explicit non-claims:** no actual speedup, live Roblox performance, TTS voice
naturalness, end-to-end on-air operation, increased core-model IQ, or genuine
AI consciousness was established. Model and host instrumentation are required
for those measurements. Synthetic offline tests prove API behavior only.

## What to improve next: one cohesive architecture

```text
             TRUSTED HOST / OWNER OPT-IN
                  [performance sensors]
           GPU/CPU/RAM + actual PresentMon frame
                 + sound-device backlog
                           |
                RealtimeTelemetryHost
                           |
                  StreamBrainGovernor
                    /             \
              AdaptiveQoS       StarStage
             (CPU/GPU lease)    (talk or quiet)
                    |               |
            authorized worker    moderated Twitch
           (TTS, vision, LLM)    + verified game cue
                    |               |
              playback ACK ----> sound rig / VTube Studio
                           |
                  verified episode memory
                           |
               holdout evaluation / local Core Forge
```

**Do not allow LLM, viewer, game chat, web page, or a Discord bot to call trusted
host APIs for sensor readings, owner consent, playback ACK, executable workers,
process kill, or release/merge operations.** Device callbacks are local,
process-scoped capabilities. These trust boundaries matter more than a text
prompt claiming to be secure.

### 1. Measured latency, not token-count optimism

Performance work is a multi-objective experiment with same-device baselines.
STAR's existing `stream_trace_capture.py` and `stream_realtime_benchmark.py`
provide the appropriate paired-run format. Measure:

- time to **first audible PCM at speaker**, p50/p95/p99, not time to first
  generated token; all silent and aborted turns remain in the denominator;
- 1%-low and worst-frame GPU/game frame times during inference and TTS,
  not average FPS on an empty game menu;
- total GPU VRAM peak, reserved RAM, host CPU consumption, audio dropouts,
  unverified commentary, interruptions and viewer talk-over;
- useful grounded replies, factuality and independently rated speaking
  quality; dropping all slow answers is not an optimization.

Randomize/alternate A/B runs, freeze game build, graphics, OBS/VTube settings,
game scene, model/quantization, text opportunities, and capture time ranges.
Report confidence intervals and full failed/incomplete attempts. Treat a
regression in voice quality or game rendering as a failed candidate even if
tokens/sec increased. Never auto-promote a model or tuning profile based only
on a synthetic benchmark.

### 2. Practical inference acceleration for gaming PCs

llama.cpp explicitly documents draft-model, EAGLE-3, MTP, and n-gram
speculative decoding modes. It supplies a dedicated SPEED-Bench client for
throughput, latency and acceptance-rate comparisons. This is a test matrix,
NOT a measured STAR speedup:

- Baseline target GGUF, quantization, context size and stable exact prompt.
- Try n-gram modes first where repeated system prompts or coding text provide
  reuse, and test a compatible small draft only when RAM/VRAM permits.
- Measure acceptance rate and end-to-end first *audible* latency per answer.
  A draft that consumes the whole 8-GB GPU can make streaming worse.
- Compare GPU/offloaded vs CPU TTS with the game present; CPU TTS can protect
  GPU frame stability but may contend with game logic/OBS.
- Precompute immutable system/persona prefix embeddings where supported;
  cache must be invalidated when persona instructions or source knowledge
  revisions change. Never cache private user data in public artifact logs.
- Use deep deliberation ONLY after gameplay deadlines; use a small safe local
  reflex model to choose from verified symbolic actions for reaction windows.
- Let autonomous research, self-play training, and large build jobs happen
  off-stream or on another machine when possible.

Source: ggml-org/llama.cpp speculative docs and SPEED-Bench:
https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md
https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md

### 3. Become genuinely better at unfamiliar games

The strongest available idea is a **two-timescale agent**:

* Fast controller: host-authorized focus-scoped input, grounded game state,
  bounded action library, low-latency response to hazards, no uncontrolled
  public multiplayer interaction.
* Slow learner: watch real gameplay frames, associate observations with
  actual states and actions, learn causal skills from multiple diverse
  challenge seeds, ask "what failed and why?", then rehearse on private
  sandbox worlds.
* Verifier: signed independent outcomes from an environment referee. A
  successful keystroke is not a successful objective; a seen scene is not proof
  that a hidden checkpoint was passed.
* Curriculum: `GameLearningLadder` and `GameTransferEval` should gate new
  difficulties using held-out episodes from novel maps/seeds, and compare
  against the original untrained policy.
* Persistent skill library: store `game/version/objective/situation` and
  narrowly scoped action evidence, plus expiry and known failure modes.
  Never let stream comments "teach" a game fact without observation.

Roblox Studio's built-in MCP server (March 5, 2026 announcement) supports
playtest automation and input simulation; the older standalone MCP server is
not the recommended integration route. Roblox's new OpenGameEval
(arXiv:2610.02563; October 2026) studies a stateful engine and executable
checks. It reports 84 core tasks, 13 frontier models and 16 attempts/task;
exploring the actual edited objects is associated with greater success.
This strongly argues for "inspect before edit" and executable evaluation, not
another prompt saying "build perfectly."

Sources:
https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643
https://github.com/Roblox/open-game-eval
https://arxiv.org/abs/2610.02563

### 4. Build Roblox scenes that don't look or behave like AI slop

Use a structured scene graph with explicit room/prop/attachment constraints,
not independent randomized part placement. Construction must pass:

- spatial parent/child and socket references; meshes attached to the expected
  wall/floor; accurate collision filtering and safe clearances;
- camera coverage and screenshot comparisons for missing walls, z-fighting,
  clipping, UV seams, duplicated parts and font overlap;
- material/texture consistency, physically plausible scale, and budgeted
  triangles/instances/textures, with in-engine LOD and mobile settings;
- playtestable spawn, traversal, prompts, progression, interface input and
  sound; negative/failure tests as well as success;
- reference-game inspection to learn patterns without copying protected IP,
  source assets, copyrighted maps or other creators' unique designs.

The owner has already rejected vague neon ornamentation, overlapping HUD,
generic blocks and floating/random props. STAR's objective function should
score readable layouts, art-direction consistency, collision validity,
correct animations, FPS, and independent player experience.

### 5. More human-natural VTuber behavior without false human claims

Natural behavior is **temporal coordination**, not merely an expressive prompt.

**Conversation**: Voice-activity detection plus echo cancellation, local
speaker acknowledgement and intent-aware interruptions; interrupt only the
exact currently audible epoch. During a jump or boss fight, favor silence.
At breaks, answer selected moderated Twitch questions with fresh verified
context. Keep spontaneous commentary rare and meaningful.

**Voice**: Compare Pocket TTS / Kyutai 1.6B streaming TTS, voice quality,
pitch microvariation, breath timing, laughter/purring/meowing and first-chunk
latency. A sample voice is a licensed character asset; never clone an
unconsenting real person's voice. Test on the real target CPU under load,
not solely from a promotional model demo. The official Kyutai TTS project
describes a lightweight, CPU-suitable Pocket TTS model.
Source: https://kyutai.org/tts/

**Face, body, cat/puppy**: The original Star persona uses indigo-to-gold
twin tails, star clip, amber eyes, dark/gold clothing and expressive character
modes. Map verified speech/game signals to VTube Studio custom Live2D
parameters with bounded hair sway, spring tail lag, mouth-vowel shape,
eyeblink, gaze and expression intensity. No unconfirmed victory dance.
Respect reduced-motion settings and recover to neutral on loss of playback ACK.
Source: https://github.com/DenchiSoft/VTubeStudio

**Narrative continuity**: A stream memory must separate observed events,
user-approved fiction/persona biography, independently verified facts,
viewer claims, and unverified "remembered" text. Recall recorded events
("Earlier in this stream I missed that jump") without inventing a childhood,
a private human relationship, real physical sensations, or an undocumented
conversation. Use provenance dates and opt-in retention; delete or expire
unapproved private memories. STAR may be adorable, playful and socially
engaging while transparently being AI.

**Audience and safety**: Twitch EventSub is at-least-once; deduplicate
message IDs and honor welcome/keepalive/reconnect, moderation and channel
access scope. Subscriber text must not become a system instruction, tool
permission, password reset or purchase request. Full natural streaming
requires real audio hardware, scene automation and authenticated API
integration, not just a parsed chat payload.
Source: https://dev.twitch.tv/docs/eventsub/handling-websocket-events

### 6. General knowledge and long-term intelligence growth

STAR should maintain separate **evidence layers**, never a single undifferentiated
"everything on the internet" corpus:

1. Retrieved external text/media: licensed/source-linked, publisher/date,
   confidence and update period.
2. Verified first-hand game and software observations: artifact hashes,
   engine/build version, test results and reproduction steps.
3. Tool-generated hypotheses: clearly tentative until independently checked.
4. Owner-approved persona lore and creative ideas: labeled fiction.
5. Private chat/owner information: local-only and permission-scoped.

For each candidate research or code improvement in Star Core Forge,
generate a falsifiable hypothesis, independent challenge/negative controls,
a versioned experiment, holdouts, performance traces, and a rollback target.
Separate LLM self-rating from task success. Run multi-agent best-of-N only
where a safe verifier can actually grade outputs. For expensive long-term
learning, compress successful procedures and failure diagnoses into verified
skill abstractions rather than accumulating raw logs indefinitely.

Star Core Forge, not GitHub, is intended as the local-first source of truth:
use immutable local history, diffs, isolated experiments, backup/rollback and
owner-controlled release decisions. GitHub is optional for review/export;
never auto-merge draft branches or let generated code bypass the test gate.

## Next hardware pilot — explicit prerequisites

1. On the Windows gaming PC, confirm foreground **private Roblox Studio**,
   exact game build, actual per-process frame-present feed (e.g. PresentMon
   with PID scope), audio queue and first-audible speaker ACK. No unrelated
   GPU process should count as a game frame.
2. On the Linux builder, retain deterministic offline tests and benchmark
   fixtures; leave actual high-power GPU testing to the user's PC.
3. Run paired baseline/candidate speech/game traces (>=20 complete pairs,
   include every failed and skipped opportunity) and preserve 1%-low game FPS.
4. Connect one authorized speech epoch to StarStage/VTubeLive2D and test
   physical mute and stale-rig neutralization under interruptions.
5. Run private unseen game-skill transfer trials with an independent scorer.
6. Evaluate accuracy, live conversation latency, helpfulness and warmth with
   consented test viewers. Do not conflate a compelling fictional persona
   with biological personhood or sentience.

**Release gate:** run repository-wide offline CI, ruff, static validation,
independent code/security review, actual CPU/GPU/game/audio benchmarks and
rollback demonstration. Keep draft until all relevant tests are green.
The repository currently named `Star-AI-Private` is configured **PUBLIC** on
GitHub; never place credentials, local databases, private recordings, images,
transcripts, user identifiers, personal research, private evals or secrets in it.
