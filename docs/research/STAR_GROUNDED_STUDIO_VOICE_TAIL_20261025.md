# STAR: inspection-first Roblox editing + honest realtime voice tail-latency
Engineering research and test record · 2026-10-25 · opt-in, no deployment

## Implemented in this change (not merely proposed)

1. The guarded native Roblox Studio **existing-script mutation path** now reads
   the actual target with Studio's documented `inspect_instance` before
   preparing any persistent native write. A missing read tool, failed read,
   empty reply, a structured path mismatch, or an incompatible class fails
   closed. The existing server/Studio identity guard, compare-and-swap edit
   and durable uncertainty journal remain in force. For a newly created
   script, the nonexistent target cannot truthfully be called "inspected".
2. Every change journal now exposes `inspection` counts for inspected
   existing scripts, newly created script paths, and **unscoped Luau edits**.
   The latter are explicitly unknown rather than counted as verified scene
   inspection. This matters because arbitrary `execute_luau` code can touch
   scene objects it did not declare.
3. The existing *real* voice call's CLI now reports p50/p95 from its timestamped
   voice pipeline. The new `latency_summary` is pure code with no new
   dependencies and excludes errors, incomplete turns and invalid clocks.
   It measures speech-end → first PCM *submitted to the speaker*, not the
   physical time the listener hears it. It does not store utterance text,
   read microphones, capture OBS, or alter live scheduling.

**This is a measurable safety/observability improvement, not a model weight
upgrade, benchmark win, or completed gaming streamer.** Inspection adds a
read-only MCP roundtrip when editing an existing script; measure its overhead
rather than describing it as a speed optimization.

## New primary evidence: what makes Roblox agents actually succeed

**OpenGameEval (Turkel et al., 2026-10-01)** evaluates 13 frontier models over
84 human-curated Roblox Studio tasks, with edits and *play-session checks*.
The leading model completes 51.7% on one attempt; only 39.4% on all five
repeated attempts. Correlational analysis reports that, holding model and
task fixed, inspecting all relevant target objects before editing is
associated with +13.4 percentage points success for scene-only tasks and
+9.8 pp for script-only tasks versus inspecting none. These are **observed
associations, not a causal estimate that our patch will increase Star's
performance by that amount**. A real test needs held-out scenes and full
Studio execution.

Official sources:
- https://arxiv.org/abs/2610.02563
- https://github.com/Roblox/open-game-eval
- https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643
- https://devforum.roblox.com/t/new-studio-testing-apis-and-assistant-improvements/4657854

Next Studio test:
- Use Star's owner-approved sandbox and the built-in Studio MCP. Record
  (task ID, scene revision, objects inspected, mutation receipt, playtest
  outcome, screenshot review) for each independently randomized task.
- On **held-out** seeds compare the same model with an inspection-first
  policy versus a baseline, randomizing run order. Separate logic changes
  from scene changes; count independent places not repeated screenshots.
- Evaluate with engine-executed assertions, Studio error output,
  geometry/collision audits and real rendered viewport screenshots.
  A correct source edit that fails playtesting is still a failed task.
- Never claim arbitrary Luau edits inspected all touched 3D objects.
  The next boundary is a host-enforced per-object observation manifest
  plus a post-change scene diff; string-level declarations alone cannot
  constrain arbitrary Luau execution.
- On user-approved Studio accounts test mobile screen layout, target
  brightness, UI safe areas, LOD, collisions and part anchoring. Disable
  publication and production places by default.

## Humanlike VTuber intelligence without invented human experiences

Star's existing voice call is a real ASR → local LLM → TTS pipeline with
barge-in and per-stage `TurnMetrics`. Average latency alone hides long stalls.
The new p95 report is intentionally the point where audio enters the local
speaker queue, **not** a claim of first audible sound. The next genuinely
stronger experiment measures microphone speech-end, transcript-ready,
first-model-token, first-text-chunk-to-TTS, first PCM produced, audio
submitted, WASAPI playback arrival, and OBS egress timestamp separately.
Do not infer one stage from another.

**CPU-first voice research (new October 2026 options):** Kyutai's Pocket TTS
repository describes 100M-parameter CPU streaming voices and new 18M, 7M
and 2M English configurations (October 2026) with first-chunk latency around
200ms in its own examples. Those are not measured Star/Windows numbers.
Star already ships an opt-in Kokoro voice option; choose the candidate by
A/B audition with consented voices, actual p50/p95 latency, intelligibility,
expressive variation, CPU cost and under-load gameplay frame time.
Do not install large models, change the default voice, or clone a third-party
voice without its owner's permission and a verified applicable license.
https://github.com/kyutai-labs/pocket-tts
https://kyutai.org/pocket-tts-technical-report/

