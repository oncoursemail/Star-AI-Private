# STAR — Validate lower-cost game vision against trustworthy held-out outcomes
Research and implementation: 2026-11-08. Development branch: `feat/star-vision-pixel-paired-validation-20261108-auto165`.

## What's new (implemented, NOT a claim of increased model speed)

The existing opt-in WindowsGameCaptureHost can downscale its VLM worker input
(PR #1070), and can reject late observations (PR #1071). A smaller input does
not by itself establish lower end-to-end latency *or* acceptable recognition:
some HUD glyphs are too small to survive resampling, and resizing costs CPU
time. Before this change, the independent PairedOfflineVisionRunner compared
two models on unchanged pixel pairs but had no way to run a candidate-only
downscale experiment using the same captured source frames.

Now the offline runner accepts `candidate_max_pixels=None | int`. Default is
None (full-resolution, original behavior). An explicitly configured candidate
pixel budget performs proportional Pillow BILINEAR resampling of BOTH the
reference and current frames, *only for the candidate*. The baseline receives
the untouched pixel snapshots. The trace identity is still SHA-256 of the
**full native-resolution current frame**. Candidate preprocessing is inside
the timed variant, so the quality/speed comparison includes resize overhead.

Safeguards: fixed 72..8,294,400 pixel budget, host-only parameter, no model-
chosen crop, randomized/counterbalanced variant execution already provided by
the runner, no raw image export, immediate scrubbing of resampled bytearrays,
ambiguous model stop still quarantines and aborts the cohort, and exceptional
preprocessing fails the existing cohort closed rather than reporting success.
This change adds no live stream action, autonomous game control, memory
promotion, inference backend change, or automatic selection of a model.

## Primary-source research and engineering findings

1. Aggarwal & Welleck, *Gym-Anything-RT* (arXiv, 2026-10-27),
   https://arxiv.org/abs/2610.37567 — agents have dramatically different
   success in genuinely real-time versus paused minigames. Therefore record
   **game-clock** action deadlines, not only VLM tokens/sec.
2. Yan et al., *Proact-VL* (2026-03-03),
   https://arxiv.org/abs/2603.03447 — commentary quality, quantity and
   response timing all matter. Only verified, fresh gameplay observations
   should be offered to Star's social/voice planner; incorrect low-resolution
   HUD recognition should result in silence, not fabricated reactions.
3. llama.cpp speculative decoding guide (repository documentation, checked
   2026-11-08), https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md
   — speculative decoding can boost generation under suitable draft/target
   configurations but adds draft compute and memory; compare actual
   first-decision latency, VRAM and FPS instead of extrapolating speed.
4. Roblox, *Studio is Going Agentic* (2026-04-15),
   https://about.roblox.com/newsroom/2026/04/roblox-studio-going-agentic
   and official built-in Studio MCP,
   https://create.roblox.com/docs/studio/mcp — use authenticated Studio
   playtest results, scripts and server-side telemetry to establish scene
   ground truth, and keep private evaluations separate from public streams.
5. Microsoft MAI-Gym (arXiv, 2026-10-14),
   https://arxiv.org/abs/2610.20939 — reproducible resettable tasks and
   independently verified rewards enable meaningful GUI-agent improvement,
   but simulator success should not be described as third-party game mastery.

## Owner-controlled validation protocol (not yet run on Windows GPU)

1. Select one **owner-approved private** game build with a fixed version, and
   preregister at least 60 novel frames: >=12 positive HUD/event changes,
   >=12 true negatives, varied small text, fast motion, combat effects,
   controller prompts, and different HUD scales. Maintain separate blind
   ground-truth labels withheld until all predictions have committed.
2. Run `PairedOfflineVisionRunner(candidate_max_pixels=921600)` for a
   1280x720-equivalent candidate budget (or a predeclared smaller budget).
   Hold model weights, prompt, token cap, backend, GPU load, frames and clock
   constant. The runner alternates model order to reduce warm-cache bias,
   but real Windows run-to-run variation still needs independent control.
3. Seal predictions *before* independent Studio/observer scoring, then evaluate
   the same case cohort with `PairedVisionTraceHost.owner_report(...)` and
   `compare_vision`. Inspect macro held-out precision, recall, F1,
   false-alert, stale, failure rates and p95 latency.
4. Use `compare_vision`'s `eligible_for_manual_pilot` only as permission to
   **consider** a monitored experiment, not as proof of superiority. A
   candidate must also preserve gameplay FPS p1/p5, OBS dropped frames,
   audio interruptions, end-to-end capture-to-action p95, CPU and VRAM
   headroom. Manually review missed small-scale cues. Trial on a different
   unseen game version before default-on release.
5. Keep live setting OFF unless a qualified Windows private rehearsal
   passes. A quality regression must cause an explicit rollback to the
   original full-resolution worker path, not automatic high-confidence
   claims.

## Next high-impact capabilities — ranked by evidence rather than hype

- **Verified gaming improvements:** record privately authorized actions and
  independently signed game outcomes; add held-out unseen maps/seed policies,
  counterbalanced training runs, latency-specific failure atlases and a
  genuine closed-loop practice coordinator. Existing game-skill and holdout
  modules are prerequisites, not evidence that Star already mastered games.
- **Compute awareness:** benchmark 8GB RTX 4060 with game + OBS + TTS + VLM
  concurrently. Prefer CPU-backed voice if its measured audio latency and
  quality beat the GPU-sharing baseline. Quantized model size does not imply
  performance without including KV cache and concurrency.
- **Human-like VTubing without misleading viewers:** consistent disclosed
  AI persona, grounded reactions to verified gameplay, genuine turn-taking,
  emotional expressiveness and pauses, stage/voice synchronization, memory
  only for events she actually experienced or audibly said, privacy filtering,
  and actionable viewer moderation. Avoid fake claims of emotions,
  consciousness, achievements or interpersonal relationships.
- **Creative intelligence:** use authorized Roblox Studio MCP to inspect,
  implement, playtest, and repair scripted experiences. Add Blender,
  animation, lighting, voice, composition and game design exercises with
  independent visual quality review and runnable acceptance checks.
- **General knowledge:** source-attributed, dated, revisable retrieval,
  fact/confidence boundaries, consented episodic memory and explicit
  conflict resolution; do not turn model-generated guesses into skill facts.

## Limits

This commit has deterministic offline tests, not an RTX 4060 gaming speedup,
not proof that Star can play a title autonomously, not a production streaming
integration and not evidence of human consciousness. The private Windows
rehearsal and held-out frame-label cohort are still required. Do not publish
raw gameplay, identities, signing secrets or hidden evaluation labels.
