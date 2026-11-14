# STAR Run 12 — real-time agent, inference, game-learning, and VTuber research

**Research date:** 2026-11-13 (America/Chicago)  
**Repository:** `oncoursemail/Star-AI-Project`  
**Integration branch:** `feat/resource-admission-20261113-run21`  
**Status:** research and integration specification. This document does not enable new models, hardware access, game control, streaming providers, or production defaults.

## Executive decision

STAR's next major improvement should be an integrated **real-time agent runtime**, not another independent agent framework or resource scheduler.

The repository already has draft work for:
- lease-based resource admission and stream-pressure governance (#1140, #1142);
- paired latency-versus-quality evaluation (#1143);
- causal turn-taking and room behavior (#1144–#1148);
- durable task/delivery continuity (#1156);
- latest-wins Live2D frame transport (#1159);
- semantic-prefix speculative thinking (#1160);
- measured thinker resource profiles and process telemetry (#1162–#1164);
- spoken-task and long-form grounding evaluation (#1165);
- natural streamer persona and event-linked human-resolution stopping (#1178).

The highest-value work is to connect these pieces through one trusted host, one monotonic event clock, one resource authority, and evidence-linked task/delivery records. Do not add a competing scheduler, second voice pipeline, or a second source of truth for playback and turn ownership.

## 1. Research findings that materially change the design

### 1.1 ROAR: evaluate gameplay while the world keeps moving

**Paper:** [ROAR: Benchmarking LMM Agents under Real-Time Constraints in Multiplayer Action-Shooter Games](https://arxiv.org/abs/2610.24282), 2026-10-16.

ROAR points out that turn-based evaluations hide a central problem: the environment pauses while the model reasons, whereas a real game continues evolving. Its Multi-Agent Asynchronous Gym separates environment progression from agent reasoning so inference does not block the world.

**STAR transfer**
- Run game simulation/capture and the agent's reasoning on separate execution paths.
- Give every observation a monotonic timestamp, frame/world revision, and expiry.
- Attach an observation revision to each proposed action.
- Reject an action if the world has advanced beyond its permitted staleness window.
- Keep a fast local controller operating from the latest valid state while strategic reasoning runs.
- Measure decision age at execution, not just model latency.

This should become STAR's core gaming acceptance principle: a correct decision delivered too late is a failed real-time action.

### 1.2 Realtime-Venus: two loops, one conversation

**Project and technical report:** [Realtime-Venus](https://realtime-venus.github.io/) · [technical report](https://arxiv.org/abs/2609.13814).

Realtime-Venus describes a continuous perception/speech loop and a separate delegated-task loop. Delegated work captures the context available when the request arrives, runs independently, and returns a prepared result to the live conversation. The frontend still decides when that result should be spoken; playback tracking confirms delivery.

**STAR transfer**
- The protected interaction loop owns audio callbacks, turn state, immediate chat, game-control deadlines, avatar playback synchronization, and broadcast-critical work.
- The capability loop owns research, coding, asset creation, indexing, long-horizon planning, and practice.
- Each delegation stores an immutable context/evidence snapshot, task ID, source session, deadline, and cancellation generation.
- Results return as proposals with evidence and freshness metadata; they do not directly speak, publish, or execute external actions.
- The Social Director chooses whether and when a result is delivered.
- Cancel stale work when its originating request, session, or world state is superseded.

Do not copy Realtime-Venus model sizes or benchmark numbers into STAR's target-hardware assumptions. Reuse the separation and lifecycle ideas, then measure STAR's own implementation.

### 1.3 Full-Duplex-Bench v3: speech quality includes task completion

**Benchmark:** [Full-Duplex-Bench v3](https://www.fullduplex.ai/benchmarks/fdb-v3), with its paper/code linked from the benchmark page.

The benchmark uses human-recorded spoken requests with disfluencies and self-corrections, multi-step tool tasks, and live streaming evaluation. It scores task success, tool selection/arguments, response quality, latency, and interruption behavior. The published tables show that fast response time and correct tool execution are separate dimensions.

**STAR transfer**
- Pair latency with task correctness and tool-argument correctness.
- Test self-corrections, changed intent, partial utterances, and multi-step requests.
- Distinguish an interruption from a backchannel or speech directed to another viewer.
- Measure false interruptions and missed interruptions.
- Retain the existing host-side room director as the authority for speak/stop/interrupt decisions.
- Do not treat a lower time-to-first-audio as a win if it increases wrong-speaker replies or failed actions.

### 1.4 SpecStream: long-context inference is a memory-transfer scheduling problem

**Paper:** [Resource-Efficient Speculative Decoding for Long-Context LLM Serving](https://arxiv.org/abs/2609.33184), 2026-09-27.

SpecStream overlaps streamed KV-history restoration, target verification, and draft computation. The paper reports throughput gains in its evaluated Qwen3 and InternLM2.5 serving configurations while preserving quality close to its comparison system.

**STAR transfer**
- Treat model weights, KV cache, and host-to-device transfer as separate memory/compute budgets.
- Record context length, KV bytes, transfer bytes, prefill latency, decode latency, concurrency, and quality for every benchmark.
- Prioritize the target model's verification path over speculative draft work when resources are constrained.
- Evaluate whether extra concurrency harms STAR's single foreground stream.
- Treat SpecStream as a serving-system research reference, not a drop-in llama.cpp option for the RTX 4060.

### 1.5 SemKV: find the quality cliff before compressing memory

**Paper:** [SemKV: Semantic Mixed-Precision KV Cache Quantization Guided by the Quality Cliff](https://arxiv.org/abs/2608.28911), 2026-08-28.

SemKV argues that uniform cache quantization can have a sharp quality cliff rather than a smooth degradation curve. Its reported storage reductions are specific to its models, quantizers, and statistical protocol.

**STAR transfer**
- Sweep cache precision against task quality on the exact model and runtime.
- Test long-context retrieval, multi-turn continuity, code editing, tool selection, and factual consistency—not only perplexity.
- Preserve a full-precision baseline and define a quality non-inferiority margin before a candidate run.
- Reject settings that increase runaway generation, omissions, or stale-memory errors even if memory use improves.
- Never assume a paper's bit-width is safe for another architecture.

### 1.6 OmniKVQuant: multimodal caches have modality-specific behavior

**Paper and code:** [OmniKVQuant](https://arxiv.org/abs/2609.11582) · [official repository](https://github.com/kaistmm/OmniKVQuant), 2026-09-10.

The paper identifies temporal key drift and heterogeneous value geometry in audio/video/text cache streams, then proposes windowed key ranges and modality-specific value rotations for its evaluated omni-modal models.

**STAR transfer**
- If STAR later uses a single audio-video-text model, benchmark multimodal KV behavior separately from text-only KV.
- Keep audio, video, and text token/time boundaries in evaluation traces.
- Test temporal recall and cross-modal grounding after compression.
- Do not apply text-only cache settings to multimodal streams without evidence.
- Do not add this runtime dependency until the selected inference engine and model actually support it.

### 1.7 GameWorld, OpenGameEval, and GameDevBench: evaluate different kinds of game skill

- [GameWorld](https://gameworld-bench.github.io/) evaluates multimodal agents across browser games and includes real-time interaction concerns.
- [OpenGameEval](https://github.com/Roblox/open-game-eval) evaluates agents in reproducible Roblox Studio sessions, separating observation from editing and scoring both scene state and simulated Play sessions. Its paper reports 84 core tasks and finds that relevant scene inspection correlates with higher task success.
- [GameDevBench](https://github.com/waynchi/gamedevbench) evaluates 333 Godot game-development tasks across gameplay, UI, 2D graphics/animation, and 3D graphics/animation. Its paper reports that visual feedback can materially improve agent performance on its evaluated tasks.

**STAR transfer**
- Keep game-playing, game-building, and game-understanding as separate skill families and scorecards.
- In Roblox Studio, inspect relevant instances and scripts before editing.
- Use Play-session checks and visual evidence, not only static code assertions.
- In Godot, verify scene trees, assets, shaders, animation, and actual gameplay.
- Require a held-out task set and repeated attempts before promoting a skill.
- Respect each benchmark's license, API requirements, and data-use terms. Do not embed benchmark credentials or private game assets in the repository.

## 2. Target architecture: one runtime, two loops, explicit authorities

```text
                   TRUSTED WINDOWS HOST
                           |
             monotonic event / clock authority
                           |
       +-------------------+--------------------+
       |                                        |
PROTECTED INTERACTION LOOP             CAPABILITY LOOP
       |                                        |
 audio callbacks / VAD                    research workers
 turn director / room queue               coding workers
 foreground chat                          game practice
 game reflex controller                   creator pipeline
 avatar playback clock                    memory consolidation
 OBS health / capture                     asset generation
       |                                        |
       +--------- evidence + task ledger -------+
                           |
                SOCIAL / DELIVERY DIRECTOR
                           |
             permission + freshness checks
                           |
             speech / avatar / UI delivery
```

### Authority boundaries

| Authority | Single owner | Rule |
|---|---|---|
| Resource admission | #1140/#1142 host supervisor | No parallel ALLOW/DEFER scheduler |
| Conversation floor | Existing room director | Prompt text never grants speaking permission |
| Playback truth | Host playback clock and delivery ledger | Generated text is not proof of audible delivery |
| Avatar frame transport | #1159 frame pump | Latest-wins applies only to replaceable animation samples |
| Task lifecycle | Existing task ledger/worker supervisor | Durable work is not silently dropped |
| Tool permissions | Existing permission/approval layer | Background reasoning cannot bypass approval |
| Game actions | Dedicated controller adapter | Model output is a proposal, never raw unrestricted input |
| Memory promotion | Governed memory/skill pipeline | Unverified output is not canonical knowledge |

### Event contract

Every cross-loop event should carry:
- opaque event ID and source ID;
- session and generation ID;
- monotonic timestamp plus clock epoch;
- source/evidence references;
- world revision where applicable;
- expiry/deadline;
- classification and confidence;
- cancellation/supersession state.

Do not store raw viewer audio, transcripts, screen captures, or game footage in general-purpose metrics. Keep content only in an explicitly authorized, bounded evidence store with retention controls.

## 3. STAR Gamer: real-time control and durable learning

### Control hierarchy

1. **Reflex controller:** high-frequency movement, camera stabilization, jump timing, and safe stop behavior.
2. **Tactical controller:** combat, positioning, route choice, resource management, and objective execution.
3. **Strategic planner:** map-level goals, team strategy, progression, and long-horizon decisions.
4. **Learning/evaluation worker:** analyzes trajectories, proposes skill updates, and tests them offline.

The reflex controller must be deterministic or tightly bounded and must not wait for an LLM. A strategic action is a short-lived proposal bound to a specific observation revision. The host validates the game, action schema, bounds, and expiry before execution.

### Skill lifecycle

```text
task definition
  -> baseline attempt
  -> timestamped observation/action trajectory
  -> failure and success analysis
  -> candidate skill / policy change
  -> deterministic checks
  -> held-out maps or levels
  -> repeated-seed evaluation
  -> regression and transfer tests
  -> versioned skill promotion or rollback
```

A skill record should contain its preconditions, game/version, action schema, evidence references, expected outcome, known failure modes, confidence, evaluation set, and version. Do not promote a strategy based only on one successful run or model self-grading.

### Gameplay scorecard

- objective completion rate;
- success across repeated seeds;
- time-to-objective;
- action age at execution;
- invalid/stale action rate;
- deaths/failures per objective;
- resource efficiency;
- recovery after unexpected events;
- transfer to unseen maps or mechanics;
- game FPS and input-to-action latency during concurrent streaming.

## 4. STAR Creator: build, run, inspect, repair

Use one reusable creator loop across Roblox Studio, Godot, and later Unity:

1. Read project manifest and version.
2. Inspect scene/object hierarchy and relevant files.
3. Build a dependency graph.
4. Plan bounded edits with a rollback point.
5. Apply edits through typed tools.
6. Run static validators and unit tests.
7. Launch an isolated Play session.
8. Capture authorized visual evidence.
9. Check gameplay, UI, animation, audio, and performance.
10. Repair only the failed acceptance criteria.
11. Repeat tests and preserve the artifact plus evidence.

For Roblox, keep OpenGameEval's observation/edit distinction: inspection is a first-class action, not optional overhead. For visual assets, store source/license/provenance and test actual import/render behavior.

## 5. STAR as a natural VTuber

Natural presence is a coordinated system, not a prompt trick.

### Social Director

Before speaking, score:
- direct-address confidence;
- topic relevance;
- event novelty and urgency;
- evidence confidence;
- conversational-floor ownership;
- whether another viewer already answered;
- current speech backlog and interruption state;
- stream/game focus;
- resource pressure.

Possible outcomes: respond, brief acknowledgement, queue, continue, ignore, wait, interrupt, or stop. Preserve the existing event-linked human-resolution stop behavior.

### Audiovisual timing

- The playback clock is authoritative for mouth movement.
- Speech segments remain ordered and use delivery receipts.
- Avatar animation frames may coalesce through the latest-wins pump.
- On interruption, revoke the current generation, flush pending avatar frames, confirm the old send is settled, then return to a neutral/listening pose.
- Do not let stale frames or old TTS segments play after a new turn begins.

### Long-session naturalness evaluation

Evaluate 30–120 minute rehearsals, not only isolated prompts:
- repeated catchphrase rate;
- response appropriateness;
- correct silence rate;
- false interruption rate;
- direct-address precision;
- grounded game-event commentary;
- speaker attribution;
- TTS queue-to-first-audio;
- speech/animation synchronization error;
- viewer-to-viewer conversation handling;
- persona consistency after many topic changes.

The character may express warmth, curiosity, humor, excitement, and preferences as a fictional AI persona. She must not fabricate a human biography, claim human lived experience, or conceal that she is an AI.

## 6. Inference and speed plan for an 8 GB GPU class

Do not select optimizations from paper headline numbers. Run matched A/B tests on the exact model, quantization, context length, runtime version, driver, and simultaneous workload.

### Candidate experiments

| Candidate | Potential benefit | Main risk / applicability gate |
|---|---|---|
| Stable prompt prefixes | Less repeated prefill | Only helps identical leading tokens |
| KV cache quantization | More context or concurrency | Quality cliffs; engine/model support |
| Speculative decoding | Fewer target decode steps | Draft overhead can lose at long context or low acceptance |
| CPU KV offload | Lower VRAM pressure | PCIe transfer latency can dominate |
| Expert caching for MoE | Less repeated expert transfer | MoE-specific; not applicable to dense models |
| Adaptive visual sampling | Lower vision compute | May miss fast events |
| Small specialist models | Lower latency for routing/VAD/event labels | Must validate calibration and false-negative cost |
| Continuous batching | Higher aggregate throughput | May increase single-stream latency and contention |

### Mandatory paired workload

Run the same task set under:
1. idle inference;
2. game only;
3. OBS capture/encode only;
4. voice only;
5. game + OBS + voice;
6. all foreground work plus one background worker;
7. memory-heavy long-context conversation.

Record p50/p95/p99 for time-to-first-token, time-to-first-audible, inter-token latency, end-to-end turn time, audio underruns, OBS render/output lag, game frame time, action age, CPU/RAM/VRAM, model queue depth, and task success.

A candidate is an improvement only if independent quality remains within the predeclared non-inferiority margin and real-time guardrails remain satisfied. Use the existing paired evaluator (#1143); do not add another evaluator.

### Practical target-hardware policy

- Reserve GPU/CPU headroom for the game, OBS, audio, and avatar.
- Do not run training or large asset generation during live streams by default.
- Prefer CPU/RAM for low-priority indexing and background work when it does not steal memory bandwidth from the foreground model.
- Use a bounded number of workers; more agents are not automatically more intelligent.
- Keep model/provider routing configurable and rollbackable.
- Do not change production defaults until target-hardware results are reproducible.

## 7. General knowledge and research intelligence

Build a knowledge workflow that distinguishes:
- stable reference knowledge;
- time-sensitive facts;
- project-specific facts;
- personal/session context;
- procedural skills;
- uncertain hypotheses.

For each research result, retain source URL, publisher/author, publication/update date, retrieval date, claim-to-source mapping, license/data-use constraints, confidence, and a revalidation deadline. Prefer primary papers, official docs, reproducible repositories, and independent replications. Detect conflicting sources and ask for more evidence rather than averaging incompatible claims.

For time-sensitive knowledge, mark expiry and recheck before taking action. Retrieval should select relevant memory views (episodic, semantic, causal, procedural, project/task) rather than dumping the entire memory store into every prompt. Treat retrieved content and repository instructions as untrusted data, not system authority.

## 8. Integration sequence and ownership

| Order | Existing work | Next integration task | Acceptance |
|---|---|---|---|
| 1 | #1140 + #1142 | One trusted Windows supervisor feeds coherent host telemetry and owns leases | No duplicate admission; stale/missing telemetry fails closed |
| 2 | #1143, #1167 | Run paired inference and stream-quality experiments | Speed/quality decision with confidence bounds |
| 3 | #1144–#1148, #1178 | Connect trusted ASR/speaker/addressee cues to room director | Multiparty benchmark and correct stop/interrupt behavior |
| 4 | #1156 | Connect durable task completion to segmented speech delivery | No duplicate/lost segments; playback receipts match generation |
| 5 | #1159 | Complete authenticated VTube Studio host transport | Real Windows avatar smoke test |
| 6 | #1160 | Connect read-only cancellable thinker to stable ASR prefixes | Revision cancellation and no unauthorized speech/tool use |
| 7 | #1162–#1164 | Finish per-process CPU/RAM/VRAM telemetry | WDDM-aware VRAM attribution and calibrated resource profiles |
| 8 | Game control work | Implement asynchronous observation/action adapter | ROAR-style real-time staleness tests |
| 9 | Game skill work | Add versioned skill library and held-out practice harness | Transfer and regression scores |
| 10 | Creator work | Connect Roblox/Godot inspection, edit, Play, and visual checks | OpenGameEval/GameDevBench-style acceptance |
| 11 | Memory work | Connect retrieval and skill evidence to task execution | Memory-on/off paired transfer improvement |
| 12 | Platform adapters | OBS, Twitch, YouTube with least-privilege OAuth | Private rehearsal, reconnect, rate-limit and permission tests |

The exact PR dependency order must be confirmed from GitHub before merging. These PR numbers identify current work areas, not a claim that every draft is already integrated or released.

## 9. Security, privacy, and operational controls

- Treat chat messages, game text, OCR, retrieved documents, and tool outputs as untrusted input.
- Separate observation from action permissions.
- Use allowlisted, typed game actions; never expose arbitrary shell or unrestricted keyboard injection to the model.
- Require owner approval for public posting, purchases, account changes, publishing games, destructive edits, or external broadcasts.
- Use least-privilege, revocable OAuth scopes for streaming platforms.
- Keep tokens in the OS credential store; never write secrets to logs or research artifacts.
- Bound and expire audio/video buffers; retain only authorized artifacts.
- Keep viewer identity and chat history out of generic telemetry.
- Use host-authenticated IPC; a `trusted_host=True` flag is not authentication.
- On uncertain worker stop, keep the lease fenced until the host confirms process termination.
- Provide emergency stop and broadcast-disable controls independent of the language model.

## 10. Research source register

1. ROAR, real-time asynchronous game agents: https://arxiv.org/abs/2610.24282
2. Realtime-Venus, full-duplex interaction and delegation: https://realtime-venus.github.io/ and https://arxiv.org/abs/2609.13814
3. Full-Duplex-Bench v3: https://www.fullduplex.ai/benchmarks/fdb-v3
4. SpecStream, long-context speculative serving: https://arxiv.org/abs/2609.33184
5. SemKV, quality-aware KV quantization: https://arxiv.org/abs/2608.28911
6. OmniKVQuant, multimodal KV quantization: https://arxiv.org/abs/2609.11582 and https://github.com/kaistmm/OmniKVQuant
7. GameWorld: https://gameworld-bench.github.io/
8. OpenGameEval: https://arxiv.org/abs/2610.02563 and https://github.com/Roblox/open-game-eval
9. GameDevBench: https://github.com/waynchi/gamedevbench
10. Duplex-MPE: https://arxiv.org/abs/2609.31948
11. MP-Bench: https://arxiv.org/abs/2609.13076 and https://github.com/atosystem/MP-Bench

## 11. Evidence and release boundaries

This document is a research/integration specification. It does not mean STAR currently has:
- autonomous gameplay or mastery of any commercial game;
- a fully connected Twitch/YouTube broadcast agent;
- a completed Windows host supervisor or per-process WDDM VRAM provider;
- a production multimodal KV cache implementation;
- automatic model-weight self-improvement;
- human consciousness or biological human experience.

The public v1.0 release and the draft development stack must remain clearly distinguished. Passing offline CI proves the tested code paths on CI runners; it does not prove RTX 4060 performance, physical microphone quality, OBS/VTube Studio behavior, or live-game competence.

**Promotion rule:** integrate one capability at a time, test it against an independent benchmark and a mixed-load host rehearsal, record exact model/runtime/hardware versions, and keep rollback available.
