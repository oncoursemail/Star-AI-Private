# STAR AI — Paired Vision Quality Gate
October 28, 2026 · draft research and offline code, not deployed

## Why this improves the system

Existing PRs #729–#751 added authorized Windows game capture, a llama.cpp
paired-frame worker, visual cue acceptance, selective recall and several
optional CPU prefilters. Some synthetic CPU traces were faster and others
regressed. Optimizing speed alone can make an AI appear faster while missing
a hazard or inventing HUD changes. This work introduces a paired, offline
**accuracy + freshness + latency gate**, so STAR can decide which changes
deserve a *real* gaming pilot using independently checked game observations.

## Current references (verified October 28, 2026)

- Roblox OpenGameEval (October 1, 2026):
  https://arxiv.org/abs/2610.02563
  Real Studio play sessions and executable checks evaluate game work more
  honestly than code compilation alone. Inspection before editing is useful.
- GameWorld (April 8, 2026):
  https://arxiv.org/abs/2604.07429
  34 games/170 tasks with state-verifiable outcomes expose the gap between
  agent perception, planning and long-horizon execution.
- VISTA visual memory (October 1, 2026):
  https://arxiv.org/abs/2610.02200
  Allows retrospective visual inspection rather than relying only on the
  current screenshot, with benchmark-specific successes not guaranteed here.
- VISTA active self-exploration (October 26, 2026):
  https://arxiv.org/abs/2610.35051
  Fresh interactive tests and tracked experiment lineage may advance STAR
  Core Forge beyond passive analysis of historical rollouts.
- Roblox Studio's native MCP connector:
  https://create.roblox.com/docs/studio/mcp
  Suitable for authorized inspection and playtesting in Studio.
- Kyutai's October 2026 small English Pocket TTS models:
  https://github.com/kyutai-labs/pocket-tts
  Potential CPU speech option to preserve gaming GPU resources.
- Live2D Cubism lip-sync specification (updated January 29, 2026):
  https://docs.live2d.com/en/cubism-sdk-manual/lipsync/
  Actual audio playback should drive mouth parameters and interruption reset.

## Implemented in this draft

New offline module: star/stream_vision_eval.py. Strict, bounded categorical
JSONL paired baseline/candidate measurements from identical game frame pairs,
plus synthetic unit tests. Model suggestions are compared to independent
host-curated game-state or blinded human labels. Measures cue micro-F1,
precision/recall, false alarms when nothing changed, stale responses,
worker errors/timeouts and p95 processing latency.

Scoring drops late visual guesses. A deterministic paired bootstrap estimates
uncertainty. At least 60 independent frame pairs, 12 positive and 12 negative
examples, non-inferior cue accuracy and no worse false-alert/failure/stale
rates plus at least 10% lower p95 latency are needed for a *manual-pilot*
recommendation. Nothing deploys or switches models automatically. Failures
remain visible in the report instead of being hidden behind averages.

No screenshots, game video, player information, secrets, free-form model
text, voice or source code are stored by this module. Aggregate reports never
reveal individual frame IDs or truth labels. Evaluator source strings are
**descriptive, not authenticated**: the trusted host must securely retain
engine-test receipts and protect hidden labels from model prompts.

### Input example (one JSON object per line)

{"case_id":"r001","game_id":"localobby","game_version":"v1","partition":"holdout","truth_source":"studio_engine","truth":[{"kind":"hud_change","region":"hud"}],"baseline":{"status":"accepted","findings":[{"kind":"hud_change","region":"hud","confidence":0.92}],"latency_ms":520,"age_ms":600},"candidate":{"status":"accepted","findings":[{"kind":"hud_change","region":"hud","confidence":0.96}],"latency_ms":240,"age_ms":300}}

Run locally: python -m star.stream_vision_eval path/to/trusted-trace.jsonl

Run separate blinded holdout cohorts for different game versions to detect
failure to transfer. Do not tune thresholds repeatedly against heldout labels;
retire compromised holdouts and replace them with unseen tests.

## Next integration priorities

1. Record genuine Windows Roblox Studio + OBS host timings, model predictions
   and independently verified engine changes for this evaluator. Measure real
   FPS and first audible TTS using the existing realtime benchmark too.
2. Test baseline full frames against ROI, static hashing and adaptive prefilter
   on paired, heldout scenes, rejecting speedups that harm visual truth.
3. Connect independently signed gameplay outcomes to the existing skill bank,
   prediction lab and curriculum ladder. Teach tactics only from practice
   trials; reserve validation worlds for checking actual skill transfer.
4. Link voice playback, mouth shapes, expressive eyes, ribbons and twin-tail
   physics to actual speech/audio events and a focus-aware quiet policy.
   Preserve genuine digital experiences as memories and avoid inventing
   human childhood or offline experiences. Publicly identify Star as an AI.
5. Give Star Core Forge hypothesis lineage, fresh rollout generation,
   independent reviewers, hard quality gates and automatic local rollback.
   GitHub remains an optional review/publishing destination, not a requirement
   for Star's own experiments.

This draft is NOT evidence of faster neural inference, better real-world
gameplay, actual live speech or improved underlying model weights. Synthetic
tests demonstrate only code-path correctness. The repo called Star-AI-Private
is currently public, so do not commit private recordings or credentials.
