# STAR Run 15 — real-time safety, lifelong skill evolution, and integrated capability engineering

**Research date:** 2026-11-13  
**Repository:** `oncoursemail/Star-AI-Project`  
**Integration branch:** `feat/resource-admission-20261113-run21`  
**Status:** source-backed research and implementation handoff. This document adds no production capability by itself.

## Executive decision

The next meaningful STAR upgrade should be an **evidence-bound real-time agent runtime**: one that can listen, speak, play, create, research, and learn without allowing slow reasoning or untrusted inputs to control time-critical actions.

This pass adds four research transfers that were not fully developed in the previous Run 14 handoff:

1. **RT-SAFE:** evaluate safety and action freshness while the environment continues moving—not only task completion.
2. **SkillFlow + SkillLearnBench:** evolve reusable skills through trajectory evidence and independent verifier feedback; usage counts are not proof of utility.
3. **Current GameDevBench + OpenGameEval:** maintain separate, reproducible scorecards for Godot game creation and Roblox Studio work.
4. **Deeper NeMo-Speech.cpp SDK integration:** use one shared recognizer with per-utterance streaming sessions and optional microbatching, rather than repeatedly transcribing growing buffers or loading one model per speaker.

The document deliberately composes with the existing PR train. It does not add another scheduler, voice agent, playback clock, memory authority, or evaluator.

---

## 1. New safety finding: success is not the same as safe real-time behavior

### RT-SAFE

Paper: https://arxiv.org/abs/2610.09294  
Project: https://github.com/XTRose29/RT-SAFE

RT-SAFE evaluates agents in a simulated urban environment where pedestrians, traffic, and hazards continue changing while the agent reasons and acts. The paper reports that matched static and real-time settings had similar task-completion rates (91.3% and 94.1%), while real-time execution increased collisions by 12.3×. In the hardest setting, only 0.7% of episodes finished without a safety event.

These are results for the paper's embodied-navigation benchmark, not measurements of STAR. The transferable lesson is that task success can hide unsafe execution, and latency itself can make an action stale before it is applied.

### Transfer to STAR

The same failure mode appears in game control and desktop automation:

- A target moves after STAR observes it.
- A menu changes before a click arrives.
- A player is no longer at the location used by the planner.
- A viewer message arrives after the response context has changed.
- A background worker tries to apply a patch against a project revision that has moved.

Every environment-changing proposal should therefore be bound to the evidence that justified it.

### Required action envelope

A future game/desktop action proposal should contain:

- session and controller-generation IDs;
- environment/game/build identifier;
- observation ID and monotonic observation timestamp;
- observed world/project revision;
- action type and bounded parameters;
- maximum action age / expiry;
- expected preconditions;
- risk class;
- cancellation generation;
- optional idempotency key.

Immediately before execution, the trusted adapter must check the latest observation and preconditions. If the observation is stale, the world revision changed, the session was cancelled, or the action expired, reject it and request a fresh plan.

**Important:** this envelope is a host contract, not permission for a model to control arbitrary desktop actions. The host owns the allowlist, rate limits, target process, input device, and stop switch.

### Risk tiers

| Tier | Example | Default handling |
|---|---|---|
| R0 — observe | Screenshot, game-state read, project inspection | Allowed in the authorized sandbox |
| R1 — reversible in-game | Move, jump, camera, select a game item | Allowlisted controller; short TTL |
| R2 — bounded edit | Modify an isolated project copy or create a draft asset | Sandbox + tests + rollback |
| R3 — external/irreversible | Publish, spend, delete, send messages, change account/security settings | Owner approval required |
| R4 — unsafe/unauthorized | Bypass anti-cheat, exploit another player, access unrelated accounts or systems | Reject |

A game adapter must not turn a benchmark's privileged state API into an unearned advantage. When the task is visual gameplay, evaluation must use the same observation/action surface available to STAR at runtime.

### Acceptance tests

- Stale observation is rejected.
- Expired action is rejected.
- Cancelled generation cannot act.
- Wrong game/build/session action is rejected.
- A changed precondition forces re-observation.
- R3 actions cannot execute without the required owner approval.
- Controller stop works even if the reasoning model is hung.
- Every action has a traceable proposal, validation result, execution result, and observation after execution.

---

## 2. Lifelong skills: promote measured utility, not skill usage

### SkillFlow

