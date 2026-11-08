# Star AI — independent speech watchdog, reactive gameplay, streaming intelligence and speed research
**Date:** 2026-11-08
**Status:** implemented and unit-tested host-only worker; production integration and hardware measurements remain pending.

## Why this increment matters
The preceding `StreamPreplayPCMBridge.watchdog(now_s=...)` only runs when an external host invokes it. A TTS worker that stops producing chunks may also stop invoking any checks. Thus a PCM budget or an event-driven watchdog alone cannot bound a frozen turn. The implemented `StreamPCMWatchdogSupervisor` starts an **independent, opt-in, local thread** to drive the existing deadline even when TTS never emits its first chunk. It shares exactly one host-monotonic clock between `admit()`, `submit()` and recurring `watchdog()` calls. The explicit PCM-submission wrapper also checks a deadline synchronously; the worker loop is not the only protection.

Failures of the thread/clock/bridge, elapsed wall-clock timeout or failed native stop request **disable future submissions, request the actual PCM STOP through the existing bridge, and retain quarantine** until the owner's native device host independently proves the old output is drained. A timeout is NEVER recorded as spoken or physically silent. The watchdog does not open microphones or output devices, trigger gameplay or OBS, infer user identity, emit audio, or grant broadcast permissions. A crashed process still requires an external process/service supervisor.

### Offline validation and usage
```python
# ONLY inside the authorized owner-controlled local audio host.
# The gate, sink, SoundSpeaker and bridge are already enabled separately.
from star.stream_pcm_watchdog_supervisor import StreamPCMWatchdogSupervisor

monitor = StreamPCMWatchdogSupervisor(bridge, interval_s=0.05)
monitor.start(owner_approved=True)
try:
    # e.g. after review = gate.revalidate(...), using identical local timebase:
    advice = monitor.admit(review, epoch="unique-native-epoch",
                           independently_quiet=host_confirmed_quiet)
    if advice.state == "ready":
        monitor.submit(review.intent, epoch="unique-native-epoch", pcm16=pcm)
    # The trusted native host must perform bridge.complete_turn() /
    # bridge.attest_quiet() with genuinely independent output evidence.
finally:
    monitor.stop()
```
`host_confirmed_quiet` in this sample is a **trusted physical host observation**, NOT a value supplied by the model or derived from app-queue emptiness. Do not call this on a PortAudio callback thread.

Added tests cover owner approval, idempotent start, frozen TTS without PCM, synchronous submission deadline, stopped-but-unheard utterances, NaN/reversed clock, failed hardware stop, failed diagnostic callback, and wrong-epoch/invalid PCM. Tests are deterministic fakes; **real hardware has not been tested**.

## Research prioritization: from talking chatbot to credible gaming VTuber
1. **A real-time game brain with distinct deadlines.** Use a tiny reactive policy for frequent screenshots/input, a slower strategic planner between critical actions, and a separate offline teacher to analyze recorded failures. Keep existing `game_deadline_router`, `game_verified_fast_path`, action freshness/ack and holdout-once ledger as the source of truth. Gym-Anything-RT (Oct 27, 2026) explicitly separates paused/slowed and real-time versions of games, revealing large degradation under evolving environments. The practical target is **successful actions before the scene changes**, not text tokens per second. https://arxiv.org/abs/2610.37567
2. **Proactive, interruptible, socially appropriate speech.** Prefer short grounded reactions to game transitions, suppress repetitive commentary, respect someone else's speech, recognize the owner's interruptions, and choose meaningful silence. Proact-VL (ICML 2026) evaluates solo commentary, co-commentary and guidance in continuous video; timing and quantity of comments matter alongside content quality. https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/
3. **Audio+avatar credibility.** Align mouth/eye/gesture cues to *played samples*, not generated PCM length. Stop old utterances at interruption before any new avatar lip motion. Use independently verified audible completion for conversation memory, with time-limited memory retention and clear AI identity. Private rehearsal must measure observable output.
4. **Knowledge and game creation grounded in tests.** Separate factual/retrieval knowledge from hypotheses and episode memories. In Roblox, first inspect the exact objects and scripts affected, make scoped changes, run a playtest, and verify scene and behavior. OpenGameEval (Oct 2026) uses executable Studio checks and links inspection behavior with improved success. https://github.com/Roblox/open-game-eval
5. **2026 Roblox MCP capabilities and boundaries.** Roblox's November 4, 2026 Studio MCP update includes Open Cloud operations and per-game permissions. New agent workflows can inspect analytics or import assets, but must use the built-in Studio MCP permissions and a disposable test experience for data writes. These tools must not silently reach live stores. https://create.roblox.com/docs/studio/mcp-open-cloud and https://devforum.roblox.com/t/studio-mcp-server-updates-open-cloud-access-in-your-mcp-client-and-asset-import-workflows/4975849

## Benchmark speed rather than claim speed
The available RTX 4060-class 8 GB GPUs must run the *game + OBS encoder + avatar + inference* simultaneously. Protect gameplay/OBS first, then choose model/precision/context/CPU-GPU placement from **on-device measurement**. Kyutai's October 2026 Pocket TTS offers 18.2M, 6.9M and 1.9M English models aimed at CPU; benchmark naturalness, word errors, first-chunk latency and CPU contention against current voices. Its published speed is NOT Star's measured speed. https://github.com/kyutai-labs/pocket-tts

For each candidate route, run A/B in counterbalanced order on identical **private** game seeds, heldout situations, warmup policy and 10+ independent episodes per condition. Track:
- p50/p95 **frame capture → model decision → OS input acknowledgment → next observed game state**;
- failed deadlines, unintended key holds, task completion, unseen-game success and skill retention;
- TTS first audible chunk, interruptions p95, tail overlap, skipped speech and ground-truth episode accuracy;
- 1% low game FPS, VRAM peak, CPU utilization, OBS render/encode drop counters and local recording audio/video alignment.
Do not accept improvements that only raise decode tokens/s while worsening actual game outcomes or OBS stability. Use llama.cpp SPEED-Bench's baseline-vs-speculative procedures for inference comparisons, without extrapolating to end-to-end gameplay. https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md

## Next actual integrations in order
1. Native Windows host invokes the new supervisor, and owns `enable → reviewed admit → submit → independent drain → settle` atomically. Ensure the native STOP+FLUSH receipt cannot be forged by queued PCM/estimated timestamps. No public broadcast.
2. Private A/V rehearsal including game capture, inference, voice, avatar and OBS with source-correlated timing and real device telemetry. Gate every *stream-enabled* path on the rehearsal's fail-closed result.
3. Run at least three unseen-game practice scenarios, with the holdout-once ledger never used for training and independent sign-off of results. Compare policy improvements across multiple seeds.
4. Counterbalanced inference and CPU TTS experiments, then optionally build a dynamic route selector only from verified performance under actual gaming/OBS load. Avoid large model downloads while local disk headroom is low.
5. Long-term personality: distinct style/expressions, verified episode diary, consent-aware social memory, spontaneous hobbies, and a clear disclosed AI persona. This yields **human-like interaction**, not evidence of human sentience.

### Caveats
No model training, native Windows audio capture, live speech, OBS recording, game controls, Open Cloud writes, streaming, production deployment, or measured neural inference gains were performed in this increment. The new thread runs only after explicit owner approval; it cannot survive an application/process crash. Tests use an isolated fake SoundSpeaker and mocked host clock. On-device A/B measurements remain the decision gate.
