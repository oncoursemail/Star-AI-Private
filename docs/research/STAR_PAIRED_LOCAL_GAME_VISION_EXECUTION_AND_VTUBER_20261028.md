# STAR: real paired-model game-vision execution and broader intelligence research
**Engineering date:** 28 October 2026 · **Status:** implemented offline integration, not deployed to Windows/OBS.
**Applies to:** Star's local-first Roblox and multi-game agent; Star's dedicated streaming PC with 8 GB-class NVIDIA GPU.

## 1. What actually changed

The previous `PairedVisionTraceHost` and `stream_vision_eval` can store and
score blinded categorical predictions, but they relied on an external host to
run *both* configured visual models on identical screenshots. That is an
important missing execution link. It is not enough to declare a trace
"trusted" without verifying that two variants actually received the same RGB.

The new `PairedOfflineVisionRunner` (`star/stream_vision_pair_runner.py`)
bridges `LocalLlamaComparisonWorker` to `PairedVisionTraceHost`. For each
approved private/offline game frame pair, it:

1. Requires explicit owner, offline capture and local-model approval. The
   original trace host must also be explicitly enabled by the authorized host.
2. Validates frame dimensions, freshness, layout, order, pair gap and host clock.
3. Takes an **independent in-memory snapshot of each RGB image**, computes the
   SHA-256 digest of the exact current snapshot, and reserves a single trace.
4. Runs two dedicated llama.cpp workers serially and resets each worker's
   previous-frame reference. Both workers see the exact same snapshots.
5. Alternates baseline-first/candidate-first order by host frame sequence to
   reduce systematic warm-cache/order bias. This is not statistically random
   and cannot eliminate all machine-state bias.
6. Records one categorical outcome and host-clock latency for each worker.
   A malformed response counts as error, never success or an inferred absence
   of change. Valid no-packet completions are counted as skipped.
7. If server inference may still be running after a timeout or exception,
   **aborts the entire cohort**, poisons the runner and preserves the worker's
   own quarantine. A client timeout is NEVER proof of physical termination.
8. Best-effort zeroes temporary RGB snapshots and resets JPEG caches when done.
   No frames, audio, chats, arbitrary captions or raw prompts are exported.

An authorized evaluator must separately freeze ALL model predictions with
`traces.seal_predictions()`, then independently label the frames with
`traces.record_truth(..., truth_source="studio_engine" | "human_annotation")`.
Only after that may the owner request the aggregate report or export to a
private non-Git directory. No runtime outcome label can be supplied by either
model. No model may promote itself to production.

### Why this is valuable

STAR can now execute *real local-model inference* through the same bounded
schema as her existing vision worker in an A/B test harness, rather than
requiring a future custom caller to build the entire experiment protocol. The
unit tests use synthetic images and fake local-model HTTP responses; they prove
contract behavior, **not** model accuracy or game success. The production
Windows frame acquisition/engine truth adapter and real GPU tests remain
unimplemented.

Example host-only sequence (pseudocode, not an automated capture tool):

```python
traces.enable(owner_approved=True, offline_capture_approved=True)
# Two dedicated LocalLlamaComparisonWorker instances, configured by owner.
runner = PairedOfflineVisionRunner(
    traces=traces, baseline=baseline_worker, candidate=candidate_worker,
    clock_ms=host_monotonic_ms,
)
# previous/current: already approved CapturedVisionFrame, same private
# sandbox game/window, host verified identity and geometry:
result = runner.run_pair(
    101, previous, current,
    owner_approved=True, capture_approved=True, model_approved=True,
)
# Repeat on held-out novel frames. Freeze first, then reveal independent truth.
traces.seal_predictions()
traces.record_truth(
    result.ticket, labels=(("hud_change", "hud"),),
    truth_source="studio_engine", independent_scorer=True,
)
aggregate = traces.owner_report(owner_approved=True)
```

Do not hand `runner`, `traces`, worker `enable`, capture flags or image
buffers to the LLM as tools. These belong exclusively to the trusted local
host. `independent_scorer=True` is a contract marker, not proof of Roblox
engine authentication. The host must establish independent source provenance.

