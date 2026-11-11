# STAR Research: Open-World Game Skill Transfer and Live Creator Architecture

**Research date:** 2026-11-11  
**Scope:** Game playing, transferable skills, game creation, natural VTuber streaming, general knowledge, and performance on owner-controlled hardware.  
**Status:** Research and integration blueprint. This document does not claim that the proposed game-learning or live-stream integrations are already implemented.

## Executive finding

STAR should not be built as one giant model that receives every screenshot, chat message, audio frame, and tool result and then decides everything. That design wastes inference time, makes actions stale, and couples game performance to conversational latency.

The stronger design is a **multi-rate, evidence-grounded agent**:

- A fast reactive controller handles time-sensitive game actions.
- A visual/state estimator converts observations into a compact, timestamped world state.
- A strategic planner works asynchronously on objectives and tactics.
- A skill system stores reusable, versioned procedures with preconditions and postconditions.
- A verifier tests whether a skill actually worked in the environment.
- A separate stream director decides whether, when, and how to speak.
- A knowledge system researches facts and game mechanics with source provenance.
- A resource governor protects speech, game frame time, and the rendering pipeline.

This approach combines the strongest reusable ideas from Voyager, MineDojo, Cradle, OpenGameEval, modern streaming benchmarks, and STAR's own under-review infrastructure.

---

## 1. Research findings and what transfers to STAR

### 1.1 Voyager: skills should accumulate as executable, testable capabilities

Voyager's research describes three connected mechanisms:

1. An automatic curriculum that selects exploratory goals.
2. A growing library of executable skills that can be retrieved and composed.
3. Iterative improvement using environment feedback, execution errors, and self-verification.

The paper reports transfer of learned skills into a new Minecraft world. Its reported performance numbers are study-specific results, not expected STAR gains.

**STAR application:** a skill must be more than a paragraph in memory. It should have an explicit interface, preconditions, action sequence or policy reference, expected effects, failure conditions, environment/version scope, and verification evidence. A skill should be reusable only when the target environment satisfies its declared assumptions.

Sources:
- https://voyager.minedojo.org/
- https://arxiv.org/abs/2305.16291
- https://github.com/MineDreamer/Voyager

### 1.2 MineDojo: use a task taxonomy, not an enormous data dump

MineDojo provides a Minecraft environment and a broad language-described task suite. Its repository describes 3,142 tasks across programmatic, creative, and playthrough categories, plus large collections of community-created videos, wiki material, and discussion data.

**STAR application:** borrow the task taxonomy and curriculum concept first. Do not make STAR download hundreds of thousands of videos or posts as an initial dependency. Large-scale media ingestion has storage, licensing, privacy, freshness, and retrieval costs. Begin with a small, curated, versioned task set and add sources only when a specific learning objective needs them.

Use programmatically verifiable tasks for objective measures. Creative tasks need human or rubric-based evaluation; do not pretend that an open-ended build has one objectively correct answer.

Sources:
- https://github.com/MineDojo/MineDojo
- https://minedojo.org/
- https://openreview.net/forum?id=rc8o_j8I8PX

### 1.3 Cradle: a general computer-control fallback

Cradle studies general computer control through visual observations and keyboard/mouse operations across games and software. This is useful for games without a supported game API.

**STAR application:** provide two separate adapter families:

- **Structured adapters:** supported game APIs, Roblox Studio tools, simulator state, or other documented interfaces.
- **Visual-control adapters:** screenshots, OCR/UI interpretation, keyboard/mouse actions, and post-action observation.

Structured access is usually easier to verify. Visual control is more general but has weaker observability and must use shorter action horizons, stronger freshness checks, and more frequent verification.

Cradle is a research framework, not a reason to grant unrestricted desktop control. STAR must keep game control behind the existing host permission/action gate and use disposable environments for experiments.

Sources:
- https://github.com/BAAI-Agents/Cradle
- https://baai-agents.github.io/Cradle/
- https://arxiv.org/abs/2403.03186

### 1.4 OpenGameEval: exploration before editing is a measurable skill

OpenGameEval runs agents in reproducible, stateful Roblox Studio sessions and checks both the edited scene and simulated play. Its paper reports 84 human-curated core tasks and finds that inspecting the relevant objects before editing correlates with materially higher task success.

**STAR application:** Creator Brain should follow an inspection-first contract:

