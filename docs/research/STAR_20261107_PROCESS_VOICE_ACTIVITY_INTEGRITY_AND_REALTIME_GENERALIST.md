# Star AI — coherent process-loopback voice evidence and measurable VTuber/gaming intelligence
**Research and engineering note, November 7, 2026.** This is a private, offline-first plan, not a claim of increased model IQ, game mastery, or functioning live VTubing.

## What this patch actually changes

The native Windows process-loopback diagnostic reports approximately 50 ms amplitude buckets and cumulative native audio callback and frame totals. The previous C# Emit() implementation reset the interval under a lock **then read cumulative counters after releasing the lock**. A concurrent native audio callback could make the exported interval contradict the exported cumulative counters. That is unreliable evidence for a natural voice interruption timeline.

- **Fixed:** C# TakeActivitySnapshot() atomically snapshots both interval and cumulative counters under one lock. Does not record raw PCM, capture a microphone, or authorize streaming.
- **New:** star.process_loopback_activity.ProcessLoopbackActivityVerifier is a default-off, one-shot bounded Python parser of native diagnostic JSONL. It rejects duplicate/missing fields, false silence claims, counter discontinuities, changed schemas, source restarts, bad packets, malformed data and unexpected authority flags.
- **Evidence boundary:** possible_audio_activity is merely an amplitude hint, not speech diarization, game success, digital/physical silence, verification of process identity, or broadcasting permission. An interval with no PCM callbacks returns None, not False.
- **Host contract:** Only feed JSONL from one **hash-pinned, owner-launched, process-identity-pinned** dedicated Star voice diagnostic. Pin process creation time and capture session; never accept viewer/model/chat-supplied lines. A local Windows host must independently correlate verified native audio abort, avatar neutral state, and OBS recording.
- **Not yet connected:** this Python component does not spawn real Windows capture, verify Windows speakers, alter OBS, launch games or talk on stream.

Host-only import example: instantiate ProcessLoopbackActivityVerifier(owner_approved=True), feed_line(native_json_line) for each line emitted by an authenticated short-lived process, then inspect summary(). The report always has authorizes_broadcast=False and verified_silence=False. A non-completed report, abnormal native exit, or malformed line is a hard failure.

## Five research-backed priorities for the next engineering cycles

### 1) Real-time game learning, not paused-model benchmarks

[Gym-Anything-RT (Oct 27 2026)](https://arxiv.org/abs/2610.37567) evaluates 100 minigames both under actual real-time constraints and with relaxed timing. There is a large performance gap. Star needs three cooperating decision loops: local reflex actions within an observed deadline, tactical planning without blocking the game, and expensive teacher analysis only between privately recorded attempts.

**Experiment:** pair a cheap rules/reflex baseline with a local small model and a stronger between-round teacher on matched privately replayable game episodes. Record target observation age, action submission plus OS acknowledgement, authoritative game outcome, capture-to-action p50/p95/p99, missed deadlines and actual frame rates. Preserve success on unseen maps and seeds. Reuse existing game_deadline_router, game_skill_gate, game_mechanic_experiments and signed skill bank; never create an alternate path that directly grants game input.

### 2) Game creator improvement with executable ground truth

[Roblox OpenGameEval (Oct 2026)](https://github.com/Roblox/open-game-eval) supplies reproducible Studio tasks and tests on scenes and simulated gameplay. Inspecting affected game objects before editing them correlates with success. [Roblox Studio MCP's Nov 4 2026 expansion](https://devforum.roblox.com/t/studio-mcp-server-updates-open-cloud-access-in-your-mcp-client-and-asset-import-workflows/4975849) adds permission-scoped Open Cloud access and asset imports.

**Experiment:** a nonpublishing 10-task curriculum using immutable place snapshots: inspect -> reproduce -> add tests -> edit Luau/asset -> Studio simulation -> visual screenshot inspection -> repair -> holdout tests. Score executable success, regressions, repair attempts, latency/cost, and independent owner review. Asset purchases, public publication, external communication, and financial action stay owner-authorized.

### 3) GPU-friendly inference and quicker first *audible* response

[llama.cpp SPEED-Bench](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md) measures throughput, latency and speculative draft acceptance. [Kyutai Pocket TTS](https://github.com/kyutai-labs/pocket-tts) provides CPU-oriented streaming speech, including small October 2026 English variants.

**Experiment:** compare vanilla local inference, prompt-KV reuse and speculative drafts, plus CPU speech against the current voice engine, with the same test questions and quality threshold. Measure first token p50/p95, first audible phoneme, interruption-to-monitor quiet, stale speech leakage, game-action success, OBS frame drops, frame-time p99, and minimum GPU free VRAM. A dedicated 8 GB RTX 3060 Ti/4060 may be heavily contended by game+OBS+avatar+LLM; route optional LLM/TTS to CPU when measured GPU pressure threatens rendering. Never infer a speed gain from architecture papers alone; speculation can regress for poor draft/target pairings.

### 4) Expressive, AI-transparent VTuber presence

[Microsoft Proact-VL (ICML May 2026)](https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/) studies when a gaming companion should respond, not only what to say.

**Stream behavior:** rank game-critical events over idle chatter; authenticate owner barge-ins; corroborate event claims with game state; maintain gentle gaze/blinks/movement during quiet periods without blocking input; support reduced motion and persona opt-in toggles; preserve verified moments as memories rather than claiming invented experiences. Use concise natural reactions, pauses and self-corrections. Keep an accurate AI disclosure and avoid making viewers believe Star is a biological human.

### 5) Real Windows sound is a separate acceptance gate

[Microsoft's Application Loopback sample (Feb 19 2026)](https://learn.microsoft.com/en-us/samples/microsoft/windows-classic-samples/applicationloopbackaudio-sample/) supports process-tree-specific capture rather than a whole-system endpoint and requires Windows build 20348+. The NAudio callback behavior when a process goes quiet must be measured, not assumed. No callbacks alone are not a certificate of physical silence. A dedicated isolated voice source, native abort result, independent output monitor and avatar-neutral acknowledgement are needed before calling a private rehearsal successful.

**Release gates:** GitHub-hosted Windows smoke builds a self-contained executable with no real capture; a separate expressly private on-owner-PC test isolates a dedicated voice process, never a microphone or full desktop; OBS is recording locally and never broadcasting; cross-lane observation timestamps/frames and game-state outcomes are checked; regression and holdout results are compared. None of those final on-device integration gates are satisfied by this patch.

## Honest evidence table

| Verification | In this patch? |
|---|---|
| Python JSONL parser and malformed/counter attack tests | Yes, synthetic |
| Atomic native producer counters and .NET synthetic self-test | Yes, Linux build/self-test |
| Self-contained Windows hosted smoke | Requires independent CI |
| Actual Windows process-loopback capture | No |
| Real physical-silence confirmation | No |
| Faster measured model inference | No |
| Improved held-out gameplay skill | No |
| Permission to broadcast | No |

The implementation is a practical step toward reliable, private, **measured** VTuber voice-latency evidence. It is not an auto-promotion, performance, or intelligence claim.
