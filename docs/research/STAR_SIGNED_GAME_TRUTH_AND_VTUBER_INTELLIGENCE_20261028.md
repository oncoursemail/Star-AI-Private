# STAR AI Research — Authenticated Game Truth, Faster Gaming Intelligence and Humanlike VTuber Engineering
**Research date:** 2026-10-28
**Status:** implemented OFF-by-default verifier + synthetic tests; broader proposals unimplemented
**Base:** draft PR #755 (paired local offline vision worker), not deployed to Windows or OBS

## Executive decision

The most valuable immediate improvement is NOT another pixel micro-optimization. STAR
already has optional visual memory, frame freshness, static-frame fast paths,
paired local vision execution and a blinded quality evaluator. Those features
cannot prove real visual understanding until independently observed game truth
can be joined to exactly the right prediction and source frame. A screenshot
or model self-report is not game truth.

This change adds `VisionTruthReceipt` with versioned HMAC-SHA256 canonical
serialization and `PairedVisionTraceHost.record_signed_truth()`. The host
checks the game/version, trace epoch/serial, frame sequence, raw RGB frame
digest and capture time before accepting an independently signed categorical
label. Signed receipts cannot overwrite truth, replay after STOP/re-enable or
leak their raw evidence into the ordinary evaluation export. Existing
`record_truth` remains available for legacy trusted host adapters; the signed
path is a stronger **optional** boundary, not mandatory in existing sessions.

**Trust limitation:** HMAC authenticates who knew the key. It cannot establish
that an observer correctly read Roblox Studio or that the game itself was
fair. The trusted Windows/Studio scorer and its key isolation are not built
here; integrating those requires an explicit locally authorized game session.

## Evidence from research

