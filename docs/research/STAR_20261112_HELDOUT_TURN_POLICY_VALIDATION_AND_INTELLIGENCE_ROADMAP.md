# STAR Research: Leakage-Resistant Turn Policy Calibration and VTuber Quality

**Date:** 2026-11-12  
**Status:** Research plus offline calibration/holdout evaluator; no live voice integration.  
**Branch:** `feat/heldout-turn-policy-validation-20261112`

## Executive summary

STAR's causal turn-taking evaluator can sweep threshold, minimum action delay, and timeout and produce a Pareto frontier. A remaining methodological risk is selecting the best operating point and reporting its performance on the same turns. That produces optimistic estimates, especially when the grid is large.

This change adds `star/stream_turntaking_validation.py`:

1. Validate disjoint calibration and holdout turn IDs.
2. Require opaque group IDs so every turn from one conversation/session remains in one partition.
3. Select a model-scored policy using calibration data only.
4. Use one-sided Wilson upper confidence bounds for false-cutoff and missed-turn rates.
5. Freeze the selected policy before evaluating the holdout once.
6. Compare the frozen policy with a silence-only baseline using the same action delay and timeout.
7. Return aggregate metrics only; no IDs, audio, transcripts, viewer data, prompts, or model outputs are returned.

The evaluator does not tune a detector, call a model, access audio, or promote runtime configuration. It makes the evidence used for later integration more trustworthy.

---

## 1. Repository audit and why this is the next useful step

The current development chain contains:

- `stream_turntaking.py`: opt-in deterministic VAD/silence advisor.
- `stream_director.py`: event arbitration, priority, cooldown, and quiet time.
- `stream_persona.py`: stable, AI-transparent streamer behavior.
- `stream_continuity.py`: disabled-by-default owner-approved gameplay continuity.
- `stream_load_governor.py`, `stream_workload_admission.py`, and `stream_workload_runtime.py`: pressure and resource-allocation policy; no Windows hardware sampling or worker execution.
- `stream_experiment_eval.py`: paired latency/quality evaluation.
- `stream_turntaking_eval.py`: causal pause evaluation, policy sweep, silence-only baseline, and Pareto frontier.

The evaluator is intentionally offline. Before wiring a selected policy into a real microphone/playback loop, STAR needs a defensible way to distinguish tuning data from final acceptance data.

A policy grid can contain many combinations. Selecting the lowest-latency point from that grid and reporting the same point on the same turns is a form of selection bias. A separate holdout, grouped by conversation/session rather than randomly by pause, is the correct next boundary.

---

## 2. Research findings

### 2.1 LiveKit eot-bench: evaluate the decision policy, not only a classifier

Source: https://github.com/livekit/eot-bench  
Leaderboard: https://livekit.com/benchmarks/eot-bench

The benchmark uses complete turns containing every annotated pause of at least 100 ms. Earlier pauses are mid-turn holds; the final pause is the true end-of-turn. Model predictions are scored causally from only the prefix available at each timestamp.

The benchmark jointly sweeps:
- end-of-turn confidence threshold;
- minimum action delay;
- maximum timeout.

It compares latency under a false-cutoff budget and includes a silence-only baseline. Its public dataset covers 14 languages. Its headline latency is conversational dead air after the person finishes, not LLM inference time.

**STAR implication:** Keep endpointing delay separate from TTFT, TTS first-audio, playback, and avatar latency. A faster LLM cannot compensate for a voice detector that waits too long or cuts the viewer off.

### 2.2 Why calibration and holdout must be grouped

Pauses from the same user turn are correlated. Turns from one conversation or rehearsal session can also share microphone, speaker, room, language, and interaction characteristics.

Randomly splitting individual pauses can leak the same conversation into both sets. STAR therefore requires a caller-supplied opaque group ID for every turn and rejects any group that appears in both partitions.

The adapter should create stable HMAC digests for conversation/session groups, not store raw viewer identities or voiceprints. The evaluator returns no group IDs.

### 2.3 Wilson upper confidence bounds

A point estimate such as 0 false cutoffs in 20 pauses does not establish that the true cutoff rate is below 5%. STAR uses a one-sided Wilson upper confidence bound for false-cutoff and missed-final rates.

This is intentionally conservative: a small sample may remain inconclusive even when no errors are observed. That is preferable to promoting a policy on weak evidence.

The bound is a binomial approximation and does not repair correlated samples. Grouped holdout design and enough independent sessions remain necessary. For clustered data, a future adapter should bootstrap at the session/group level rather than treating every pause as independent.

### 2.4 LiveKit production endpointing defaults are not universal STAR settings

Current LiveKit documentation describes 0.5–3.0 s default endpointing delays and 0.3–2.5 s with its audio turn detector, with a VAD minimum silence duration requirement. These are framework defaults for its pipeline, not a universal optimum for STAR's hardware, audience, language, or game context.

