# Star Intelligence: fresh pre-playback control, faster game intelligence & natural VTuber behavior
**Research reviewed:** 2026-11-03. **Implementation branch:** `feat/star-verified-preplay-20261103-auto44`.
**Status:** offline code and regression tests; **not** a real Windows/OBS/voice/game rehearsal.

## 1. New engineering finding: TTS completion can invalidate an earlier decision to speak

Star already has an intelligent stream director and a debounced turn-taking adviser. However the original flow checked who was speaking when a turn was **prepared** and checked only timestamp and plan identity when the first audible PCM was **acknowledged**. Slow inference and speech synthesis can create a window during which the owner begins speaking, the game switches rounds, OBS becomes overloaded, or an urgent action begins.

**Change implemented here:**
- New `star/stream_preplay_fence.py`: typed `PreplayWitness` and deterministic `assess_preplay`; checks short-lived host-attested VAD turn, exact game scope, game-critical state, stream pressure and PCM readiness.
- Opt-in `StarStage.enable(require_preplay_witness=True)`; host must invoke `preplay_clearance` **after TTS is queued and immediately before the first actual PCM write**. Without a recent successful clearance, `acknowledge_audible` rejects and abandons the plan.
- Freshness: VAD/host snapshot at most 75 ms old at clearance, then at most 100 ms from clearance to host acknowledgement. Older plans are never revived. A confirmed owner barge-in or game-scope change abandons the queued speech instead of speaking a cut-off answer later. Existing non-opted-in hosts retain legacy behavior.
- This system is **not** cryptographic sensor verification, a voice model, a TTS engine, an OBS client, device output authorization, or a broadcast switch. The trusted host must continuously monitor interruptions and physically stop/flush PCM. An acknowledgement after sound begins is too late to retroactively prevent already-audible audio.
- Viewer text cannot supply host approval, VAD evidence or game scope. The one-way advice and metrics avoid retaining microphone, private chat, audio, screenshots, IDs or content.

**Source rationale:** Microsoft's *Proact-VL* (ICML 2026, published May 2026) specifically separates deciding **whether/when** to respond from generating the content of a gaming companion's commentary, and argues for keeping actual response latency inside the real-time budget. LiveKit's interruption design and 2026 issue reports also demonstrate the importance of distinguishing genuine speaking turns from false interruptions and stale playout. These are ideas and engineering evidence, **not** a claim that Star's naturalness has been measured.
- https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/
- https://github.com/livekit/agents-js/blob/main/agents/src/voice/turn_config/interruption.ts
- https://github.com/livekit/agents/issues/5359

## 2. Faster intelligence: separate reaction, tactics, learning and expression

**Proposed local runtime decomposition (not part of this patch):**
1. **Reflex path, deadline-driven:** cheap event detector or a small model makes short decisions under the scene deadline. It must only propose actions; owner-approved game-control and verified telemetry remain separate. Skip stale moves instead of completing impressive reasoning too late.
2. **Tactical path:** reason across a few short actions with compact state and a bounded inference budget; call asynchronously only when available slack exists.
3. **Slow teacher/practice path:** after active gaming, generate alternative plans, run safe trials, and evaluate held-out scenarios. Preserve failed attempts, not just success stories. Promote skills only with fresh independent evidence, diversity of game conditions, and measured transfer to another unseen case.
4. **Expression path:** concise speech and avatar gestures that do not occupy the game decision deadline or speak over others. Prefer independent CPU speech if it preserves GPU frame time on Star's 8 GiB cards.

**Why end-to-end timing matters:** GameScaling's Nov 1, 2026 ViZDoom correction revised its real-time scores from 16.4→11.5 and 13.2→8.5 after including screenshot capture, transfers, preprocessing, action and recording overheads and ensuring the game continued moving. Star's capture-to-action benchmark should be used as the *primary* performance report, with tokens/s secondary. The numbers are from the researchers' benchmark, not Star's machine.
- https://gamescaling.github.io/

**Speed experiment plan:** A/B unchanged baseline vs (a) cached prefix/KV with stable prompt sections, (b) small reactive model, (c) speculative decoding only when proven beneficial, (d) CPU TTS. Compare under **game + OBS + audio load** with the same scene seeds and clock. Record p50/p95 capture→action, p95 time to first *audible* PCM, qualified game progress and error rate, GPU memory high-water mark, OBS render/encoder drops, avatar-frame continuity and total watts if available. Blind or separately review any subjective voice-naturalness scores. Do not choose one optimization by peak token throughput.

**Important caveat:** llama.cpp's SPEED-Bench provides a repeatable methodology but speculative decoding does not always help; published 2026 reports show regressions on some Windows and model combinations. Benchmark the installed build, driver, quantization, context and workload with control/experiment pairs; disable by default until passing both speed and quality gates.
- https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md
- https://github.com/ggml-org/llama.cpp/issues/23052
- https://github.com/ggml-org/llama.cpp/issues/28220

