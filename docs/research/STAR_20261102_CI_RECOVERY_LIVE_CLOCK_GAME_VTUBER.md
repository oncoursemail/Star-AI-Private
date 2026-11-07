# STAR: CI recovery, live-clock game intelligence, and believable VTuber engineering

**Research and implementation note — November 2, 2026.** This note separates verified changes from proposals. No neural weights were changed; no game or OBS broadcast was started.

## 1. GitHub CI failure, diagnosed and fixed in this branch

[GitHub Actions run 41496836235](https://github.com/oncoursemail/Star-AI-Project/actions/runs/41496836235) for draft PR #910 failed two jobs despite earlier focused local tests passing.

- Full offline suite: **15,185 passed, 329 skipped, 705 subtests, one failed**. The failed test, `test_parallel_benchmark_can_measure_the_server`, uses a fake OpenAI-compatible response missing `finish_reason`. Production benchmark logic *correctly* rejects unknown/truncated completion states; the test fixture must provide `finish_reason="stop"` to simulate a completed reply. Do **not** weaken the production integrity check.
- Pyright baseline gate: `star/stream_endpointing_eval.py:27` passed an `object` directly to `float()`, causing `reportArgumentType`. Narrow type to `int | float` with `cast()` **after** existing strict runtime validation. Do not widen accepted input or update the error baseline.

These issues do not prove that model throughput or reasoning regressed. They block GitHub's release-quality evidence until a passing run exists.

## 2. Real-time intelligence must use the *live clock*

[Realtime-Bench](https://arxiv.org/abs/2610.22155), submitted October 15, 2026, distinguishes *Wall Clock* (game advances while the model thinks), *Paused Clock* (inference pause removed), and *Token Clock* (simulated time follows generated tokens). Its reported best wall-clock success of 44% and Pass^3 of 36% are **paper results, not STAR results**.

**Proposed STAR experiment:** extend the existing `game_deadline_router.py` and `game_realtime_loop.py` offline harness with all three timing modes, keeping scenarios, seed, model version, action set, and permissions fixed. Record captured-frame age, decision-to-action time, expired leases, correctness, and *actual progress at the deadline*, not only tokens/second. Test new game builds and unfamiliar seeds. Compare fast student vs slow teacher only when the teacher's extra reasoning time is included.

[The World Won't Wait / RealtimeBench](https://arxiv.org/abs/2610.20665), submitted October 14, 2026, describes slow offline teacher / fast online student learning. Its reported progress change from 13.51 to 24.19 after two learning rounds is from the paper, not a STAR measurement. For STAR: between attempts, save scoped lessons with provenance, replay on distinct hidden holdouts and revoke lessons on regression. Never leak holdout outcomes to training or run a teacher during a live broadcast or resource distress.

## 3. Humanlike VTuber delivery depends on selecting *when* to speak

[Proact-VL](https://arxiv.org/abs/2603.03447), first submitted March 3, 2026 and revised June 2026, treats proactive gaming companions as joint problems of latency, when-to-respond, speech quantity and output quality. Its evaluation spans solo commentary, co-commentary and user guidance.

STAR already has advisory primitives in `stream_director.py`, `stream_social_turn_benchmark.py`, `stream_idle_attention.py`, `stream_endpointing_eval.py`, `stream_stage.py`, and `stream_quality.py`. This does **not** imply a working Windows avatar/microphone/OBS integration.

**Proposed operator-reviewed benchmark:** preregister viewer questions, actual game successes, failed attempts, speech hesitations, accidental noise, owner interruptions, critical-game silence and topic changes. Measure speaking-decision precision/recall, unnecessary remarks, pauses, overlapping voice, p95 first *audible* PCM latency, lip/audio drift, grounding failures, scene-stale memories, and game frame-time tails. Analyze independent conversations or episodes, not correlated frames as independent samples. Silence can be the correct answer.

Character performance: small irregular blinks, gaze following genuine game state, subdued idle animation, variable prosody, conversational restraint, short sincere reactions to *verified* events, continuity of real game experiences, and expressive Star/Astro/Amber interactions. Never invent wins, real-world memories, human biology or private relationships. Disclose that Star is an AI performer rather than deceiving viewers about being human.

## 4. 8 GiB VRAM: speed without game/OBS regressions

The [llama.cpp server documentation](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md) covers optional prompt caching and metrics. [SPEED-Bench](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md) measures speculative-decoding throughput and draft acceptance instead of assuming every draft model is faster.

**Proposed controlled comparison:** prompt cache on/off x speculation on/off x OBS/game load idle/active, using identical model hashes, prompts, slot counts and matched Windows hardware. Measure TTFT, *completed and valid* response p50/p95, total wall time, token throughput, draft acceptance, CPU/VRAM peaks and 1%-low game FPS. Reject truncated completions, stale cache canaries, source-mismatched screenshots and missing device-clock evidence. Use the verified fastest *quality-preserving* configuration, never fastest tokens alone.

**Scheduler order:** protect capture/game/OBS/audio first; offer bounded reactive inference; admit speech synthesis and sparse vision only under verified headroom; stop offline teacher, indexing and asset generation during gaming/stream stress. CPU speech may protect GPU memory but can starve gameplay on the CPU: measure it, do not assume.

## 5. Nonbroadcast Windows acceptance test (still outstanding)

The official [OBS WebSocket API](https://github.com/obsproject/obs-websocket) provides status/metrics; [VTube Studio's plugin API](https://github.com/DenchiSoft/VTubeStudio/wiki/Plugins) supports host-approved expressions, hotkeys and avatar parameters. This branch adds neither adapter.

Acceptance requires verifying game window/focus, OBS **not streaming**, avatar ownership, microphone consent and audio-device clock epoch. In a separately approved local recording, test speech generation, real speaker interruption, mouth movements tied to consumed audio, signed gameplay observations, scene handoffs, and released game keys. Inject GPU pressure, OBS frame drop, scene changes, low-confidence speech and worker crashes. Confirm neutral avatar, muted playback, stopped workers and no external broadcast at shutdown. Keep evidence anonymized, local and short-lived.

## 6. Game creation and general knowledge improvements

Use existing Roblox Studio Lab, Luau static analysis and automated testing to ship a tested *vertical slice*: inspect project -> produce alternative designs -> compile and lint -> run engine and multiplayer interaction tests -> inspect geometry/UI/animation screenshots -> repair verified defects -> retain a source-linked, versioned lesson. Don't equate compilable code with working game mechanics.

Maintain a distinct **knowledge provenance vault** for published sources with capture date, version, trust grade, contradiction tracking and retrieval citations. Separate verified external knowledge from persona memory, unverified chat and game logs. If no source supports a claim, Star should acknowledge uncertainty rather than hallucinate.

## Release status

**Actually implemented here:** restore protocol-accurate successful fake responses in the benchmark tests; resolve the endpointing Pyright typing violation without altering runtime behavior; document an experiment-and-acceptance plan. **Already present but not proven in live integration:** opt-in gameplay action and streaming advisory layers. **Not done here:** model training, new reasoning weights, measured inference acceleration, real game winning, Windows streaming rehearsal or public VTuber broadcast. Leave the PR draft stacked on #910 and keep `main` untouched until GitHub CI and host acceptance pass.
