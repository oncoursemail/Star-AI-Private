# STAR AI — independent frame-age enforcement and generalist VTuber roadmap

**Research date:** 2026-11-06. **Scope:** owner-controlled private game/Studio laboratories and
a later, separately approved OBS/voice/avatar rehearsal. **Status:** this change implements
one bounded timing guard; the remaining items are research and prioritized validation plans.

## The concrete defect addressed

The existing `NativeGameRoundtripAudit` already checks frame age using a monotonic
measurement clock injected into the audit and independently checks native host-call elapsed
time. But a frozen, faulty, or injected measurement clock can conceal an *old game frame*
during decision making, before the Windows input port is called. A previous real-clock
check protected the *native worker* but not the **capture → reasoning → dispatch** interval.

This revision begins an independent host `time.monotonic_ns()` stopwatch when `capture()`
begins, before sampling the benchmark clock. It rejects old or regressed independent
readings at `decision_ready()`, `no_action()`, and `execute()` **before any native
input**. Rejected actions revoke the whole measurement window rather than cherry-picking
good frames. Tests simulate a frozen benchmark clock and delayed real host time.

These checks are **additional**, not alternatives, to frame sequence coverage,
focus, key-up, watchdog, native-call budget, and observable game-state changes.

**Boundaries:** the OS stopwatch starts when the adapter receives a frame, not when
the graphics driver produced it. For true camera/game-state age, the trusted Windows
host must supply and authenticate capture timestamps from an independent source. This
change does not drive a game, train a model, speed up inference, grant stream
permission, or establish skill mastery. It remains opt-in with explicit owner approval.

## Generalist gaming intelligence: the next useful integration

STAR already contains `game_realtime_loop`, `game_state_transition_witness`,
`game_action_outcome_feedback`, `game_practice_curriculum`, and
`game_skill_gate`. Focus on composition, **not a fifth competing memory store**.

1. **Reactive lane (10–50 ms target where host hardware permits):** lightweight
   model/policy acts on fresh, permitted observations only; never wait for slow
   image captioning when a deadline expires. A no-op is a legitimate recorded
   decision, not a missing sample. Use the host's independent clock to gate input.
2. **Tactical lane (hundreds of ms):** selectively retrieve short verified
   strategy snippets, choose a high-level objective, and explain/adjust policy.
   Any plan surviving a scene transition requires fresh revalidation.
3. **Reflective lane (offline, resource-aware):** replay *authenticated* failures
   and test alternative tactics in isolated game simulators. Never claim practice
   gains from the same episodes used to choose the tactics.
4. **Skill proof:** report episode success **and** normalized progress, input
   validity, observed frame coverage, wall-clock latency, failures, abstentions,
   and elapsed play time. Stratify by unseen seeds, genres, and mechanics.
   Evaluate real-time and paused-environment tracks separately.
5. **Counterfactual learning:** the signed state observer can prove the host
   reported a checkpoint/win/loss; it does NOT prove that an immediately preceding
   action caused it. Randomize strategies in safe lab runs, use baseline
   comparisons, and retain a skill only after improvement is independently
   reproduced. Mark no evidence as *unknown*, never as success.

**Evidence:** GameWorld (April 2026) offers 34 browser games, 170 tasks, engine
state-based success/progress, and an explicitly separate real-time variant:
https://gameworld-project.github.io/ and https://arxiv.org/abs/2604.07429 .
GameDevBench's ICML 2026 research establishes the importance of visual feedback
in real engine game-development tasks: https://sethkarten.ai/papers/gamedevbench.html .
Neither benchmark's published scores measure STAR until STAR is evaluated on them.

## Inference and hardware efficiency: measure speed, not just tokens/s

Current Windows observations from preceding authorized diagnostics showed an
8 GiB RTX 3060 Ti with very little unallocated VRAM during sampled activity.
Treat those measurements as **time-local**, not present certainty. Prefer
CPU-side voice after verification and refrain from launching extra GPU workers
just because utilization percentage looks low.

- Run a read-only `stream_gpu_budget_diagnostic` sampling window **while** game,
  OBS, avatar and speech are active. Admission must reserve game/encoder/desktop
  headroom and refuse unknown telemetry; never silently unload another model.
- Collect p50/p95 for request queueing, prompt prefill, first *audible* PCM,
  decode, frame arrival, action release, OBS render and dropped frames.
  Token throughput alone is not responsiveness.
- Benchmark a *fixed* prompt/task set in two conditions: single-model baseline,
  then optimized caching/speculative decoding. Hold context length, concurrency,
  quantization and output length fixed. Measure speculative draft acceptance;
  a larger draft can worsen latency on constrained GPUs.
- Keep prompt KV caches per authenticated session. No shared viewer chat/KV
  state unless an isolation test confirms an explicit boundary.
