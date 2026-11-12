# STAR AI: Absolute Task Deadlines, Voice-Task Continuity, and Game Completion

**Research date:** 2026-11-12  
**Implementation branch:** `fix/task-ledger-deadline-retry-20261112`  
**Parent:** draft PR #1154 (`feat/versioned-task-ledger-20261112-auto11`)  
**Scope:** correct an absolute-deadline edge case in the versioned task ledger and translate new 2026 research into measurable requirements for STAR's voice, VTuber, gamer, creator, and learning systems.

## Executive summary

This audit found a retry-window bug in the new versioned task ledger:

- A task could fail or be cancelled before its deadline.
- Its absolute deadline could then pass.
- `refine()` could still reopen the task because deadline expiration was applied only to queued/running records.
- `reap()` also ignored failed/cancelled records, even though the API deliberately permits those states to be refined and retried.

The fix treats a deadline as an absolute end to the task's retry window. Once it passes, queued, running, failed, and cancelled-but-retryable records become expired. Completed records remain completed. A task without a deadline can still be refined after failure/cancellation.

This is a narrow correctness change. It does not change runtime defaults, execute workers, terminate processes, authorize tools, or promote learned skills.

## 1. Implementation and invariant

### Corrected invariant

For every task with deadline (D):

- Before (D), eligible non-completed states may be refined/retried subject to normal compare-and-swap checks.
- At or after (D), no queued/running/failed/cancelled task may be reopened.
- Reaping must make the same deadline decision even if no caller attempts a mutation.
- A completed task is immutable and is not rewritten as expired after completion.

### Source changes

- `star/task_ledger.py`
  - Include FAILED and CANCELLED in deadline expiration.
  - Include FAILED and CANCELLED in deadline reaping.
- `tests/test_task_ledger.py`
  - Test refine-after-deadline for failed and cancelled tasks.
  - Test reaper expiration for both retryable states.
  - Preserve the no-deadline cancelled-task refinement behavior.

The task ledger remains an in-memory control-plane primitive. Its monotonic timestamps remain scoped to a host clock epoch. Durable checkpoint recovery must continue to validate source, task-contract, worker, and context revisions independently.

## 2. New research: voice conversation must track work and communication separately

### Joi-Bench-Task (submitted 2026-11-09)

Paper: https://arxiv.org/abs/2611.12118

This benchmark evaluates full-duplex voice agents while users change requests, interrupt tool execution, or interrupt spoken delivery. Its simulator can inject interventions at controlled points in a task. The paper reports that the best result-completion rate under request changes was 55%; four of five evaluated agents had average information-omission rates of at least 23% after interruption.

**STAR implication:** a task being completed is not the same as the result being communicated. The system needs separate, versioned states for:

1. requested;
2. accepted;
3. executing;
4. completed;
5. result prepared;
6. spoken/submitted;
7. playback acknowledged;
8. reported to the user.

Do not mark a user obligation as fulfilled merely because a worker returned. If STAR is interrupted after completing research but before speaking the result, the obligation must remain reportable. If a request is refined, preserve earlier obligations unless the user explicitly supersedes them.

The task ledger tracks execution freshness. A future delivery ledger should track communication receipts and playback generations; neither ledger should be treated as proof that a remote viewer heard the stream.

### MultiPartyTurnBench (submitted 2026-10-14)

Paper: https://arxiv.org/abs/2610.20172  
Benchmark page: https://www.fullduplex.ai/benchmarks/multipartyturnbench

The benchmark contains 240 channel-separated conversations with two to five speakers and six interaction types. It separates end-of-turn detection from interruption detection. Reported learned systems achieve 82.5–92.6% end-of-turn recall at 4.3–11.8% false-positive rates, while selective interruption remains much harder; five full-duplex agents score 46.9–54.7% balanced accuracy on selective interruption handling.

**STAR implication:** do not implement a single voice-activity threshold as the Social Director. Maintain separate evidence for:

- genuine floor completion versus a pause;
- backchannel versus takeover;
- explicit versus implicit addressing;
- interruption intent versus overlapping speech;
- whether STAR should speak, yield, stop, or remain silent.

Evaluate end-of-turn, interruption, response appropriateness, and silence preservation separately. Use synthetic channel-separated tests for controlled coverage and real recorded audio for external validity.

## 3. New research: game creation has an artifact-to-play gap

### OpenGameEval (published 2026-10-01)

Paper: https://arxiv.org/abs/2610.02563  
Code and task suite: https://github.com/Roblox/open-game-eval

OpenGameEval runs agents inside reproducible Roblox Studio sessions and checks both edited scene state and simulated play. It separates observation tools from editing tools. Its 84-task, 13-model study reports a best single-attempt pass rate of 51.7%; the best five-of-five consistency rate is 39.4%. Inspecting every relevant object before acting is associated with +13.4 percentage points on scene-only tasks and +9.8 points on script-only tasks.

**STAR implication:** Creator tools should explicitly separate read/inspect operations from edit/execute operations. Require the agent to inspect the relevant hierarchy, scripts, properties, remotes, and runtime state before mutation. Log exploration coverage as a diagnostic, not as a substitute for final correctness.

### CEGame-Bench (submitted 2026-10-19)

Paper: https://arxiv.org/abs/2610.26098

CEGame-Bench evaluates complete-game creation from an empty project across Defold, Godot, Roblox Studio, Unity, and Unreal Engine. Its 50 tasks use a design document as a checkable contract and a hidden evaluator that plays with real input. Runs can average up to 295 steps and 65 million tokens. The paper reports that only 16% of agent runs reach the ending. Its Game Completion Boost skill maps requirements to player checkpoints, compares expected state with visible outcomes, and replays affected paths after repair; it raises execution-based scores by 14.1–24.3 points for three evaluated models on high-difficulty games.

