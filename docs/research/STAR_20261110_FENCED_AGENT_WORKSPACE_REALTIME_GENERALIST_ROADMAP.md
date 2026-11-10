# STAR 2026-11-10 — Fenced Agent Workspace, Real-Time Learning, and Generalist Roadmap

## Executive summary

This update advances PR #1112's durable, lease-fenced agent coordinator by adding a **transactional virtual-artifact workspace**.

Before this change, the durable coordinator intentionally rejected every task with declared write scopes. A coordinator-only lease check is not enough to protect an external file or service: the resource receiving a write must validate the current owner/fence itself.

The new workspace makes SQLite the protected resource for a deliberately bounded first step:

- A task can write only inside its immutable `Task.writes` scopes.
- The current unexpired lease and monotonically increasing fencing token are checked inside the same `BEGIN IMMEDIATE` transaction as the artifact update.
- Existing artifacts require a SHA-256 compare-and-swap precondition.
- Commit IDs are idempotent and cannot be reused for different content or ownership.
- Artifacts from another task are not readable or replaceable until that writer task completes.
- Paths are normalized as relative POSIX keys; traversal, backslashes, drive prefixes and control characters are rejected.
- Per-file, per-run byte and file-count budgets bound database growth.
- SQLite schema v2 is migrated to v3 without deleting the run/task ledger.

This is a **virtual workspace**, not a filesystem/Git/Roblox writer. Workers must not receive the database path or direct SQL access. No host files, Git refs, game places, OBS, microphones, TTS devices, model weights or live player sessions are modified.

## Research synthesis

### 1. Resource-side fencing and transactional writes

A lease expiry does not physically stop a paused or partitioned worker. A fencing token is useful only when the protected resource rejects stale tokens. PR #1112 already uses monotonically increasing tokens for the result ledger; this update extends the same principle to artifact commits.

SQLite documents serializable transactions by serializing writers. `BEGIN IMMEDIATE` obtains the write transaction before read/compare/write logic, and WAL permits readers to continue on a consistent snapshot while the writer commits. This lets the workspace validate the lease, compare the expected content digest, store the new bytes, and append the commit receipt as one transaction.

Important operational limits:

- SQLite still has one writer at a time. Keep transactions short; never call a model, network service, game engine or tool while holding one.
- WAL databases must live on a supported local filesystem, not SMB/NFS/cloud-sync folders.
- This is single-host coordination, not a multi-host consensus system.
- Database file permissions and the parent-directory ACL are part of the trust boundary.
- Direct SQL access by a worker would bypass the API-level checks. Keep the database host-owned.

### 2. Agent memory should remember actions and causes, not just dialogue

**AMA-Bench** evaluates long-horizon agent memory over environment/tool trajectories, not only human chat. Its analysis identifies missing causal and objective information as a weakness of similarity-only retrieval. The paper reports 57.22% average accuracy for its AMA-Agent approach, 11.16 points above the strongest baseline in its study.

**MESA** argues that always loading every memory structure wastes context and can introduce noise. It selects a task-dependent subset of evidence structures; its paper reports an 8.5% improvement over its strongest baseline while using 41% fewer evidence tokens than an all-structure alternative.

Implications for STAR:

- Store action → observation → outcome → causal explanation as structured episodes.
- Preserve provenance, time, project/game version and confidence.
- Retrieve a task-specific mixture of episodic, procedural, semantic and project memory.
- Use a cheap first-stage filter, then rerank only a small candidate set.
- Revalidate code, symbols, files and tests before reusing historical implementation claims.
- Measure memory-on versus memory-off with identical models, prompts, tools, budgets and graders.
- Track both transfer gains and interference on unrelated tasks.

### 3. Real-time gameplay requires asynchronous perception/reason/action

**LOLPlay** evaluates screenshot-and-input agents in native League of Legends. Its 36 tasks use 82 executable subgoal checks. In its reported experiments, the strongest task success rate was 25%, subgoal success was 40.3%, and higher reasoning effort did not improve results. The authors describe actions executing after the observed scene had already changed.

**ROAR** studies multimodal agents in multiplayer action-shooter environments under real-time constraints. Its asynchronous environment interface separates environment evolution from agent reasoning, rather than pausing the world while a model thinks.

Implications for STAR Gamer:

- Keep a short action loop and a separate slower strategic loop.
- Timestamp every screenshot/state observation and expire actions derived from stale observations.
- Use game-specific adapters and permission-scoped input tools.
- Train/evaluate reflex, tactical, strategic and learning policies separately.
- Record action, observed state, result, reward/subgoal and failure cause.
- Use held-out maps, patches and scenarios to test generalization.
- Never treat a successful API call as proof that the intended in-game outcome occurred.

### 4. Game creation needs visual execution feedback

**GameDevBench** contains 333 Godot 4.4.1 tasks across 2D graphics/animation, 3D graphics/animation, UI and gameplay logic. Its paper reports that visual feedback improved one GPT-5.4 configuration from 41.1% to 52.0%. The upstream benchmark README lists stronger agent-plus-harness configurations, but those are not model-only scores and should not be treated as STAR targets.

Roblox's official Studio announcement describes a plan/build/test workflow, a built-in MCP server and a playtesting agent that can inspect code/data models, read logs and use a test character to validate gameplay against the original plan.

Implications for STAR Creator:

- Inspect the project and relevant scene objects before edits.
- Produce a plan with explicit acceptance checks.
- Keep Roblox, Godot, Unity and Blender evaluations separate.
- Capture before/after screenshots or video and compare against expected visual states.
- Run engine checks, playtests and regression scenarios.
- Treat asset generation, script correctness, runtime behavior and visual quality as separate grading dimensions.
- Use private test places/projects by default; publishing and live-player actions require explicit owner authorization.

