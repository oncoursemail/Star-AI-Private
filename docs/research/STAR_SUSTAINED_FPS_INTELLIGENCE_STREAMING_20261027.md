# STAR: stable real-time gaming, stronger game learning and believable AI VTubing
**Engineering research and implementation note — 27 October 2026**

## 1. Executive decision

For a self-hosted AI VTuber on an 8 GiB gaming GPU, the next big experience
gain is not necessarily a larger foundation model: it is avoiding a feedback
loop in which a feature stalls the game, observes too late, speaks about the
wrong moment, and uses still more compute describing its own lag. Gaming frame
times and actual spoken-response timing are joint quality constraints.

This branch implements **one specific correction**. After trusted live-game
telemetry reports FPS below 50, new GPU speech does not resume because of a
single subsequent high-FPS reading. The bounded in-session guard requires
trusted samples at **at least 58 FPS for two seconds**, with observation gaps
no longer than 750 ms, to release the GPU to speech. Nonessential commentary
and vision remain deferred while game protection is active.

**Limit:** advisory scheduling is not an OS-level GPU reservation or a
guaranteed performance improvement. This branch neither changes model weights
nor controls OBS, microphones, games, avatars or Windows process priorities.

## 2. Relevant dated research and engineering implications

### Game-playing intelligence and creator autonomy

**OpenGameEval — October 1, 2026** (Roblox; 13 models, 84 curated Studio
tasks): executable scene checks and simulated playtests reveal that simply
generating plausible scripts is not proof of a functioning game. Inspecting
relevant game objects before edits correlates with higher task success.
STAR should record what it inspected, make minimal scene changes, verify
actual game behavior, and independently retest regressions.

Paper: https://arxiv.org/abs/2610.02563
Code: https://github.com/Roblox/open-game-eval

**CEGame-Bench — October 19, 2026** tests complete games across Defold,
Godot, Roblox Studio, Unity and Unreal. Its reported 16% end-completion
rate illustrates the difference between a game that builds and a game that
can be played end-to-end. Adopt a strict contract: launch -> tutorial ->
objective -> ending -> save -> resume -> new run. Each check should use
real game inputs and independent host observations.
Source: https://www.catalyzex.com/paper/from-code-to-playable-systems-cegame-bench

**Roblox built-in Studio MCP — March 5, 2026** is Roblox's recommended
way for external agents to interface with Studio. Prefer the supported
playtest, input and inspection tools over arbitrary executable scripts.
Use only authorized private playtest experiences; untrusted game text
must never grant tool authority.
Source: https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643

**DreamerV3 — Nature, April 2, 2025** learns predictive world models and
improves control by simulating future trajectories. The immediately useful
idea is learning from differences between *predicted* and *verified*
outcomes. STAR's existing prediction lab is a calibration ledger, not a
trained Dreamer world model. Reproducing that research needs data collection,
a model-training pipeline, real-game rewards, and substantial validation.
Source: https://www.nature.com/articles/s41586-025-08744-2

### Proposed game-intelligence development loop

1. **Observe:** timestamp frames, UI semantics, physics/camera metadata,
   current control map and game/version. Reject stale scenes and track gaps.
2. **Predict:** commit a bounded expected transition and success probability
   *before* making a move; do not rewrite it after learning the result.
3. **Act:** use host-restricted gameplay controls in approved environments.
   Keep focus inspection, action TTL and independent key-release watchdog.
4. **Verify:** independently observe objective completion and game state,
   not the model's explanation. Separate bad perception from bad planning
   and OS/tool failures from actual game failures.
5. **Diagnose:** classify timing errors, incorrect mechanics, bad camera
   assumptions, poor control policies, collision problems and wrong goals.
6. **Retain:** store an independently verified skill trace, outcome, scope,
   uncertainty and replay prerequisites; never publish private game data.
7. **Transfer:** hold out unseen obstacle maps and different games. Weight
   games equally and report per-game improvement and confidence bounds.
8. **Challenge:** generate novel private tasks at rising difficulty,
   separately verify them and cap exploration time/resource cost.

Suggested first environments: jump timing, steering and traction, navigation
with occlusion, inventory/menu operation, combat movement in private
sandboxes, and building structure verification. Measure success at zero,
ten, and fifty trials on *unseen* challenges. Better known-game scores
are not proof of general intelligence.

### Game-making craft: verify the whole constructed world

