# STAR research: adaptive live-streaming calibration and generalist capabilities

**Research date:** 2026-11-11  
**Implementation branch:** \`feat/multiparty-floor-control-20261110-auto11\`  
**Implementation scope:** offline calibration and evaluation only. No microphone, audio capture, TTS, avatar, OBS, gameplay input, model weights, routing defaults, or production permissions are changed.

## Executive summary

STAR's next intelligence gains should come from tighter feedback loops, not simply adding more agents or longer prompts:

1. **Live Social Director:** understand acoustic turn boundaries, addressee, social intent, conversational history, and whether speaking is appropriate.
2. **Adaptive compute conductor:** protect the live speech/game loop from background work and optimize the whole experience rather than isolated tokens/second.
3. **Generalist Gamer:** learn in a reproducible environment, separate paused decision quality from real-time reaction, and prove transfer to unfamiliar games.
4. **Creator Brain:** inspect actual running scenes and assets, not only source code; verify changes through state and visual evidence.
5. **Evidence-backed memory:** retain what happened, what changed, what was learned, and whether old evidence remains valid.
6. **Measured improvement:** use calibration/holdout splits, paired experiments, objective game state, physical playback receipts, and target-hardware metrics.

This update adds one concrete capability: the multiparty floor evaluator now selects a conservative response-probability threshold on calibration conversations only, then evaluates that frozen threshold on conversation-disjoint holdout data. It refuses to select a threshold when the calibration set is too small.

## 1. Live voice: separate timing, task success, prosody, and grounding

### InteractionBench (2026-11-02)

InteractionBench evaluates four dimensions on the same recorded audio:
- conversational timing;
- spoken-task accuracy;
- whisper and volume control;
- grounding over conversations longer than twenty turns.

The paper reports 221 items per system across 13 scenarios and 1,519 graded runs. Among the six full-duplex systems, timing and spoken-task accuracy were rank-correlated at rho = 0.83. It measures timing where the client hears the system; substituting a server clock materially changes the result for a hosted system.

Source: https://arxiv.org/abs/2611.02430

**STAR application:** maintain separate scorecards for floor decisions, task correctness, vocal delivery, long-session grounding, and first audible PCM. Server completion time is not listener-perceived latency. A generated sentence that never reached the output device must not be recorded as something the viewer heard.

### Full-Duplex-Bench v3

FDB-v3 uses 100 human-recorded spoken requests across 79 scenarios, 12 speakers, and four domains. Tasks include disfluencies and one-to-three chained tool calls against mock APIs. It scores task completion, tool-call accuracy, latency, and turn-taking.

Source: https://www.full-duplex.ai/benchmarks/fdb-v3  
Paper: https://arxiv.org/abs/2604.04847

**STAR application:** add a spoken-tool-use test lane. The voice loop must preserve the user's corrections and intent, finish the required tool chain, and yield correctly when interrupted. Do not collapse tool correctness and turn-taking into one score.

### Realtime-Venus: continuing through non-addressed speech

The published Realtime-Venus report separates continuation through backchannels, speech directed at other people, and background speech from response to actual user interruptions. Its page reports 97% continuation through backchannels, 88% through speech directed at others, 86% through background speech, and a separately measured 75% response rate to interruptions for its evaluated system/configuration.

Source: https://realtime-venus.github.io/

These are external benchmark results, not STAR results or universal targets.

**STAR application:** measure both sides of natural floor control:
- false interruption while a person is still speaking;
- false response when speech is not addressed to STAR;
- missed response when STAR is directly addressed;
- correct continuation while a viewer speaks to another viewer;
- actual playback cancellation and time-to-silence after an authenticated interruption.

A system that never speaks can achieve a low false-response rate, so precision must always be paired with recall and task success.

## 2. New implementation: calibration-only response threshold selection

Updated:
- \`benchmarks/stream_multiparty_floor_eval.py\`
- \`tests/test_stream_multiparty_floor_eval.py\`

The evaluator now adds \`response_threshold_selection\` to schema version 2.

### Policy

- The host supplies a response probability for each annotated event.
- Calibration and holdout remain conversation-disjoint.
- At least 20 calibration events and at least five examples in each class (respond / non-respond) are required.
- Candidate thresholds are evaluated only on calibration data. A sorted score array, prefix class counts, and binary search make the sweep O(n log n) rather than rescanning every event for every candidate.
- The selected cutoff maximizes calibration recall, then F1 and precision, subject to a configurable maximum calibration false-response rate (default 5%).
- The prediction rule is explicitly \`p > threshold\`; a threshold of 1.0 is the conservative no-speech endpoint.
- The chosen threshold is frozen and evaluated once on holdout data.
- If calibration coverage is insufficient, the report says \`insufficient_calibration\` and emits no selected threshold.

CLI:

\`\`\`bash
python -m benchmarks.stream_multiparty_floor_eval \\
  --cases ./private-evals/floor-decisions.jsonl \\
  --max-calibration-false-response-rate 0.05
\`\`\`

This is an offline analysis tool. It does not change \`FloorPolicy\`, tune a production classifier, enable streaming, or authorize speech. Human-annotated, representative, consented data is still required. Calibration on four toy examples is intentionally insufficient.

### Why the holdout rule matters

Selecting a threshold on the same conversations used to report its performance leaks speaker style, recurring topics, and conversational context. STAR must freeze policy using calibration conversations, then evaluate unseen conversations once. If the holdout result is poor, revise the model/policy and collect a new independent holdout; do not repeatedly tune against the old holdout.

## 3. Game intelligence: separate decision quality from reaction speed

### GameWorld

GameWorld provides 34 browser games and 170 tasks across runner, arcade, platformer, puzzle, and simulation genres. Its evaluator reads task-relevant serialized game state and reports verifiable success and normalized progress. It also studies GameWorld-RT, where the environment continues running during inference.

Sources:
- Paper: https://arxiv.org/abs/2604.07429
- Project: https://gameworld-bench.github.io/
- Code: https://github.com/gameworld-project/gameworld

The benchmark shows why paused and live-clock results must be reported separately. Pausing isolates decision quality; real-time play also tests perception/action latency and reaction timing.

### GameDevBench

GameDevBench evaluates 333 Godot 4.4.1 game-development tasks spanning 2D graphics/animation, 3D graphics/animation, UI, and gameplay logic. Its authors report that visual image/video feedback improves agent performance in their tested setup.

Sources:
- Paper: https://arxiv.org/abs/2602.11103
- Official repository: https://github.com/waynchi/gamedevbench

### Generalist game learning and continual skill acquisition

#### SIMA 2: transfer concepts across worlds

Google DeepMind's SIMA 2 combines language reasoning with action in 3D virtual worlds. Its report demonstrates transfer of concepts such as mining in one world to harvesting in another, self-directed practice in unfamiliar games, and iterative improvement from experience. The same report also identifies limits in very long-horizon task verification, short interaction memory, precise low-level controls, and robust visual understanding.

Source: https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/

**STAR application:** represent transferable mechanics independently from game-specific bindings. A learned concept such as gather-resource, evade-hazard, navigate-to-marker, craft-item, or coordinate-with-teammate should carry explicit preconditions and a new-game adaptation phase. A skill name alone is not evidence of transfer.

#### Scaling in Games (2026-10-20)

This study evaluates 120 continued-pretraining configurations across 0.8B–27B model sizes, 50–1,600 hours of data, and five mixtures from single-world to diverse multi-world corpora. It reports that more data improves in-corpus performance, diversity helps transfer to related worlds but gives limited gains on distant worlds, and single-world training can generalize worse to distant worlds as model size increases.

Source: https://arxiv.org/abs/2610.28698

**STAR application:** train and practice across different visual styles, controls, physics, camera systems, objective structures, and genres. Track transfer distance; do not count another map from the same game as a fully independent world. Keep distant-world holdouts.

#### SkillLearnBench: skill learning needs external feedback

SkillLearnBench evaluates continual skill generation on 20 verified tasks across 15 sub-domains. Its analysis finds that iterative learning with external feedback can improve reusable workflows, while self-feedback alone can cause recursive drift; no continual-learning method wins consistently across every task/model.

Source: https://arxiv.org/abs/2604.20087  
Code: https://github.com/cxcscmu/SkillLearnBench

**STAR application:** never promote a skill solely because STAR's own critic says it worked. Require environment-derived state changes, deterministic checks where available, independent replay, and unseen-task transfer. Keep a regression suite for every promoted skill; roll back a skill when it harms previously solved tasks.

#### World-In-World: evaluate world models in closed loops

World-In-World (ICLR 2026) evaluates world models with agent players in closed-loop environments. Its paper reports that visual quality alone does not guarantee task success; controllability matters, and post-training on action-observation data plus inference-time compute can improve embodied task performance.

Source: https://proceedings.iclr.cc/paper_files/paper/2026/hash/5b4263be85820683d78675cc18d2efc7-Abstract-Conference.html

**STAR application:** a predicted future frame is useful only if it improves a real action decision. Compare predicted state transitions with observed game state; score action validity and objective progress, not visual plausibility alone. Use world-model rollouts as optional planning hints, never as the authority for whether an action succeeded.

#### ASIWorld and long-horizon survival tasks

ASIWorld proposes a persistent survival sandbox with persistent world/character state, character-scoped observations, and asynchronous actions for evaluating sustained goal execution.

Source: https://arxiv.org/abs/2610.14807

**STAR application:** add long-horizon tasks that require resource planning, recovery after death/reset, persistent objective state, and coordination of dependent subgoals. Score whether plans remain coherent after the world changes, not merely whether the next action is locally plausible.

### Recommended skill contract

Every game skill should be a versioned contract:

- **Preconditions:** required game state, equipment, resources, permissions, and environment version.
- **Observation requirements:** what state/screen cues must be visible before acting.
- **Action policy:** bounded actions and allowed control interface.
- **Expected state delta:** objective progress, inventory change, position, health, score, or other verifiable effect.
- **Termination:** exact success, failure, or timeout condition.
- **Recovery:** safe retry, reset, retreat, or alternate strategy.
- **Evidence:** trajectory ID, environment version, independent verifier, and held-out transfer result.
- **Regression suite:** previously solved scenarios that must remain solved after the skill changes.

Promote only after repeated success across distinct scenarios and an unseen transfer task. Store failures as counterexamples with their exact preconditions; do not compress away the reason a skill failed.

### STAR game architecture

Continue using existing systems rather than creating parallel memory stores:
- \`star/gameplay_skill_bank.py\`
- \`star/game_skill_memory.py\`
- \`star/game_transfer_eval.py\`

Recommended loop:

\`observe -> identify objective -> plan -> act in a sandbox -> inspect state -> inspect visual result -> diagnose -> repair -> retest -> evaluate on an unseen scenario\`

For every run, record the exact game/engine version, task version, action interface, observation cadence, inference latency, step budget, objective-state progress, terminal success, invalid actions, and reset behavior.

For Roblox Studio, inspect hierarchy, scripts, properties, assets, and visual state before editing. Use disposable test places and synthetic player data. Production publishing, live DataStore writes, monetization, player-impacting actions, and external asset publication remain owner-approved operations.

## 4. Memory: traceable experience, temporal updates, and skill transfer

### AMA-Bench

AMA-Bench evaluates memory on long agent-environment trajectories composed of states, actions, observations, and tool outputs. Its paper argues that memory systems lose causal/objective information when they rely primarily on similarity retrieval.

Source: https://proceedings.mlr.press/v306/zhao26bs.html  
Project: https://ama-bench.github.io/

### LongMINT

LongMINT tests memory under evolving facts and interference. Its dataset contains 15.6k QA pairs over long contexts averaging 138.8k tokens and extending to 1.8M tokens. The paper reports that retrieval and memory construction are major bottlenecks and that later updates can interfere with earlier facts.

Source: https://arxiv.org/abs/2605.18565

### MemWeaver

MemWeaver combines temporal graph memory, reusable experience memory, and evidence-preserving passage memory. Its dual-channel retrieval joins structured relations with supporting source passages.

Source: https://arxiv.org/abs/2601.18204

### Recommended STAR memory fabric

Keep three linked but distinct layers:

1. **Event trace:** immutable, timestamped observations, tool actions, outputs, model/version identifiers, and test receipts.
2. **Semantic state:** current facts, entities, relationships, temporal validity, source provenance, confidence, and contradiction links.
3. **Procedural skills:** reusable instructions with preconditions, tool versions, expected outcomes, failure modes, and verification tasks.

A memory promotion should require:
- source and timestamp;
- whether the item is observed, inferred, or user-provided;
- project/model/game version;
- independent verification where possible;
- freshness/expiry policy for perishable facts;
- conflict check against current state;
- reversibility and a reason for retention.

Never let an untrusted viewer message, retrieved webpage, generated plan, or tool output directly rewrite durable identity, permissions, or production configuration. Keep private viewer memory opt-in, minimal, and separate from raw stream media.

## 5. Inference speed: memory movement and service-level objectives

### FlashOffloading (2026-11-05)

FlashOffloading studies host-DRAM-centric KV-cache offloading with rolling GPU cache, a decode hot cache, sparse indexing, and overlapped computation/loading. The paper reports gains on an Ascend 910C prefill/decode-disaggregated platform under a 30 ms time-per-output-token objective.

Source: https://arxiv.org/abs/2611.07542  
Code: https://github.com/vllm-project/vllm-ascend/tree/releases/v0.30.0

**Hardware caveat:** those results are not evidence of a speedup on STAR's RTX 4060 8 GB system. The Ascend kernels and platform are not directly portable. The useful lesson is to measure cache movement, hot/cold locality, and overlap rather than assume that moving KV to host RAM is free.

### TurboQuant

TurboQuant explores low-bit online vector quantization for KV-cache memory reduction.

Paper: https://arxiv.org/abs/2504.19874  
Google Research: https://research.google/blog/turboquant-redefining-ai-efficiency-with-extreme-compression/

**STAR application:** only test quantized KV when the exact inference runtime/model format supports it. Compare paired output quality, long-context retrieval, first-token latency, inter-token latency, RAM/VRAM, and mixed-load frame-time. Do not apply a research kernel to production just because its paper reports a favorable H100 result.

### Target-hardware benchmark matrix

For each pinned model/build:
- cold and warm prefix-cache runs;
- prompt/prefill tokens per second;
- time to first token;
- inter-token latency and p50/p95;
- context length and active sequence count;
- KV-cache size and precision;
- RAM, VRAM, CPU utilization, and PCIe transfer;
- speculative draft acceptance and end-to-end quality;
- paired task accuracy and abstention;
- game frame-time p50/p95, OBS dropped frames, audio underruns, and first-audible-PCM latency under concurrent load.

Use a service-level objective for the live loop. Background indexing, model evaluation, asset rendering, and research should yield to authenticated owner interruption, live voice, and time-critical gameplay. A higher tokens/second number is not a win if the game stutters or speech becomes late.

## 6. VTuber embodiment: make behavior coherent, not merely animated

Use one explicit host-owned state machine:

\`\`\`text
LISTENING
  -> SPEECH_CANDIDATE
  -> TURN_COMPLETE
  -> ADDRESSEE_RESOLVED
  -> FLOOR_DECISION
      -> RESPOND -> TTS_QUEUED -> SPEAKING
      -> BACKCHANNEL -> NONSPOKEN_CUE
      -> LISTEN / SILENCE
      -> HOLD
  -> YIELDING
  -> LISTENING
\`\`\`

Avatar behavior should be driven by actual state:
- mouth movement from played audio, not generated text;
- listening expressions while speech is actually arriving;
- neutral mouth and yield animation after playback is physically stopped;
- laughter only when the speech/context policy selects it;
- expression intensity bounded by the configured persona;
- reduced-motion and user-controlled animation settings respected;
- no false lip-sync after cancellation;
- no persistent real-world identity inferred from anonymous diarization slots.

### InteractiveAvatar: long-duration visual consistency and intent-aware reactions

The InteractiveAvatar research proposes continuous streaming avatar generation with a Long-Short Visual Memory mechanism for visual consistency and a Reasoning-Reaction Module for aligning avatar speech/actions with user intent.

Paper: https://arxiv.org/abs/2606.22905

**STAR application:** borrow the state-management idea, not the heavyweight video-generation stack. Maintain compact short-term expression state plus a slower-changing persona/appearance state. Route intent to a bounded reaction vocabulary, then synchronize the reaction with the actual voice/playback state. Avoid generating a new full avatar video for every response when a deterministic Live2D rig can produce the required expression more cheaply and consistently.

Naturalness is not maximum motion or maximum talking. It is appropriate timing, coherent reactions, remembering relevant context, and being comfortable with silence. STAR remains transparently identified as an AI streamer.

## 7. General knowledge and multimodal tool use

### AgentVista (NeurIPS 2026)

AgentVista evaluates general multimodal agents on 209 expert-curated tasks across 25 sub-domains and seven broad categories. Tasks use realistic visual scenes and require multi-step workflows that interleave visual evidence with tools such as web search and code execution. Its November 2026 repository update reports 35.4% overall accuracy for the strongest listed model/configuration; this is an external benchmark result, not a STAR score.

Source and benchmark code: https://github.com/hkust-nlp/AgentVista

**STAR application:** general knowledge should not be reduced to trivia. Evaluate whether STAR can inspect a diagram, locate the relevant evidence, compare sources, perform calculations, use a tool, and produce a verifiable answer. Use distinct holdout tasks across:
- academics and scientific figures;
- technology and hardware troubleshooting;
- geography and map reasoning;
- society and policy/current events;
- culture and art;
- entertainment and media;
- commerce and product constraints.

For every answer, preserve claim-level source provenance, publication/observation date, freshness, uncertainty, and the exact tool evidence used. Separate stable knowledge (e.g. mathematics) from perishable knowledge (e.g. current releases or prices). When evidence conflicts or is stale, abstain or research again rather than inventing certainty.

Recommended knowledge loop:

\`question -> decompose claims -> retrieve authoritative evidence -> cross-check -> calculate/use tools -> answer with uncertainty -> delayed recall test -> update provenance\`

Do not let a model grade its own answer as the only correctness signal. Prefer exact answers, deterministic calculations, independently checked sources, or human-reviewed labels. For visual questions, retain the minimal evidence region and source reference rather than storing entire private images or conversations.

## 8. Unified feature roadmap

| System | New capability | Proof required |
|---|---|---|
| Live Social Director | Addressee, speech-act, group floor, overlap, interruption | Conversation-disjoint annotated audio tests |
| Voice Execution | Full-duplex TTS, cancellation, physical flush, heard-only history | First-audible and interrupt-to-silence receipts |
| Avatar Embodiment | Lip-sync, listening, thinking, laughing, yielding | Host playback/rig state alignment |
| Adaptive Compute Conductor | Priority classes and preemption for background work | Mixed game + OBS + voice rehearsal |
| Star Gamer | Cross-game skill acquisition and transfer | Unseen maps/tasks, live-clock objective scores |
| Star Creator | Code + asset + scene inspection and repair | GameDevBench-like task suite and visual acceptance |
| Memory Fabric | Event, semantic, and procedural memory with provenance | AMA-Bench/LongMINT-style temporal/interference tests |
| General Knowledge Lab | Research, source verification, uncertainty, domain practice | Held-out factual and applied tasks |
| Skill Workshop | Extract reusable skills from verified traces | Need-aware retrieval and skill-transfer evaluation |
| Reliability Console | Trace failures, regressions, latency and resource contention | Reproducible run receipts |

Suggested compute priority:
- P0: authenticated owner stop/interruption and safety actions;
- P1: live audio, turn-taking, and speech cancellation;
- P2: immediate game perception and input acknowledgement;
- P3: short-horizon gameplay reasoning and viewer responses;
- P4: background research, indexing, training/evaluation, rendering.

The host must enforce these priorities. Prompt text alone is not a scheduler.

## 9. Acceptance plan

Before calling STAR a natural, reliable live streamer:

1. Use owner-consented, human-annotated conversations with entire conversations disjoint between calibration and holdout.
2. Evaluate EOT/INT separately from addressee/floor decisions.
3. Report response precision, recall, false-response rate, group/side/backchannel/overlap errors, and confidence calibration.
4. Capture first audible PCM, playback cancellation, physical time-to-silence, and avatar state transitions at the actual Windows output device.
5. Run a private 30–60 minute session with game + OBS + voice + avatar + background work.
6. Record game frame-time p50/p95, input acknowledgement, OBS dropped frames, audio underruns, CPU/RAM/GPU/VRAM, model TTFT/TPOT, and first-audible latency.
7. Evaluate game skill on both paused and real-time tracks, then on unfamiliar tasks.
8. Re-run memory tests after facts are revised and after a delay.
9. Keep all reports aggregate-only; do not publish private audio, transcripts, viewer identities, or voiceprints.

No benchmark score, external paper result, offline test, or model-generated self-report proves human equivalence. Report only what STAR actually measured on its own hardware and held-out data.

## References

- InteractionBench (2026-11-02): https://arxiv.org/abs/2611.02430
- Full-Duplex-Bench v3: https://www.full-duplex.ai/benchmarks/fdb-v3
- Realtime-Venus: https://realtime-venus.github.io/
- GameWorld: https://arxiv.org/abs/2604.07429
- GameDevBench: https://github.com/waynchi/gamedevbench
- AMA-Bench: https://proceedings.mlr.press/v306/zhao26bs.html
- LongMINT: https://arxiv.org/abs/2605.18565
- MemWeaver: https://arxiv.org/abs/2601.18204
- FlashOffloading (2026-11-05): https://arxiv.org/abs/2611.07542
- TurboQuant: https://arxiv.org/abs/2504.19874
