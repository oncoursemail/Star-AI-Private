# STAR — Realtime game rehearsal QoS, intelligence and VTuber execution plan
*Engineering checkpoint: 2026-11-05. Research-backed proposals are not live feature claims.*

## Finding and implemented fix: private gameplay is realtime

**Reproduced defect:** In `star/stream_budget.py`, the older advisory only
protected live broadcasts. With `live=False, game_active=True` it returned
`allowed=True, sample_fps=4` for vision even at 500 MiB free VRAM, <45 FPS,
or >350 ms of buffered speech. It also admitted background training, rendering
and research during a **host-declared private VTuber rehearsal**. This is exactly the setup required
to rehearse Star's game-playing plus avatar, voice and OBS without broadcasting.
It risks making the very benchmark meant to establish smoothness contend for GPU
and CPU work. The `studio_vision_qos` implementation separately assumed that
all non-live capture was permitted at 4 Hz.

**Reproduced before fix:** five failed assertions and one uncaught
`OverflowError` in the focused budget test. The older policy reported
4 Hz during active nonbroadcast gameplay, let pressured vision through,
and did not convert a giant integer telemetry value into a bounded
validation failure.

**Code in this branch:**
- Reserve live-stream **or explicitly host-declared private rehearsal** time
  for gameplay and speech; defer training, rendering and research during those
  protected sessions. Ordinary nonbroadcast game-skill training is preserved.
- At healthy measured headroom, bound vision to **1 Hz** when playing a
  game, even if OBS is privately recording or streaming is disabled.
  Use the 4-Hz advisory only for offline sessions **without** an active game.
- Block vision on <1536 MiB free VRAM, measured game FPS <45, or
  speech backlog >350 ms whether or not Star is broadcasting.
- Propagate the authorized private-rehearsal bit from the trusted hardware
  host into resource advice. This prevents an offline practice engine from
  being accidentally treated like a streaming session.
- Make the Studio MCP visual sampling interval follow the *advised*
  sample FPS, including exponential duplicate-scene backoff. Otherwise
  reducing the advisory cap would not actually slow capture.
- Normalize giant numeric telemetry values to `ValueError` rather than
  allowing an `OverflowError` to escape into host scheduling.
- Keep workload advice read-only; it cannot launch inference, play audio,
  control Roblox or OBS, or authorize public streaming.

**Policy, not performance proof:** 1 Hz is only a conservative default.
No actual latency, quality, frame pacing, or GPU speedup is claimed here.
Increasing the cap requires measured frame-time headroom, not intuition.

## Priority 1: demonstrate a complete *private* Windows VTuber episode

Existing pieces include local game/OBS/voice watchers, game-input gates,
recording artifact audits, PCM playback audits, dynamic streaming admission,
and signed learning evaluations. Integrate these through a single ephemeral
episode ID with independently sampled timestamps and explicit scene/worker
epochs. Run on the authorized Windows game PC:

1. Confirm OBS broadcasting is OFF; confirm recording on a local private
   profile, selected audible Star track and legitimate game/window identity.
2. Obtain actual GPU/CPU memory, presented-frame intervals (p50/p95/p99),
   voice backlog, TTS first-audio, and avatar frame events from host sensors.
   Never ask the LLM to estimate its own FPS or whether it was audible.
3. With authorized test-game input, perform a reproducible practice task.
   Record state transitions and outcome receipts independently of Star's text.
4. Inspect the finished recording for game picture, recorded (not merely
   synthesized) voice, lips-to-audio offset, pauses and movement continuity.
5. Fail closed for unobserved FPS, stale sensors, output-device changes,
   unreliable game scope, capture glitches, or missed recordings. No broadcast.
6. Compare paired *game+voice+avatar+OBS* runs rather than standalone model
   tokens/sec. Report p95 first-audio, p95 game frame time, visual freshness,
   action success, verified audio coverage, p95 AV offset, and error rate.

Suggested acceptance experiment, *not a measured result*: require a completed
5-minute private episode with no unverified game-action success, no unintended
live broadcast, all media tracks inspectable, and no sustained frame-time
regression from a control run. Calibrate latency and A/V budgets empirically
on the Windows hardware and an independent reviewer rubric.

## Priority 2: intelligence through verification, not unchecked recursion

- **Game creation:** Inspect the Studio scene and scripts before editing;
  generate a small set of candidate Luau patches; static-analyze and run
  independent playtests before promoting a patch. Roblox's built-in MCP
  server and playtest agent make this a concrete plan/build/test loop.
- **Held-out game skill:** Record initial policy fingerprint, seed/scenario
  set, permitted input protocol and baseline *before* trials. Use blinded,
  unfamiliar levels; balance candidate and baseline execution order; separate
  movement, navigation, tactical planning, and chat/streaming interference.
  Report confidence intervals and time-to-recovery, not just one win.
