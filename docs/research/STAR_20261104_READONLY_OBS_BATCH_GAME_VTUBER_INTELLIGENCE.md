# STAR research: low-overhead OBS evidence and game/VTuber intelligence (2026-11-04)

Status: **offline-tested opt-in software, not a verified live OBS/Windows rehearsal**. No model weights were trained or measured to be smarter. Builds on the previous draft knowledge-graph repair.

## The implemented improvement

OBS WebSocket v5 supports RequestBatch (OpCode 8) and RequestBatchResponse (OpCode 9), with SerialRealtime execution (type 0) and haltOnFailure. Star's authenticated, localhost-only OBS status probe previously performed three serial socket request/response exchanges to obtain GetStats, GetStreamStatus and GetRecordStatus per sample. A new explicitly opt-in --batch-reads option obtains the same three measurements using one serial-realtime batch per sample. For three observations this reduces the **number of socket request/response exchanges from 9 to 3**, excluding authentication. It does not reduce the number of OBS read operations, and no real wall-clock speedup has yet been measured. Do not confuse fewer round trips with faster game FPS or smarter inference.

Only these three read-only request types may be sent. The gate rejects mismatched batch ID, missing/extra results, reorder, mismatched individual request IDs/types, failed results, active stream and inappropriate recording state. A stale result cannot become new evidence because existing request-ID and timestamp barriers remain active. The optional batch uses SerialRealtime rather than SerialFrame to avoid putting polling on the OBS graphics thread. The existing sequential path remains the default for compatibility.

To test on an explicitly authorized local OBS v5 machine, provide the OBS password securely via STAR_OBS_WEBSOCKET_PASSWORD in the trusted host environment (never in a model prompt or git), then run:

    python -m star.stream_obs_local_readonly_probe --observe --batch-reads --samples 3

For an independently started private OBS recording, --verify-private-recording and --verify-recording-progress can also be selected. These flags only observe and never start/stop recording. Nothing in this upgrade broadcasts, records, reads private audio/chat, drives games, installs software, or changes the GPU.

Sources: https://github.com/obsproject/obs-websocket/blob/master/docs/docs/partials/introduction.md ; https://github.com/obsproject/obs-websocket/blob/master/docs/generated/protocol.md ; https://github.com/obs-websocket-community-projects/obs-websocket-js/blob/master/src/types.ts . An OBS issue documents duration/timecode reporting zero despite other output counters, underscoring why file decoding is required after a rehearsal: https://github.com/obsproject/obs-studio/issues/9550 .

## Proposed intelligent streaming architecture

Star's ability to produce useful correct actions while a game renders and speech plays matters more than a maximal isolated tokens/s figure. Separate four cooperating loops:

1. **Frame-critical host loop**: real game-state timestamps, present-frame p95, signed input receipts and physical key release. This loop cannot wait for model research, cross-frame vision or a streaming service. Validate focus, game identity and data freshness before control.
2. **Speech/reactive loop**: quick moderation, priority selection, bounded model response, interruptible output, real PCM playout evidence and measured avatar lip motion. A generated sentence is NOT an audible utterance. If a viewer interrupts, stale speculative drafts are discarded.
3. **Tactical loop**: plans routes, next objectives, puzzle strategies and co-op play from verified observations; plans expire on scene change, death or timeout. It supplies suggestions, never unverified claims of success.
4. **Background loop**: source-grounded retrieval, game code generation, tools, Luau tests, offline learning and optional model training. This loop yields GPU/CPU memory to real game, OBS and voice on demand.

Benchmark pinned local model+quantization, real prompt lengths, context cache hit rate, hardware memory headroom, first audible response p50/p95, actual game action success, game-frame p95, audio underruns, OBS render/encoder misses, and sustained tail latency. Require successful decisions, no increase in erroneous action claims and no gameplay smoothness regression before promoting a faster configuration. Back up local configurations and retain rollback.

Kyutai Pocket TTS offers CPU-oriented streaming speech, with additional tiny English variants described in October 2026. Candidate only: compare pronunciation, voice identity, latency, licensing, CPU load and stream quality on the actual gaming PC; do NOT infer a hardware speedup from the vendor demonstration. Source: https://github.com/kyutai-labs/pocket-tts .

