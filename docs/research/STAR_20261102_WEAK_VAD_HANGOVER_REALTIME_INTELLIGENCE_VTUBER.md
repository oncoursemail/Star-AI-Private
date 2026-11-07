# STAR — Weak-VAD speech safety, real-time intelligence and autonomous VTuber roadmap
**Research and implementation date:** 2026-11-02 (UTC)
**Status:** local deterministic correction and offline tests; NOT a live-audio, game, model-speed or OBS validation.
**Parent:** STAR gaming/VTuber draft PR #900 (stacked branch, not main).
**Design principle:** native, natural-looking AI character; genuine experiences, not fabricated claims of being human.

## 1. Newly reproduced real defect: weak speech classified as silence

`star.stream_turntaking.TurnTakingGate` offered `speak` immediately when the
last calibrated owner/guest VAD probability was in the range **(0.10, 0.50)**,
even though the same input did not qualify as verified quiet (quiet requires
both probabilities <=0.10). The previous legacy-mode hangover updated only
on probabilities >=0.50. In a live conversation the model could start
speaking over hesitant, low-volume or uncertain speech. Separately, an
`echo_cleared=False` frame followed by a single quiet observation could
produce an immediate `speak` decision without waiting for the echo-unknown
period to clear.

### Reproduction and correction
- A 30-ms host frame at 100ms with `owner=.35, guest=.0`, or
  `owner=.0, guest=.42`, led to `TurnAdvice(action='speak')`. Four new
  targeted cases initially **FAILED**, confirming the problem before repair.
- Mark non-quiet VAD activity (`max(owner,guest) > 0.10`) as a timestamped
  hold/hangover event. Treat uncleared echo as unknown, not trusted quiet.
- Preserve strong authenticated-owner barge-in (`owner>=0.75` with continued
  evidence), no interruption authority from uncertain speech, and all
  verified-quiet/recent-frame checks. The hangover is still 350ms, not
  an invented or dynamically tuned value.
- Keep the gate opt-in; no microphone input is read and no device/OBS action
  occurs. Physical microphone/AEC/DIAR configuration remains host-owned.
- A new `StarStage` integration test ensures uncertain viewer activity
  prevents the stage from creating the next spoken turn.
- **Risk:** the more conservative behavior may delay a response after noise,
  particularly if a VAD is miscalibrated. Compare with a preregistered,
  reviewer-labeled endpoint benchmark and tune the *upstream VAD* or
  opt-in verified quiet based on measured false-cutoffs versus dead air.
  Do not claim the correction is audibly better without recordings.

## 2. Research: humanlike timing is not simply minimum silence

LiveKit's open EoT benchmark compares end-of-turn delay at fixed premature
cutoff budgets. Its published English table reports that LiveKit Turn Detector
v1 reaches 543ms at a 5% cutoff budget, versus 1070ms for v1-mini. These
are *benchmark figures from other systems*, not STAR throughput or voice
quality. They support measuring the response latency/interruptions frontier
rather than choosing the smallest endpointer by parameter count.

STAR has `stream_endpointing_eval.py` with turn-scoped statistical
uncertainty. The next integration must feed **real prerecorded, reviewer
labeled, source-turn-grouped pauses** and include soft speech,
hesitations, overlapping speakers, clipped microphones, AEC failure,
playback bleed, accents, gaming exclamations and network jitter.
A fixed 350ms hangover is a conservative gate, NOT a semantic EoT model.
Speak/hold/yield decisions must remain separate from playback cancellation
and owner permissions.

**Acceptance (proposed, not achieved):**
- No candidate ships solely on lower average endpoint latency.
- Report median and p95 response, false-cutoffs *by source turn*, latency
  regressions on matched examples, missed ends and confidence intervals.
- Include "weak voice" and "echo unknown" adversarial strata.
- For owner barge-in, an independently authenticated speaker source and
  confirmed audio stop must precede scene cancellation.
- Sample the actual speaker output and avatar mouth response. Command
  issuance timestamps are not audible onset timestamps.

Source: https://github.com/livekit/eot-bench (observed 2026-11-02).
LiveKit's published benchmark does not establish STAR hardware performance.

## 3. Two-timescale autonomous game intelligence

Pan et al., *The World Won't Wait* (posted 2026-10-14) introduce
RealtimeBench: 180 live-clock game tasks and an offline teacher that writes
instructions for a fast online student. Their study reports a rise from
13.51 to 24.19 average progress points after two correction rounds.
This is independent research, not a STAR achievement.

