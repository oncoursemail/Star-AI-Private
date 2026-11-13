# STAR Task Coordination, Memory-to-Action, and Unified Intelligence Research

**Research date:** 2026-11-13  
**Implementation branch:** feat/task-communication-ledger-20261113-run20  
**Parent branch:** feat/stream-host-session-20261113-run19 (draft PR #1176)

## Executive decision

STAR needs one durable source of truth for the work she is doing and the results she has actually communicated. A chat transcript is not a task system; generated text is not proof that work completed; generated audio is not proof that a viewer heard it.

This change introduces an opt-in SQLite task ledger with explicit state transitions, worker leases, generation fencing, checkpoints, evidence references, durable report obligations, and actual-playback acknowledgement.

The ledger is a coordination primitive. It is not a model, agent, permission system, tool executor, or automatic self-modifier. The desktop host and orchestrator must integrate it in a later stage.

## Research findings that directly affect STAR

### Joi-Bench-Task — 9 November 2026

Paper: https://arxiv.org/abs/2611.12118

This benchmark evaluates whether a full-duplex voice agent tracks four different facts while conversation and work change:
1. what work is executing;
2. what has completed;
3. what has already been communicated;
4. what remains to be reported.

Its interactive simulator changes or withdraws requests during tool execution and interrupts spoken result delivery. In its evaluation of five commercial voice agents, the best result-completion rate under request changes was 55%; four of five agents had average information-omission rates of at least 23% after interruption.

**STAR implication:** task completion and communication completion must be separate. A build can finish while STAR is answering a viewer, and its report can remain queued. An interrupted utterance must not be marked delivered merely because TTS generated it.

### InteractionBench — 2 November 2026

Paper: https://arxiv.org/abs/2611.02430

InteractionBench measures conversational timing, spoken-task accuracy, whisper/volume control, and groundedness across conversations longer than twenty turns. It includes 221 items across thirteen scenarios and measures timing at the client-heard boundary.

**STAR implication:** do not call server first-token latency the time a viewer heard STAR. Instrument model TTFT, first TTS chunk, scheduled playback, and audible client/loopback onset separately. Evaluate social timing and factual grounding separately.

### MP-Bench and Full-Duplex-Bench v3

- MP-Bench: https://www.fullduplex.ai/benchmarks/mp-bench
- Full-Duplex-Bench v3: https://www.fullduplex.ai/benchmarks/fdb-v3
- Research: https://arxiv.org/abs/2604.04847

These benchmarks evaluate turn-taking, response appropriateness, real speech disfluencies, interruptions, and multi-step tool-use scenarios.

**STAR implication:** test whether a request is directed to STAR, whether a speaker is addressing another viewer, whether a backchannel should be ignored, and whether an interruption is warranted. More responses do not automatically mean better social behavior.

## Implemented: durable task coordination ledger

### Source files

- star/task_coordination.py
- tests/test_task_coordination.py
- benchmarks/task_coordination_bench.py

### State model

PROPOSED -> ACCEPTED -> RUNNING -> COMPLETED

PROPOSED / ACCEPTED / RUNNING / BLOCKED can be cancelled where allowed. RUNNING can become BLOCKED. BLOCKED or COMPLETED can be retried into a new generation. RUNNING is entered only through an atomic worker claim, not a generic status update.

### Worker leases and generation fencing

Each claim includes a bounded worker identifier, an opaque lease token, a UTC Unix expiry, and the current task generation.

The database stores only a SHA-256 digest of the lease token. The raw token is returned to the claimant and is not included in the public TaskRecord representation.

An expired RUNNING task can be reclaimed. Reclaim increments the generation before returning the new claim. A late worker from the old generation cannot checkpoint, renew, block, or complete the task.

Use UTC Unix timestamps for persisted leases. Do not persist monotonic-clock values because monotonic epochs are not stable across process restarts or machines. Voice-session timing should continue to use monotonic clocks.

### Verified completion

A task cannot transition to COMPLETED without both:
- result_ref: an opaque reference to the produced artifact/result;
- evidence_ref: an opaque reference to verification evidence.

The ledger does not inspect the artifact or prove that a test was meaningful. The orchestrator must create evidence only after the relevant evaluator or engine check succeeds.

### Communication is a separate obligation

A report stores references to content and evidence; it does not store spoken text or raw viewer transcripts.

A report remains QUEUED until the host receives actual playback acknowledgement and calls mark_report_played. Model generation, TTS submission, or text emission alone must not mark a report delivered.

If a task is retried, reports from the prior generation are excluded from the pending queue. A stale worker or stale playback acknowledgement cannot mark a newer generation as communicated.

Current acknowledgement granularity is report-level. The future speech adapter should split long reports into sentence-sized segments and acknowledge each only after its actual playback boundary. Exact word-level resume requires TTS alignment or client playback acknowledgements and is not claimed by this module.

### Durability and bounds

- Explicit SQLite path required; no implicit global database.
- WAL mode for file-backed databases.
- BEGIN IMMEDIATE serializes cross-connection claims.
- One connection per ledger instance is protected by an RLock.
- Default caps: 10,000 tasks, 10,000 reports, 8,192 recent events.
- IDs, titles, references, and list sizes are bounded.
- Task/event/report records contain references and state, not raw PCM, voiceprints, viewer profiles, credentials, or chat transcripts.
- Capacity is fail-closed: new rows are rejected rather than silently evicting active obligations.

The desktop host must choose the database path, access controls, backup policy, retention/rotation policy, and whether a task should be persisted. Never put the database in a synchronized/public repository or upload it to GitHub.

## How STAR should use this across capabilities

### VTuber and Social Brain

1. A consented audio/chat adapter receives an event.
2. ASR produces provisional captions separately from finalized utterances.
3. Speaker, addressee, and intent classification runs on finalized data.
4. RoomStreamHost applies source consent, moderation, rate limits, and bounded payload rules.
5. The Social Director decides respond, continue, queue, ignore, wait, or interrupt.
6. Only a user-authorized task may be promoted into durable work; viewer text alone never grants tool permission.
7. STAR's voice pipeline produces audio.
8. The playback adapter acknowledges what was actually played.
9. Only then does the ledger mark the corresponding report as communicated.
10. Live2D expressions and captions follow actual playback, not generated text.

Do not turn every chat message into a persistent task. Direct viewer requests should be ephemeral unless the stream owner explicitly enables a policy that promotes selected requests. The host must distinguish casual conversation from a durable work obligation.

### Gamer Brain

- Use a fast perception/control loop for immediate movement and input.
- Use a slower planner for objectives, routes, inventory, and strategy.
- Save checkpoints at safe boundaries.
- Record a task as complete only after game-state evidence confirms the objective.
- Treat a failed run as experience, not as a verified skill.
- Retest learned skills on held-out maps, seeds, or scenarios before promotion.

### Creator Brain

- Inspect project structure and current scene before editing.
- Use a task generation for each planned implementation attempt.
- Save checkpoints before risky multi-file edits.
- Compile, lint, and test in an isolated workspace.
- Launch the engine and inspect actual visual/gameplay output.
- Store screenshot, video, and test-result references as evidence.
- Require save/reload and end-to-end gameplay checks before marking a milestone complete.

### Knowledge Brain

- Store source provenance, retrieval time, confidence, and expiry for time-sensitive facts.
- Reconcile contradictions instead of appending every new claim.
- Keep model-generated hypotheses distinct from verified facts.
- Use memory to ground future task parameters, not merely to repeat old conversations.
- Preserve a correction path so obsolete facts do not silently influence actions.

## Memory-to-action research

### Mem2ActBench — ACL 2026

https://aclanthology.org/2026.acl-long.370/

Mem2ActBench contains 2,029 multi-session histories and 400 tool-use tasks. Its human evaluation found that 91.3% of tasks strongly depend on memory. It evaluates whether remembered context correctly grounds tool choice and parameters.

**STAR implication:** evaluate whether retrieved project constraints and prior decisions improve a later action. A memory that can be repeated but does not improve tool arguments or task completion is not sufficient.

### From Recall to Forgetting — ACL Findings 2026

https://aclanthology.org/2026.findings-acl.1337/

This work evaluates stale-memory reuse and conflict reconciliation.

**STAR implication:** persistent facts should have provenance, scope, last-confirmed time, and a way to be superseded. An old model, path, branch, or preference must not silently override a newer explicit correction.

## Inference speed and intelligence research

### llama.cpp measurement before tuning

- Project: https://github.com/ggml-org/llama.cpp
- Server: https://github.com/ggml-org/llama.cpp/tree/master/examples/server
- Benchmark tooling: https://github.com/ggml-org/llama.cpp/tree/master/examples/llama-bench

Measure the same model, prompt set, context, quantization, concurrency, and thermal state before comparing changes. Record:
- prompt processing tokens/sec;
- generation tokens/sec;
- p50/p95 time-to-first-token;
- inter-token latency;
- peak VRAM and host RAM;
- queue wait and active sequences;
- cancellation/restart correctness.

### KV cache and offload research

- TurboQuant: https://research.google/blog/turboquant/
- UlaCache: https://arxiv.org/abs/2610.29820

TurboQuant explores low-bit KV-cache compression; UlaCache explores logical addressing across GPU and CPU memory for sparse serving. Published results use specific models and accelerator/server configurations. UlaCache's reported H200/B300 results are not a prediction for a single 8 GB RTX 4060.

**STAR adoption rule:** do not enable a cache format or offload policy because a paper reports a speedup on a different GPU. Test long-context recall, coding accuracy, tool-use accuracy, TTFT, decode rate, transfer overhead, game frame-time p95/p99, and audio underruns on the actual host.

### Model routing and best-of-N

- Use a fast, smaller model for low-risk classification, formatting, and simple chat.
- Route difficult coding, planning, and multi-step research to a stronger model when measured difficulty justifies it.
- Retrieve verified project examples before asking a model to recreate known solutions.
- Reserve best-of-N generation and heavy critics for offline/background work; they must not contend with live speech, game input, or the active stream.
- Promote a model, prompt, or skill only after paired holdout evaluation; retain rollback metadata.

More reasoning tokens and more agents are not automatically more intelligence. The target is higher task success per unit of latency, memory, and energy, without regression in safety or stream responsiveness.

## Game-playing and game-development research

### SIMA 2 — Google DeepMind

https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/

SIMA 2 combines instruction following and visual interaction with a self-improvement cycle using generated tasks, reward estimates, and accumulated experience.

**STAR Gamer adoption:** generate a curriculum, attempt it in a reproducible environment, score actual outcomes, save a skill only when verified, then retest on a held-out environment. A natural-language explanation of a game is not demonstrated skill.

### Roblox OpenGameEval

https://github.com/Roblox/open-game-eval

The benchmark uses reproducible Roblox Studio sessions and separates observation from editing. STAR Creator should inspect relevant objects before changing them, then verify both the scene and actual Play-mode behavior.

### GameDevBench — ICML 2026

- Paper/results: https://proceedings.mlr.press/v306/chi26a.html
- Code: https://github.com/waynchi/gamedevbench

The benchmark contains 333 multimodal Godot game-development tasks across gameplay, UI, 2D graphics, and 3D graphics. Its paper reports that visual/image/video feedback improved one evaluated GPT-5.4 setup from 41.1% to 52.0%.

**STAR Creator adoption:** visual feedback is part of the engineering loop, not a cosmetic add-on. Compare screenshots, inspect animation timing, and play the result in the engine.

## Performance benchmark included

benchmarks/task_coordination_bench.py exercises the full lifecycle:

create -> accept -> claim -> checkpoint -> complete with evidence -> queue report -> playback acknowledgement.

The script defaults to an in-memory database and accepts an explicit database path for a durable-WAL comparison. It reports tasks/sec, ledger operations/sec, and p50/p95 per-task latency. It is a local microbenchmark, not a production SLA.

In the isolated Python environment used while preparing this change, 1,000 in-memory tasks completed 7,000 ledger operations in approximately 0.28 seconds (about 3.6k full task lifecycles/sec). This does not represent STAR's Windows machine, disk-backed WAL performance, or production concurrency.

## Acceptance plan for the next integration stage

| Area | Acceptance test |
|---|---|
| Durable restart | Task/checkpoint/report state survives process restart |
| Worker race | Two processes cannot claim the same unexpired task |
| Worker crash | Expired lease can be reclaimed with a new generation |
| Stale completion | Old generation cannot checkpoint or complete after reclaim |
| Evidence | Completed task requires result and evidence references |
| Communication | Report remains queued until playback acknowledgement |
| Interrupted speech | Unplayed report remains pending; stale playback cannot acknowledge a new generation |
| Request changes | Reprioritization preserves completed and still-owed work |
| Viewer privacy | No raw chat/transcript/voiceprint is stored by the ledger |
| Tool safety | Task creation/updates never grant tool permissions |
| Stream quality | Task DB activity does not cause audio underruns or OBS/game frame drops |
| Memory | Retrieved preferences improve action correctness and stale-memory resistance |
| Gaming | Skill promotion requires held-out gameplay evidence |
| Game creation | Scene, Play session, save/reload, and completion checks all pass |

## Hardware-aware schedule for STAR

For the single 8 GB GPU gaming/streaming configuration:

1. Keep audio callback, playback, and game-input loops at the highest scheduling priority.
2. Run light intent classification and queue operations on CPU.
3. Benchmark CPU-first ASR before reserving more GPU memory for speech models.
4. Keep the main reasoning model warm only if its memory footprint does not destabilize the game or avatar.
5. Move heavy research, best-of-N, asset generation, and model experiments to a secondary worker or off-stream windows.
6. Use resource-aware admission control, not unbounded parallel agents.
7. Record per-process CPU/RAM/VRAM, game frame time, OBS dropped frames, audio underruns, TTFT, TTS queue-to-playback, and task completion.

## Security and privacy boundaries

- Task titles and references are data, never system instructions.
- Viewer text cannot create permissions, authorize tools, purchase items, publish code, or control the desktop.
- A task completion record is not an approval record.
- High-impact or irreversible actions still require the existing owner approval path.
- Store opaque artifact/evidence references, not raw audio, viewer profiles, voiceprints, credentials, or chat transcripts.
- Keep the SQLite database local and out of GitHub.
- Use explicit consent for each audio/chat/game source and separately for OBS/VTube Studio control.
- Treat ASR/OCR/game observations as untrusted external input.

## Implementation status and non-claims

Implemented in this branch:
- SQLite-backed task state and bounded event history;
- atomic worker claims and expiring leases;
- hashed lease-token storage;
- generation fencing on expired-worker recovery;
- checkpoint/result/evidence references;
- report queue and actual-playback acknowledgement;
- stale report exclusion;
- 22 focused tests;
- a standard-library lifecycle benchmark.

Not implemented by this change:
- desktop runtime wiring or automatic task creation;
- a multi-agent scheduler or worker process supervisor;
- Twitch/YouTube adapters;
- ASR/diarization or addressee classification;
- VTube Studio/OBS control;
- game observation or input;
- model routing or model-weight changes;
- automatic model training or self-modification.

The exact-head GitHub Actions workflows for this new branch must pass before this change is considered repository-verified. No merge, release, installer, default permission, or production main change is authorized.
