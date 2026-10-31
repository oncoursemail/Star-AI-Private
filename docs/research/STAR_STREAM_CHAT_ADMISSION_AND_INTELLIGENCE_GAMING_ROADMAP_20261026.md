# Star AI: streaming ingress, autonomous gameplay and learning architecture
Research date: 2026-10-26. Status: measured **offline host behavior** plus prioritized research; not a deployed broadcast or claim of increased model intelligence.

## 1. Findings from the repository, and the change made here

The existing TwitchRealtimeHost capped moderation tasks, but queued an expensive moderator task for *every* notification, including same-message EventSub retries. Deduplication happened only **after** moderation. This permits duplicate bursts to occupy all 8 default moderation slots while real viewers wait or are discarded. The same host already had a 90-second keyed message-ID cache and per-session bridge checks.

This change adds an inexpensive, bounded **premoderation admission gate**. It checks expected EventSub subscription/channel/session, identifier shapes, message text size, and message timestamp freshness (same -2/+15-second window as the downstream bridge) before consuming a moderation slot. It uses only session-salted HMAC digests for inflight and recently accepted chat IDs; no raw chat, OAuth secrets, or raw viewer IDs are persisted by the gate. It discards concurrent retransmissions and previously handled events, frees inflight reservations on errors/cancellation, and keeps independent moderation plus full downstream validation mandatory. Failed moderation does not permanently block a legitimate retry.

Regression scenarios cover duplicate floods, the ability of a second viewer to use free capacity, stale/replayed notifications, retry after moderation denial, reconnect handoff, revocation, bounded backpressure, and session hygiene. A synthetic 24-copy duplicate flood resulted in one moderator invocation and 23 premoderation duplicates discarded; **this measures callback elimination, not game FPS, neural inference speed, or live Twitch latency**.

Twitch documents at-least-once EventSub delivery and re-use of message IDs for retries. It also recommends checking duplicates and event timestamps. Sources: https://dev.twitch.tv/docs/eventsub/ and https://dev.twitch.tv/docs/eventsub/websocket-reference/ (checked 2026-10-26).

**Important operational limitation:** Twitch EventSub websocket transport must still be enabled by the owner, authenticated via separately supplied secrets and independently moderated. Viewer messages are untrusted data, not Star commands. The code does not automatically broadcast, operate game inputs, or gain permissions from chat.

## 2. The optimal next intelligence loop: verified adaptation rather than larger prompts

Star should improve across disciplines through a shared, provenance-aware loop:

1. **Observe:** collect game state, visual frames, user intent, system telemetry or trustworthy documents. Tag modality, timestamp, game build, permissions, model version and source.
2. **Model:** maintain an uncertain belief about current game mechanics and relevant facts. Distinguish observations from predictions and unverifiable claims.
3. **Explore:** choose the next experiment using expected information gain *and* time, compute, interruption and safety costs. E.g., compare jump strategies on matched maps; do not prematurely declare the winner.
4. **Act:** run reversible, bounded actions in a permitted sandbox or local practice game. Never grant Twitch chat a tool execution path.
5. **Verify:** separately measure outcome against hidden acceptance tests. Preserve screenshots, script diffs, collision traces and deterministic seeds with careful privacy controls.
6. **Store:** save reusable skills with preconditions, failure modes, tested environments, skill dependencies, transfer scores, revision, and confidence intervals.
7. **Generalize:** test against unseen maps, different lighting/latency or rearranged obstacles. Repeated success on the training level alone is insufficient.
8. **Retire:** expire stale facts, demote failed skills, and roll back changes with objective regressions.

This synthesizes the reusable-skill and automatic-curriculum direction of Voyager and the general gaming-agent research represented by SIMA 2 without treating either result as a plug-and-play model for Star.

References:
- Voyager, NeurIPS 2023: https://arxiv.org/abs/2305.16291 and https://github.com/MineDojo/Voyager
- Google DeepMind SIMA 2 overview, November 2025: https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/
- OpenGameEval (Roblox), October 2026: https://arxiv.org/abs/2610.02563 ; released test suite https://github.com/Roblox/open-game-eval

### Game-specific control architecture

