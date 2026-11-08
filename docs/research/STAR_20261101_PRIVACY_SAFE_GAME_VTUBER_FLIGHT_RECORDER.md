# STAR: private-by-construction game + VTuber flight recorder and next intelligence trials

**Date:** 2026-11-01. **Change status:** implemented and synthetically tested on authorized Linux development host; draft/unmerged. **Not** a neural-network upgrade, production streamer, active game-player, voice-model integration, GPU-speed result, or proof of subjective consciousness. Repository is **public**. No screenshots, chat, audio, secrets, user identities, logs containing raw prompts, or model weights belong in a commit.

## 1. Problem: isolated passing checks do not prove an integrated streamer

STAR now has separate advisory controllers for (a) deadline-aware game inference, (b) host-confirmed input permission and release, (c) actual audio-device playout versus queued/generated PCM, (d) synchronized VTube Studio animation, (e) Twitch ingestion, and (f) frame-loss/stream admission. They are useful components, but they have different timing edges. An excellent local model latency score can coincide with an interrupted audio output, mouth movement after playback stopped, OBS encoder stalls, or a game action issued for a superseded scene.

This patch supplies the missing **bounded, privacy-minimal host-measurement ledger**:

- `star/stream_rehearsal_recorder.py`: `StreamRehearsalRecorder` accepts only eleven strictly typed, enumerated host events. It never accepts arbitrary event bodies, speech text, images, chat, audio, game titles or viewer data. Correlators are tiny opaque per-session tokens, never exported in reports.
- The recorder enforces one monotonic host clock, limits sample count and maximum episode duration, declines unauthenticated/invalid events without advancing its clock, and prevents scene replay, concurrent workers, unmatched worker exits, stale-scene action claims, held-button action overlap, duplicate releases, impossible audio/animation order, and impossible OBS counter deltas.
- `end()` marks a crashed rehearsal as incomplete; it does *not* claim that an unverified worker was terminated or that a held input was released. `report()` exports only numeric aggregate summaries. Session identifiers, tokens, and individual event timelines remain memory-only.
- A complete single-utterance episode with 120–5,000 host-measured frame durations can be converted with `to_realtime_run()` into STAR's **existing** `RealtimeRun` paired QoS analyzer. This is an integration bridge: timing measurements can now be evaluated against a matched baseline, rather than remaining isolated assertions.

Trust boundary: the Python `host_verified=True` switch is a *declaration from the authorized host*, not cryptographic proof; never let an LLM, Twitch viewer, website, or VTube Studio input call this API directly. Windows adapters must separately authenticate input focus, capture timestamps, process-exit handles, consumed PCM, actual renderer frames, and OBS stats. This observer cannot start OBS, render a mouth frame, press a key, change models, or assert a game win.

### Supported event contract

| Event | Host evidence and relation |
| --- | --- |
| `scene_observed` | Fresh strictly increasing game-scene sequence and host capture clock |
| `worker_started`, `worker_exited` | Unique worker correlator tied to scene; exact exit match required; no overlapping workers |
| `action_claimed`, `action_released` | Host-controlled input permit; current scene only; no concurrent held permit; release matches claim |
| `speech_queued`, `pcm_first_audible`, `pcm_stopped` | Speech epoch; first-audible requires actual device output, not TTS completion |
| `avatar_frame_rendered` | Recorded only after PCM becomes audible and before the device stops |
| `frame_presented` | Actual game/renderer frame time, in milliseconds |
| `obs_stats_sampled` | OBS skipped/total cumulative frame counters; delta measured between comparable samples |

A closed session exports scene-to-action, speech-to-audible, audio-to-first-avatar and game-frame p50/p95/p99 where applicable, severe maximum frame time and OBS skipped-frame fraction. The bridge deliberately refuses to export a benchmark-ready run without a clean shutdown and enough data. Each number is a **measurement**, not proof of causation or enhanced intelligence.

### Synthetic verification

Run:

```bash
/home/star/.cache/star-verification-venv/bin/python -m pytest -q \
  tests/test_stream_rehearsal_recorder.py \
  tests/test_stream_realtime_benchmark.py \
  tests/test_game_realtime_loop.py
/home/star/.cache/star-verification-venv/bin/python -m ruff check \
  star/stream_rehearsal_recorder.py tests/test_stream_rehearsal_recorder.py
python3 -m compileall -q star/stream_rehearsal_recorder.py
```

New tests check actual metric math and conversion to an existing analyzer; invalid payloads, private text, untrusted telemetry, reversed clocks, replay, wrong-worker exit, concurrent workers, stale input, input-release mismatches, inaudible avatar animation, audio replay, impossible OBS counters, crashed sessions, retention bounds, and concurrent duplicate scene events. The tests run **synthetic clocks**, not real hardware.

## 2. Exact Windows integration plan (owner-opt-in, local by default)

Instrumentation belongs in **the trusted host adapters, not the model's generated prose**. Create one recorder per rehearsal episode. The OBS, audio and game adapters must call the recorder *after* independent evidence has been validated; errors must never authorize input or silently discard a running worker.

