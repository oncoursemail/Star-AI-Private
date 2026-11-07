# STAR — Real-time thinking cost, gaming intelligence, VTuber realism, and generalist roadmap
**Research and reproducible private implementation — 2026-11-05 (America/Chicago)**

## What this change actually ships

This branch extends the authenticated *synthetic* maze loop with a bounded world-time model.
A model may take `decision_delay_ticks` (0..24) to return a symbolic suggestion. The
independent engine continues to advance patrols during that delay, detects collisions,
and checks the hazard position *at action commit*, not merely at capture.
`max_frames` now consistently caps **world ticks**, not "free" model deliberations.

An optional `action_deadline_ticks` (0..24 or disabled with `None`) drops advice
that arrives too late. Dropped advice never moves the player or receives movement
credit. Scores expose world ticks, delayed-threat hits, and suppressed moves.
Signed observations remain unmodified; there is no future hazard schedule in
the advisor's input. Every experiment remains owner-opt-in, offline, bounded,
and advisory-only: **no real game input, live OBS, networking, model inference,
or training is enabled**.

### Reproducible measured *synthetic* examples

- Open corridor, same two legal moves and three observations: zero simulated
  thinking ticks gives success after **3 world ticks**; 3 thinking ticks per
  observation gives success after **12 world ticks**. This isolates response
  latency from decision quality in a static map.
- In a private six-cell patrol test with radius-1 observations, immediate
  advice succeeds. Delaying each recommendation one synthetic tick causes the
  moving hazard to hit the stationary player *during deliberation*, after
  **6 world ticks** and **2 actual moves**. Failure is independently scored.
- A two-tick delayed recommendation can become invalid because the hazard
  now occupies its destination; the engine rejects the move, rather than
  crediting a previously safe-looking action.
- With one tick of latency and a zero-tick action deadline, the scorer records
  suppressed late advice and does not claim that the character moved.
- These tests deliberately do not claim real FPS, token throughput, TTS
  latency, or a neural intelligence improvement.

Run:
```bash
python -m pytest -q tests/test_realtime_latency_maze_lab.py \
  tests/test_signed_maze_lab.py tests/test_signed_moving_hazard_lab.py \
  tests/test_predictive_hazard_guard.py
```

## Research findings: what should change Star's priorities?

### 1. Real-time intelligence is NOT offline task success

Aggarwal and Welleck's *Gym-Anything-RT* (published **2026-10-27**)
evaluates 100 visual minigames with and without a moving clock. In one
comparison, a tested frontier model's pass rate falls from **75% paused**
to **9% real-time**. This should be a red flag for STAR's existing "think
then act" design. We must **measure elapsed world time**, not count only
completed puzzle steps or tokens generated.

Source: https://arxiv.org/abs/2610.37567

**Recommended architecture — three different clocks:**

1. **Reflex lane** (<1 game frame target): bounded non-LLM controller for
   verified, already-authorized actions like timing, safe evasion, and
   deterministic movement. No network dependency in the live action path.
2. **Tactical lane** (~100–1000 ms targets, hardware-dependent): goal
   selection, tool choice, navigation replans, inventory and enemy modeling.
   Output a *proposal* tagged with capture sequence, deadline and uncertainty.
3. **Deliberative lane** (background): researched strategies, novel mechanics,
   memory curation, multimodal analysis, self-generated practice, and robust
   post-game learning. The live reflex loop never blocks on this worker.

The executor must discard proposals from stale capture epochs, revoked
sessions, or after their action deadlines; a verified host signs source
frames, but **signing does not prove that the reader observed reality**.

### 2. Faster Star means lower time-to-correct-action

Benchmark end-to-end:
`frame capture -> perception -> world state -> policy -> action-gate -> input
-> new verified frame`. Report p50/p95/p99 per stage, missed deadlines,
real game FPS and 1% lows, GPU peak and VRAM headroom, CPU load, audio
underruns, OBS dropped frames, actions replayed, and *goal success on held-out
tasks*. Never use model tokens/second as the only success metric.

On machines with **8 GB VRAM**, keep the live GPU budget hard-capped.
Evaluate a small quantized model and task-specific CPU services alongside
game + OBS rather than filling VRAM with a large conversation model.
`llama-server` supports KV-prefix reuse (`cache_prompt`, generally
enabled by default) and speculative decoding; benchmark acceptance rates
and CPU/GPU overhead, using pinned versions and equal task cohorts.
A draft model can reduce speed if memory pressure dominates.

Sources:
- https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md
- https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md

### 3. Humanlike VTuber performance is grounded timing + coherent life

For **natural but clearly disclosed AI streaming**, prioritize:

