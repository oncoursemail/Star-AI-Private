# STAR AI — Real Host Gameplay/OBS Measurement Bridge and Intelligence Plan
**November 4, 2026 — tested engineering record**

## What this change actually delivers

The previous staged change added `game_load_shift_guard.py`, a read-only
comparator of two windows of gameplay/OBS performance. However, it requires
`GameLoadSample` records assembled by the caller. A simulator, a stale OBS
snapshot, or twenty records copied from the same OBS frame interval could be
misleading. This iteration adds `star/game_load_host_bridge.py` and adversarial
tests for a **real-host input composition contract**, reusing three already
implemented modules:

- `CaptureToActionTrial` contains measured host phase timestamps, a separate
  OS input acknowledgment, and independent game-world frame progression.
- `ObsStatsWindow` turns **two OBS GetStats counter readings** into an
  interval-specific `ObsLagWindow`. An OBS lifetime skip percentage is not
  equivalent to a measurement of the relevant action interval.
- `GameLoadSample` / `assess_game_load_shift` compare successive windows
  while retaining lost input acknowledgments as bad outcomes, not fast ones.

`GameHostLoadTick.to_sample()` validates clock-domain enclosure, input
acknowledgment/world-motion consistency, game/version IDs, both OBS
render/output skip percentages, and finite GPU headroom. An absent input ack
becomes `None`; a frozen world with an acknowledged input **cannot** count
as a clean sample.

`assess_host_game_load()` rejects repeated/overlapping OBS counter intervals,
replayed capture ordering, distinct AI A/B variants (this is NOT an A/B model
test), unbounded traces, and unverified host flags. It compares separately
sourced real-host evidence *if the trusted host supplies it*.

**Boundary:** The repository code is a deterministic **offline adapter**.
Tests construct *synthetic* `CaptureToActionTrial` and `ObsLagWindow`
instances. This iteration did NOT run OBS, a game, a local model, a microphone,
voice synthesis or a livestream. `host_verified`, `independently_measured`
and `obs_continuity_verified` are untrusted Boolean assertions from Python
objects, NOT signatures or physical authentication; a trusted sampler is still
required. Even a stable report cannot authorize gameplay, promote a learned
skill, or start a broadcast.

### Reproduce

```bash
python -m pytest -q tests/test_game_load_host_bridge.py \
  tests/test_game_load_shift_guard.py \
  tests/test_game_capture_to_action_benchmark.py \
  tests/test_obs_stats_window.py
python -m ruff check star/game_load_host_bridge.py tests/test_game_load_host_bridge.py
```

## Why this is the next useful integration

The recent synthetic load curriculum can learn a timing correction in its
own simulator. It cannot infer a controller's true action latency on Windows.
Likewise, valid `SendInput` calls acknowledge OS input insertion, **not**
recognition of the command in a game's world state. We must separately measure
`game_state_after_action` from a permitted instrumentation source, never
from model narration. See Microsoft's SendInput documentation:
https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendinput

An OBS `GetStats` reading reports running counters, not the precise skip
percentage in the last individual game action. Use two readings and delta
calculations as `ObsStatsWindow` already does; avoid interpreting
`outputSkippedFrames` as an exact hardware encoder root cause. Source:
https://github.com/obsproject/obs-websocket/blob/master/docs/generated/protocol.md

### Proposed nonbroadcast Windows capture sequence (still unperformed)

1. Launch a local, **private**, permitted game or Roblox Studio test, with the
   owner's approved game/control scope. Disable streaming destinations.
2. Start a **local OBS recording only** using an owner-approved host. Bind to
   one OBS process/session and a read-only continuity witness. Never move
   stream keys, frames, chat, or microphone bytes into metrics records.
3. Collect two independently timed GetStats readings per observation, actual
   game frame progression, capture/transfer/preprocess/inference timestamps,
   OS input acknowledgement and release confirmation. Include timeouts.
4. Ensure one monotonic Windows clock drives all measurements; attach one
   interval to **one** trial; never reuse the same OBS interval as 20 distinct
   data points. Measure baseline and subsequent load windows with the
   **same game build, model configuration, host and workload profile**.
5. Capture 20+ samples/window for each preregistered workload: idle,
   game only, game+OBS local recording, then game+OBS+voice+avatar+AI.
   Compare full-path p95, maximum single stall, p99 game frame,
   worst OBS render/output skips and free VRAM.
6. Stress for at least 20 minutes for load/thermal drift. An inconclusive
   or degraded window triggers **manual investigation**, not automated
   broadcast or "model got smarter" claims.
7. Verify separately that the game actually advanced/awarded progress, that
   keyboard/mouse releases occurred, and that audible PCM was stopped after
   an interruption. The drift adapter cannot establish any of those outcomes.

## Research priorities for faster Star AI on 8-GB VRAM systems

**Measure independent milestones, not just tokens/sec.** For a fixed
model/quant/context and task suite, compare TTFT, prefill, decode, p50/p95
response time, answer correctness, benchmark task pass rate, and idle vs
game+OBS+voice QoS. Allocate GPU headroom first to the running game, OBS,
and avatar; admit heavy local models only when resource telemetry permits.
The October/November 2026 llama.cpp SPEED-Bench is useful for model-server
throughput and speculative acceptance, but cannot demonstrate game skill:
https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md

**Multi-tier intelligence scheduler** (design, not deployed by this PR):
- Fast reactive lane: short model/context, hard capture-to-action deadline,
  cached executable action policies, simple stop/abstain when stale.
