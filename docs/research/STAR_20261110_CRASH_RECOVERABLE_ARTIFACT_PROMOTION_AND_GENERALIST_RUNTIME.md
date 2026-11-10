# STAR AI — Crash-Recoverable Artifact Promotion and Generalist Runtime Research

**Research date:** 2026-11-10  
**Implementation:** `star/artifact_promotion_journal.py` and the host artifact materializer  
**Status:** opt-in host staging infrastructure; not connected to source-tree writes, production workers, Git publication, Roblox publishing, or live streaming.

## Executive finding

The previous host materializer had a safe compare-and-swap check and a same-directory temporary file, but its filesystem replacement and its success report were not tied together by a durable recovery record. A process could stop after the rename but before the caller received a receipt. A later run could see the new bytes, but there was no durable record explaining whether that was a completed promotion, an interrupted one, or an unrelated edit.

This increment adds a SQLite write-ahead intent journal around the staging replacement. It does **not** claim that SQLite and the filesystem form one atomic transaction. Instead, it makes the boundary recoverable by recording intent first and reconciling observed file digests after restart.

The broader research review found that STAR already has substantial parallel work for model quality/speed, llama.cpp metrics, continual-learning evaluation, real-time game mastery, natural VTuber speech, GPU admission and task scheduling. The highest-value work now is integration and end-to-end acceptance, not another disconnected feature with overlapping responsibilities.

## 1. Research: crash consistency across a database and filesystem

### 1.1 A filesystem rename and a database commit cannot be treated as one transaction

Python documents that `os.replace()` replaces an existing file and is atomic on POSIX when successful; cross-filesystem moves may fail. Creating the temporary file in the destination directory avoids the cross-filesystem case, but atomic visibility is not the same as a durable multi-file transaction.

Source: https://docs.python.org/3/library/os.html#os.replace

STAR therefore uses a small write-ahead protocol:

1. Verify the complete-run artifact and SHA-256 digest.
2. Write a same-directory temporary file and flush its contents.
3. Recheck the destination's exact prior digest.
4. Commit a durable PREPARED intent to SQLite.
5. Replace the destination with the temporary file.
6. Sync the parent directory where the platform supports it.
7. Mark the intent COMMITTED.

If the process stops between steps 4 and 7, the next trusted host can reconcile the journal against the target and temporary-file digests.

### 1.2 SQLite WAL and synchronous FULL

SQLite documents that WAL is a same-host mechanism; it is not suitable for a database shared across machines or placed on a network filesystem. WAL allows readers and a writer to proceed concurrently, but SQLite still serializes writers.

SQLite's synchronous documentation distinguishes consistency from durability: in WAL mode, FULL adds a WAL sync at each transaction commit so committed changes are durable across power loss, subject to the operating system and storage device honoring flush requests.

Sources:
- https://sqlite.org/wal.html
- https://www.sqlite.org/pragma.html#pragma_synchronous
- https://www.sqlite.org/transactional.html

STAR's promotion journal therefore:
- lives inside the private staging root on one local host;
- uses WAL mode;
- sets synchronous=FULL on every connection;
- uses BEGIN IMMEDIATE for state transitions;
- stores hashes, versions, relative paths and state—not artifact payloads;
- is not a distributed lock or a multi-machine coordination service.

No storage setting can compensate for a drive, controller or filesystem that falsely acknowledges flushes. The implementation must be tested on the actual Windows and Linux filesystems used by STAR.

### 1.3 Windows durability is a separate acceptance target

The current materializer uses Python's portable replacement API and flushes the temporary file. On POSIX it also syncs the parent directory. The current Python layer does not claim a Windows directory-entry durability guarantee.

The Windows host should eventually use a native, reviewed replacement adapter based on Windows file handles and the appropriate flush/replace APIs, with tests for the exact supported filesystem. The trusted host must also verify private directory ACLs and reject reparse-point escapes. Portable Python path checks alone are not a substitute for a native handle-relative security boundary.

### 1.4 Process supervision is still separate

Windows Job Objects can group processes, apply limits and terminate a job's associated process tree when the last job handle closes if KILL_ON_JOB_CLOSE is configured. Child-process breakaway and assignment timing matter; a coroutine cancellation is not proof that an OS process exited.

Source: https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects

STAR still needs a native Windows/Linux process supervisor that:
- creates the containment boundary before launching untrusted work;
- assigns and verifies the process before releasing it to execute;
- records OS process identity, not just a PID;
- observes exit status and confirms the full process tree is empty;
- retains GPU/VRAM leases until physical stop is witnessed;
- reconciles orphaned workers after host restart.

This PR does not launch or terminate processes.

