# STAR AI — event-time truth, verified game learning, faster local inference and natural VTuber behavior
**Research date:** 2026-10-30. **Status:** engineering proposal + two implemented speech-admission corrections in this draft. No real GPU, game, avatar or OBS measurements were produced.

## Executive diagnosis

STAR's fastest route to a convincing gaming VTuber is **not** another disconnected agent. It is a closed loop with trustworthy timestamps, stable identities, real-time scheduling, independently verified game outcomes, and natural speech control.

The existing repository already contains `StreamDirector`, `StreamFocusInbox`, the paired realtime benchmark, OBS quality witness, cross-skill matrix, active practice planner, gameplay skill bank, and mechanic probe lab. Keep them as the source of truth. Star Core Forge is the intended local-first code/experiments/rollback owner; GitHub is a publication mirror and should not be a required self-improvement dependency.

### Two concrete defects found and corrected

1. **Direct viewer input had weaker identity admission than the deferred-chat inbox.** `StreamFocusInbox.capture()` rejects missing/noncanonical stable platform IDs, while `StreamDirector.offer()` previously accepted them. Because `StreamDirector.propose()` checks its per-viewer cooldown only for a nonempty speaker ID, anonymous events could evade fairness. Now *all direct viewer questions and comments* require a canonical, bounded ASCII speaker ID. Host-side account authentication and normalization are still mandatory: string syntax alone is not proof of identity. Existing gameplay and owner events do not require viewer IDs.
2. **Accepted clock-skew could cause premature narration.** `StreamDirector.offer()` deliberately tolerates source timestamps up to 500 ms ahead of the host clock, but `propose()` previously allowed those same events to be spoken immediately. That can cause Star to announce a game success or react to a danger *before its reported event time*. Admission still tolerates the skew, but `propose()` now refuses an event until its timestamp is reached.

Regression tests cover anonymous/aliased viewer IDs, fair follow-up to a different stable account, continued acceptance of non-viewer events, near-future game success, and future owner-interruption timing. These are offline synthetic tests. They do not verify that upstream identities or gameplay observations are authentic.

## Research map (verified primary sources)

