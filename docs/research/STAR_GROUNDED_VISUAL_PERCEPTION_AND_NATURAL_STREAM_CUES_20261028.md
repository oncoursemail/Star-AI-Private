# STAR — grounded visual perception and natural game-stream cues
**Engineering research snapshot:** October 28, 2026. **Status:** optional, local-first draft feature; no deployment.

## The bottleneck addressed
PR #729 added approved, PID-scoped Windows game capture, real CPU/GPU/FPS telemetry, a novelty gate, a single-flight vision lease, and a synchronous host-managed worker. It reported only that a worker physically stopped or succeeded. The vision result could not enter a bounded game-awareness path or contribute safely to VTuber attention. More screenshots alone do not yield intelligence.

This change adds a **candidate semantic layer**:
- An immutable VisualPacket from 1–4 categorical findings: HUD/scene/menu changes, movement, newly appearing objects, possible hazard indicators, and unknown. Each finding has a host-defined region, a model-reported confidence and optional normalized rectangle. There are **no free-text captions, quotations, URLs, instructions, private pixels, or win labels**.
- A WorkerReport can include a packet only after physical stop and successful processing. WindowsGameCaptureHost checks that packet timestamp and dimensions exactly match the authorized game frame, and all existing lease, window identity, revocation and resource checks still pass. Revoked or stale results are discarded.
- An independent, disabled-by-default GameVisualCueHost may turn **two distinct admitted frames** agreeing on category+region into a low-priority game_observation proposal to StarStage. It enforces confidence, freshness, ordering, and a cooldown. Evidence is always marked reported rather than observed: a VLM guess can never trigger a victory or danger animation.
- This is an **offline integration bridge**. No actual VLM, game-control policy, neural training, TTS engine, OBS broadcast or new permission is installed.

### Future trusted host wiring
1. A host authorizes one game process/window and continuously supplies measured CPU, GPU, FPS, voice backlog and capture rights. Default OFF remains unchanged.
2. An explicitly installed local VLM processes CapturedVisionFrame.rgb in the trusted synchronous worker. Parse its strict JSON findings with parse_visual_packet and supply captured_ms, width and height **from the frame**, not from model-generated text. The VLM must not select the processor, HWND, PID or crop.
3. Return WorkerReport(stopped=True, succeeded=True, perception=packet) only when physical model/child/GPU work really stopped. Unknown stop must remain quarantined. Image bytes are zeroized after the callback.
4. If the capture dispatch contains an accepted packet, a trusted local host may optionally call GameVisualCueHost.observe(dispatch, now_ms=monotonic_clock). Do not expose this class as a viewer, webpage, in-game or general model tool.
5. StarStage may elect to remain silent. The separate physical TTS and avatar host must still acknowledge audible playback, manage interruptions and mute/reset on shutdown. Stage plans are not speech.
6. Use local endpoint allowlists for future model adapters. Never relay personal screenshots to arbitrary model APIs, log raw frames, or put secrets in a source repository.

Example bounded VLM JSON (the model must not choose its own capture timestamp):
{"findings":[{"kind":"hud_change","region":"hud","confidence":0.91,"box":[20,30,150,100]}]}

The model's confidence is not a calibrated probability. Two agreeing readings from the same model are *not* independent truth verification. A winning state still requires signed game-engine evidence.

## Research findings and future priorities

### 1. Game construction needs executable tests
Roblox's built-in Studio MCP server was announced March 5, 2026. Its Playtest Agent beta followed April 9. The October 1, 2026 OpenGameEval study covers 84 curated Roblox tasks with executable checks and finds that agents which inspect relevant objects before editing are more likely to pass. For STAR, use **inspect → plan → generate alternatives → Studio playtest → independent assertions → screenshot/geometry audit → repair → retest**. A convincing image or code sample is not a playable experience.

Sources:
- https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643
- https://devforum.roblox.com/t/studio-beta-studio-assistant-mcp-playtest-agent/4566767
- https://github.com/Roblox/open-game-eval
- https://arxiv.org/abs/2610.02563

### 2. Gameplay mastery requires causal tests, not a victory guess
Use **perceive → hypothesize → permitted action → independently inspected state/result → strategy revision → matched-seed retry**. Visual packets help *where to look*; they cannot prove causality, kills, health, unlocked rewards, a completed objective or memories. Feed actual signed practice records into STAR's existing skill bank. Evaluate transfer to unseen levels, unknown controls, altered camera positions and unique objectives.