For STAR, prioritize a **three-lane loop**:
1. **Reflex/host lane:** deterministic focus/consent/age/deadline gates.
   Do not call a large teacher while a frame deadline is active.
2. **Reactive student:** small, already warmed model selects an allowlisted
   symbolic action bound to the exact captured frame, always willing to
   abstain if the deadline or scene identity is invalid.
3. **Offline coach:** between authorized sessions, mine failed attempts,
   propose testable gameplay policies and compare them in held-out maps
   using identical starting states. Only promote strategies with independent
   trial evidence, confidence, and rollback data. Review cheating/game rules.

Treat simulator/prototype games separately from public competitive lobbies.
The offline coach's skill memo must never directly authorize key injection.
The router's latency budget must include capture -> dispatch, not only
neural token production. Temporal gaps and frame reordering are first-class
inputs, not "higher intelligence" failures.

Source: https://arxiv.org/abs/2610.20665 (2026-10-14).

## 4. Infrastructure design: protect GPU and stream reliability

Keep cross-device orchestration **deadline and resource aware**. A proposed
deployment boundary for the dedicated gaming machine is:

- **Game/OBS/avatar node:** render game, capture timestamped frames, host
  trusted device/audio focus checks, coordinate microphone, speech playback
  confirmation and avatar frames; stop all game actions on permission/focus
  loss. Cache current lightweight state.
- **Worker node:** serve specialist inference, research/retrieval and
  developer tasks behind bounded queues with health probes. Prefer small
  fast models during gameplay; defer heavy visual reasoning, Blender,
  training and game building to offline windows.
- **Conductor:** decision log with opaque IDs, bounded timestamps,
  cancellation acknowledgements, resource reservations and per-step
  provenance. No chat instruction can override game/OBS ownership.
- **Monotonic clocks:** timestamp observations and game actions in the
  SAME host domain; record network RTT/clock offset independently before
  remote comparisons. Avoid trusting raw timestamps across machines.

**Read-only hardware snapshot (2026-11-02 UTC, Main Windows PC):**
`nvidia-smi` reported RTX 3060 Ti, 8,192 MiB total, **345 MiB free**,
17% instantaneous GPU utilization, with `llama-server` running. Neither
OBS nor VTube Studio was detected in the requested process names. This is a
SINGLE snapshot, not a sustained capacity measurement or proof of a hardware
optimization. Do not begin a full GPU game+avatar+OBS rehearsal from such a
thin memory margin without first measuring the cause and reserving headroom;
consider a smaller realtime model or serving inference from another node.
Do not terminate owner workloads merely to improve a benchmark.

Benchmark explicit workloads, not theoretical VRAM fits: idle, speech only,
game only, game+OBS+avatar, full game+voice+inference, and recovery from
inference timeout. Record p50/p95/p99 **time to first audible output**,
token prefill/decode, capture-to-action, 1%-low FPS, OBS render/encoder drops,
VRAM peaks, CPU contention, power and thermal throttling.
Optimize the worst observed bottleneck first. Maintain a runnable baseline.