- Make fast-path reactions and speech less work for the large reasoner: fixed
  high-confidence event templates, pre-validated short reactions, interruption
  cancellation, and rate-limited expensive reasoning. Do not drop or fabricate
  negative gaming evaluations to improve a latency chart.

**Reproducible upstream method:** llama.cpp's official SPEED-Bench
(https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md)
reports latency, prompt/decode throughput and draft acceptance with a baseline
versus speculative decoding comparison. It is a method to adapt, **not evidence
of performance gains on STAR's GPUs**.

## Streaming as a natural, trustworthy AI VTuber

Natural does not mean continuously talking or concealing being AI. The goal
is contextual awareness, appropriate silence, low-latency conversation,
consistent interests, and expressive speech and animation.

- Maintain three independent channels: **physical action**, **speech floor**,
  and **facial/body expression**. Each has its own bounded queue and emergency
  stop. An animation may not outlive its audible speech epoch.
- Use existing `stream_turntaking`, `stream_interrupt_host` and
  `stream_social_turn_benchmark` instead of replacing proven components.
  Owner barge-in needs authenticated, echo-cleared, sustained VAD plus a
  verified physical playback stop. Guest speech can hold STAR's next turn,
  not grant access to microphone, computer or game input.
- Author conversational priority from grounded evidence: owner interruption,
  urgent game event, direct viewer question, new social message, optional
  commentary. During combat or time-critical navigation, deliberately
  **stay quiet**, shorten responses and suppress nonessential model calls.
- A persistent character journal should store only short, sourced summaries of
  confirmed gameplay and approved conversations, not falsely invented
  relationships, victory claims, private viewer details or credentials.
- Introduce *backchannels* (short acknowledgment or nonverbal nod), laughter,
  emotion/face gestures and memory callbacks only when grounded by observed
  events. Document that STAR is an AI VTuber.

NVIDIA DyaPlex (June 2026) researches streaming full-duplex speech + motion:
https://research.nvidia.com/labs/amri/publication/nagano2026dyaplex/ .
ELLSA 2 (October 15, 2026) evaluates simultaneous listening/speaking and
nonverbal expressions while silent: https://arxiv.org/abs/2610.21452 .
These are promising architectural references, not drop-in Star modules.

**Offline acceptance rubric:** matched prerecorded case pairs for viewer
question, incidental sound, authenticated owner barge-in, critical gameplay,
and game success/failure. Required: independently verified audible onset,
no undesired interruption, limited cross-talk, stopped old PCM after barge-in,
neutral avatar reset, low unplanned speech gaps, no hallucinated game claims.
For live operation, add independent human review of persona quality and comfort.

## Game creation & Roblox Studio automation

Roblox added built-in Studio MCP playtest controls in March 2026 and expanded
MCP-per-game Open Cloud access on **Nov 4, 2026**. On **Nov 5, 2026** it
introduced a **beta** R15 prompt-to-animation tool and optional R6→R15 motion
rebuilding through Studio Assistant/MCP.

Official:
- https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643
- https://devforum.roblox.com/t/studio-mcp-server-updates-open-cloud-access-in-your-mcp-client-and-asset-import-workflows/4975849
- https://devforum.roblox.com/t/studio-beta-generate-r15-animations-from-a-prompt-plus-optional-r6-motion-rebuilder/4977709

Integrate with STAR's existing Luau parser/linter, Studio source bridge,
script/visual checks, replayable build verification and permission isolation.
Autonomous experimentation belongs in a local throwaway place/session; only
known-passing code, assets and moderation-safe animation previews should be
proposed for production. Model-generated assets may require moderation and
cannot always be deleted through Open Cloud. Never use live datastore writes,
publish, payments, or player moderation as practice actions.

## Ordered next implementation milestones

1. **Host frame-origin witness:** bind a trusted engine/capture sequence and
   timestamp to each invocation, then test dropped/reordered/delayed frames.
2. **Causal feedback lab:** separate observed game progress from genuine
   strategy improvement via paired seeded trials, held-out episodes, and
   signed source/renderer evidence.
3. **Windows offline end-to-end rehearsal:** pinned test game + native input
   worker/watchdog + game-state source + voice/TTS + avatar + OBS recording.
   Measure dropped frames, inference and audible latency concurrently; do not
   interpret submit receipts as successful real-world actions.
4. **Resource-aware action/speech scheduling:** when VRAM pressure or stream
   latency crosses a benchmarked threshold, shed discretionary research and
   commentary *before* the game or audio device suffers.
5. **Character interaction evaluation:** human-reviewed natural pacing,
   expressive animation, grounding, humor, and recoverable mistakes alongside
   objective technical timing results.

### Verification to run in this PR

- Targeted native-audit and frame-coverage tests with simulated frozen clocks.
- Windows port/watchdog and OBS/game action regression selections.
- Static Python compilation, Ruff, and Git whitespace checking.
- Independent CI and real Windows+OBS hardware trials remain outstanding
  until explicitly executed and their results inspected.
