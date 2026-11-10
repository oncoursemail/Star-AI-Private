# STAR — memory, turn-taking, game mastery, and creator intelligence research

**Research snapshot:** 2026-11-09 (America/Chicago)  
**Repository:** `oncoursemail/Star-AI-Project`  
**Scope:** long-horizon memory, conversational timing, local inference, real-time gameplay, Roblox/game-engine creation, and natural AI VTuber behavior.  
**Status:** research and architecture recommendations only unless explicitly marked implemented. This document does not claim new model training, native Windows integration, hardware speedups, or gameplay mastery.

## Executive conclusion

Star's next intelligence gains should come from better **state management, feedback, and evidence**, not merely longer prompts or more simultaneous agents.

Five research findings have especially direct engineering implications:

1. **Memory must preserve execution state and verify freshness.** A remembered test result is unsafe after the file, dependency, model, or environment it tested has changed.
2. **Memory should intervene selectively.** Injecting every remembered fact into every prompt wastes context and can distract the action model. A memory worker should remind only when a relevant prior constraint or failure is likely to change the next action.
3. **Natural streaming needs a dedicated turn-taking evaluator.** End-of-turn (EOT) and interruption (INT) detection are separate from response generation and separate again from physical playback.
4. **Game agents need outcome-grounded, continuous-time evaluation.** Paused gameplay, screenshots, and model self-reports do not establish real-time skill.
5. **Game creation needs visual and executable feedback.** Compiling a script is only one part of validating a scene, animation, UI, or playable experience.

The architectural recommendation is to keep Star's fast interaction loop small and deadline-bounded, while separate memory, planning, research, and game-building workers run under resource budgets. Every worker should return typed evidence, not authority.

## 1. Long-horizon memory: preserve state, not just conversation

### MemTrace — state-consistent memory for coding agents

MemTrace (arXiv:2610.04838, 2026-10-04) stores immutable execution traces anchored to files, symbols, and tests, then links them in a dependency-aware trace graph. When context is compacted, a small set of anchors can reconstruct the latest task state. Before old evidence is reused, the system checks whether it is still valid against the current repository state.

The paper reports improvements on three long-horizon coding benchmarks under its evaluated Codex CLI setup: DeepSWE pass@1 +21.2 points, SWE-EVO resolved rate +4.4 points, and SWE-Milestone score +17.8 points. These are results from that study, not expected Star gains.

**Application to Star:**

- Store an immutable trace for each meaningful action: inspected artifact, exact revision/hash, action, command/tool, exit status, test result, and follow-up dependency.
- Anchor evidence to file hashes, symbol signatures, test IDs, model/runtime revisions, and game/scenario IDs.
- On retrieval, revalidate only the anchors relevant to the next action. A changed source file invalidates old test evidence for that file; a changed model/runtime invalidates old latency comparisons.
- Keep compact active-task anchors in working memory; retain full traces in local storage.
- Preserve failed attempts and diagnoses so Star does not repeatedly retry equivalent failed approaches.
- Treat tool output as evidence with scope and timestamp, not as a universal fact.

Do not store secrets, raw viewer audio, or unrestricted chat logs in the trace graph. Store opaque references and bounded summaries; keep content capture separately opt-in.

