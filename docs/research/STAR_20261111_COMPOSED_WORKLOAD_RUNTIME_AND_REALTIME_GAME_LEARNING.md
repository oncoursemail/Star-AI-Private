# STAR Research — Composed Workload Admission, Real-Time VTuber Interaction, and Game Learning

**Research date:** 2026-11-11  
**Implementation branch:** `feat/stream-workload-runtime-bridge-20261111`  
**Scope:** Compose existing STAR stream-pressure and resource-admission policies. This is a policy-layer integration, not a Windows hardware adapter or a live streaming activation.

## Executive summary

STAR already has several useful but distinct policy components:

- `StreamLoadGovernor` consumes trusted stream telemetry, applies pressure thresholds and recovery hysteresis, and provides advisory decisions.
- `WorkloadAdmissionController` reserves abstract CPU, RAM, and VRAM allocations with bounded queues, priorities, deadlines, and host-confirmed release.
- `AdaptiveQoS` separately evaluates inference route headroom, recent p95 latency, CPU/GPU slots, and per-job deadlines.
- The stream rehearsal recorder and diagnostics evaluate audible latency, frame timing, avatar synchronization, OBS counters, turn quality, and held-out skill transfer.

The missing piece was a single policy path that carries the existing governor's *freshness, pressure, and active-session state* into the multi-resource reservation controller. Without that bridge, the two systems could disagree: a healthy live stream could look "normal" to the pressure governor while a generic queue admits background research or asset generation.

This update adds `StreamWorkloadRuntime` and refines the lane taxonomy so conversational chat remains responsive while heavy tools and background work are deferred during active streaming or gameplay.

It does **not** inspect hardware, start/stop processes, call models, move game characters, operate OBS/VTube Studio, capture audio, or authorize tools. The host still owns execution and permissions.

## 1. Policy composition

### Layer 1 — host observations and pressure hysteresis

`StreamLoadGovernor` remains the single owner of pressure thresholds:

- game FPS p10;
- voice latency p95;
- OBS dropped-frame percentage;
- free VRAM;
- audio underruns;
- streaming and gaming state.

The new runtime accepts only a `StreamSample` already produced by a trusted host adapter. It requires an explicit trusted-host assertion, a non-future timestamp, and a sample no older than the governor's configured freshness window. It then reuses the governor's existing pressure/hysteresis state instead of copying thresholds into another module.

### Layer 2 — cross-workload resource reservation

`WorkloadAdmissionController` remains responsible for:

- abstract CPU millicore, RAM MiB, and VRAM MiB budgets;
- a protected real-time reserve;
- bounded queue and active lease counts;
- deterministic priority/FIFO ordering;
- queued deadlines and duplicate-request protection;
- fail-closed health handling;
- capacity release only after the host confirms that a worker has stopped.

The new bridge converts the governor result into `HostHealth` and forwards it to the controller. The stricter freshness limit wins: a sample that is too old for the governor is marked degraded even if the controller's own health window is longer.

### Layer 3 — inference-specific QoS

`AdaptiveQoS` remains a separate inference-only gate. It is responsible for measured per-route p95 completion time, CPU/GPU slots, RAM/VRAM headroom, game-active calibration, deadlines, and quarantining expired workers.

The host should apply both the cross-workload resource lease and the inference-specific QoS decision before starting an inference worker. A resource lease alone is not a model route or an execution permission. Do not collapse the two systems into a single guessed "AI score."

### Lane policy

| Lane | Active stream/game | Degraded host | Reason |
|---|---|---|---|
| Audio | Protected | Protected | Keep playback path responsive |
| Game control | Protected | Protected | Preserve deadline-sensitive control; action gate still required |
| Voice | Protected | Protected | Keep conversational response path available |
| Avatar | Protected | Protected | Preserve already-authorized animation work |
| Chat | Protected | Protected | Keep viewer/user conversation responsive |
| Interactive tools | Deferred | Deferred | Avoid expensive file, browser, and tool work during active play |
| Research | Deferred | Deferred | Background research can wait |
| Learning | Deferred | Deferred | Consolidation should not compete with a live session |
| Asset generation | Deferred | Deferred | Rendering/generation is expensive and nonurgent |

When the machine is idle and healthy, all lanes can compete under the explicit resource budget. During an active stream or game, only the latency-sensitive lanes and chat can use the scheduler. When pressure or telemetry staleness is detected, all nonprotected lanes are blocked. Chat is protected from health gating but cannot consume the hard real-time reserve; only audio, game control, voice, and avatar lanes can use that reserved slice. These classifications do not grant microphone, game, OBS, VTube Studio, file, network, or broadcast permissions.

