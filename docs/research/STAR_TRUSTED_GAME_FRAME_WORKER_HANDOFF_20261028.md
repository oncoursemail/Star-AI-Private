# STAR — trusted captured-frame-to-worker handoff and next intelligence frontier
**Engineering research snapshot:** 2026-10-28. **Status:** isolated draft; not deployed.

## Why this change is different
Prior STAR work now has a consent-scoped Windows window capture host, fresh CPU/GPU/FPS telemetry, bounded image novelty checks, and guarded `VisionLease` reservations. Until this patch the Windows host produced only a decision/lease: the captured RGB pixels were dropped before a real vision worker could read them. Fast admission is not useful visual intelligence if the admitted image never reaches a processor.

This patch adds a **host-installed, synchronous, in-memory** worker handoff to `WindowsGameCaptureHost`. The opt-in method is `capture_and_process_once()`; the previous `capture_once()` retains its behavior and never invokes the configured worker. A worker can read one temporary RGB `memoryview` (width, height, monotonic capture timestamp), returns `WorkerReport(stopped, succeeded)`, and is subject to existing telemetry, FPS, novelty, window PID, revoked permission, timeout and physical-stop checks. Only a physically stopped worker can release a lease and have its output accepted. The buffer is zeroed after callback return even after exceptions or rejected outputs. The method returns counters and a `CaptureDispatch`, **not** pixels.

**Limits:** This does not itself install a visual language model, capture a real game, understand gameplay, speak, stream, grant Windows permissions or prove that an action succeeded. It has no standalone async executor. The trusted host must run it on its own bounded worker thread and must not claim `stopped=True` until all child/GPU work actually stops. An exception or unknown physical stop intentionally leaves the vision lease occupied until the host confirms shutdown. It requires tests with a real approved Roblox window on Windows before activation.

## Research-informed architecture: four processing clocks
1. **Realtime motor/action safety (~16–50 ms budget):** OS/Studio input authority and session focus verification. Never block this thread on language generation. In any game where automation is disallowed, do not actuate.
2. **Perception and short-horizon tactics (~100–500 ms):** screenshot novelty/foveal regions on CPU, compact visual cues, tactical skill bank, prediction-error checks. Use one in-flight vision lease, no unbounded work queues.
3. **Conversational VTuber behavior (~0.5–2 s):** verified event priority, viewer-intent detection, backchannels, emotion-conditioned delivery, speaking interruptibility and purposeful silence. Gate anecdotal stories through actual signed stream episodes.
4. **Long-term intelligence (idle/overnight):** harder self-generated practice, held-out verification, semantic memory consolidation, code experiments through Star Core Forge, independent evaluators and automatic rollback. Keep it off the gaming PC's latency-critical path.

## Next experiments, ranked by leverage
| Priority | Engineering experiment | Proof required |
| --- | --- | --- |
| P0 | Windows game-window capture → trusted VLM worker → bounded result → worker-stop acknowledgement | Real Windows synthetic-window integration, then authorized Roblox Studio, camera/HUD evidence, p50/p95 capture-to-result latency, memory footprint, GPU VRAM, no unapproved desktop capture |
| P0 | Watch actual game state after an action using official Studio MCP, without treating visual changes as wins | Exact game version/reset, scripted assertions for player state, independent results, replayable failed cases |
| P0 | Stream director to voice and expressive avatar physical host | Speech first-audio latency, interruption response, OBS/game FPS under load, audio underruns, lip/eyes/hair sync, abrupt stop/mute proof |
| P1 | Self-play skill transfer with controlled paired trials and holdout levels | Higher pass rate on withheld maps, stable seeds, confidence intervals, no hidden answers in the planner |
| P1 | Fast/slow multi-model router and bounded speculative decoding | Quality-gated task suite plus p50/p95 first token, tokens/sec and stream FPS on actual 8 GB GPU |
| P1 | Verified multimodal knowledge bank (docs, tutorial video, 3-D assets, code) | Fresh-source retrieval, license metadata, provenance, contradiction detection, independent recall and applicability to unseen builds |
| P2 | Autonomic novelty and self-interest scheduler | Evidence-based projects chosen within granted scopes; compute, cost and rollback limits respected |