1. Identify the requested outcome.
2. Inspect the relevant hierarchy and properties.
3. Read scripts and dependencies that own the behavior.
4. Record the observed starting state.
5. Plan a minimal edit.
6. Make the edit in a disposable place.
7. Run static checks.
8. Simulate the actual player interaction.
9. Verify scene and runtime postconditions.
10. Save a skill only after repeatable success.

This prevents a common failure mode: generating plausible Luau without understanding the actual DataModel or multiplayer ownership.

Sources:
- https://github.com/Roblox/open-game-eval
- https://arxiv.org/abs/2610.02563

---

## 2. Proposed STAR Game Brain

### 2.1 Separate clocks and action horizons

The game loop should have three rates:

| Loop | Responsibility | Design rule |
|---|---|---|
| Reactive | Immediate movement, aim, dodge, interaction | Must not wait for a long reasoning call |
| Tactical | Short combat or objective sequence | Re-plan when observations or outcomes invalidate the plan |
| Strategic | Route, build order, team strategy, long-term goals | Runs asynchronously and proposes options, not stale inputs |

A strategic plan is not a command. Before execution, the host must check that the observation is still fresh, the game/session identity matches, the action is permitted, and the relevant preconditions still hold.

Every proposed action should carry:
- Environment and session identifier.
- Observation sequence/timestamp.
- Expiry or maximum age.
- Required preconditions.
- Expected postcondition.
- Cancellation reason if the state changes.

If the game state changes, the action expires. Do not execute a delayed sequence merely because a planner once approved it.

### 2.2 Compact world-state representation

Do not repeatedly send entire screenshots and chat histories to the largest model. Convert observations into a compact state record:

- Player position, velocity, health, resources, inventory.
- Nearby entities and their confidence.
- Current objective and progress.
- Map/route landmarks.
- Visible UI state and cooldowns.
- Recent action and observed outcome.
- Unknown or occluded information.
- Timestamp and source of every field.

Keep raw frames as short-lived evidence for debugging or replay, subject to explicit privacy and retention settings. Long-term memory should store derived, useful facts rather than indiscriminately retaining viewer media.

### 2.3 Environment adapters

Define a common adapter contract:

- `observe()`: return a timestamped observation.
- `inspect()`: return supported structured state.
- `propose_actions()`: expose only documented actions.
- `execute()`: request a permitted action through the host gate.
- `verify()`: check expected postconditions.
- `reset_or_replay()`: use only in a disposable evaluation environment.

The adapter must declare its capabilities and limitations. A screenshot-only adapter must not pretend it can inspect hidden inventory or authoritative server state.

### 2.4 Skill artifact schema

A candidate game skill should include:

- Stable skill ID and version.
- Game/engine and adapter ID.
- Environment version or compatibility range.
- Observation and action schema digests.
- Preconditions and prohibited states.
- Inputs and bounded parameters.
- Expected effects/postconditions.
- Timeout and cancellation conditions.
- Failure signatures and recovery strategy.
- Source/provenance and creation date.
- Development/holdout evidence.
- Last successful verification date.

Store general primitives separately from game-specific skills. For example, `navigate_to_visible_waypoint` may transfer, while a particular game's dash timing or recoil pattern must remain game-specific until separately verified.

Do not store arbitrary generated code as a trusted skill. Skills should invoke allowlisted, typed actions through a sandboxed runner. A SKILL.md file is reference material, not a permission grant.

---

## 3. Automatic curriculum and practice

### 3.1 Curriculum stages

Use a progressive task graph rather than random practice:

1. **Orientation:** identify controls, camera, HUD, objectives, and reset behavior.
2. **Primitive actions:** move, jump, aim, interact, equip, navigate.
3. **Short combinations:** move-and-aim, evade-and-recover, collect-and-return.
4. **Mechanic mastery:** timing, physics, cooldowns, resource use, enemy patterns.
5. **Objective tasks:** complete a level, defend an area, solve a puzzle, build a structure.
6. **Adversarial variants:** altered map, different seed, changed loadout, unexpected interruption.
7. **Transfer probes:** test a general primitive in a new environment without assuming game-specific parameters transfer.

The curriculum planner should choose the next task using:
- Current skill confidence.
- Recent failure modes.
- Task prerequisites.
- Expected learning value.
- Evaluation cost.
- Environment risk.
- Available compute and time budget.

Do not optimize only for wins. Include exploration, resource efficiency, survival, completion time, invalid actions, and recovery from mistakes.

### 3.2 Evaluation metrics

For each task family, report:

