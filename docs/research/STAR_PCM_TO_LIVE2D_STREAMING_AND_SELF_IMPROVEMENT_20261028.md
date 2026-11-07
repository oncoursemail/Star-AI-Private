# STAR — consumed audio to animated avatar, plus the next intelligence frontier
**Research / implementation: 28 October 2026.** This note distinguishes working
offline code, experimental integration, and hypotheses. No model weights were
trained and no real stream was started.

## What this branch does, and what already existed

- Existing StarStage, StarPlayoutClock, DeviceAudibleSampleHost,
  VTubeLive2DBridge and VTubeLocalHost supply speech-turn authorization,
  playout-based timing, an output-device counter seam, custom rig values and a
  loopback-only authenticated VTube Studio protocol respectively.
- New `AudibleAvatarSession` joins these **existing components** into one
  host-owned path. It accepts the exact identity-bound audio epoch, only
  distributes a fresh sound-clocked motion sample, and drops old/foreign frames.
- On paused, stalled, unobserved or zero-frame playout, a one-shot **neutral
  hold** clears mouth movement without consuming a fake audio cursor or
  terminating an otherwise resumable speech turn. The existing separate
  final-neutral protocol still requires physical stop/flush.
- If the avatar socket fails, the coordinator stops sending animation and
  closes the socket. **It does not claim or attempt to stop the physical audio
  device.** The host must stop/flush PCM before calling `end()`.
- All new behavior is OFF until separate trusted host opt-ins. There is no
  viewer/chat/model-facing permission path, new key, account, microphone,
  livestream, screenshot upload or gameplay input. VTube Studio must be
  installed, its plugin authenticated, and the 14 custom input parameters
  manually mapped to the artist's original rig.

### End-to-end host contract

1. Owner approves the stage, playout clock, device adapter, VTube Studio host
   and session independently. VTS authentication token resides in OS-protected
   local host storage, **not in source control or a model prompt**.
2. Stage accepts a real signal and creates a plan; host queues and actually
   starts speech, calls its audible acknowledgement, then arms
   `StarPlayoutClock` with the matching PCM envelope/duration.
3. Host binds `DeviceAudibleSampleHost` with actual sample rate and PCM
   duration; VTS connects and registers custom parameters.
4. `AudibleAvatarSession.bind(plan, epoch, playback_epoch)` binds **the same**
   stage, device identity and rig epoch. Calls to `report_played()` must come
   from the output backend's consumed-frame clock, never from queued PCM.
5. Render worker calls `render(epoch)` just before dispatch. No queue/replay
   is installed. Pauses/stalls receive neutral silence. On stop, Windows host
   flushes output **first**, then calls `end(epoch,
   output_stopped_and_flushed=True)`.
6. One owner-controlled worker must serialize these lifecycle calls. Direct
   concurrent calls to the underlying device/renderer bypass that invariant
   and are **not authorized**. Reconnects require explicit host recovery.

### Critical external acceptance

**The new tests use a fake VTS socket and host-simulated played samples.**
This does NOT attest that audio reached speakers or that OBS captured it.

Windows 11 real test: use a dedicated WASAPI shared-mode playback stream and
measure `IAudioClock::GetPosition` paired with
`IAudioClock::GetFrequency` / `IAudioClock2::GetDevicePosition` as applicable.
The playback queue's submitted frames are not equivalent to heard frames.
Treat QPC/device-clock drift, shared-mode resampling, underrun, cursor resets,
device hot-swap and interrupt races as failure conditions. The matching
monotonic clock passed to VTS and the playout clock must use the **same
timebase**; do not pass wall-clock Unix timestamps.

Record a local owner-approved synthetic phrase and OBS preview; check median,
p95 and worst-case audio/visible lip skew at 30/60 FPS, immediately neutral
mouth on pause, interruption/underrun and VTS disconnect. Record gaming FPS,
1% lows, OBS dropped frames, first audible token, p95 audio and vision
latency, VRAM, system RAM, CPU usage and localhost socket overhead while a
Roblox game is active. Test reduced-motion and cat/puppy rig mappings. Require
human-rated expressive quality; plausible data-driven motion does not imply
phoneme-grade lip-sync or human emotions.

VTube Studio's API defines `InjectParameterDataRequest`, custom parameter
registration and 1-second input timeout; the neutral hold prevents stale
mouth-open behavior during a paused speech turn. Input parameters do not
automatically map to an artist's Live2D *model* parameters.

- https://github.com/DenchiSoft/VTubeStudio/blob/master/README.md
- https://docs.live2d.com/en/cubism-editor-manual/standard-parameter-list/
- https://learn.microsoft.com/en-us/windows/win32/api/audioclient/nf-audioclient-iaudioclock-getposition
- https://learn.microsoft.com/en-us/windows/win32/api/audioclient/nf-audioclient-iaudioclock2-getdeviceposition

## Genuine intelligence improvement: new research and practical sequence