Source: https://docs.livekit.io/agents/logic/turns/turn-detector/

**STAR implication:** Measure a local baseline and evaluate the detector/policy on representative private rehearsal data. Do not copy a provider's defaults and call the stream human-like.

---

## 3. Implementation details

### Data split contract

The caller supplies:
- calibration `SilenceSpan` observations;
- holdout `SilenceSpan` observations;
- an exact mapping from every opaque turn ID to an opaque group ID;
- a predeclared policy grid;
- predeclared acceptance constraints.

The evaluator rejects:
- overlapping turn IDs;
- overlapping span IDs;
- missing or extra group mappings;
- group IDs shared across partitions;
- malformed or unbounded identifiers;
- invalid pause data;
- insufficient calibration sample sizes.

All turns from a conversation/session group must be assigned to one partition. Use keyed digests at the host boundary. Never use viewer names, account IDs, raw audio fingerprints, or voiceprints as group IDs.

### Policy selection

The evaluator runs the existing bounded policy sweep on calibration only. It excludes the silence-only baseline from candidate selection.

Eligible policies must satisfy:
- one-sided Wilson upper bound for false cutoffs <= configured limit;
- one-sided Wilson upper bound for missed final turns <= configured limit;
- p95 observed endpointing latency <= configured limit.

A deterministic tie-breaker selects the lowest p95 latency, then lower confidence bounds for errors, mean latency, action delay, timeout, and threshold.

### Frozen holdout evaluation

Only after a calibration candidate is frozen does the function evaluate the holdout. It evaluates the silence-only reference at the same action delay and timeout.

The holdout result is:
- `PASS`: all sample-size and predeclared gates pass;
- `FAIL`: adequate sample size exists and one or more gates fail;
- `INCONCLUSIVE_HOLDOUT`: sample size is insufficient;
- `NO_CALIBRATION_CANDIDATE`: no policy qualifies on calibration;
- `INSUFFICIENT_CALIBRATION`: calibration sample size is too small to select.

The function does not persist a one-use holdout ledger. The orchestration layer must keep holdout data sealed and must not repeatedly tune against it. If a holdout is reused for tuning, it becomes calibration data and a new holdout is required.

---

## 4. Research: faster local inference without damaging the stream

### llama.cpp SPEED-Bench

Source: https://github.com/ggml-org/llama.cpp/tree/master/tools/server/bench/speed-bench

The upstream server benchmark compares baseline and speculative decoding with matched prompts and output lengths. It reports prompt throughput, decode throughput, end-to-end request latency, and draft acceptance. Its guidance says to match client concurrency to the server's configured slot count.

**STAR experiment plan:**
- Pin the exact model file hash, quantization, backend, context size, and llama.cpp build.
- Separate warm-up from measured runs.
- Match prompt set, output budget, and concurrency.
- Compare one, two, and four slots only where memory permits.
- Test prefix caching and speculative decoding separately.
- Run with OBS, voice, avatar, and gameplay active.
- Pair speed with held-out task quality and frame/audio guardrails.

Do not equate aggregate throughput with conversational speed. More slots can increase throughput while worsening first-audible latency or VRAM pressure.

---

## 5. Research: Star as a gamer and game creator

### GameDevBench (ICML 2026)

Project: https://github.com/waynchi/gamedevbench  
Paper/project page: https://waynechi.com/gamedevbench/

The current project describes 333 Godot game-development tasks across 2D graphics/animation, 3D graphics/animation, UI, and gameplay logic. The published work shows that visual feedback can materially improve agent success; code-only success is not enough for multimodal game development.

**STAR Creator plan:**

1. Inspect the project scene, assets, scripts, and engine version before editing.
2. Create a minimal, reviewable change.
3. Run the project in an isolated test workspace.
4. Inspect screenshots and short gameplay captures.
5. Run engine diagnostics and deterministic gameplay assertions.
6. Repair visual and functional regressions.
7. Re-run the original test and held-out regression tasks.

Use this loop for Roblox Studio/Luau and later Godot/Unity. Keep engine-specific tools and permissions separate.

### Two-timescale game agent

- **Reactive loop:** immediate visual state, hazard avoidance, movement, and short-horizon control.
- **Strategic loop:** objectives, mechanics discovery, route planning, practice curricula, and strategy review.
- **Skill memory:** versioned procedures with preconditions, scope, known failure modes, and signed practice evidence.
- **Transfer evaluator:** tests whether a mechanic learned in one game works in a different game.

The strategic model must not block the reactive control loop. A skill is not “mastered” after one successful attempt.

---

## 6. Research: general knowledge that transfers into useful actions

### Mem2ActBench (ACL 2026)

Paper: https://aclanthology.org/2026.acl-long.370/