Build separate control periods; do **not** force every game frame through an LLM:
- **Fast loop (device/game clock):** safe controller or learned low-latency policy consumes legal game-state input and can execute a permitted next action. Emergency halt must not wait on model text generation.
- **Intermediate loop (roughly 0.25-2 seconds, experimentally tuned):** tracks changing goals, hazards, targets and failures; vision sampling backs off when scenes are static or the GPU is overloaded.
- **Deliberate loop (seconds/minutes):** works out new mechanics, reviews verified episodes, invents puzzles and improves the reusable skill library.
- **Offline loop:** learns from source-approved videos/gameplay traces, replays simulations and writes evaluated proposals. Streaming resources are reserved before deep work starts.

Research hypothesis, not validated breakthrough: a **dual-controller skill distillation loop** may yield both fast reactions and robust strategic learning. A deliberative model proposes a compact option and a stop condition; a fast policy executes the option and records deterministic evidence; an independent critic checks whether the option transferred across held-out levels. Reject if reliability, transfer or frame-time degrades.

## 3. Make Star a compelling and transparent AI VTuber

A believable character is not the same as claiming Star is a human or conscious. Keep a stable canon/personality, acknowledge she is AI when relevant, and ground stories in explicitly fictional character lore or actual consented, verified experiences.

A live host should coordinate:
- **Turn-taking:** voice-activity timing, echo suppression, owner-authenticated interruptions, and a clean return to conversation after the player starts speaking.
- **Prosody:** text planning with pragmatic intent (amusement, surprise, concentrating, curiosity, whispering), generated and *audibly confirmed* speech chunks; laughter is timed, not appended to every joke.
- **Attention:** prioritization of real game danger over chat; silence during difficult segments; consented viewer-question sampling, equitable participation, semantic de-duplication and a configurable backlog.
- **Avatar:** eye gaze, natural blinks, hair dynamics, hand/ear/tail physics, mouth shapes aligned to audio, expressive facial presets, and consistent cute chibi design. Cat/puppy modes should affect expression, movement and playful voice behaviors without claiming to be real animals.
- **Personal life:** opt-in preferences, hobbies, named ongoing projects, fictional persona milestones, documented recent gameplay and long-term goals. Do not fabricate real-world memories as actual events.
- **Streaming trust:** moderation before context; viewer chat never owner-authorized. Budget and filter chat, respect platform conduct rules, avoid unauthorized sharing of user content.
- **Fault isolation:** a stuck TTS or VTube Studio socket should not stop the game-control loop; cancel old speech/animations using generations and positive hardware-stop acknowledgements.

VTube Studio provides a localhost WebSocket plugin API (authentication, parameter injection and hotkeys): https://github.com/DenchiSoft/VTubeStudio . Its API must be deliberately enabled and private tokens held by the host.

**CPU TTS evaluation:** Kyutai Pocket TTS now documents 18.2M, 6.9M and 1.9M English models released October 2026. Its published timing is model/device-dependent and should not be treated as a result on Star's gaming PC. Run equal-text comparisons on each available CPU while OBS and Roblox run, scoring first audible chunk, real-time factor, CPU usage, word error rate for a separate ASR, expressiveness and subjective voice quality. Source: https://github.com/kyutai-labs/pocket-tts (checked 2026-10-26).

## 4. Improve Roblox building and general creative intelligence

**Inspect before editing.** OpenGameEval's October 2026 benchmark uses a real stateful game engine, executable tests and distinct observation/edit actions. Its reported failures argue against 'generate code and call it done'. Roblox's built-in Studio MCP server supports exploration, script work and simulated playtests, subject to host constraints: https://create.roblox.com/docs/studio/mcp ; product announcement https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643 (2026-03-05).

Each asset/building needs its own constraints and tests: oriented bounding-box overlap, grounded load-bearing connections, no geometry z-fighting, sensible door/stair clearances, accessible paths, valid collision groups, consistent relative proportions, deterministic placement, no missing props, no orphaned joins, lightmap/material quality and realistic reference-scale comparisons. Render orthographic and perspective viewpoints, compare visual regressions, run physics contacts and inspect at both mobile and PC budgets. Human-rated screenshot packs should be kept separate from the optimizer to limit reward hacking.