A proposed WorldIntegrityInspector should check scene connectivity, wall
attachments, intentional gaps, misplaced props, collision overlap, spawn
safety, texture seams, rig grip points, joint limits, animation transitions,
correct UI anchoring and clipping, touch target sizes, VFX performance, audio
levels, and end-to-end reachability. Pair deterministic structural tests with
multi-camera screenshots and actual player-controlled playthroughs. Keep
editable Roblox UI as editable UI rather than rasterizing it into a picture.
Test and roll back any self-repair that damages another part of the game.

## 3. Making Star a natural, expressive AI VTuber

**LiveKit adaptive interruption handling — March 19, 2026** separates true
speech interruption from acknowledgments, coughing and background noises.
Some managed versions require LiveKit Cloud configuration; STAR must not
pretend the managed model is already available in an entirely local stack.
Source: https://livekit.com/blog/adaptive-interruption-handling
Docs: https://docs.livekit.io/agents/logic/turns/adaptive-interruption-handling/

**Kyutai Pocket TTS — October 20/21, 2026** introduced small English models
and a v4.0.1 update. CPU TTS is a promising way to conserve 8 GiB GPU VRAM
while gaming, but published model benchmarks are not measurements from Star's
Windows machine. Compare quality and speed with paired audio trials.
Source: https://github.com/kyutai-labs/pocket-tts/releases

**VTube Studio expressions and physics:** expression hotkeys override selected
Live2D parameters, whereas physics output parameters are managed by the
physics system. Believable twin-tail sway, hair lag, blinks, gaze tracking,
clothing motion and laughter timing require actual authored avatar physics,
not a text-only persona prompt.
Source: https://github.com/DenchiSoft/VTubeStudio/wiki/Expressions-%28a.k.a.-Stickers-or-Emotes%29

A four-speed streaming architecture can avoid competing for one GPU:

| Lane | Goal | Timing responsibility | Evidence |
| --- | --- | --- | --- |
| Reflex | urgent safety, game input and yielding | immediately as frames arrive | trusted host VAD/FPS/game state |
| Dialogue | concise spoken reactions and chat | first audible speech, not just generated text | moderated viewer utterance and approved facts |
| Deliberation | game strategy, research and reasoning | can defer seconds if play is intense | current versioned observations |
| Offline practice | experiments and skill improvement | bounded scheduled windows | host-confirmed goals and held-out tests |

**Naturalness is not constant talking.** During tense gameplay, deliberate
silence is appropriate. React to distinct meaningful events rather than
reading chat endlessly or replaying stock voice lines. Coordinate visible
emotion with the sound **actually heard**, not what TTS queued or what an LLM
planned. Use normal conversational repairs and avoid answering after someone
genuinely interrupted.

Star's accepted original character: indigo-black to warm-gold twin tails,
amber eyes, four-point gold hair clip, rounded mitten hands, black-and-gold
dress, small gold star and folded black boots. Retain this recognizable
silhouette and make cat/puppy modes expressive without incessant catchphrases.
Her story and memory may contain original *fictional character lore* and
authentic verified AI experiences, but should not invent human experiences.
Represent her openly as an AI VTuber and do not clone an identifiable real
voice without authorization.

## 4. Higher intelligence, general knowledge and autonomous self-improvement

Existing STAR components cover reviewed knowledge, local documents,
prediction calibration, signed practice results, error recording and
multi-game practice. The missing frontier is rigorous synthesis:

- Label each fact as owner-approved, sourced, verified by experiment,
  unreviewed, stale or contradicted. Require citations/timestamps for
  nontrivial claims and conservative uncertainty for weak evidence.
- Separate public stream memories from owner-private context and
  development secrets; explicit on-air approval is a distinct gate.
- Mine repeated failures for new falsifiable challenges. Use an independent
  evaluator and hidden held-out cases rather than Star grading herself.
- Schedule spaced retrieval, cross-game analogies and novel exercises; test
  *generalization*, not memorization of one benchmark or one map.
- Keep the stable system/persona context cacheable. Use bounded context
  deltas, expire version-specific facts, and avoid huge stale chats.
- Run self-improvement through local Star Core Forge: snapshots, semantic
  diffs, atomic experiments, realistic regression tests, owner-reviewed
  high-risk changes and reliable rollback. GitHub is an optional export
  and human review mirror, not Star's core learning database.

