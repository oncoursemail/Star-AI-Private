# STAR — Durable Agent Runs, Fencing, Real-Time Game Intelligence, and VTuber Roadmap

**Research date:** 2026-11-10  
**Implementation branch:** feat/durable-agent-run-coordinator-20261110-auto11  
**Base:** draft PR #1111 (bounded async cancellation/quarantine)  
**Rollout:** disabled until a trusted host adapter and independent acceptance tests exist.

## Executive finding

STAR has an increasingly capable set of individual subsystems: bounded async agent execution, cancellation quarantine, deadline-aware streaming dispatch, game-development evaluation, continual-learning evaluation, model-quality/speed evidence, live OBS/voice telemetry, and multi-party turn-taking.

The remaining infrastructure gap is coordination across **multiple processes and restarts**. An in-memory asyncio task registry can retain a cancellation-resistant coroutine while its Python process remains alive, but it cannot provide durable ownership to multiple independent worker processes or reject a late result after a lease has been reassigned.

This change adds a small, local, SQLite-backed **read-only agent-run control plane**. It issues durable leases and monotonically increasing run-scoped fencing tokens, enforces attempt budgets and dependency order, and accepts completion only from the currently unexpired lease.

It deliberately does **not** start workers, execute tools, edit files, publish Roblox experiences, control OBS, or claim to terminate a process. Mutating workers remain out of scope until STAR has a resource-side fenced commit gateway.

## Research findings

### 1. A lease is not a kill switch

A paused worker may resume after its lease expires. If the old worker can still write directly to a file, Git branch, database, game or external API, merely checking its local lease object is insufficient.

The fencing-token pattern assigns a strictly increasing token to each new ownership. The protected resource must atomically reject stale tokens. The token must be checked at the **actual mutation boundary**, not only by the coordinator.

Useful background:
- Martin Kleppmann, *How to do distributed locking* (2016): https://martin.kleppmann.com/2016/02/08/how-to-do-distributed-locking.html
- ZooKeeper recipes and lock ownership: https://zookeeper.apache.org/doc/current/recipes.html
- etcd concurrency API: https://etcd.io/docs/v3.6/dev-guide/api_concurrency_reference_v3/

**STAR implication:** this v1 rejects any task with declared write scopes. Its fencing token protects only the SQLite task/result ledger. It does not make arbitrary side effects safe. The next write-capable version must require a host-owned resource gateway that enforces compare-and-swap or an equivalent single-writer fence at the destination.

### 2. SQLite can provide atomic local claims, not a multi-machine consensus service

SQLite documents that BEGIN IMMEDIATE starts a write transaction immediately and can return SQLITE_BUSY if another writer is active. WAL mode allows readers to proceed alongside a writer, but SQLite still has a single writer at a time.

Sources:
- Transaction semantics: https://www.sqlite.org/lang_transaction.html
- WAL locking: https://www.sqlite.org/wal-lock.html
- WAL overview: https://www.sqlite.org/wal.html

**STAR implication:** a local SQLite database is appropriate for coordinating several worker processes on one Brain/desktop. It is not a distributed lock service for Brain 1 and Brain 2 over a network share. This implementation requires a local filesystem and WAL mode; do not place the database in OneDrive, Dropbox, SMB/NFS or another synchronized/network directory. Cross-machine coordination should use an actual service with a documented consistency model.

### 3. Async cancellation and process termination are different boundaries

Python's asyncio documentation explains that wait_for() cancels an awaitable and waits for cancellation to complete; elapsed time can exceed the requested timeout. asyncio.wait() returns pending tasks without cancelling them, and tasks need strong references while they are running.

Sources:
- Python 3.13 asyncio tasks: https://docs.python.org/3.13/library/asyncio-task.html
- Python 3.13 task groups and cancellation: https://docs.python.org/3.13/library/asyncio-task.html#task-groups

**STAR implication:** PR #1111's AgentRuntimeState handles unconfirmed asyncio cancellation in one process. This coordinator handles a different problem: durable task ownership between processes. Neither one kills a subprocess, thread, GPU kernel, model server or audio device. The future Windows/Linux process supervisor must observe actual process-tree exit and native stop acknowledgements.

### 4. Real-time game intelligence has a reasoning/interaction trade-off