- Success rate and confidence interval.
- Completion time distribution.
- Objective progress.
- Invalid action rate.
- Death/failure count where meaningful.
- Resource efficiency.
- Recovery rate after a failed attempt.
- Human intervention rate.
- Performance on unseen seeds/maps.
- Skill transfer gain and unrelated-task regression.

Aggregate by independent environment/session, not by pretending every frame or action is an independent sample. Preserve failed and timed-out episodes; do not silently discard them.

### 3.3 Promotion policy

A candidate skill is promoted only after:

1. It passes a development set.
2. It passes an independent holdout.
3. It works on more than one seed or scenario where applicable.
4. It does not regress unrelated tasks.
5. It records exact environment, runner, policy, and skill digests.
6. A rollback target exists.

A single successful episode is an anecdote, not mastery.

---

## 4. STAR Stream Director: game-aware but not constantly talking

The stream director should not share the same policy as the game controller. A viewer conversation, a combat event, and a background research result have different speaking priorities.

### 4.1 Event-driven commentary

Create a bounded event timeline for:
- Objective completed or failed.
- New area or mechanic discovered.
- Unexpected game event.
- Near miss or recovery.
- Viewer message addressed to STAR.
- Viewer-to-viewer conversation.
- Important research result.
- Avatar/voice state changes.

Each event should include source, timestamp, confidence, relevance, and expiry. Commentary must be grounded in observed events; the system should not invent game state to fill silence.

### 4.2 Natural participation policy

The Social Director should decide among:
- Speak to the whole room.
- Reply to a specific viewer.
- Use a short nonverbal reaction.
- Continue listening.
- Remain silent.

Measure false interruptions, missed turns, response appropriateness, addressee accuracy, and silence preservation independently. Silence is a valid outcome.

### 4.3 Interruption correctness

LiveKit's turn-handling documentation describes interruption handling that stops speech and truncates conversation history to the portion the user actually heard. STAR should preserve the same invariant: after an interruption, do not leave unheard generated speech in conversational memory as though it was delivered.

Avatar mouth/viseme playback must follow the actual audio playback timeline. If audio is interrupted, the corresponding avatar motion and queued commentary must also be cancelled or reconciled.

Sources:
- https://docs.livekit.io/agents/logic/turns/
- https://docs.livekit.io/agents/logic/turns/tuning/

### 4.4 Persona quality without deception

A convincing streaming character needs stable preferences, humor, conversational habits, memory of relevant events, and consistent avatar behavior. It should not falsely claim to be a human or fabricate personal experiences. Disclose that STAR is an AI character when the context calls for it, and keep viewer privacy and consent separate from character memory.

---

## 5. Speed and compute architecture

### 5.1 Route by deadline and cognitive demand

| Workload | Preferred path |
|---|---|
| Audio/VAD and playback | Dedicated lightweight real-time worker |
| Simple acknowledgement | Small, low-latency route or deterministic response |
| Reactive game decision | Compact state/policy; bounded model fallback |
| Social turn decision | Fast classifier/controller plus context |
| Strategic game plan | Stronger reasoning model asynchronously |
| Luau/game creation | Coding model plus Studio verification |
| Research/general knowledge | Background research model with citations |
| Memory consolidation | Idle/background only |

A larger model is not automatically better for every subtask. Measure the quality/latency tradeoff per category.

### 5.2 Benchmark correctly

Use the AIPerf metric vocabulary where the backend exposes the required evidence:

- TTFT: request to first generated token.
- ITL: time between consecutive tokens.
- Request latency: complete response duration.
- Output-token throughput.
- p50/p95/p99 distributions.
- Speculative-decoding acceptance where available.

Do not label arbitrary API chunk gaps as token ITL. If the server emits several tokens in one chunk, chunk timing is not token timing.

Run paired tests on the exact model, quantization, backend build, context, slot count, and hardware. Include warm-up, cold-start, idle, game-active, voice-active, and combined workloads. Compare both speed and task quality.

Sources:
- https://docs.nvidia.com/aiperf/reference/ai-perf-metrics-reference
- https://developer.nvidia.com/blog/benchmarking-llm-inference-at-scale-with-aiperf/

### 5.3 Consumer GPU constraints

For the 8 GB RTX 4060 target:
- Keep audio and simple state estimation on CPU when measurements support it.
- Preserve VRAM headroom for the game renderer and active model.
- Avoid loading several large models concurrently without measuring peak VRAM and paging.
- Test quantization for answer quality as well as speed.
- Treat KV-cache and speculative decoding as experiments, not universal wins.
- Defer indexing, training, video generation, and large research jobs when voice/game deadlines are at risk.