### 1. Test outcomes, not convincing descriptions

Roblox's **OpenGameEval** (October 1, 2026) evaluates agent edits in reproducible
Studio sessions with executable scene/play checks, 84 curated core tasks and
measured object inspection. Star should use its own staged Studio Lab with
holdout games and no test-answer leakage.
GameWorld spans **34 games and 170 tasks** using observable serialized state:
success is not "the model thought it won". Build an independent read-only
observer for authorized games and compare against agreed win/checkpoint
conditions. Separate exploratory, training, validation and locked tests.

- https://github.com/Roblox/open-game-eval
- https://gameworld-bench.github.io/
- https://github.com/gameworld-project/gameworld

### 2. Reusable visual memory that can learn new queries

**ReSight**, submitted October 24, 2026, separates retained observation
evidence from derived fields, then explores missing capabilities and distills
verified memory tools. For Star: retain owner-permitted **bounded keyframe
references** with game/version/time/scene provenance; put potentially wrong
AI captions in a separate derived layer. When a new gameplay question appears,
reprocess limited archived frames only with capture and privacy permission.
A lesson should reference verifiable frames/outcomes, not rewrite history.
Do not store viewers, account details or raw streams by default.

- https://arxiv.org/abs/2610.33487

### 3. Active research at the current skill frontier

**VISTA**, submitted October 26, 2026, maintains a graph of harness hypotheses
and tests variants with fresh rollouts; **AdaRSI**, October 14, distinguishes
tool-harness problems from cases that really require model fine-tuning. Star
Core Forge should track each candidate's lineage, observations, hypothesis,
CPU/GPU budget, independent test results and rollback. Attempt diagnosis
through code/search/tool improvements **before** spending GPU hours on training
a model that may be misconfigured.

**Active-Zero** (February 2026) motivates calibrated self-created multimodal
exercises, but do not automatically treat synthetic answers as ground truth.
Use available challenge difficulty and unseen settings to measure transfer,
not repeated memorization. Reject improvements with statistically unconvincing
success changes or large performance costs.

- https://arxiv.org/abs/2610.35051
- https://arxiv.org/abs/2610.20474
- https://arxiv.org/abs/2602.11241

### 4. Responsive models without degrading gaming

Measure TTFT, prompt/prefill/decode throughput, cache-hit fraction, p95
response time, VRAM paging, CPU offload and frame time under simultaneous OBS
and game workloads. Route tiny requests to a small fast model, complex
strategies to a larger model only when gameplay is stable, and postpone
experiments when the host signals frame drops. Distinguish CPU preprocess
savings from neural inference throughput and actual FPS improvements.

The llama.cpp server documents slot metrics/prompt caches; instrument the
**current installed version** first rather than hardcoding capabilities.
A continuously full KV cache is not automatically good: it competes with RAM
used by games and Windows file cache.

- https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md

### 5. Star as an engaging, natural gaming performer

Kyutai's **Pocket TTS v4.0.0 (October 20)** and bugfix **v4.0.1 (October 21)**
offer CPU-oriented 18M/7M/experimental 2M English configurations. Audition them
against naturalness, emotion range, spoken mistakes, interruption recovery and
first-audible latency; smaller does not inherently mean better. Use real
audible timing, not generated word timestamps.

A genuinely engaging virtual personality needs episodic continuity grounded
in events she experienced, specific humor, grounded enthusiasm, expressive
breathing/pauses, and comfortable silence when a game demands focus. Do not
invent human childhood, first-hand events or emotions she cannot verify.
Her chibi hair, ribbon, gaze, cat/puppy modes and Live2D physics should remain
artist-controlled and support reduced-motion.

- https://github.com/kyutai-labs/pocket-tts/releases

## Prioritized engineering gates

| Priority | Build/measure | Pass condition |
|---|---|---|
| P0 | Windows real consumed-audio clock -> VTS -> OBS | No stale mouth after pause/interrupt; bounded p95 A/V skew |
| P0 | Private/public repository audit | No tokens, private frames or viewer data in a public repository |
| P1 | Independent Roblox Studio game-state observer | Correct outcome labels on held-out verified tasks |
| P1 | Held-out performance gate under Roblox + OBS | No unacceptable FPS/voice regressions |
| P1 | Retrieval memory with separated evidence/derived notes | Can answer new questions using provenance without changing raw evidence |
| P2 | Source-backed knowledge and Star Core Forge harness graph | Accuracy/latency lift on unseen problems, rollback on regression |
| P2 | Voice model auditions and avatar quality review | Owner-rated naturalness, intelligibility and animation quality |
| P3 | Long-term challenge generation and genuine skill transfer | Improvement survives unseen seeds/maps/games |

**Status:** these are researched and prioritized next steps, not completed
model training, real device integration, game mastery or a live broadcast.
Keep this as a draft PR; the GitHub repo named `Star-AI-Private` is reported
publicly visible and must not be trusted as a private workspace.