## 3. Local VTuber speech and avatar

Kyutai's **Pocket TTS v4.0.0 (released October 20, 2026)** introduced small English models (~18.2M, 6.9M and 1.9M parameters, and REFL variations). **v4.0.1 (October 21, 2026)** contains fixes for the sub-20M versions. These are compelling *candidates*, not a recommendation to automatically replace Star's existing voice. Compare perceived clarity, consistent character timbre, fast first chunk, pronunciation, interruptions, CPU usage and actual audible-device latency.
- https://github.com/kyutai-labs/pocket-tts/releases
- https://github.com/kyutai-labs/pocket-tts

The most human-*like* experience is not maximum chatter. Star should let players speak, maintain conversational context across a natural back-and-forth, react only to verified gameplay, and use short expressive sentences or deliberately remain silent during tense gameplay. A user should be able to tell she's an AI VTuber, not be misled that she has a human identity, independent senses or unobserved experiences.

**Evaluation gates, experimental targets (not established results):**
- 0 owner voice-overlaps intentionally caused by delayed new PCM in a scripted sample of 100 pre-play turns; verified-quiet witnesses must be <=75 ms old.
- 0 stale-game narration during 100 forced round transitions while TTS is queued.
- No rise in verified game mistakes or OBS frame loss compared with current baseline while new voice system is enabled.
- Subjective naturalness scored by independent human review of paired recorded clips; preserve a deliberate-silence scenario, false-interruption scenario, and owner barge-in scenario.
- Avatar blink/gaze/mouth/speech cues must be evaluated on **decoded audio/video output**, not just rig request frames. Existing AV synchronization and output-QoE gates can provide complementary measurements.

## 4. Stronger game creation and general intelligence

Roblox released its built-in Studio MCP connector in March 2026 for external assistants and playtest automation. StudioTestService allows multi-client scripted testing; OpenGameEval evaluates stateful Roblox development agents in reproducible sessions, and reports that inspecting the affected game objects before editing correlates with better results.

**Recommended Star exercise loop:** inspect selected game objects and code → retrieve official API references → generate 4–8 alternative minimal patches → static analysis (Luau tooling) → unit and server/client Studio tests → screenshot/scene-quality checks → choose a tested candidate → record exact failure type and fix → compare with held-out tasks. Do not claim to have built/played a game based solely on generation; obtain independent run-and-observe receipts.
- https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643
- https://create.roblox.com/docs/reference/engine/classes/StudioTestService
- https://github.com/Roblox/open-game-eval

Add knowledge retrieval by **provenance and revision**: separately index official Roblox API dumps, community examples, local project artifacts and unverified viewer chat; retrieve only what is relevant; track source date and confidence; run a tool or test before converting a claim into memory. Prefer recoverable local snapshots and explicit rollback. Background learning should be paused under host-verified game/OBS load; a clever answer that causes encoder stalls is a regression.

## 5. Integration contract and missing real-world proof

For the **private nonbroadcast Windows rehearsal**, the trusted PC host must own all of:
- Continuous VAD with local monotonic timestamps; establish authenticated owner vs guest identity *outside* a speech model and cancel playback on real owner interruption.
- Original `StagePlan` identity, `queue_audio`, fresh `PreplayWitness`, and `preplay_clearance` immediately before physical PCM submission. A clearance is a **short-lived advisory**, not blanket streaming authorization. The host must handle physical stop, mute and rig reset if conditions change after the check.
- Owner-controlled game window and independently verified input release, signed engine observations and liveness watchdog, plus an emergency stop that doesn't depend on a blocked Python worker.
- Local authenticated OBS **read-only** monitoring; no broadcast or recording activation without separate owner approval. Record audible first PCM and output capture/AV for actual quality checks.
- Resource throttling that gives game frame deadlines, speech playout and OBS priority over optional training or heavy graphics generation.

**Today's scope:** new deterministic preplay fence and strict-mode stage integration, with simulated tests. There is **no measured speedup, human-equivalence proof, game-winning gain, audio quality gain or Windows hardware acceptance result** in this change. Keep strict mode off by default until the real native audio host supports the complete revalidation and cancellation sequence.

### Practical next milestones

1. Wire and test the strict preplay handshake with Star's Windows audio host, including intentionally delayed TTS and false/interrupted VAD; maintain a hard local mute and stop control.
2. Run a private 5–10 minute synthetic game + OBS + avatar session, capture actual device PCM and decoded AV, and produce an independent red/green quality report.
3. Compare 8 GB GPU local models and CPU speech under an identical capture-to-action workload; promote only independently verified improvements.
4. Run a reproducible Roblox Studio multiplayer build/test/repair task using a known failing project and a held-out scene for final validation.