Create three processing lanes:
- **Reflex (~16–50 ms desired):** trusted key-up, game focus, input safety, immediate stop and renderer. Never wait on an LLM.
- **Perception (~250–2000 ms adaptive):** CPU novelty/ROI and a budgeted local VLM only for admitted frames. Annotate uncertainty.
- **Learning (idle or between rounds):** deeper reasoning, benchmark practice, verified retrieval, cross-game skill transfer, Forge experiments and rollback.

An RTX 4060 with 8 GB VRAM should protect game rendering and voice before allocating intensive visual-model work.

### 3. Fast local intelligence should be benchmarked, not assumed
llama.cpp supports visual model inputs via multimodal support and its OpenAI-compatible server. The October 15, 2026 v0.7.0 release documents a host-memory MoE expert cache and speculative-decoding changes, but neither is a guaranteed win for STAR's model and GPU. Test CPU-only small VLMs, adaptive ROI VLM calls, prompt-cache reuse, quantization, model routing, and partial GPU offload with equal quality at controlled temperatures and seeds.

Measure p50/p95 capture→inference→cue, first audible audio, tokens/sec, memory/VRAM, game FPS, speech underruns, missed observations and false positives. Do not generalize synthetic CPU measurements into model or OBS results.

Sources:
- https://github.com/ggml-org/llama.cpp/blob/master/docs/multimodal.md
- https://github.com/ggml-org/llama.cpp/releases/tag/v0.7.0

### 4. Humanlike streaming is primarily conversational timing
LiveKit documents layered speech activity detection, end-of-turn decisions, adaptive interruptions, and local v1-mini turn detection. Kyutai Pocket TTS v4.0.0, released October 20, 2026, offers 18M/7M and experimental 2M English variants. This provides candidates for CPU-based short reactions, but voice consistency and laughter need direct listening tests. Live2D's physics/skinning can support STAR's flowing twin tails and ribbons when synced to actual audio and motion.

Humanlike behavior for STAR means listening before answering, occasionally being silent and focusing on a game, speaking briefly about events she really experienced, not repeating catchphrases, and keeping a distinct consistent persona. A truthful character can roleplay, but should not assert that fictional human memories or emotions are verified events. Respect viewer privacy, moderation, accessibility, reduced-motion settings and audience interruption.

Sources:
- https://docs.livekit.io/agents/logic/turns/turn-detector/
- https://docs.livekit.io/agents/logic/turns/tuning/
- https://github.com/kyutai-labs/pocket-tts/releases
- https://docs.live2d.com/en/cubism-editor-manual/physics-operation/

### 5. General knowledge and autonomous self-improvement
Use separate provenance stores for temporary sensor data, signed experience, sourced public research, and distilled verified procedural skills. Attach document date, license, provenance and revision to knowledge. Detect contradictions and stale claims rather than merely embedding more text. Let STAR invent harder tasks but keep evaluator answers out of the solver's context. Star Core Forge should run isolated candidate changes, independent held-out tests, resource measurements and local rollback. GitHub is optional outward publishing.

## Acceptance tests needed before enabling
- At least 50 varied consented HUD/scene/menu events plus adversarial in-game text and occlusions; report precision/recall, false commentary, and missed events.
- Windows capture-to-result p50/p95 and hardware FPS/VRAM telemetry with an actual approved Roblox Studio window, plus forced revocation/PID switch tests.
- End-to-end OBS, mic, voice and Live2D animation: first audio latency, interruption recovery, silent intervals, audible acknowledgements and physical mute on stop.
- Real unseen game objectives and independently asserted wins; controlled trials with withheld tests, never vision guesses as scores.
- Security audits: no global desktop fallback, prompt injection from on-screen text blocked, fresh approved capture only, offline and no external screenshot uploads.
- Full regression suite, native Windows hardware acceptance, and exact GitHub tree comparison before merge/deploy.

## What offline tests establish
Schema rejection, prompt-injection filtering by rejecting freeform payloads, source-frame stamp/dimension binding, revoked worker results discarded, replay and cooldown rejection, and stage-safe unverified cues. They do **not** show a VLM was installed, greater model intelligence, faster model inference, independent game mastery, or live VTuber performance.
