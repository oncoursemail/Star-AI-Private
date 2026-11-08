# STAR — Cross-process audio isolation, faster intelligence and VTuber capability review

**Prepared November 8, 2026 (UTC).** Status: **tested offline differential auditor and owner-only Windows experiment code**, not deployed, not an audible experiment, not a benchmarked model improvement. Previous positive tone fixture PR #1060 is the immediate parent. This is a *stacked draft*.

## What changed this iteration

A process-specific WASAPI capture path activating successfully on a silent fixture and an in-memory tone generator passing `--self-test` do not show that the output is *exclusive* to the intended process. A shared system mix could accidentally be accepted as a private voice stream if the test only checks that the target produces nonzero PCM.

This iteration implements a **paired independent-process differential experiment**:

- Disposable `StarToneProbe.exe` produces a short 440 Hz, 3%-scale tone after a 1.8 s lead-in when specifically launched in paired mode. The existing standalone tone's lead-in remains unchanged.
- A second `StarSilentControl.exe` makes no audio at all. Both fixtures are *children of the owner-run script*, and the owner cannot point the test at a browser, game, microphone, or third-party PID.
- Two independent `Star.ProcessLoopback` observers run **concurrently**, one bound to the tone PID/executable and the other to the silent PID/executable. The short-lived source is deleted, and trace files contain only activity counters and amplitude summaries, not PCM or speech.
- The new offline Python differential auditor consumes the exact two bounded JSONL streams. It reuses STAR's strict native-window verifier to reject invalid JSON, duplicated keys, forged silence/broadcast/game authority, nonmonotonic counters, invalid amplitudes and incomplete captures.
- **Fail-closed comparison:** the positive control must show **at least two** measured nonzero PCM windows (peak >= 2, RMS >= 1, 2–300 milli full-scale maximum); the negative control must also show at least two healthy *zero-amplitude PCM* windows and **no** nonzero PCM anywhere. **Missing callbacks in the negative control are inconclusive**, not evidence of isolation or physical silence.
- Both double opt-ins `-OwnerApproved -AllowAudibleTone` are required, and the fixture cannot be launched in paired mode without exact authorization arguments. Windows CI runs only compilation, deterministic waveform self-tests, parser tests and rejected invocation paths; it never plays sound, captures audio, runs OBS, or broadcasts.

This is an **offline-compatible trace pair** after a trusted owner host supplies two observations, not a certificate of Windows process identity. JSONL cannot authenticate PIDs; the owner-host process handles and explicit target-exe binding are a separate trust boundary. Windows hardware results are still pending. These controls are never a playback-stop/quiet witness or an authorization to go live.

### Exact acceptance ladder

| Step | Evidence to demand | Status |
|---|---|---|
| Native activation on owner Windows | Windows process loopback opens a fresh isolated silent child | Previously demonstrated on Nov 7 |
| Differential S1 | **One concurrent audible positive + silent negative**, both completed, correct pinned child identity, bounded PCM contrast | **Implemented for owner-only experiment; not run** |
| Actual voice S2 | Fresh signed STAR TTS subprocess; known approved utterance; physically monitored playback; independent isolation | Not implemented |
| Interruption S3 | Verified abort request, native pending-packet state, health/lifecycle, output stage neutrality, no old audio tail | Not verified |
| Private game/OBS S4 | Real game with avatar and recording-only OBS session; p50/p95/p99 end-to-end reaction, video and voice QoE, dropped frames and GPU headroom | Not verified |
| Live S5 | Owner-reviewed acceptance, separate explicit platform/stream consent, moderation and privacy | Not granted |

## Turning intelligence into measured real-time performance

**Research signal.** The October 27, 2026 *Gym-Anything-RT* paper compares the same 100 minigames under real-time and paused conditions and finds major gaps. The correct response is not simply to increase context or ask the model to deliberate longer.

**Proposed STAR architecture:** keep a *fast policy* (fresh scene and safe actions) independent of a *slower planner* (strategy, tool reasoning and retriever). Give each observation an immutable epoch and short deadline. Never allow late planner work, cached chat responses or previous-game actions to control the current game. Existing modules `game_deadline_router`, `game_realtime_gap_audit`, `game_gap_failure_atlas`, `game_holdout_once_ledger` should share one signed, source-bound capture-to-action trace before claiming improved ability.

**Learning that generalizes:** run curriculum from 2D obstacle navigation -> temporal avoidance -> aiming/physics -> cooperative control. Generate new seeded challenge distributions, preregister a separate once-only holdout, block evaluation leakage from the training memory store, compare old/new policies on matched trials, and **revert** if a skill worsens on unfamiliar games or gameplay FPS degrades. A high score in paused games must not be misreported as interactive real-time competence.