1. Start a nonbroadcast, owner-approved rehearsal on the Windows device. Ensure the game window and streaming test scene are fixed, no private chat is captured, and telemetry uses the *same monotonic host clock*.
2. Have the game capture adapter emit a new `scene_observed` only on actual accepted observations. Record `worker_started` after a real process launch and `worker_exited` only after OS-confirmed exit. New scenes do not terminate previous workers by declaration.
3. Emit `action_claimed` only after the existing gate has independently authorized a press on the same scene and focused game window; emit `action_released` only after key-up confirmation. Rejected controls must be counted elsewhere, not misreported as claimed input.
4. Speech adapter emits `speech_queued` for an identified utterance, but emits `pcm_first_audible` only upon verified consumption at the audio-device playout boundary. The avatar renderer emits `avatar_frame_rendered` on successful frame presentation; speech stop must be confirmed at the device boundary.
5. Game render loop records `frame_presented` per on-screen frame (no images), capped at 5,000 samples per benchmark run. OBS adapter records cumulative skipped/total frames in one stable OBS output epoch. On an OBS reset or device reconnect, **end the episode and start a new epoch**; do not join incompatible counters or clocks.
6. Collect independent host GPU high-water mark for the paired benchmark. End cleanly, convert to the existing `RealtimeRun` and compare baseline/candidate matched by game version, map/scene, OBS settings, model, thermal conditions, frame cap, input script and workload seed.
7. Do not upload event streams, IDs, audio or face/screen data. Publish only manually reviewed aggregate reports and conditions. Rehearsal does not automatically enable any new model, worker process, game input, stream, purchase, or broadcast.

Missing/incomplete transitions are a **failed rehearsal**. Do not try to improve scores by deleting failed samples.

## 3. Intelligence: three clocks, not one permanently large model

**Fast path (during play):** deterministic safety/focus checks, short cache-resident context (current objective, scene age, risk, controls), strict inference deadlines and a safe no-action fallback. A fast student proposes limited symbolic actions; the authorized host controls the actual input. Precompute animation/response templates for low-stakes reactions that genuinely match game state.

**Tactical path (short pauses):** prediction of the next hazard, local route planning, cooldown timing, teammate awareness, confidence calibration and decision-audit tagging. Never let this path block a live game frame or audible-device stop.

**Slow path (between attempts):** a stronger teacher independently reviews consented, content-minimal attempt evidence, proposes explicit strategy revisions, reruns the challenge and checks on held-out seeds/maps. STAR Core Forge retains only successful, reproducible improvements with diff, test, provenance and rollback; no GitHub dependence for internal learning. Tests must distinguish *real observed skill change* from a longer prompt that merely asserts mastery.

**Relevant result, not a STAR performance claim:** RealtimeBench/TORSI, published **October 14, 2026**, evaluated 180 tasks in continuously running games. Its fast-player/slow-teacher approach improved the studied fast student's mean progress from 13.51 to 24.19 on a 0–100 scale after two rounds. Treat this as a hypothesis to test on STAR, not proof her current architecture has improved ([primary paper](https://arxiv.org/abs/2610.20665)).

**Quantifiable game-learning ladder:** navigation -> jump timing -> moving hazards -> aim/tracking in permitted sandbox -> team coordination -> multi-step resource strategy -> transfer to unseen maps. For each level measure zero-shot success, retries, median completion time, recoveries, invalid/stale actions, fraction of episodes requiring human rescue, skill retention after a delay, and generalization to entirely different game mechanics. Use fixed evaluator seeds, sealed held-out seeds and audit-friendly signed outcomes. Independently validate the game outcome; a model self-report is never evidence.

## 4. Higher speed on 8 GB VRAM: optimize the full experience

For STAR's GPU-constrained deployments, first establish *identical paired hardware configurations* and measure:
- P50/P95/P99 game-observation-to-authorized-action time, inference time, TTS queued-to-audible time, PCM-to-avatar time, and actual frame times.
- OBS dropped/skipped-frame fraction, encoder backlog, GPU memory peak, CPU saturation, thermal throttling and audio underrun/recovery.
- Per-workload model quality: game instructions, code generation, retrieval, reasoning and conversational timing. Faster but incorrect output is not an improvement.

Use llama.cpp SPEED-Bench to compare a baseline with n-gram speculation, MTP and/or draft models, **one change at a time**. It reports per-category latency, throughput and speculative acceptance; the server must be started separately. Official docs: [SPEED-Bench](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md), [speculative decoding](https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md). Verify that speed improves on STAR's *actual model and GPU*: draft workloads can consume GPU memory or decrease throughput, especially for high-entropy speech/storytelling.

**Selective Rust:** move only profiles-proven hot, well-bounded host operations (frame metadata parsing, queue scheduling, time-epoch bridging, event validation, byte buffering) behind stable FFI/IPC boundaries. Leave high-level training experiments and rapidly changing inference integrations in Python until a benchmark proves the migration matters. Preserve current Python tests as a behavioral oracle. Prioritize avoiding redundant observations, model cold starts and GPU contention before rewriting the system.