The two diagnostic counts `deferred_for_health` and `deferred_for_active_session` can overlap. They answer different questions: one is blocked by degraded/stale measurements, the other by an active stream/game policy.

## 2. Why separate fast and slow loops

Real-time environments continue changing while an agent reasons. A single long reasoning loop can produce an action that is already stale when it arrives.

### Evidence: LOLPlay (2026-10-25)

LOLPlay evaluates screenshot-and-input agents in native League of Legends across 36 champion-specific tasks and 82 executable subgoal checks. The paper reports that higher reasoning effort did not improve the tested models' task/subgoal success, while longer requests left fewer interaction rounds and trajectories included actions executing after the observed scene changed.

**STAR implication:** keep a bounded fast loop for fresh observations, immediate control, voice interruption, and avatar response. Run long-horizon strategy, research, memory consolidation, and creator planning asynchronously. Every delayed game action should be tied to a fresh observation epoch and revalidated by the host immediately before submission.

Source: https://arxiv.org/abs/2611.03685

### Evidence: MechEval and WARC (2026-11-09)

The WARC paper studies learning unseen game mechanics from limited exposures. Its 35M-parameter world model updates during interaction and is evaluated on 69 recurring mechanics across 20 ARC-AGI-3 games. The authors report that four in five mechanics reached at least 80% prediction accuracy on held-out games, with a graph explorer improving the public-game efficiency score from 0.15 to 0.46.

**STAR implication:** use a compact, separately versioned transition/world model or skill artifact to learn game mechanics. Do not directly mutate the main assistant's weights during a livestream. Require held-out prediction and action tests, versioned artifacts, rollback, and comparison against a frozen baseline before reusing a learned mechanic.

Source: https://arxiv.org/abs/2611.12324  
Code and weights: https://github.com/third-intelligence/WARC

### Evidence: SIMA 2

SIMA 2 combines high-level language goals, reasoning, visual observations, and goal-directed actions in 3D virtual worlds. It is a useful reference for connecting abstract objectives to grounded actions, but its published results do not imply that a small local STAR model will inherit the same capability.

**STAR implication:** represent gameplay as explicit objectives, observable subgoals, action proposals, fresh observations, and environment-confirmed outcomes. Keep commentary separate from control decisions.

Source: https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/

## 3. Natural multiparty VTuber behavior

### Evidence: MP-Bench (Findings of EMNLP 2026)

MP-Bench evaluates voice agents as active participants in multi-party conversations, measuring turn-taking awareness, response appropriateness, and comprehension. Its reported evaluation of 12 agents found that real-time agents scored at or below 22% on multiparty comprehension and near chance on turn-taking.

**STAR implication:** evaluate group conversation behavior separately from ordinary one-user chat. Add tests for whether Star should speak, use a short backchannel, or remain silent; measure who is addressing her, response appropriateness, missed turns, false interruptions, and duplicate responses independently.

Source: https://aclanthology.org/2026.findings-emnlp.1437/

### Evidence: LiveKit adaptive interruption handling

LiveKit's documentation describes an adaptive barge-in model that distinguishes intentional interruptions from short acknowledgements and incidental sounds. It also documents false-interruption recovery and a turn-boundary cooldown for corrections near the start/end of an agent turn.

**STAR implication:** preserve a true interruption path, but do not stop speech for every "mm-hmm", cough, or background sound. If an interruption is classified as false and no user turn follows, resume the already-generated speech instead of regenerating the whole answer. Treat the feature as an optional provider integration, not a required dependency or permission bypass.

Sources:
- https://docs.livekit.io/agents/logic/turns/adaptive-interruption-handling/
- https://docs.livekit.io/reference/agents/turn-handling-options/

### Streaming personality and memory

A convincing streamer needs selective continuity, not constant narration. Use the existing cross-session continuity store only for owner-approved, verified gameplay practice. A memory callback should be emitted at most once per stream and marked complete only after the host confirms audible playback. Never invent prior experiences, force irrelevant callbacks, or store viewer-level profiles by default.

Recommended quality lanes:

1. Multiparty comprehension.
2. Turn-taking and correct silence.
3. Response appropriateness.
4. Interruption precision/recall.
5. False-interruption recovery.
6. Audible latency.
7. Avatar/audio synchronization.
8. Repetition and stale-memory rate.
9. Persona consistency and AI transparency.

