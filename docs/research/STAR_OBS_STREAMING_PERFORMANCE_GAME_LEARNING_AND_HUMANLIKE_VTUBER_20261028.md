# STAR: broadcast-aware speed, game intelligence and humanlike VTuber engineering
**Research and implementation note — 2026-10-28 — experimental, offline-first**

## Executive decision

Do not declare STAR "faster" because a CPU voice model generates speech
faster or a visual model emits more tokens. A gaming VTuber has a **multi-system
latency budget**: game presentation, OBS composition and encoding, first
*audible* speech, genuinely current game perception, avatar synchronization,
and viewer turn-taking. Optimizing one component can damage another.

This increment implements an **opt-in, offline OBS performance veto** against
the existing matched voice/game benchmark:

- **star/stream_obs_qos_gate.py** parses four OBS 5.x GetStats frame
  counters and pairs before/after counter windows with existing
  RealtimeRun pairs by exact game, version, pair and variant.
- Reject counter resets, malformed values, duplicate pairs, missing data,
  shortened/mismatched windows, unexpected scope, OBS reconnects and silent
  stream inactivity. Missing evidence is **inconclusive**, not success.
- Compare render-thread and output-thread skip percentages both absolutely
  and *relative to the baseline*. Check each candidate window for a hidden
  spike; reject bad broadcast performance even when audible speech improves.
- Keep the module **read-only and host-supplied**. No OBS network connection,
  credentials, broadcast controls, gameplay control, recordings, screenshots,
  viewer text or automatic model promotion are added.
- Reuse the existing compare_realtime evaluation for first-audible latency,
  1%-low game FPS, GPU peak, pairing and performance criteria. OBS data
  cannot replace actual gameplay and audible evidence.

A favorable verdict is **eligible for an owner-supervised pilot**, not
production deployment or evidence of human-quality voice. All tests use
synthetic snapshots, not an actual running OBS process.

## Primary research and implementation sources

1. **OBS protocol:** OBS WebSocket 5.x GetStats documents renderTotalFrames,
   renderSkippedFrames, outputTotalFrames, outputSkippedFrames, activeFps and
   average rendering time. These are render/output thread counters, **not
   equal to network transport losses**. GetStreamStatus separately reports
   stream activity, reconnection and output statistics.
   https://github.com/obsproject/obs-websocket/blob/master/docs/generated/protocol.md
   https://github.com/obsproject/obs-websocket/blob/master/src/requesthandler/RequestHandler_General.cpp

2. **Studio automation:** Roblox StudioTestService supports plugin-security
   ExecuteMultiplayerTestAsync(numPlayers,args), at most 8 simulated clients,
   GetTestArgs() and EndTest(). This verifies executable Studio behavior,
   not visual quality merely from a generated image.
   https://create.roblox.com/docs/reference/engine/classes/StudioTestService

3. **OpenGameEval** (Turkel et al., October 1, 2026): 84 human-curated
   Roblox Studio tasks scored in reproducible scene/play sessions.
   Separate observation from editing and measure exploration; inspecting
   relevant objects before editing correlates with better success.
   https://arxiv.org/abs/2610.02563
   https://github.com/Roblox/open-game-eval

4. **CEGame-Bench** (Dong et al., October 19, 2026): examines full game
   completion across Defold, Godot, Roblox Studio, Unity and Unreal.
   Agents often obtain integration points despite failing real playthroughs.
   Prioritize real-input completion, save/reload and player experience.
   https://arxiv.org/abs/2610.26098

5. **GameWorld** (Ouyang et al., April 2026): 34 games and 170 tasks
   with state-verifiable outcomes across five genres. A 2026-08
   fine-control protocol explores higher-frequency interaction.
   A model's confidence is not a scored win.
   https://arxiv.org/abs/2604.07429
   https://github.com/gameworld-project/gameworld

6. **Natural voice and delivery:** Kyutai Pocket TTS supports CPU-oriented
   streaming speech. Its October 2026 small English variants are potential
   voice options, **not evidence of better expressive quality**. LiveKit's
   v1-mini end-of-turn detector runs locally on CPU. VTube Studio documents
   custom parameter creation and data injection for avatar animation.
   https://github.com/kyutai-labs/pocket-tts
   https://docs.livekit.io/agents/logic/turns/turn-detector/
   https://github.com/DenchiSoft/VTubeStudio/blob/master/README.md