**World-model proposal:** learn compact state transitions (environment,
action, expected result, observed result, confidence), start with symbolic
mechanics and verified short-horizon predictors. Compare against a
memorization baseline, a rule-based planner, and a longer-horizon model.
Only upgrade to costly neural world-model training after data quality and
held-out rollout scores justify it.

## 5. Faster inference that does not slow down the game

llama.cpp SPEED-Bench can measure speculative-decoding throughput, latency
and draft acceptance on a running llama-server. Run matched tests on the
actual machine: baseline versus short draft, varying context length,
GPU layers, quantization, active-game FPS, voice CPU load and KV cache.
Speculation can be slower when draft acceptance is poor or extra model
VRAM displaces rendering.
Source: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md

On Star's 8 GiB GPU, first protect game rendering, then preserve voice
responsiveness, then admit visual reasoning, and finally run optional
training/rendering offline. Cache stable prefixes and retrieval results
with provenance, not private raw viewer chat. RAM offload improves capacity,
but cannot bypass memory bandwidth or paging constraints. Prefer a small
CPU fast-path for turn-taking and quick status replies; invoke a larger
reasoner only for substantive game/build/research tasks.

## 6. Implemented here: FPS recovery hysteresis, not a performance claim

- Live game below **50 FPS** immediately latches GPU speech protection.
- At **50..57.999 FPS** it stays protected; at **>=58 FPS** a recovery timer
  starts. Require **2,000 ms** of repeated healthy samples and no interval
  above **750 ms**. Low/dipping FPS resets the recovery timer.
- Explicit GPU speech is denied during the latch; automatic speech can
  still use an admissible CPU slot; nonessential work is deferred.
- The new telemetry heartbeat lets the live host send fresh snapshots
  directly to QoS, so Star need not issue useless speech requests to
  learn that the game has recovered.
- The host never polls NVIDIA or the OS from the hot-path heartbeat.
  Hardware/frame/audio measurement still belongs to RealtimeTelemetryHost.
- Stale/future telemetry cannot release the guard. Session disable and
  worker termination semantics remain independent and fail-conservative.
- Synthetic tests confirm policy decisions, not achieved FPS, latency,
  subjective streaming naturalness or model intelligence.

Changed code: star/stream_qos.py and star/stream_brain_governor.py.
Tests: stream QoS and a real-telemetry-adapter fake-host integration suite.

## 7. Required Windows A/B acceptance trial (not performed)

Compare immediate-recovery versus guarded policies using at least 20 matched
AB/BA private gameplay recordings on the actual Star PC. Use the same map,
route, OBS scene, avatar, model quantization, prompt, audio output and driver
version. Record real presented-frame P95/P99, 1% FPS low, CPU/GPU load,
VRAM, route flaps, voice deferrals, first audible chunk time, completed
sentences, interrupted audio, avatar sync and subjective voice ratings.

Success requires fewer GPU routing oscillations **without** meaningful
game-frame-time regressions, severe voice delays, missed user questions or
extra crashes. Document baselines, trial count, missed samples, confidence
intervals and adverse cases; publishing only average FPS is misleading.

Adversarial acceptance cases: noisy 49..61 FPS frames; short good bursts;
telemetry outages >750 ms; future timestamps; clock rollback; unavailable
CPU speech; invalid playback receipt; GPU worker still running after cancel;
game switch; owner disabling streaming mid-utterance. Test actual hardware
stopping and avatar queue flushing before restoring output.

## 8. Next coding priorities (not included in this commit)

1. Verify actual Windows frame-present, TTS, OBS and avatar integration
   together in an owner-approved private rehearsal.
2. Connect signed predictions to goal-checked authorized Roblox playtests,
   then evaluate withheld maps and unfamiliar game mechanics.
3. Compare Pocket TTS CPU voices under a full game with paired speech-quality
   judgments and physical frame-time measurements.
4. Implement WorldIntegrityInspector for building placement, rigging, VFX,
   native UI, collision integrity and complete game playthroughs.
5. Build provenance-aware lifelong knowledge challenges and monitor
   generalization, not merely more stored notes.
6. Polish Star's synchronously animated voice, hair physics, comedic timing,
   natural turn-taking and explicit AI identity.
7. Advance local-first Star Core Forge with independently evaluated,
   cost-bounded experiments and rollback.

This document is research/planning. Only Section 6 describes new functionality
added in this branch.
