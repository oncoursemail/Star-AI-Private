# STAR Research: Private Stream Rehearsal Gates, Voice Naturalness & Game Transfer

**Research date:** 2026-11-11  
**Implementation:** bounded, offline rehearsal evaluator  
**Status:** evaluation primitive only; host instrumentation and private-device acceptance remain separate

## Executive summary

The repository already contains several useful foundations that should be integrated rather than replaced:

- star/stream_director.py: opt-in, consent-gated speech arbitration with deliberate quiet time and stale-event/replay protections.
- star/stream_budget.py and star/stream_qos.py: conservative workload advice and measured inference admission.
- star/stream_hardware_telemetry.py: trusted off-hot-path CPU, memory, VRAM, frame and speaker-backlog observations.
- star/llama_metrics.py and the streaming inference probe: local inference and first-content measurements.
- star/agent_trace.py, adapters and the trace profiler in the preceding development chain: causal correlation and stage timing.
- Existing game-skill, Roblox Studio, general-knowledge and task-continuity work.

The missing piece is a repeatable acceptance report that answers whether a complete private VTuber rehearsal is actually good enough. This change adds that evaluation layer. It does not add another scheduler, voice controller, game controller or memory store.

## 1. New implementation

### Files

- star/stream_rehearsal_eval.py
- tests/test_stream_rehearsal_eval.py

### What the evaluator scores

The caller supplies a strict schema containing aggregate numeric samples and event counts only.

Latency and timing:
- First model content p95.
- First audible output p95.
- Game frame-time p99.
- Absolute avatar/audio synchronization error p95.

Realtime stability:
- Fraction of playback chunks affected by an audio underrun.
- OBS render-thread skipped-frame rate.
- OBS output-thread skipped-frame rate.

Conversational quality:
- Turn precision and recall from trusted labels.
- False interruption behavior is represented in false-positive counts.
- Missed genuine turns are represented in false-negative counts.

Continuity and learning:
- Task recovery success rate.
- Stale task-resume count.
- Duplicate speech replay count.
- Held-out game-skill transfer rate.

### Gate semantics

Each threshold is supplied by the operator. None disables that gate. The evaluator deliberately has no universal latency or FPS defaults because acceptable values depend on the target game, frame cap, encoder, audio device, model and machine.

Every configured gate returns one of:

- PASS: sufficient evidence meets the configured threshold.
- FAIL: sufficient evidence violates the threshold.
- INCONCLUSIVE: evidence is missing, has a zero denominator, or does not meet the minimum observation count.

A missing metric is never treated as zero. A run with any measured failure is FAIL; otherwise, any inconclusive configured gate makes the run INCONCLUSIVE.

Percentiles use the nearest-rank method. The report contains aggregate metrics only; it does not retain raw samples or arbitrary metadata.

### Why separate first-content from first-audible latency

The existing streaming inference probe measures the first non-whitespace API content chunk. That is not when a viewer hears Star. First-audible latency must be measured at the local playback/device boundary, and ideally checked against a loopback capture during a private test.

Likewise, an API chunk gap is not token-level inter-token latency unless the server reports token boundaries. Do not relabel chunk cadence as token timing.

## 2. Inference speed research

### llama.cpp SPEED-Bench

The upstream SPEED-Bench client targets an already-running llama-server. It reports per-category prompt throughput, decode throughput, end-to-end request latency and speculative-draft acceptance. Its documentation recommends matching client concurrency to the server slot count (--np) for throughput runs. Baseline and speculative runs should use the same benchmark, category, output length and sample selection.

Sources:
- https://github.com/ggml-org/llama.cpp/tree/master/tools/server/bench/speed-bench
- https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md

**STAR application**

1. Pin the llama.cpp build, model file SHA-256, quantization, context length, GPU layers, Flash Attention, CPU threads, slot count and draft configuration.
2. Warm up the same model before each candidate.
3. Randomize paired baseline/candidate order.
4. Keep prompt samples and output caps identical.
5. Report successful, failed and incomplete requests separately.
6. Compare prefill, decode, first-content and end-to-end latency separately.
7. Re-run under game-only, OBS-only, game+voice, and full game+voice+avatar+OBS workloads.
8. Reject a speculative configuration if draft work or memory contention makes the actual target workload slower.