Do not combine these into one opaque "human-likeness" score.

## 4. Local inference speed without quality regression

### llama.cpp SPEED-Bench

The upstream benchmark recommends matching client concurrency to the server slot count when measuring throughput. It compares baseline and speculative decoding with the same benchmark/category/output-length settings and reports both decode speedup and end-to-end latency speedup.

**STAR implication:**

- Pin model/quantization hash, llama.cpp build, flags, context, prompt set, output length, slot count, and concurrency.
- Compare warm-resident and cold-load runs separately.
- Measure prompt throughput, decode throughput, first-token latency, end-to-end latency, and answer quality.
- Do not infer a speedup from draft acceptance alone.
- Do not copy datacenter GPU tuning to an 8 GB consumer GPU without testing the actual model and mixed workload.

Source: https://github.com/ggml-org/llama.cpp/tree/master/tools/server/bench/speed-bench

### A practical 8 GB GPU policy

Keep enough VRAM headroom for the game, OBS, avatar, and any GPU-backed audio/vision work. Prefer CPU for latency-sensitive inference only when paired measurements show that CPU route meets the actual deadline. A nominally faster GPU route is not useful if it starves rendering or increases first-audible latency.

The scheduler remains advisory. No model route, process priority, CPU affinity, CUDA setting, context size, or model residency is changed by this PR.

## 5. Roblox and game creation

OpenGameEval runs agents inside reproducible Roblox Studio sessions and scores both scene/script changes and simulated play sessions. Its action space separates observation from editing, allowing inspection behavior to be measured rather than grading only the final source code.

**STAR implication:**

- Inspect relevant objects and scripts before editing.
- Build in a private test place.
- Check scene state and script behavior.
- Simulate player input and playtest.
- Verify multiplayer/client-server invariants.
- Use separate held-out tasks for mechanics, UI, animation, physics, and sound.
- Keep publishing, monetization, live player-data, and production permissions outside unattended workflows.

Sources:
- https://github.com/Roblox/open-game-eval
- https://arxiv.org/abs/2610.02563

## 6. General knowledge, task memory, and transferable skills

General knowledge should not be implemented as an ever-growing prompt or an undifferentiated vector database. STAR should keep distinct representations for:

- **Semantic knowledge:** source-backed facts, concepts, definitions, and relationships.
- **Temporal knowledge:** when a claim was true, when it was checked, what superseded it, and when it may expire.
- **Episodic experience:** what STAR actually observed or attempted in a particular task/session.
- **Procedural skill:** a tested sequence or executable artifact that reliably performs a task.
- **Task state:** current project/game objective, verified progress, blockers, and next action.
- **World-model knowledge:** predictions about how a game or tool changes after an action.

### Evidence: MemoryArena (2026-02-18)

MemoryArena evaluates interdependent multi-session Memory-Agent-Environment loops rather than isolated fact recall. Its paper reports that agents with near-saturated results on traditional long-context memory benchmarks can still perform poorly when earlier experience must guide later actions.

**STAR implication:** test whether remembered knowledge changes a future action correctly. A fact-recall score is not proof that Star can apply the fact to a tool, game, project, or conversation.

Source: https://arxiv.org/abs/2602.16313

### Evidence: Mem2ActBench (ACL 2026)

Mem2ActBench constructs 2,029 sessions and 400 memory-dependent tool-use tasks. The authors report that 91.3% of the tasks were strongly memory-dependent and identify failures in applying memory to tool selection and parameter grounding.

**STAR implication:** build held-out tests where a remembered project constraint, approved preference, game version, or previous task state must change a later tool action. Score the action and its parameters, not only the retrieved summary.

Source: https://aclanthology.org/2026.acl-long.370/

### Evidence: APEX-MEM (ACL 2026)

APEX-MEM uses temporally grounded, entity-centric property graphs, append-only history, and retrieval-time resolution of evolving or conflicting information. The authors report 88.88% on LOCOMO and 86.2% on LongMemEval in their evaluated configuration.

**STAR implication:** preserve temporal history and resolve current truth at retrieval time. Do not silently overwrite old facts, and do not surface an obsolete preference as current simply because it is semantically similar.

Source: https://aclanthology.org/2026.acl-long.749/

### Evidence: LifeBench (2026-03-04)

LifeBench evaluates long-horizon, multi-source memory across declarative and non-declarative information, including habits and procedural patterns inferred from distributed traces.