LOLPlay (submitted 2026-10-25) evaluates visual agents in native League of Legends with 36 champion-specific tasks and 82 executable subgoal checks. The paper reports that higher reasoning effort did not improve success for the evaluated models; longer requests could leave fewer interaction rounds. GPT-6 Astra reached 25.0% task success and 40.3% subgoal success at medium effort in that study.

Source: https://arxiv.org/abs/2611.03685

**STAR implication:** game mastery should not be measured by long reasoning answers alone. A real-time game agent needs short perception/action cycles, scene-freshness checks, explicit action deadlines, and subgoal verification. Deep strategy should run asynchronously and must not block reflexive control or live speech. Results from LOLPlay are benchmark-specific and are not predictions of STAR's performance.

### 5. Game creation needs executable and visual verification

GameDevBench provides 333 Godot tasks across 2D graphics/animation, 3D graphics/animation, UI and gameplay logic. Its official repository documents the task set and leaderboard:
- Paper/project: https://sethkarten.ai/papers/gamedevbench.html
- Official repository: https://github.com/waynchi/gamedevbench

**STAR implication:** keep game creation separate from game mastery. A game-development result needs engine execution, regression checks and visual inspection; a game-playing result needs held-out scenarios and real-time action evidence. A single combined score would hide important weaknesses.

### 6. Local inference speed must be measured end-to-end

llama.cpp's server documents prompt-prefix reuse through cache_prompt, per-request prompt/generation timings through timings_per_token, and prompt-progress reporting. These can help separate prompt processing from token generation, but a faster decode rate does not necessarily mean faster first audible speech or better game performance.

Source: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md

**STAR implication:** use existing PRs #1101–#1102 and the paired streaming benchmark as the measurement foundation. Compare TTFT, first speakable token, first physically audible output, decode rate, output quality, game frame time, OBS loss, audio underruns, VRAM and memory pressure under the same mixed workload. Do not enable a speculative-decoding or quantization change solely because tokens/second rises.

## Implementation

New module: star/agent_run_coordinator.py

### Capabilities

- Immutable run registration bound to a canonical hash of the full task plan.
- Read-only task contracts only; any declared write scope is rejected.
- SQLite WAL database with synchronous=FULL, foreign keys and a bounded busy timeout.
- Atomic BEGIN IMMEDIATE task claims across processes on one local machine.
- Run-scoped, monotonically increasing fencing token on every new lease grant.
- Unique lease ID and validated worker ID.
- Bounded lease duration and attempt count, both pinned in the immutable run policy.
- Lease renewal without changing the fencing token.
- Expired-lease reclamation with a higher token on the next claim.
- Completion accepted only when run, task, worker, lease ID, token and expiry still match.
- Idempotent retry of the exact same completion; changed/stale completion is rejected.
- Retryable failure, terminal failure, dependency blocking and run finalization.
- Only direct dependency results are included in a worker's lease, reducing unnecessary context exposure. Treat those results as untrusted data, never as tool instructions.
- Status output contains aggregate state only, not task answers.
- Private database directory required on POSIX (mode 0700); database file is restricted to 0600. Windows host must provision an equivalent private ACL.
- No automatic worker launch, tool invocation, model routing, game input, TTS, OBS or external mutation.

### Why read-only in v1

A coordinator cannot prevent a stale process from writing directly to a resource that ignores its fencing token. For that reason, write-capable tasks are rejected rather than giving a false safety guarantee.

The future mutation gateway must:
1. Stage changes in an isolated workspace.
2. Revalidate the current run/lease at commit time.
3. Enforce a monotonic fence or expected-version compare-and-swap at the destination.
4. Use stable idempotency keys for retries.
5. Record an immutable operation receipt.
6. Reconcile uncertain outcomes before retrying.
7. Keep live publishing, spending, destructive changes and public broadcasts behind owner approval.

For ordinary filesystems, a Python pre-check followed by an arbitrary write still has a TOCTOU gap. The host should be the only process with write access to the protected destination and should serialize the final atomic replacement through its own commit service. Git branch updates should use expected-head checks. Roblox/Open Cloud actions should use narrowly scoped per-experience credentials and remain owner-gated for publishing.

