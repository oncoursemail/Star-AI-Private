# STAR research: verified action feedback, faster real-time intelligence, and natural VTuber play

**Researched:** November 3, 2026 (US Central)
**Scope:** Star AI / Star Intelligence, owner-controlled game environments, Roblox Studio, offline simulation and private streaming rehearsals.
**Status:** Working host-only feedback code and offline tests in this branch; all other recommendations are experiments, not demonstrated capabilities.

## 1. What was missing after the input-latency calibration

The existing owner-only pipeline can (a) read a scoped, independently signed engine frame; (b) keep that feed fresh; (c) admit reactive inference before a deadline; (d) claim a one-time input ticket; and (e) demand independently confirmed key-up. The November 3 input-acknowledgement work measures whether the operating system accepted the input.

**None of those observations says the game actually changed.** An OS input receipt does not verify an in-game checkpoint, enemy defeat, win, or even that the game accepted the action. Teaching Star that every successful key release was a successful maneuver would corrupt her skill memory.

The new `GameActionOutcomeFeedback` closes a narrow part of this loop. Once input has been independently released, it opens a bounded evidence window, then observes only subsequent **signed, witness-corroborated game-state transitions** from the existing private host. Progress, loss, and unverified timeout are distinct. Its output **never authorizes skill credit, game victory claims or broadcasting**. A timeout is unknown, *not* a failed skill. Missing input, lost telemetry, reversed clocks, duplicate receipts, altered MACs, changed sessions and scope mismatches prevent evidence from being accepted.

The integration is optional and OFF by default. The host still must independently own the game, the source key, the Windows input port and emergency stop. The observer cannot tell whether an apparently positive game event was **caused** by Star's particular action; other systems and players may have produced it. It deliberately misses events that occur during a key hold and before independently verified key release. Future causal learning needs paired trials and controlled environments.

### New host-only data flow

1. Trusted engine/server test host → signed frame → pinned authenticated bridge → two-sample state transition witness.
2. OBS/game authorized input adapter → single-use action permit → host-confirmed key-up.
3. Host starts a post-release feedback window linked to that permit ticket, the same approved game and signing session.
4. Independently witnessed checkpoint/win/loss from *later* authenticated frames may resolve an **observation**, not a causal reward.
5. Expiration produces **unverified_timeout**; source failure revokes the outcome window. No untrusted model or viewer can insert an event.

This is a basis for a **closed-loop measurement harness**, not a production game-winning agent.

## 2. Research: real-time intelligence is a whole-system deadline problem

GameScaling's November 1, 2026 correction is particularly instructive. Its revised ViZDoom evaluation includes overhead omitted by its earlier time compensation: screenshot capture, image transfer, preprocessing, action processing and video recording. Published real-time scores were revised to 11.5 (GameScaling-9B-S3) and 8.5 (27B-S3). A frontier model may reason very well when the game pauses, but lose to a weaker model that acts in time when the world keeps moving.

**STAR measurement formula:**

`total_control_latency = frame_capture + transfer + image_preprocess + prompt_prefill + decoding + action_policy_check + OS_dispatch + actual_game_observation_delay`

Measure p50, p95, p99, deadline miss rate, frame age and dropped frames for each stage; tag OBS-live/idle and system CPU/GPU load. Capture-to-action is not enough until a later trusted engine observation closes the measurement. Verify actual game response with an owned sandbox, not with key acknowledgement alone.

**Architecture recommendation:** Three cooperative schedulers, not three competing GPU-hungry models:

- **Reactive lane** (game deadline): minimal approved action vocabulary, small perception or state adapter, cached policy, short context, no tool search. If p95 budget cannot meet the specific deadline, skip or use a prevalidated deterministic fallback. Never silently claim a completed action.
- **Tactical lane** (slower cadence): map and mechanic summaries, short horizon plans, strategy confidence and error recovery. It may propose a new action policy, but only a separate host-approved gate may activate it.
- **Study lane** (pause/offline): larger model(s), retrieved documentation, opponent simulations, self-play challenges, code generation, candidate ranking, verifier and skill-bank updates. Preemption should not interrupt game/OBS.