### 5. VTuber quality is a multi-objective real-time system

Full-Duplex-Bench v3 uses real human speech with disfluencies and chained tool-use tasks. It evaluates accuracy, latency and turn-taking separately. This supports a multi-lane evaluation for STAR's live performance rather than one generic "human-like" score.

Recommended streaming measures:

- time to first audible response (not only model TTFT);
- end-of-turn precision/recall and false-interruption rate;
- interruption stop latency and unheard-speech truncation;
- multi-speaker attribution and addressed-to-agent precision;
- silence preservation and unsolicited interjection rate;
- voice/avatar lip-sync error and expression timing;
- factual/tool-use accuracy;
- stream continuity and viewer-context recall;
- game FPS/frame-time percentiles, OBS dropped frames and audio underruns.

Human-like quality should mean natural timing, expressive but consistent personality, good listening, context awareness and appropriate silence. STAR should remain transparently identified as an AI performer.

### 6. Local inference speed must be measured by workload

The official llama.cpp documentation describes speculative decoding (draft models, EAGLE-3 and n-gram variants) and server timing fields for prompt processing and token generation. These techniques can improve some workloads, but draft acceptance and isolated tokens/second are not sufficient evidence of end-to-end benefit.

Recommended RTX 4060/8 GB evaluation matrix:

- prompt-prefix cache on/off;
- speculative decoding off versus compatible draft/ngram modes;
- quantization and GPU-layer sweeps;
- CPU thread and batch-thread sweeps;
- context-length and KV-cache pressure;
- small/fast model versus deep model routing;
- one live stream versus game + OBS + avatar + TTS + vision + background agents.

Record TTFT, time-to-first-audio, inter-token latency, p50/p95 completion latency, accepted draft tokens, tokens/sec, VRAM peak, system RAM, GPU utilization, game frame times, OBS drops and audio underruns. Change one factor at a time and pin model/runtime versions. Do not assume a benchmark on another GPU or accelerator transfers to STAR's hardware.

## Implemented in this PR

### Coordinator schema v3

Adds:

- `artifacts`: current virtual artifact content, digest, version and writer fence.
- `artifact_commits`: immutable commit receipts keyed by run and commit ID.
- schema migration from v2 to v3.

### API

- `commit_artifact(lease, resource, content, commit_id, expected_sha256=None)`
- `read_artifact(lease, resource)`

The commit path performs current-lease validation, scope enforcement, content digest calculation, compare-and-swap, quotas, artifact update and commit-receipt insert in one SQLite write transaction.

### Budgets

- 4 MiB maximum per artifact.
- 64 MiB maximum artifact bytes per run.
- 256 artifacts maximum per run.
- 500-character maximum resource key.
- UTF-8 text or raw bytes accepted.
- SHA-256 integrity checked on read.

### Publication semantics

A task may inspect its own workspace artifacts across lease retries, which allows a replacement attempt for the same immutable task to resume from staged work. Other tasks cannot read or replace those artifacts until the writing task reaches durable `completed`. This avoids accidentally treating partial output from a failed worker as a published dependency.

## Tests added or updated

- Initial scoped artifact commit and read.
- SHA-256 compare-and-swap.
- Idempotent commit retry and commit-ID collision.
- Stale lease rejection after reclaim/fence increment.
- Failed writer output remains unpublished.
- Completed writer output becomes visible to dependent reader.
- Path traversal, Windows path and out-of-scope rejection.
- File size limit and digest corruption detection.
- Run-to-run artifact isolation.
- v2 → v3 schema migration.
- Existing coordinator write-scope test updated to exercise the new gateway.

## What this does not do

- It does not materialize virtual artifacts onto disk.
- It does not modify Git, Roblox Studio, game files, assets, model weights or stream devices.
- It does not launch or stop worker processes.
- It does not provide multi-machine consensus.
- It does not authenticate a malicious process with direct database access.
- It does not itself improve model intelligence, gameplay skill, voice naturalness or inference speed.

## Next engineering stages

1. Add a host-owned workspace materializer that accepts only verified artifact versions and uses filesystem-level CAS/atomic replacement.
2. Keep staging workspaces isolated per task; promote only after tests and independent review.
3. Add a durable process supervisor with process-group/job-object termination acknowledgements.
4. Add a read-only game observation adapter with observation timestamps and stale-action rejection.
5. Build a private Roblox/Godot benchmark runner with reproducible fixtures and visual evidence.
6. Add an asynchronous memory evidence selector and causal episode schema; compare against AMA-Bench-style action traces.
7. Add a full-duplex VTuber rehearsal harness and multi-party evaluation set.
8. Run a mixed-load hardware benchmark on the actual Windows RTX 4060 machine before changing inference defaults.

## References

- AMA-Bench: https://arxiv.org/abs/2602.22769
- MESA: https://arxiv.org/abs/2608.10108
- LOLPlay: https://arxiv.org/abs/2611.03685
- ROAR: https://arxiv.org/abs/2610.24282
- GameDevBench: https://github.com/waynchi/gamedevbench
- Roblox Studio agentic workflows: https://about.roblox.com/newsroom/2026/04/roblox-studio-going-agentic
- Roblox Studio MCP/playtest automation: https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643
- Full-Duplex-Bench v3: https://arxiv.org/abs/2604.04847
- llama.cpp speculative decoding: https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md
- Python asyncio cancellation: https://docs.python.org/3.13/library/asyncio-task.html
- SQLite isolation: https://www.sqlite.org/isolation.html
- SQLite transactions: https://www.sqlite.org/lang_transaction.html