**CPU/GPU separation:** give gameplay/OBS and audio device time priority over background finetuning, rendering or teacher workers. Evaluate Kyutai's October 2026 18.2M/6.9M/1.9M Pocket TTS models as low-footprint CPU speech alternatives, but compare intelligibility, expressiveness and audible latency against STAR's current voice. The project's published CPU speed examples are model/hardware dependent, not STAR benchmarks ([Kyutai Pocket TTS](https://github.com/kyutai-labs/pocket-tts); [Oct 21, 2026 release notes](https://github.com/kyutai-labs/pocket-tts/releases)).

## 5. Make Star a believable, truthful gaming VTuber

Natural delivery requires *coordination*, not continuous speech. Build a turn director with five states: listening, thinking, speaking, reacting and focused gameplay. An interruption should lower voice priority and stop device playback before the mouth state goes neutral. Expressive laughter, gasps and surprise must be triggered by actual gameplay/social context, not a random timer. Star can choose to be quiet during a high-stakes boss fight and then comment when safe.

LiveKit documents a local CPU `v1-mini` turn detector for deciding whether a person has finished speaking. Pin the model and verify it runs locally rather than silently selecting a cloud-hosted full model; voice activity detection and end-of-turn detection are distinct functions ([LiveKit official turn detection](https://docs.livekit.io/agents/logic/turns/turn-detector/)). Use the VTube Studio public WebSocket API for authenticated, coordinated eye, mouth, head and body parameters, bounded reaction envelopes and safe re-neutralization. Model physics for the twin tails and ribbon, blinks, little gaze shifts, ear/cat or puppy persona modes and playful Astro/Amber cohost interactions—**only after the PCM/renderer timing boundary is correct** ([official VTube Studio API](https://github.com/DenchiSoft/VTubeStudio/blob/master/README.md)).

Use persistent, evidence-grounded lore: she may remember games she played, lessons she learned, friends she talked to with consent, and jokes viewers enjoyed. A warm, adorable 21-year-old *character persona* is possible without asserting that software is a biological person, inventing real childhood memories, presenting untested self-awareness as consciousness, or impersonating actual people. Chat moderation, privacy and no-obligation social boundaries are mandatory.

Useful next experiments: listener-rated turn naturalness (blind audio pairs); objective words-overlap/interruptions; speech onset latency; false lip motion after actual audio stop; callback accuracy to previous verified streams; proportion of unsolicited commentary grounded in real observations; consistency of personality across 10 sessions; maximum simultaneous CPU/GPU pressure when playing.

## 6. General knowledge and game creation

General knowledge should be a **versioned, sourced skill and reference library**, not an undifferentiated web scrape: source license, date, retrieval hash, freshness TTL and conflict handling. Use a small router to choose cached approved local skills first, authorized web research second, and a clearly marked uncertainty/abstention path last. Train on repeated benchmark tasks with fresh holdouts to avoid retrieval contamination.

For Roblox game generation, require a scene tree inspection, explicit design brief, model placement plan, connection/collision checks, art and UI visual critique, then executable tests. Roblox's [StudioTestService reference](https://create.roblox.com/docs/reference/engine/classes/StudioTestService/AddPlayers) and [Studio testing documentation](https://create.roblox.com/docs/studio/testing-modes) describe scripted multi-client scenarios and virtual input in Studio. Qualification should cover 1–8 simulated clients, joins/leaves, UI hitboxes, network ownership, props that collide incorrectly, missing art, character grip/rig mismatch, game economy and FPS, not just Luau syntax.

STAR should build a small game, play it with a permitted test agent, identify a measurable problem, repair it, replay the same seeds and then replay unfamiliar seeds. STAR Core Forge should treat every proposed self-improvement as a hypothesis with a bounded rollback point. This matters more than simply adding more packages to her environment.

## 7. Next acceptance gates and limitations

1. **Offline correctness:** complete focused unit suite + Python compilation + Ruff + type check and exact source blob identity against published commit.
2. **Trusted host wiring:** game, PCM device, VTube Studio and OBS adapters emit the defined events under an owner-controlled rehearsal flag. Reset epochs on reconnect. No public broadcast, player input or cloud execution by default.
3. **Matched Windows performance:** 20+ independent, pre-registered baseline/candidate pairs with enough game frames and speech events; check tails, worst-case hitches, GPU peak, stale actions and speech continuity using STAR's existing paired evaluator.
4. **Human-facing naturalness:** blind feedback on actual recorded voice/avatar rehearsals with consent, not fake character self-ratings; rollback if any privacy, delay or gameplay-proficiency regression.
5. **Game mastery:** independently observed win/success rate on held-out maps and new mechanics, retention and time-to-completion with CPU/VRAM budget unchanged or improved.

**This patch is deliberately not a deployed all-in-one Windows integration.** The recorder is real code and connects to the existing benchmark format; host sensor hookups, synchronized devices, OBS stream rehearsal, live gameplay measurements, learning-model changes and expressive voice generation remain unimplemented here. Refuse to advertise synthetic test timing as neural inference, speech or GPU speed.
