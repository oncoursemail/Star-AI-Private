# STAR: graphics-aware game building, faster useful intelligence and genuine VTuber presence
**Research/implementation date:** 2026-10-29
**Status:** experimental, opt-in architecture; new quality gate is offline and advisory.

## Why this upgrade

The hardest bottleneck in AI game creation is frequently **visual correctness**, not producing a syntactically valid Luau script. A complete game can pass structural checks while displaying bad proportions, unreadable HUD cards, broken animation, wrong lighting, floating props or awkward VFX.

GameDevBench (ICML 2026) covers 132 real game-development tasks; its reported best-agent overall success was 54.5% and its graphics-focused 2D subset 31.6%. The paper found visual/video feedback improves performance in a controlled setting. This is an incentive to independently **observe → compare → repair → replay**, not evidence STAR currently achieves those rates.

Sources:
- GameDevBench, ICML 2026: https://sethkarten.ai/papers/gamedevbench.html
- Roblox's OpenGameEval paper (2026-10-01), 84 human-curated Studio tasks and executable assessments: https://arxiv.org/abs/2610.02563
- Roblox's open evaluation harness: https://github.com/Roblox/open-game-eval
- GameWorld (2026-04-08), 34 games / 170 verifiable tasks: https://arxiv.org/abs/2604.07429

### This implementation: `star/studio_multimodal_quality_gate.py`

A reviewer-independent, matched-scenario, five-dimensional quality comparison:
1. A trusted host preregisters **8–64 withheld scenarios across >=2 games** and archives a timestamped manifest SHA-256 before any run. A hash presented after the fact is NOT preregistration.
2. Baseline/candidate builds are rendered on the same scenario. Trusted hosts attest independent engine integrity and completed playthrough, and retain screenshot material outside the language-model context.
3. Independent reviewers assess **geometry, composition, readability, animation and effects** on an explicit 0–5 anchored scale; screenshots are identified by SHA-256 without storing pixels in this evaluator.
4. An independently held HMAC key binds signed observations to the study, case, game version, scenario, screenshot, timestamp and grades. This authenticates the reporting host, not the truth of its grades.
5. The quality gate rejects missing/double/replayed/stale/wrong-scope evidence, contradictory grades on identical screenshots, lost playthrough integrity, severe per-case regressions, mean dimension regressions or improvement isolated to one game.
6. A favorable result is **eligible_for_review**, never automated deployment, editing, publication, or a declaration of visually perfect art.

Tests use *synthetic reviews*. Real screenshot quality, gameplay and ratings are NOT verified in this PR. These results should eventually become a second independent review layer behind the already built Studio scene regression and actual playthrough evaluators.

#### Reviewer instructions (to be developed separately)

Use a fixed pair of real game snapshots and one owner-curated visual rubric. Before revealing a candidate label, independently score each view for obvious clipping/floating props; coherent object grouping/scale; legibility at standard stream resolution; animation cadence and joint correctness; and appropriate VFX/lighting with no flashing artifacts. Randomize A/B order; prefer >=2 reviewers and report inter-rater agreement. Keep reviewers blind to code/model identity. Human ratings are subjective and must not replace engine checks.

## Intelligence: learn by verified experiences, not self-report

**Recommended next architecture:**
- A fast event model observes actual game frames and predicts a bounded next-state distribution with confidence. It must distinguish *game facts*, *viewer claims*, and *uncertain inferences*.
- A task-level planner chooses controlled actions. It only acts via existing owner-scoped game gates. The model cannot self-certify outcome success or unlock permissions.
- An independent test host verifies objective completion (including lost lives, soft locks, multiplayer desynchronization and reset validity) and attaches a signed practice record.
- The practice ledger indexes successful and failed *action sequences*, scene fingerprints and game version; retrieve only relevant examples for future unfamiliar tasks, excluding holdouts.
- A curriculum generator proposes harder or novel challenges, but an independent evaluator with sealed seeds decides whether skill transfers. Count distinct games and task families, not only repeated wins on one map.

**General knowledge:** retain source URLs, retrieval timestamps, scope, contradictions and uncertainty rather than unlimited opaque summaries. Keep model-curated memories separate from host-verified past actions, and attach provenance to a compact response context. Benchmark answer correctness and citation validity on holdout questions.

