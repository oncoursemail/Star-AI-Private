# STAR research: need-aware skills, causal memory, live avatars, game mastery and inference

**Research date:** 2026-11-10  
**Implementation branch:** \`feat/general-skill-bm25-retrieval-20261110-auto11\`  
**Scope:** research synthesis and an offline evaluator. No model route, microphone, avatar, game input, OBS state, permissions, or production setting is changed.

## Executive findings

STAR already has separate foundations for general Agent Skills, gameplay evidence, paired game-transfer evaluation, continual-learning evaluation, multi-party streaming research, and model quality/speed gates. The next intelligence gain should come from measuring whether STAR knows **when** to use a capability, whether using it actually helps, and whether the experience remains useful later.

This pass adds \`benchmarks/agent_skill_need.py\`. It evaluates the missing middle stage between finding a skill and applying it:

1. Does the task actually require an external skill?
2. Does STAR decide to load one?
3. Does she load a relevant skill rather than a distractor?
4. Does the skill-assisted run improve the result?
5. What latency and context-token cost did the skill add?

The evaluator is offline, deterministic, bounded, and aggregate-only. It does not change live skill selection or claim a model-intelligence gain.

The research also points to three broader architectural opportunities:

- **Causal, just-in-time memory:** preserve immutable experience/evidence, but retrieve detailed history only when a task needs it.
- **Stateful, socially aware avatar behavior:** distinguish listening, thinking, speaking, reacting and yielding; coordinate nonverbal motion with the conversational floor.
- **Closed-loop game mastery:** separate observation from mutation, learn through controlled practice, and require independent transfer tests on unseen situations.

## 1. Need-aware Agent Skill incorporation

### Why retrieval alone is insufficient

The April 2026 paper *Skill Retrieval Augmentation for Agentic AI* and SRA-Bench separate retrieval, incorporation and application. The benchmark contains 5,400 capability-intensive instances, 636 manually authored gold skills, and a 26,262-skill corpus with 25,626 distractors.

A central finding is that the evaluated agents did not meaningfully increase skill loading when their skill-free answer was wrong: reported overall loading was 36.9% in both correct and incorrect cases. Progressive disclosure—compact metadata first, full skill instructions only after selection—was more robust to distractor noise than injecting every retrieved skill body.

This supports STAR's existing metadata-only BM25 search and identifies the next missing measurement: **need awareness and utility**.

Primary sources:
- Paper: https://arxiv.org/abs/2604.24594
- Toolkit: https://github.com/oneal2000/SR-Agents
- Dataset card: https://huggingface.co/datasets/WeihangSu/SRA-Bench

### New implementation

Added \`benchmarks/agent_skill_need.py\` and \`tests/test_agent_skill_need.py\`.

The JSONL evaluator accepts a curated task record with:
- opaque task ID and local query;
- gold need label: \`required\`, \`optional\`, or \`not_needed\`;
- gold relevant skill names;
- predicted probability that a skill is required;
- actual load/skip decision and actually loaded skill names;
- no-skill and skill-assisted outcomes;
- load latency and loaded-token cost.

It reports:
- need-decision precision, recall and F1;
- Brier score and 10-bin expected calibration error;
- required-task load rate;
- gold-skill recall on required tasks;
- precision among actually loaded skills;
- false-load rate on tasks labelled not-needed;
- optional-task load rate;
- paired no-skill versus skill-assisted success gain, including unnecessary loads so harmful over-fetch is not hidden;
- p50/p95 skill-load latency and total/mean loaded tokens.

Optional tasks are reported separately and excluded from binary required/not-needed calibration. A skill-assisted outcome is accepted only when at least one skill was actually loaded and a no-skill baseline outcome exists. The report omits task IDs and query text.

Example:

\`\`\`bash
python -m benchmarks.agent_skill_need --cases ./private-evals/skill-need.jsonl
python -m benchmarks.agent_skill_need --cases ./private-evals/skill-need.jsonl --out ./reports/skill-need.json
\`\`\`

The output path must not already exist. The benchmark does not call a model, fetch SRA-Bench, read skill bodies, or execute tools. Gold labels and task text should remain in a private, versioned evaluation dataset; do not put private user queries or viewer messages in the repository.

### Evaluation protocol

For each frozen task/model identity, compare:
1. no skill;
2. metadata only;
3. selected skill body;
4. gold skill as a diagnostic upper bound unavailable to the agent;
5. hard-negative distractors;
6. progressive disclosure versus full-content injection.

Keep backbone, prompt, runner, tool policy, context/output budget, sampling parameters and grader fixed. Interleave paired arms, preregister the task roster, and keep skill retrieval, need decision, actual load, actual use and final task utility as separate events. A model's statement that it used a skill is not evidence; use host-observed load/use receipts and objective task graders.

## 2. Causal and just-in-time memory

### AMA-Bench: agentic memory is not ordinary chat recall

AMA-Bench evaluates long-horizon memory over continuous agent-environment trajectories, including machine-generated actions and observations. The paper identifies two failure modes in existing memory systems: missing causal/objective information and lossy similarity-only retrieval. Its proposed AMA-Agent adds a causality graph and tool-augmented retrieval; the paper reports 57.22% average accuracy, 11.16 percentage points above its strongest evaluated memory baseline.

Source: https://arxiv.org/abs/2602.22769

### JAM: retrieve detailed history just in time

*Just-In-Time Agent Memory with Runtime Agentic Research* proposes a hierarchical page store with compact navigational summaries. A memorizer preserves the full history; a query-conditioned researcher retrieves, inspects and integrates only the evidence needed for the current request. The design aims to avoid both expensive full-history prompts and irreversible loss from over-aggressive pre-summarization.

Paper: https://arxiv.org/abs/2609.34385  
Code: https://github.com/VectorSpaceLab/general-agentic-memory

### APEX-MEM: temporal facts and evolving entities

APEX-MEM represents temporally grounded events in an entity-centric property graph, preserves history append-only, and resolves conflicting or changing facts at retrieval time. The ACL 2026 paper reports 88.88% on LoCoMo and 86.2% on LongMemEval.

Paper: https://aclanthology.org/2026.acl-long.749/

### Recommended STAR memory design

Do not replace STAR's existing memory stores with a second competing database. Add a query-time evidence layer over the existing governed stores:

- **Immutable experience records:** task, time, project/game version, action, observation digest, tool result, outcome and provenance.
- **Causal edges:** \`attempted\`, \`caused\`, \`blocked_by\`, \`verified_by\`, \`supersedes\`, \`derived_from\`.
- **Temporal entity facts:** preserve old values and validity intervals; resolve the current value at retrieval time rather than overwriting history.
- **Compact navigational summaries:** point to exact source records and bounded file/symbol/test anchors.
- **Just-in-time inspection:** retrieve a summary first, then fetch exact source evidence only when the task requires it.
- **Freshness checks:** revalidate file hashes, symbol anchors, model/build IDs and test results before treating historical evidence as current.
- **Memory utility evaluation:** paired memory-off/on task streams, dependent transfer probes, independent interference probes, retention probes and sealed holdouts.

A similarity score is a candidate-ranking signal, not proof that an old memory is true or current. Keep the existing continual-learning evaluator's fixed-runner, paired-arm and independent-validation discipline.

## 3. Natural VTuber streaming and avatar embodiment

### EmbodiedHead: model listening as a distinct avatar state

EmbodiedHead proposes a causal avatar pipeline with explicit per-frame listening/speaking state conditioning and a streaming audio scheduler. Its design suppresses spurious mouth movement while listening and coordinates speech-driven facial motion with turn transitions.

Paper: https://arxiv.org/abs/2604.17211

### Hallo-Live: quality-aware streaming generation

Hallo-Live explores asynchronous dual-stream audio/video generation and human-centric preference distillation. The authors report 20.38 FPS and 0.94-second latency on two NVIDIA H200 GPUs. That is a research result on high-end hardware, not an expectation for STAR's 8 GB RTX 4060.

Paper: https://arxiv.org/abs/2604.23632  
Official implementation: https://github.com/fudan-generative-vision/Hallo-Live

### Practical direction for STAR

Keep STAR's accepted stylized/Live2D mascot and existing avatar-control path. Do not replace it with a heavy generative-video model by default. Adapt the useful state model:

| Avatar state | Desired behavior |
|---|---|
| Listening | Mouth neutral/closed; subtle eye focus, blink and attentive pose |
| Thinking | Brief gaze shift or small idle motion; avoid repetitive fake gestures |
| Speaking | Audio-synchronized mouth shapes, expressive eyes and bounded head motion |
| Backchannel | Short nonverbal nod, smile or reaction; no unnecessary TTS |
| Laughing | Coordinated voice, face and body cue with a bounded duration |
| Yielding | Stop speech animation and return to listening |
| Gameplay reaction | Match the observed event and confidence; distinguish surprise, success, frustration and uncertainty |

The Social Director should coordinate:
- VAD and semantic end-of-turn;
- multi-party speaker/addressee/floor evidence;
- whether a response is actually owed;
- cancellable TTS chunk playback and barge-in;
- avatar state and lip-sync;
- short-lived session context and permitted long-term memories.

Natural streaming is not constant talking. Silence, listening, yielding and stopping after a human has answered are valid actions. Keep STAR transparently identified as AI; optimize timing, context, humor, expressiveness and continuity rather than pretending to be human.

Do not store raw audio, voiceprints, private viewer identities or full chat transcripts in the new benchmark. Use ephemeral speaker slots and aggregate measures where possible. Existing multi-party floor and cross-modal timeline work should be integrated in dependency order, not duplicated.

## 4. Gaming mastery and autonomous game creation

### OpenGameEval: inspect before editing

OpenGameEval runs agents inside reproducible, stateful Roblox Studio sessions and scores both scene changes and simulated play. The October 2026 paper describes 84 human-curated tasks and 13 evaluated models. The best reported single-attempt pass rate was 51.7%; only 39.4% of tasks were solved five times out of five. Runs that inspected every reference-relevant object before acting passed 13.4 percentage points more often on scene-only tasks and 9.8 points more often on script-only tasks than runs that inspected none.

Paper: https://arxiv.org/abs/2610.02563  
Official benchmark: https://github.com/Roblox/open-game-eval

### GameDevBench: visual feedback matters

The ICML 2026 GameDevBench release describes 132 real game-development tasks spanning code, graphics, shaders, sprites and animation. Its report highlights a significant graphics gap and improvement from image/video feedback. This supports requiring real visual inspection instead of treating successful compilation as proof of a good game.

Research overview: https://sethkarten.ai/papers/gamedevbench.html

### STAR's existing foundations

The current branch already contains:
- \`star/gameplay_skill_bank.py\`: independently signed practice/validation evidence and conservative skill suggestions;
- \`star/game_transfer_eval.py\`: paired, preregistered holdout comparisons across games and situations;
- \`star/game_skill_memory.py\`: bounded game episode evidence and practice advice;
- \`star/general_knowledge_benchmark.py\`: a narrow development-artifact consistency suite.

Extend these systems rather than creating another game skill bank.

### Recommended closed loop

\`\`\`text
Observe -> Build a state estimate -> Choose a bounded objective
   -> Practice in an isolated environment -> Measure outcome
   -> Update skill hypothesis -> Validate on unseen situations
   -> Test transfer to another map/game -> Request review
\`\`\`

For Studio/game creation, separate read-only observation from mutation:
- inspect hierarchy, scripts, properties, constraints, output and screenshots;
- identify the exact objects/symbols a change depends on;
- plan a minimal edit;
- mutate only an authorized disposable test place;
- launch and playtest;
- inspect visual state, logs and behavior;
- repair and retest;
- use independent holdouts for any claim of improved gameplay skill.

Measure game performance on a live clock as well as paused/offline tasks. Track task success, objective completion, unsafe actions, retries, latency, transfer to unseen maps/seeds, and performance regression across game genres.

## 5. Inference speed, memory pressure and mixed workloads

### llama.cpp MoE cache

The upstream MoE-cache documentation explains that frequently used experts can remain in device memory while other experts stay in host memory. \`--moe-cache-mib\` controls cache size and \`--moe-cache-cpu-share\` chooses how much of the cache-miss work is computed on the CPU rather than uploaded. The best setting depends on host RAM speed, PCIe transfer, pinned/mapped memory, model, cache size and batch regime. The upstream tuning script runs multiple configurations and models the cache behavior.

Documentation: https://github.com/ggml-org/llama.cpp/blob/master/docs/moe-cache.md

### Prompt/KV cache observability

llama.cpp's server reports \`cache_n\` (reused prompt tokens) and \`prompt_n\` (newly evaluated tokens) in timing data. Preserve a stable prompt prefix and inspect these counters before assuming prompt caching is effective. A growing context can still increase decode cost because each generated token attends over the context.

Discussion with upstream maintainer explanation: https://github.com/ggml-org/llama.cpp/discussions/29001

### TurboQuant: research, not a drop-in setting

Google Research describes TurboQuant, PolarQuant and QJL for KV-cache/vector compression. The post reports at least 6x KV-memory reduction in its evaluated setups and up to 8x attention-logit performance on H100 accelerators for a 4-bit configuration.

Official research post: https://research.google/blog/turboquant-redefining-ai-efficiency-with-extreme-compression/  
Paper: https://arxiv.org/abs/2504.19874

Do not claim those numbers on STAR's RTX 4060 8 GB. Do not enable an unofficial fork or quantized cache by default. First establish whether the exact backend/model supports it, then run paired quality and latency tests against the existing cache path.

### Mixed-load benchmark policy

Run each candidate configuration in two modes:
1. isolated inference;
2. concurrent game + OBS + voice + avatar + bounded background agent load.

Record model/build/quantization, context size, prompt prefix, cache hit/miss counters, TTFT, inter-token latency, end-to-end latency, tokens/s, VRAM/RAM, game FPS p10, OBS dropped frames, audio underruns and first-audible-PCM latency. Compare paired prompts and task quality. A faster isolated decode that causes stream stutter is a regression.

Preserve the existing priority order:
- P0: owner interruption, voice playback safety and stream control;
- P1: live conversation, avatar and gameplay perception;
- P2: interactive game actions and immediate creator feedback;
- P3: research, indexing, coding agents and asset generation.

Background work should yield under live pressure. Keep CPU/RAM optimization and stable local fallbacks as first-class goals; do not assume more GPU use is always faster.

## 6. General knowledge and transfer

A broad knowledge system should be evaluated by domain and by application, not by a single trivia score. Maintain development and sealed holdout suites across:
- mathematics and logic;
- science and engineering;
- history and geography;
- programming and software architecture;
- art, music, animation and design;
- game mechanics and game development;
- communication and languages;
- computer operations and research literacy.

For every learned fact or skill, preserve source/version, confidence, known limitations, last verification and examples of successful application. Test both direct recall and transfer to a new task. Include abstention when evidence is insufficient and regression probes to detect when new memories harm unrelated tasks.

## 7. Acceptance gates

| Area | Minimum evidence before enabling a new live behavior |
|---|---|
| Skill need decision | Held-out precision/recall, Brier/ECE, false-load rate |
| Skill utility | Paired no-skill/skill-assisted task outcomes and context cost |
| Memory | Paired memory-off/on streams, stale-evidence rejection, transfer and interference tests |
| VTuber turn-taking | Human-annotated multi-party holdout; false interruption, silence preservation and response delay |
| Avatar | Listening/speaking transition, lip-sync drift, stop/yield correctness and reduced-motion tests |
| Game mastery | Independent signed holdouts across multiple unseen situations and game versions |
| Game creation | Scene checks, real playtest, screenshot review, logs and regression tests |
| Inference | Paired quality/speed tests plus concurrent game/OBS/voice workload |
| General knowledge | Domain-level holdouts, transfer tests, provenance and abstention |

No benchmark score should directly authorize publishing, spending, changing permissions, controlling a public game, or starting a livestream. Those remain separate host/owner approval boundaries.

## 8. Sources

- SRA / SRA-Bench: https://arxiv.org/abs/2604.24594
- AMA-Bench: https://arxiv.org/abs/2602.22769
- JAM: https://arxiv.org/abs/2609.34385
- APEX-MEM: https://aclanthology.org/2026.acl-long.749/
- EmbodiedHead: https://arxiv.org/abs/2604.17211
- Hallo-Live: https://arxiv.org/abs/2604.23632
- OpenGameEval: https://arxiv.org/abs/2610.02563
- OpenGameEval source: https://github.com/Roblox/open-game-eval
- GameDevBench overview: https://sethkarten.ai/papers/gamedevbench.html
- llama.cpp MoE cache: https://github.com/ggml-org/llama.cpp/blob/master/docs/moe-cache.md
- llama.cpp prompt cache counters: https://github.com/ggml-org/llama.cpp/discussions/29001
- Google Research TurboQuant: https://research.google/blog/turboquant-redefining-ai-efficiency-with-extreme-compression/
- TurboQuant paper: https://arxiv.org/abs/2504.19874

## Verification and limitations

- The need-aware evaluator is standard-library-only and does not access model APIs or runtime services.
- Focused local tests are recorded separately from repository CI; repository CI must independently validate the committed branch.
- The evaluator needs a locally curated, versioned JSONL dataset before it can report real STAR behavior.
- No model, memory store, avatar, microphone, OBS, game input, inference configuration or production branch was changed.
- No measured speedup, improved intelligence, human-equivalent behavior, game mastery or livestream acceptance is claimed by this research pass.
