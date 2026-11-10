# STAR AI — Agent Runtime Deadline Integrity & Cancellation Quarantine

**Research date:** 2026-11-10  
**Implementation:** \`star/agent_runtime.py\`  
**Status:** draft engineering change; host integration and full repository CI remain required.

## Executive finding

STAR already has a useful multi-agent foundation:

- \`star/orchestration.py\` validates task DAGs and read/write path conflicts.
- \`star/agent_runtime.py\` runs trusted async workers with dependency snapshots, time budgets and bounded concurrency.
- \`star/mission_checkpoint.py\` resumes completed read-only work only when task-plan and source revisions match.
- The streaming control plane separately requires host acknowledgements before releasing inference/audio reservations.

A concrete lifecycle gap remained: the agent runtime used \`asyncio.wait_for()\` for each worker and awaited \`asyncio.gather()\` for all workers during global cleanup. A timeout therefore did not guarantee that the call returned near its deadline. A cancellation-resistant coroutine could keep the run waiting, and an adapter that misunderstood cancellation could release task/resource ownership too early.

This update hardens that boundary. It does **not** add model intelligence or increase token throughput. It makes long-running research, coding, game-development and specialist tasks less likely to outlive their declared budget invisibly or be mistaken for completed work.

## Research findings

### 1. Python's timeout primitive is not a hard wall-clock kill

The Python 3.11 asyncio documentation states that \`asyncio.wait_for()\` cancels the awaited task on timeout, then waits until that task is actually cancelled. Total elapsed time can therefore exceed the requested timeout. The same documentation describes \`asyncio.wait()\` as returning \`done\` and \`pending\` sets at its timeout without cancelling pending tasks.

References:
- [Python 3.11 — Coroutines and Tasks](https://docs.python.org/3.11/library/asyncio-task.html)
- [Python 3.11 — Task cancellation](https://docs.python.org/3.11/library/asyncio-task.html#task-cancellation)

**Design implication:** use \`asyncio.wait()\` to enforce the scheduler's own deadline, explicitly request cancellation, wait for a small bounded grace period, and preserve a strong reference to any task whose stop remains unconfirmed. Never describe a cancellation request as proof that a worker stopped.

Python also warns that the event loop keeps weak references to tasks. A supervisor must retain strong references to background tasks until they finish.

### 2. Long-horizon coding is different from single-task success

RoadmapBench evaluates 115 long-horizon software-upgrade tasks across 17 repositories and five languages. Its tasks have a median of roughly 3,700 changed lines across 51 files. The strongest evaluated system resolved 39.1% of tasks in the reported study.

Reference: [RoadmapBench, 2026](https://arxiv.org/abs/2605.15846).

**Design implication:** STAR's creator workflow needs durable task ownership, explicit dependencies, resource locks, bounded retries and regression checks across the whole change—not merely a successful code-generation response.

### 3. Multi-agent collaboration has its own failure modes

AgentWorld evaluates long-horizon collaboration in a multi-agent sandbox, with 50+ interaction rounds and teams of 3–20 agents. Its reported best task success was 52.0%, with failures including communication breakdowns, role confusion and loss of shared plans.

Reference: [AgentWorld, 2026](https://arxiv.org/abs/2609.31590).

**Design implication:** adding more agents or parallelism is not automatically an intelligence improvement. STAR needs explicit task contracts, dependency evidence, bounded concurrency and a truthful record of workers that are still running after a deadline.

### 4. Reliability compounds across long sequences

A 2026 study of long-horizon agent degradation analyzes 10,664 trajectories and reports that success falls as dependent action sequences grow. It argues for horizon-aware reliability budgets rather than relying on short-task aggregate pass rates.

Reference: [How Fast Do Agents Rot?, 2026](https://arxiv.org/abs/2609.01660).

**Design implication:** report timeouts, cancellations, incomplete work and unconfirmed stops as distinct outcomes. Do not let a partial or late response satisfy a dependency or enter a durable success checkpoint.

## Implementation

### A. Pin timeout budgets once

A per-task timeout callback is now evaluated exactly once per task at run admission. The resulting numeric budget is validated and pinned. A stateful callback can no longer return one value during validation and a different value when the worker starts.

### B. Observe deadlines without waiting indefinitely for cancellation

Each trusted async worker has a start time, pinned deadline, cancellation reason, cancellation-request timestamp and quarantine-registration state.

The scheduler waits with \`asyncio.wait()\` and monotonic deadlines. It does not use \`wait_for()\` as a supposed hard process-kill primitive.

### C. Add bounded cancellation grace

When a task or team deadline expires:

1. STAR requests cancellation.
2. STAR waits no longer than \`cancel_grace\` (default 150 ms; bounded to 0–5 seconds).
3. If the task completes, its late result is discarded and the task is recorded as timed out, cancelled or incomplete.
4. If it is still running, STAR records \`stop_unconfirmed\` and retains the task.

A worker that returns after its deadline is never accepted as successful, even if the scheduler notices its completion slightly later.

### D. Preserve resource ownership until the coroutine really finishes

A cancellation-resistant task remains in the current plan's running set. \`TaskPlan.ready()\` therefore continues to see its read/write locks and concurrency slot. A conflicting task cannot start while the old coroutine is still alive; independent work may continue if a slot is available.

At the end of a run, \`AgentRuntimeState\` retains a strong reference to any unconfirmed task. A later plan using the same runtime state is rejected until the quarantine clears. The host can call \`wait_for_quarantine()\` to wait without cancelling the worker, then safely reuse the runtime.

### E. Keep partial work separate from verified completion

The runtime distinguishes:
- \`completed\`
- \`failed\`
- \`blocked\`
- \`timed_out\`
- \`cancelled\`
- \`incomplete\`
- \`stop_unconfirmed\`

Partial text remains visibly marked incomplete. It cannot satisfy a dependency, be checkpointed as a completed node or be synthesized as a verified result.

### F. Handle cancellation by the parent application

If the caller cancels the whole plan, the runtime requests cancellation for active workers, waits only for the bounded grace period, retains any still-running tasks and re-raises the caller's cancellation. It does not silently convert caller cancellation into success.

## Scope and trust boundary

This is an **async coroutine supervisor**, not an operating-system process supervisor.

A trusted worker adapter that wraps \`asyncio.to_thread\`, a subprocess, a model server, GPU work, a game process or a device operation must not report completion merely because its awaiting coroutine was cancelled. It must wait for the external operation's real stop acknowledgement, or use a separate host-owned process supervisor with its own PID/job-object/lease and termination receipt.

\`asyncio\` cannot forcibly terminate an OS thread or guarantee that an external process has stopped. The runtime documents this contract and does not claim otherwise.

No model-generated Python is executed. No worker receives another worker's credentials. No tool permissions are inherited. Write-capable plans remain opt-in and automatic checkpoint replay remains read-only.

## Relevance to STAR's capabilities

### General research and knowledge

Specialist tasks can gather sources, independently critique claims, synthesize findings and fact-check results. A timed-out research worker must not be mistaken for a completed source review.

### Roblox and cross-engine game development

Planner, Luau, UI, animation, environment, review and integration workers can run in parallel only when their declared read/write scopes do not conflict. A late editor must not continue changing a file after the coordinator has released its lock.

### Game-playing and skill acquisition

Game practice, strategy analysis and held-out evaluation should be separate task roles. If a gameplay worker misses its deadline, its partial observation must not be stored as a successful skill or counted as a win. Live input remains governed by the separate owner-authorized game host.

### VTuber streaming

Live speech, interruption handling, physical audio, avatar output and game-critical work remain separate from background research and development plans. Cancelling a background task must never be treated as proof that audio, a model process or a GPU worker has physically stopped. The existing streaming governor/host acknowledgement path remains authoritative for those resources.

### Speed and hardware efficiency

The change reduces the risk of hidden overrun and stale workers occupying resources indefinitely at the orchestration layer. It does not increase model tokens/second. Actual speed work must still be measured using first-token latency, inter-token latency, end-to-end completion, game frame p99, OBS drops, audio underruns, CPU/RAM/VRAM and answer quality under the same mixed workload.

## Verification

Focused offline tests cover:
- true parallel async overlap;
- dependency ordering and failure propagation;
- write permission and read/write lock behavior;
- per-task and global deadlines;
- partial-result handling;
- a timeout callback evaluated once;
- cancellation-resistant workers;
- retained quarantine state;
- blocking a new plan while a worker is still active;
- holding a conflicting resource lock until the worker actually stops;
- caller cancellation.

The isolated focused suite passed **14 tests** under Python 3.13.5. \`compileall\` passed. Ruff is not installed in the scratch environment. The full repository test suite, Pyright, GitHub Actions and Windows host acceptance have not yet run.

## Next engineering priorities

1. Add a Windows/Linux process supervisor for actual subprocess/model workers. Use Windows Job Objects on Windows and an appropriate process-group/cgroup boundary on Linux; require an explicit process-exit receipt before releasing GPU/CPU/resource leases.
2. Add role-specific worker registries with separate, least-privilege capability sets. A research worker should not inherit Roblox publishing, filesystem-write or stream-control permissions.
3. Add a durable side-effect journal for approved mutations: intent, idempotency key, before-state digest, operation receipt, after-state digest and rollback plan. Do not automatically retry uncertain writes.
4. Feed real CPU/GPU/VRAM/game-frame/audio telemetry into concurrency admission. Do not choose parallelism from model confidence or a fixed agent count alone.
5. Evaluate multi-round task plans with RoadmapBench- and AgentWorld-style holdouts, including failures and cancelled runs in the denominator.
6. Keep live VTuber work on its own latency budget; background research, training, asset rendering and game creation should yield when actual live telemetry shows pressure.

## Explicit non-claims

- No model weights were trained or changed.
- No inference speedup or intelligence gain was measured.
- No game was played or published.
- No Roblox place, OBS scene, microphone, speaker or avatar was controlled.
- No Windows process worker was connected.
- The change improves coroutine-level deadline integrity and makes unconfirmed cancellation visible; it does not prove that external OS/device work has stopped.
