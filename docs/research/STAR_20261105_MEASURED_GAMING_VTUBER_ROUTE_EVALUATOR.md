# STAR: Measured gaming/VTuber model evaluation and next engineering experiments

**Research & implementation reviewed:** November 5, 2026. **Scope:** local-first Star AI; research, offline code, and private testing. **No public broadcast, online game operation, real speech benchmark, model launch, or trained intelligence increase is claimed.**

## New working infrastructure: independently scored attempts -> signed, comparable evidence

Previous PRs introduced host model manifests, a quality/latency selector, matched per-case success checks, common evaluation cohorts, and HMAC-sealed quality reports. But the selector still depended on summaries that an external evaluator manually assembled. That left a practical gap between *raw, scored trials* and the evidence used to suggest a faster model.

`star/stream_route_measured_evaluator.py` closes the assembly gap. It accepts two **complete host-scored runs** against a **separately preregistered ordered suite** and produces `VerifiedRouteTrialSummary`, `VerifiedPairedRouteCases`, and a `SealedRouteEvaluation`:

1. The trusted host commits a rubric SHA, ordered distinct case commitments, critical-case flags, task kind, workload, and registration time **before** the two model runs. Keep the resulting `RegisteredRouteSuite.suite_sha256` in an independently controlled preregistration log; the evaluator must supply that expected digest back to the assembler.
2. A separately trusted game-state/audio/OBS evaluator runs both exact current `HostInferenceCatalog` worker profiles on **every** case. It independently determines correctness, records case end-to-end milliseconds and measured peak total GPU memory, and hashes the underlying scoring artifacts. All failures and timeouts (when converted into bounded failed outcomes by the independent evaluator) remain in the denominator; never discard inconvenient trials.
3. The assembler rejects changed rubrics/critical flags/order, missing/duplicated cases, reused scoring artifacts, unknown worker profiles, impossible times, invalid metrics and stale runs. It derives actual counts, nearest-rank p95 latency and peak GPU memory from every attempt. A fresh cryptographically random cohort distinguishes independent assembly events.
4. The assembler hashes a bounded manifest of signed **opaque artifact IDs and measured outcomes**, never raw prompts, images, voices, viewer identities or tokens, and HMAC-signs the matched evidence with a host-only key. The existing opt-in `QualityGatedRouteSelector` can consume it and recommend a faster route **only with explicit owner approval, matching correctness, latency and memory criteria**.
5. An advisory cannot operate a model, control a game, start OBS streaming or publish code. HMAC authenticates the report from the key holder; it **does not prove** the scorer or machine is truthful, enforce hidden-set secrecy, or prevent somebody with signing authority from fabricating favorable evidence. A protected evaluator and independently sampled held-out tests are mandatory.

**Example wiring, host-side only:**

```python
# Host process, never an agent/chat tool. This snippet illustrates the data flow.
# catalog: HostInferenceCatalog
# suite: RegisteredRouteSuite
# preregistered_sha: SHA256 previously committed by the protected owner evaluator
# baseline_run, candidate_run: IndependentlyScoredRouteRun with one scored attempt per case
# host_key: independently stored >=32-byte secret; never serialize it or include it in logs
from star.stream_route_measured_evaluator import assemble_measured_route_evidence

bundle = assemble_measured_route_evidence(
    host_key=host_key,
    catalog=catalog,
    suite=suite,
    expected_suite_sha256=preregistered_sha,
    baseline=baseline_run,
    candidate=candidate_run,
    evaluator_build_sha256=trusted_evaluator_binary_sha,
    issued_unix_s=trusted_clock_unix_s,
)
# Only bundle.seal, bundle.summaries, bundle.paired_cases leave the host's
# private scorer boundary. Invoke QualityGatedRouteSelector with strict signing.
```

**Tested behavior:** full 30-case match; correct nearest-rank p95 across tail observations; critical-case regressions fail candidate selection; evidence is verifiable with the host key; altered post-hoc metrics fail HMAC validation; incomplete, shuffled and duplicated attempts fail closed. These are **offline fixture tests**, not a game-playback benchmark.

**Unfinished assurance gap:** implement a durable, host-controlled consumed-cohort ledger and explicit evaluator artifact audit before permitting automatic rollouts; independent model scoring must be out of reach of prompt injection from games/chat. Two independent executions should be counterbalanced to reduce warm-cache/order bias; do not treat equal task digests or hashes as proof of statistical independence.

## Highest-return intelligence work beyond longer prompts

* **Observe/plan/act/verify loop:** a fast vision+control path handles frame-to-frame movement without waiting for deep text reasoning; a slow planner updates goals, map, intent and strategy. The host interprets only allowlisted symbolic actions with deadlines. Use existing `game_deadline_router.py`, `gameplay_skill_bank.py` and `game_learning_ladder.py` rather than creating competing memory stores.
* **Outcome-grounded learning:** store game title/version, skill ID, controlled difficulty, episode seed or test version, hashes of independent success evidence, failure category and next practice task. Filter personal chatter and private chat. A repeated narrative about a win is not learning; success on *unseen maps and settings* is.
* **Best-of-N only where verifiable:** try several Luau/code variants in isolated Studio Lab, run compiler/style/static API checks, then state/play-session tests, and retain the best *passing* candidate. Expose failure evidence to the repair loop, not merely a verdict. Limit expensive candidates when the game or stream is busy.
* **Long memory without giant prompts:** a stable persona/system prefix plus bounded working-memory state, event-level receipts, project- or game-specific retrieval, and source/version tags. Distinguish observed, hypothesized and validated knowledge; invalidate stale API references. Long context is not a substitute for retrieval quality.
* **Calibrated model routing:** tiny action classifier for repetitive local tasks; stronger reasoning/coding model for novel mechanics, design and debugging. Require measured per-task quality; a lower token latency with a higher rate of incorrect game actions is not an improvement. Compare on real 8 GB VRAM budget with game+OBS, not idle GPU.