## 2. Important limitations and real-world acceptance gates

The RGB snapshot protects against mutation of a source capture between model
calls. It does **not** prove that the capture is a legitimate game frame. A
separate authorized Windows host must validate HWND/PID, user consent, offline
game mode and exact game version. It must use its own trusted monotonic clock.

The second model is run later than the first, so slow inference can exceed a
live latency budget even though the frame is the same. Counterbalancing
reduces order bias but is not a substitute for controlled real-device tests.
For comparisons, hold visual context, quantization, resolution, system prompt,
sampling parameters, GPU/CPU placement and background load fixed. Alternate
order, log *both* failures, and use independently labeled hard negatives.

The trace's current evaluation labels are only a small list of *visible
differences* such as HUD changes. A detected HUD change does not prove a
player won, a jump succeeded or the game was completed. For autonomous play
and game creation, combine the vision findings with the separate signed
`GameplaySkillBank`, `GamePredictionLab`, `GameActionGate`, and Roblox
Studio engine executable tests. Keep evaluation holdouts excluded from
training, retrieval and self-generated exercise hints.

**Required Windows/OBS acceptance (NOT performed here):**
- Start with a private Roblox Studio place and dedicated capture process; verify
  old/current frames from one exact pinned window and the same game version.
- Run baseline and candidate locally with actual image-capable llama.cpp model
  loads; verify schema/constrained JSON support for the installed server build.
- Include failures, no-event frames, moving scenes, tiny HUD changes, menu
  overlays, identical-image pairs, and out-of-distribution games.
- Measure vision F1/precision/recall, false alerts, stale-rate, timeout-rate,
  first-response latency, p95 worker duration and average CPU/JPEG overhead.
- Also measure game FPS, 1% lows, OBS dropped frames, GPU/VRAM utilization,
  speech backlog, first-audible voice response and avatar lip-sync skew.
- Run A/B variants on the same machine with order varied; reject any candidate
  that loses game FPS, makes false hazard claims or worsens conversational QoE.
- Owner reviews the blinded aggregate result and approves any manual pilot.
  The quality gate is not a deploy button.

### Model/stream scheduling on an 8 GB GPU

The next meaningful speed improvement is NOT another tiny RGB shortcut.
Live frame-to-response inference measured in seconds cannot drive moment-to-
moment game inputs at 60 FPS. Reserve a fast symbolic/game-state path for
reflexes and a slower on-demand visual model for hard perceptual questions.
Use independent engine telemetry for fast actions, verified scene-state
checking for Roblox building, and VLMs for semantic visual novelty.

Prefer two or three resource pools: high-priority gameplay/OBS; bounded
speech/audio; best-effort vision/research. Use admission control keyed to real
FPS, VRAM, CPU, model queue depth and voice backlog. The existing governor
already provides a starting point. On low VRAM, test CPU-based speech rather
than keeping another voice model resident in GPU memory. Measure end-to-end
effects: CPU TTS may save VRAM but cause CPU contention and frame stalls.
Do not disable hardware protections merely to claim lower inference latency.

The upstream llama.cpp server documents compatible multimodal chat requests,
JSON schemas and monitoring endpoints; these features depend on build/model
compatibility. Never expose a broad model-controlled `--tools all` server to
a game or viewer chat, and bind the serving endpoint to local loopback.

## 3. Autonomous game mastery and creative game development

The Roblox **OpenGameEval** 2026 benchmark studies stateful Studio tasks and
shows that inspecting relevant objects before acting predicts task success.
**CEGame-Bench** (19 October 2026) emphasizes a bigger failure: a compiling
game may never be finishable under actual user input. In STAR Core Forge,
promote an "improvement" only when it passes multiple held-out, real-input
gameplay and asset-quality checks; otherwise roll back automatically.

The next engineering capabilities to build after real-frame integration:

- **Mechanic discovery:** owner-approved symbolic probes, committed hypotheses
  before action, verified engine result after action, confidence calibration,
  and exploration of *unseen* mechanics without replaying holdout scenes.