- **General knowledge:** Maintain source links, provenance, retrieval
  timestamps, contradicting evidence, and explicit unknowns. A model should
  not store its own unsupported assertion as a proven lesson.
- **Self-improvement:** Reserve GPU-heavy training and video work for
  offline non-game windows. Make every code experiment reversible in Star's
  internal Forge with hashes, offline tests, review gates and automatic
  rollback when a promoted change fails independently verified metrics.
- **Fast/slow separation:** Serve short acknowledgments and
  high-confidence gameplay reactions on a small low-latency path. Route hard
  research, coding and strategic tasks to a slower reasoning worker; cancel
  stale tasks when scene epochs change. Background drafts never get speech or
  game-input authority without the existing output gates.

**Measurement:** create a benchmark manifest with model SHA, GGUF
quantization, context size, input prompt hashes, warm/cold cache policy,
GPU allocation and concurrency. Compare cold prompt processing,
time-to-first-token, p50/p95 generation, first audible PCM, speculative
draft acceptance, total system RAM/VRAM and frame-time impact. llama.cpp
SPEED-Bench is a starting methodology, not a promise of speed gains.
Try prompt-cache reuse, bounded retrieval and speculative decoding only when
they improve *task accuracy per second* and obey GPU admission.

## Priority 3: natural and expressive AI VTuber behavior

Natural presence is a coordination problem, not merely a larger language model:

- **Perception:** Timed game events from trusted observations; a rolling,
  low-detail game-state summary; viewer-chat attention budget; detected
  dialogue turns from local VAD/ASR with source consent.
- **Turn taking:** Decide whether a reaction is worth interrupting game
  focus; suppress repetitive commentary; allow brief acknowledgments,
  thinking pauses, listening gestures, overlap repair and silence.
  Use owner-authenticated interrupt checks, echo cancellation and actual
  device-stop receipts. Do not infer owner identity from voice similarity.
- **Expressivity:** Link facial expression, blinks, gaze and motion to
  *verified* game moments and actual audible speech. The same output epoch
  must govern PCM, mouth and body frames; delayed model output is discarded
  after scene changes. Respect reduced-motion mode and user-selected modes.
- **Consistent character:** Persistent interests, selected hobbies, recognizable
  humor, explicit recalled experiences and evolving preferences. Distinguish
  memories of actual episodes from creative persona lore. Permit owner review
  and redaction; do not invent memories to appear human.
- **Social behavior:** Natural greetings and goodbyes, contextual references,
  collaborative play, clear consent for voice/chat recording, moderation and
  anti-harassment tools. Identify Star as an AI VTuber, not an actual human.
  Unrestricted imitation is not needed to be an entertaining personality.
- **Voice choices:** Benchmark CPU-only Pocket TTS (including October 2026
  small-English checkpoints) against the current TTS *on this machine* for
  expressive quality, CPU/VRAM use, first-audio and A/V alignment. Kyutai
  Moshi's full-duplex approach inspires turn-taking, but its heavier model
  is **not** assumed practical alongside an 8-GB GPU game. Consider a
  modular VAD+ASR+LLM+CPU TTS pipeline first, with a private A/B voice rubric.

## Research sources (verified on 2026-11-05)

- Roblox Studio's native MCP server / simulated-input workflow
  (Roblox Developer Forum, 2026-03-05):
  https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643
- Roblox Studio's built-in playtest agent beta (2026-04-09):
  https://devforum.roblox.com/t/studio-beta-studio-assistant-mcp-playtest-agent/4566767
- Roblox's agentic plan/build/test overview (2026-04-15):
  https://about.roblox.com/newsroom/2026/04/roblox-studio-going-agentic
- OpenGameEval paper (2026-10-01) and reproducible tasks:
  https://arxiv.org/abs/2610.02563
  https://github.com/Roblox/open-game-eval
- Microsoft Proact-VL (ICML 2026): proactive gaming comments,
  selective timing and multimodal response quantity:
  https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/
- Kyutai Pocket TTS (October 2026 small CPU models):
  https://github.com/kyutai-labs/pocket-tts
- Kyutai Moshi dual-channel streaming speech architecture:
  https://github.com/kyutai-labs/moshi
- Unity ML-Agents (curriculum, randomization, imitation, evaluation):
  https://github.com/Unity-Technologies/ml-agents
- llama.cpp SPEED-Bench (latency, throughput and speculative acceptance):
  https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md

## Acceptance gates

The branch changes *resource advice and visual-capture cadence*, not the
base model or any computer-control permission. Before promoting, run both
focused QoS tests and broader offline gaming/streaming/Roblox regressions,
then a private hardware-in-the-loop session. Verify that idle/offline
development can still use 4-Hz visual sampling, that a private game is
bounded to 1 Hz, and that resource pressure cancels nonessential work.
A draft PR must remain separate from main until independent CI passes;
no public streaming should be auto-enabled as a side effect.
