# STAR Intelligence — Integrated Gameplay Learning, Speed, Game Creation and VTuber Roadmap
Research date: October 29, 2026. Implementation: star/studio_practice_cycle.py.
Status: experimental, opt-in, offline tests until an authorized real Windows Studio exercise.

## Major architectural finding

STAR already has a surprisingly wide collection of individual components:
Studio screenshots, owner-scoped input, signed game outcomes, skill memory,
prediction calibration, game-quality reviews, audio/video quality checks,
and resource governors. **Integrating these into actual closed-loop learning
is now higher value than implementing more disconnected quality gates.**

The new StudioPracticeCycle stitches the first full private-Studio practice
transaction together: fresh hardware telemetry -> real host-captured visual
frame -> preregistered success estimate -> host-reviewed bounded input ->
observed next frame -> independent signed objective verdict -> persistent
practice memory -> probability calibration and optional grounded episode
memory. Its default is OFF; one attempt consumes its authorization. Neither
a key press nor a model's description is proof of winning a game.

### Relevant verified research

- **Roblox OpenGameEval, October 1, 2026:** 84 curated Studio tasks,
  stateful executable evaluation, and evidence that inspecting target scene
  objects is associated with higher success. Observation is correlational,
  not proof of causality. Source: https://arxiv.org/abs/2610.02563
  Code and tasks: https://github.com/Roblox/open-game-eval
- **Roblox Studio MCP, March 5, 2026:** built-in server supports playtests
  and simulated player input, making repeatable private development possible.
  https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643
- **GameWorld, April 8, 2026:** 34 games and 170 verifiable browser tasks;
  time-critical control, long-horizon planning and memory remain difficult.
  https://arxiv.org/abs/2604.07429
- **GameDevBench, ICML 2026:** 132 development tasks; best reported overall
  result 54.5%, 2D graphics tasks 31.6%. Image and video feedback improved
  the evaluated agents but does not automatically improve STAR.
  https://sethkarten.ai/papers/gamedevbench.html
- **llama.cpp server documentation (2026):** parallel decoding, continuous
  batching, speculative decoding and caching; batch sharing makes heavy
  postprocessing in the decode thread expensive.
  https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md
  https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README-dev.md
- **LiveKit turn handling (2026):** differentiates voice detection, end
  of conversational turns, and genuine interruptions; a local CPU v1-mini
  detector exists.
  https://docs.livekit.io/agents/logic/turns/turn-detector/
  https://livekit.com/blog/turn-detection-and-interruption-handling
- **VTube Studio's plugin API:** local authenticated WebSocket control of
  custom expression/rig parameters.
  https://github.com/DenchiSoft/VTubeStudio
- **OBS WebSocket:** packaged with OBS Studio 28+, password recommended.
  https://github.com/obsproject/obs-websocket

## A. Actual gameplay mastery — technical plan

1. Run the new cycle in a fresh private Roblox Studio scene, where the owner
   configures the observer, action allowlist, independent game-state scorer,
   source of hardware metrics, and local keys. Do not touch public servers.
2. Build a library of **mechanic probes**. For a jump: vary start distance,
   jump timing and velocity while keeping terrain fixed. For aiming: vary one
   target motion parameter. Log signed *actual* checkpoint/goal changes.
3. Add a fast deterministic action lane between expensive vision steps.
   Uncertain camera, focus, menu, death or stale frames cancel any horizon.
   Do not assume VLM token speed is enough for 60 Hz control.
4. Use existing GameLearningLadder and GamePredictionLab for increasingly
   difficult practice, conservative lower-bound mastery and diagnosis of
   failures. Reserve unfamiliar levels and games as withheld holdouts.
5. Verify **transfer**, not memorization: measure success on unseen maps,
   objective variants and mechanics families with the same action budget.
6. Avoid overtraining: repeated identical tasks may improve a single scene
   without improving overall game competence. Record objective state,
   attempts, action count, errors, elapsed time and model/resource profile.

Proposed near-term acceptance target (not achieved): 30+ signed actions across
three mechanics, demonstrably calibrated prospective forecasts, improvement
on a never-before-seen private level, and zero unconfirmed held keys.

## B. Better Roblox and general game creation

Combine scene hierarchy inspection, spatial/structural integrity, collision
and pathfinding, screenshot design review, animation/VFX playback and real
end-to-end playthroughs before considering a game ready for review.

