# STAR: measuring the real-time intelligence gap before scaling models

**Research date:** 2026-11-07 | **Change:** host-only, default-off game-mode comparison

## Why the next bottleneck is not another speech controller

STAR already has modules for audio interruptions, OBS/resource pressure, protected
game-action permits, paired inference speed studies, private game practice and
verified episode reactions. Those are valuable infrastructure, but an AI can
appear excellent in a paused minigame and fail when the world moves. The next
priority should be **measured causal investigation**, not calling slower
deliberation "higher intelligence" or assuming that a faster language model
automatically means better gameplay.

In *Gym-Anything-RT* (Aggarwal & Welleck, October 27, 2026), model results
diverge sharply between real-time and pause-on-think settings. A notable
reported GPT-6 Astra (xHigh) contrast is 9% versus 75% pass rate. This is a
research benchmark result, **not a measurement of STAR** and not a prediction
about a particular local model. It establishes the importance of collecting
both execution modes on the *same* hidden evaluation cases.

Source: https://arxiv.org/abs/2610.37567

## Implemented: small independent diagnostic

`star.game_realtime_gap_audit` adds a strictly read-only, synthetic-testable
comparison on a **predeclared, frozen** set of 20–256 holdout scenario/seed
identities from at least two scenarios. A separately trusted game host supplies
paused and real-time outcomes, verifies equivalent resets and independent
outcomes, and measures action delay and scene deadlines.

The evaluator rejects missing cases, duplicated IDs, unknown scopes, malformed
or reordered mode pairing, host-unverified events, mismatched seeds, unexpected
deadline bounds, and invalid numbers. It reports paired success/progress,
p95 action latency, action deadline misses, discordant outcomes and a
descriptive one-sided exact sign-test p-value. A large gap requires an
absolute >=15-point deficit, paused success >=60%, and p<=0.01. The threshold
is screening only; no automatic optimization, model promotion, or gaming
permissions follow.

**Limitations:** booleans and a protocol SHA are operator declarations, not
trusted timestamps, signed preregistration, proof of equivalent initial states,
real game competence, or causal evidence. Delayed actions may be correlated with
misses, but paused mode also changes how the agent perceives and reasons.
Results do not identify which model weights or policies to train. *No real
game sessions or benchmarks occurred in this change.*

## Experimental ladder (implement in the trusted game host separately)

1. **Prove provenance:** hash a frozen game build, harness, scenario list,
   checkpoints, model/quantization and inference settings; timestamp/sign the
   protocol before collecting outcomes. Hide holdout seeds and rubrics from the
   agent. Version every environment and reset deterministically.
2. **Run matched A/B modes:** for each case, perform a paused and real-time
   attempt with counterbalanced order, independent start-state witness,
   per-frame host monotonic capture and actuator ACK timestamps, and result
   witness from the game engine. Do not hand the model holdout outcomes.
3. **Isolate latency:** use equal observation/input policies and record
   camera-to-model, first usable action, OS acknowledgment, in-engine action
   application and resulting world-state change independently. Test with
   prerecorded visual streams only for repeatability, then validate in real
   game time (which continues advancing).
4. **Improve throughput by bottleneck:** if time-to-first-action dominates,
   experiment with a small fast policy and early stopping; if action execution
   is late, optimize capture+dispatch and frame freshness; if paused outcomes
   are weak, improve grounded vision/goal planning before optimizing speed.
5. **Verify held-out transfer:** sample distinct maps, game versions and
   mechanic families, including unseen visual clutter, latency spikes,
   simultaneous speech, OBS recording, and game/stream GPU contention.
   Measure both success and regression across games before retaining skills.

Roblox OpenGameEval (October 2026) demonstrates executable validation of
agent-produced scene and gameplay edits. Its analysis finds a positive
association between inspecting relevant objects and downstream success; STAR's
Roblox coding/repair loop should **inspect -> edit -> playtest -> verify**,
rather than promoting code because it looks plausible.

Sources:
- https://github.com/Roblox/open-game-eval
- https://arxiv.org/abs/2610.02563
- https://about.roblox.com/en-nz/newsroom/2026/04/roblox-studio-going-agentic

## Performance experiments for 8 GB RTX 3060 Ti / RTX 4060 class

- Compare **actual first-action latency p50/p95/p99**, in-engine action
  application, game p95 frame time, OBS dropped/render/encode frames, and
  VRAM headroom. Decode tokens/second is only a secondary metric.
- A/B prompt caching, stable system-prefix KV reuse, n-gram vs draft-model
  speculative decoding, batching at one and two concurrent requests, and
  context sizes under game+OBS load. Use the exact same model, prompts,
  quantization, hardware profile and timeouts for both configurations.
- llama.cpp's SPEED-Bench measures throughput, latency and draft acceptance
  and supports comparing baseline against speculative settings. It is a
  useful **external measurement tool**, not guaranteed acceleration on STAR.
  https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md
- Separate performance-sensitive fast reaction from slower tactical analysis
  and offline teacher/training. Reserve frame/VRAM headroom for game+OBS,
  downgrade or drop optional commentary before delaying a gameplay action.
  Explore CPU TTS only if measurements show acceptable voice quality and
  first-audio latency, and no CPU contention with game capture.
- Keep the cache keyed by model/version, tokenizer hash, instructions,
  conversation context identity and authorization scope. Never cache raw
  viewer secrets or holdout answer keys into model-visible shared prefixes.

## Human-like VTuber behavior, without pretending to be human

Star should **react to events, not narrate continuously**. An effective live
avatar has scene-aware short utterances, natural pauses, turn-taking and
barge-in handling, subtle facial motion, coherent remembered preferences and
self-initiated hobbies. Critical on-screen events should preempt chat
commentary; chat should not be able to create fictitious game wins or grant
input/broadcast permissions. Natural expressive behavior is achievable without
claims that Star is sentient or a human person.

*Proact-VL* (ICML 2026) specifically studies proactive gaming commentators/
guides that decide when to speak as well as what to say. Run commentary A/B
with human-review ratings for relevance, timing, silence, grounding, humor,
nonrepetition and AV sync, alongside OBS recording evidence. Never equate
"fewer pauses" with better stream quality.

Source: https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/

## Beyond gameplay: generalist capability program

- **Autonomous game creator:** curated project briefs, Roblox Studio inspection,
  Luau static checks, Studio tests, asset/UI/VFX quality evaluation, screenshots
  and independent bug-fix verification. Only promote reproducibly working
  changes. Sandbox untrusted assets and project files.
- **Grounded general knowledge:** local citation-tagged retrieval with update
  times, source freshness, uncertainty and practice/holdout quiz cards. The
  model should *abstain* when it cannot verify a claim.
- **Persistent digital character:** explicit memory provenance, evolving
  hobbies, continuity and expressive scripts with privacy/retention controls.
  Allow ordinary sandbox learning; external social posts, purchases and
  irreversible actions remain owner-governed.
- **Self-improvement infrastructure:** sandbox experiments, versioned local
  snapshots/rollbacks, isolated tests, comparison against immutable holdouts
  and owner-reviewed release changes. GitHub is an optional publishing mirror.
- **Streaming release gate:** replay recorded test scenes while OFFLINE,
  then verify speech interruption, physical audio/neutral avatar, OBS
  recording, game FPS, hallucination rate and actual skill improvement
  before any owner-authorized live broadcast.

**Priority:** first produce genuine measured real-time game outcomes and
capture-to-action timings; then select faster routing/model configurations;
finally expand autonomous learning and streaming expressiveness. This is more
likely to improve actual gameplay and streaming quality than another round
of generic AI prompts or an unbenchmarked neural model swap.