Mem2ActBench synthesizes 2,029 sessions and 400 tool-use tasks, with human evaluation finding that 91.3% of its tasks are strongly memory-dependent. It evaluates whether an agent applies long-term information to tool choice and parameter grounding, not merely whether it can repeat a fact.

**STAR implication:** evaluate memory and general knowledge by later task performance. Store provenance, source date, scope, confidence, contradictions, review date, and held-out task evidence.

Recommended curriculum:
- mathematics and statistics;
- physics, chemistry, biology;
- computer science and engineering;
- history and geography;
- economics and practical digital skills;
- languages and communication;
- psychology and social reasoning;
- art, music, design, storytelling;
- game design and production.

Separate factual knowledge from procedural skills and environment-specific game mechanics.

---

## 7. VTuber behavior: make the experience natural and transparent

The goal is conversational competence, expressive timing, and consistent character behavior—not pretending to be a human or inventing lived experiences.

Evaluate these separately:
1. End-of-turn delay.
2. True interruption detection.
3. Backchannel handling.
4. ASR finalization.
5. LLM time-to-first-token.
6. TTS first-audio.
7. Actual playback acknowledgement.
8. Avatar reaction/mouth synchronization.

For a private rehearsal, measure:
- false cutoff rate at fixed latency budgets;
- missed-turn rate;
- endpointing p50/p95;
- barge-in precision and recovery;
- response appropriateness from blinded human labels;
- first-audible latency;
- audio underruns;
- avatar synchronization;
- game frame-time p95/p99;
- OBS render and output skips.

Do not collapse these into one “human-likeness” score. Keep owner identity verification separate from voice similarity, and do not retain raw audience audio or transcripts by default.

---

## 8. Next integration phases

### Phase A — offline validation (this change)
- grouped calibration/holdout split;
- predeclared policy constraints;
- one-sided Wilson error-rate bounds;
- deterministic calibration selection;
- frozen holdout evaluation;
- same-policy silence baseline.

### Phase B — benchmark adapter
- map a licensed eot-bench validation subset into the content-free schema;
- preserve dataset revision, license, language, and adapter version;
- score only causal prefixes;
- group by complete turn/session;
- keep final test data sealed.

### Phase C — actual STAR voice pipeline
- connect host-supplied VAD/EoT scores;
- connect playback acknowledgements;
- measure TTS and avatar timing separately;
- test interruption/backchannel scenarios;
- no policy auto-promotion.

### Phase D — Windows rehearsal and mixed workload
- owner-approved WASAPI capture with ephemeral buffers;
- OBS and VTube Studio local authenticated APIs;
- Windows CPU/RAM/GPU/VRAM telemetry;
- PresentMon game frame-time;
- real audio playback and underrun observations;
- run the private mixed workload before enabling any automatic resource policy.

### Phase E — gaming and creator intelligence
- two-timescale gameplay;
- game-specific skill artifacts;
- held-out skill transfer;
- inspection-first game editing;
- visual feedback and engine-level playtests;
- general-knowledge task evaluation.

---

## 9. Sources

1. LiveKit eot-bench: https://github.com/livekit/eot-bench
2. LiveKit EoT leaderboard: https://livekit.com/benchmarks/eot-bench
3. LiveKit turn detector documentation: https://docs.livekit.io/agents/logic/turns/turn-detector/
4. llama.cpp SPEED-Bench: https://github.com/ggml-org/llama.cpp/tree/master/tools/server/bench/speed-bench
5. GameDevBench: https://github.com/waynchi/gamedevbench
6. GameDevBench project and results: https://waynechi.com/gamedevbench/
7. Mem2ActBench, ACL 2026: https://aclanthology.org/2026.acl-long.370/

## 10. Validation boundary

- This is a pure/offline evaluation module.
- It does not capture audio, call an EoT model, operate TTS/playback, OBS, VTube Studio, Windows APIs, or game input.
- Group separation is only as trustworthy as the host-supplied opaque group IDs.
- Wilson bounds assume independent Bernoulli trials; repeated turns from a session are correlated. Grouped splits reduce leakage, but a future clustered bootstrap should be added for confidence intervals across sessions.
- The holdout is not persisted as consumed; the experiment runner must enforce one-time use.
- No measured reduction in interruptions, latency, or inference time is claimed.
- No game mastery, general-intelligence gain, or human-equivalent behavior is claimed.
- No Windows, RTX 4060, OBS, audio, VTube Studio, Roblox Studio, Godot, or livestream integration test is claimed.
- Production `main` and the v1.0 installer remain unchanged.

## Files

- `star/stream_turntaking_validation.py`
- `tests/test_stream_turntaking_validation.py`
- `docs/research/STAR_20261112_HELDOUT_TURN_POLICY_VALIDATION_AND_INTELLIGENCE_ROADMAP.md`