A high draft acceptance rate is not itself proof of a speedup. The upstream benchmark's paired comparison calculates decode and latency speedups from matching baseline/speculative runs; STAR should preserve that discipline.

### Resource scheduling

The existing stream_qos.py and stream_budget.py already provide advisory admission logic. Keep the policy hierarchy:

1. Audio continuity and owner interruption.
2. Gameplay responsiveness.
3. Interactive speech and short reasoning.
4. Vision/commentary at a bounded cadence.
5. Background research, training and heavy rendering only when measured headroom permits.

Never run trace analysis, disk I/O, model inference or blocking hardware probes inside an audio callback or render thread. Hardware polling belongs on a worker; hot paths consume immutable recent snapshots.

## 3. Voice naturalness and interruption handling

### LiveKit turn handling

Current LiveKit Agents documentation exposes explicit turn detection, endpointing, interruption and preemptive-generation settings. Interruption can use adaptive context-aware detection or simpler VAD. The documentation also describes a false-interruption timeout and resume_false_interruption, which can resume speech after a cough/noise event when no user transcript arrives.

The documentation notes that adaptive mode is conditional: it is available in supported LiveKit Cloud/dev configurations, while other self-hosted cases may fall back to VAD. Do not assume a feature is active just because the configuration object accepts a field.

Sources:
- https://docs.livekit.io/reference/agents/turn-handling-options/
- https://docs.livekit.io/agents/logic/turns/tuning/
- https://livekit.com/blog/adaptive-interruption-handling

**STAR application**

Evaluate separately:
- End-of-turn recall.
- False end-of-turn rate.
- Genuine interruption recall.
- False interruption rate.
- Interruption-to-audio-stop latency.
- False-interruption recovery latency.
- Duplicate speech after resume.
- Correct task continuation after the interruption.

Use labeled consented scenarios. Include short backchannels, laughter, coughs, keyboard/game sounds, overlapping viewers, direct questions and explicit owner stop signals. Do not optimize latency by making every sound interrupt Star.

### Multiparty stream behavior

A livestream is not a one-user/one-assistant call. Star must distinguish direct address, viewer-to-viewer replies, side conversations, overlapping speech, a human already answering, and a conversation that does not need her participation.

Use session-local speaker labels only where the platform provides them. Do not infer real-world identity from voice or create persistent voiceprints by default. Aggregate telemetry should store counts, not transcripts or viewer identities.

A good streamer sometimes listens, reacts nonverbally or remains quiet. Constant speech is not a naturalness metric.

### Synthetic social rehearsal: Concordia

Google DeepMind's Concordia is a component-based framework for generative agent-based simulations. It combines language-model reasoning, associative memory and a Game Master that applies actions to a simulated environment.

Source:
- https://deepmind.google/research/publications/64717/

**STAR application:** use a local synthetic rehearsal room to generate controlled group-chat situations before a public stream: multiple viewer personas, side conversations, jokes, backchannels, direct questions, corrections, interruptions and topic changes. The evaluator should score whether Star speaks, yields or stays silent at the right time. Synthetic conversations are useful for coverage and regression, but they are not a substitute for consented human evaluation or real stream testing. Do not use private viewer conversations as training material without explicit permission.

## 4. Avatar embodiment and synchronization

### VTube Studio

The official VTube Studio project documents a public WebSocket API for plugins. It supports authenticated plugin access, hotkey triggering, parameter injection and event subscriptions. Some operations require additional user-granted permissions. Keep the connection local, require explicit user authorization, protect the API token, and never commit tokens or enable risky permissions automatically.

Sources:
- https://github.com/DenchiSoft/VTubeStudio
- https://github.com/DenchiSoft/VTubeStudio/wiki/VTS-Model-Settings

### Live2D Cubism

Live2D's current SDK manual describes mapping lip-sync parameters from the model settings and feeding them values from audio input or motion. One documented method obtains playback audio level and applies it to the model's lip-sync parameters. The manual also describes separating mouth motion from the main body motion manager.

Source:
- https://docs.live2d.com/en/cubism-sdk-manual/lipsync/

**STAR application**

- Start mouth animation from the actual playback clock, not when text is generated.
- Clear queued mouth/viseme updates when audio is cancelled.
- Keep mouth motion, facial expression, gaze and body motion as separate layers.
- Drive expressions from explicit conversation/game state, not from model confidence.
- Measure absolute audio-to-avatar onset/offset error during rehearsal.
- Keep idle breathing/blinking on a lightweight animation clock.