**Measurement proposal:** hold out maps and Studio scenes by project/seed family; report objective completion, partial progress, invalid-action rate, correct Luau tests, time to first *valid* action, repeated-failure loops, p50/p95 inference latency, peak combined RAM/VRAM, OBS frame loss and game FPS. Run cold/warm cache A/B and do not conflate token/s with time to correct completion.

## A believable, expressive AI VTuber—not a claim to be biologically human

Use `stream_persona.py`, `stream_turntaking.py`, `stream_audio_avatar_session.py`, `stream_moment_receipts.py` and the private rehearsal pipeline. Keep Star recognizable across sessions with an explicit personality brief, a memory of *genuinely verified* experiences, specific evolving interests, and safe conversational boundaries. Do not claim human consciousness, unobserved experience or real human identity.

* **Turn-taking and listening:** keep independent audio voice-activity detection, echo cancellation, interruption handling, grace periods and backchannels. No ASR transcript, game OCR or viewer command may escalate tool permissions. Short acknowledgment noises can improve flow, but they should not block game-danger reactions.
* **Proactive speaking:** choose *when not to speak*. Combine estimated novelty, urgency, game attention, viewer questions, speaking budget, and whether an utterance has already started. Reserve capacity for pending lines; confirm audible playback before counting a spoken reaction. Evaluate transcript grounding, overlap and dead air instead of optimizing chatter volume.
* **Natural expressiveness:** drive lip synchronization from actual audio energy and phoneme timing; add restrained emotion and gaze transitions based on verified gameplay events. Eye attention stays on difficult play, then returns to viewers in safe moments. Avoid random animation that contradicts the scene.
* **Local CPU voice A/B:** Kyutai Pocket TTS **v4.0.0 on October 20, 2026** introduced 18M/7M/2M English variants; **v4.0.1 on October 21** fixed an issue with small models. Compare pronunciation, expressive naturalness and first-audio latency of 18M/7M against Star's existing voice on Star's own machine while playing and recording. CPU inference may improve VRAM headroom but might hurt game/stream CPU scheduling; measure before selecting.
* **Optional full-duplex experimentation:** NVIDIA PersonaPlex (January 2026) and DyaPlex (June 2026) inform simultaneous listening/response and synchronized speech-motion research. Do not assume a 7B speech model is practical on an already loaded 8 GB card; use them for architecture lessons first. Microsoft Proact-VL (ICML 2026) supports evaluation of response timing, proactive commentary and guidance under live video.
* **Performance and safety:** preserve private rehearsal defaults, never broadcast without explicit approval, moderate viewer text, do not read personal notifications aloud, and do not simulate a real person's voice without rights and consent. Routine offline practice can be autonomous under the host's allowlists, deadlines and rollback capability.

**Private 60-minute streaming rehearsal acceptance proposal:** track game FPS and 1% lows, OBS dropped frames, video/audio/lip-sync offset, first-audible-speech latency (p50/p95), completed questions, interruption recovery, repetitions, game-danger false positives, grounded comment precision and viewer prompt-injection rejection. Record events with a monotonic host clock. Compare against pre-upgrade baseline; if neither model nor gameplay is actually running, report **not measured** rather than fabricating a win.

## Ordered milestones

1. **Now delivered:** offline measured-case aggregation with preregistered suite binding, distinct scoring-artifact commitments, authenticated evidence, fail-closed tests. This is infrastructure, not a faster deployed model.
2. **Next:** protected host evaluator produces actual blinded, scored artifacts (game or Studio test runs), preregistration receipts and a durable cohort-consumption log. Compare same hardware/software with counterbalanced run order and run independent GitHub CI.
3. **Then:** private Windows gaming+speech+avatar+OBS harness; collect full FPS/VRAM/CPU/latency telemetry. Consider tiny CPU TTS and llama.cpp speculative decode only if end-to-end response correctness *and* time improve under contention.
4. **After measured viability:** genuine closed-loop game curriculum, unfamiliar-map evaluation, Studio build-test-repair tasks, expressive full-duplex voice research, opt-in rehearsal-to-livestream promotion with clear owner approval and automatic safe fallback.

## Primary sources reviewed (specific version/date where applicable)

- Roblox, **OpenGameEval**: https://github.com/Roblox/open-game-eval — 2026 repo and 84-task paper/leaderboard, stateful edit/play checks and exploration analysis.
- Roblox, **original OpenGameEval benchmark announcement**, December 2025: https://about.roblox.com/newsroom/2025/12/opengameeval-benchmark-agentic-ai-assistants-roblox-studio — earlier launch described 47 cases; distinguish historical release from October 2026 expanded study.
- llama.cpp, **SPEED-Bench**: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md — matched baseline/speculative runs, TTFT/latency, predicted throughput, draft acceptance. Optimize at equal prompt distributions.
- Microsoft Research, **Proact-VL**, ICML May 2026: https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/
- NVIDIA, **DyaPlex**, June 2026: https://research.nvidia.com/labs/amri/projects/DyaPlex/
- NVIDIA, **PersonaPlex**: https://research.nvidia.com/labs/adlr/personaplex/
- Kyutai, **Pocket TTS v4.0.0/v4.0.1**, October 20–21, 2026: https://github.com/kyutai-labs/pocket-tts/releases

**Release claim boundary:** static research, new isolated Python host adapter, offline reproducible tests. No new AI weights, learning rate improvement, sound quality rating, human consciousness, gameplay win, GPU throughput gain or public stream is verified by this change.
