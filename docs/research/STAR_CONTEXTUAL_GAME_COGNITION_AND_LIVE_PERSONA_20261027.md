# STAR Intelligence — Contextual Game Foresight, Long-Horizon Creation and Believable VTubing
**Research checkpoint:** 2026-10-27 · **Implementation:** offline, owner-enabled diagnostic only · **Deployment:** not live

## Why this checkpoint differs from previous STAR upgrades

STAR already has an opt-in, pre-action game forecast ledger backed by independently
verified *practice* outcomes. It can tell the owner "these forecasts were poorly
calibrated." But its original broad advice combines predictions made on different
objectives and game actions in one game version. Suppose a model often clears a
small jump but consistently fails a precise crouch: pooled advice can tell it the
wrong confidence for *both*. More learning data is not inherently more useful
learning data when its contexts are mixed.

This checkpoint adds **exact-context, freshness-limited calibration**, abrupt
outcome-shift detection, and signed-evidence **practice-focus suggestions**.
No game input, model training, chat, internet request, owner permission, GitHub
merge, stream start, or real player interaction is performed by these methods.

### Implemented interface and guardrails

`GamePredictionLab.contextual_advice(model_id, *, game_id, game_version,
objective_id, situation_id, action_id, proposed_bps, now_unix_s)`:

- Uses only predictions made *before* action and resolved against the exact
  practice trial already verified by `GameplaySkillBank`. Independent holdout
  trials are excluded at ingestion and resolution; this API never queries them.
- Separates model builds, game builds, objectives, observed situations and
  authorized actions. Neither unrelated actions nor pooled game-wide wins may
  affect this result.
- Rejects context advice when fewer than **20 exact-context practice trials**
  are available within the preceding **14 days**, or fewer than **8** lie in the
  same 20%-wide forecast-probability bucket. No cross-bucket extrapolation.
- When 24+ matching bucket observations exist, compares the most recent 12
  with the preceding 12. A change of six or more successes/failures blocks
  calibration with `practice_distribution_shift` until a trusted review.
  This heuristic is deliberately conservative, not a formally calibrated
  change-point test.
- With stable evidence, returns a bounded Beta(2,2)-shrunk **reviewable**
  probability estimate. `authorized_to_play` is *always false*.
- Excludes future-dated and old evidence relative to the trusted host's clock.
  Reads are bounded to 1,024 recent records; tests use no network or Studio.

`GamePredictionLab.focus_suggestions(...)`:

- Groups the same fresh, verified practice evidence by
  `objective/situation/action` and distinguishes **overconfident failures**,
  **underestimated successes**, and **unreliable predictions**.
- Requires at least eight signed practice observations in a group; ranks
  established errors higher than extremely small groups; emits short bounded
  diagnostic cards (no screenshots, player IDs, scripts, raw traces, receipts
  or scorer keys). Distinct game builds cannot be mixed.
- This can guide the *owner or trusted offline curriculum constructor* toward
  a specific challenge, not create a new skill, claim mastery, choose game
  keys, change settings, unlock permissions, or train neural weights.
- Reproducing an original error on unseen held-out levels is still required to
  establish transfer. An AI's self-reported improvement is not independent
  evidence. Generic `advise()` remains for backward-compatible pooled
  diagnostics; hosts should prefer `contextual_advice()` for action-level review.

Example owner-side, not model-authored, call:

```python
from star.game_prediction_lab import GamePredictionLab

# bank is a host-owned, independent GameplaySkillBank
with GamePredictionLab(bank, "private_game_forecasts.sqlite") as lab:
    review = lab.contextual_advice(
        "model_v7", game_id="private_obby", game_version="levelpack_3",
        objective_id="reach_platform", situation_id="moving_ledge",
        action_id="jump", proposed_bps=8800, now_unix_s=trusted_clock(),
    )
    if review.status == "practice_distribution_shift":
        queue_human_diagnosis("Moving ledge assumptions may have changed")
    # Even reviewable advice is NOT a keypress authorization or a verified
    # model upgrade. Never expose raw bank DB, signature keys, or holdouts.
```

The `bank`, `trusted_clock`, and `queue_human_diagnosis` symbols in this
example are provided by the authorized embedding application, not by STAR.

## Evidence and design changes recommended next

### 1. Long-horizon game creation: close the artifact-to-play gap

**CEGame-Bench** (submitted **2026-10-19**) evaluates full game-creation
agents across five engines, from empty projects through real-input gameplay.
The paper reports only **16% of agent game runs reaching the ending**, with
execution/gameplay quality weaker than integration success. Its
requirements-driven playtesting skill improved evaluated execution scores in
reported experiments, but those gains are *not* STAR measurements.

STAR should promote games only after a reproducible sequence:
design contract -> inspected world/dependency graph -> editable build ->
automated controlled playthrough -> objective completion -> save/restart ->
multiplayer/network tests where applicable -> owner aesthetic review.
The **first missing acceptance step** determines the next repair, not a vague
"looks good" model score. Store only safe artifact hashes and passing or failing
check identifiers in the self-improvement ledger.