Primary source: [MemTrace paper](https://arxiv.org/abs/2610.04838) · [MemTrace implementation](https://github.com/Homy-Xu/MemTrace).

### Remember When It Matters — selective memory intervention

The July 2026 paper *Remember When It Matters* models memory as an active worker that watches the recent trajectory, updates a structured bank, and decides whether to inject a short memory-grounded reminder or stay silent. It reports +8.3 percentage points on Terminal-Bench 2.0 and +6.8 points on tau-squared-Bench in its evaluated setup. Its ablations report that selective intervention outperformed always-on memory exposure and general retrieval.

**Application to Star:**

- Keep the action model's prompt compact; do not append the entire memory store.
- Run retrieval against the current task, tool, project, game, and recent failure signature.
- Inject only a short reminder when it changes a decision: an owner constraint, a known failing command, a security invariant, or an uncompleted prerequisite.
- Add a cooldown and deduplication key so the same reminder is not repeated every turn.
- Record whether the reminder was used and whether it improved the outcome; do not equate retrieval with usefulness.
- Let the memory worker recommend; it must not execute tools or override owner policy.

Primary source: [Remember When It Matters](https://arxiv.org/abs/2607.08716) · [Research code](https://github.com/yifannnwu/proactive-memory-agent).

### Proposed Star memory record

A useful typed record should include:

- `kind`: fact, observation, experience, procedure, skill, hypothesis, preference, or persona lore;
- `subject` and `scope`: project/game/model/device/session;
- `source_ref`: opaque file/tool/event reference;
- `source_revision`: hash, version, or host epoch where applicable;
- `observed_at` and optional `expires_at`;
- `confidence` and verification method;
- `dependencies`: evidence that must remain unchanged for reuse;
- `status`: active, superseded, stale, disputed, or rejected.

A skill should be promoted only after repeated successful use and held-out transfer. A hypothesis must never silently become a fact. Fictional Star persona lore must remain separate from actual interaction history.

## 2. Natural VTuber streaming: evaluate turn-taking separately from speech

### TurnBench — end-of-turn and interruption detection

TurnBench (arXiv:2608.25218; public code under MIT) describes 154 two-channel conversations totaling about 30 hours, 106 speakers, and six conversation types, with triple annotations. It evaluates EOT and INT timestamps using recall, false-positive rate, and detection latency. The public dataset access is gated, and the data has a separate non-commercial license that prohibits voice cloning; do not mirror or redistribute it, and follow its access and dataset-specific terms.

**Application to Star:**

- Separate the listener from the response generator. The listener predicts whether the speaker is continuing, yielding the floor, or interrupting; the response planner then chooses speak, backchannel, defer, or silence.
- Measure EOT and INT detection latency independently from first-audio latency.
- Use a causal streaming baseline first (VAD + pause duration + incremental ASR features); only add a learned detector if it improves recall without excessive false interruptions.
- Preserve partial ASR as provisional. A pause inside a sentence is not necessarily turn completion.
- Give owner speech and explicit barge-in priority over optional Star commentary.
- Cancel optional TTS and avatar motion as one turn/epoch, and verify native STOP/FLUSH before declaring audio stopped.
- Evaluate speaker overlap and self-correction separately from ordinary silence gaps.

The existing `stream_response_timing_benchmark.py` evaluates whether Star should speak, backchannel, or remain silent after an event. It does **not** score the listener's EOT/INT detector. A future adapter should consume only sanitized timestamps and opaque IDs, with no raw audio or transcript in reports.

Primary source: [TurnBench repository and dataset description](https://github.com/SesameAILabs/turnbench) · [TurnBench paper](https://arxiv.org/abs/2608.25218).

### Full-duplex interaction acceptance

Measure these stages separately:

1. capture-to-VAD observation;
2. VAD/ASR partial availability;
3. EOT/INT decision;
4. response-planner decision;
5. first TTS chunk;
6. native PCM submission;
7. first device-observed sample;
8. avatar first-visible response;
9. cancellation-to-physical-quiet.

A response is not "heard" merely because the TTS engine returned text or a PCM buffer was queued. Native host receipts must bind request, output route, session epoch, and monotonic timestamps.

## 3. Game mastery: use outcome state and a running clock

### GameWorld — verifiable multimodal game evaluation

GameWorld describes 34 browser games and 170 tasks across runner, arcade, platformer, puzzle, and simulation genres. Its scoring reads serialized game state (for example, score, position, lives, and checkpoints) rather than relying only on screenshot heuristics or an LLM judge. It also distinguishes a real-time variant where the environment continues advancing during inference.

**Application to Star:**

- Prefer authoritative game-state oracles when available; use vision-based estimates only when no trusted state API exists.
- Record success, normalized progress, damage/lives, action count, wall-clock deadline, and observation age.
- Run paused and real-time tracks separately. Never compare their scores as if they were the same task.
- Split practice and evaluation scenarios. The learner must not train on the held-out maps or initial states used to claim transfer.
- Track per-mechanic skill (movement, aiming, navigation, timing, resource use) instead of one blended "game IQ" score.
- Use a fast reflex controller for immediate actions and a slower tactical planner for route/strategy updates. The tactical planner must not block the action deadline.

Primary source: [GameWorld benchmark](https://gameworld-project.github.io/).

### Gym-Anything-RT

The October 27, 2026 real-time benchmark reinforces that strong paused-environment reasoning can collapse when the game clock continues during model inference. Star should measure observation age, decision latency, action acknowledgement, and deadline misses—not just final win rate.

Primary source: [Gym-Anything-RT, arXiv:2610.37567](https://arxiv.org/abs/2610.37567).

## 4. Game creation: visual feedback and inspection are first-class

### OpenGameEval — Roblox Studio

OpenGameEval evaluates agents inside reproducible Roblox Studio sessions using executable checks on both the edited scene and simulated play. Its paper describes 84 curated tasks, 13 models, and 16 attempts per task. It reports that inspecting task-relevant objects before editing was associated with higher pass rates: +13.4 points on scene-only tasks and +9.8 points on script-only tasks versus runs that inspected none of those objects.

**Application to Star:**

- Make inspection a required phase before edits: hierarchy, object properties, scripts, references, constraints, and current runtime state.
- Separate observation tools from edit tools so the agent can be evaluated for exploration quality.
- Validate the saved scene and then simulate/playtest it.
- Preserve before/after artifact hashes and executable test receipts.
- Keep publishing, live DataStore writes, monetization, and production changes owner-approved.

Primary source: [OpenGameEval paper](https://arxiv.org/abs/2610.02563) · [Roblox OpenGameEval repository](https://github.com/Roblox/open-game-eval).

### GameDevBench — multimodal game-engine work

GameDevBench contains 333 Godot game-development tasks across 2D graphics/animation, 3D graphics/animation, UI, and gameplay logic. Its paper reports that gameplay tasks were easier on average than 2D graphics tasks (51.4% versus 33.0% success in the reported aggregate), and visual feedback raised GPT-5.4 from 41.1% to 52.0% in its evaluated setup.

**Application to Star:**

- Treat screenshots/video from the running engine as a feedback channel, not as decorative evidence.
- Compare actual runtime frames against intended layout/animation/lighting.
- Check multiple resolutions and device classes.
- Evaluate UI reachability, clipping, hierarchy, animation state, collision, audio, and game logic separately.
- Require an executable test or an explicitly labeled human review for each dimension.

The benchmark is Godot-specific; adapt its evaluation principles rather than assuming its tasks directly measure Roblox performance.

Primary source: [GameDevBench repository and results](https://github.com/waynchi/gamedevbench) · [GameDevBench paper](https://arxiv.org/abs/2602.11103).

## 5. Faster local inference: optimize the whole gaming/streaming system

The existing mixed-workload benchmark is a useful start, but a model-only benchmark cannot decide which model is best for Star's live workload.

### Required measurement matrix

Compare the same model revision, quantization, prompt suite, context length, sampler, and runtime build under these stages:

1. model idle;
2. model + game;
3. model + game + OBS;
4. model + game + OBS + TTS;
5. full stack + vision and avatar updates.

Capture:

- first nonempty content chunk (client-observed, not raw engine TTFT);
- server TTFT and prompt-eval time when the runtime exposes them;
- decode tokens/second when token usage and timing are complete;
- inter-chunk p50/p95/p99;
- first-audio and first-avatar latency;
- GPU/VRAM peak and headroom;
- CPU, RAM, disk I/O, and queue depth;
- game frame-time p95/p99 and missed action deadlines;
- OBS render/encoding lag and dropped frames;
- audio underruns and cancellation-to-quiet latency;
- task quality on fixed, held-out evaluations.

### Research candidates, not automatic upgrades

- llama.cpp speculative decoding (including n-gram approaches): measure acceptance rate and end-to-end latency with identical prompts; a higher acceptance rate alone is not proof of a user-visible speedup.
- Prefix/KV caching: useful when prefixes repeat, but measure cache hit rate, eviction, memory pressure, and prompt-prefill savings separately from decode speed.
- KV-cache compression/offload: potentially valuable for longer contexts, but CPU↔GPU transfers and gaming contention may erase the benefit on an 8 GB consumer GPU.
- Smaller specialist models: route only to explicitly configured, evaluated aliases; retain a stronger model for tasks whose quality gate fails.
- CPU TTS: benchmark CPU contention against GPU TTS under actual game load; offloading is not free if it steals time from the game or ASR.

**Promotion rule:** no model/runtime profile should be recommended for the live stream merely because it has higher tokens/second. It must preserve task quality, first-audio latency, game frame-time, OBS health, and memory headroom. Reports from different hardware, revisions, or workload suites are not comparable.

## 6. Integrated Star architecture

| Loop | Responsibility | Deadline/authority |
|---|---|---|
| Reflex | Latest game/audio observation and immediate safe response | Hard deadline; bounded allowlisted actions |
| Conversation | EOT/INT, turn ownership, speak/backchannel/silence | Causal event epoch; owner barge-in wins |
| Tactical | Game strategy, route choice, viewer context, task planning | Runs asynchronously; cannot block reflex |
| Memory | Trace updates, freshness checks, selective reminders | Read-only recommendations; no tool authority |
| Creator | Inspect, edit, run, visually compare, repair | Sandboxed project scope; publish requires approval |
| Research | Search, source comparison, claim ledger, experiments | Source-linked; hypotheses stay unverified |
| Performance | Workload measurement and resource admission | Protect game/OBS/audio headroom |

Every loop should communicate through typed, bounded messages with opaque IDs, source/revision, monotonic time, expiry, and confidence. A slow worker must never make stale data appear current.

## 7. Prioritized implementation plan

### P0 — keep current benchmark and CI trustworthy

- Keep the local-only mixed workload benchmark bounded and privacy-safe.
- Fix the Pyright async stream-close type error with `inspect.isawaitable`, and retain tests for both asynchronous and synchronous close methods.
- Require Linux offline tests, Pyright, React checks, and Windows packaging before calling a PR green.

### P1 — memory trace graph

- Introduce append-only trace records and dependency anchors.
- Revalidate evidence against the current repository/model/game revision before reuse.
- Add a selective memory reminder policy with utility threshold, cooldown, and token budget.
- Evaluate memory-to-action success on held-out tasks; retrieval hit rate alone is insufficient.

### P1 — turn-taking evaluator

- Add an EOT/INT adapter that accepts only causal timestamps and opaque IDs.
- Report EOT recall, INT recall, false-positive rate, and detection latency by conversation type.
- Keep dataset licensing and gated access separate from code licensing; do not use voice datasets for cloning.

### P1 — quality-aware inference comparison

- Pair performance runs with fixed knowledge, Luau, debugging, and game-task quality suites.
- Require matching model/runtime/hardware/workload identities.
- Reject incomplete token usage or missing category coverage.
- Recommend manual review only; never silently change the configured model.

### P2 — game and creator adapters

- Build a small Star-owned task subset inspired by GameWorld, OpenGameEval, and GameDevBench.
- Keep practice seeds separate from held-out evaluation seeds.
- Capture runtime screenshot references and executable state checks.
- Add real-time action deadlines and resource-loaded tests.

### P2 — native Windows rehearsal

- Wire the Python plans to actual WASAPI endpoint/route observations, VTube Studio, and OBS.
- Verify native stop/flush and route-change behavior before enabling audio.
- Run private, nonbroadcast 30–60 minute rehearsals with the full stack.
- Keep all new capabilities disabled until their specific native acceptance tests pass.

## 8. Safety, privacy, and trust boundaries

- No raw transcripts, viewer identities, audio, or screenshots in default benchmark artifacts.
- Dataset access and license restrictions must be respected; no voice cloning from TurnBench data.
- OBS WebSocket stays authenticated and loopback-only by default.
- VTube Studio parameters and hotkeys use a host-side allowlist and rate limits.
- Game input remains limited to an explicitly selected private test environment until owner approval.
- Publishing, live game writes, account actions, public broadcasting, purchases, and destructive system operations remain owner-approved.
- A model's claim that it learned, spoke, saw, or completed a task is not evidence; use independent host receipts and held-out evaluation.

## References

1. MemTrace (2026-10-04): https://arxiv.org/abs/2610.04838
2. Remember When It Matters (2026-07-09): https://arxiv.org/abs/2607.08716
3. TurnBench: https://github.com/SesameAILabs/turnbench and https://arxiv.org/abs/2608.25218
4. GameWorld: https://gameworld-project.github.io/
5. Gym-Anything-RT (2026-10-27): https://arxiv.org/abs/2610.37567
6. OpenGameEval (2026-10-01): https://arxiv.org/abs/2610.02563 and https://github.com/Roblox/open-game-eval
7. GameDevBench: https://github.com/waynchi/gamedevbench and https://arxiv.org/abs/2602.11103
8. llama.cpp: https://github.com/ggml-org/llama.cpp
9. SGLang: https://github.com/sgl-project/sglang
10. OBS Remote Control Guide: https://obsproject.com/kb/remote-control-guide
11. VTube Studio Plugin API: https://github.com/DenchiSoft/VTubeStudio/wiki/Plugins
