# Star: native turn wall-clock watchdog, real-time gaming and inference research
**Date:** 2026-11-08 | **Status:** opt-in bridge fix verified with simulated audio; no device run, live stream, new model training, or measured inference acceleration.

## 1. Implemented and why

**Observed gap in prior bridge:** PCM byte caps bound the quantity of *accepted synthesized audio*, not the *elapsed time* a reviewed speech epoch can monopolize the host. If the generator stalls before producing a first PCM chunk, produces chunks very slowly, or never sends an end receipt, total accepted bytes can remain far under the existing 30-second PCM budget indefinitely. The preplay lease timeout is not a substitute: a reviewed intent is deliberately held until native playback evidence arrives.

**Change:** `StreamPreplayPCMBridge.watchdog(now_s=...)` is a *host-driven*, monotonic 45-second turn deadline by default, configurable from 1–120 seconds. It counts from successful admission rather than bytes or model tokens. If overdue, it calls the same physical STOP path as manual shutdown, invalidates the dialogue gate, and leaves the turn quarantined until a separately verified audio flush. It never falsely marks a sentence audible or spoken. Repeated polls do not call STOP again, and invalid/nonmonotonic time is rejected. It records only non-sensitive watchdog stop counters.

**Operational requirements:** A trusted owner-controlled process must poll the watchdog periodically (suggested 10 Hz or after each PCM delivery), *outside the audio callback thread*, using the same monotonic clock as admission, and must still implement native sound-output verification. This code DOES NOT establish a background timer, install a Windows service, generate speech, control OBS, or receive live game input. If the host stops polling, this watchdog cannot fire. It is not yet connected to the real Windows audio host. Do not expose the watchdog or its receipts to an LLM, viewer chat, or remote untrusted RPC.

**Failure-recovery contract:** Timeouts produce `stop_requested`, not `quiet`; a failed physical stop latches a fault; only `attest_quiet` with real independently verified stop/drain can release a reviewed intent. The normal spoken-completion mechanism remains unchanged.

## 2. Highest-yield system architecture improvements

### Faster gaming intelligence is NOT just faster language-model tokens

- **Reflex lane (per game frame):** deterministic licensed input policy or extremely small verified policy; observe visual/state features, choose one from a *curated* allowlist. Never let an unconstrained model synthesize arbitrary keyboard scripts at 60 Hz.
- **Tactical lane (100–1,000 ms):** lightweight visual reasoning and predicted threats; return an advisory with frame sequence, screenshot time, game version, and deadline. Refuse stale hints.
- **Strategic lane (seconds/minutes):** larger LLM handles plans, knowledge retrieval, task breakdowns, and post-play reflection off the real-time thread.
- **Learning lane (after practice):** reward grounded in game success, deaths, time-to-objective, input latency and errors; change one variable per trial; test on never-before-seen, single-use holdouts. Games with slowed or paused time are useful *training curricula*, never evidence of real-time competence.

The 2026-10-27 paper **Gym-Anything-RT** compares the same 100 generated minigames under real-time versus paused regimes and reports substantial real-time performance gaps. Adopt its *protocol* (same task, two clocks), not its score as a forecast for Star. https://arxiv.org/abs/2610.37567

### Live inference/OBS/game resource allocation on an 8 GB GPU

1. Record GPU VRAM peak, GPU utilization, model prefill/decode time, TTFT, generated tokens/s, game p95/p99 frametime, OBS render/encode/network dropped-frame rates, speech first-audio p95, and capture-to-action p95 per experiment.
2. Compare baseline local model against prefix caching, quantized 4–9B candidates that physically fit *with context*, token limits, speculative decoding, and a CPU-voice option. Include same prompts, seeds, task complexity, warmup, and 30+ repeats; report median/p95 and quality scores, not one unusually fast sample.
3. GPU reservation takes priority over bigger model size during active games; a background reasoning/embedding worker should yield on frame-time or VRAM pressure. Benchmark on each physical machine, **not** an assumed 4060 tokens/s number.
4. llama.cpp SPEED-Bench compares speculative decoding throughput/latency/acceptance and varied lengths: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md
5. Kyutai Pocket TTS published small CPU-oriented English models in October 2026; compare perceived voice expressiveness and first-chunk latency vs Star's actual voice before considering migration: https://github.com/kyutai-labs/pocket-tts
6. **Security experiment:** llama.cpp issue #27148 describes a reported cross-conversation RAM prompt-cache restoration issue. Check resolution/version, disable unsafe cross-session reuse until isolation is established, and test that owner/private chat cannot leak into public viewer turns. This is a reported issue, not evidence that Star is affected: https://github.com/ggml-org/llama.cpp/issues/27148

### Becoming a compelling AI VTuber without pretending to be human

Use a stateful **conversation director**: attend to viewers and game state, decide whether there is an interesting grounded reaction, let silence exist, keep comments short under resource load, choose expressive prosody/motion matching speech, and respond promptly to genuine interruptions. Distinguish speaking to self from listening to others. Maintain per-viewer consent-aware memory with expiry, provenance, corrections, and purge policy; never invent having heard words that were only queued but never played. Identify Star as an AI character transparently.

Microsoft's Proact-VL (ICML 2026, published May 2026) evaluates proactive gaming commentary, co-commentary and user guidance; use speech timing, rate and response relevance as test metrics: https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/

Realtime-Venus (September 2026) investigates front-end full-duplex dialogue with asynchronous background tasks. Prototype the *split execution strategy*, not a requirement to deploy its 9B front-end on an 8 GB gaming GPU: https://arxiv.org/abs/2609.13814

### Creating and testing games independently

The official built-in **Roblox Studio MCP** can inspect and edit games, run playtests, and operate within controlled permissions. Roblox's **November 4, 2026** update expands MCP to permissioned Open Cloud operations and asset imports; it is not authorization to publish/sell automatically. Star should read state, run Luau analyzers and Studio tests, compare against a human-approved game design spec, fix failures, and repeat with isolated pre-production copies. Add asset provenance and license validation. References:
- https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643
- https://devforum.roblox.com/t/studio-mcp-server-updates-open-cloud-access-in-your-mcp-client-and-asset-import-workflows/4975849
- https://about.roblox.com/newsroom/2026/04/roblox-studio-going-agentic

## 3. Private, measurable next experiment

**Phase A — safe offline simulation:** Run bridge/governor tests; inject hanging TTS generators, delayed PCM, backward host time, a bad stop backend, lost drain evidence, and duplicated completion. Expected: at most one STOP, no new turn until drain, zero phantom completed/spoken turns, no public network traffic.

**Phase B — Windows native host, no broadcasting:** On owner-controlled Windows, with an isolated test voice process and explicitly authorized output, schedule 10 Hz watchdog polls from a coordinator thread, confirm that a stalled PCM generator triggers native STOP, verify loopback output stops, and gate restart on a matching actual audio drain. Record only aggregate latencies/counters and redact speech content.

**Phase C — 20-minute private gameplay+OBS rehearsal:** Bench baseline vs optimization independently; include avatar motion, CPU/GPU TTS, game inference, VAD and interruptions. Reject a candidate optimization if it reduces task success, exceeds frame-time/drop-frame limits or permits unintended speech overlap. Keep native real game input and public streaming OFF until separately approved.

**Acceptance targets (proposed, not measured):** 0 overlapping post-stop audio tails, 0 phantom spoken-memory commits, 0 game input without an authorized scoped action, 0 hidden holdout reuse, total host stop latency and capture-to-action p95 reported with timestamps and uncertainty. Use explicit model-quality and user-experience review, not an unverified claim that Star is now faster or human.