## 2. Promotion journal state machine

Each intent records:
- opaque operation ID;
- run ID and virtual resource;
- artifact version;
- expected previous SHA-256 (or null for a new file);
- new SHA-256;
- staging-root-relative target and temporary paths;
- PREPARED/COMMITTED/CONFLICT/ABORTED state;
- a bounded error code and timestamps.

Recovery applies only these rules:

| Observed state | Recovery action |
|---|---|
| Target already has the new digest | Mark COMMITTED; the rename already happened |
| Target still has the exact expected old digest and temp has the new digest | Replay the same-directory replacement, sync, then mark COMMITTED |
| Target digest differs from both expected old and new | Mark CONFLICT; never overwrite |
| Target still matches old digest but temp is missing or corrupt | Mark ABORTED; never invent missing bytes |
| Transient I/O failure | Keep PREPARED so a later host retry can inspect again |
| Invalid or escaped journal path | Mark CONFLICT; do not follow the path |

Recovery is idempotent: terminal journal rows are not replayed. A later call sees no pending row after successful reconciliation.

The journal is deliberately single-host/single-writer. It does not solve an attacker racing a file path from another process, and it does not grant workers direct filesystem access. A future native materializer should use directory handles and platform-specific no-follow/reparse-point controls to close the remaining time-of-check/time-of-use window.

## 3. How this fits STAR's existing intelligence architecture

The repository already has separate draft work for the major capability areas. The current priority should be to connect those pieces under one measurable runtime rather than duplicate them.

### 3.1 Intelligence, memory and continual learning

- PR #1109 adds a paired memory-on/memory-off evaluator across dependent transfer, independent interference, conventional probes and retention.
- Reuse that evaluator to compare causal action-observation-outcome memory against transcript-only memory.
- Validate old coding traces against current file, symbol, dependency and test digests before retrieval.
- Keep memory retrieval budgets different for a live voice turn and a long background research task.
- Require held-out transfer and retention evidence before changing a memory policy.

PR: https://github.com/oncoursemail/Star-AI-Project/pull/1109

### 3.2 Faster inference without sacrificing quality

- PR #1101 supplies read-only llama.cpp server metrics.
- PR #1102 gates model changes on paired quality and speed evidence.
- PRs #1091 and #1092 harden paired speed and speech comparisons against replayed or inconsistent evidence.
- PR #1110 adds deadline-aware scheduling in front of the existing stream governor.

The upstream llama.cpp SPEED-Bench server client is specifically designed to compare speculative decoding configurations through a running server and reports latency, throughput and draft acceptance. Use it as a reproducible experiment, not as a guarantee that a draft model will accelerate STAR on an 8 GB GPU.

Source: https://github.com/ggml-org/llama.cpp/tree/master/tools/server/bench/speed-bench

Every speed experiment should pin model/quantization/tokenizer/backend/request trace and compare:
- prompt/prefill time;
- time to first token;
- inter-token latency;
- completion latency;
- first audible sample;
- output quality and task pass rate;
- GPU/CPU/RAM/VRAM pressure;
- game frame-time and OBS/audio regressions under simultaneous load.

Do not change production model routing from a single synthetic throughput result.

### 3.3 Real-time gaming and game creation

GameWorld contains 34 browser games and 170 tasks, with success and normalized progress read from serialized game state rather than inferred only from screenshots or an LLM judge. GameWorld-RT keeps the game running during inference and must be reported separately from a paused environment.

Sources:
- https://gameworld-bench.github.io/
- https://arxiv.org/abs/2604.07429