7. **Inference engines and limits:** llama.cpp prompt caching,
   speculation and model-slot metrics merit paired testing on Star's CPU
   and 8-GB GPU budget. Strata's October 2026 CPU offload benchmarks are
   leads, but claimed gains are hardware-/model-/quantization-specific.
   https://github.com/ggml-org/llama.cpp
   https://github.com/Niko1221/Strata/blob/main/bench/results/2026-10-06-llamacpp-0.6.0/README.md

## Existing architecture — not a deployment claim

The existing repo already contains:
- stream_realtime_benchmark.py: paired first audible, GPU and game FPS.
- stream_audio_avatar_session.py, stream_audio_sample_host.py,
  stream_playout_clock.py: audible-first animation foundations.
- stream_focus_inbox.py, stream_game_reactions.py, stream_episode.py:
  focused silence, delayed questions and signed practice commentary.
- gameplay_skill_bank.py, game_learning_ladder.py, game_transfer_eval.py:
  verified practice, difficulty progression and unseen holdout evaluation.
- studio_scene_integrity.py: static compilation of read-only Studio tests.

Star Core Forge is the local-first self-improvement foundation, with GitHub
optional as a publication channel. Existing offline modules are **not**
proof a real Windows Roblox/OBS/Live2D rehearsal has passed.

This increment adds a cross-component performance veto **without introducing
another scheduler, new neural model, or competing database**.

## Exactly how to evaluate a new voice/vision configuration

1. Pre-register a baseline/candidate cohort with the same game build,
   level, scene, OBS settings, bitrate, resolution, GPU power policy,
   audio output device and planned test ordering. Commit this roster in
   an owner-controlled audit location *before* examining performance.
2. On an authorized Windows host, collect the existing RealtimeRun JSONL
   with actual device-audible time, game frame timings, GPU peak, and
   completed speech — no synthetic "first generation chunk" substitutes.
3. For each matched variant, capture OBS GetStats at start and finish,
   projecting only four allowlisted frame counters. Separately attest
   stream activity, reconnection and an opaque OBS process/session token.
   Windows must be at least 2 seconds, at most 10 minutes, and span
   120+ frames in each thread; candidate/baseline exposure within 20%.
4. Supply one JSONL row per variant containing exactly:
   pair_id, variant, game_id, game_version, session_id, start_ms, end_ms,
   before, after, stream_active, reconnect_observed.
   The before and after maps use OBS WebSocket GetStats camelCase keys.
   The host must enforce **same OBS process** and continuous status; the
   comparator cannot authenticate an offline source.
5. Run locally: **python -m star.stream_obs_qos_gate realtime.jsonl obs.jsonl --gpu-budget-mib 6656**
6. Treat regressed as reject/diagnose, inconclusive as insufficient
   evidence, and eligible_for_manual_pilot as only a candidate for
   separate owner-supervised Windows acceptance.

Default conservative constraints: average candidate render/output loss
<=0.5%, no candidate window >1%, increase over baseline <=0.2
percentage points, and no candidate reconnection/inactivity. These
thresholds are owner-tunable engineering defaults, **not universal human
perception standards**. The existing first-audible/FPS/GPU benchmark is
also required. OBS GetStats frame losses are not a substitute for
monitoring network drops from GetStreamStatus.

### Threats to validity

- OBS process restarts reset counters. The host-supplied session token
  is an attestation, not cryptographic authentication. Counter resets
  are rejected, but a hidden reset could still contaminate a result.
- Unit tests of metadata decisions are not evidence of correct Windows
  capture, genuine speech, OBS output, real game play or neural speedups.
- A host that omits high-loss periods or reports inaccurate stream status
  can be misleading. Review selected real OBS recordings and logs.
- Broadcast render/output loss, network delivery, audio underruns,
  lip-sync and speech pleasantness need separate observations.
- Favorable matched measurements are not proof of general intelligence,
  autonomous game mastery or consciousness.

## The next highest-value research and build plan