Use resource-aware admission: if VRAM headroom, game FPS, OBS dropped frames, speech queue or TTS onset are out of budget, stop speculative inference and offline teacher workers first. A quiet, accurate Star is better than 50 tokens/s that freezes the game.

**On an 8 GB GPU:** benchmark quantization, batch sizes, long context and cached-prefix prompt layouts rather than claiming any one model is the fastest. Time-to-first-meaningful-action matters more than tokens/s; measure full context swaps and GPU memory contention, including OBS encoding. Model-bound performance claims from another GPU do not transfer automatically.

## 3. How Star should *actually* learn to play games better

### Observation is not causation

A signed checkpoint after a key press does not prove the press helped. In test worlds, compare against randomized no-action, random-action, current-policy and candidate-policy baselines using matched seeds and equivalent wall-clock budgets. Keep validation seeds and levels **held out**; reject repeated observation IDs and duplicate signed trials. Separate practice from official score.

### Skill curriculum

Each skill has: game version, context, allowed actions, intended target, explicit pass/fail criteria, independent observer, held-out trials, and revocation conditions. Progress from basic locomotion to timed hazards, inventory management, cooperation and unplanned recovery. Use adversarial perturbations: lower FPS, network lag, camera occlusion, changed UI layout and opponent behavior.

A new 'observed_progress_after_action' can suggest a **hypothesis** to test, never grant a mastered skill. Require repeated independently checked results over fresh sessions; regress learned competence after recent verified failure. Escalate harder challenges only when holdout scores remain positive after actual real-time latency is charged.

### General knowledge and tool proficiency

Maintain source-provenance-aware retrieval for Roblox Luau APIs, Blender geometry, programming, art techniques, game manuals and public documentation. Associate each memory with source, version, confidence, expiration, and observed tests. Use a tool selector (local index, relevant docs, simulation) rather than web browsing during a split-second game action. Distinguish personal experience from quoted facts and from model-generated hypotheses. Give Star a durable self-model of current capabilities/limits and explicit uncertainty, not unsupported claims of human consciousness.

## 4. More convincing and enjoyable VTuber behavior

Microsoft Research's **Proact-VL** (ICML 2026; May 2026) addresses the crucial question **when** a gaming companion should speak. Its Live Gaming Benchmark covers solo commentary, co-commentary, and user guidance. For Star, trigger speech from meaningful verified gameplay events, genuine user turns and selected story beats, not constant periodic chatter.

**Proposed speech director:** audio activity/VAD + verified scene urgency + speaker focus + recent discourse + pending speech backlog → `speak / wait / short acknowledgment / interrupt / silence`. Dialogue should contain natural timing, personal but consistent preferences, real recollections, laughter where appropriate, varying energy by scene and respectful turn-taking. Never fabricate a death, win or object pickup from an uncertain screenshot.

LiveKit's 2026 adaptive interruption handling distinguishes intentional interruptions from short acknowledgments; its false-interruption recovery is a model worth benchmarking. The existing Star voice liveness/clockless stop and pre-play gates should be wired into the actual Windows audio host, with physical mute/stop measured separately.

For low GPU pressure, **Kyutai Pocket TTS v4.0.0 (Oct 20, 2026)** released 18m/7m/2m English variants; **v4.0.1 (Oct 21)** corrected an issue in the sub-20m models. Conduct AB/X listening tests and on-device TTFA/onset/jitter benchmarks before switching. Tiny voice models trade fidelity against speed. Star's avatar should follow actually audible phonemes (visemes), be expressive but not uncanny, observe a reduced-motion toggle and avoid reacting to unverified game state. Represent her honestly as an AI VTuber, not a human impersonator.