Paper: https://arxiv.org/abs/2604.17308

SkillFlow evaluates 166 tasks across 20 task families. Its lifelong protocol starts with an empty skill library, then lets an agent patch that library using its trajectories and verifier rubrics. The reported results show both positive transfer and regressions: Claude Opus 4.6 improves from 62.65% to 71.08% on the evaluated protocol, while other configurations gain little or regress. The paper explicitly shows that frequent skill use is not necessarily useful skill use.

### SkillLearnBench

Paper: https://arxiv.org/abs/2604.20087  
Project: https://cxcscmu.github.io/SkillLearnBench/

SkillLearnBench evaluates 20 verified skill-dependent tasks across 15 subdomains at three levels: skill quality, execution trajectory, and final task outcome. It reports that external feedback and repeated improvement can help, while self-feedback alone can cause recursive drift.

### STAR skill lifecycle

Treat each skill as a versioned, testable artifact—not an unreviewed memory note.

1. **Observe:** capture a bounded task trajectory and environment/version metadata.
2. **Explain:** identify the actual failure or success mechanism.
3. **Propose:** generate a small skill patch, not a whole-library rewrite.
4. **Review:** check scope, dependencies, permissions, secrets, and unsafe instructions.
5. **Verify:** run the skill against its original task and independent sibling tasks.
6. **Canary:** use it in a disposable environment with a rollback path.
7. **Promote:** make it available only after it improves outcome quality or efficiency without unacceptable regressions.
8. **Monitor:** record success, retries, time, cost, and negative transfer.
9. **Repair or retire:** patch, quarantine, or roll back skills that regress.

### Skill artifact schema

A skill record should include:

- stable skill ID and semantic version;
- domain and task-family tags;
- preconditions and required tools;
- inputs/outputs and bounded side effects;
- executable steps or referenced implementation;
- provenance and source trajectory IDs;
- verifier suite and held-out suite IDs;
- supported application/model versions;
- success, failure, cost, latency, and regression history;
- trust level and permission requirements;
- supersedes/dependency relationships;
- rollback target.

Do not store secrets, raw viewer audio, private chat transcripts, or unrelated personal data in skills.

### Anti-patterns to test for

- **Skill inflation:** one skill per task instead of reusable workflow abstraction.
- **Negative transfer:** a skill learned in one game breaks another game.
- **Self-confirmation:** the agent marks its own output correct without an independent verifier.
- **Stale dependencies:** a skill silently assumes an old API, game patch, UI, or file layout.
- **Context bloat:** retrieving every skill because it matches a keyword.
- **Unbounded self-editing:** live streaming or production behavior changes without canary and rollback.

### Promotion rule

A skill should be promoted only when its measured utility is positive on a predefined evaluation set and its regression risk is acceptable. Compare against both the no-skill baseline and the previous skill version. Keep a sealed holdout set to prevent the skill generator from optimizing only to visible tests.

---

## 3. Game creation: separate Godot and Roblox scorecards

### GameDevBench — current public benchmark

Project: https://github.com/waynchi/gamedevbench

The current repository describes 333 Godot 4.4.1 tasks spanning:

- 2D graphics and animation;
- 3D graphics and animation;
- user interface;
- gameplay logic.

The project reports that visual image/video feedback improves evaluated agent performance, and that graphics-heavy tasks remain harder than gameplay-oriented tasks. The official task runner also uses strict confinement and a pinned Godot version for comparable results.

Use the official benchmark only after checking its license, exact release, task-distribution terms, and execution requirements. Do not silently compare results from different Godot versions or different task subsets.

### OpenGameEval — Roblox Studio

Project: https://github.com/Roblox/open-game-eval  
Paper: https://arxiv.org/abs/2610.02563

The repository describes 84 human-curated core tasks with 16 attempts per task. It separates observation tools from editing tools and checks both the edited scene and a simulated Play session. Its findings support an inspection-first workflow: inspect relevant objects before modifying them.

### STAR Creator evaluation

Keep separate benchmark suites:

| Suite | What it measures |
|---|---|
| Roblox Studio | Hierarchy inspection, Luau edits, asset placement, scene state, Play-session behavior |
| Godot | Scene/node edits, scripts, UI, 2D/3D assets, animation, runtime behavior |
| Blender | Mesh/rig/material correctness, exports, scale, naming, visual inspection |
| Cross-engine | Requirements coverage, reproducible builds, runtime stability, performance, rollback |