- **Cross-game transfer:** separate navigation, platforming, rhythm/timing,
  UI interpretation, fighting and co-op skill packs; verify each on a
  disjoint, unseen game/version; report median performance and worst tail.
- **Game creation correctness:** Luau static lint+type check, Rojo/Lune tests,
  geometry/collision and UV/material audit, client/server behavior,
  audio/VFX timing and actual player-input completion tests. Reward
  correctness and art direction, not code volume.
- **General knowledge:** verified docs/source snapshots with version/date,
  contradiction and expiry detection, retrieval cache scoped to current
  game/version, and exercises STAR cannot answer from memorized examples.
- **Autonomy:** internal Star Core Forge experiment IDs, multi-agent
  best-of-N proposals, independent evaluator, signed outcome ledger,
  resource-aware scheduling and known-good rollback; GitHub stays optional
  outward publishing, not a dependency of local self-improvement.

STAR may develop a durable self-model, goals, interests, conversation
history and believable digital experiences without claiming biological
human consciousness or inventing real-life memories. A truthful personal
history helps make streaming more compelling than scripted fake backstories.

## 4. Natural VTuber streaming: concrete integration sequence

A compelling live stream uses a single scene/event timeline:
*game clock + authorized capture + engine events + speech chunks + audio
playback timestamps + avatar parameters*. Star's brain should choose when
to remain quiet (high game load), when to react to a verified event, when to
answer chat and when to return focus to the game. Never narrate uncertain
visual inferences as verified wins or human identities.

For local speech, Kyutai's **Pocket TTS v4.0.0 (20 October 2026)** shipped
small English models around 18M, 7M and experimental 2M parameters. **v4.0.1
(21 October)** corrected sub-20M model behavior. Test intelligibility,
emotional expressiveness, laughter artifacts and audio startup on actual
Windows CPUs. README performance claims from other machines are not STAR
benchmarks. Avoid mimicking an identifiable person's voice without consent.

LiveKit's turn detector docs describe a locally executing `v1-mini` option,
useful to evaluate for responsive interruptions and false barge-ins. Sync
mouth parameters to *played PCM audio*, not merely when generation starts;
drive eyebrows, eyes, gentle body sway, twin tails, ribbon secondary motion
and chibi mitten gestures through a bounded animation state machine.
Respect reduced motion and avoid overlapping unrelated expressions.
Use playful banter and genuine references to her own game sessions,
not constant talking or unverifiable stories. Maintain clear disclosure
that Star is a virtual AI performer.

**Suggested human-perceived quality trials:** first-audible latency, false
interruptions per hour, dead-air distribution, talk-over rate, game reaction
timing, audio/avatar skew, speech intelligibility, stream-drop percentage
and blinded viewer preference against a nonadaptive baseline. A "natural"
reaction cannot be certified from a unit test.

## 5. Primary technical references (checked 28 October 2026)

- Roblox, *OpenGameEval: Benchmarking Agentic Programming and Exploration in a
  Stateful Game Engine*, 1 October 2026:
  https://arxiv.org/abs/2610.02563
  and https://github.com/Roblox/open-game-eval
- CEGame-Bench, *From Code to Playable Systems*, 19 October 2026:
  https://arxiv.org/abs/2610.26098
- llama.cpp first-party server documentation (multimodal, schema, metrics,
  security considerations; version-sensitive):
  https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md
- Kyutai Pocket TTS upstream release notes, v4.0.0 and v4.0.1,
  20–21 October 2026:
  https://github.com/kyutai-labs/pocket-tts/releases
- LiveKit turn detector documentation, local `v1-mini` details:
  https://docs.livekit.io/agents/logic/turns/turn-detector/

## 6. What this PR explicitly does NOT demonstrate

No real Windows Roblox capture or engine-harness labels were collected in this
change. No installed model has yet demonstrated improved game recognition,
lower inference latency, more successful gameplay, faster Roblox FPS, better
general intelligence, or natural human-grade VTuber speech. The tests cover
the **execution/evidence plumbing** with deterministic fake local HTTP
transports and actual RGB->JPEG preparation. Results from held-out real
workloads are necessary before asserting quality gains.