**STAR implication:** evaluate habits and skills separately from facts. For example, knowing the definition of a Luau pattern is not the same as consistently producing correct Luau; remembering a game strategy is not the same as executing it under new conditions.

Source: https://arxiv.org/abs/2603.03781

### STAR knowledge-card contract

Every reusable knowledge item should carry:

1. Stable opaque ID and domain.
2. Claim or procedure, with scope and version.
3. Primary source(s), source date, and last verification time.
4. Evidence type: cited fact, observed event, tested procedure, or hypothesis.
5. Confidence and known counterexamples.
6. Validity/expiry or a recheck policy for time-sensitive facts.
7. Supersedes/superseded-by relationships.
8. Required permissions and privacy/retention class.
9. A held-out evaluation or execution test when the item claims to be a skill.

### General-knowledge curriculum

Build a broad, source-backed curriculum across mathematics, computing, engineering, science, history, geography, language, economics, arts, and practical digital skills. For each domain, use a loop of retrieve → explain → solve a new problem → verify → schedule spaced review. Separate stable concepts from current facts that need fresh research.

Track factual accuracy, source support, calibration, contradiction handling, stale-claim rate, transfer to new tasks, and successful tool execution. Never equate the number of stored facts, retrieved chunks, or completed lessons with intelligence.

## 7. Acceptance plan

### Phase A — deterministic policy tests

- Verify fresh/stale/future host samples.
- Verify governor pressure and recovery hysteresis.
- Verify chat stays ahead of tools/background work.
- Verify active streaming/gameplay defers tools, research, learning, and asset generation.
- Verify idle healthy state can admit background work.
- Verify degraded state blocks nonprotected lanes.
- Verify active leases remain reserved until host-confirmed stop.

### Phase B — host adapter (separate change)

A Windows host adapter must collect CPU, RAM, VRAM, game frame-time, OBS render/output, voice backlog, audio underruns, and source epochs on a consistent monotonic clock. Do not use a single free-VRAM sample as the entire health model. Rotate source epochs after process/device restarts and reject counter deltas across epochs.

### Phase C — private mixed-workload rehearsal

Run a private, nonbroadcast rehearsal with game + OBS + voice + avatar + inference. Compare:
- first-content p50/p95;
- first-audible p50/p95;
- game frame-time p95/p99;
- audio underrun rate;
- OBS render skips, encoder skips, and network drops separately;
- turn-taking precision/recall and silence accuracy;
- stale action rejection;
- held-out game-skill transfer;
- task completion and answer quality.

Run at least three matched repetitions for baseline and candidate. Preserve failed requests and compare paired per-turn outcomes; never subtract unrelated p95 values.

### Phase D — owner review

Only after CI, host acceptance, and private rehearsal should a human consider enabling the bridge. A passing policy test does not prove hardware performance, intelligence gain, game mastery, natural speech, or production readiness.

## 8. Explicit limitations

- No Windows hardware adapter is added.
- No CPU/RAM/VRAM values are inferred from installed hardware.
- No process is launched, killed, reprioritized, or preempted.
- No model weights, prompts, model routes, memory policy, permissions, audio devices, avatar, OBS settings, game input, or broadcast state are changed.
- No measured speedup, intelligence gain, game mastery, or human-equivalent behavior is claimed.
- The `trusted_host` argument is an in-process assertion, not cryptographic proof of sensor truth.
- The host must independently enforce permissions and confirm worker termination before releasing a lease.

## References
9. MemoryArena — https://arxiv.org/abs/2602.16313
10. Mem2ActBench — https://aclanthology.org/2026.acl-long.370/
11. APEX-MEM — https://aclanthology.org/2026.acl-long.749/
12. LifeBench — https://arxiv.org/abs/2603.03781

1. LOLPlay, 2026-10-25 — https://arxiv.org/abs/2611.03685
2. MechEval/WARC, 2026-11-09 — https://arxiv.org/abs/2611.12324
3. SIMA 2 — https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/
4. MP-Bench, Findings of EMNLP 2026 — https://aclanthology.org/2026.findings-emnlp.1437/
5. LiveKit adaptive interruption handling — https://docs.livekit.io/agents/logic/turns/adaptive-interruption-handling/
6. llama.cpp SPEED-Bench — https://github.com/ggml-org/llama.cpp/tree/master/tools/server/bench/speed-bench
7. OpenGameEval — https://github.com/Roblox/open-game-eval
8. OpenGameEval paper — https://arxiv.org/abs/2610.02563
