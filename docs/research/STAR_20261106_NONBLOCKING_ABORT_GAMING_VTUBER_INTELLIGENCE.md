# Star AI — emergency gaming abort, measured intelligence and natural VTuber systems
**Research and implementation note — 2026-11-06**
**Scope:** local-first, owner-authorized private test hosts. No game input, OBS broadcast, model training, GPU benchmarking or microphone recording was performed for this change.

## Newly identified safety/reliability defect: cancellation could wait behind input I/O

The optional `HostMonotonicGameProbe.guarded_dispatch()` runs an approved host callback while holding a Python reentrant lock. Before this change, `abort()` attempted to acquire that same lock. If a native input callback blocked, an independent safety/shutdown thread could call `abort()` but remain **blocked until input I/O returned**. This failure mode matters for real-time gaming: even a perfect stale-action detector is inadequate if the emergency cancellation signal itself is delayed.

**Implemented:** a process-local `threading.Event` cancellation fence is latched *before* attempting any state lock. `abort()` takes the lock only if immediately available; the existing dispatch path checks the signal and revokes its entire timing window on return. A concurrent abort during replay preparation likewise discards unpublished replay evidence. An abort from within the callback itself revokes the window. The formerly collected timestamps are cleared on revocation; nothing is reported as independently proven gameplay. The default feature remains host-only and opt-in.

**Deliberate limitation:** Python cannot interrupt a blocked callback, unsend already-injected input, or enforce a physical key-up deadline. Production Windows game integration still requires an independently responsive native cancellation/neutralization fence and a host-side watchdog that physically releases all held keys/buttons. This change makes *evidence cancellation* nonblocking; it does not certify safe physical actuation.

Verification: the deterministic new tests hold a synthetic callback open on a separate thread, cancel from another thread, and assert that cancellation returns before the callback is released, with prior successful evidence also revoked. They cover same-thread cancellation and legacy API rejection after abort. Run them with `PYTHONPATH=. .../pytest tests/test_host_nonblocking_abort.py`; no real key injection is involved.

## Evidence-driven gaming intelligence — priority integration path

1. **Short-horizon reflex loop**: isolate a small, deadline-limited action controller from expensive tactical reasoning. Perceptual acquisition, decision, native dispatch, host ACK, *physical release*, and game-state transition need separate monotonic timestamps. Keep a hard maximum age per action and a cancellation watchdog outside any model/GPU execution thread.
2. **Tactical loop**: use a world model that predicts trajectories and game-specific mechanics, but let the host independently verify whether predicted state changes occurred. Retain uncertainty, not simply one chosen action. When uncertain, prefer reversible/low-risk actions or observe again.
3. **Long-horizon practice loop**: introduce unfamiliar games, held-out tasks, counterfactual failures and skill transfer trials. Measure objective-completion, safety violations, progress and wall-clock latency together. Label successes only with trusted in-game telemetry. Keep training/retrieval data strictly separated from evaluation holdouts.
4. **Evidence pipeline**: build on the repository's existing `VerifiedGameStateObserver`, `GameActionOutcomeFeedback`, `GameTrial`, and game benchmark modules, rather than treating host callback acceptance as a win. Existing signed moments are provenance assertions *within the trusted test host*, not cryptographic proof that an arbitrary online game is honest.

**Why:** *GameWorld* (2026) uses 34 browser games, 170 tasks and objective state-variable scoring, which is a much stronger evaluation template than an LLM judging screenshots. Its real-time track evaluates environments that continue advancing during reasoning. *Gym-Anything-RT* (2026-10-27) reports a large paused-vs-realtime success gap; inference deadlines are part of intelligence-in-practice, not just a performance optimization.

**Next verifiable milestone:** on an owner-controlled offline Windows game, collect one privacy-scrubbed episode with a native kill fence and independently sampled state transitions. A passing result needs (a) every offered frame accounted for, (b) no stale action accepted, (c) key-up physically verified, (d) gameplay state objectively corroborated, (e) dropped frames and failures retained, (f) no OBS broadcast.

## Making Star faster without sacrificing gaming quality

**Fast-path routing rather than one giant model:** classify workloads into urgent input, short dialog/backchannels, complex game strategy, game-building/research and background learning. Admit GPU jobs only when predicted memory headroom and game/OBS frame budget allow them. Make quality-based fallback to a smaller model or CPU voice possible. Avoid silently downgrading critical reasoning: defer it or tell the user when needed.

**Measure the complete path:** report p50/p95/p99 for capture→observation, prefill, first token, decision-ready, native input submission, ACK and verified state change; for VTuber speech, track voice turn endpoint→first audible sample (not text ready), speech interruptions, lip-sync drift and OBS render/encode/network drops. Separate model tokens/sec from capture-to-action success.

**RAM and caching:** session-isolated KV cache, exact model/prompt cache fingerprints, bounded memory budgets and no cross-viewer leakage. Speculative decoding is an experiment, not a guaranteed win: benchmark draft+target configurations versus normal decoding under *concurrent OBS + game workloads*. If a GPU has only 8 GB VRAM, large models and long contexts can compete with the game; do not use an inference-only speed estimate as streaming throughput proof.