## Practical game-learning system

Start in approved private/owned game labs with bounded controls and repeatable resets. Instrument observations, permitted actions, actual tool dispatch, game engine feedback and host-signed outcomes. Train movement/camera/navigation first, then timing, combat, puzzles, cooperation and unfamiliar scenarios. Keep failure cause distinctions: perception, stale observation, model plan, late control, physics collision and environment reset.

Do not give skill credit merely for moving a key or a model reporting a win. Use signed, independent outcomes and precommitted unseen seeds. Balance candidate vs baseline turn order, block validation leakage, randomize maps and force evaluation on levels not practiced. Report confidence bounds and failure modes rather than a cherry-picked highlight. Existing Star components to join: game_action_outcome_feedback, game_practice_curriculum, game_holdout_schedule and game_transfer_eval. This PR does NOT add a new trained gameplay policy.

Roblox's official March/April 2026 Studio MCP + playtest agent allow build-test-repair workflows. Use them to inspect an actual project, modify Luau in controlled branches, run Studio playtests, inspect logs and game screenshots, and validate repairs. The Studio tool being connected is not sufficient proof of a polished game. Sources: https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643 and https://devforum.roblox.com/t/studio-beta-studio-assistant-mcp-playtest-agent/4566767 .

Unity ML-Agents' curriculum learning and environment-parameter randomization are useful for a local skill lab. Source: https://unity-technologies.github.io/ml-agents/Training-ML-Agents/ .

## Humanlike, but honest, VTuber performance

Star should be an engaging **clearly identified AI** personality, with natural pacing, selective silence, eye focus, subtle gestures, blinking, realistic laughter, short acknowledgements, well-timed interruptions and contextual humor tied to real gameplay. She should admit uncertainty and mistakes; she should remember concrete verified session experiences without inventing a human private life or pressuring viewers into dependence. Persist only privacy-scoped, owner-approved memory with provenance and expiration. Avoid reading raw viewer messages, secrets or unmoderated content aloud.

Microsoft's ICML 2026 Proact-VL studies proactive game commentary and guidance, including **when** to speak, **how much** to say and streaming perception. Its benchmark is useful for designing Star's naturalness experiments, but paper metrics do not demonstrate an actual improvement in Star. Source: https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/ and https://github.com/microsoft/AnthropomorphicIntelligence/tree/main/Proact-VL .

## The next measurable gates

**1 — Real OBS read-only batch parity.** With OBS already running in a local, authenticated, nonbroadcast test, compare sequential vs batch over at least 100 alternating windows. Require exactly matching stream/record activity interpretation, zero unapproved requests and no extra render/encoder misses. Measure median/p95 per-sample wall latency, not just socket message count. Keep batching off if parity cannot be demonstrated.

**2 — Full private Windows VTuber rehearsal.** Run an authorized test game, Star speech, animated avatar, OBS recording and hardware telemetry together. Do not make any public broadcast. Independently inspect the stopped recording with stream_private_rehearsal_audit_cli, check observable gameplay, audible speech, mouth alignment, event-to-comment grounding, frame p95 and dropped frames. Obtain owner review before any outward stream.

**3 — Actual gameplay competence.** Train on a distinct practice split and compare new policies on sealed unseen maps against a counterbalanced baseline. Retain signed observations, no holdout tuning and an explicit rollback decision.

**4 — Actual general intelligence and speed.** Evaluate source-grounded difficult questions, Luau/run-and-repair tasks, error correction and evidence-supported answers before/after measured model routing and prompt-cache optimizations. Do not confuse passing adapter tests with increasing model reasoning quality.

Read-only host inspection for this run: Windows Main has an RTX 3060 Ti (8192 MiB), about 5115 MiB free and 31% utilization in a single sample, plus FFmpeg/FFprobe. Process inventory found StudioMCP helpers but not a named OBS, Roblox Studio or VTube Studio process. No live full-stack rehearsal or benchmark was performed; this hardware snapshot is not a performance guarantee.

This branch is for draft review, with reversible changes and independent CI. No main branch or stream permissions should change automatically.