**STAR implication:** do not call a game complete because scripts compile, a scene opens, or a screenshot looks good. Create a Game Completion Gate:

1. Parse the design document into atomic player-visible requirements.
2. Map each requirement to an observable runtime checkpoint.
3. Build from an empty or known project state.
4. Launch the actual engine.
5. Drive the game with real or reproducible input.
6. Verify progression, fail/retry, pause/resume, restart, and ending paths.
7. Save, close, reopen in a fresh process, and verify persistence.
8. Repair the failing path.
9. Replay the repaired path and all dependent regression paths.
10. Promote the artifact only when every required gate passes.

Use engine-specific evaluators; the CEGame-Bench paper finds that engine rankings differ, so one engine's score must not be treated as a universal game-development score.

## 4. STAR capability architecture

### A. Conversation and task continuity

Keep these ledgers distinct:

- **Task ledger:** current task contract, version, lease, deadline, execution state.
- **Delivery ledger:** result prepared, speech generation, playback generation, local playback acknowledgement, and still-unreported obligations.
- **Conversation state:** floor owner, speaker channel, addressee confidence, topic, interruption type, and unresolved questions.

The coordination layer should offer typed operations such as refine, supersede, pause, resume, cancel, prepare-report, and acknowledge-delivery. Validate them in trusted code. A model-selected operation is intent, not authorization.

### B. Natural VTuber behavior

The Social Director should use a low-latency deterministic floor-control path for obvious cases and invoke deeper reasoning only for ambiguous social context. The Avatar Director should receive one synchronized behavior state, but preserve separate clocks for:

- generated text;
- generated phonemes/visemes;
- submitted PCM;
- scheduled device playback;
- optional local process-loopback observation.

Use phoneme timing when available and amplitude only as fallback. Keep viewer identity and raw audio out of long-term memory by default. Make VTube Studio access owner-authorized, revocable, and local-secret-safe.

### C. Gamer learning

Keep two time scales:

- **Reactive controller:** deadline-bound input, camera, movement, combat, and immediate hazard avoidance.
- **Strategic planner:** objectives, map, resource economy, route planning, strategy, and skill selection.

Store skills with preconditions, action sequence, expected observations, failure conditions, version, and held-out transfer evidence. One successful run is an episode, not mastery. Promotion should require repeated success on unseen maps/seeds or altered conditions and a rollback path.

### D. General knowledge

Treat knowledge as claims with provenance, timestamp, confidence, and domain. Separate stable reference knowledge from time-sensitive facts. Require source-grounded retrieval for current facts, practice for procedural skills, and delayed/held-out tests for transfer. Do not let a single unverified episode overwrite an established skill or fact.

## 5. Speed and quality: measure the complete interactive session

A local inference configuration should be accepted only when it improves useful response latency without degrading the rest of STAR's live workload.

Record, with a versioned schema:

- queue wait and context assembly;
- model prefill and time-to-first-token;
- time-to-first-useful-text;
- TTS first-PCM and speaker submission;
- scheduled DAC playback and optional loopback;
- output-token latency and request completion;
- game frame-time p95/p99;
- audio underruns;
- OBS render skips, encoder lag, and network drops;
- VRAM/RAM peak and headroom.

Compare cold/warm model residency, prefix cache, KV-cache settings, quantization, speculative decoding, and concurrency using identical prompts and held-out quality checks. Do not report token throughput as a speedup if first-audible latency or gameplay/streaming quality regresses.

## 6. Acceptance tests for the next milestones

| Area | Acceptance requirement |
|---|---|
| Task deadline | Failed/cancelled task cannot be refined after absolute deadline |
| Task reaper | Failed/cancelled retryable records expire when deadline passes |
| Task semantics | No-deadline failed/cancelled tasks remain refinable |
| Voice continuity | Interrupting speech does not erase a completed-but-unreported obligation |
| Request refinement | Superseded work cannot overwrite a newer task version |
| Multiparty streaming | Backchannels do not trigger speech; genuine interruptions can take the floor |
| Silence | STAR remains silent when the conversation is not addressed to her |
| Avatar timing | Visemes follow playback timing, not merely TTS generation |
| Roblox Creator | Relevant objects are inspected before edits; play-time checks are required |
| Complete game | Ending, restart, save, fresh-process reopen, and regression paths pass |
| Gamer | Skills pass held-out maps/seeds before promotion |
| General knowledge | Delayed transfer and source freshness are measured |
| Performance | First-audible, game p99, audio underruns, OBS health, and model quality all stay within measured budgets |

## 7. Research sources

- Joi-Bench-Task: https://arxiv.org/abs/2611.12118
- MultiPartyTurnBench: https://arxiv.org/abs/2610.20172
- MultiPartyTurnBench benchmark page: https://www.fullduplex.ai/benchmarks/multipartyturnbench
- OpenGameEval: https://arxiv.org/abs/2610.02563
- OpenGameEval implementation: https://github.com/Roblox/open-game-eval
- CEGame-Bench: https://arxiv.org/abs/2610.26098
- VTube Studio API: https://github.com/DenchiSoft/VTubeStudio
- llama.cpp server and benchmark tooling: https://github.com/ggml-org/llama.cpp

## Validation boundary

This branch contains a deterministic ledger correctness fix and focused regression tests. It does not implement the future delivery ledger, Social Director, VTube Studio transport, Windows audio capture, game controller, or Game Completion Gate. No Windows device, OBS session, VTube Studio model, Roblox Studio project, live game, livestream, or RTX performance benchmark was exercised. No model weights, inference routing defaults, runtime permissions, broadcast settings, or production branch are changed.