**Voice candidate:** Kyutai Pocket TTS **v4.0.0 (2026-10-20)** released 18m, 7m and experimental 2m English variants; **v4.0.1 (2026-10-21)** fixed small-model pronunciation and changed the default English model. Test CPU startup cost, audible latency, quality, stability and total stream frame impact on actual hardware. These models are not automatically the best natural voice for Star.

**Hardware action:** development Linux root volume was approximately 95% full during this run; avoid pulling model weights or deleting unknown project data. Establish storage headroom, then measured, reproducible A/B runs on the authorized Windows host.

## Make Star a believable *AI* VTuber without fake human claims

Give Star a durable **character bible** (the accepted chibi look, recognizable voice, preferred humor, privacy rules, interests and evolving project history), not just a single persona prompt. Stream outputs should come from four distinct, interruptible channels:

- **Listening and backchanneling:** quick acknowledgments and idle-gaze cues when a viewer is speaking; silence when an important game action is in progress; incoming turns can interrupt a long response. Use trustworthy end-of-speech signals.
- **Natural voice and face:** expression/laughter timing should follow *actual audible* phonemes and game events, with lip sync and gaze constrained by true playback state. Provide a consistent voice and reduced-motion option.
- **Grounded autobiographical continuity:** recall only actual signed gameplay milestones, user-authorized memory and validated anecdotes. Separate fiction/roleplay from actual achievements, prior relationships and current events. A streamer can express curiosity and affection without pretending to have a human body or independent consciousness.
- **Stage director:** priority and cooldown rules to prevent rapid-fire repetitive jokes; latency-aware speech cancel/preempt, intentional conversational pauses, and safe streamer mute when OBS/audio telemetry becomes unreliable. Allow deliberate hobbies, artwork and narrative arcs as *projects*, with actual work/results evidenced.

NVIDIA **DyaPlex (June 2026)** studies streaming full-duplex conversational speech plus synchronized motion. It is a useful design reference, not a drop-in guarantee for Star's existing rig. Build a low-cost version first using real-time audio playback envelopes and existing rig animation; measure whether audience conversations feel more responsive before considering large generative motion models.

## Game creation and wider generalist capabilities

Use Roblox's built-in Studio MCP to inspect the game model, author scripts, run Luau and test *in a throwaway place*; build scripted and visual oracles for collision, UI touch targets, sound, animation, physics and networking. The **Studio MCP Open Cloud** documentation explicitly warns that some granted scopes can change live data stores, game settings, moderation state, currency and assets. Keep read-only/private-test permissions by default; exporting assets, releasing a game, running financial operations or affecting players uses separate owner approval.

Expand Star's generalist knowledge with source-versioned retrieval and task-specific memory:
- development: API versions, Luau analyzers, reproducible Roblox Studio builds, Blender exports and material constraints;
- play: rules identification, tactic prediction, team communication, cooperative multiplayer (respect game terms and anti-cheat);
- art/audio: critic/evaluator loop with visual or waveform checks;
- desktop operations: explicit device budgets, rollback, audit trails and emergency stop;
- research: provenance, source dates, contrastive hypothesis tests and independent holdouts.

For autonomous self-improvement, use the already requested local offline-first forge. **Propose → branch → implement → static-check → sandbox-test → independent score → rollback/promote**. Do not equate accumulating self-written lessons with model-weight intelligence gains. Only measured transfer to unfamiliar tasks counts.

## Acceptance gates and what is NOT yet implemented

The implemented delta in this change is a nonblocking abort *signal* for one host gaming timing probe and synthetic regression tests. It does **not** install real Windows input control, provide independent game-state proof, achieve native low-latency inference, download TTS models, or turn on a live stream.

Before saying Star can autonomously game and stream on Windows, require a private, non-broadcast rehearsal with bounded native input holds, host-controlled stop, audio stop, OBS-safe state, accessible character animation, measurable on-screen game performance and recorded evidence quality. Collect failure cases as well as wins. A larger neural model should only be called an intelligence upgrade when paired A/B holdouts show a repeatable improvement at acceptable frame time and resource usage.

### Sources reviewed (publication and release dates)
- GameWorld: https://gameworld-project.github.io/ (2026 benchmark, 34 games / 170 tasks)
- Gym-Anything-RT: https://arxiv.org/abs/2610.37567 (2026-10-27)
- RT-SAFE: https://arxiv.org/abs/2610.09294 (2026-10-07; separate task completion from risky collisions)
- NVIDIA DyaPlex: https://research.nvidia.com/labs/amri/projects/DyaPlex/ (June 2026)
- Kyutai Pocket TTS: https://github.com/kyutai-labs/pocket-tts/releases (v4.0.0 2026-10-20; v4.0.1 2026-10-21)
- Roblox Studio MCP Open Cloud: https://create.roblox.com/docs/studio/mcp-open-cloud (accessed 2026-11-06)
- OBS WebSocket: https://github.com/obsproject/obs-websocket (local authenticated OBS connection; no broadcasting performed)