VTube Studio hotkeys and expressions are useful for authored reactions (laugh, surprised, annoyed, thinking, excited), while continuous parameter injection is appropriate for playback-driven mouth movement. Do not flood the API with repeated hotkeys; the documented hotkey queue has a finite capacity and frame-based execution cadence.

## 5. OBS measurement: do not collapse different failure modes

The official obs-websocket GetStats response distinguishes:
- activeFps;
- averageFrameRenderTime;
- renderSkippedFrames and renderTotalFrames;
- outputSkippedFrames and outputTotalFrames.

Sources:
- https://github.com/obsproject/obs-websocket
- https://github.com/obsproject/obs-websocket/blob/master/src/requesthandler/RequestHandler_General.cpp
- https://github.com/obsproject/obs-websocket/blob/master/docs/generated/protocol.json

**STAR application**

Keep render-thread skips separate from output-thread skips. Correlate each with game frame-time p95/p99, GPU/VRAM, CPU and voice backlog. A single “stream health” percentage hides whether the bottleneck is composition, encoding/output or the game itself.

Use OBS authentication and keep the WebSocket listener local unless a protected remote-control design is explicitly configured. Read-only stats collection should be separate from scene changes, stream start/stop and other control operations.

## 6. Game mastery and Roblox creation

### OpenGameEval

OpenGameEval evaluates agents inside reproducible, stateful Roblox Studio sessions. It separates observation actions from editing actions and scores both the resulting scene and simulated gameplay with executable checks. The October 2026 paper reports 84 curated tasks across 13 models and 16 attempts per task. It also reports that inspecting objects touched by a reference solution correlated with higher pass rates in the evaluated benchmark.

Sources:
- https://arxiv.org/abs/2610.02563
- https://github.com/Roblox/open-game-eval
- https://about.roblox.com/newsroom/2025/12/opengameeval-benchmark-agentic-ai-assistants-roblox-studio

**STAR Creator application**

1. Inspect the DataModel, scripts, dependencies and relevant properties.
2. Record the project revision and exact Studio instance.
3. Make a minimal plan with executable acceptance criteria.
4. Edit only an isolated test place.
5. Run Luau static checks.
6. Playtest with a simulated player.
7. Verify scene state, logs, physics and network behavior.
8. Repeat the task and test held-out scenes.
9. Promote a skill only after independent validation.

Observation and mutation tools should remain distinct. Live publishing, player data, economy changes, moderation and other external effects remain separately authorized.

### Generalist 3D agents: SIMA 2

Google DeepMind's SIMA 2 combines a vision-based game interface with a language/reasoning model and keyboard/mouse actions. Its research preview describes goal reasoning, interaction in multiple commercial games, language-conditioned behavior, and self-directed improvement from experience. The paper/blog also calls out remaining limits: long-horizon planning, short interaction memory, precise low-level control and robust visual understanding.

Source:
- https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/

**STAR application:** borrow the architecture, not the unavailable research model. Keep a slow strategic planner, a fast observation/action loop, a versioned skill bank and held-out transfer tests. Store compact verified state summaries instead of replaying entire screen histories. Use task success and independent environment state—not an agent's narration—as the reward signal.

### Interactive world models: Genie 4

Google DeepMind announced Genie 4 on October 27, 2026 as a real-time interactive world-simulation model with multimodal scene, sound and dialogue generation.

Source:
- https://deepmind.google/blog/genie-4-a-new-generation-of-world-simulation/

**STAR application:** treat world models as a future optional training/evaluation source. If access becomes available, generate diverse private practice environments, test whether a skill transfers across visual/physics variations, and compare predicted versus observed transitions. Genie 4 is not a local dependency or a substitute for real Roblox/game playtests; access and reproducibility must be verified before integration.

### Game-skill transfer

A skill is not mastered because Star can describe it or repeat one successful button sequence. Record the game version, control mapping, preconditions, state features, allowed actions, predicted state transition, failure conditions and independent success evidence. Test on unseen maps, seeds and situations. Retire or revalidate skills after patches that change controls, physics or mechanics.

Use a fast reactive controller for immediate movement and a slower strategic planner for objectives. Strategic proposals must expire quickly and be checked against a fresh frame before action. The model must not hold keys indefinitely; use bounded action durations and a host-side key-up watchdog.

