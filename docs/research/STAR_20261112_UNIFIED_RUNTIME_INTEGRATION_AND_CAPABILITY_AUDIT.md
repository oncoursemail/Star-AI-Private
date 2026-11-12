# STAR Unified Runtime Integration & Capability Audit

**Research date:** 2026-11-12  
**Scope:** Existing source, open development PRs, streaming/voice, local inference, gaming, game creation, memory, general knowledge, Windows execution and safety.

This is an integration audit, not a claim that every capability described below is already running. It deliberately separates shipped functionality, source-level foundations, draft PR work, and hardware/application integrations that still need to be built and tested.

## Executive finding

STAR does not need another independent “brain” for every feature. The repository already contains a broad set of evaluators, policy modules, telemetry parsers, memory experiments, process supervision work, skill retrieval, and game/voice foundations. The largest remaining architectural gap is **runtime wiring**: trusted Windows observations and application adapters must feed one scheduler and execution supervisor, and their outcomes must flow back into a common evidence and learning system.

The next phase should therefore prioritize a **Unified Host Runtime** over adding more disconnected planners, schedulers, memories, or benchmark wrappers.

## Repository and release boundary

The source and development work inspected for this audit is in `oncoursemail/Star-AI-Project`. Its README points installers and public releases to `oncoursemail/Star-AI`; these are distinct repositories with different roles.

The source README describes STAR v1.0.0 as a Windows 11 local-first chat application. It explicitly labels Studio Lab, full Blender automation, and the richer voice path as coming-soon or opt-in work. Open PRs, CI artifacts, and source-only code are not part of the released installer until merged, packaged, and released.

**Do not silently change production defaults or claim that draft work is shipped.** Keep new host integrations opt-in until device, permissions, recovery, privacy, and mixed-workload tests pass.

## Existing work found in the source/PR inventory

The open development stack already contains much of the groundwork below. Treat these as existing work to integrate, not invitations to create duplicate subsystems.

| Area | Existing source / PR work observed | Integration still needed |
|---|---|---|
| Local inference | PR #1131 telemetry for llama.cpp; #1129 streaming first-content benchmark | Version-pinned provider adapter, mixed-load measurement, safe cache identity |
| Tracing | #1132 bounded trace ledger; #1133 runtime adapters; #1134 span profiler | One trace context across UI, model, tool, audio, game and avatar boundaries |
| Streaming evaluation | #1135 rehearsal gates; #1137 recorder; #1138 diagnostics; #1143 speed-vs-quality evaluation | Trusted host observations and real private rehearsal runs |
| Memory | #1136 temporal memory evaluation; #1109 continual-learning transfer evaluation; #1117 reversible consolidation proposals | Real task hosts, sealed holdouts, rollback and stale-evidence revalidation |
| Voice turn-taking | #1144 causal evaluator; #1145 calibration/holdout; #1146 one-use ledger; #1147 clustered evidence; #1148 conservative coverage | Real audio labels, multilingual and multiparty data, hardware timing |
| Resource policy | #1140 workload admission; #1142 bridge to stream pressure; #1123 game-control QoS; #1125 speech CPU reserve | Trusted CPU/RAM/VRAM/game/OBS/audio telemetry and a host dispatcher |
| OBS | #1149 GetStats parser; #1150 GetStreamStatus sampler | Authenticated local WebSocket client, reconnect lifecycle, device test |
| Playback | #1127/#1151 queued-vs-playback timing and callback meter isolation | WASAPI/IAudioClock correlation, acoustic/remote measurement, avatar calibration |
| Process safety | #1118 Windows Job Object process-tree containment; #1119 suspended assignment; #1120 bounded shutdown | Unified supervisor integration, restart policy, resource accounting |
| Skills and tools | #1121 cached BM25 skill retrieval; #1114/#1115 artifact staging and promotion | Skill execution provenance, compatibility checks and outcome-based retrieval |
| Game/social context | #1103 event timeline; #1107 multiparty floor evidence; #1139 cross-session practice continuity | Real game/stream adapters and consent-aware event ingestion |
| Home/persona | #1122 idempotent affect events | Keep expressive state grounded in events; no duplicated or fabricated reactions |