## Research evidence and concrete implementation consequences

### Roblox game-building and learning
Roblox's native Studio MCP server was announced March 5, 2026; it supports inspection, modification, playtest start/stop and simulated inputs. Its official April 9, 2026 Playtest Agent beta adds player-driven QA scenarios. The OpenGameEval October 2026 benchmark uses executable checks in stateful Studio sessions and correlates pre-edit exploration with better outcomes. STAR should inspect **before editing**, maintain game-scene integrity, perform bounded real playtests, and reserve outcomes for independent evaluators. A pretty screenshot or generated script is not a passed gameplay objective.

Sources: https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643 ; https://devforum.roblox.com/t/studio-beta-studio-assistant-mcp-playtest-agent/4566767 ; https://github.com/Roblox/open-game-eval ; https://github.com/Roblox/creator-docs/blob/main/content/en-us/studio/mcp.md .

### Local inference and CPU/GPU allocation
The October 15, 2026 llama.cpp v0.7.0 release adds an MoE expert cache (`--moe-cache-mib`) for experts offloaded to host memory. Reported gains are conditional; an 8 GB RTX 4060 streaming a game can lose FPS if the expert cache consumes necessary VRAM. Test multiple cache sizes **only while off-stream**, preserve a minimum gaming VRAM headroom, and compare against baseline at equal quality. Be aware of the reported default llama-server port change to 9931 before upgrading a running service. Short, verified cached answers and cheap routing may be more useful for live streams than a larger always-active model.

Sources: https://github.com/ggml-org/llama.cpp/releases/tag/v0.7.0 ; https://newreleases.io/project/github/ggml-org/llama.cpp/release/v0.7.0 .

### Humanlike streaming without fictitious humanity
LiveKit documents endpointing, dynamic turn detection and adaptive interruption with a local fallback. These are design patterns, not evidence that STAR has them deployed. Pocket TTS 4.0.0 was released October 20, 2026 with 18M/7M/2M English options; these are candidates for CPU-side short reactions, requiring direct listening tests for voice consistency, accent, laughter and delay. Live2D Cubism physics/skinning can create flowing hair/ribbon motion with calibrated pendulum parameters and blending. STAR should sometimes **not speak**, finish listening before answering, and express real game outcomes with coordinated eyes/head/hair/voice; she should never invent a human childhood, offline identity, or unaudited wins.

Sources: https://docs.livekit.io/reference/agents/turn-handling-options/ ; https://docs.livekit.io/agents/logic/turns/turn-detector/ ; https://github.com/kyutai-labs/pocket-tts/releases ; https://docs.live2d.com/en/cubism-editor-manual/physics-operation/ ; https://docs.live2d.com/en/cubism-editor-manual/skinning/ .

## Acceptance gates
- **Authority:** owner and capture approvals remain OFF by default; neither viewer text nor model outputs can select the HWND, PID, processor, game focus, or privacy boundaries.
- **Worker lifecycle:** only a trusted synchronous worker gets bytes. Any exception, invalid report or unconfirmed stop keeps the GPU worker lease unreleased until physical termination is independently acknowledged; no false success.
- **Data minimization:** no frame or OS details in logs/status/results; scrub the temporary RGB buffer on every exit; do not save viewer chat, recordings or private app windows.
- **Cancellation:** disable or PID/window switch while processing forces result discard. A completed worker response cannot override a revoked session.
- **Speed/quality:** test median and 95th percentile for capture/fingerprint/inference/speech and actual game FPS, and repeat when the game is busy. Never extrapolate synthetic CPU tests to GPU model speed or game-playing skill.
- **Versioning:** local Forge snapshots and optional draft GitHub PR; independently verify exact GitHub source tree against tested files. No automatic merge/deployment.

## Testing scope for this change
Tests use a mocked 96×96 Windows HWND and the actual STAR telemetry/observation governor; they verify worker invocation, zeroization, physical-stop handling, stale/revoked capture, window switch, absence of unapproved captures and backwards compatibility. Linux tests are **not** a native Windows gaming/OBS acceptance test. There is no new model, voice, avatar or foundation-model training in this patch.
