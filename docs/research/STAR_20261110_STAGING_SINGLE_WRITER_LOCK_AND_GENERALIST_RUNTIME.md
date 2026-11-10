# STAR AI — Cross-Process Staging Integrity and Generalist Runtime Research

**Research date:** 2026-11-10  
**Implementation:** cooperative local-host staging lock, materializer integration, and CI fixes  
**Status:** opt-in private staging infrastructure; no source-tree writes, process launching, Git publishing, Roblox publishing, model configuration changes, or live streaming changes.

## Executive finding

PR #1115 correctly made one materializer instance safe against overlapping calls in its own process and made interrupted replacements recoverable through a SQLite write-ahead intent journal. Its explicit boundary was single-host, single-writer operation.

A Python threading RLock does not coordinate two independent Python processes. SQLite WAL serializes database writers, but the filesystem replacement occurs between separate database transactions. Two trusted materializer processes could therefore interleave recovery, compare-and-swap, replacement, and journal finalization.

This increment closes that gap for cooperating processes on one local staging root. It uses a persistent OS lock file held across the entire critical section. The lock is advisory/cooperative, not a distributed lock, and it does not protect against an untrusted process that ignores the lock or can rewrite the private staging directory.

The run also corrected the Pyright regression reported by PR #1115 and repaired a missing test import that the cancelled offline test job had not reached.

## 1. Why a process lock is needed

### 1.1 Thread locks stop at the process boundary

The materializer's threading.RLock only coordinates callers that share that exact in-memory lock object. A second STAR host process has a different object and can enter its own critical section concurrently.

The risky sequence is:

1. Process A reads a PREPARED journal intent.
2. Process B reads the same PREPARED intent.
3. Both inspect the same target and temporary file.
4. One process replaces the target.
5. The other process may observe an unexpected state or race journal finalization.

Even if SHA-256 and compare-and-swap checks detect many conflicts, the host should not allow two cooperating writers to run this protocol simultaneously.

### 1.2 OS advisory locks

Python documents POSIX fcntl.flock() as an OS file-descriptor lock. On Windows, msvcrt.locking() locks a byte range associated with a file descriptor and reports lock contention with OSError.

STAR uses:
- POSIX: exclusive non-blocking flock, retried until a bounded monotonic deadline.
- Windows: a one-byte non-blocking msvcrt region lock, retried until the same bounded deadline.
- Same-process protection: a process-local lock registry keyed by the canonical lock path.
- Fail-closed behavior: unsupported platforms and malformed lock files are rejected.
- Persistent lock file: the lock file is never unlinked, avoiding the old-inode/new-inode split-lock problem.
- Crash release: closing the descriptor or exiting the process releases the OS lock.

References:
- Python fcntl: https://docs.python.org/3/library/fcntl.html#fcntl.flock
- Python msvcrt: https://docs.python.org/3/library/msvcrt.html#msvcrt.locking

### 1.3 SQLite WAL is not the filesystem lock

SQLite WAL allows readers and a writer to proceed concurrently, but only one writer can append to the WAL at a time. WAL is designed for processes on the same host and does not work over a network filesystem.

The SQLite transaction protects journal rows. It does not automatically cover the later filesystem rename. STAR therefore holds the OS staging lock from recovery through CAS validation, replacement, directory synchronization, and journal finalization.

Reference: https://sqlite.org/wal.html

### 1.4 Boundaries

This lock:
- coordinates only trusted STAR materializer instances that honor it;
- is for one local host and one private staging root;
- is not a distributed lease or fencing service;
- must not be used on SMB/NFS, cloud-sync folders, or shared multi-host roots;
- does not replace Windows directory ACL provisioning;
- does not protect against a hostile local process with write access to the staging root;
- does not authorize source-tree, Git, Roblox, or production writes.

The lock file is persistent and should not be deleted during normal cleanup. A future host maintenance command may remove it only after proving no process can still hold or open that staging root.

## 2. Windows process supervision remains the next boundary

A coroutine cancellation or a staging lock does not terminate an external renderer, model server, game engine, or child process.

Microsoft Job Objects can manage a process group as a unit, apply resource limits, account for work, and terminate all processes associated with the job. STAR should eventually create a job, start a child in a controlled state, assign it before allowing untrusted work to run, disallow breakaway unless explicitly required, and verify job completion before releasing resource leases.

This is a separate implementation and is not included in this change.

Reference: https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects

## 3. Research: inference speed must be measured with quality

The llama.cpp SPEED-Bench client benchmarks an already-running llama-server and reports per-category latency, throughput, and speculative-draft acceptance. Its qualitative categories include coding, humanities, math, multilingual, QA, RAG, reasoning, roleplay, STEM, summarization, and writing.

For STAR:
- benchmark the same prompt set and model build before and after each change;
- keep server slot count and client concurrency aligned;
- report time-to-first-token, inter-token latency, end-to-end latency, and throughput separately;
- measure quality and task completion alongside speed;
- test the live-stream workload separately from background batch workloads;
- do not enable speculative decoding or change model quantization merely because one throughput number improves.