A task is not complete because code compiles. It must also pass the appropriate runtime and visual checks.

### Creator loop

**Inspect → Plan → Build → Run → Observe → Compare → Repair → Verify → Save skill**

For visual tasks, capture before/after screenshots or short clips and compare them against the requested acceptance criteria. Keep visual checks separate from code checks so a correct script cannot hide a broken scene, wrong scale, missing asset, or bad animation.

---

## 4. Streaming ASR: use the native streaming session correctly

### Current NeMo-Speech.cpp capabilities

Project: https://github.com/NVIDIA/NeMo-Speech.cpp  
Native SDK guide: https://github.com/NVIDIA/NeMo-Speech.cpp/blob/main/docs/sdk.md

The current project documents streaming ASR, speaker diarization, TTS, endpointing, and a stable C ABI. Its README reports 160 ms streaming-ASR chunks and vendor measurements of 2.3 ms per chunk / 67× real time on RTX 4090 and 27 ms / 6× real time on CPU. These are NVIDIA measurements, not STAR or RTX 4060 measurements.

The SDK guide exposes a concrete streaming lifecycle:

- create a recognizer;
- open a streaming recognition session;
- push float32 audio chunks;
- retrieve partial/final results;
- signal finish and drain remaining results;
- close the stream.

It also documents that one recognizer can serve independent utterances from multiple threads, while each individual stream should be driven by one thread. Compatible concurrent utterances can be microbatched through the shared recognizer's batching configuration. The SDK distinguishes resource-exhausted and unavailable errors.

### STAR integration decision

Run 14 identified that STAR's current `SpeechToText` interface is one-shot and that partial recognition may re-run ASR on an increasingly large accumulated buffer. The correct next step is an optional streaming adapter behind the existing `Engines` factory—not a replacement CallSession or a second voice-agent stack.

Recommended first prototype:

1. Keep Faster-Whisper as the fallback.
2. Build NeMo-Speech.cpp as a pinned optional local sidecar or native component.
3. Use one shared recognizer/model instance.
4. Open one stream per utterance.
5. Feed each audio sample once; do not resend the entire growing buffer.
6. Drive each stream from exactly one worker.
7. Use bounded queues and the existing resource-admission authority.
8. Publish partial transcript revisions only to ephemeral UI/preview state.
9. Only a finalized transcript may commit the user turn, enter canonical conversation history, trigger tools, or become durable memory.
10. On barge-in, mute, timeout, device loss, or shutdown, cancel the exact stream and wait for confirmed closure before releasing its resource lease.
11. Keep diarization optional and lower priority than the audio callback and final transcript.
12. Bind speaker labels to random session-scoped IDs; do not infer real identities or persist voiceprints.

### Sidecar security and packaging

- Bind only to loopback by default.
- Pin a tagged release and checksum; do not ship an unpinned nightly.
- Download model weights separately and verify hashes and model-specific licenses.
- Do not bundle model weights until distribution terms are reviewed.
- Start/stop the sidecar through the existing host supervisor.
- Keep model storage separate from the application binary.
- Test clean install, offline restart, model-missing recovery, sidecar crash, port conflict, and shutdown.
- Do not expose a local inference server to the LAN or public network by default.

### ASR scorecard

Measure on the same licensed, consented audio set:

- word error rate / character error rate;
- first partial latency;
- partial revision count and stability;
- final transcript latency;
- endpoint latency;
- speaker attribution error;
- overlap handling;
- CPU, RAM, VRAM, and GPU contention;
- cancellation latency;
- recovery after engine crash.

Do not train on benchmark audio unless the dataset license and consent explicitly permit it.

---

## 5. Inference speed: test edge MoE speculation without assuming a speedup

### S2-MoE

Paper: https://arxiv.org/abs/2608.15018  
Code: https://github.com/angerybob/S2-MoE

S2-MoE investigates routing-aware self-speculative decoding for MoE models on edge devices. Its paper reports up to 5.3× and approximately 2.0× average speedup over standard autoregressive decoding across its own tested models and datasets. This is not a STAR benchmark and should not be treated as a general llama.cpp default.

### Upstream llama.cpp MoE cache

Documentation: https://github.com/ggml-org/llama.cpp/blob/master/docs/moe-cache.md

