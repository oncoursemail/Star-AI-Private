# STAR Recursive Game Learning, Skill Harnesses, and General-Knowledge Research

**Research date:** 2026-11-13  
**Repository:** `oncoursemail/Star-AI-Project`  
**Purpose:** translate recent recursive-agent, embodied-control, game-learning, knowledge-retrieval, and avatar research into a concrete plan that reuses STAR's existing systems instead of creating parallel schedulers or skill banks.

## Executive findings

STAR's repository already contains substantial game-learning and streaming infrastructure: signed practice evidence, multi-game practice allocation, sealed and counterbalanced holdouts, skill-transfer audits, fast-path advice, cross-session continuity, memory-to-action evaluation, paired stream evaluation, task coordination, playback acknowledgements, and a composed stream/resource runtime.

The next leap is **not another gameplay skill database or another resource scheduler**. It is to connect these pieces through one hierarchical execution harness and one carefully regularized improvement loop:

1. A deterministic safety shield and trusted host boundary.
2. A fast reactive layer that executes already-verified skills.
3. A slower planner that selects goals and composes skills.
4. An outer recursion agent that studies failures, proposes small changes, and promotes only changes that survive independent held-out tests.

Recent research makes this architecture unusually concrete. R²SI and RRSI show how to separate execution from improvement and how to prevent recursive harness evolution from overfitting. The CoRL 2026 paper *The Harness* describes a three-layer control hierarchy with model-free guards at every control tick. Voyager and MineDojo provide a long-running game-learning pattern with automatic curricula, executable skills, and internet-scale demonstrations. A 2026 multi-agent Minecraft report shows the potential—and the cost—of team-level long-horizon execution.

## 1. Existing STAR work to reuse

Do not fork these capabilities into a second implementation:

