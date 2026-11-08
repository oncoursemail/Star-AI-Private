# STAR: scenario-stratified real-time game failure atlas and generalist roadmap

**Research / implementation:** 2026-11-07 (America/Chicago)
**Status:** experimental, entirely offline; no Windows/OBS/game/voice processes launched.

## What changed and why

The preceding `game_realtime_gap_audit` can flag a statistically screened
paused-vs-real-time performance discrepancy on matched, independently
host-declared test outcomes. But a global deficit can hide two fundamentally
different situations:

1. STAR misses almost every game mechanic because she cannot act on moving
   information before the scene changes.
2. STAR succeeds in some scenes and fails only on particular mechanics, camera
   angles, obstacles or loads. A global speed rewrite may not repair these
   failures, and could make stronger contexts worse.

This release adds **`star.game_gap_failure_atlas`**, an offline diagnostic
which consumes the complete *already validated* holdout pairs. It reports:
- Anonymous scenario slots (no scene ID, seed, player, raw frame or transcript).
- Paused/live victories and progress, p95 real-time action delay, deadline
  misses and overlap of lateness with paired paused-only failures.
- Whether the direction of the gap is present in every scenario, spread
  across multiple, concentrated in one, or **opposite on different scenes**.
- A bounded follow-up *experiment class*, not automated game control:
  grounding/strategy probe; reproduce scenario heterogeneity on new
  practice data; camera-to-engine-ack timing probe; moving-world perception
  and policy probe; or gather fresh preregistered holdouts.

The diagnostic **does not** propose a policy change, reveal holdout case keys,
tune weights, request an input permit, speak, stream or declare the model
smarter. Its host booleans and protocol hash are not signed proof.

## Statistical trap: pooled wins are not broad game mastery

A 24-case synthetic regression fixture has 16 paused-only failures on two
scenarios and 4 real-time-only successes on a third. The parent exact paired
sign test still flags a substantial pooled gap. The atlas separately marks
`opposing_scenario_directions`, requiring new-scenario reproduction before
calling it a broadly applicable real-time deficit.

This is a **descriptive** subgroup analysis: per-scenario counts are often
small, share model/scene conditions and are not independent trials of overall
transfer. Subgroup comparisons must NOT generate uncorrected statistical
significance claims; do not select hyperparameters using holdout slices.

The honest experiment is to precommit the *next* protocol in a separate
trusted host and compare a latency intervention with a perception/strategy
intervention, using new, hidden, balanced game versions and mechanic types.
Keep evaluation and training data separate, and never feed hidden failures
directly back to the self-learning model.

### Next trusted-host instrument design

Host-owned JSONL evidence for each game trial, after owner-approved private
test consent, should contain:

- Game/version/build digest, scenario family and seed commitment in a
  protected host-only manifest, with host-signed timestamp and run order.
- Independent capture timestamp, frame age, model decision time, input
  submission, OS acknowledgment, in-engine application, resulting state
  transition and game outcome. Preserve a single monotonic clock and mark
  unknown missing measurements as unknown, not zero.
- Predeclared time budget and deadline; treat late actions and late
  *confirmed effects* separately.
- Render FPS percentiles, VRAM headroom, OBS encoding/render drops, CPU
  pressure and concurrent TTS/vision load.
- Paused-vs-live pairs with counterbalanced order and verified equivalent
  reset positions. Group by mechanics and difficulty **before** looking at
  results, avoid multiple-comparison peeking and use fresh holdouts for
  intervention confirmation.

If success in the paused environment is weak, first repair the world model
and grounding. If paused is strong but live misses are late across several
mechanics, examine capture-to-effect latency. If only one map degrades,
investigate its unique perception/controls. **Correlation is not causation.**

## Relevant primary research checked November 7, 2026

**Real-time generalist gaming.** *Gym-Anything-RT* (published October 27, 2026)
created 100 real-time visual minigames with pause/slowdown controls and found
large gaps between paused and moving-world evaluation. Their reported numbers
are *research findings on evaluated models*, not STAR benchmarks.
https://arxiv.org/abs/2610.37567

**Game creator verified intelligence.** Roblox *OpenGameEval*
(arXiv:2610.02563; repository updated in 2026) runs reproducible,
stateful Roblox Studio experiments with executable checks. Agents that inspect
relevant objects before editing perform better in its study. STAR should
measure inspections, tool use, script validation, live playtests and genuine
game-state effects, not just natural-language coding confidence.
https://github.com/Roblox/open-game-eval