The upstream cache is relevant when MoE expert weights stay in host memory and frequently used experts can be cached in device memory. It is not a benefit for dense models or models whose experts already fit in VRAM. The documented CPU-share option depends on RAM, PCIe transfer speed, pinning, cache size, and the model's routing pattern.

### Paired experiment plan

On the target Windows machine, compare:

1. Current production baseline.
2. Same model with supported ordinary speculative decoding.
3. S2-MoE only for a compatible MoE model/build.
4. Upstream MoE cache only when expert weights are actually host-resident.
5. CPU-only and GPU-assisted variants where supported.

Record:

- time to first token;
- decode tokens/second;
- prompt prefill tokens/second;
- p50/p95/p99 request latency;
- draft acceptance / verification overhead;
- CPU utilization and RAM bandwidth;
- VRAM peak and allocation failures;
- game frame-time p99 and OBS dropped frames during inference;
- answer quality on a fixed holdout suite.

Do not select a configuration by tokens/second alone. A faster model that loses answer quality or starves the stream is a regression.

---

## 6. Human-like streaming: social presence without deception

STAR should be a recognizable, expressive AI character—not a system pretending to be a human.

A more natural stream comes from coordinated evidence and timing:

- recognize who is speaking, with uncertainty;
- distinguish direct questions from viewer-to-viewer conversation;
- use event salience rather than narrating every frame;
- remember session-local topics and callback opportunities;
- react to verified gameplay events;
- vary delivery based on context without inserting fake stutters or fake laughter;
- allow silence and listening expressions;
- synchronize captions, audio actually played, lip motion, and avatar expressions;
- stop an answer when a human has already resolved that exact question;
- avoid fabricated personal biography, physical presence, or experiences.

### Social Director signals

A future host-side score may combine:

- directness / addressee confidence;
- event novelty and importance;
- conversation relevance;
- whether another participant already answered;
- current speaker/floor state;
- response freshness;
- moderation state;
- recent STAR speech frequency;
- current gameplay focus.

This score can prioritize cues, but it must not override the existing room director, moderation rules, consent, or host-side speaking permissions.

### Long-session evaluation

Use consented, synthetic, or licensed sessions to measure:

- correct addressee rate;
- false interruption rate;
- missed direct questions;
- response latency;
- repeated phrase rate;
- irrelevant commentary rate;
- proportion of time speaking;
- appropriate silence;
- factual grounding of reactions;
- lip-sync drift;
- playback/caption mismatch;
- viewer privacy and retention behavior.

Do not treat “more talking” as “more human.”

---

## 7. General knowledge and broad capability growth

General knowledge should be a verified research workflow, not an unbounded text dump.

### Knowledge pipeline

1. **Question decomposition:** identify what must be known and which claims are time-sensitive.
2. **Source retrieval:** prefer primary documentation, papers, official APIs, and reproducible repositories.
3. **Claim extraction:** store individual claims with source, date, version, and evidence location.
4. **Conflict detection:** preserve disagreement rather than flattening conflicting sources into one answer.
5. **Freshness policy:** expire or revalidate changing facts such as APIs, prices, model support, and platform rules.
6. **Answer synthesis:** distinguish evidence, inference, and uncertainty.
7. **Practical verification:** run code, tests, calculations, or controlled experiments where possible.
8. **Memory promotion:** retain compact, useful conclusions and procedures with provenance—not entire unfiltered pages.

### Capability areas to grow

- science, mathematics, history, geography, and language;
- software engineering and systems administration;
- Roblox, Minecraft, Godot, Unity, and Blender;
- art, UI/UX, animation, audio, and video;
- gameplay strategy and accessibility;
- research literacy and source evaluation;
- project planning, estimation, and debugging;
- teaching, practice generation, and skill transfer.

Use short retrieval tests, practical tasks, and teach-back exercises to verify learning. Do not claim that adding documents to a vector database automatically makes STAR knowledgeable.

---

## 8. Architecture fit: preserve one authority per responsibility

| Existing work | Keep as authority for |
|---|---|
| #1140 / #1142 | Resource admission and stream-pressure composition |
| #1143 | Paired quality/latency evaluation |
| #1156 | Delivery and playback evidence |
| #1159 | Live2D frame transport |
| #1177 | Durable task coordination |
| #1178 | Room direction, response stopping, and persona behavior |