- Tactical lane: brief horizon planning, mechanic model, object tracking,
  event priorities and hypothesis checks. It can be interrupted by the
  reactive lane; no hidden blocking in the input path.
- Offline research lane: higher-capacity reasoning, web/document retrieval,
  competing code candidates, self-generated exercises, and programmatic
  tests. Store provenance and separate held-out evaluation data; do not
  rewrite success criteria after seeing results.
- Resource arbiter: admit work based on real free VRAM/CPU pressure,
  game frame times, encoder skips, and voice queue health; cancel noncritical
  research first. Compare fixed-seed paired tests at matched workload.
- Learn from verified game outcomes (progress/loss) without assuming causal
  credit from an unrelated checkpoint. Reward updates should require
  repeat trials, novelty checks, anti-leakage holdouts and transfer tests.

No universal speed multiplier is defensible without these measurements.
Speculative decoding, larger contexts and GPU offload sometimes **increase**
latency under memory pressure. Route only verified experiments into runtime.

## Humanlike, expressive VTuber behavior — feasible measurable targets

The goal is to make Star a believable **AI performer**, not to misrepresent
her as a human. Prioritize lived continuity: what happened in the last
battle; whom she is speaking to; what she is attempting next; how reliably
she knows it; and when silence is more useful than speech.

- **Perception:** Timestamped scene/event features, not invented game
  results. Use consistent evidence keys for object and outcome references.
- **When to speak:** Two independent policies: event relevance and
  interruption/scene urgency. Suppress or defer quips during dangerous
  actions and drop outdated responses when the scene changes. Microsoft's
  Proact-VL (ICML 2026, May) directly studies *when* gaming companions
  should respond, not only content:
  https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/
- **How to listen:** Short, optional acknowledgments, predictive turn-taking
  and appropriate turn-claim aggressiveness. Microsoft's RESPOND (March
  2026) proposes controls for backchannel intensity and early turns:
  https://www.microsoft.com/en-us/research/publication/respond-responsive-engagement-strategy-for-predictive-orchestration-and-dialogue/
  Benchmark *interruptions that actually stop audio*, not merely scheduler
  flags, plus the rate of talking over a teammate.
- **Voice:** Compare naturalness, audible first-chunk latency, CPU use,
  timing stability, forced stop, character voice consistency and license
  before using a new model. Kyutai's Pocket TTS October 20–21, 2026
  releases added 18M/7M/2M English small variants; **candidate only**:
  https://github.com/kyutai-labs/pocket-tts/releases
- **Avatar:** Viseme timing from emitted PCM, emotion tags grounded in the
  context, breathing/blinks/micro-gestures, physical hair/ear movement with
  bounded rig budgets, and reduced-motion support. Test capture-to-visible
  reaction at 60 FPS under GPU contention; expression quality needs human
  review.
- **Personality and memory:** Episodic, source-linked game memories,
  stable voice/style preferences, recurring jokes and self-directed goals;
  allow forgetting/correction and disclosure that Star is AI. Do not
  manufacture personal encounters or claim human consciousness.

Proposed VTuber evaluation: perceived conversational naturalness from
blinded human raters, false commentary rate, interruption success rate
(audible PCM actually stops), backchannel precision, OBS frame skip rate,
frame p99, 20-minute stability, and recovery after microphone loss.

## Autonomous games and general knowledge beyond the stream

Roblox's March 5, 2026 built-in Studio MCP server allows external assistant
workflows including playtest and input simulation. Roblox's April 15, 2026
agentic roadmap adds plan/build/test workflows. StudioTestService provides
multiclient automation. Integrate project discovery → verified asset/script
modifications → Luau lint/tests → Studio multi-client playtest → measured
game outcomes → snapshot diff → rollback of failures. Sources:
- https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643
- https://about.roblox.com/en-nz/newsroom/2026/04/roblox-studio-going-agentic
- https://create.roblox.com/docs/reference/engine/classes/StudioTestService

For general knowledge, use retrieval with source timestamps, uncertainty
categories, and verifier tools per answer. Convert **validated** solutions
to reusable skill cards, not indiscriminate model self-training. For game
strategy use a curriculum (observe controls → basic movement → goals →
timed reaction → adversarial scenarios → multiplayer coordination), held-out
scenarios and durable versioned progress. Do not automate online competitive
games where bot control would violate the rules.

## Priority list after this PR

**P0:** Trustworthy Windows passive sampler for a private nonbroadcast
rehearsal, with real capture timings, OBS counter windows, GPU metrics and
separately verified input release. This remains the major missing capability.

**P1:** Link load-drift observations to the existing scheduler in **advisory**
mode; no automatic deployment or streaming switch. Record thermal drift and
fallback behavior on 8 GB VRAM.

**P2:** Real audible TTS interrupt/viseme synchronization, with repeated
recording-based blind evaluation; preserve game FPS and OBS quality.

**P3:** Roblox Studio playtest robot with reproducible challenge packs and
multiplayer holdouts, tracking actual outcomes and regressions.

**P4:** Offline model speed/quality A/B matrix and role-specific memory
benchmarks, then feature-gated reversible rollout.

Security posture: local/offline-first, no arbitrary external commands from
game/chat content, least-privilege permissions, no secret logging, optional
features off by default, owner approval for high-risk/public external
operations. GitHub is a publishing mirror, not a prerequisite for Star's
future integrated local development and rollback system.