| Primary evidence | What it establishes | STAR integration decision |
| --- | --- | --- |
| [Roblox StudioTestService reference](https://create.roblox.com/docs/reference/engine/classes/StudioTestService/AddPlayers) and [Studio testing API announcement](https://devforum.roblox.com/t/new-studio-testing-apis-and-assistant-improvements/4657854) | Plugins can run scripted server/multiclient tests, add players, simulate disconnects and exercise input; the announcement specifies up to eight simulated clients. | Use the existing Studio automation runner to build an *offline*, scene-scoped, host-asserted test harness for lobby, UI, physics, checkpoint and join/leave behaviors. |
| [GameWorld, April 8, 2026](https://arxiv.org/abs/2604.07429) | 34 browser games and 170 tasks with state-verifiable success; authors identify latency, context memory and fine control as major challenges. | Grade STAR's progress on held-out levels by external win-condition receipts, not model-generated descriptions of winning. |
| [llama.cpp SPEED-Bench](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md) | Measures category-specific throughput, latency and speculative-draft acceptance from a running server, with explicit concurrency settings. | Compare baseline / caching / speculative / parallel-slot configs under pinned models, prompts, token budgets, hardware and temperature. |
| [llama.cpp server developer notes](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README-dev.md) | Active slots share a decoding batch; heavy processing on the single-threaded server context damages multi-request latency. | Keep rendering/OBS, game controls, chat ingestion and long-running post-processing outside the inference thread. |
| [llama.cpp server documentation](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md) | Continuous batching, slot parallelism and KV prompt reuse are available; cached prompts may change exact sampling results. | Test short stable prompt prefixes with checksum-pinned skill bundles. Do not interpret cache reuse as higher model intelligence. |
| [llama.cpp idle-slot cache report, October 2026](https://github.com/ggml-org/llama.cpp/issues/30252) | A reported cache-saving path blocked new requests for seconds under an affected multi-slot configuration. This is an issue report, not a confirmed fault on STAR hardware. | Add p99 queue-delay and slot-save stall checks before enabling cache/slot experiments. |
| [LiveKit turn-handling reference](https://docs.livekit.io/agents/logic/turns/) and [tuning guide](https://docs.livekit.io/agents/logic/turns/tuning/) | VAD/turn detection, interruption detection, dynamic endpointing and preemptive generation are separate controls with latency/false-interruption tradeoffs. | Prototype optional turn-boundary detection and barge-in only after the existing audio, cancellation and OBS timing instrumentation is reliable. |

## System architecture for the next 90 days

```text
TRUSTED HOST (user opt-ins, source auth, permissions)
        |
        v
Event admission --- provenance/time guard --- moderation
        |                             | 
   gameplay telemetry             viewer questions
        |                             |
        v                             v
 Fast perception / controller    focus inbox (bounded)
        |                             |
        +---------- StreamDirector ---+
                         |
                    priority QoS
                         |
                  LLM speech planner <---- verified episodic memories/RAG
                         |
                    streaming TTS
                         |
          device callback -> audio routing -> OBS capture witness
                         |
                 avatar face/eyes/tails rig
                         |
       metrics: observed->plan->utterance->OBS+frame pacing

OFFLINE ONLY (lower priority): StudioTestService / game practice /
general-knowledge challenge set / Core Forge isolated experiments
```

**Do not put a language model on the per-frame gameplay-control path.** Controllers and bounded action primitives should run fast and deterministically, while tactical analysis uses sparse key frames and exceptional events. Long-horizon strategy and knowledge indexing get admission only when actual FPS/audio/VRAM headroom permits.

## Priority A — make speed increases demonstrable

1. Establish a fixed capture protocol: warmup, 20+ *pre-registered* A/B pairs for each of four workloads (gaming commentary, general knowledge, Roblox creation, live dialogue), alternating trial order and keeping game/version/scene fixed.
2. Pin backend commit, GPU driver, GGUF hash, quantization, CUDA/Vulkan build, CPU threads, llama-server `--np`, context, prompt-cache flags, speculation type/draft and model temperature. Otherwise data are not comparable.
3. Keep an RTX 4060 8 GB VRAM reserve for game render + encoder + avatar and for fragmentation; **6656 MiB is an existing experiment guardrail, not proof that this allocation fits every game**. If inference consumes the render budget, move background tasks to Brain 1 / CPU or use a smaller model.
4. Distinguish median token throughput from real perceived speed: capture request enqueue, first token, first valid complete phrase, TTS first chunk, physical audio callback, independently audible OBS onset, and subtitle/avatar timestamp. Monitor p50/p95/p99 and dropout, not just an average.
5. Measure cost of speculative decoding. A draft model can lose on high-entropy/coding workloads and may consume enough RAM/VRAM to harm gameplay. Implement candidates as reversible, opt-in *configurations*, not universal acceleration rules.
6. The existing `stream_workload_quality_matrix.py` and paired quality witness remain prerequisites: no new wrong matched cases, zero unsupported achievements, OBS audible, A/V measured, FPS and VRAM guardrails respected. Only a reviewed **rehearsal suggestion** may pass, never an automatic live model change.
7. Track the queue-occupancy distribution and cache save pauses. A multi-slot server with excellent throughput but 1-second chat spikes is not acceptable for a lively streamer.

**Possible experiments, ordered by value:** (i) shorter stable system prefixes; (ii) fixed-size category-specific knowledge packs; (iii) cheaper local turn detection; (iv) smaller fast-path model for reaction planning with validated fallback; (v) draft decoding; (vi) slot-count tuning. Reject any setting if answer correctness, FPS, p99 tail latency or audio delivery declines.

## Priority B — learning to play unfamiliar games for real

**Hierarchy**: 20-60 Hz input/safety controller (game dependent, not an inference target), 1-5 Hz tactical perception, event-triggered LLM plans and slower retrospective learning. These are *experimental bands*, not measured STAR rates. Controlled private/supported games only; do not automate prohibited competitive services.

1. **Observe** bounded frames, audio and structured game telemetry with timestamps and source IDs. Preserve unknowns. Do not turn viewer claims into verified victories.
2. **Hypothesize** mechanics (jump arc, timing windows, collision patterns, interaction range, enemy tells, cooldowns). Use `GameMechanicProbeLab` and externally signed `GameplaySkillBank` receipts.
3. **Probe** one variable at a time, randomize when feasible, vary seeds and conditions, and respect action-practice budgets. Never label practice evidence causal or mastery.
4. **Act** via deterministic primitives with stop/recovery paths: look, move, jump, interact, retry. A safety watchdog releases held inputs when observation goes stale, the host loses focus, or a pause/stop arrives.
5. **Verify** checkpoint, survival, score and actual match outcome from independently observed game state, then compare prediction with reality.
6. **Transfer** to held-out maps with unfamiliar textures/geometry and no access to hidden answers. Track success rate, attempts, time, collisions, game FPS, invalid actions and nonresponsive frames.
7. **Learn** only durable, provenance-linked strategies after a successful held-out check. Failed or inconclusive trials stay as failures/inconclusive; retain why they did not work without hallucinating achievements.

**Curriculum**: camera and movement -> platform jumps -> dynamic hazards -> inventory and UI -> NPC interactions -> multi-object objectives -> navigation with delayed feedback -> adversarial or multiplayer timing. Maintain separate practice/evaluation seeds and disallow contamination across both.

## Priority C — becoming a game creator, not just a Luau code emitter

Adopt a scene contract for every generated Roblox map: anchors, walkable graph, prop geometry bounds, collision groups, object ownership, lighting and performance ceilings. Require:
- Reproducible Studio edit plan, original asset-license record and before/after visual diff.
- Luau static checks plus executable tests; clean compile does **not** imply correct gameplay.
- Geometry audits for orphaned walls, intersections, z-fighting, missing supports, alignment tolerances, clipping avatars and inaccessible routes.
- Camera/perception audits of UI on small/large screens and high DPI; device profiles and simulated input from Studio's testing APIs.
- Playtest outcomes: checkpoints reached, items interacted with, multiplayer join/leave respected, asset load failures and performance ceilings.
- Creative scorecard assessed across held-out scenes with human review; measure coherence, animation timing and gameplay fun separately from script correctness.

For **new game ideas**, avoid cloning source projects. Generate distinct mechanic variants, prototype each minimally, compare playtest engagement, then promote only original high-scoring designs into Star's internal skills library.

## Priority D — Star as a convincing, candid AI streamer

Naturalness should be a **behavioral integration outcome**, not a claim that Star is human.

- **Attention:** focus in intense gameplay; only danger/owner interrupts are eligible. Revisit moderated chat questions after focus returns, with honest elapsed-time context. Avoid responding to every chat line.
- **Turn timing:** use STT+VAD+turn model where beneficial; support false-interruption recovery, bounded barge-in and deliberately unhurried timing. Never assume the latest TTS queue enqueue means viewers heard speech.
- **Expression:** drive gaze, blinking, eyebrows, mouth visemes, breath/body sway, twin-tail spring motion, blush, delight, surprise and disappointment from the same timed *observed events* that drive speech. Avoid random reactions detached from gameplay.
- **Voice:** use a consistent original performance voice, natural prosody and laughter; do not impersonate a real person. Test on original, consented audio; evaluate human-perceived clarity and laughter realism blindly.
- **Narrative memory:** Star may say 'I fell off that platform earlier' *only after a verified recorded episode*. Her persona history is disclosed fictional lore where applicable; do not manufacture offline friendships, personal suffering or personal human experiences.
- **Social continuity:** build opt-in preference/relationship memory with expiry, consent and protected viewer privacy. Keep raw chat and speaker identities outside the language-model memory path by default.
- **Recovery:** if audio fails, subtitle sync drifts, gameplay input is uncertain or GPU pressure is high, reduce verbosity, pause expensive reasoning or fall back to silent play rather than making unsupported claims.
- **Avoid repetitive 'AI presenter' behavior:** track repeated phrase templates and spontaneous-comment density. Review actual OBS recordings for conversational fluency, awkward pauses and overreaction frequency.

Acceptance requires independent OBS measurement of audio onset and A/V drift, real viewers' evaluation of conversational quality (with consent), safe interruption handling, and actual in-game performance. None of these are supplied by synthetic tests.

## Priority E — independent general intelligence and local-first Core Forge

**Knowledge system:** maintain separate layers for curated base documentation, timely retrieved sources, verified personal episodes and temporary working hypotheses. Every statement used for gameplay or teaching should carry provenance, timestamp, confidence and expiry; ask for research when stale. Do not blend invented examples into factual memories.

**Core Forge loop (GitHub optional):**
1. Star proposes a measurable hypothesis, e.g., 'turn detector reduces p95 response by 150 ms with no higher false-barge-in rate.'
2. Instantiate a resource-limited isolated branch/worktree, pin exact dependencies and datasets.
3. Run bounded candidate comparisons (Best-of-N where affordable); static checks -> unit tests -> simulation -> integration rehearsal -> human review if public/external-facing.
4. Produce signed local artifacts: checksums, failing cases, host measurements and semantic diff. Keep secrets/recordings off GitHub.
5. Promote only evidence-backed improvements in a reversible configuration, using progressive rollout and automatic rollback on regression.
6. Invent harder private tasks across code, Roblox physics, animation, visual understanding, research, reasoning and social timing. Hold out private validation items. Failure should generate new hypotheses, not self-awarded skill points.

**Architecture boundaries:** Brain 2 owns game+OBS+avatar latency; Brain 1 handles bulk retrieval/training/candidate evaluation when available. Default OFF for capture, web access, public posting and any external actions not previously authorized. All destructive, spending and externally consequential actions retain appropriate approval and budget gates. An LLM's self-description is not evidence of consciousness; durable self-modeling and reflective behavior are functional engineering goals.

## Acceptance matrix for the next hardware rehearsal

| Goal | External/host witness | Fail condition |
| --- | --- | --- |
| Game mastery | Checkpoint, score or win-state receipt on held-out levels | Agent narrative claims success but game doesn't |
| Building integrity | StudioTestService, scene-tree/geometry validator, visual review | Detached objects, z-fighting, inaccessible routes, broken UI |
| Local speed | Complete A/B quality matrix with FPS, TTFA and VRAM | Any new matched error or lower perceptual QoS |
| Speech delivery | OBS-recorded PCM onset and A/V alignment | TTS generated but inaudible, stale/early narration |
| Social fairness | Stable authenticated viewer ID and queue/focus limits | Anonymous/aliased IDs bypass per-viewer rate limits |
| Humanlike communication | Blinded review of recorded, AI-disclosed stream segments | Repetitive monologues, fabricated life memories, wrong emotional events |
| Forge self-improvement | Isolated reproducible benchmarks and rollback receipts | Failures disguised as wins, code changes escaping sandbox |

## Scope and limitations

This PR modifies only `star/stream_director.py` and adds offline regression coverage plus this research note. It does not train weights, install software, change model routing, send chat, modify gameplay, turn on OBS, authorize a stream, or prove a speed/skill improvement. The host must independently attest the source's time, stable account ID, moderation and playback. Source-based suggestions here require real Windows rehearsal and independent validation before promotion.

**Repository privacy warning:** `oncoursemail/Star-AI-Private` is currently **public** despite its name; never commit model keys, recordings, personal memories or unreviewed chat datasets to it.
