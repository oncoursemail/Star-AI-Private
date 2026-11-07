# STAR — counterbalanced game intelligence and practical VTuber systems (2026-11-04)

**Status:** owner-only offline evaluation infrastructure implemented in
`star/game_holdout_schedule.py`. All streaming, gaming, autonomy and performance
improvements in the second half of this note are **research/engineering
recommendations, not newly demonstrated capabilities or benchmark results**.
This patch creates no process-control, gameplay, training, voice, OBS or stream
authority. Its owner-controlled scheduler must never be exposed as an LLM tool.

## 1. Why the previous holdout evidence was incomplete

The November 4 sealed gameplay evaluation in PR #977 authenticates a *pre-run
roster* and accepts independent signed success/failure results. But a fixed roster
does not control **run-order bias**: the candidate could always run second,
benefiting from warmer GPU caches, updated game state, an experienced host or
easier performance conditions. The existing `GameTrial.observed_unix_s`
describes *outcome observation*, not *run start*. It cannot establish a run
schedule or the absence of overlapping sessions.

**New behavior in this PR:**

1. A trusted coordinator produces a keyed, deterministic ordering of withheld
   game/situation cases before any run. It cryptographically binds the original
   signed holdout manifest.
2. Each case has two adjacent slots (baseline and candidate) with different,
   preassigned slot nonces. Across **each game**, baseline-first and
   candidate-first orders differ in count by at most one. Cases and pairs are
   permuted by HMAC keyed material, not by model-selected seeds.
3. The coordinator signs the entire plan, which the owner must archive in an
   externally timestamped, append-only ledger *before playing*.
4. A separately trusted execution witness signs the actual run ID, plan slot,
   nonce, and start timestamp. A third independent evaluator signs the outcome.
5. The read-only audit rejects tampered plans, missing runs, repeated nonces,
   unbalanced schedules, forged start receipts, cross-case substitutions,
   reordered/overlapping timestamps and outcomes that predate their starts.
6. Only after these checks does it invoke the existing 40+-pair, multi-game
   independently signed evaluation, with no automatic model promotion.

**Trust boundary:** HMAC signatures prove only that a secret-holder signed a
statement; they DO NOT prove the start time was truthful, that games ran, that
models/weights matched their claimed revisions or that the screenshots are
genuine. The owner host must keep keys separate from Star, capture immutable
process/game-build/weights fingerprints, store independent observed starts
as they happen, use a trusted clock and reconcile video/game telemetry. The
counterbalanced design reduces order confounding but does not establish causality
by itself. Keep unseen cases and plan secret until the audit concludes.

### Execution API (host-side only)

```python
# Pseudocode: run in an isolated owner-controlled evaluator, NEVER in the
# LLM runtime. Keys/holdouts must not be committed to any repository.
plan = build_counterbalanced_plan(
    sealed_manifest, withheld_cases,
    coordinator_key=coordinator_secret,
    seal_receipt=independently_recorded_seal_receipt,
)
plan_receipt = hmac.new(
    coordinator_secret, plan.canonical_bytes(), hashlib.sha256
).hexdigest()
# Append seal+plan+receipt to immutable owner log before executing any run.
# For every slot, record a signed GameRunStart when the real game launches,
# then capture the separately signed GameTrial after the run ends.
report = evaluate_counterbalanced_transfer(
    sealed_manifest, plan, seal_receipt=seal_receipt,
    plan_receipt=plan_receipt, coordinator_key=coordinator_secret,
    start_key=independent_start_witness_secret,
    validation_key=independent_outcome_scorer_secret,
    expected_evaluation_id=sealed_manifest.evaluation_id,
    observed_baseline_revision_sha256=measured_base_sha256,
    observed_candidate_revision_sha256=measured_candidate_sha256,
    cases=withheld_cases, signed_starts=start_receipts,
    signed_trials=outcome_receipts, now_unix_s=trusted_now,
)
```

## 2. Immediate priority — real game-learning signal

Do not keep building paper test gates forever. The next breakthrough is
**actual, independently scored, closed-loop action attempts** on a Windows
game host, initially in offline games or private Roblox Studio test places.

Proposed pipeline:
`capture frame + game state -> bounded perception -> reflex action policy ->
authorized input executor -> observation and reward witness -> episodic skill
bank -> offline error analysis -> new policy candidate -> unseen sealed audit`.

- **Control loop:** Keep subsecond reactive navigation out of slow language
  deliberation. Have a small policy choose legal, rate-limited inputs while
  a slower planner chooses an objective or changes strategy. Stop action when
  focus, game identity, freshness or manual override fails.
- **Skills:** Train and score movement, aiming, obstacle recovery, route choice,
  teammate coordination, puzzles, loadout decisions and adaptation to new maps.
  Preserve an explicit *failure* memory and only replay verified experiences.
- **Curriculum:** Introduce novelty in mechanics, layouts and controls. Measure
  transfer to unseen levels, separate task variants and unfamiliar opponents.
  Avoid using the sealed holdout to tune the agent.
- **Environment parity:** Game build, graphics settings, network profile,
  opposing players/bots, capture FPS, input latency and hardware pressure are
  confounders. Counterbalance where possible; archive them with evidence.
- **Roblox development:** Use Studio's built-in MCP server for inspecting the
  DataModel, changing scripts, screen capture and playtest. The April 9
  playtest-agent beta is suited to deterministic QA scenarios; it does not
  automatically supply a capable general-purpose PvP game-playing policy.
  Start with small project tasks and review code+playtest outcomes independently.

