# STAR AI — Host-Owned Artifact Staging and Real-Time Generalist Acceptance

**Date:** 2026-11-10  
**Status:** Research and implementation proposal; staging code is opt-in and not connected to production workers.

## Executive summary

STAR now has a draft chain for bounded async cancellation (#1111), durable local lease/fencing coordination (#1112), and a SQLite virtual artifact workspace (#1113). The virtual workspace protects logical writes, but it deliberately does not materialize them into files. This increment adds a host-owned export boundary: only artifacts from a fully successful run can be staged, the destination is a dedicated directory outside Git worktrees, and replacement requires an explicit SHA-256 compare-and-swap.

This is a deliberately narrow step. It does not let model-generated code write to the source checkout, publish Git commits, modify Roblox places, launch processes, or control a stream.

## 1. Research findings and architectural implications

### 1.1 Atomic replacement is not the same as safe authorization

Python documents that os.replace() replaces a file and is atomic on POSIX when successful, but may fail across filesystems. That gives a useful visibility boundary when the temporary file is created in the destination directory. It does not by itself validate the caller, prevent path traversal, establish durability, or protect against an untrusted process racing the destination.

Implementation implications:
- create the temporary file in the same destination directory;
- write and flush the complete payload;
- fsync the file before replacement;
- perform os.replace only after rechecking the expected destination digest;
- fsync the parent directory on POSIX;
- keep the staging root private and host-owned;
- reject symlinks and all paths outside the fixed root;
- require an expected digest to replace any existing different file.

Python source: https://docs.python.org/3/library/os.html#os.replace

### 1.2 Windows process supervision should use OS-owned process groups

Microsoft's Job Objects API can group processes, inherit association to child processes created with CreateProcess by default, impose resource limits, collect accounting information, and terminate all processes in a job. JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE can terminate associated processes when the last job handle closes.

Important caveat: child processes created through some alternate mechanisms may not join the job, and breakaway flags change the process-tree guarantee. STAR's future Windows supervisor must verify assignment and process exit rather than assuming that closing an asyncio task or parent process stopped every child.

Windows source: https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects

### 1.3 Voice quality needs four separate acceptance dimensions

InteractionBench (published 2026-11-02) evaluates conversational timing, spoken-task accuracy, whisper/volume control, and groundedness over conversations longer than twenty turns. It uses 221 items across thirteen scenarios and measures timing where the client hears the audio, so network delay is included for hosted systems.

Implication for STAR's VTuber acceptance:
- measure first audible sample at the viewer/client, not only model-server timestamps;
- grade spoken task correctness separately from turn timing;
- test volume/delivery controls from the waveform;
- test groundedness after long conversations;
- retain the existing MP-Bench and Full-Duplex-Bench turn-taking tracks rather than collapsing them into one score.

Sources:
- https://arxiv.org/abs/2611.02430
- https://www.fullduplex.ai/benchmarks/interactionbench
- https://www.fullduplex.ai/benchmarks/mp-bench
- https://arxiv.org/abs/2604.04847

### 1.4 Game mastery needs state-verifiable and real-time tracks

GameWorld separates binary task success from normalized progress and reads serialized game state rather than relying only on screenshots or an LLM judge. Its GameWorld-RT variant keeps the environment moving while inference runs. Those are different conditions and should be reported separately.

Implication for STAR Gamer:
- score success and progress from authoritative game state where available;
- preserve a visual-only track for games without state APIs;
- add a real-time track where the world continues during reasoning;
- expire observations and actions when their scene/version is stale;
- measure action latency and progress under the same fixed game seed/scenario;
- report skill transfer on unseen maps or mechanics separately from training-task success.

Source: https://gameworld-project.github.io/  
Paper: https://arxiv.org/abs/2604.07429

### 1.5 Inference speed must remain tied to quality

STAR already has separate draft work for read-only llama.cpp server metrics (#1101) and a model quality/speed evidence gate (#1102). This increment intentionally does not duplicate those components or claim an inference gain.

The next performance report should join:
- prompt/prefill time;
- decode/inter-token time;
- client-visible first text;
- first audible PCM;
- end-to-end completion;
- game frame-time p50/p95;
- OBS render/network drops;
- audio underruns;
- VRAM/RAM/CPU pressure;
- task quality and held-out pass rate.

A faster model is not an improvement if it causes worse game decisions, more false interruptions, or unstable streaming.

## 2. Implemented host boundary

### Coordinator export API

AgentRunCoordinator.read_completed_artifact(run_id, resource):
- is host-only; it accepts no worker lease;
- refuses export unless finish_run() marked the entire run completed;
- checks that the artifact writer task is completed;
- checks that the writer's completion fence equals the artifact fence;
- verifies the writer's persisted contract declared the resource in its write scope;
- verifies the latest artifact commit receipt matches task, resource, fence, version and digest;
- recomputes SHA-256 over the stored bytes.

### Staging materializer

star/agent_artifact_materializer.py:
- requires an explicitly initialized dedicated staging root;
- refuses roots inside a Git worktree;
- rejects symlinked path components, target symlinks and path traversal;
- writes only to root/run_id/resource;
- uses same-directory temporary files, file fsync, atomic os.replace, POSIX directory fsync;
- creates files with owner-only permissions on POSIX;
- makes identical exports idempotent;
- refuses to replace a different existing file unless its exact current SHA-256 is supplied;
- serializes calls through one in-process materializer instance.

### Deliberate boundaries

- This is a single-host, single-writer staging tool.
- On Windows, the host must provision a private ACL; portable Python cannot reliably inspect the DACL.
- The staging root must not be shared with model-generated code or untrusted workers.
- It does not provide cross-process locking, multi-host consensus, source-checkout writes, Git commits, Roblox publishing, process launch/termination, OBS/TTS control, or model routing.
- It does not make the model smarter or faster by itself.

## 3. Next architecture stages

1. Windows Job Object supervisor: create a job before worker launch, assign the process before allowing untrusted task execution, set explicit resource/time limits, capture exit status, and verify the full process tree is empty before releasing leases.
2. Crash-recoverable promotion journal: record intended staging promotion, expected source digest, artifact digest, and completion receipt; recover idempotently after a host crash.
3. Independent review gate: static checks, unit tests, engine launch, visual inspection, and task-specific acceptance before any source-tree promotion.
4. Roblox/Godot runners: separate game-creation benchmarks from game-mastery benchmarks; use private test places/projects and no live publication.
5. Generalist learning: preserve causal action-observation-outcome traces, retrieve by task similarity and recency, and evaluate transfer/interference/retention on held-out tasks.
6. VTuber rehearsal: InteractionBench-style client-audible timing, multi-party floor control, long-context groundedness, avatar/PCM sync, and viewer-safe disclosure.
7. Mixed-load inference: paired quality/speed experiments under actual game + OBS + TTS + avatar + background-research load.

## 4. Acceptance criteria

Before this materializer is enabled in a host worker pipeline:
- all focused tests pass on Linux and Windows;
- the full repository suite and static checks pass;
- symlink, path traversal, digest mismatch and crash-retry tests pass;
- Windows staging ACLs are verified by the host installer;
- staging root is outside every checkout and inaccessible to workers;
- only fully completed runs can export;
- no automatic Git commit or production deployment is enabled.

## 5. References

- Python os.replace: https://docs.python.org/3/library/os.html#os.replace
- Python temporary files: https://docs.python.org/3/library/tempfile.html
- Windows Job Objects: https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects
- InteractionBench (2026-11-02): https://arxiv.org/abs/2611.02430
- MP-Bench: https://www.fullduplex.ai/benchmarks/mp-bench
- Full-Duplex-Bench v3: https://arxiv.org/abs/2604.04847
- GameWorld: https://gameworld-project.github.io/
- GameWorld paper: https://arxiv.org/abs/2604.07429
- Realtime-Venus: https://arxiv.org/abs/2609.13814
- llama.cpp server metrics: https://github.com/ggml-org/llama.cpp/tree/master/examples/server
- STAR PR #1101: https://github.com/oncoursemail/Star-AI-Project/pull/1101
- STAR PR #1102: https://github.com/oncoursemail/Star-AI-Project/pull/1102
- STAR PR #1107: https://github.com/oncoursemail/Star-AI-Project/pull/1107
- STAR PR #1108: https://github.com/oncoursemail/Star-AI-Project/pull/1108
- STAR PR #1109: https://github.com/oncoursemail/Star-AI-Project/pull/1109
- STAR PR #1110: https://github.com/oncoursemail/Star-AI-Project/pull/1110
- STAR PR #1111: https://github.com/oncoursemail/Star-AI-Project/pull/1111
- STAR PR #1112: https://github.com/oncoursemail/Star-AI-Project/pull/1112
- STAR PR #1113: https://github.com/oncoursemail/Star-AI-Project/pull/1113