**Suggested evaluation set:** 100 annotated conversational episodes (interruption, backchannel, silence, high-stress gameplay, conflicting viewer instructions, simultaneous audio), blind human ratings for naturalness and relevance, missed owner interruption rate, p95 audible onset, hallucinated game-claim count, CPU/GPU peak and OBS drop rate. Keep private streams/recordings local and consented.

## 5. Roblox and general game-creation capability

Roblox's April 15, 2026 announcement describes deeper built-in Studio MCP workflows for planning, building and testing. `StudioTestService` supports scripted multiplayer client tests for lobby, disconnect, matchmaking and join/leave flows; it should be run in an isolated Studio Lab, not on live player sessions.

**OpenGameEval**, released in October 2026, evaluated 84 curated Roblox tasks and found that looking at objects relevant to the reference solution before editing is associated with higher pass rates. This is evidence for an inspect-first tool policy, not for unbounded autonomy. **GameDevBench** (ICML 2026) reports large gaps on graphics-focused work and gains from image/video feedback.

Implement a forge that creates 4–8 candidate changes in isolated game clones, runs Luau static analysis, executes Studio tests, inspects video/frame differences and server logs, then promotes only artifacts independently passing checks. Prevent model-generated checkers from being the sole arbiter. Cache approved skill snippets, avoid exporting private user assets, and preserve a rollback path. Collect code correctness, FPS, multiplayer consistency, visual quality and real-user acceptance separately.

## 6. Prioritized implementation and falsifiable gates

**Now, implemented here:** optional single-action signed post-release progress observer and integration with the telemetry/actuation interlock, isolated test environment, no physical device access. When enabled, unresolved evidence prevents overlapping new action attempts; source revocation erases pending credit.

**Next, test on Windows privately (no broadcasting):** trusted engine host → signed telemetry over isolated IPC → action interlock → actual key-up probe → post-action window, while OBS records *locally* and no external service is contacted. Inject frame stalls, clock jumps, repeated MACs, rapid input cancellation, fullscreen switching and speaking interruptions. Record exact Windows build, GPU, CPU and drivers.

**Next, measure real-time performance:** 50+ paired episodes for each mode (OBS off, OBS local recording, streamer speech), at least 500 bounded timing samples per condition, same seeds and model versions. Promotion gate: no regressions in safety or verified success; demonstrate p95/p99 actual game response improvements **and** stable game FPS/OBS quality. Report uncertainty intervals; do not claim superiority from one run.

**Later, demonstrate learning:** demonstrate held-out win rate/progress per minute vs no-training control on >=3 varied authorized game environments. Verify personality quality using independent user ratings rather than anthropomorphic assertions.

### Source links and dates

- GameScaling: realtime-game benchmark and **Nov 1, 2026 ViZDoom correction** — https://gamescaling.github.io/
- Microsoft Research **Proact-VL**, ICML 2026, **May 2026** — https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/
- LiveKit adaptive interruption and false interruption handling — https://docs.livekit.io/reference/agents/turn-handling-options/
- Kyutai Pocket TTS **Oct 20–21, 2026** release notes — https://github.com/kyutai-labs/pocket-tts/releases
- Roblox **Apr 15, 2026**, Studio goes agentic — https://about.roblox.com/newsroom/2026/04/roblox-studio-going-agentic
- Roblox StudioTestService API — https://create.roblox.com/docs/reference/engine/classes/StudioTestService
- Roblox OpenGameEval **Oct 2026** — https://arxiv.org/abs/2610.02563
- GameDevBench, **ICML 2026** — https://sethkarten.ai/papers/gamedevbench.html
- GameWorld, **Apr 2026** (outcome-verifiable multi-game agent evaluation) — https://arxiv.org/abs/2604.07429

**Known limits:** Offline signed-event tests cannot prove the Windows native input port is safe, a real game acted on a control, a model grew more intelligent, real inference speed increased, humanlike emotion emerged, or public streaming is ready. All require separate verified experiments.