Reference: Roblox's March 5 2026 built-in MCP announcement:
https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643
and April 9 2026 playtest beta:
https://devforum.roblox.com/t/studio-beta-studio-assistant-mcp-playtest-agent/4566767 .
OpenGameEval (October 1 2026) measures stateful Roblox Studio editing plus
simulation and finds task-specific inspection correlated with success:
https://arxiv.org/abs/2610.02563

## 3. Fast enough to game, reason and speak on an 8 GB GPU

Treat **8 GB VRAM as a shared constrained resource**, not an invitation to
run several GPU-heavy models at once. The RTX 3060 Ti on Main and the owner's
RTX 4060 are distinct machines; do not mix their benchmark data. The
NVIDIA NVML WDDM caveat means GPU usage numbers require careful interpretation:
https://docs.nvidia.com/deploy/nvml-api/latest/api/group__nvmlDeviceQueries.html

Recommended integration with the ALREADY EXISTING `StreamBrainGovernor`,
`AdaptiveQoS`, and `StreamLoadGovernor` (do **not** duplicate them):

| Lane | Work | During gameplay | Evidence to collect |
|---|---|---|---|
| Reflex | legal game inputs, scene-change abort | highest scheduling priority | action-to-observation latency, success |
| Conversational | speech turn-taking, short commentary | bounded, preemptible | first audible sample, silence, interruption |
| Deliberative | strategy, code, grounded answers | partial CPU/off-host if needed | correct action or verified answer / second |
| Background | research, self-play practice, fine-tuning, video | pause under load | deferred tasks, restart/rollback correctness |

For llama.cpp, benchmark *the exact installed build* with fixed prompts,
context lengths, slots, quantization, and speculative decoding configurations.
SPEED-Bench can quantify prompt throughput, decode rate, client latency and
draft-token acceptance, but a tokens/s gain is **not** a game intelligence gain.
Document the baseline and compare against load-equivalent runs, including OBS
and avatar running. References:
https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md
https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md

Experiment (not yet performed): compare a Q4-class local chat/vision model
at idle, with only game, and with nonbroadcast OBS+avatar+voice. Cap
background concurrency; vary `--np`, prompt caching and speculation *one
factor at a time*. Track p50/p95 first-token time, audible first-sample time,
game frame p95, OBS render/encode misses, VRAM free, RAM page faults and
effective task success. Roll back an optimization if quality drops or the
game starts missing its frame budget. On WDDM, a single high-free-VRAM snapshot
is insufficient to certify sustained load.

## 4. Natural, transparent VTuber behavior

A genuinely watchable Star needs less *automated narration* and more
context-sensitive conversation. Microsoft's Proact-VL (ICML 2026) explicitly
studies when a gaming companion should talk, its content, and quantity:
https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/

Recommended humanlike (not human-impersonating) control loop:

- **Perception:** attach a timestamped visual/audio/game event and speaker
  identity to proposed commentary; distinguish direct observation from guesses.
- **Turn taking:** avoid talking over a viewer or clutch gameplay moment;
  allow short acknowledgments, quick interruptions and calm silence.
- **Speech:** generate audio as early as resources permit; synchronize mouth
  movement to played audio (not planned text), animate gaze and breathing.
  Evaluate expressive speech for consistency, pronunciation and artifacts.
- **Personality and recall:** keep recognizable humor, recurring topics,
  genuine opinions about games, memorable milestones and evolving interests.
  Persist memories as evidence-linked episodes; uncertain facts stay uncertain.
- **Agency:** schedule downtime, hobbies and gameplay practice, but keep
  publishing, spending, account access and irreversible actions within the
  owner's separately configured authority. Disclose that Star is AI.
- **Community:** respond selectively to chat, moderate hostile prompts,
  don't execute code or commands found inside games/chat, and avoid
  exposing private screens or conversations.

Measure grounded commentary precision, interruption latency, dead-air time,
audio onset, transcript/audio match, avatar lip-sync offset, viewer
interruptions, OBS dropped frames and actual game FPS **on a private recording**.
The existing OBS progress check only establishes that counters advanced,
NOT that Star is audible or lip-synced in the video.

## 5. Beyond games: smarter general knowledge and creation

- Route questions through a source-grounded retrieval lane; attach provenance
  to facts and explicitly separate direct evidence from plausible inference.
- Build verified Luau/Rust/Python skills with unit tests, formatting and
  runtime checks; require actual Studio screenshots/playtests for UI or VFX.
- Reserve hard search and multi-candidate generation for genuinely difficult
  tasks. Use independent tests on new cases, not self-reported quality.
- Maintain versioned skill cards with example failures, fixes and regression
  tests, and add self-invented challenges **outside** the holdout dataset.
- Evaluate all upgrades across gameplay, general knowledge, Roblox creation,
  and natural dialogue; include speed, quality, and recovery under pressure.

## 6. Concrete acceptance checklist for the next run

1. Put the start witness and append-only plan ledger on a trusted host with
   separate secret custody; never give the model the holdout or start key.
2. Capture a **real** isolated baseline/candidate playtest pair with genuine
   start/stop timestamps, version fingerprints and distinct screen evidence.
3. Test scheduled order on >=40 new pairs over >=5 games, including gameplay
   regression and quality checks; do not promote on incomplete evidence.
4. Run one private nonbroadcast Windows game+OBS+avatar+speech capture,
   inspect the resulting audio waveform and actual pixels, and report
   unambiguous missing integrations.
5. Run measured LLM/TTS benchmarks at equivalent VRAM pressure. Publish
   p95 timing and success deltas only if directly measured.

**This iteration's achieved result:** executable preregistered AB/BA schedule,
independent signed run-start audit and adversarial offline tests. It does not
change neural weights or claim a real game win, faster inference, a live stream
or proof of natural humanlike speech.