**Code/UI/3D:** use small constrained generation proposals, property/physics checks, visual regression and simulation. A build is not done until it passes platform execution *and* independent visual/playable review. Reuse original editable UI/3D assets instead of flattening their output into a screenshot.

## Performance: optimize end-to-end work rather than tokens/s

Observed on the `starai` Linux device during this run (one non-intrusive inspection):
- 48 logical CPUs, 125 GiB total memory, ~40 GiB available, 5.2 GiB swap allocated, six `llama-server` processes shown.
- `nvidia-smi` produced no GPU information on that host; no GPU or inference-speed conclusion can be drawn.
- Swap *allocation* alone is not proof of current swapping activity. Measure `vmstat`/PSI, active model context residency, and per-request queue latency before tuning.

**Priority plan:**
1. Deduplicate or isolate six potential model-server queues with host-level admission. Use health and pressure samples rather than treating RAM as unlimited.
2. Protect Roblox FPS/OBS output/TTS playback under an explicit real-time budget. Run graphics checks, expensive game evals and research on non-streaming workers only.
3. Keep the static streamer persona and tool schema prefix stable for llama.cpp server slot KV reuse. Benchmark cache-hit rates; a prompt-cache flag alone does not prove reuse.
4. Run a true paired A/B comparison of model routing, prompt caching, speculative decoding and batch sizes. Measure request→audible p95, useful task completion, frame-time p99, GPU peak, process RSS, quality gate outcome and interrupt stop latency; reject any quality/performance tradeoff that breaks live reliability.
5. Prefer CPU-powered wake/end-of-turn and avatar physics if actual measurements indicate less GPU contention. Avoid installing a new TTS or vision model based only on its advertised parameter count.

Reference: llama.cpp server prompt caching notes (updated 2026-08-11): https://multigrid.ai/learn/llamacpp-prompt-caching

## A genuinely natural AI VTuber: a unified attention/action timeline

Star should not incessantly narrate the game. Conversation, game focus and avatar animation need to share an event clock:
- **Playing:** one low-latency game-control lane; speech can be withheld during jumps, fights, critical aim and visually complex cutscenes. Queued chat does not bypass moderation or become tool instructions.
- **Interacting:** use audio end-of-turn detection, short acknowledgements only when useful, interrupt-driven cancellation/neutral animation, and no continued stale speech. Backchannels differ from real interruptions.
- **Reacting:** voice pitch, laughter, expression, blinking, twin-tail spring physics and mouth visemes should reference observed events and actual *consumed* audio position, not fabricated chat or queued TTS.
- **Remembering:** describe her own verified past game attempts, goals and mistakes; spontaneous jokes can reference what really happened. Keep identity consistent, transparent that Star is AI and never invent off-stream human experiences.
- **Learning:** ask herself scoped hypotheses, run permitted experiments, and update confidence from verifiable outcomes rather than prose agreement.
- **Privacy:** avoid preserving raw viewer names, chat messages, video/audio or account identities for personality memory. Consent and retention are separate controls.

Turn-taking reference: https://docs.livekit.io/agents/logic/turns/ (audio turn detection, adaptive interruption and dynamic endpointing). VTube Studio official docs: https://denchisoft.com/documentation/.

## Release and benchmarking protocol

For a future owner-authorized Windows test:
1. Freeze two well-formed Roblox Studio snapshots and independent evaluation seeds. Keep code history and reference assets.
2. Capture local, authorized screenshots at consistent resolution, camera and UI scale; verify play state and outcome independently.
3. Obtain blinded visual rubric grades and record the host-only seal in a separate audit ledger before candidate execution. Keep screenshots local.
4. Compare gameplay success, average graphics ratings per game, worst-dimension losses, p95 latency, FPS, OBS output and actual audible avatar synchrony.
5. Reject visual regressions, gameplay failures and missing evidence even if the candidate is faster. Human review must approve any deployment; improvements remain OFF until then.

### Limitations, explicit

The new code **does not** itself generate artwork, operate Roblox, master a game, speak, train weights, change models, or infer whether a screenshot is beautiful. It is a verifiable *measurement and review boundary*. Synthetic fixture scores in its tests are not proof of improvement in Star's deployed intelligence, speed, gaming or VTuber presence. Its release thresholds are initial review heuristics, not validated human quality scores.

The repository named `Star-AI-Private` is publicly visible. Treat it as public; never add keys, personal memories, recordings, user secrets or non-approved project files.