**Full-duplex research:** NVIDIA PersonaPlex (2026-01-15) explores speech
overlap, interruptions and role-controlled voice; model footprint and
runtime integration must be measured on the owner's 8 GB VRAM GPUs.
A small local cascade may outperform heavier full-duplex configurations
for actual streaming if game+encoder memory pressure dominates.
https://research.nvidia.com/labs/adlr/personaplex/

**Character experience:** maintain a stable Star mascot and personality,
with normal/cat/puppy mode differences, context-appropriate amusement,
natural pauses, attention shifts, multi-second anticipation and callbacks
to externally verified gameplay. Prioritize real viewer input, then game
events, then optional background facts. Each audio clip, caption, facial
viseme, gaze event and gesture must share a cancellable turn epoch so a
barge-in cannot animate discarded speech. Use physics-based secondary motion
for ribbons, hair, ears and tail with reduced-motion settings. Represent
fictional backstory as fiction; Star should be clear she is an AI rather
than pretending to have a real human childhood.

## Gaming intelligence: self-play that proves transfer

1. **Observe:** time-stamped HUD / video frame / allowed position telemetry,
   controller state, objective, rules as hypothesis, known uncertainty.
   Game versions and episode IDs prevent leakage across sessions.
2. **Predict:** Star proposes the next bounded action, expected outcome,
   safety stop and information gained. The policy can choose quick reaction
   vs slower deliberate planning based on deadlines.
3. **Execute:** only approved game/Studio adapters may actuate. The agent
   cannot turn benchmark authorization into access to protected games,
   anti-cheat bypass, public matchmaking or other users' accounts.
4. **Verify:** compare expected movement/reward/state with the host's actual
   result. Track failure modes, confidence and real independent successes.
5. **Retain and test:** save small proven skills, measure success on
   different layouts and control schemes not used during learning.
   Repeated steps within one episode never become independent evidence.
6. **Refine games Star builds:** source edit → scene audit → live Studio
   playtest → screenshot/UI check → human-style critique grounded in
   actual rendered evidence. A scripted pass cannot certify aesthetics.

Reference ideas: Google DeepMind SIMA 2, Voyager skill library, DreamerV3
world models. They provide research directions, not ready-made training
or guaranteed generalization on Star's installed hardware.
https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/
https://arxiv.org/abs/2305.16291
https://www.nature.com/articles/s41586-025-08744-2

## Hardware-aware systems and general knowledge

**Fast path:** foreground gamer / OBS encoder reserve VRAM and frame-time
budget first. Reserve audio threads and Star's low-latency TTS/ASR queues.
Hold long context research, fine-tunes, code generation and game asset
renders off the active gaming GPU. Prefer one resident small model with
cache reuse to multiple large models fighting for 8 GB of VRAM.

**Measured inference:** llama.cpp's speculative `ngram-simple` is an
experimental option in prior PR #598, not an automatic optimization.
Compare pinned model hash, pinned server hash, GPU power profile,
prefill latency, token generation, end-to-end voice and OBS/game frame
time using Star's local A/B harness and upstream SPEED-Bench; reject if
quality drops, even if a short synthetic prompt becomes faster.
https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md
https://github.com/ggml-org/llama.cpp/tree/master/tools/server/bench/speed-bench

**Knowledge:** maintain separate sourced facts, model inferences and
verified experimental outcomes. License/source/date/version provenance,
conflict checks and stale-fact TTL are necessary; uncontrolled retrieval
can slow Star down and confidently import bad data. Keep retrieval
default-off, do not train on eval answers, and promote only after
held-out knowledge/Luau/gameplay/visual/voice tests beat baseline without
critical regressions.

## Acceptance and hard boundaries

- New offline tests must cover both successful inspection and rejection of
  missing, empty, wrong-path, wrong-class and absent `inspect_instance`
  results before any native script mutation. Existing sandbox and undo tests
  must still pass.
- Voice summary must report unknown instead of zero for missing data,
  reject NaN/inf/out-of-order stamps, keep private utterances out of
  summaries and report correctly calculated nearest-rank p50/p95.
- Studio editing and voice timing statistics alone are **not** a verified
  lift in game creation, speech naturalness or model intelligence. Next
  milestone is owner-approved actual Studio and local voice/OBS rehearsal
  against baseline, measuring p95 queueing plus speaker output and held-out
  task success.
- Repository and branch: draft PR on `star/next`, no merge to `main`,
  no deployment, no cloud uploads, no autonomous streaming changes.
- Important security observation: GitHub's repository metadata currently
  labels `Star-AI-Private` as **public**; do not add secrets, private voice
  samples, stream chats, identity data or raw benchmark traces to this repo.