Run 15 adds no second scheduler, evaluator, room director, task ledger, playback clock, or memory database.

The game action broker should be a narrowly scoped adapter that checks the latest observation and allowlist before passing input to the authorized game controller. It should not become a generic computer-control permission layer.

---

## 9. Recommended implementation sequence

| Phase | Work | Exit condition |
|---|---|---|
| A | Baseline mixed-load instrumentation | Reproducible voice/game/OBS latency and resource traces |
| B | Streaming ASR adapter prototype | Each sample fed once; final transcript parity; exact cancellation |
| C | Optional diarization | Speaker attribution improves multiparty tests without blocking audio |
| D | Observation-bound game action broker | Stale/expired/wrong-session actions always rejected |
| E | Skill versioning and verifier harness | Skill patches are reproducible, held-out tested, and rollbackable |
| F | Creator benchmark harness | Separate Roblox and Godot scorecards with visual/runtime checks |
| G | Inference experiments | Paired target-hardware results with quality and stream-performance guardrails |
| H | Long-session streamer rehearsal | Natural turn-taking and synchronized avatar behavior under mixed load |
| I | General-knowledge evaluation | Claim provenance, conflict handling, freshness, and practical task scores |

## 10. Mixed-load acceptance gate

Run STAR under a realistic combined workload:

- microphone capture and streaming ASR;
- Brain generation and TTS playback;
- Live2D/VTube Studio updates;
- OBS scene rendering/recording;
- an actual game at target resolution;
- chat ingestion and moderation;
- one bounded background research or Creator task.

Report at minimum:

| Domain | Metrics |
|---|---|
| Voice | first partial, final transcript, first audible audio, interruption stop, WER |
| Conversation | addressee accuracy, false barge-ins, missed direct questions |
| Avatar | frame age, dropped frames, lip-sync drift |
| Stream | OBS skipped frames, audio underruns, capture/render lag |
| Gaming | observation age, action age, control latency, task success, safety events |
| Inference | TTFT, prefill/decode speed, p50/p95/p99, quality score |
| Host | CPU, RAM, VRAM, GPU utilization, queue depth, lease duration |
| Learning | skill utility delta, holdout success, negative transfer, rollback rate |
| Creator | build/test pass, visual acceptance, Play-session behavior |

Establish the actual target-machine baseline before setting numerical SLOs. Keep p95/p99 and worst-case behavior; averages alone can hide stream-breaking stalls.

---

## 11. Source register

- RT-SAFE (2026-10-07): https://arxiv.org/abs/2610.09294
- RT-SAFE project: https://github.com/XTRose29/RT-SAFE
- SkillFlow (2026-04-19): https://arxiv.org/abs/2604.17308
- SkillLearnBench (2026-04-22): https://arxiv.org/abs/2604.20087
- SkillLearnBench project: https://cxcscmu.github.io/SkillLearnBench/
- GameDevBench (ICML 2026, 333 Godot tasks): https://github.com/waynchi/gamedevbench
- OpenGameEval (84 Roblox Studio tasks): https://github.com/Roblox/open-game-eval
- OpenGameEval paper: https://arxiv.org/abs/2610.02563
- NVIDIA NeMo-Speech.cpp: https://github.com/NVIDIA/NeMo-Speech.cpp
- NeMo-Speech.cpp native SDK: https://github.com/NVIDIA/NeMo-Speech.cpp/blob/main/docs/sdk.md
- S2-MoE (2026-08-15): https://arxiv.org/abs/2608.15018
- S2-MoE implementation: https://github.com/angerybob/S2-MoE
- llama.cpp MoE cache: https://github.com/ggml-org/llama.cpp/blob/master/docs/moe-cache.md

## Final engineering conclusion

STAR's next intelligence gain should be measured as **better decisions under time pressure**, not just larger prompts, more agents, more stored documents, or higher token throughput.

The strongest path is to combine:
- incremental speech processing;
- a real-time action freshness/safety gate;
- versioned skills that improve only under independent evaluation;
- separate game-playing and game-creation benchmarks;
- a single resource supervisor;
- natural, evidence-grounded streaming behavior;
- provenance-aware general knowledge.

This plan turns the existing research into a testable integration sequence while preserving STAR's local-first architecture and keeping external actions, model changes, and production defaults behind explicit gates.