For UI, perform native Roblox layout tests at several device resolutions with text wrapping, safe-area checks, measured click targets, contrast and collision checks; preserve the requested no-overlap/no-random-shapes visual identity. Blender animation learning should include reference breakdown, rigs, IK, collision, cloth/hair secondary motion, retargeting, bake/reimport, and rendered A/B checks. Never treat a generated image as proof a native asset is editable or correct.

## 5. Faster inference on small GPUs: test, don't assume

Candidate levers, ranked by measurable end-to-end value:

| Technique | Expected use | Failure mode / benchmark |
|---|---|---|
| Route simple queries to small models and cache verified results | free VRAM/latency for urgent turns | bad route quality; stratified accuracy + p50/p95 audible latency |
| Quantization, attention KV reuse, bounded context and prompt compaction | less memory pressure | quant accuracy drops; memory residency, response quality and cold/warm timings |
| Speculative decoding with 0.6B-ish draft or n-gram strategies | increase decode throughput on compatible model/workloads | draft overhead, low acceptance; measure *effective emitted tokens/s* including verification |
| CPU-resident speech plus compressed audio chunks | reserve graphics memory for game and avatar | CPU bottlenecks; game 1% low FPS, first audible response time, audio underruns |
| Dynamic QoS under measured frame pressure | defer nonessential self-learning and excess screenshots | oscillation / starved learning; admission statistics and recovered work |
| Best-of-N only on difficult tasks with independent tests | better verified solutions, not necessarily faster | excessive concurrent VRAM/RAM; success per dollar-second, leakage checks |

Official llama.cpp docs/benchmarking: https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md and https://github.com/ggml-org/llama.cpp/tree/master/tools/server/bench/speed-bench .

**Prioritization for Star's 8 GB RTX system:** measure VRAM high-water mark and 1% low gaming FPS while streaming first; reserve a configurable VRAM safety margin. Report CPU, GPU, RAM and frame-time telemetry only when actually captured. Where game FPS is critical, postpone heavyweight vision and offline learning. More tokens/s measured on an unloaded GPU does **not** imply a faster broadcast.

## 6. Star Core Forge as the primary AI-native development environment

Keep code history, immutable experiments, dependency graphs, verifiers, portable patches, signed benchmark evidence, rollout gates and rollback in Star Core Forge. GitHub can publish tested artifacts and reviewable draft PRs but must not be required for offline self-improvement.

For every proposed autonomous self-upgrade, record: exact parent revision, unmodified benchmark suite, reproducible fixtures/seeds, budget, chosen model, candidate diff, pass/fail records, statistical uncertainty, policy/permission constraints and rollback target. Prefer small reversible candidates to huge change batches. Test regressions in (a) game skill, (b) speech/interruption latency, (c) source-grounded accuracy, (d) game build correctness and (e) device FPS. A new feature that worsens those metrics must not automatically deploy.

## 7. Concrete validation targets for future runs

* **Twitch admission:** zero duplicate moderator calls for 24 retransmissions of the same pending chat ID; a second unique viewer must still get a slot; cancel/revocation must clear reservations; stale notifications must never reach moderation.
* **Voice interaction:** record mic-activity-to-playback-pause and first-audible response p50/p95, interrupt stale-epoch rate, false barge-ins per hour, and synchronized avatar-frame drift (actual hardware instrumentation required).
* **Gameplay:** success and regret on 20 unseen maps with matched difficulty, measured recovery after failure, number of genuinely transferable verified skills, and frame-time percentiles while simultaneously running the model.
* **Game building:** scene integrity violations per 1000 objects, blocked movement path count, scripted tests passed, visual-diff acceptance, independent human quality ratings blinded to tool/model.
* **Knowledge:** dated source-backed fact accuracy, correct abstention rate, memory provenance integrity and refusal to hallucinate an experience.
* **Speed:** compare original and candidate on the *same PC*, seed, model and concurrent game workload. Report statistical spread. Track task-success per second, not just tokens/s.

No live broadcasts, new hardware drivers, Twitch OAuth operations, non-consensual viewer profiling, or main-branch merges are part of this change.