## How this fits the existing STAR stack

| Existing subsystem | Responsibility | New coordinator relationship |
|---|---|---|
| star/orchestration.py | Validated DAG and resource scopes | Supplies the immutable task plan |
| star/agent_runtime.py (PR #1111) | In-process async workers and cancellation quarantine | Local coroutine layer beneath durable claims |
| star/mission_checkpoint.py | Reuse completed read-only task results when revisions match | Separate result-resume mechanism; do not confuse it with a live lease |
| star/stream_work_dispatcher.py (PR #1110) | Prioritize live/background streaming work | Can later prioritize which worker requests a lease |
| star/stream_brain_governor.py | Hardware admission and live brain leases | Still owns actual resource admission |
| PRs #1101–#1102 | Inference metrics and quality/speed gate | Supply evidence for model configuration changes |
| PRs #1107, #1105–#1106 | Multi-party floor control and turn-taking | Keep conversational work separate from background agent claims |
| PR #1108 | Cross-engine game-creation evaluation | Grades creator workers |
| PR #1109 | Continual-learning memory evaluation | Grades transfer/retention, not task ownership |

## Recommended next capabilities

### A. Resource-side fenced commit gateway
Do not add write-capable distributed agents until the destination enforces fencing. Start with isolated Git worktrees and a host-owned commit broker; later add Roblox Studio/Open Cloud adapters with per-experience scopes and owner approval.

### B. Process supervisor
Tie lease expiry to a Windows Job Object / Linux process group or cgroup. On cancellation, request graceful stop, wait a bounded grace period, terminate the owned process tree, then verify process exit. A coroutine finishing is not proof that a child process or GPU worker stopped.

### C. Role registry and capability manifests
Define research, code-review, Luau, UI, animation, game-perception, gameplay and integration roles. Each role should have a pinned worker revision, explicit read/write scopes, tool allowlist, output schema, context budget and maximum parallelism. Never inherit another worker's credentials or tool grants.

### D. Two-timescale gamer
- Fast loop: fresh frame, lightweight state estimate, short action, immediate result check.
- Slow loop: strategy, route planning, long-horizon objective and learning.
- The slow loop may propose; the fast loop revalidates scene freshness and deadlines before any action.
- Evaluate held-out maps, mechanics, difficulty levels and unseen seeds.
- Track both subgoal completion and full-task success; preserve no-op and failure evidence.

### E. General knowledge with provenance
Store source, retrieval date, confidence, contradiction links and expiry/freshness policy. Distinguish stable knowledge from current facts. Test transfer to unseen questions rather than counting documents ingested.

### F. Natural AI VTuber interaction
Maintain separate measures for addressee recognition, appropriate silence, interruptions, first-audible latency, factual grounding, voice consistency, expressive avatar timing and long-session drift. Use nonverbal listening cues where speech would interrupt. Keep background research from blocking live conversation.

## Acceptance plan

Before any host integration is enabled:

1. Run two independent Python processes against one private local SQLite database and prove they cannot claim the same task.
2. Pause worker A beyond lease expiry; let worker B claim with a larger fencing token; prove A's late completion is rejected.
3. Verify a renewal preserves its token and cannot revive an already expired lease.
4. Kill/restart the coordinator process; re-register the exact same plan and prove completed results persist while expired leases are reclaimed only after TTL.
5. Test SQLITE_BUSY, disk-full, read-only database, WAL recovery and corrupted result digests.
6. Confirm a plan change under the same run ID is rejected.
7. Confirm any write-capable task is rejected.
8. Verify no task answer or private content appears in status metrics or logs.
9. Only after the read-only path passes, design a separate fenced mutation gateway.
10. Run the full Windows mixed-workload rehearsal: game + OBS + TTS + VTube Studio + local inference + background agents. Measure p50/p95 first-audible latency, game frame time, OBS render/network loss, audio underruns, VRAM/RAM and worker stop time.

## Explicit non-claims

This implementation does not make the base model smarter, accelerate token generation, play a game, create a game, stream, operate OBS, terminate external processes or publish to Roblox. It supplies durable ownership and stale-result rejection for read-only agent tasks on one local host. Model quality, game skill, streaming naturalness and inference speed require separate real-world measurements.