The table describes the inspected PR inventory and does not imply those PRs are merged or shipped.

## Target architecture: one runtime, multiple specialized loops

```text
                 WINDOWS HOST ADAPTER
       CPU / RAM / VRAM / devices / game / OBS / audio
                         |
                  TRUSTED OBSERVATION BUS
             timestamps + source + epoch + quality
                         |
                  UNIFIED TRACE CONTEXT
                         |
                DEADLINE-AWARE SCHEDULER
          admission / QoS / cancellation / budgets
                         |
                EXECUTION SUPERVISOR
       process trees / leases / restart / cleanup / logs
                         |
        +----------------+-------------------+
        |                |                   |
   FAST REACTIVE     DEEP PLANNER        CREATOR / RESEARCH
   voice/game loop   long-horizon loop   tools and sandboxes
        |                |                   |
        +----------------+-------------------+
                         |
               VERIFIED OUTCOME LEDGER
         tests / game state / playback / source evidence
                         |
              MEMORY + SKILL PROMOTION GATE
          provenance / freshness / transfer / rollback
```

### Runtime invariants

1. **One monotonic host clock per observation domain.** Record wall-clock time only for human-readable logs; use monotonic clocks for durations. Rotate epochs on process, device, stream, game-session or model restart.
2. **Every observation has provenance.** Include source, schema version, timestamp, epoch, validity and freshness. Unknown is not zero; stale is not current.
3. **Separate policy from actuation.** Admission and QoS decide whether work may run; only the execution supervisor dispatches it. A parser or evaluator must never be mistaken for a live adapter.
4. **Deadlines beat queue order.** Voice capture/playback and game-control actions have bounded deadlines. Background research, indexing, training and asset generation yield when interactive work is under pressure.
5. **No unbounded queues.** Audio, frames, traces, events, tool requests and background tasks need explicit capacity, expiry, overflow accounting and cancellation.
6. **Every long task is recoverable.** Persist task identity, lease, checkpoint, artifacts and last verified state. On restart, reconcile before resuming; do not replay non-idempotent external actions blindly.
7. **Evidence precedes learning.** A successful-looking response, screenshot or generated script is not proof of success. Require engine/test state, playback evidence, or source-grounded verification.

## Speed and intelligence: benchmark the complete path

### Local inference

Use the existing llama.cpp telemetry and streaming benchmark as the base. Pin the exact server build, model hash, quantization, context, prompt template, sampler, thread counts, GPU offload, slot count, and request concurrency for every run.

Measure separately:

- Prompt/prefill time and prompt tokens per second.
- Time to first token (TTFT).
- Time to second token and inter-token latency.
- Output tokens per second.
- End-to-end completion latency.
- First audible speech, not only first generated text.
- Tool latency and total agent critical-path time.
- CPU, RAM, VRAM, GPU utilization, queue wait, and model load/cold-start time.

Run paired baseline/candidate tests with identical prompts and a fixed quality grader. Include cold start, warm prefix, long context, multi-request concurrency, and mixed load with a game + OBS + audio + avatar. Report p50/p95 and error rates. Reject a speed change if it degrades task accuracy, factuality, interruption behavior, or game-control safety.

**Prefix/KV cache:** keep stable system instructions and tool schemas at the front of the prompt; keep changing user/context data after them. Cache identity must include model and tokenizer digest, adapter/LoRA selection, prompt-template version, tool schema, policy version and relevant multimodal configuration. Do not share cache state across incompatible adapters or tenants. The upstream llama.cpp issue tracker has documented cache-correctness reports under concurrent and adapter-switched workloads; pin versions, add cross-session contamination tests, and disable cross-slot/RAM cache paths if a tested build cannot prove isolation.

**Speculative decoding:** evaluate draft-model, n-gram and supported assisted modes per task family. A high draft-acceptance percentage is not itself an end-to-end win. Keep it only when TTFT/inter-token/end-to-end latency improve without quality regressions and without starving GPU memory needed by the game or avatar.