Reference: https://arxiv.org/abs/2610.26098

### 2. Game-environment inspection before any edits

**OpenGameEval**, posted **2026-10-01**, evaluates 13 frontier models on
84 Roblox Studio tasks. In that study, inspecting relevant objects before
acting was associated with +13.4 percentage points on scene-only tasks
and +9.8 on script-only tasks, controlling for model and task. Association is
not a guaranteed causal effect or STAR performance gain.

Recommended STAR "Inspect-Plan-Build-Test-Repair" contract:

1. Capture scoped Studio object hierarchy, scripts, collision groups,
   attachments, transforms and terrain/world anchors.
2. Construct a typed contact/containment graph: floors support walls,
   roof attachments have supports, props have plausible anchors, UI remains
   native/editable, and mechanisms have wiring and interaction affordances.
3. Generate up to four genuinely different candidates; verify each with
   geometry assertions (overlap, z-fight and penetration tolerances), playtest
   traces and rubric-guided visual review.
4. Require runnable evidence that the player can traverse doors/stairs,
   complete objectives, and interact with needed objects. No human-grade
   quality claim from a static screenshot alone.

Roblox Studio's built-in MCP (announced **2026-03-05**) and the Playtest
Agent beta (announced **2026-04-09**) provide relevant primitives; do not
assume every external game or published Roblox place grants this access.

References:
- https://arxiv.org/abs/2610.02563
- https://github.com/Roblox/open-game-eval
- https://devforum.roblox.com/t/studio-beta-studio-assistant-mcp-playtest-agent/4566767

### 3. Genuine self-directed gameplay: predictions -> experiments -> adaptation

Extend `contextual_advice` into a **reviewed curriculum loop**, not an
uncontrolled reinforcement-learning claim:

- Independently measure a compact game state (position/velocity bins, player
  health, accessible objects, hazard type, objective progress, timestamp).
- Have a fast controller propose *only* previously permitted symbolic inputs,
  while a slower model proposes a falsifiable prediction and an uncertainty
  estimate. Record the prediction **before** input.
- Follow the existing signed `PortfolioStudioBridge` evidence path.
- If failure was predicted, explore a different approved move or refine the
  skill. If failure was surprising, queue a hypothesis and verify it on a
  different private practice seed. An LLM cannot declare its hypothesis true.
- A signed practice card can prioritize rehearsal; only sealed, independently
  scored unseen-game results can measure transfer. Compare macro-averaged
  change across *different* games, not raw total wins.

Risk: replayable offline exercises can be overfitted. Lock hidden eval seeds,
scenario hashes and scorers outside STAR's agent and its editable codebase.

### 4. General knowledge and long-term interests

"More facts" should mean **retrievable, attributable, current, reusable
knowledge** rather than dumping internet pages into a prompt.

- Build a local source atlas with license, source URL, fetch timestamp,
  topical scope, extraction digest, trust tier, and expiry/update policy.
- Use project-scoped retrieval and semantic deduplication; never execute code
  or grant privileges because retrieved text told STAR to.
- Separate source facts, recalled verified episodes, inferred hypotheses and
  deliberately fictional character lore. Every factual public claim needs
  evidence freshness; missing evidence should trigger uncertainty, not fiction.
- Train smaller, verified reusable skills: research a question, cite an
  independently checkable source, attempt a task, run tests, create a
  correction note, compare performance on unseen tasks.
- Distill expensive reasoning into compact playbooks *only after* evaluation;
  do not treat AI-generated summaries as authoritative ground truth.
- Give Star bounded self-directed interests (drawing, game design,
  storytelling, analysis, social chat), with idle-time budgets and visible
  "what I'm working on" status. Memory can support consistent character
  continuity without claiming human childhood or experiences Star never had.

Acceptance metric: blinded citation accuracy and task completion on
time-separated/held-out material, plus retrieval latency and source provenance.

### 5. Make an 8 GB GPU behave like a multitasking game machine

Do not run a single giant inference pipeline continuously through every frame.
Use three rates: ultra-cheap input safety every dispatch; lightweight visual
and conversation cues at an adaptive rate; expensive strategy and knowledge
work only during high headroom/offline practice.

Use an *actual measured* benchmark, never inferred speedups:

| Trial | Measurement | Fail closed when |
| --- | --- | --- |
| Tiny local quick reply vs default LLM | median/p95 time-to-first-token, factual correctness | accuracy deteriorates |
| n-gram/draft speculative decoding | effective emitted tokens/second, draft accept ratio, first audible audio | p95 audible delay or frame time worsens |
| CPU Pocket TTS small model vs current voice | blind voice quality, laughter expressiveness, real onset, CPU utilization | Star loses characteristic voice or game p1 FPS |
| Prefix/KV caching | speed with unchanged prompts; prompt-digest invalidation | persona/knowledge changes use stale cached facts |
| Sparse vision sampling | missed hazard rate + 1%-low FPS | missed objective transitions or stale frames |
| Background game-builder experiments | test pass rate plus frame/VRAM/audio pressure | on-stream tasks compete with game or voice |

