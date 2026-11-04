# STAR — OS-verified last-mile VTuber output, speed and game intelligence
**Research and implementation note — 2026-11-04.** Stacked on draft PR #968. New work is **opt-in** and **not a completed game/OBS/voice rehearsal**.

## Concrete problem and change
The worker-epoch reply fence checks that a model answer belongs to the current *registered* worker, while the host OS supervisor checks that the *real operating-system process* still matches its verified executable. Until now, those checks were independent. An old queued speech segment could pass the registry check if its worker had died but no new OS observation had arrived. The missing step was an explicit **last-mile composition**.

Added `HostLiveOutputGate`, which always calls `HostOSWorkerSupervisor.refresh(epoch)` immediately before `HostWorkerReplyFence.claim(...)`. The gate obtains a trusted monotonic timestamp only **after** the OS process refresh, avoiding caller-supplied timestamps that could backdate a slow probe. Failure cancels the one-shot receipt; a restarted, dead, reused-PID, zombie or modified-executable worker cannot have a previously queued answer marked eligible. A new `HostWorkerReplyFence.cancel(permit)` is identity-bound, cannot evict another permit by copying its fields, and `clear_pending()` flushes pending eligibility on gate disable. Tests cover the combined path and preserve the independent older tests.

**Truth boundary:** this still never plays PCM, verifies the actual weights currently resident in memory, attests the game's screen, reads OBS, or grants a stream or mic permission. The returned booleans `authorizes_audio` and `authorizes_broadcast` are always false. OS processes can exit between the last probe and real audio delivery. The trusted Windows launcher must own the process handles and call this gate, then enforce the existing preplay turn-taking, audio queue cancellation, audible device acknowledgments and OBS nonbroadcast-state checks. No model/chat/viewer-controlled PID, path, receipt or enable call.

## Findings prioritized by measurable impact

### 1. Real-time intelligence: correct results per second, not tokens per second
- Separate **reactive** low-cost frame/game-state loops from **tactical** choices and **slow reflective** research. Skip deep reasoning during control deadlines. Isolate inference latency calibration by actual workload class (idle, game, stream, game+stream) and exact live model worker epoch. See existing `AdaptiveQoS`, `HostWorkerEpochRegistry` and `HostOSWorkerSupervisor`.
- GPU memory headroom matters more than instantaneous utilization on an 8 GiB GPU; cache and context usage are workload-dependent. Test explicit workload admission reservations; do not allocate a second GPU TTS/VLM based solely on idle utilization. Use CPU speech conditionally if CPU generation meets target.
- Benchmark candidate draft models, speculative decoding and KV-prefix reuse on the *same prompts and exact deployment* against a non-speculative baseline, and verify response correctness. Key SLOs to **measure**, not assert: capture-to-decision p50/p95, voice first-audible-sample p95, token throughput, tokens accepted by draft, GPU peak VRAM, game p1 FPS, TTS dropped/canceled ratio, and response correctness in hidden holdout tasks.
- Run quality regression checks after model update or worker restart. Profiling must include simultaneous OBS local recording, avatar and gameplay to avoid passing an idle-only benchmark.

### 2. Playing games well: external outcomes, purposeful practice, unseen maps
A game agent should acquire verified sensor/action/outcome evidence, not reward itself for saying it succeeded.
1. On an owner-authorized private test environment, define a concrete skill (jump timing, navigation, combat aim, crafting, co-op communication) and a measurable objective.
2. Reproduce an episode with game version, inputs, frame timestamps, OS input-release acknowledgments, game-state observations, verified result and known failure modes. Never infer a win from generated commentary.
3. Review a small failed clip *off the real-time gameplay path*, compare 2–4 candidate policies, run structured practice, and promote a policy only if blind success-rate and tail-latency both improve.
4. Maintain separate practice and holdout splits, reset the game state independently, and score **wins and mistakes on unseen layouts**, recovery from interrupted inputs, response-time violations, and transfer to another game.
5. Curriculum generator should introduce harder variations only after sustained evidence, not just a single success. Keep policy rollbacks and never test against non-consenting players or anti-cheat systems.

**Roblox** officially introduced built-in Studio MCP on March 5, 2026 with test control and input simulation. The April 9 playtest-agent beta is relevant for simple validation, not proof of universal game-playing competence. OpenGameEval (October 2026) uses real stateful Studio tasks and executable outcome checks; model performance correlates with inspecting scene objects before editing. STAR should run inspection -> implement -> playtest -> verify -> rollback, not text-only code generation.