**Hardware strategy:** the target consumer GPU has 8 GB VRAM. Profile CPU/RAM and GPU together; do not copy H100/H200/B200/RTX 5090 settings into STAR. Use smaller quantized fast models for speech classification, routing, short acknowledgements and reactive decisions; reserve larger/deeper models for asynchronous planning, code review, research and complex creator tasks. Route by measured capability and deadline, not by model name alone.

### Voice and streaming

Use a causal full-duplex pipeline:

1. Capture microphone frames with device timestamps.
2. Run VAD and streaming ASR without waiting for a complete utterance.
3. Track speaker identity and conversational floor separately from transcript content.
4. Predict end-of-turn and interruption with calibrated uncertainty.
5. Start speculative reasoning only when it can be cancelled safely.
6. Stream TTS in short, speakable chunks.
7. Schedule the avatar from the actual output timeline.
8. Record callback/DAC/loopback evidence and distinguish it from acoustic arrival and remote viewer receipt.

Do not collapse these stages into one “response latency” metric. TurnBench shows that end-of-turn and interruption quality must be measured separately and that backchannel-dense conversation styles increase false interruptions. MP-Bench exposes a major multiparty gap: evaluated real-time agents reached at most 22% multiparty comprehension and near-chance turn-taking. STAR needs a social-floor model, not just diarization.

For streaming realism, measure:
- EOT recall, false cutoff rate, missed-final rate and detection latency.
- Interruption recall, false interruption rate and recovery quality.
- Response appropriateness and silence preservation.
- Multiparty comprehension and correct addressee selection.
- First audible response p50/p95 and total speech completion.
- Prosody, volume, disfluency handling and long-conversation grounding.

The character can be expressive and conversational without claiming to be biologically human. Keep viewer recording and persistent profiles consent-based and minimal.

### Windows audio and avatar

WASAPI loopback can capture the audio mix rendered by a shared-mode endpoint. It is useful for verifying what reached the Windows audio engine, but it is not proof of what a remote viewer heard or what sound pressure reached a room microphone. Correlate device position/QPC or IAudioClock with the host monotonic clock, handle device invalidation and endpoint changes, and rotate the audio-route epoch.

Use MMCSS only for dedicated capture/render workers after Windows profiling; do not raise the entire STAR process priority. Audio buffers should be selected from the actual endpoint's supported periods, not from an arbitrary “smallest possible” value.

For Live2D/VTube Studio:
- Require the user to approve the plugin in VTube Studio.
- Store the returned token in Windows Credential Manager or an equivalent OS secret store.
- Connect only to loopback by default; make the port configurable; never expose the API on a public interface.
- Subscribe to events rather than polling every frame.
- Allowlist parameter IDs and hotkeys; rate-limit injection and reconnect safely.
- Drive mouth parameters from TTS phoneme/viseme timing when available, with smoothed audio amplitude as a fallback.
- Keep eyes, gaze, blinking, body, hair physics, expressions and gestures as separate animation layers.
- Add a neutral/listening state and motion cooldowns to avoid repetitive or overactive animation.

### Gaming and skill acquisition

Use two coordinated loops:

**Reactive controller (hard deadline):** fresh frame/state observation, small action horizon, action gate, action execution, next-frame verification. It handles movement, aiming, dodging, camera, interaction and immediate hazards.

**Strategic learner (asynchronous):** objectives, map model, mechanics, route planning, practice curriculum, skill retrieval, post-run critique and transfer probes. It must never block the reactive controller.

Borrow the strongest ideas from SIMA 2 and Voyager:
- Translate natural-language objectives into observable subgoals.
- Build an automatic curriculum from the current failure frontier.
- Save executable, composable skills with prerequisites and supported game versions.
- Attach each skill to the environment fingerprint, preconditions, action bounds, expected state changes, counterexamples and verification tests.
- Replay skills in a sandbox, then test on a held-out map or altered situation before promoting.
- Track success rate, completion time, deaths/failures, resource efficiency, action latency and transfer performance.

Do not mark a skill “mastered” because it succeeded once. Require repeated success across independent seeds/maps and a holdout challenge. For multiplayer, keep player-impacting actions, account actions and external communications behind explicit permission scopes.