## 7. General knowledge and research

Keep the existing general-knowledge benchmark honest about its scope. A small development suite is an artifact-integrity check, not proof of broad intelligence.

The existing Knowledge Lab direction should use distinct evaluation layers:
- SimpleQA for short stable facts.
- TruthfulQA for common misconceptions and false premises.
- FreshQA for dated, changing facts.
- BrowseComp for difficult multi-source research.
- GAIA for tool-using assistant workflows.
- GPQA for expert science reasoning.

Sources:
- https://openai.com/index/introducing-simpleqa/
- https://github.com/freshllms/freshqa
- https://openai.com/index/browsecomp/
- https://huggingface.co/gaia-benchmark
- https://arxiv.org/abs/2311.12022

Do not combine these into one undifferentiated score. Track domain accuracy, citation support, freshness, abstention, false-premise correction and held-out performance separately. Keep benchmark answer keys outside the model/tool sandbox.

## 8. Private rehearsal protocol

Run a private rehearsal with a pinned game build, model, quantization, audio device, avatar, OBS scene and frame cap.

Include:
- Quiet gameplay.
- Busy combat.
- Multiple viewers talking to each other.
- A direct question to Star.
- A backchannel while Star speaks.
- A genuine interruption.
- A false interruption/noise event.
- A viewer answering another viewer.
- A long background research task interrupted by chat.
- A Roblox build/playtest task.
- A game-mechanic practice task on a held-out level.

Record aggregate observations only. Keep consented raw recordings, if needed for human review, outside the Git repository and under a separate retention policy.

### Acceptance dimensions

| Dimension | Evidence |
|---|---|
| Inference | First-content p50/p95, prefill/decode throughput, failures |
| Audible response | First-audible p50/p95 |
| Turn-taking | Labeled precision/recall, false interruptions, missed turns |
| Recovery | Task recovery rate, stale resumes, duplicate speech |
| Avatar | Playback-to-mouth synchronization error |
| Gameplay | Frame-time p95/p99 and held-out skill transfer |
| OBS | Render and output skipped-frame rates separately |
| Audio | Fraction of playback chunks affected by underruns and speaker backlog |
| Knowledge | Accuracy, source freshness, citation support and abstention |

Use randomized paired baseline/candidate runs. Pin all relevant versions and configuration. A candidate must improve its intended metric without regressing speech continuity, game frame times, avatar synchronization or answer quality.

## 9. Phased implementation roadmap

### Phase A — evaluation primitive (this PR)
- Validate a strict, bounded aggregate snapshot.
- Calculate nearest-rank timing percentiles and event rates.
- Apply operator-supplied thresholds.
- Report PASS, FAIL or INCONCLUSIVE.
- Add deterministic offline tests.

### Phase B — host adapters
- Connect local playback acknowledgements.
- Connect trusted game frame-present samples.
- Connect OBS GetStats read-only samples.
- Connect VTube Studio playback-epoch/parameter timing.
- Keep all collection off audio/render hot paths.

### Phase C — social and recovery evaluation
- Add labeled multiparty scenarios.
- Add false-interruption and backchannel tests.
- Connect interruption recovery to the existing task checkpoint coordinator.
- Verify that no completed speech or side effect is replayed.

### Phase D — game and creator evaluation
- Run isolated Roblox Studio scenarios.
- Add held-out game-mechanic transfer trials.
- Validate builds through both scene checks and simulated playtests.

### Phase E — measured optimization
- Use the trace profiler to locate bottlenecks.
- Run paired llama.cpp SPEED-Bench configurations.
- Adjust QoS only after mixed-workload evidence.
- Roll back any candidate that harms voice/game/OBS stability.

## 10. Safety and validation boundary

This PR adds a pure evaluator and offline tests only. It does not:
- connect to OBS or VTube Studio;
- capture microphone, camera, chat, audio, video or screenshots;
- change model selection, quantization, prompts or memory;
- schedule or start model jobs;
- control a game or avatar;
- start/stop a broadcast;
- change permissions or secrets;
- claim human-equivalent behavior or autonomous mastery.

The report is an acceptance aid, not a security authorization or production-readiness certificate. GitHub Actions must pass on the exact PR head, then a private Windows/RTX 4060 rehearsal must supply real measurements before any performance or naturalness improvement is claimed.