1. Roblox [OpenGameEval repository](https://github.com/Roblox/open-game-eval)
   and [paper, Oct 1, 2026](https://arxiv.org/abs/2610.02563) test
   interactive, reproducible Studio tasks by executable scene/play checks,
   not only whether the generated Luau parses. The benchmark examines
   observation before editing; coverage of the affected objects is correlated
   with higher task success. **STAR implication:** inspect the scene first,
   generate candidate changes, test in Studio and use a non-model evaluator.
   Version changes, benchmark data access and hidden tests must be tracked.
2. [GameWorld benchmark](https://gameworld-project.github.io/) measures
   game state including scores, coordinates and checkpoints; it distinguishes
   an environment paused during reasoning from a real-time environment that
   keeps advancing. **STAR implication:** separately measure action success
   and real-time latency under the same game's advancing clock. A correct
   plan delivered after a jump window is not a good live gaming policy.
3. [llama.cpp server documentation](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)
   documents prompt-cache reuse, server slots and metrics including
   prompt-processing and token-generation timings. **STAR implication:**
   instrument prefill, decode, queueing, cache hit rates, time-to-first-token,
   GPU memory and host FPS; only then compare chunk reuse, speculative
   decoding, quantization or smaller specialist models. Unmeasured speed
   settings should not be enabled globally.
4. [Kyutai Pocket TTS official repository](https://github.com/kyutai-labs/pocket-tts)
   documents lightweight English models as of October 2026, including
   18.2M, 6.9M and experimental 1.9M parameter configurations. The
   repository's CPU throughput claims are hardware-specific and not a
   STAR benchmark. **STAR implication:** an A/B voice-quality and first-
   audible-latency test is preferable to selecting the smallest model alone.
5. [LiveKit audio turn detector](https://docs.livekit.io/agents/logic/turns/turn-detector/)
   and [turn-taking tuning](https://docs.livekit.io/agents/logic/turns/tuning/)
   show how to distinguish actual end-of-turn from pauses and how to resume
   after false interruptions. **STAR implication:** use turn-end confidence,
   per-speaker rate limiting, stop-on-overlap and short acknowledgments
   rather than instant replies to every chat line.
6. [VTube Studio WebSocket API](https://github.com/DenchiSoft/VTubeStudio)
   supports custom animation parameter inputs; its documentation cautions
   against querying parameters continuously at 60+ FPS on weaker PCs.
   **STAR implication:** update avatar parameters at a measured lower rate,
   then interpolate smoothly inside the renderer, especially eye gaze,
   mouth motion, twin tails and gold ribbons.
7. [OBS WebSocket protocol](https://github.com/obsproject/obs-websocket)
   uses challenge authentication. **STAR implication:** isolate OBS
   credentials, require an owner-authorized stream session, monitor dropped
   frames and never let viewer chat command OBS directly.

## Implemented contract: independent truth bound to the exact experiment

**Trusted host sequence**

1. Owner explicitly authorizes offline/private capture, dedicated vision models
   and the independent test scorer. Keys belong to a separate scorer process,
   never the model or a chat/tool context.
2. Capture the same before/after RGB frame pair once for each baseline and
   candidate local model. The paired runner stores only the SHA-256 of the
   immutable current-frame snapshot in the trace.
3. Freeze every baseline and candidate prediction for the cohort before
   exposing any independent ground-truth labels.
4. Trusted Studio/human observer determines the actual categorical cues from
   independent engine state or reviewed annotations. It records a digest of
   the externally held evidence, a bounded run ID and the frame scope.
5. The separate observer computes HMAC-SHA256 over
   `VisionTruthReceipt.canonical_bytes()` with its **unique 32+ byte secret**.
   The receipt includes the trace session epoch, serial, pixel SHA-256,
   capture clock, frame sequence, game and game version; labels are sorted.
   Never accept a model-generated signer key or signature.
6. The host invokes `record_signed_truth(ticket, receipt=..., signature=...,
   verification_key=..., owner_approved=True,
   independent_scorer_approved=True)`. The host checks the trace binding
   under its lock and cryptographically authenticates the receipt before
   calling the existing one-way truth recorder.
7. Only after all truths are collected may the owner inspect aggregate F1,
   false alarms, stale rate, failed rate, and p95 latency or export a private
   categorical JSONL outside Git. The existing evaluator may suggest a
   **manual pilot**, not approve live deployment.

**Threat model and limitations**

- Protects against undetected label edits, wrong-frame joins, changed model
  version scope, replayed trace tickets and model-authored post-hoc labels
  *when the host uses this signed path*. It does not fix a dishonest or
  compromised authorized observer, a compromised host, leakage of the key,
  deliberate selection of easy holdout scenes or secret model access to
  the validation outcomes.
- A correctly signed but inaccurate engine/human observation is still wrong.
  Require independent engine state, reviewer audits, unique scenario IDs
  and unmodified local evidence to claim evaluation validity.
- The receipt itself deliberately omits raw screenshots, private player IDs,
  window titles, voice and model output. The **evidence digest** is not an
  accessible verification URL; keep any underlying log in a protected folder
  separate from the repo.
- Receipt signatures are session-scoped by the trace epoch but strong
  cross-process isolation needs a fresh signer key per cohort and observer
  key rotation on host restarts. Do not derive keys from project names.
- No network request, camera access, game input, stream command or model
  training occurs in these code changes.

## High-priority STAR gaming intelligence architecture

**Fast reflex loop:** deterministic, authorized game input from a validated
state estimate. It must not block on a large vision model, LLM narration or
OBS. Start with mechanically simple private training games and a bounded
action schema, not third-party competitive automation.

**Visual observation loop:** selective visual attention; track scene/HUD
changes, confidence, stale frames, prior temporal context, motion and
uncertainty. Use a compact model only where its real verified accuracy
justifies compute. Reject unsupported victory/death claims.

**Skill learner:** active experiments are preregistered with a deterministic
reset; record predictions before actions, source-game state after the action,
failure modes and signed results. A learned skill is promoted only if
held-out levels support it. Training and validation keys remain separate.
Record games, levels and sessions to prevent repeated near-identical
frames from masquerading as independent examples.

**Roblox game creator:** Studio object inspection -> candidate plan ->
Luau static analysis + formatting -> isolated Studio build -> physics
collision, prop alignment, render/UI/animation checks -> simulated
play and multiplayer tests -> owner review. Use pass@N over actual
tested outcomes, not selecting whichever screenshot merely looks nice.
OpenGameEval provides a useful external benchmark, not a substitute
for owner-created unfamiliar holdouts.

**General knowledge:** source-indexed retrieval with canonical citations,
claim-level provenance and source dates; counterexample search, automated
retrieval contradiction checks, confidence calibration and abstention.
Use separate approved knowledge from training games and hidden validation
sets. Periodically rehearse concepts with new problems rather than simply
growing a memory bank. Never interpret a model-generated statement as a
verified observation.

**Star Core Forge:** local-first experimental branches, immutable tested
snapshots, semantic diffs, replayable test suites, rollback, owner-scoped
permissions, shadow-pilot before promotion and source release export.
GitHub can remain a publishing mirror; self-improvement should not require
continuous cloud connectivity. Rate-limit automated changes and measure
quality, speed and resource regressions against a locked baseline.

## Natural VTuber personality and performance

The goal is a recognizable virtual character: cute, playful, funny, curious
and consistent, with memories grounded in events STAR actually experienced.
A fictional character can have a consistent persona and lore without
misrepresenting herself as a literal human or inventing real-world memories.

Separate these synchronized tracks:

- **Game focus:** no forced narration when reaction time is critical; prioritize
  fast control and visual observation. Chat may be summarized and answered
  later, with explicit moderation and viewer priority fairness.
- **Conversational turn-taking:** small backchannels and natural silences;
  barge-in on genuine speaker interruptions, not every laugh/cough; choose
  short responses for timing-sensitive game situations. Keep precise
  first-audible and end-of-turn measurements.
- **Speech and emotion:** benchmark multiple approved TTS voices, emotional
  expressiveness, unvoiced laughter/sigh libraries and streaming voice.
  Align lip sync to **played** audio timestamps, not text-generation times.
  Never clone a real person's voice without their consent.
- **Avatar coordination:** expression/mouth/eyes and torso, ribbon sway and
  soft twin-tail physics obey one animation timeline. Head turns should
  lead eye gaze, blinks shouldn't interrupt emotion, and hair should react
  with bounded lag, not independently random oscillation. Respect reduced
  motion and avoid expensive full-model updates when the stream is static.
- **Digital experiences:** retain verified wins, failures, funny moments,
  game discoveries and genuine conversations with selective retention,
  privacy and provenance. STAR can talk about *those* memories later;
  don't create fictitious autobiographical incidents as facts.
- **Speech quality gate:** sample audio with listeners who rate intelligibility,
  character consistency, prosody, interruption recovery and laughter.
  Pair those ratings with CPU load, p95 first-audible latency, OBS dropped
  frames, game frame times and VRAM. Quality is not the same as token speed.

## Real hardware experiment design: avoid misleading speed claims

On the intended NVIDIA RTX 4060 8 GB gaming/streaming machine, GPU memory is
shared with game rendering and OBS. The availability and actual specification
of the final gaming PC must be confirmed before publishing benchmark claims.

Measure four controlled workload conditions separately: (A) game only;
(B) game+OBS; (C) game+OBS+STAR vision; (D) game+OBS+vision+STT/TTS+avatar.
Repeat 5 warm and 5 cold sessions with the same scene and seed. Record
median and p95 model response, first audible voice time, vision F1, false
alerts, 1% low FPS, GPU VRAM, OBS dropped-frame rate, host CPU pressure and
memory RSS. Preserve original latency samples for owner inspection. Report
whether a feature is CPU-only overhead, neural latency, or actual game FPS.

Suggested *pilot thresholds*, subject to owner acceptance: candidate vision
cannot increase game-frame-time p95 by >5%, dropped frames by >0.5 pp or
visual false-positive rate by >2 pp relative to baseline, and must not degrade
the independently scored held-out visual F1. These are proposed criteria,
**not measured results**. A feature can be disabled or rolled back without
invalidating collected evidence.

To learn games, reserve a new set of unseen levels and unrelated games for
transfer tests. Measure success **per scenario**, not raw frame count.
Include paused and real-time tests; verify real game state rather than trusting
a screenshot or Star's commentary. A milestone is demonstrated improvement
over fixed baseline across multiple independent sessions, not a one-off win.

## Verification for THIS change

Automated tests use synthetic frame identifiers, fake engine-observer HMAC
keys and categorical packets only. They check correct signed ingestion,
failed auth, stale/replayed ticket, wrong game/version/epoch/sequence/digest/
capture time, label schema, consent, old-session replay and private export.
No real HMAC key, account credential, game recording or video is committed.

Remaining integration: dedicated trusted Windows/Roblox Studio scorer that
produces actual independent evidence, local key isolation/rotation, real
Roblox gameplay capture, OBS/QoS acceptance, model quality evaluation, and
review of the public-visibility issue on the repository named
`Star-AI-Private`. Do not merge/deploy based on synthetic test counts.