### A. Real Windows Roblox + OBS + Live2D rehearsal

Connect the existing audio clock to device-observed Windows playback,
not generated TTS time. Link authorized VTube Studio parameters to
mouth/eyes, gestures, tail and ribbon physics. Evaluate p50/p95 first
audible, interruption tail, phoneme/mouth alignment, game FPS, 1%-low
FPS, OBS renderer/encoder loss, reconnections, VRAM/CPU/RAM and
thermals. Add GetStreamStatus **network dropped** metrics separately.
Record real listener and viewer QA. A successful CPU TTS optimization
cannot ruin OBS or the game.

### B. Intelligence per second, not just tokens per second

Split reflex loops (controls, motion, speech interruption, silence)
from deliberation loops (reasoning, visual inspection, research,
planning and code generation). Only perform expensive visual inference
on uncertain/novel scenes, reusing frame hashes and stable prompt
prefixes. Give the streaming workload priority over training.
Pair CPU Pocket TTS with Star's default Kokoro voice to check both
latency and subjective quality; never silently swap her chosen voice.
Test llama.cpp prompt reuse, speculative decoding and alternative
inference engines with comparable model accuracy, quantization,
same input tokens, CPU memory, VRAM and GPU load. Retain measured
wins only. An 8-GB VRAM card cannot host unlimited resident models.

### C. Learn to play unfamiliar games well

Use a reproducible process:
**observe -> formulate rules -> choose safe experiment -> act in a
permitted environment -> verify outcome independently -> practice
harder -> transfer to a held-out situation.**
Record real practice evidence in the signed skill bank; keep validation
sealed. Train on repeated errors, but stop endless failing loops and
force diagnosis. Verify new-level completion, safe response to hazards,
timing, multiple game genres and actual input latency. GameWorld is a
good general benchmark; use Roblox Studio in private, authorized tests.
Avoid claiming "mastery" from scripts or model-created reward signals.

### D. Complete game creation beyond correct code

Use OpenGameEval-style object inspection before modification and run
real StudioTestService checks on Brain 2. Validate structural layout,
missing props, collisions, pathfinding, game objectives, checkpoints,
win/death flows, UI on multiple viewport sizes, multiplayer
replication, save/load and render performance. Follow with blinded
screenshot/video visual QA against the author's reference and real
input playthrough: surface bad textures, z-fighting, broken grips,
incorrect prop placement and nonsensical scales. Use reversible
checkpoints, rollbacks and bounded candidate exploration. CEGame-Bench
shows why compiler success is not game completion.

### E. General knowledge and Star Core Forge

Store primary source, license, project scope, revision time, provenance,
confidence, contradictions and stale-source checks for retrieved facts.
Distinguish observed moments from inferred descriptions and character
lore. Star Core Forge should invent increasingly difficult exercises,
attempt reversible changes, run offline automated tests and promote
only improvements that survive independent held-out evaluation.
Never leak hidden test cases into the learning loop or equate an
AI-generated grading report with ground truth.

### F. More convincingly humanlike Star — without deception

Star can develop a coherent fictional AI persona with enduring interests,
curiosity, humor, playfulness, cat/puppy expressions, facial and hair
motion, responsive spoken turns and memories of her **actual**
authorized projects, gameplay and viewer interactions. Do not invent
a human life history or claim consciousness is solved. Use
verified game events rather than fabricated wins, let her remain
quiet during tense moments, recover naturally from interruptions,
and treat moderated chat as untrusted data. Build small audience
listening studies, laughter/prosody tests and real audiovisual
synchronization scores, rather than declaring a voice "human"
because its TTS runs in real time.

## Why this patch matters

A voice model can respond faster while silently costing OBS rendering
frames. That makes a *worse* gaming streamer despite better inference
numbers. STAR should only adopt future speed changes that preserve
real gameplay, real audible responsiveness and real broadcast health.

**Scope of this PR:** dependency-free offline performance gate,
its opt-in CLI and allowlisted JSONL parser, synthetic unit tests and
this research note. No actual OBS WebSocket, TTS model weights, gameplay,
Studio runtime, broadcast or neural training was used. Nothing is
automatically enabled or deployed.