### 3. Humanlike VTuber behavior: event-grounded and genuinely conversational
Star can be a distinctive AI performer without falsely claiming human childhood or consciousness.
- **Timing and silence**: Microsoft Proact-VL (ICML 2026, released code March 16) evaluates proactive gaming commentary. Use utility-vs-distraction decisions: speak when observed events warrant it, remain quiet during high-risk gameplay, cut off obsolete sentences when input or game state changes. Measure irrelevant commentary, repetition and interruptions.
- **Turn-taking**: Microsoft's March 2026 RESPOND work emphasizes short listening acknowledgments and controllable proactive entries. Treat backchannels separately from full utterances, and prioritize an actual speaking viewer. No random filler.
- **Embodiment**: Sync mouth and facial action to PCM actually emitted, not planned speech. Make head/eye/tail movements subtle during listening, stable in critical moments, and respect reduced-motion settings. Avoid interpreting chat sentiment as a viewer's emotional state.
- **Long-term persona**: STAR should remember verifiable game episodes, favorite activities, recurring co-creations and chosen personal goals with source provenance and user consent. Distinguish lore from actual experiences, allow correction, and avoid collecting unnecessary viewer identifiers. Local-first session memory and owner-configurable retention.
- **Voice**: Kyutai's Pocket TTS is a plausible CPU candidate; compare cold/warm first-chunk, interruptions, expressiveness and pronunciation on Main's actual CPU. Do not assume every CPU model is faster or more natural.
- **Streaming**: OBS's bundled WebSocket since OBS 28 can report status, but auth must be enabled. Use nonbroadcast recording for acceptance; never treat an OBS process existing as evidence that a frame, audio sample or local recording happened.

### 4. Expand beyond gaming
Build a unified retrieval library with versions and provenance: Roblox Creator Docs, Luau language tooling, engine API dumps, local project files, approved reference examples, and domain-specific docs for Blender, Rust, Python, graphics, physics and audio. Feed verified worked examples rather than untrusted webpage instructions. Maintain semantic task memory, scratchpad/research memory, and long-term signed lesson memory separately. Uncertain facts need citations or tests. Route cheap deterministic tasks to tools and escalate only when measured failure risk justifies it.

For autonomous game creation, add an iterative visual evaluation loop with side-by-side before/after screenshots, geometry and hand-grip validation, testable physics/lighting constraints, multiplayer trials and a reproducible project revision. Run scene inspection and Luau/static checks before editing. Consider a nightly set of increasingly difficult closed-lab build-and-play challenges, with final acceptance controlled by independent engine results.

## Last-mile Windows rehearsal acceptance — missing today
The next milestone must produce ONE complete, local, private, reproducible episode. Initial proposed gates (targets, not current measurements):
- Single owner-pinned game executable and verified model worker, reproducible game state and game build; no public matchmaking required.
- OBS and avatar running; OBS proves recording active **and streaming inactive** through authenticated read-only requests; one local recorded clip with independent playback verification.
- Captured video-frame evidence timestamped, vision inference matched to game state, real game input physically released after every action, win/failure explicitly verified by the game (or honest unknown).
- OS worker refreshed immediately before eligible generated reply, correct voice epoch, playback gate, audio sample/buffer acknowledged at the actual sink; no stale output after restart.
- Per-stage p50/p95 latency, missed deadlines, GPU+CPU headroom, game p1 frame-time, voice first-audible-sample latency, action success and false-claim rates.
- Real observer listens to 10+ turns, including overlapping chat and silent gameplay, and rates natural timing, clarity, nonintrusiveness, consistent persona and actual interruption behavior.
- Recovery drills: kill worker, restart it with same PID if possible, remove audio device, OBS stop, stale game frame, changed app version, corrupt artifact, backward clock. No unattended broadcast or input after any failure.
- No merge until all stacked PRs independently pass CI, integration on actual Windows worker host is reviewed, and a private rehearsal passes.

## Primary references (verified on November 4, 2026)
- Roblox Studio built-in MCP, March 5, 2026: https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643
- Roblox Studio playtest agent beta, April 9, 2026: https://devforum.roblox.com/t/studio-beta-studio-assistant-mcp-playtest-agent/4566767
- Roblox OpenGameEval, paper submitted October 1, 2026 and official repo: https://arxiv.org/abs/2610.02563 and https://github.com/Roblox/open-game-eval
- Microsoft Proact-VL, ICML 2026: https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/
- Microsoft RESPOND, March 2026: https://www.microsoft.com/en-us/research/publication/respond-responsive-engagement-strategy-for-predictive-orchestration-and-dialogue/
- Official Kyutai Pocket TTS: https://github.com/kyutai-labs/pocket-tts
- Official OBS WebSocket: https://github.com/obsproject/obs-websocket ; https://obsproject.com/kb/remote-control-guide
- Official llama.cpp: https://github.com/ggml-org/llama.cpp

## Implementation status
Committed scope: real OS liveness/reply-fence composition and cancellation primitives with isolated deterministic tests, all OFF by default. Not implemented this run: model architecture changes, neural training, OS/game input integration, new avatar rig, real OBS recording, a live broadcast, a performance speedup, or a claim of greater model intelligence. Keep draft, stacked on #968; verify CI before merge.
