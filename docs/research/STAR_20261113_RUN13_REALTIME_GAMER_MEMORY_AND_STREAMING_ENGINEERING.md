# STAR Run 13 — Real-Time Gamer, Memory-Hierarchy Inference, and Natural Streaming

**Research date:** 2026-11-13  
**Repository:** `oncoursemail/Star-AI-Project`  
**Target branch:** `feat/resource-admission-20261113-run21`  
**Status:** research transfer and engineering decision record; no new runtime capability is implied by this document.

## Executive decision

STAR's next meaningful capability gain should come from making the existing systems cooperate under a single, measurable runtime—not from adding more agent personas or another scheduler.

This research adds four current findings to the existing development plan:

1. **Real-time game control is a different problem from paused game reasoning.** Gym-Anything-RT reports a 9% pass rate for GPT-6 Astra (xHigh) in real-time versus 75% with the same minigames paused. A screenshot-and-reason loop is therefore not a sufficient controller.
2. **Reusable skills can reduce repeated exploration, but only when independently verified.** Continual Harness reports that 62% of its executed actions across 25 games came from saved skills. That is a result for its own harness/model/evaluation, not a forecast for STAR.
3. **Host RAM can be part of the inference memory hierarchy, but offload is not automatically faster.** StrataFlux and FlashOffloading show promising overlap/precision-streaming techniques on specific platforms. Neither result establishes compatibility or speedup on STAR's 8 GB RTX 4060 class machine.
4. **Natural streaming is an endpointing/turn-taking optimization problem, not just a personality prompt.** LiveKit EoT-Bench evaluates causal pause decisions across 14 languages and exposes the false-cutoff versus response-delay tradeoff.

The repository already has draft work for resource admission, task/delivery durability, incremental reasoning, room direction, voice, and Live2D transport. The correct next step is to integrate those contracts in dependency order and validate them on the real Windows host.

## 1. Repository truth and boundaries

The default-branch README describes the published v1.0 product as a local-first Windows chat application with optional model/server, web, Roblox, Blender, Discord, and a server-side practice loop. It explicitly warns that open PRs, CI artifacts, and passing tests do not make a feature part of the installer. It also says the v1.0 evaluation did not demonstrate a smarter base model than v0.9.0.

Keep these maturity labels everywhere:

- **Shipped:** included in the latest published installer and release notes.
- **Opt-in shipped:** included in the release but requires setup and explicit activation.
- **Draft implementation:** code exists on an unmerged branch/PR.
- **Research only:** paper, benchmark, design, or offline plan; no runtime capability implied.
- **Host acceptance pending:** requires real Windows, GPU, microphone, OBS, VTube Studio, Studio, or game testing.

This document is research/engineering guidance. It does not enable a game controller, connect streaming accounts, install models, modify weights, change permissions, or alter release defaults.

## 2. New real-time interaction evidence: Gym-Anything-RT