### Game creation

OpenGameEval's 2026 Roblox Studio benchmark provides a direct lesson: separate observation from editing and inspect all relevant objects before modifying them. Its paper reports higher task pass rates when agents inspect the objects their solution will touch. GameDevBench shows that visual/image feedback improves agentic game-development results; code-only grading misses scene, animation, shader, UI and gameplay errors.

STAR Creator should follow:

```text
inspect project -> map dependencies -> plan acceptance criteria
 -> implement small change -> compile/analyze -> launch engine
 -> inspect scene/screenshots -> simulate player actions
 -> assert game-state outcomes -> repair -> rerun regression
 -> save verified artifact + provenance
```

Use Roblox Studio test places and engine-side assertions for Roblox. Use Godot/Unity test scenes and deterministic input replay where supported. Keep asset generation, import, rigging, animation, collision, camera and UI checks in separate validators. A project is complete only when the acceptance criteria pass in a playable build.

### General knowledge and memory

Keep memory types distinct:
- Working: current task and near-term state.
- Episodic: verified prior interactions and experiments.
- Semantic: stable facts and concepts with sources.
- Procedural: executable skills and workflows.
- Temporal: facts that change and need expiry/revalidation.
- Project/world models: entities, dependencies, state and relationships.

Each stored item should carry source/provenance, observation time, valid-from/to or expiry, confidence, scope, privacy class, model/tool version and verification status. Retrieval should prefer relevant, current evidence; stale repository symbols, game APIs, prices, documentation and user instructions must be revalidated before action.

Evaluate memory by whether it improves future task completion, transfer and decision quality—not by recall QA alone. Run paired memory-on/off campaigns with identical model, prompt, tool policy, context budget and tasks. Include independent interference tasks to detect memory-induced regressions. Promote consolidations only through reversible, owner-reviewable gates.

For general knowledge, build source-grounded learning packs: question -> primary sources -> extracted claims -> contradiction check -> short explanation -> quiz/task -> delayed retrieval -> applied project challenge. Track factual accuracy, source freshness, uncertainty calibration, transfer and retention.

## Unified scheduler priorities

Recommended default priority classes (policy proposal; do not enable until host measurements exist):

| Priority | Work | Behavior under pressure |
|---|---|---|
| P0 | Audio capture/render, safety stop, active game-control deadline | Reserved capacity; never wait behind background jobs |
| P1 | Turn detection, first response, avatar output, active UI/game observation | Short bounded jobs; preempt/cancel speculative work |
| P2 | Current conversation reasoning, tool call needed for the live task | Deadline-aware; cap concurrency and context |
| P3 | Strategic game planning, code generation, scene analysis | Async; checkpoint and yield |
| P4 | Research, indexing, memory consolidation, practice generation, model experiments | Run only with spare resources; resumable |

Admission must account for CPU, RAM, VRAM, audio backlog, game frame-time p95/p99, OBS render/encode/network state, and task deadlines. Never infer resource health from a single GPU-utilization number.

## Security, privacy and autonomy

- Keep local application adapters loopback-only by default.
- Keep tokens in OS secret storage; never log credentials or raw audio/video.
- Use explicit per-application scopes and owner-visible toggles.
- Use read-only inspection before edit-capable tools.
- Execute generated code in isolated workspaces with bounded CPU, memory, disk, time and process trees.
- Require owner approval for publishing, monetization, purchases, account changes, external messages, destructive edits, live player-data writes and other irreversible/high-impact actions.
- Routine reversible maintenance can be autonomous when policy and audit trail are explicit.
- Keep raw viewer audio/video retention off by default; retain aggregate metrics and consented, short-lived debugging samples only.
- All agent actions should have a trace ID, authorization decision, precondition, result and rollback path.

## Next implementation sequence

### Phase A — Stabilize the current development stack
1. Resolve the current PR #1151 Pyright and offline regression failures.
2. Require full CI on the exact head.
3. Keep the stacked PR chain draft until its parent/child dependencies are understood.
4. Update the release status table only after merge, packaging and Windows validation.