STAR already has real-time game mastery work, including scenario-balanced evaluation and anti-replay controls (PR #1093 and related game-evaluation changes). Keep game mastery separate from game creation:
- mastery: win/progress, action latency, valid inputs, scenario diversity and unseen-map transfer;
- creation: build success, engine launch, static checks, visual inspection, playtest coverage, regression count and repair success.

A game agent should use a fast perception/action loop and a slower strategic loop. Every action should be bound to a fresh scene/state version; stale observations must expire rather than being replayed after the world changes.

PR: https://github.com/oncoursemail/Star-AI-Project/pull/1093

### 3.4 Natural VTuber interaction

LiveKit's current turn-taking documentation separates endpointing, interruption detection, false-interruption recovery and preemptive generation. Adaptive interruption handling distinguishes genuine barge-ins from backchannels; false-interruption recovery can resume speech, while preemptive TTS reduces latency at the cost of wasted synthesis when a turn changes.

Sources:
- https://docs.livekit.io/agents/logic/turns/tuning/
- https://docs.livekit.io/agents/logic/turns/adaptive-interruption-handling/

STAR already has extensive work on audible-turn evidence, long-session voice health, OBS load verification and game/voice arbitration (for example PR #1085 and PRs #1075–#1084). The next step is a real client-audible rehearsal, not merely adding another VAD threshold.

Measure separately:
- first audible latency at the output/client;
- false interruption and missed barge-in rates;
- turn-end delay;
- backchannel handling;
- resume-from-interruption correctness;
- multi-speaker floor attribution;
- long-session factual grounding and repetition;
- avatar/phoneme/PCM synchronization;
- game frame-time, OBS drops and audio underruns.

AI identity should remain transparent to viewers. Natural timing, humor, silence and expressive delivery are valuable; pretending to be a human is not required.

## 4. Implementation in this increment

### New module: star/artifact_promotion_journal.py

- SQLite WAL database stored in the dedicated staging root.
- synchronous=FULL on every connection.
- Explicit schema version and fail-closed handling of a newer schema.
- PREPARED intents committed before file replacement.
- Terminal COMMITTED/CONFLICT/ABORTED transitions.
- Bounded identifiers, hashes, relative paths and error codes.
- SQLite connections explicitly closed after every operation.

### Updated: star/agent_artifact_materializer.py

- Creates the journal only after validating the staging root.
- Writes and fsyncs the same-directory temporary file.
- Persists PREPARED before os.replace().
- Finalizes the journal after replacement and directory sync.
- Exposes recover_pending() for trusted-host startup.
- Replays only if target still matches the recorded old digest and temp matches the new digest.
- Recognizes an already-applied rename after a crash.
- Never overwrites an unexpected external edit.
- Leaves transiently failing intents pending for retry.
- Calls recovery before starting another materialization.

### Tests

New test file: tests/test_artifact_promotion_recovery.py

Covers successful journaling, crash before replacement, crash after replacement but before journal finalization, external destination collision, missing temporary file, and unsupported journal schema.

## 5. Deliberate limits

This is not:
- a cross-host distributed transaction;
- a filesystem sandbox for untrusted workers;
- a source-checkout or Git promotion system;
- a Roblox publishing mechanism;
- an OS process supervisor;
- a model router or inference optimization;
- a live OBS, microphone, TTS or game controller.

It does not directly increase neural intelligence, tokens/second, game win rate or human-equivalent behavior. It makes one development artifact boundary recoverable and auditable.

## 6. Acceptance criteria before integration

1. Run the focused journal/materializer tests on Linux and Windows.
2. Run the full repository test suite, Ruff and Pyright.
3. Add process-kill fault injection at every journal/file boundary.
4. Test abrupt process termination and host restart on the actual supported filesystems.
5. Verify Windows staging ACLs and reject reparse-point redirection using native handles.
6. Run concurrent-writer adversarial tests; keep multiple materializer processes unsupported until a cross-process lock is implemented.
7. Confirm that a stale or conflicting intent never overwrites external bytes.
8. Keep staging outside all source worktrees and inaccessible to model-generated code.
9. Do not enable automatic Git commits, Roblox publication, model promotion or live broadcast.

## 7. Research references

- Python os.replace: https://docs.python.org/3/library/os.html#os.replace
- SQLite WAL: https://sqlite.org/wal.html
- SQLite synchronous: https://www.sqlite.org/pragma.html#pragma_synchronous
- SQLite transactions: https://www.sqlite.org/transactional.html
- Windows Job Objects: https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects
- llama.cpp SPEED-Bench: https://github.com/ggml-org/llama.cpp/tree/master/tools/server/bench/speed-bench
- LiveKit turn-taking tuning: https://docs.livekit.io/agents/logic/turns/tuning/
- LiveKit adaptive interruption: https://docs.livekit.io/agents/logic/turns/adaptive-interruption-handling/
- GameWorld benchmark: https://gameworld-bench.github.io/
- GameWorld paper: https://arxiv.org/abs/2604.07429
- STAR PR #1101: https://github.com/oncoursemail/Star-AI-Project/pull/1101
- STAR PR #1102: https://github.com/oncoursemail/Star-AI-Project/pull/1102
- STAR PR #1109: https://github.com/oncoursemail/Star-AI-Project/pull/1109
- STAR PR #1110: https://github.com/oncoursemail/Star-AI-Project/pull/1110
- STAR PR #1111: https://github.com/oncoursemail/Star-AI-Project/pull/1111
- STAR PR #1112: https://github.com/oncoursemail/Star-AI-Project/pull/1112
- STAR PR #1113: https://github.com/oncoursemail/Star-AI-Project/pull/1113
- STAR PR #1114: https://github.com/oncoursemail/Star-AI-Project/pull/1114