**Paper:** [Gym-Anything-RT: Scaling Real-Time Environments for Vision-Language Agents](https://arxiv.org/abs/2610.37567)  
**Submitted:** 2026-10-27  
**Project/code:** [gym-anything/gym-anything-rt](https://github.com/gym-anything/gym-anything-rt)

The benchmark generates 100 visual minigames and can run the same task in real time, slowed, or paused. The paper reports GPT-6 Astra (xHigh) at 9.0% pass rate in real time and 75.0% when paused. It also notes that agents with code-writing capability sometimes bypass visual real-time control by writing code that exploits environment access.

**Interpretation for STAR:** high reasoning quality does not imply low-latency embodied control. STAR must be evaluated on the actual observation-to-action loop, with the game clock running. Benchmark adapters must also prevent privileged state access or game-specific shortcuts when the intended task is visual control.

### 2.1 Required control hierarchy

| Loop | Intended cadence (initial design range, not a hard runtime setting) | Responsibility | Must not do |
|---|---:|---|---|
| Device/audio callback | 5–20 ms blocks, engine-dependent | Keep audio capture/playback deadlines | Wait for an LLM or disk |
| Reflex controller | 10–50 ms | Input timing, movement primitives, camera stabilization, safe stop | Perform open-ended reasoning |
| Visual/event perception | 50–200 ms or event-triggered | Detect scene changes, hazards, UI state, target/objective changes | Reprocess every frame with a large model |
| Tactical planner | 250 ms–2 s | Route, combat, objective and resource decisions | Emit unbounded or stale actions |
| Strategic planner | Seconds to minutes | Long-horizon goals, progression and team strategy | Block reflex or voice loops |
| Learning worker | Background/offline | Replay analysis, skill proposals, held-out evaluation | Change live policy during a stream without approval |

These ranges are design starting points. They must be calibrated per game, device, input API, and host load.

### 2.2 Observation-bound action contract

Every model-proposed game action should be a typed, bounded proposal containing:

- session ID and controller generation;
- game/build identifier;
- observation ID and world revision;
- monotonic observation timestamp and clock epoch;
- action schema and bounded parameters;
- short expiry/deadline;
- expected preconditions;
- cancellation/supersession token;
- reason/evidence reference for audit.

The trusted host must reject an action when the world revision changed, its expiry elapsed, the session ended, the schema is invalid, or the controller generation was revoked. The model never receives arbitrary shell access or unrestricted keyboard injection. A safe-stop action must remain available independently of the language model.

### 2.3 Gamer skill loop

1. Define the task and observable success condition.
2. Run a baseline attempt with a fixed seed or recorded scenario.
3. Record bounded observation/action/result events.
4. Identify the smallest causal failure, not merely the final loss.
5. Generate a candidate skill or controller adjustment.
6. Replay deterministic cases.
7. Test unseen seeds, maps, and mechanics.
8. Compare with no-skill and distractor-skill controls.
9. Promote only if the held-out gain clears a predeclared threshold without violating safety or latency.
10. Version the skill and preserve rollback.

A skill record must include game/version, preconditions, action schema, success evidence, failure modes, evaluation set, confidence, provenance, and version. One win is not mastery.

### 2.4 Gamer scorecard

- task completion rate across repeated seeds;
- held-out map/mechanic transfer;
- objective completion time;
- invalid action rate;
- stale action rate and action age at execution;
- recovery after unexpected events;
- resource efficiency;
- controller CPU cost;
- input-to-action latency;
- game frame-time p50/p95/p99 under concurrent streaming;
- regressions versus the previous skill version.

Use [GameWorld](https://gameworld-bench.github.io/) for broad multimodal browser-game evaluation and [OpenGameEval](https://github.com/Roblox/open-game-eval) for Roblox Studio exploration/edit/Play-session tasks. They measure different things and should remain separate scorecards.

## 3. Continual Harness: skills as reusable executable knowledge

**Project:** [Continual Harness](https://continual-harness.github.io/)  
**Research context:** [ARC-AGI-3](https://arcprize.org/arc-agi/3)

Continual Harness describes a reset-free agent harness with persistent state, memory, reusable skills, subagents, and a refiner that reviews trajectories and updates the harness. Its project report says that across 25 games, 62% of executed actions came from saved skills. It also reports a 20.54% public-set result in the stated ARC-AGI-3 evaluation, so the skill-reuse observation must not be mistaken for broad game mastery.

### STAR transfer

Use the existing skill retrieval and governed learning work; do not create a second skill database.

Separate three gates:

1. **Retrieval:** did STAR retrieve the right skill for this state?
2. **Incorporation:** did she correctly interpret its preconditions, limitations and steps?
3. **Application:** did it improve the result on a held-out task?

Add controls for no skill, a relevant skill, and a plausible-but-wrong distractor. Measure tokens, latency, invalid actions and final task success. Keep the original trajectory and provenance for every promoted skill.

A trajectory refiner may propose changes, but it must not edit the evaluator, success oracle, holdout set, permissions, or its own promotion threshold. Human review remains required for changes that alter tool permissions, public actions, or persistent policy.

## 4. New inference research: StrataFlux and FlashOffloading

### 4.1 StrataFlux

**Paper:** [StrataFlux: Memory-Hierarchy-Native Low-Bit LLM Inference](https://arxiv.org/abs/2611.08363), 2026-11-05.

StrataFlux uses selective precision streaming from host RAM/SSD, overlapping delivery with compute and reusing fetched precision. The paper evaluates 2–4-bit weights and 2–3-bit KV cache. On an RTX 5090, its reported 2-bit Qwen3-8B configuration raises AIME 2024/2025 accuracy from 11.0% to 47.1% at unchanged GPU memory use; this is a paper-specific result, not a STAR measurement.

**STAR decision:** retain as a research candidate. Do not assume the technique is available in the pinned llama.cpp build, the selected model architecture, or the owner's RTX 4060. Verify source code, model support, license, and exact runtime flags before any prototype.

### 4.2 FlashOffloading

**Paper:** [FlashOffloading: Low-Latency KV Cache Offloading for Long-Context LLM Serving](https://arxiv.org/abs/2611.07542), 2026-11-05.

The paper uses host DRAM, rolling/hot HBM caches, sparse indexing and compute/load overlap. Its reported up-to-1.38x prefill and 1.91x decode throughput improvements are from GLM-5.2 with MTP3 on an Ascend910C prefill/decode-disaggregated platform. It is integrated in [vllm-ascend](https://github.com/vllm-project/vllm-ascend/tree/releases/v0.30.0).

**STAR decision:** this is a design reference for memory-tier scheduling, not a drop-in RTX 4060 optimization. Do not copy its speedup into STAR's performance claims.

### 4.3 Practical llama.cpp experiments

The upstream [llama.cpp speculative decoding guide](https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md) documents draft-model, n-gram and EAGLE-3 approaches. The [SPEED-Bench client](https://github.com/ggml-org/llama.cpp/tree/master/tools/server/bench/speed-bench) measures throughput, latency and draft acceptance against a running server. The [MoE cache guide](https://github.com/ggml-org/llama.cpp/blob/master/docs/moe-cache.md) describes a cache for MoE experts kept in host memory; it is not applicable to dense models.

Run the existing engine's supported candidates before considering a custom offload implementation.

### 4.4 Matched benchmark protocol

Pin and record:

- model file hash, tokenizer/template, quantization and context length;
- llama.cpp commit/build flags, driver, GPU and OS;
- thread count, NUMA placement, server slots and prompt-cache policy;
- prompt set, output cap, warm-up, repetitions and concurrency;
- draft model/version and accepted draft tokens;
- peak VRAM, host RAM, page faults and transfer volume.

Measure separately:

- model load time;
- prompt prefill tokens/s and time-to-first-token;
- decode tokens/s and time-per-output-token;
- first client content chunk;
- first audible sample;
- total end-to-end response time;
- queue wait and cancellation time;
- task accuracy, tool correctness and groundedness.

Compare idle, game-only, OBS-only, voice-only, game+OBS+voice, and mixed foreground/background workloads. A candidate wins only when it improves a predeclared latency or capacity objective while remaining within a quality non-inferiority margin and real-time resource guardrails. Higher tokens/s alone is not a win if first-audible latency, game p99, or audio stability regresses.

## 5. Natural streaming: use causal endpointing metrics

**Benchmark:** [LiveKit EoT-Bench](https://github.com/livekit/eot-bench) and [dataset](https://github.com/livekit/eot-bench-data).

The benchmark contains real human-to-agent turns across 14 languages and annotates silence pauses of at least 100 ms. Earlier pauses are mid-turn hesitations; the final pause is the actual end of turn. It evaluates the production decision—respond now or keep listening—rather than only offline classification accuracy.

Its published comparison illustrates the tradeoff. At a 5% false-cutoff budget, the reported English endpointing delay is 543 ms for LiveKit Turn Detector v1, versus 1,600 ms for a silence-only VAD baseline. At a 300 ms latency budget, the reported false-cutoff rates are 9.9% and 55.6%, respectively. These are benchmark operating points, not STAR targets or guarantees in noisy live streams.

### STAR transfer

Reuse the existing voice turn detector and causal evaluator. Add a dataset/adapter integration only after checking the dataset's licence and audio-data policy. Do not build a competing endpointing engine just to consume this benchmark.

Score:
- false cutoff rate;
- endpointing delay at fixed cutoff budgets;
- missed endpoint rate;
- language/noise/speaker-count breakdown;
- addressee precision and recall;
- backchannel-versus-interruption classification;
- false interruption and missed interruption;
- recovery after an incorrect stop;
- first-audible latency after a true turn end.

Tune on development data and retain a sealed, consented holdout. Do not use public benchmark audio to train STAR unless the dataset's explicit licence and terms permit that use.

## 6. VTuber social presence: a coordinated audiovisual state machine

A natural stream requires the speech pipeline, conversation-floor authority, event understanding, personality, playback ledger and avatar to agree on what is happening.

### 6.1 Social decision

For every candidate utterance, evaluate:

- whether STAR was directly addressed;
- whether the message is meant for another viewer;
- whether the current topic is still active;
- whether the event is novel or important;
- whether someone already answered;
- evidence confidence;
- current speaker/floor owner;
- pending speech backlog;
- game concentration and stream pressure.

Possible decisions: speak, short backchannel, queue, wait, ignore, interrupt, or stop. The prompt can shape style but cannot grant speaking permission.

### 6.2 Avatar timing

- Use the actual audio playback clock as the mouth/viseme authority.
- Associate every speech segment and avatar sample with a turn generation and playback epoch.
- Drop stale animation samples after interruption or a new turn.
- Keep durable speech segments ordered; latest-wins coalescing is appropriate only for replaceable animation frames.
- Return to listening/neutral only after the old playback generation is fenced and settled.
- Measure speech-to-viseme skew and stale-frame age.

### 6.3 Long-session rehearsal

Use private, consented 30–120 minute rehearsals with multiple speakers, viewer-to-viewer conversation, game events, silence, topic changes and interruptions.

Track repeated catchphrase rate, appropriate response rate, silence quality, speaker/addressee accuracy, false interruptions, grounded commentary, speech latency, avatar synchronization, and stream stability. A single-turn demo is not sufficient.

STAR may have a warm, curious, funny, expressive fictional AI personality. She must remain transparent that she is an AI and must not fabricate human biography or lived experience.

## 7. More capability areas worth building

These are capability families, not a promise that each should become a separate always-running agent.

| Capability | Useful first version | Evidence of success |
|---|---|---|
| General knowledge/research | Source-ranked research with claim-to-source mapping, dates and contradictions | Factuality, source quality, correction rate |
| Tutoring | Adaptive lessons, exercises, worked examples and spaced review | Retention and transfer to unseen questions |
| Game coaching | Explain a mechanic, create a practice drill, compare replays | Improvement across repeated/held-out attempts |
| Game creation | Roblox/Godot inspect → edit → run → visually inspect → repair | Benchmark tasks plus human quality review |
| Creative studio | Art, story, music/audio, animation and asset pipelines with provenance | Output acceptance and reproducible project files |
| Project operator | Durable task board, dependencies, checkpoints and verified delivery | Completion rate and crash recovery |
| Personal knowledge | User-approved notes, project decisions and searchable history | Correct retrieval and correction propagation |
| Stream production | Segment ideas, scene-state suggestions, captions and clip markers | Operator-approved output and low distraction |
| Learning planner | Identify skill gaps and schedule bounded practice when idle | Measured transfer without foreground regression |

Do not make all of these always active. Route work by user intent, deadline, resource budget and evidence requirement.

## 8. One runtime with explicit authorities

The existing PR stack should remain the authority for each domain:

| Concern | Existing owner to preserve | Integration rule |
|---|---|---|
| Resource admission | #1140/#1142 | One lease-based supervisor; no duplicate scheduler |
| Task lifecycle | #1177 and worker lifecycle work | Durable, idempotent tasks and fenced worker termination |
| Conversation floor | #1176/#1178 room director | Typed event-linked stop/interrupt semantics |
| Playback truth | Existing voice delivery/playback ledger work | Only acknowledged audio is treated as spoken |
| Avatar transport | #1159 | Playback-epoch-bound, latest-wins visual samples |
| Incremental reasoning | #1160–#1164 | Read-only/cancellable until final transcript and permissions allow action |
| Skill/memory promotion | Existing governed learning/memory work | External evaluator and sealed holdout |
| Tool permission | Existing host permission layer | Model output and retrieved content cannot grant authority |

### Required cross-loop event envelope

Every event crossing components should carry:

- opaque event ID;
- session, task and generation IDs;
- monotonic timestamp and clock epoch;
- source and trust classification;
- evidence references;
- observation/world revision where applicable;
- expiry/deadline;
- cancellation/supersession state;
- privacy/retention classification.

Do not place raw audio, viewer transcripts, screenshots or game footage in general telemetry. Content evidence belongs in a separate, consented and retention-bounded store.

### Failure/recovery rules

- Task writes use idempotency keys and compare-and-swap revisions.
- A worker lease remains fenced until the host confirms process-tree termination.
- Reconnects resume from durable task/delivery state; they must not duplicate a spoken segment or game action.
- If host telemetry is missing or stale, defer new background work rather than guessing capacity.
- Emergency stop and broadcast-disable must be host controls independent of the language model.
- Viewer chat, OCR, game text, web pages and model outputs are untrusted input.

## 9. Integration order

1. Reconcile the actual PR dependency graph and select one reviewed integration train.
2. Finish one resource supervisor with calibrated host telemetry and lease fencing.
3. Complete durable task → delivery → playback receipts and crash recovery.
4. Finish the voice room director with real ASR, speaker and addressee adapters.
5. Connect authenticated VTube Studio and OBS adapters behind explicit opt-in and revocation.
6. Run EoT-Bench-compatible offline evaluation and consented multi-speaker rehearsal.
7. Build the game observation/action adapter with stale-action rejection and safe stop.
8. Add deterministic practice/replay and skill promotion using held-out seeds.
9. Connect Roblox OpenGameEval and Godot GameDevBench-style tasks.
10. Run inference candidates using llama.cpp's supported benchmark tooling.
11. Evaluate memory/skill retrieval and continual refinement against no-memory controls.
12. Only then promote selected capabilities into a release.

Do not retarget child PRs to `main` just to make them look mergeable. Merge or integrate in dependency order, then rerun full CI on the exact final head.

## 10. Acceptance gates

Before calling a capability available:

- exact-head Python tests, lint, type checks and frontend tests pass;
- Windows packaged-app smoke test passes;
- the actual target model/runtime/hardware are recorded;
- real microphone and speaker tests pass for voice;
- OBS/VTube Studio authentication, reconnect, revocation and emergency stop pass;
- a 30-minute minimum mixed-load rehearsal covers game + OBS + voice + avatar + one bounded background worker;
- report p50/p95/p99 latency, audio underruns, OBS drops, game frame time, stale actions and queue wait;
- held-out task success improves without violating the quality/latency margin;
- crash/power-loss tests do not duplicate actions or speech;
- release notes distinguish shipped, opt-in, draft and untested features.

The 30-minute run is a minimum smoke/soak gate, not proof of long-term reliability. Extend to multi-hour runs before public autonomous streaming.

## 11. Source register

- Gym-Anything-RT paper: https://arxiv.org/abs/2610.37567
- Gym-Anything-RT code: https://github.com/gym-anything/gym-anything-rt
- Continual Harness: https://continual-harness.github.io/
- StrataFlux: https://arxiv.org/abs/2611.08363
- FlashOffloading: https://arxiv.org/abs/2611.07542
- vLLM Ascend implementation: https://github.com/vllm-project/vllm-ascend/tree/releases/v0.30.0
- llama.cpp speculative decoding: https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md
- llama.cpp SPEED-Bench: https://github.com/ggml-org/llama.cpp/tree/master/tools/server/bench/speed-bench
- llama.cpp MoE cache: https://github.com/ggml-org/llama.cpp/blob/master/docs/moe-cache.md
- LiveKit EoT-Bench: https://github.com/livekit/eot-bench
- LiveKit EoT dataset: https://github.com/livekit/eot-bench-data
- GameWorld: https://gameworld-bench.github.io/
- OpenGameEval: https://github.com/Roblox/open-game-eval
- GameDevBench: https://github.com/waynchi/gamedevbench

## 12. Non-claims

- No StrataFlux or FlashOffloading implementation is installed in STAR.
- No inference speedup is measured on the owner's RTX 4060.
- No autonomous gameplay, game mastery or Roblox Studio autonomy is enabled by this document.
- No Twitch/YouTube OAuth, OBS or VTube Studio connection is enabled by this document.
- No real microphone/live-stream acceptance is claimed.
- No model weights are retrained or self-modified.
- No research benchmark result is a STAR result.
- This work does not establish consciousness or biological human experience.

**Engineering recommendation:** integrate the existing scheduler, durable task/delivery path, room director and avatar playback authority first. Then build the real-time game controller and learning harness on top of those trusted foundations. This is the shortest path to a STAR that can stream, play, learn and build without one workload destabilizing the others.
