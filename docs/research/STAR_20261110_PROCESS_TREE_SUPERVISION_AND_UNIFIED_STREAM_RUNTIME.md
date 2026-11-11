# STAR — Process-Tree Supervision, Real-Time Streaming and Generalist Intelligence Research

**Research snapshot:** 2026-11-10  
**Implementation branch:** `feat/process-tree-supervision-20261110-auto11`  
**Stacked on:** cross-lane rehearsal PR #1116  
**Scope:** worker lifecycle correctness, interactive latency protection, VTuber behavior, game mastery, game creation, memory and local inference.

## Executive finding

The `star/next` development branch already contains substantial specialist systems: agent-fleet orchestration, an ACP adapter, a P0–P3 inference scheduler, stream hardware telemetry/QoS, a stream director and event timeline, VTube/stream hosts, game-learning and transfer evaluators, and a signed cross-lane rehearsal gate in PR #1116.

The highest-value gap found in this pass was lower-level than another model or agent: **worker cancellation did not consistently own the worker's entire process tree**. A CLI or ACP worker could exit while a browser, compiler, renderer, model helper or other descendant continued consuming CPU/RAM/GPU resources. A descendant could also keep a captured stdout pipe open after the root process exited. That is especially harmful when Star is trying to preserve interactive voice, game and OBS latency.

This increment adds cross-platform process-tree supervision and wires it into both the direct agent-fleet runner and the ACP adapter. It does not claim to make a model intrinsically smarter or faster; it makes cancellation and resource release more reliable so background work is less likely to interfere with the live path.

---

## 1. Implementation delivered

### 1.1 New module: `star/process_supervisor.py`

A single lifecycle abstraction now supports:

- POSIX: launch a worker in a new session/process group; terminate the whole group, not only the leader PID.
- Windows: create a Job Object, enable `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`, attach the Star-owned worker PID, terminate the job as a unit, and query active-process accounting.
- Sync and asyncio launch helpers.
- Explicit `mode` and bounded error diagnostics.
- `require_tree=True` for callers that must fail closed if tree containment cannot be established.
- A safe default fallback mode (`root_only`) when Windows Job Object assignment is refused, rather than silently claiming tree containment.
- Bounded `wait_empty` validation; no unbounded waits.
- No CPU, memory, affinity or priority caps are applied by default.

### 1.2 Agent fleet integration

`star/agent_fleet.py` now starts direct commands through the managed-process helper. Cancellation and timeout terminate the process group/job. When the root process exits, the supervisor closes the group/job **before** joining the stdout reader. This prevents a child that inherited stdout from keeping the pipe open and leaving a worker behind.

### 1.3 ACP integration

`star/acp_adapter.py` now starts the ACP child through the async managed-process helper. Session teardown terminates the worker tree and then closes the supervisor. Protocol-level turn cancellation remains distinct from process teardown; the adapter does not kill a reusable session merely because one turn was interrupted. Fleet-owned `run_turn` teardown still releases the complete process tree.

### 1.4 Regression coverage

New `tests/test_process_supervisor.py` covers:

- Windows Job Object lifecycle through an injected fake Win32 API.
- Assignment failure and root-only fallback.
- Fail-closed behavior when `require_tree=True`.
- Invalid wait bounds.
- POSIX sync cleanup after the root exits but a descendant remains.
- POSIX sync cancellation of descendants.
- POSIX asyncio cancellation of descendants.

Additional integration regressions were added to `tests/test_agent_fleet.py` and `tests/test_acp_adapter.py` to prove that descendants are cleaned up through the actual fleet and ACP entry points.

**Local focused validation:** 8/8 Linux-runnable process-supervisor tests passed in an isolated environment. A Windows-only native acceptance test now starts a worker, waits for Job Object assignment, creates a child, then verifies active-process accounting reaches zero after termination. The Windows-only test is skipped on Linux; it still requires the repository's gated Windows acceptance run.

---

## 2. Windows Job Object research and an important limitation