### Phase B — Real Windows host runtime
1. Implement a read-only Windows Host Adapter for CPU, RAM, VRAM, process tree, device identity and game/OBS health.
2. Add WASAPI loopback and audio-route epochs; report engine output separately from acoustic and remote receipt.
3. Connect OBS WebSocket with local authentication, reconnect and read-only scopes first.
4. Wire the existing resource admission policy to real telemetry; then let the existing supervisor dispatch bounded worker processes.
5. Add a mixed-workload private rehearsal runner with reproducible manifests and aggregate-only reports.

### Phase C — Natural VTuber
1. Complete a user-approved VTube Studio WebSocket adapter.
2. Synchronize visemes/expressions to playback time.
3. Add multiparty social-floor and addressee selection.
4. Run TurnBench-style EOT/interruption tests and MP-Bench-style group scenarios.
5. Test long streams for repetitive behavior, silence preservation, voice/avatar drift and recovery after device or OBS restart.

### Phase D — Gamer and Creator
1. Wire game observation and gated input to a fresh-frame closed loop.
2. Build a verified skill schema and held-out transfer harness.
3. Add Roblox OpenGameEval tasks to the Studio Lab regression suite.
4. Add visual feedback and playtesting to game creation.
5. Expand cross-engine creator tasks only after Roblox tasks have deterministic acceptance checks.

### Phase E — Knowledge and continual improvement
1. Connect existing knowledge and memory evaluators to real task hosts.
2. Add source freshness, provenance and stale-evidence invalidation.
3. Run paired memory-on/off and skill-transfer campaigns.
4. Promote lessons only after independent verification and reversible review.

## Release gates

A capability is not “done” until:
- Its real adapter is connected and reconnects after process/device restart.
- Unit, integration and Windows hardware tests pass.
- Mixed workload does not violate P0 latency or game-frame budgets.
- Privacy and permission scopes are reviewed.
- Failure, timeout, cancellation and rollback are tested.
- Performance and quality are compared against a pinned baseline.
- Documentation clearly states whether it is available, opt-in, experimental or coming soon.

## Primary research and implementation sources

- llama.cpp server prompt caching and timing: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md
- llama.cpp SPEED-Bench: https://github.com/ggml-org/llama.cpp/tree/master/tools/server/bench/speed-bench
- llama.cpp speculative decoding: https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md
- llama.cpp cache correctness reports (examples): https://github.com/ggml-org/llama.cpp/issues/27148 and https://github.com/ggml-org/llama.cpp/issues/26207
- OpenTelemetry GenAI metrics: https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-metrics.md
- Microsoft WASAPI loopback: https://learn.microsoft.com/en-us/windows/win32/coreaudio/loopback-recording
- Microsoft WASAPI overview: https://learn.microsoft.com/en-us/windows/win32/coreaudio/wasapi
- Microsoft MMCSS: https://learn.microsoft.com/en-us/windows/win32/procthread/multimedia-class-scheduler-service
- VTube Studio API: https://github.com/DenchiSoft/VTubeStudio
- Live2D Cubism lip-sync: https://docs.live2d.com/en/cubism-sdk-manual/lipsync/
- TurnBench paper and leaderboard: https://arxiv.org/abs/2608.25218 and https://turnbench.sesame.com/
- MP-Bench (Findings of EMNLP 2026): https://aclanthology.org/2026.findings-emnlp.1437/
- SIMA 2 (Google DeepMind): https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/
- Voyager: https://arxiv.org/abs/2305.16291 and https://voyager.minedojo.org/
- OpenGameEval (Roblox): https://arxiv.org/abs/2610.02563 and https://github.com/Roblox/open-game-eval
- GameDevBench: https://github.com/waynchi/gamedevbench
- MemoryArena: https://arxiv.org/abs/2602.16313

## Explicit limitations

This document is a research and integration plan. It does not claim that the Windows Host Adapter, WASAPI loopback, VTube Studio bridge, real-time social brain, autonomous gameplay loop, or cross-engine creator pipeline has been implemented or hardware-tested. It does not claim human consciousness, human-equivalent behavior, measured inference speedup, game mastery, or a production-ready autonomous streamer.