llama.cpp server documents parallel slots, continuous batching, caching,
speculative decoding, quantization, multimodal and monitoring capabilities.
Benchmark a fixed model/quant, same prompt/scene, fixed generation budget,
and measured response correctness before enabling a new decode scheme.
An issue filed 2026-09-05 (#28425, subsequently closed as stale) describes
recurrent/hybrid cache rollback concerns in particular configurations.
Treat it as a reported edge case, *not* a blanket assertion about all Qwen
or a verified bug on STAR; include back-to-back shared-prefix/chat-history
tests and memory-growth checks before trusting long-running hybrid serving.

Sources:
- https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md
- https://github.com/ggml-org/llama.cpp/issues/28425

## 5. Humanlike streaming — coordinated, grounded character behavior

Star should feel socially responsive without claiming to be human:
- **Listening:** low-confidence audio -> defer, meaningful pauses,
  avoid constant filler, interrupt only on independently confirmed owner
  signal, never echo-triggered owner authority.
- **Speaking:** local CPU-oriented voice candidates compete against GPU
  voice options using actual first-phoneme latency, emotion/prosody
  listener ratings, peak RAM, language quality and sustained-load failure.
  Use expressive punctuation sparingly; never fabricate wins or viewers.
- **Avatar:** VTube Studio's API offers custom parameters, hotkeys and
  model controls. Bind *measured playback envelopes* to lips, with smooth
  eye targets and bounded expression transitions; avatar should return to
  idle if audio stops, but should not imply a completed word if TTS failed.
- **Perception:** each camera/game observation receives a capture
  timestamp, game+episode scope, confidence and validity horizon.
  Reactions to old frames are dropped or converted into uncertain recall.
- **Social memory:** retain only approved, evidence-backed episode events;
  scope game-specific claims. Remember relationships only through
  legitimate, consented interactions. Never invent private facts.
- **Character autonomy:** have authored hobbies, art, music, game creation,
  self-assigned practice goals, playful moments with Astro/Amber, and
  self-assessment without asserting literal human feelings/consciousness.
- **OBS rehearsal:** begin nonbroadcast with authenticated read-only
  status/metrics, then test permissioned routing/recording separately.
  Overlay health/failure indicators must not leak host diagnostics to
  public chat.

Sources:
- https://github.com/DenchiSoft/VTubeStudio/blob/master/README.md
- https://github.com/DenchiSoft/VTubeStudio/wiki/Plugins
- https://github.com/obsproject/obs-websocket

## 6. Broader capability roadmap: creation, learning and knowledge

**Roblox game-building quality loop:** project inspection -> design
constraints -> generate alternatives -> static Luau checks ->
controlled StudioTestService/VirtualInput multiplayer/device tests ->
screenshot/geometry/collision audit -> rollback or accept with visual
and gameplay proof. Roblox docs explicitly describe multi-client
testing and virtual input; tests must honor studio authorization and
in-game rule restrictions. Add Blender geometry validation with actual
triangulation/collider bounds, rig bone naming and UV/artifact checks.
Judge maps, animation and UI *visually*, not just through unit tests.

**General knowledge:** indexed local source registry with fetched-at date,
license, reliability, retrieval confidence, contradiction tracking,
private/public authorization and expiring facts. Separate researched
claims from directly observed gameplay. Use a source freshness check for
live news/game patch facts; offline answers label uncertainty. Avoid a
single enormous static system prompt; keep stable persona/cache prefix,
retrieve small relevant verified notes for each task.

**Self-improvement:** difficulty ladder proposes harder games/build tasks,
verifier runs blind held-out tests, compares cost vs quality, rejects
regressions and stores semantic improvements with reproducible provenance.
Promote skill changes only after multi-seed evaluation; do not feed test
answers into the training set. Self-directed routines may run locally but
unrestricted external actions/purchases/public posts still need appropriate
owner-issued authorization and limits.

Source: https://create.roblox.com/docs/studio/testing-modes
(official Roblox documentation; inspected 2026-11-02).

## 7. Prioritized experiment backlog (not implemented here)

| Priority | Experiment | Measurable acceptance and rollback |
|---|---|---|
| P0 | End-to-end nonbroadcast Windows game+mic+TTS+avatar+OBS test | Real traces demonstrate matched source/ack for game, speech and animation; no unauthorized broadcast. |
| P0 | Weak-VAD and AEC calibration | Matched held-out pauses; fewer talk-overs without statistically worse p95 response latency. |
| P1 | Adaptive game latency route | Lower stale-action rate without worse multi-seed held-out win/progress score, under real FPS load. |
| P1 | CPU vs GPU voice on same 8-GB gaming workload | Measure p95 audible onset, 1%-low game FPS, quality ratings and GPU headroom; reject worse variants. |
| P1 | Parallel game-dev repair agents | Improve independently graded StudioTestService success/visual review per watt/hour. |
| P2 | Persistent self-directed lesson planner | Increasing challenge difficulty + validated transfer gains, no self-grading leakage. |
| P2 | Offline visual/animation director | Compare blinded viewer naturalness ratings and AV offset distributions; no invented experience. |

## 8. Evidence levels and explicit limitations

**Demonstrated in this change:** red test reproduction and deterministic
fix of weak VAD/echo uncertainty, plus an offline stage integration test.
This improves the *advisory decision*, not demonstrated voice naturalness.

**Not demonstrated:** new model weights, model training, independent game
mastery gains, real Steam/Roblox live gameplay, TTS first-audio improvement,
OBS streaming, audio hardware responsiveness or actual video naturalness.
Do not claim these until host-captured measurable evidence exists.

**Acceptance gate before any promotion:** tests and style checks pass;
uncertainty/interruptions show improvement on representative held-out
audio; host safety and session scoping remain intact; baseline rollback
is available; public streaming is separately authorized.