- A *conversation floor manager* that can listen while speaking, backchannel
  without interrupting, yield to viewers, and stay appropriately silent during
  tense gameplay. Use consent-aware voice chat, filtering, moderation and
  explicit interruption reasons.
- A stable and expressive personality/profile, evolving verified preferences,
  episodic memories of actual games, confidence calibration, humor grounded in
  observed events, and explicit distinctions between memory and invention.
- Speech envelopes with emotion curves, laughter cues, emphasis, breath
  variation and intentional pauses; lip/eye/gaze/head/hand movement driven
  by **actual audio and game events**, not arbitrary idle motion.
- A two-stage speech policy: fast, grounded short reactions for urgent moments;
  slower thoughtful responses for substantive chat. Coordinate with combat
  state so Star doesn't speak over a dangerous mechanic.
- A safety envelope for public platforms: identifiable as AI, clear user
  moderation controls, no fabricated human biography or deceptive
  relationships, protect private chat/credentials, rate limits and mute/kill
  switch. An AI may express a convincing persona without claiming to be human.

Relevant work:
- NVIDIA DyaPlex (June 2026): simultaneous streaming speech and dyadic
  motion, a *research direction*, not an out-of-box deployment.
  https://research.nvidia.com/labs/amri/publication/nagano2026dyaplex/
- NVIDIA PersonaPlex: full-duplex speech persona conditioning; 7B-size
  workload may compete heavily with a consumer 8 GB gaming GPU.
  https://github.com/NVIDIA/personaplex
- Kyutai Pocket TTS: CPU-first streaming voice; October 2026 English
  18.2M/6.9M/1.9M configurations are worth comparing against the
  current voice service **on the actual Windows host**.
  https://github.com/kyutai-labs/pocket-tts

**Next acceptance test:** private OBS capture with game, avatar, microphone,
viewer-message simulator, speech synthesis, interrupted questions, time
pressure, mute controls, and independent audio/video sync scoring. Record
real p95 first-audio latency and interruption recovery, not subjective polish
alone. Use simulated chat and an unlisted rehearsal before public deployment.

### 4. General intelligence comes from verified practice, not unchecked self-training

Build a curriculum manager that generates tasks at several difficulty levels,
uses a bounded tool budget, and can expand once out-of-sample task success
improves. Each skill record must include environment version, evidence,
actions, failed attempts, allowed tools, source age, and reproducibility.
For unfamiliar games, prefer understanding controls and rules, safe
exploration, consequence logging, a world model with uncertainty and
independent score recording. Do not optimize against a leaked test map.

For Roblox, use the built-in Studio MCP server for read/explore/build/playtest.
Roblox's *OpenGameEval* (2026-10-01) scores reproducible engine sessions
with executable scene and play checks; reported gains from inspecting
relevant objects before edits support STAR's inspect->plan->build->test->repair
workflow. Restrict Open Cloud capabilities per game and separate read-only
investigation from asset publishing, purchases, bans and live data writes.

Sources:
- https://arxiv.org/abs/2610.02563
- https://create.roblox.com/docs/studio/mcp
- https://create.roblox.com/docs/studio/mcp-open-cloud
- https://devforum.roblox.com/t/studio-mcp-server-updates-open-cloud-access-in-your-mcp-client-and-asset-import-workflows/4975849 (2026-11-04)

### 5. Hard gates before the next autonomous launch

1. Keep this synthetic clock benchmark in CI (deadline=0, controlled delay,
   patrol collisions, no-future-knowledge tests).
2. Connect a **trusted, sandboxed, owner-approved game-state host** that emits
   authenticated capture IDs, monotonic timestamps, observation uncertainty,
   and an independently measured action-commit time. No live input enabled
   until the end-to-end evidence boundary is verified.
3. Compare one fast bounded controller vs a delayed LLM on *held-out* mazes,
   then on safe offline games. Report individual failures and confidence
   intervals instead of only aggregated success percentages.
4. Rehearse with OBS, avatar and voice simultaneously; enforce GPU/CPU
   admission control, capture drop thresholds, and immediate safe stop.
5. Add self-improvement as reviewed experiments with verifiable rollbacks,
   not autonomous promotion based on model-generated claims.
6. For public game streaming, respect game/server rules; exclude anti-cheat
   evasion, private data, unsolicited user impersonation or competitive
   online automation without game-specific authorization.

**Implementation status:** Synthetic clock and engine-side checks are in
code/tests in this branch. Real-game control, fast reactive policies, the
natural-voice stack, and GPU performance optimization remain *next milestones*
rather than demonstrated production capabilities.