Reference: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md

## 4. Research: natural VTuber turn-taking

LiveKit's current Agents documentation describes adaptive interruption handling that distinguishes a real barge-in from short backchannels such as "uh-huh" and "right". Its false-interruption recovery can resume speech after a VAD event that produces no user transcript.

This is a useful design reference, not a reason to silently move STAR's local-first voice pipeline to a hosted service. Adaptive handling has specific VAD/STT or real-time-model prerequisites; self-hosted use can require LiveKit inference credentials and has quota/usage considerations.

Recommended STAR acceptance measurements:
- true interruption precision and recall;
- false interruption rate;
- time from genuine barge-in to audio stop;
- recovery delay after false interruption;
- missed corrections at turn boundaries;
- first audible response latency;
- multi-speaker attribution and floor ownership;
- transcript/audio alignment;
- voice/avatar synchronization;
- appropriate silence and long-context continuity.

Keep the local VAD path available as a deterministic fallback and compare alternatives on the same recorded holdout conversations.

References:
- https://docs.livekit.io/agents/logic/turns/adaptive-interruption-handling/
- https://docs.livekit.io/reference/agents/turn-handling-options/

## 5. Research: game mastery needs state-verifiable and real-time tracks

GameWorld evaluates multimodal agents across 34 browser games and 170 tasks. It computes success and progress from serialized game state rather than relying solely on screenshots or an LLM judge. Its real-time variant keeps the game running during inference and should be reported separately from the paused track.

STAR's game-learning loop should therefore keep two distinct scores:
1. State-verifiable outcome/progress on deterministic tasks.
2. Real-time control quality under wall-clock deadlines.

Use held-out maps, seeds, mechanics, and game versions. Prevent repeated-start replays, lucky wins, and easy scenarios from being counted as general skill improvement. Record action validity, latency, deaths/lives, checkpoints, objective completion, and transfer to unseen scenarios.

Reference:
- https://arxiv.org/abs/2604.07429
- https://gameworld-bench.github.io/

## 6. Generalist intelligence roadmap

A stronger generalist should be measured by whether she can retrieve relevant knowledge, apply it to unfamiliar tasks, recognize uncertainty, and retain verified procedures—not by memory size or self-reported confidence.

Recommended layers:
- Semantic knowledge: stable facts with provenance and freshness.
- Episodic memory: interactions and project experiences.
- Procedural memory: reusable, tested skills.
- Causal memory: actions, observations, consequences, and failure explanations.
- Working memory: only the context needed for the active task.
- Project memory: architecture, constraints, decisions, and verified examples.

A learning update should pass a holdout evaluation before becoming a trusted skill. Use cross-domain transfer tests for Luau-to-Python concepts, 2D-to-3D navigation, game mechanics, research workflows, and creative tooling. Keep failed experiments and uncertainty visible rather than rewriting history.

## 7. Recommended integrated architecture

### Live interaction plane
- streaming speech and turn-taking;
- social/multi-party floor tracking;
- game-critical perception;
- avatar expression and audio synchronization.

### Background intelligence plane
- research and general knowledge;
- project planning;
- game creation;
- practice and skill consolidation;
- asset generation and rendering.

### Trusted execution plane
- durable task coordinator;
- cancellation quarantine;
- process supervisor;
- resource leases;
- fenced artifact workspace;
- host-only staging and promotion journal;
- independent build/test/review gates.

The live plane receives reserved latency and hardware capacity. Background work is deferred under pressure. Only the trusted host can materialize verified artifacts. Publishing, live-game changes, purchases, and irreversible external actions remain separate approval gates.

## 8. Implementation and tests

This increment:
- adds StagingRootLock with POSIX flock and Windows msvcrt locking;
- serializes different materializer instances within the same process;
- holds the OS lock across recovery and promotion;
- uses a bounded timeout and fails closed on unsupported platforms;
- leaves a persistent lock file and never unlinks it;
- fixes the Pyright bool-narrowing error in the materializer;
- imports AgentRunCoordinator in the crash-recovery test module;
- adds spawn-based cross-process exclusion and lock-path safety tests.

Focused tests cover persistent private lock files, cross-process exclusion, bounded timeout, recovery after the owner releases the lock, symlink rejection, and directory rejection.

## 9. Remaining acceptance work

- Run the complete offline Python suite after the CI cancellation.
- Confirm the Pyright baseline gate is green.
- Run Windows CI for msvcrt locking and inspect inherited staging-root ACLs.
- Test process termination while holding the lock and verify a new host can recover.
- Run two real STAR host processes against one staging root.
- Add a native Windows Job Object supervisor in a separate reviewed change.
- Keep source-tree promotion disabled until the supervisor, filesystem adapter, and crash-recovery tests pass on the actual Windows target.

No measured model-speed increase, game win-rate gain, human-level intelligence claim, or live VTuber improvement is made by this infrastructure change.