**Roblox game creation:** the October 2026 OpenGameEval paper reports 84 stateful Studio tasks and shows exploration before editing associates with success. STAR should use inspect-before-edit, API checks, Luau lint/type checks, owner-approved Studio actions, and authoritative edit-mode + simulated-playmode tests. Score independently checked task completion, not volume of generated code. Add a private dataset of previously unseen UI, VFX, gameplay physics, multiplayer and debugging tasks.

## Speed and resource budget on an 8 GB GPU

1. **Measure while gaming, not in a vacant GPU benchmark.** Record GPU memory current/peak, p99 frametime, OBS rendering/encoding drops, input p50/p95, LLM TTFT, decode tokens/s, queue delay, and voice first-byte/stopping tail. Run simultaneous game + OBS recording + avatar + TTS + LLM before and after each optimization.
2. **Pareto model routes.** A 4-bit ~9B model may occupy much of an 8GB card once KV cache, inference runtime, compositor, game and OBS need memory; never promise fixed tokens/sec or unbounded context. On VRAM pressure, favor smaller or CPU-assisted fast policy, reduce active context/admit fewer jobs, and preempt background self-learning. Prefer *measured* utility per wall second over model parameter count.
3. **Exploit verified prompt/cache locality.** Stable skill instructions and game API documentation belong in reusable prompt prefixes; fresh visual frames and live streamer conversation belong in bounded changing suffixes. Compact long history into provenance-aware events and fetch relevant facts with validity timestamps.
4. **Evaluate speculative decoding, don't assume it helps.** llama.cpp supports draft models, n-gram and EAGLE-3 variants; its SPEED-Bench reports latency, throughput and draft acceptance. Compare paired workloads with and without speculation under the *same* 8GB gaming GPU pressure. Reject methods that raise frame stalls or p95 speech latency even when decoding tok/s rises.
5. **Speech offloading:** Kyutai Pocket TTS is designed for CPU real-time generation; test voice quality, streaming start, timing and interruption rather than treating compactness as quality. Pre-synthesizing lines may cause stale speech; live freshness/interruptions take priority.
6. **Instrument and protect the stream:** OBS WebSocket is bundled with OBS 28+ and should be authenticated; prefer recording-only and read-only stats probes. Treat 'recording active' and 'streaming active' as distinct states. Inference should reduce load first when OBS dropped frames or game frametimes deteriorate.

## More natural AI VTuber conduct

Research such as Microsoft's *Proact-VL* (ICML 2026) focuses on **whether/when to speak** in a live gaming context. STAR should use a turn policy with silence and opt-in speech; detect verified game milestones and avoid chatter during critical reaction windows. Keep TTS mouth/eyes tied to actual playback state, not token generation. Build consistent, original expressive persona and interests grounded in witnessed sessions, while remaining **AI-transparent** rather than claiming to literally be human or conscious.

Suggested experiences to evaluate in private recording: clean interruption when an owner speaks; context-aware excitement when the game state confirms a win; calm recovery on failure; fair credit to other players; voluntary quiet during tense actions; controlled proactive comments after cooldown; consistent memory of verified prior episodes; safe moderation and privacy protection. Use blind human ratings of naturalness, relevance, pacing, memory accuracy, disclosure and repetition. A transcript that *sounds* human is not proof of achieved on-air latency or gaming skill.

## Measurement contract before any stronger claim

- **Inference improvement** = significant reduction in p95 end-to-end task time without worse task success, context-grounding error, GPU memory pressure, game FPS or OBS performance. Three or more repeated paired configurations with exact host/model/quantization and timestamps.
- **Gaming improvement** = better progress/win rate on previously unseen *real-time* episodes with controls for seeds and compute wall time; holdout-once ledger prevents repeated exposure.
- **Streaming improvement** = lower validated overlap/late-voice rate, acceptable private listener ratings, authentic process-local PCM observation and recording-only OBS stability.
- **Human-like improvements** = natural expressivity and social ability; do not imply actual human biology or subjective experience.

## Primary sources checked November 8, 2026

- Microsoft Windows process-loopback sample and include/exclude process-tree model: https://learn.microsoft.com/en-us/samples/microsoft/windows-classic-samples/applicationloopbackaudio-sample/
- NAudio WasapiRecorder API documentation: https://naudio.github.io/NAudio/docs/WasapiRecorder.html
- Gym-Anything-RT, published October 27, 2026: https://arxiv.org/abs/2610.37567
- Roblox OpenGameEval, October 2026 paper and executable Studio framework: https://arxiv.org/abs/2610.02563 and https://github.com/Roblox/open-game-eval
- llama.cpp speculative decoding methods: https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md
- llama.cpp SPEED-Bench client: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md
- Microsoft Proact-VL (ICML 2026): https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/
- Kyutai Pocket TTS (2026 CPU real-time TTS): https://kyutai.org/next/tts/
- OBS WebSocket official repository (bundled OBS 28+, authentication guidance): https://github.com/obsproject/obs-websocket