The target is smooth mixed-workload behavior, not the highest idle tokens/sec.

---

## 6. General knowledge and memory

Keep three distinct kinds of memory:

1. **Semantic knowledge:** sourced facts, definitions, technical documentation, and current information.
2. **Episodic memory:** what happened in a particular game, project, stream, or task.
3. **Procedural memory:** verified skills and reusable workflows.

Every stored item should carry source, date, environment/version, confidence, and verification status. Current technical facts must be refreshed against authoritative documentation. A past success should not silently become a universal rule.

For research answers, retain source links and separate:
- Directly verified facts.
- Inferences.
- Open questions.
- Expired or superseded information.

For general knowledge, expand evaluation across factuality, reasoning, tool use, multimodal understanding, temporal freshness, and uncertainty calibration. Public development tasks are useful for iteration but are not sealed holdouts.

---

## 7. Integration map to STAR's existing work

The repository already has several relevant development tracks under review. The new design should connect them instead of duplicating their responsibilities:

| Existing area | Intended role |
|---|---|
| `star/agent_skills.py` and skill retrieval benchmark | Discover and retrieve skill references |
| `star/continual_learning_eval.py` | Test memory transfer and regression |
| `star/game_dev_eval.py` | Evaluate game-creator outcomes |
| `star/stream_multiparty_floor.py` | Decide whether STAR owns the conversational floor |
| `star/stream_qos.py` | Advise workload admission and preserve speech capacity |
| `star/inference_benchmark.py` | Measure local model streaming behavior |
| `star/voice/` | Capture, speech, playback, and voice-turn evidence |

These components are on separate draft branches/PRs as of this research date. Their presence in a PR does not mean they are merged into `star/next`, included in the Windows installer, or validated on the owner's RTX 4060 machine.

### Proposed next integration sequence

1. Stabilize and merge the existing voice, QoS, skill retrieval, multiparty, and benchmark PRs only after their own CI and review gates pass.
2. Define one versioned game-environment adapter contract.
3. Add a bounded game-episode receipt schema and replayable local test fixture.
4. Connect verified skill artifacts to the existing retrieval library.
5. Add a curriculum planner that selects only tasks whose prerequisites and risk profile are satisfied.
6. Run the first end-to-end experiment in a disposable Minecraft or Roblox environment.
7. Add a stream-commentary adapter that consumes verified game events, not raw speculative plans.
8. Run a private mixed-workload rehearsal before enabling any public broadcast.

---

## 8. Safety, privacy, and release gates

- Game input remains behind the host's explicit game-action permission gate.
- Use private/disposable environments for autonomous practice.
- No unattended purchases, trades, account changes, public publishing, monetization, moderation actions, or live player-data writes.
- Do not ingest private viewer messages/audio into long-term memory without a clear consent and retention policy.
- Research downloads must respect licenses, terms, and storage budgets.
- Background learning must stop or yield when voice, game, or OBS deadlines are threatened.
- Every experiment must have cancellation, timeout, bounded resource use, and rollback.
- A successful CI run proves only the tested software paths, not real game mastery or a successful livestream.

## 9. Acceptance test: STAR as a gaming VTuber

A private 30–60 minute rehearsal should combine:

1. A real supported game and a fixed task objective.
2. A held-out map/seed or unfamiliar mechanic.
3. Game-state observations with timestamps.
4. Voice input and playback.
5. Multiple simulated or consenting viewers.
6. Avatar mouth/viseme synchronization.
7. OBS output statistics.
8. Background research and memory retrieval.

Pass criteria should include:
- No stale game action is executed after its observation expires.
- Objective progress is verified by the environment.
- A learned skill succeeds on an unseen variant before promotion.
- No speech is recorded as delivered before the output evidence says it played.
- Interrupted speech is removed from the unheard portion of conversation history.
- STAR correctly identifies when a viewer addresses her versus another viewer.
- Silence is preserved when participation is not useful.
- Game FPS, audio underruns, OBS rendering/encoding/network drops, memory, VRAM, and voice latency remain within predeclared limits.
- The report identifies every unavailable measurement instead of fabricating a pass.

## Final recommendation

Build STAR as a coordinated digital-world agent with a fast body, a slower planner, a verified skill library, a grounded memory system, and a socially aware stream director. The strongest path is not to make one model reason harder on every frame. It is to give each subsystem the right evidence, deadline, tool scope, and verification contract—and then measure the complete system under the same simultaneous load STAR will face while gaming and streaming.