**Roblox integration change November 4, 2026.** Roblox Studio MCP now
supports permission-scoped Open Cloud tasks and asset import. Scoped game
permissions and the owner's sandbox experience are prerequisites for all
writes. APIs that can publish, charge Robux, modify player data, change
monetization or enact moderation require independent owner approval. An
unprivileged test harness must not silently grant these capabilities.
https://devforum.roblox.com/t/studio-mcp-server-updates-open-cloud-access-in-your-mcp-client-and-asset-import-workflows/4975849
https://create.roblox.com/docs/studio/mcp-open-cloud

**Speed, not just tokens/sec.** `llama.cpp` SPEED-Bench measures response
latency, throughput and speculative-token acceptance. Compare immutable
model/quantization/context/prompt conditions with warm/cold cache runs; reject
a route that worsens real-game p95 frame time, first-action latency or voice
quality. The 8 GB GPU budget is shared with rendering/OBS; use conservative
VRAM admission, scheduled prefill, cache isolation and CPU TTS trials.
https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md

**Spontaneous yet grounded VTubing.** Proact-VL (ICML 2026) studies deciding
*when* to speak, continuous scene perception and restrained contextual gaming
commentary. Realtime-Venus (September 2026) explores full-duplex listening
and appropriate non-interruption. DyaPlex (NeurIPS 2026) explores synchronized
speech and dyadic motion. STAR needs voice/eye/gesture synchronization,
backchannels, contextual silences, recovery from interruptions, gentle humor
and consistent interests; these are *measurable interaction qualities*,
not evidence of consciousness or human identity.
https://proact-vl.github.io/
https://realtime-venus.github.io/
https://research.nvidia.com/labs/amri/projects/DyaPlex/

## Higher intelligence roadmap with objective gates

**P0: Actual local measurements.** Freeze a private game + OBS scene; collect
a real paused/live replay on the Windows host and run the parent gap audit
followed by this atlas. Do not treat synthetic tests as victories. Publish only
an anonymous scorecard and verified durations; keep actual traces private.

**P1: Controlled faster brains.** A/B lightweight reactive controller,
dedicated background tactical planner, evidence-grounded retrieval, shared
prefix caching, speculative decoding and optional CPU TTS. Guard against
frame drop, event staleness, clipped audio and context contamination.
Track p50/p95/p99 capture-to-*effect*, deadline compliance, frame time and
verified outcome. Use a quality and game-win non-regression gate.

**P2: Cross-mechanic game competence.** Teach only on practice episodes;
test on locked unseen scenes and new game versions. Keep causal hypotheses
separate from observed outcomes, include failure examples and maintain an
independent regression bank. Build mastery over navigation, tracking,
timing, objectives, strategy, cooperative behavior and multi-game transfer.
No unofficial anti-cheat bypass, cheating in multiplayer, or unauthorized
account/input automation.

**P3: Autonomous game design.** Studio inspect -> plan -> build -> static
Luau checks -> executable playtest -> visual inspection -> regression review.
Keep the Studio target constrained to owner-approved test experiences. Require
both client/server security checks and reproducible screenshots for UI,
VFX, character grips and gameplay. Use best-of-N only within bounded resource
budgets with independent tests; do not claim quality from pass@N alone.

**P4: General knowledge and expressive digital life.** Provenance-aware
retrieval, source freshness, uncertain-answer abstention, generalist quiz
holdouts, long-horizon tool tasks, coherent autobiographical *character*
memories with explicit consent and expiry, and self-initiated creative projects.
Never misrepresent STAR as a biological person or fabricate lived experiences.
Use an owner-controlled sandbox for independent learning. Publishing,
purchases, moderation and safety-sensitive changes remain independently
permissioned.

## Acceptance criteria for the current patch

- Deterministic offline operation with no network, audio, OS input or OBS calls.
- Preregistered paired cases and verification enforced by the parent module;
  no cherry-picked or missing cases; at least two real scenario families.
- Opposing directional effects exposed; no pseudo-significance or causal claim.
- Correct p95, deadlines, progress and count arithmetic under shuffled order.
- No returned scenario/seed/game/player identifiers or sensitive transcripts.
- Static checks and regression tests pass on developer host.
- **No claim** of Windows game testing, neural speedup, voice quality boost,
  new gameplay ability, Twitch readiness or merged production code.

## Reproducible private test command

```bash
python -m pytest -q tests/test_game_gap_failure_atlas.py tests/test_game_realtime_gap_audit.py
```

This module is a narrow, inspectable diagnostic step toward measuring real
gameplay learning. The next major engineering task is a trusted host wrapper
that can collect and attest genuine Windows game-action traces without
letting the model read holdout labels or start broadcasting.