Geometry-first workflow: structural shell -> collision, doors, stairs and
navigation -> UV/material quality -> object placement -> animation -> UI ->
lighting/VFX/audio -> varied quality settings -> multiplayer/latency tests.
Preserve original editable Blender/Roblox source assets and attribution.

A visual judge needs multiple camera angles and short video sequences:
one screenshot cannot reveal collision leaks, rig popping, hair/cloth
interpenetration or UI state transitions. Human blind reviews and actual
runtime checks should remain separate from the candidate that built the game.

## C. Faster useful intelligence, not just higher tokens/second

| Lane | Protect/measure | Next experiment |
| --- | --- | --- |
| Private gameplay | p95 perception-to-action, FPS, safety errors | action micro-policy and asynchronous VLM |
| Live speech | end-of-turn to first audible sample | local CPU detector, streaming TTS, cancellation |
| General Q&A | grounded answer accuracy, latency | context caching and difficulty-based model routing |
| Game creation | independently passing tasks/min | best-of-N only when validation pays for compute |
| Game observation | useful recognized events/GPU-second | ROI motion sampling and duplicate-frame caching |
| Research/self-improvement | holdout gains at equal compute | paired signed A/B evaluations in Core Forge |

Prioritize: key-release safety, game FPS, audio+animation and OBS, foreground
conversation, vision, deeper reasoning, then background experiments.

Benchmark prompt-prefix caching, speculative decoding, model routing, CPU/RAM
offload, queue admission and task parallelism separately. Some speculative
decoders lose time to rejected draft tokens; some large caches evict useful
working context; more GPU utilization may harm game FPS.

On Star's 8 GB-class streaming GPU, keep an explicit headroom reservation.
Offload heavy reasoning to Brain 1/2 only if real network jitter and
first-audible latency beat the local baseline. No claim of a measured speedup
until real host benchmarks establish one.

## D. A more natural AI VTuber

Star's personality should emerge from **real experiences**, not invented
human memories. Design an attention state machine: difficult gameplay means
brief, natural silence; a witnessed win means a grounded celebration; safe
downtime allows conversation, spontaneous curiosity and playful mannerisms.

Drive speech turn-taking, voice output, mouth, blinking, eye focus, body pose
and damped twin-tail physics from one timeline. Interruption must stop stale
lip movement and queue state; VAD noise should not always cut off her voice.
Reactions, chat answers and stories must stay faithful to her actual past
actions and saved consented experiences.

Use VTube Studio's authenticated local plugin API with bounded parameters;
do not expose it directly to raw chat input. Use OBS read-only measurements
and offline captures before touching streaming controls. Restrict storage of
private microphone audio, viewer names and personal transcripts.

A/B blind-review metrics: natural pause rating, interruptions per hour,
grounded vs hallucinated game reactions, visible mouth-to-audio offset,
first-audible latency, avatar FPS and game frame-pacing.

## E. Broad general knowledge and autonomous self-development

Reuse the existing STAR knowledge bank, verified retrieval, memory and
autonomous research tooling rather than forking another database. Keep
source provenance, timestamps, expiration policy, contradiction checks,
uncertainty and strict separation between documented facts, user-approved
memories and fictional character lore.

Give STAR self-generated multidisciplinary problems (science, history,
writing, coding, art, music, game rules) with withheld evidence-based tests.
Track what she can actually solve, not what she says she knows. Core Forge
should run reproducible local commits, experiment receipts, rollbacks and
branch comparisons; Github is optional publication, not her core brain.

## New component limitations and next integration

The implementation runs **one** owner-approved private Studio action.
It accepts only the trusted host's fresh observations, action port and
separately signed practice verdict. It does not run arbitrary games, change
model weights, start OBS, or let a model sign its own outcome. The local
reviewer/scorer is the most important missing production connection.

Next Windows test: open a disposable private obby, stop broadcasting,
capture real frames through the Studio MCP screenshot call, issue an
allowlisted jump, independently verify checkpoint changes, and record
signed successes *and failures*. Inspect both the skill bank and the
forecast calibration report. A model summary alone cannot count as truth.

All proposed benchmarks and future streaming refinements are unverified
until measured on real hardware. No credentials, private video, viewer
identities or personal chat records should be published in GitHub.