| Existing STAR work | Reuse in the unified design |
|---|---|
| [#703 multi-game fair practice](https://github.com/oncoursemail/Star-AI-Project/pull/703) and [#708 evidence-guided practice](https://github.com/oncoursemail/Star-AI-Project/pull/708) | Curated game portfolio, fair exposure, and practice selection |
| [#947 sustained signed recovery](https://github.com/oncoursemail/Star-AI-Project/pull/947) | Prevent one lucky success from restoring mastery |
| [#977 sealed game holdouts](https://github.com/oncoursemail/Star-AI-Project/pull/977) and [#978 counterbalanced trials](https://github.com/oncoursemail/Star-AI-Project/pull/978) | Prevent leakage, order effects, and target-scene contamination |
| [#1040 verified gameplay fast path](https://github.com/oncoursemail/Star-AI-Project/pull/1040) | Keep signed database work off frame-critical input paths |
| [#1136 temporal memory evaluation](https://github.com/oncoursemail/Star-AI-Project/pull/1136) and [#1139 cross-session continuity](https://github.com/oncoursemail/Star-AI-Project/pull/1139) | Measure memory-to-action transfer and retain only approved practice evidence |
| [#1140 resource-aware admission](https://github.com/oncoursemail/Star-AI-Project/pull/1140) and [#1142 composed stream/resource runtime](https://github.com/oncoursemail/Star-AI-Project/pull/1142) | One authoritative scheduler, queue, lease system, and protected real-time reserve |
| [#1166 paired stream-variant evaluation](https://github.com/oncoursemail/Star-AI-Project/pull/1166) | Compare model, harness, memory, voice, and gameplay revisions on matched holdouts |
| [#1176 room host](https://github.com/oncoursemail/Star-AI-Project/pull/1176) and [#1177 task/communication ledger](https://github.com/oncoursemail/Star-AI-Project/pull/1177) | Stream events, long-running tasks, worker recovery, and playback-confirmed reporting |

These are repository references, not a claim that every draft is merged or shipped. Their branch dependencies and exact-head CI must be reconciled before runtime integration.

## 2. Research findings

### 2.1 R²SI: separate the agent that acts from the agent that improves

[R²SI project and results](https://r2si.worldscape.io/) (October 2026) uses two layers:

- **Robot Agent:** acts from current observations, task description, and episode memory through a reusable Skill layer.
- **Recursion Agent:** reviews rollouts, revises skills and harness code, tests the revision, and only then releases a versioned update. Where a reactive model is used, execution records can also become training data.

The project reports RoboDojo results with the same underlying VLM as its reference agent, attributing the difference to the harness. Those are robotics benchmark results, not evidence that the same numbers will transfer to Roblox or commercial games.

**STAR application:** keep live gameplay execution simple and bounded. Run improvement offline or in an isolated practice environment. Treat a skill/harness revision as a versioned candidate, never as an immediate live edit.

Source: https://r2si.worldscape.io/

### 2.2 RRSI: recursive self-improvement needs regularization

[RRSI: Regularized Recursive Self-Improvement of Agent Harnesses](https://arxiv.org/abs/2609.24972), revised October 4, 2026, studies the risk that repeated harness edits overfit a finite evolution set. It constrains the proposal process with an annealed edit budget and search history, then uses a critic and pruner to screen benchmark-specific, low-value, or overly expensive changes. Across its evaluated coding, workspace, and engineering-design benchmarks, the paper reports up to 4.3 points of gain on five out-of-distribution benchmarks and 30% fewer policy tokens than unregularized evolution in the reported setup.

**STAR application:**
- Propose one narrowly scoped change per candidate after early exploration.
- Record the hypothesis, component, diff, expected benefit, measured cost, and failure modes.
- Screen for hard-coded benchmark/seed leakage before running tests.
- Require a noise-adjusted minimum gain and no critical regression.
- Prune changes with no recent independent contribution.
- Preserve untouched games, maps, prompts, and task families for transfer evaluation.
- Keep the base model frozen until harness/skill changes have proven value; model fine-tuning is a later, separately governed experiment.

The paper's results are bounded to its evaluated domains. They do not prove universal recursive improvement.

Source: https://arxiv.org/abs/2609.24972

### 2.3 The Harness (CoRL 2026): three control layers, guards at every tick

[The Harness: One Agent Harness for Anything that Acts](https://web.eecs.umich.edu/~stellayu/publication/2026harnessCoRLL.html), presented at CoRL in November 2026, places a coding agent above reusable perception/motion skills and bounded VLA calls, with guards that react every control tick without another model call and a fixed safety shield below them. The authors also describe applying the same harness pattern to desktop use and commercial games with GUI action models.

**STAR application:**
- **Top layer — planner/coding agent:** decomposes objectives and composes known skills; called on new goals, uncertainty, or recovery—not for every key press.
- **Middle layer — skills/reactive policy:** executes bounded action chunks and returns control after fresh observations.
- **Bottom layer — deterministic guards:** check focus, scene identity, deadlines, health, action allowlists, resource limits, and stop conditions on every control tick.
- **Fixed safety shield:** blocks actions outside the owner-approved environment and capability scope.

This is a strong fit for keeping model reasoning out of the latency-critical game-input path.

Source: https://web.eecs.umich.edu/~stellayu/publication/2026harnessCoRLL.html

### 2.4 Voyager: automatic curriculum plus executable, compositional skills

[Voyager](https://voyager.minedojo.org/) introduced an open-ended Minecraft agent with an automatic curriculum, an expanding executable skill library, and iterative improvement using environment feedback, execution errors, and self-verification. Its skills are compositional and can be retrieved in a new world for related tasks.

**STAR application:** a skill should be an executable, testable behavior with explicit preconditions and observable effects—not a paragraph that merely describes how to play. Compose small validated skills into larger goals such as gathering, crafting, navigation, building, and combat preparation.

Source: https://voyager.minedojo.org/

### 2.5 MineDojo: game knowledge can be grounded in demonstrations

[MineDojo](https://minedojo.org/) provides thousands of language-prompted Minecraft tasks and an internet-scale knowledge collection. Its project page lists 730K narrated YouTube videos, roughly 7K wiki pages, and 340K Reddit posts. MineCLIP aligns time-grounded video with language descriptions to provide a relevance signal for an attempted behavior.

**STAR application:**
- Use demonstrations to propose skills and candidate objectives, not as unquestioned truth.
- Attach source, game version, timestamp, and scope to every extracted fact.
- Convert a demonstration into a candidate procedure, then test it in the actual sandbox.
- Use visual/text similarity as a shaping signal only; require game-state evidence for completion.
- Keep external community content untrusted and never let it authorize game input or tools.

MineDojo is a 2022 research platform; its scale is useful inspiration, but its environment and data versions must be checked before adopting any artifact.

Sources:
- https://minedojo.org/
- https://github.com/MineDojo/MineDojo

### 2.6 Multi-agent Minecraft: long-horizon tasks benefit from coordination, but failures are expensive

The October 15, 2026 preprint [A team of Gemini 4 Argon agents beats Minecraft](https://arxiv.org/abs/2610.22319) reports four agents coordinating through Mineflayer, in-game chat, and shared memory to defeat the Ender Dragon in a randomly generated world. The reported run took 27 hours and 14 minutes, wrote 2,783 programs, and included 605 deaths.

**STAR application:** team mode is promising for complex, sandboxed objectives, but it needs an explicit task board and recovery protocol. Do not equate one successful long run with reliable mastery or assume the same cost is acceptable for a live stream.

Source: https://arxiv.org/abs/2610.22319

### 2.7 TREC RAG 2026: general knowledge should be evaluated as retrieval plus grounded answering

[TREC RAG 2026](https://trec-rag.github.io/) is an agent-first evaluation track with separate retrieval and retrieval-augmented-generation tasks, development/test topics, the ClimbMix-400b corpus, and the RAGDoll evaluation toolkit.

**STAR application:**
- Score retrieval separately from answer generation.
- Require evidence that supports each important claim.
- Track publisher, URL, publication/update date, retrieval date, version/scope, and uncertainty.
- Detect stale or contradictory facts instead of silently blending them.
- Evaluate multi-hop questions and practical follow-through, not only short factual recall.
- Keep source content untrusted; retrieved text cannot grant tools or permissions.

The track's public page lists its 2026 conference in November and its results/judgments as TBD at the time of this research.

Source: https://trec-rag.github.io/

### 2.8 EmbodiedHead: the avatar must know whether it is listening or speaking

[EmbodiedHead](https://arxiv.org/abs/2604.17211) proposes explicit per-frame listening/speaking state conditioning and a streaming audio scheduler to avoid spurious mouth motion while listening. It is a research talking-head system, not a drop-in Live2D replacement.

**STAR application:** carry explicit LISTENING, THINKING, SPEAKING, INTERRUPTED, and IDLE states into the existing Live2D/VTube Studio parameter layer. Mouth motion and captions must follow actual output playback, not generated text. Listening should use attentive eye/head/idle motion without fake speech motion.

Source: https://arxiv.org/abs/2604.17211

## 3. Recommended STAR execution architecture

Use one control hierarchy and one improvement loop:

```text
                 OWNER / TRUSTED HOST
                         |
                FIXED SAFETY SHIELD
                         |
                DETERMINISTIC GUARDS
                         |
             +-----------+-----------+
             |                       |
        LIVE EXECUTION           TASK / MEMORY SPINE
             |                       |
       REACTIVE SKILLS          STRATEGIC PLANNER
             |                       |
       GAME / STUDIO             CURRICULUM
       OBSERVATIONS                   |
             |                 RECURSION AGENT
             |                       |
             +---- EVIDENCE <--- CANDIDATE HARNESS
                                     |
                              TRAIN / EVOLVE SET
                                     |
                              SEALED HOLDOUTS
                                     |
                          ACCEPT / REJECT / PRUNE
                                     |
                           VERSIONED SKILL RELEASE
```

### Layer A — fixed safety shield

A deterministic host-owned layer must:
- allow only the current approved game, project, window, and session;
- enforce per-game action allowlists and deadlines;
- stop on focus loss, session mismatch, stale observation, invalid clock, or revoked consent;
- reject viewer/chat/web/OCR text as an authority source;
- keep purchases, account changes, public publishing, destructive edits, and competitive automation behind explicit owner approval;
- never allow the model to edit or bypass the shield.

### Layer B — reactive skills

Use already-verified, bounded routines for common actions: movement, camera control, jump timing, interaction, inventory selection, safe navigation, and known Studio operations. Each action chunk must return control for a fresh observation and verification.

A skill contract should bind:
- stable skill ID and semantic version;
- game/build/version and supported environment;
- preconditions and required observations;
- bounded action program and permitted inputs;
- expected state effects and independent success evidence;
- deadlines, retry budget, and stop/recovery behavior;
- known failure modes and resource envelope;
- source/provenance, tests, and dependency versions.

Treat this as a contract for the existing skill bank, not a new parallel skill store.

### Layer C — strategic planner and curriculum

The planner chooses a goal and retrieves relevant verified skills. It should use current world state, prerequisites, novelty, expected learning value, resource cost, and risk to select the next task. The curriculum should:
- start with programmatically verifiable tasks;
- expand from known skills to combinations;
- balance practice across the approved game portfolio;
- increase difficulty only after sustained, recent evidence;
- include recovery and unfamiliar-state tasks;
- avoid repeating a solved task merely to inflate success counts.

### Layer D — recursion agent

The outer agent reviews failure traces and proposes a bounded change to a skill, planner, prompt, or harness. It must not change the live executor directly.

Promotion sequence:
1. Freeze the baseline revision and evaluation plan.
2. Generate one candidate with a stated hypothesis.
3. Run static checks and safety-shield tests.
4. Evaluate on the evolve/practice set.
5. Run independent sealed, counterbalanced holdouts.
6. Check cross-game and cross-version transfer.
7. Compare quality, latency, token/compute cost, complexity, and regressions.
8. Promote as a versioned candidate only after every gate passes.
9. Keep rollback to the prior version available.
10. Prune changes that do not retain independent value.

## 4. Gamer Brain, Creator Brain, and Knowledge Brain

### Gamer Brain

- Use visual observation for unknown games and structured game-state signals where permitted.
- Keep fast control separate from strategic reasoning.
- Build a skill library from executable, scoped routines.
- Practice in private/sandboxed sessions.
- Verify objective completion from game state or an independent scorer.
- Test on held-out maps, seeds, levels, difficulty, and game versions.
- Measure recovery after failure, not only clean-run success.
- Never bypass anti-cheat or automate prohibited competitive play.

### Creator Brain

Creator Brain should use Gamer Brain as a playtester, not as the same controller that writes the game. Its loop is inspect → plan minimal change → edit isolated project → static checks → launch/playtest → capture visual/runtime evidence → repair observed defect → save/reload → independent acceptance.

For Roblox, reuse [OpenGameEval](https://github.com/Roblox/open-game-eval) and Roblox Studio's own test/runtime evidence. For broader game creation, reuse [GameDevBench](https://github.com/waynchi/gamedevbench) as a task taxonomy and evaluation reference. A green unit-test suite alone does not prove that a game is visually coherent or fun.

### Knowledge Brain

- Separate episodic events, semantic facts, and procedural skills.
- Preserve evidence pointers and validity/version ranges.
- Retrieve only the evidence needed for the current question or action.
- Mark uncertain, conflicting, or stale information explicitly.
- Evaluate with retrieval recall/precision, claim support, answer correctness, freshness, and practical task success.
- Use general web knowledge to propose hypotheses; verify important claims against authoritative sources.

## 5. Human-natural VTuber integration

The avatar and Social Brain should share one event timeline but remain separate components.

| State/event | Social behavior | Avatar behavior |
|---|---|---|
| Listening | Track addressee and conversational floor | Attentive eyes/head, no speech mouth motion |
| Thinking | Delay if the other speaker may continue | Subtle thinking expression |
| Speaking | Stream short grounded segments | Mouth/visemes follow actual playback |
| Interrupted | Stop/trim unplayed content and update history | Stop mouth motion; transition to listening |
| Gameplay danger | Prioritize game safety and concise reaction | Focused expression only when grounded |
| Laughing/excited | Use context-appropriate prosody | Expression follows an actual selected reaction |
| Idle | Silence is allowed; no forced chatter | Natural blinking and low-amplitude motion |

Do not synthesize an elaborate diffusion avatar for STAR's current Live2D pipeline before measuring its GPU cost. The useful near-term transfer from EmbodiedHead is explicit listening/speaking state and causal scheduling.

## 6. Speed and intelligence: what to optimize

The biggest likely gain is **fewer expensive model calls on already-understood actions**, not simply a larger model or more speculative decoding.

1. Use deterministic verified skills for familiar, low-uncertainty control.
2. Call the planner for new goals, uncertainty, novel scenes, and recovery—not every input tick.
3. Batch non-urgent perception and retrieval away from frame/audio callbacks.
4. Cache static game/project knowledge with exact game/project version and invalidation.
5. Keep the existing lease-based resource scheduler authoritative; do not add a second ALLOW/DEFER scheduler.
6. Benchmark local model/quant/backend/context/concurrency as matched configurations.
7. Measure first audible response, p95/p99 latency, task accuracy, game frame-time p99, audio underruns, OBS skips, RAM/VRAM, and compute cost together.
8. Reject a faster variant if it loses a previously correct held-out case or harms stream/game quality.

The [llm-speed dataset](https://llm-speed.com/) (version 2026-11-06) lists 803 results from 356 signed runs across 116 models and 19 hardware configurations. It is useful for selecting benchmark candidates and methodology, but it does not replace a matched run on STAR's actual RTX 4060/8 GB system. Do not infer a STAR speedup from another GPU's leaderboard result.

## 7. Evaluation gates

| Dimension | Evidence required |
|---|---|
| Skill correctness | Independent state-based success, not model self-grading |
| Mastery | Multiple recent distinct practice buckets and conservative confidence bound |
| Transfer | Sealed unseen maps/scenes and version changes |
| Long horizon | Completion under deadline with checkpoint/recovery evidence |
| Memory utility | Paired memory-off/on held-out action success |
| General knowledge | Retrieval evidence, supported claims, freshness, contradiction handling |
| Stream naturalness | Addressee accuracy, false interruptions, missed turns, correct silence |
| Avatar synchronization | Playback-to-frame alignment and stale-frame suppression |
| Speed | First-audible p50/p95, frame-time p99, audio/OBS stability |
| Cost | Model calls, policy tokens, CPU/RAM/VRAM, wall-clock time |
| Safety | Zero unauthorized input, publishing, purchases, or permission escalation |

Missing, stale, mismatched, or insufficient evidence is **INCONCLUSIVE**, never a pass. Use separate practice, evolve, validation, and sealed holdout data. Never let a candidate repeatedly inspect the same holdout.

## 8. Recommended implementation sequence

1. **Consolidate scheduler authority:** retain #1140/#1142 as the single lease-based resource path; do not merge a second scheduler from #1178.
2. **Reconcile the task spine:** connect task coordination, delivery acknowledgements, traces, and the authoritative worker supervisor.
3. **Connect one safe game environment:** begin with a reproducible sandbox/browser task set, then Minecraft/Mineflayer or Roblox Studio under explicit host controls.
4. **Unify skill contracts:** adapt the existing GameplaySkillBank and general skill routing; do not create a second registry.
5. **Add the outer recursion agent:** failure clustering, one-change proposals, RRSI-style regularization, sealed holdouts, complexity pruning, and rollback.
6. **Add team mode:** shared task ledger, bounded leases, explicit resource ownership, evidence-backed world-state updates, and crash recovery.
7. **Ground general knowledge:** integrate retrieval and claim-level evidence evaluation informed by TREC RAG 2026.
8. **Map avatar states:** add explicit listening/speaking/interrupted states to the existing playback-locked Live2D path.
9. **Run a 30-minute mixed-load soak:** game + OBS + avatar + voice + one CPU background task, then a separately admitted GPU task.

## 9. Safety, limitations, and non-claims

- R²SI, The Harness, and COAP-style work are robotics/agent-harness research; their reported scores are not game benchmarks for STAR.
- Voyager and MineDojo are useful design precedents, not ready-made STAR integrations.
- The four-agent Minecraft report is one long sandboxed run with substantial failure cost, not evidence of general game mastery.
- RRSI's gains are limited to its tested benchmarks; STAR must run its own sealed evaluation.
- EmbodiedHead is not a production Live2D plugin and should not be installed as one.
- No new model weights, training jobs, live game input, OBS/VTube Studio connection, provider credentials, or broadcasting permissions are enabled by this research.
- Keep raw audio, viewer profiles, credentials, local databases, signing keys, and private holdout cases outside Git.
- STAR remains transparently an AI character; natural timing and expression must not be used to deceive viewers into believing she is human.

## 9.1 New research: skill learning needs external feedback

### SkillLearnBench (22 April 2026)

Paper and code:
- https://arxiv.org/abs/2604.20087
- https://github.com/cxcscmu/SkillLearnBench

SkillLearnBench evaluates 20 verified skill-dependent tasks across 15 subdomains at three levels: skill quality, execution trajectory, and task outcome. Its findings are especially relevant to STAR:
- continual skill methods improve over a no-skill baseline, but no method wins consistently across tasks and models;
- stronger foundation models do not automatically produce better learned skills;
- reusable, clearly structured workflows are easier to improve than open-ended tasks;
- iterative external feedback supports genuine improvement, while self-feedback alone can create recursive drift.

**STAR decision:** evaluate a skill at three separate levels: (1) is the skill artifact clear, scoped, and safe; (2) does the executor follow the intended procedure; (3) does the task outcome improve on held-out cases. Do not promote a skill because its authoring model says it is better. Require external execution evidence and independent holdouts.

### Retrospective Harness Optimization (RHO, EMNLP 2026 Findings)

Paper: https://aclanthology.org/2026.findings-emnlp.2439/  
Code: https://github.com/wbopan/retro-harness  
Project: https://paper-rho.wenbo.io/

RHO selects a diverse coreset of difficult past trajectories, re-solves them, uses self-validation/self-consistency to propose harness changes, and selects among candidates with pairwise self-preference. The paper reports a SWE-Bench Pro pass-rate change from 59% to 78% after one optimization round in its evaluated setup.

**STAR decision:** borrow RHO for candidate generation over prompts, skills, tool descriptions, and workflow control flow. Do not let the optimizer see sealed holdout tasks or edit the evaluator. Self-preference is a search heuristic, not independent proof. A candidate must still pass STAR's deterministic tests, paired repeated trials, sealed task families, safety checks, and rollback gate.

Recommended STAR skill promotion sequence:

`experience → failure taxonomy → candidate skill/harness variants → development feedback → independent execution → sealed holdout → versioned promotion`

## References

- R²SI project: https://r2si.worldscape.io/
- RRSI paper: https://arxiv.org/abs/2609.24972
- The Harness (CoRL 2026): https://web.eecs.umich.edu/~stellayu/publication/2026harnessCoRLL.html
- Voyager: https://voyager.minedojo.org/
- MineDojo: https://minedojo.org/
- MineDojo repository: https://github.com/MineDojo/MineDojo
- Multi-agent Minecraft (2026-10-15): https://arxiv.org/abs/2610.22319
- TREC RAG 2026: https://trec-rag.github.io/
- EmbodiedHead: https://arxiv.org/abs/2604.17211
- Roblox OpenGameEval: https://github.com/Roblox/open-game-eval
- GameDevBench: https://github.com/waynchi/gamedevbench
- Local inference measurements: https://llm-speed.com/