Kyutai's official Pocket TTS repo documents its **October 2026** 18.2M,
6.9M and 1.9M parameter English models, designed to run on CPU. Published
throughput on other hardware is not a benchmark for STAR's machine.
The existing `stream_realtime_benchmark.py` can compare paired real
host measurements without changing live routing. Upgrade only after 20+
balanced recordings, no dropped audible turns, and a stable game-FPS floor.

References:
- https://github.com/kyutai-labs/pocket-tts
- https://github.com/ggml-org/llama.cpp

### 6. Expressive VTuber design without speaking constantly

The strongest social improvement is not a larger prompt. It is a **stateful
speech-performance director** separating game attention, talk priority,
genuine audible playback, avatar cues and remembered episode facts.

- **Attention:** hard gameplay moments can defer casual chat; questions gain
  fairness over time; important owner interruptions still take priority.
- **Duplex turn taking:** distinguish corrections from "mm-hm", laughter and
  background noise, and resume interrupted speech carefully. The official
  LiveKit turn-handling controls expose duration, word-count and false
  interruption safeguards; model adaptation still requires real evaluation.
- **Expression:** implement intensity curves for eye squint, pupil motion,
  blink, head pitch, shoulder lean, mouth open, laughs, brows, and Star's
  playful cat/puppy mode. Expressions should be bound to the actual voice
  audio timeline and game events, not text generation timestamps.
- **Character consistency:** maintain approved gold/black Star mascot design,
  four-point star pin, ribbon hair, twin-tail physics, mitten hands, and
  companion interactions. Show changes in a clean editable 2D/3D rig,
  not a flattened image sprite pretending to be a rig.
- **Physics:** Live2D documents real-time hair movement via Cubism physics;
  test bounce, settling, coupling to head rotation and frame-rate invariance.
  VTube Studio's official plugin API supports locally scoped WebSocket
  parameter/expression control, but needs explicit user-side API opt-in.
- **Believability:** laughter should have breath/prosody changes, not just
  "haha" spoken flatly. Star may tell true memories of verified play sessions,
  refer to a fictional character backstory as lore, and acknowledge that she
  is AI. Never fabricate human relationships or off-camera experiences.

References:
- https://docs.livekit.io/reference/agents/turn-handling-options/
- https://docs.live2d.com/en/cubism-editor-manual/physics-operation/
- https://github.com/DenchiSoft/VTubeStudio

### 7. Self-owned Forge and human-supervised autonomy

STAR Core Forge should be the durable local authority for its experiments,
while GitHub is optional draft-review/publication transport. A candidate
change must have an immutable provenance record:
`source_version -> proposal -> isolated build -> offline tests -> simulator
trials -> bounded human review -> versioned rollout -> rollback`.

Keep signature keys, hidden scorers, game reservations, streamer tokens and
account data *outside* the model's editable working directory. Untrusted
agents may propose actions but never manufacture "tests passed", overwrite
evaluations, or auto-publish games. Recovery after power loss should restore
services, known-good configuration and bounded work queues without replaying
old permissions, stale gameplay inputs or old audio.

"More human-like" here refers to consistent long-term character behavior,
social interaction and expressive performance, not a demonstrated subjective
consciousness or independent legal identity.

## Immediate implementation order / acceptance checklist

**Already added in this checkpoint:** contextual probability advice; freshness,
sample and distribution-shift guards; verified, owner-reviewable practice-focus
cards; offline adversarial regression tests.

**Next (not delivered by this checkpoint):**

1. Run actual Windows private-Studio trials across three *versioned* scenario
   families, log real forecast timing and independent outcome evidence.
2. Show that context-aware review improves prediction Brier score on future
   data vs original pooled review, without leaking sealed evaluation tasks.
3. Connect reviewed focus cards to challenge generation in Star Core Forge;
   require explicit scope, independent scoring, per-game fair scheduling,
   runtime budgets and rollback.
4. Compare Pocket TTS and current Star voice on same text with human listening
   review and verified first-audible latency while a game renders.
5. Stage a five-minute mock VTuber session using real game events and synthetic
   public chat, then count missed high-priority questions, false reactions,
   duplicate celebrations, voice interruption errors and dropped frames.
6. Implement visual build-quality assertions and 10 reference design
   challenges, followed by independently checked playable games.
7. Evaluate new code with `unittest`, `pytest` where installed, static
   checking and a simulated Studio loop; no automatic live deployment.

## Claim boundary

The new methods make forecast feedback **more relevant** and identify
evidence-supported topics for offline rehearsal. They do NOT yet improve
model weights, show faster inference, establish higher general intelligence,
operate live Windows gaming, or make Star indistinguishable from a human
streamer. Only future measured experiments may support those claims.