Microsoft documents Job Objects as a way to manage process groups as a unit. A job can terminate all associated processes, apply limits and expose aggregate resource accounting. By default, children created through `CreateProcess` inherit the job unless breakaway limits are enabled. Closing the last handle with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` terminates all associated processes. Nested jobs are supported from Windows 8 / Server 2012 onward.

Sources:

- https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects
- https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-assignprocesstojobobject
- https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-setinformationjobobject
- https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-queryinformationjobobject

**Current limitation:** this first implementation attaches the Job Object immediately after `Popen` / `asyncio.create_subprocess_exec` returns. A child spawned in the very small interval before assignment could escape the Job Object. The code does not claim race-free Windows containment.

The next Windows hardening step is a native `CreateProcessW` launcher using `STARTUPINFOEX` and `PROC_THREAD_ATTRIBUTE_JOB_LIST`, which Microsoft documents as supported on Windows 10 and newer / Server 2016 and newer. That assigns the Job Object at process creation rather than after launch:

- https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-updateprocthreadattribute

The current implementation intentionally does not enable CPU-rate, memory, working-set or affinity limits. Those controls can make an interactive stream worse if configured without measurements. First collect per-job CPU time, active-process count, memory and I/O; then use soft admission/scheduling budgets and only test hard caps in an isolated benchmark.

---

## 3. Runtime architecture: protect the live path

Star should treat the live stream as a latency-sensitive workload, not just another agent task.

Recommended scheduling tiers:

| Tier | Work | Policy |
|---|---|---|
| P0 | Audio capture/playback, game input, emergency stop, OBS health | Reserved capacity; lowest queue delay |
| P1 | Viewer addressing, turn-taking, short replies, avatar reactions | Small bounded latency budget |
| P2 | Gameplay planning, scene commentary, current stream context | Preemptible at safe checkpoints |
| P3 | Research, coding, asset generation, memory consolidation | Background; pause/cancel when P0/P1 pressure rises |

The existing priority proxy and resource planner are the right foundations. The new process-tree layer closes one lifecycle gap: when a P2/P3 worker is cancelled, its descendants should not continue competing with P0/P1.

Do not equate higher raw tokens/second with better stream performance. Measure the whole mixed workload:

- First-audible-response latency and p50/p95/p99.
- ASR partial/final latency and end-of-turn detection delay.
- TTS first-chunk latency, audio underruns and playback queue depth.
- Game input-to-action delay and frame-time percentiles.
- OBS render/encode lag and dropped frames.
- CPU, RAM, VRAM, GPU utilization, disk I/O and active worker-process count.
- Background task completion and cancellation latency.

A model configuration is an improvement only if quality stays within the agreed regression bound **and** the live-path latency/stream health improves or remains stable.

---

## 4. Local inference: benchmark before changing model settings

The upstream `llama.cpp` SPEED-Bench client benchmarks an already-running `llama-server`. It reports per-category prompt throughput, decode throughput, average request latency and speculative-draft acceptance. Its documentation recommends matching benchmark concurrency to the server's slot count (`--np`) for throughput measurements and comparing baseline/speculative runs with identical prompts and settings.

- https://github.com/ggml-org/llama.cpp/tree/master/tools/server/bench/speed-bench
- https://github.com/ggml-org/llama.cpp/blob/master/docs/moe-cache.md

The MoE cache can keep frequently used experts in device memory while other experts remain in host memory. The documented CPU-share option can help only when host RAM access is faster than uploading missed experts over PCIe for the actual machine/model configuration. It is not a universal speed switch.

Recommended experiment order for the RTX 4060 8 GB class machine:

1. Establish baseline TTFT, prompt t/s, decode t/s, p95 latency and quality on representative Star prompts.
2. Measure the same server with realistic concurrency and long-context requests.
3. A/B stable prompt-prefix reuse and KV-cache/context policies.
4. A/B speculative decoding with identical prompt sets and output budgets.
5. For MoE models only, sweep expert-cache size and CPU share while measuring PCIe, RAM and VRAM pressure.
6. Repeat while OBS, the game, voice and avatar are active.
7. Keep a setting only if the mixed-workload result is better; otherwise revert.

No inference speed gain is claimed by this PR.

---

## 5. VTuber streaming: naturalness is a multi-party control problem

A convincing AI streamer should be socially fluent, expressive and context-aware while remaining transparent that she is AI. “More human” should mean better timing, attention, humor, continuity, listening and reactions—not fabricated claims of consciousness or human identity.

### New benchmark signals

- **TurnBench:** 154 two-channel conversations, about 30 hours and 106 speakers; scores end-of-turn/interruption recall, false-positive rate and detection latency.
  - https://github.com/SesameAILabs/turnbench
- **MP-Bench:** Findings of EMNLP 2026; evaluates voice agents as participants in multi-party conversations. Across 12 agents, real-time systems were at or below 22% on multi-party comprehension and near chance on turn-taking.
  - https://aclanthology.org/2026.findings-emnlp.1437/
- **Duplex-MPE:** 2,000 scenarios with three or four human speakers plus an assistant; tests explicit versus implicit addressing, answer accuracy, silence preservation and stopping when a human has already resolved the request.
  - https://arxiv.org/abs/2609.31948
- **Model Interruption Bench:** EMNLP 2026; turn-based error recognition reached 59–67% for the strongest systems, while real-time mid-speech interruption true positives fell below 10% in the evaluated setup. Recognizing an error is not the same as interrupting correctly in time.
  - https://aclanthology.org/2026.emnlp-main.2349/

### Design implications

1. Separate **speaker detection**, **addressee inference**, **turn-state estimation** and **response policy**.
2. Give the policy an explicit “stay silent” action. Silence is often the correct response when two viewers are talking to each other.
3. Use confidence thresholds and a short confirmation window before interrupting; allow fast barge-in for safety or direct address only.
4. Preserve an event timeline linking audio spans, speaker IDs, chat messages, game events, avatar actions and OBS scene changes.
5. Make interruption recovery stateful: remember what was already spoken, acknowledge the interruption, answer it, then resume only the unspoken portion.
6. Evaluate on real multi-speaker audio, not transcript-only turn-taking tests.

### Avatar and broadcast integration

- VTube Studio exposes a local WebSocket API (default port 8001); plugin API access must be explicitly allowed in the app. Use a configurable localhost endpoint and least-privilege plugin requests.
  - https://github.com/DenchiSoft/VTubeStudio
- OBS WebSocket is included with OBS Studio 28+; OBS recommends password protection for remote control.
  - https://obsproject.com/kb/remote-control-guide

Keep OBS/VTube Studio control local, authenticated and allowlisted. A viewer message must never be able to issue arbitrary scene/source/file/process commands.

---

## 6. Game mastery and autonomous game creation

### Game playing

Use real-time, closed-loop evaluation. The game must continue advancing while Star perceives, reasons and acts. Measure:

- Objective completion and survival, not only win rate.
- Input-to-action latency and missed action windows.
- Movement/aiming/navigation efficiency.
- Resource use and avoidable damage/deaths.
- Performance across new maps, seeds and rule variations.
- Transfer to an unfamiliar game with related mechanics.

Keep a skill curriculum: observe controls → solve a constrained task → practice → diagnose failure → change one strategy → retest → transfer. Store the successful procedure as a versioned procedural skill only after held-out evaluation.

Useful starting benchmark: GameWorld's browser-game tasks and real-time track (34 games / 170 tasks in the published benchmark snapshot):
- https://gameworld-bench.github.io/

### Game creation

The current GameDevBench repository describes 333 tasks for modern game-engine development. Its findings emphasize that graphics/asset tasks remain difficult and that image/video feedback can materially improve agent results. This supports a mandatory visual feedback loop for Star Creator:

1. Read project/code/assets.
2. Form a plan and expected visual result.
3. Implement one bounded change.
4. Launch the actual game/engine.
5. Capture screenshots or short clips and inspect logs/state.
6. Compare observed output to expected output.
7. Fix the defect and rerun regression tests.
8. Verify on an unseen scene/map where possible.

- https://github.com/waynchi/gamedevbench
- https://arxiv.org/abs/2602.11103

Do not promote a game build because it compiles. Require runtime, visual, gameplay, performance and regression evidence.

---

## 7. General intelligence and memory

Recent research points toward evaluating memory by downstream utility and transfer, not by the amount of information retained.

- **MemGym** separates memory performance from reasoning/retrieval/tool-use confounders across dialogue, deep research, coding and computer-use regimes:
  - https://arxiv.org/abs/2605.20833
- **HELM** treats memory as epistemically governed: provenance, freshness, consistency, recency and evidence state are part of retrieval:
  - https://aclanthology.org/2026.emnlp-main.721/
- **Long-Term Agent Memory through Complementary Curation and Consolidation** reports complementary episodic and relational memory on LoCoMo and LongMemEval-S:
  - https://arxiv.org/abs/2610.39790
- **The Epistemics of Agent Memory** shows why consolidation needs reversibility, poison resistance and auditability, and cautions that a consolidation score is not automatically a valid predictor of real transfer:
  - https://arxiv.org/abs/2609.33013

Recommended memory record:

`{kind, claim_or_skill, source_refs, observed_at, valid_from, valid_until, confidence, epistemic_state, dependencies, version, test_refs}`

Keep six complementary stores:

- Semantic: facts and concepts.
- Episodic: what happened, when and in which environment.
- Procedural: reproducible skills and workflows.
- Causal: action → outcome → explanation.
- Working: current task/stream state.
- Project: code architecture, decisions, constraints and versions.

Retrieval should filter by provenance, freshness, contradiction and project version before ranking by semantic similarity. Consolidation should be reversible and evaluated on held-out transfer tasks. Do not let an untrusted viewer message, web page or model-generated claim become trusted permanent knowledge without evidence.

### General-knowledge engine

Build a source-grounded knowledge service rather than treating the model's parametric knowledge as a live encyclopedia.

1. **Ingestion:** accept approved web pages, API references, PDFs, books, videos/transcripts, images and structured datasets. Preserve canonical source URL/ID, author/publisher, publication/update date, retrieval time, content digest and license/access constraints.
2. **Claim extraction:** store atomic claims with subject, predicate, object, time interval, source span, confidence and epistemic state. Keep competing claims rather than silently overwriting disagreements.
3. **Temporal validity:** use domain-specific freshness windows (for example, software APIs/prices/weather need short windows; stable mathematics needs long windows). Revalidate volatile facts before answering.
4. **Hybrid retrieval:** combine lexical search, embeddings, metadata filters and graph traversal. Retrieve source evidence first, then ask the reasoning model to synthesize it; do not let similarity alone promote a claim.
5. **Answer discipline:** cite claims, separate verified facts from inference, state uncertainty, and abstain when sources conflict or are stale. Maintain a correction trail when a later source supersedes an earlier one.
6. **Practice and transfer:** turn knowledge into short tasks, explain-back exercises and unfamiliar applications. A fact is learned only when STAR can use it correctly in a new context, not merely repeat its stored wording.
7. **Evaluation:** score factual accuracy, citation support, temporal correctness, contradiction handling, abstention calibration and cross-domain transfer separately. Keep a held-out set so retrieval tuning does not overfit the questions used to build memory.

Useful domain coverage for the initial knowledge graph: mathematics, science, history, geography, programming, engineering, art/music, language, game design, game engines, 3D production, networking and computer operations. For fast-changing topics, route through fresh research; for stable topics, prefer curated reference material and verified lessons. Keep the knowledge graph, episodic memories and procedural skills linked but separately governed.

---

## 8. Prioritized follow-on roadmap

| Priority | Work | Acceptance evidence |
|---|---|---|
| 1 | Windows creation-time Job Object launcher using `PROC_THREAD_ATTRIBUTE_JOB_LIST` | Child cannot escape between process creation and assignment |
| 2 | Add process-tree mode, active count and CPU/I/O accounting to worker receipts | Every run records containment mode and bounded cleanup |
| 3 | Feed worker lifecycle into resource admission | P2/P3 cancellation releases resources before P0/P1 latency degrades |
| 4 | Unified audio/chat/game/OBS/VTube event timeline | Correct event ordering and addressee attribution on replay |
| 5 | Multi-party stream policy trained/evaluated on TurnBench, MP-Bench and Duplex-MPE | Better turn accuracy without increasing false interruptions; silence preserved |
| 6 | Real-time gameplay harness | Live-clock success, input latency and unseen-map transfer |
| 7 | Game Creator visual feedback loop | Runtime screenshots/video, log checks and regression evidence |
| 8 | llama.cpp mixed-load benchmark suite | Same-prompt baseline/spec comparison with quality guardrails |
| 9 | Governed memory consolidation | Held-out retention/transfer, contradiction and rollback tests |
| 10 | Full 60-minute private stream rehearsal | Stable FPS, p95 voice latency, no audio underruns, no OBS drops, verified task outcomes |

## 9. Safety and validation boundaries

- Only Star-launched worker PIDs are attached to process supervisors; this is not a global process killer.
- The Windows default is a best-effort Job Object attach with explicit `root_only` fallback diagnostics. Use `require_tree=True` where uncontained workers are unacceptable.
- Windows native Job Object execution has not been run on the owner's Windows PC in this increment.
- POSIX process groups are terminated immediately with SIGKILL; graceful TERM→KILL escalation can be added later if a worker needs shutdown hooks.
- CPU/memory/affinity caps remain off until measured.
- No OBS scene, microphone, VTube Studio model, game, GPU workload, livestream or model server was started during this research pass.
- No model-quality, game-skill, tokens-per-second or “human-likeness” improvement is claimed without a measured benchmark.

The goal is a reliable foundation: background agents must stop when Star needs the machine, and the next intelligence improvements must be demonstrated in a real mixed workload rather than inferred from isolated unit tests.
