# Star AI: decision-time OBS liveness, real-time learning and natural VTuber roadmap

**Research date:** 2026-11-08. **Status:** implementation + offline regression tests; draft stacked change, not live deployment. **Project:** Star AI. These are testable engineering recommendations, not assertions that Star now has human-level intelligence, a self-aware mind, a trained gameplay policy, or a streaming broadcast.

## New implementation: trust must persist until the decision

The previous read-only `ObsLoopbackLiveHost` (#1078) pinned the OBS process and OS TCP listener before/after authenticated websocket sampling. But `recommend()` could still return a prior healthy admission profile **after OBS exited, rebound the listener, or restarted between samples**. A model preparing a sentence could receive obsolete resource advice, even though no new sample was taken. Separately, the generic `StreamLoadGovernor` accepts telemetry as old as three seconds by default: this is longer than the desired real-time speech-admission cadence.

This change makes `recommend()` validate the pinned OBS process name/PID/creation time and unique IPv4 127.0.0.1 listener ownership again on the **decision boundary**. It also bounds the most recent accepted observation to a strict, configurable **750 ms** default; an expired/reversed receipt revokes the live epoch and disables optional workload advice immediately. Decisions remain advisory; the host still must independently authorize playback, game input and broadcast. A stopped transport remains stopped; re-arming requires a fresh session.

**Scope:** read-only process/socket checks and in-memory clock validation. No OBS mutations, broadcasts, recordings, microphone access, game input or output text. The decision-time check is intended for **low-frequency speech/workload admissions**, not for render/audio callbacks (OS TCP-table enumeration is potentially expensive). Review latency overhead on actual Windows hardware before enabling.

**Tests:** valid previously warmed advice; process disappearance between calls; listener-ownership loss; 749/751 ms TTL boundary; non-finite clock; invalid TTL types/ranges; safe warming behavior. Offline fake OBS does not prove real Windows compatibility.

## Research: where additional intelligence should come from

### 1. Real-time reflexes are different from deep reasoning

*Gym-Anything-RT*, posted **October 27, 2026**, creates 100 visual real-time minigames. The authors report a major real-time/paused gap on at least one frontier model (9% vs 75% success), emphasizing that a model able to reason when the world stops is not necessarily good at gaming while objects move.

Implement three independent loops for Star:
- **Reflex loop (target deadline 50-150 ms, task dependent):** capture only an approved game process; detect change, urgency, collisions and hazards; use already verified low-latency controls and drop late decisions. Reaction should not await a paragraph-length LLM explanation.
- **Tactics loop (0.3-2 s when safe):** route fight-or-flee, navigation, inventory, team communication and safe tactical tool calls to an appropriate model. Evaluate on state-dependent goals, not how eloquently a model describes them.
- **Practice loop (minutes/hours, off-stream):** generate a curriculum of counterexamples, retry, record independently observed rewards, and propose policies only after *held-out* maps/seeds and game versions pass. Keep practice-only mistakes out of live streams.

The important target is **win/progress rate at fixed response deadlines** with game FPS preserved. Compare the same game in real time, slow motion and paused mode. Report p50/p95 capture-to-action and misses, and vary the update interval, visual pixel budget, local model, load and input contention. Experiments must not bypass game anticheat or automate unauthorized competitive multiplayer.

### 2. Learning should not become memorizing the test

*Gym-Anything for Robotics* (posted **October 29, 2026**) presents simulation generation plus independent environment/task auditing and privileged-teacher approaches. It reports strong agents still have difficulty on unseen tasks, a useful reminder that self-generated practice can overfit the teacher.

For Star's local learning:
1. Build practice scenarios with frozen task manifests; separate generated practice seeds from hidden holdouts held by a verifier.
2. Log an opaque action ID, game-version ID, reaction deadline, success/progress, frame evidence digest and witness type. Never treat the LLM's own declaration of success as success.
3. Require statistically meaningful improvements over *matched* baseline attempts, including negative outcomes, not only selectively saved highlights.
4. Run **transfer trials** on unseen maps, changed physics, new teammates, alternate camera settings and time-pressure modes.
5. Retire or quarantine skills when a game update invalidates their preconditions; allow recovery/rollback without changing training history.

Star already has a `GameplaySkillBank`, separate verification / holdout facilities and game-deadline routers. **Integration and native evidence sources** are a higher priority than yet another unconnected skill planner.

### 3. Generalist knowledge: retrieval, verification and transfer

*Gym-Anything* (posted **April 7, 2026**) describes converting software into auditable agent environments and using independent review to find missing steps in long tasks. For Star, transfer this into real projects: Roblox Studio development, Blender meshes/materials, coding in Rust/Python/Luau, debugging, OBS/media production, and everyday factual research.

Separate:
- **Verified reference memory:** API versions, working code, known UI patterns, cited documentation.
- **Procedure memory:** reproducible workflows and preconditions for each tool, each device and each version.
- **Episodic stream memory:** events with witnessed game/source IDs and actual playback acknowledgements; do not fabricate achievements or claim Star spoke a sentence that was never audible.
- **Hypotheses:** unverified guesses and ideas clearly marked as such; must not silently become facts.

Use task-specific retrieval with source timestamps, a small active context, cached stable tool schemas, and a verification pipeline (unit tests, screenshots, simulator results, human review when needed). Max context alone is not intelligence: benchmark fact retention and tool-success rates under changing context lengths and workload contention.

## Research: believable AI VTuber behavior without impersonating a human

Microsoft's **Proact-VL (ICML 2026; May 2026)** studies proactive continuous visual understanding, *when* an AI companion should speak, and both quality and quantity of gaming commentary. In its study, scenarios include solo commentary, co-commentary and player guidance. For Star, train/evaluate **silence as a first-class output**:
- No ordinary joke when the player is in a critical fight, a person is talking or speech playback is already active.
- A spontaneous reaction to a *witnessed* event should occur while the event is still relevant.
- A question deserves an answer even during calm scenes; genuine owner interruption is higher priority than a prepared monologue.
- Remember specific prior gameplay facts and preferences without repeating stale catchphrases, performing fake memory, or inventing inner experiences.
- Give Star personal recurring mannerisms, changing interests and creative goals (games, art, friends, mascot modes) with consistent continuity; acknowledge she is AI rather than pretending to be a human individual.

**VoiceChat-TTS (August 13, 2026)** explores continuous LLM-token-driven speech, mid-utterance interruption and silence without resetting the model cache. This suggests testing an incremental TTS playout strategy against Star's existing PCM, preplay fences, interrupt/quiet witnesses and audio/rig host. The live listener must confirm **actual audible stop**, not merely that generation was cancelled. Distinguish gaming dialogue, co-commentary, chat reply and owner request.

For expression: drive eye movement, blink, head tilt, lip motion, gestures and occasional laughter from **audible phonemes / observed game facts**, with strict bounds on amplitude and synchronized playback epochs. In quiet periods, the existing quiet attention component should make minimal natural movement; a reduced-motion toggle stays respected. Additional animation is not evidence of genuine subjective feelings.

**Streaming success rubric** (independently reviewed A/B of matched scenes): first audible PCM latency, owner interrupt-to-silence, false interruption rate, talk-overlap, unnecessary speech in fights, grounded event references, memory consistency, viewer response appropriateness, rig/voice sync, and sustained game FPS/OBS QoS. Count silent, failed, cancelled and interrupted turns; do not evaluate only successful utterances.

## Research: getting meaningfully faster on a consumer 8 GB GPU

Do not promise any specific tokens/s from parameter size alone. Model file size, cache/context growth, draft model, KV precision, GPU layers, encoder/TTS contention, CPU bandwidth and game VRAM all matter. An 8 GB RTX 4060 cannot be assumed to keep a 9B model, long cache, OBS and a demanding game fully resident together.

Suggested reproducible experimental matrix (owner opt-in; **no results claimed**):
- **Baseline:** one latency-optimized small local model (e.g. 4B-class), fixed prompts and task categories at two contexts (short and long), fixed sampling settings.
- **Alternatives:** stronger local model at lower quantization; sparse/pixel-budget VLM; cached stable prompt bank; draft/speculative strategies; separate CPU speech model. Try one variable at a time.
- **Workloads:** idle machine; running game; game+private OBS recording; game+OBS+voice. Include periods with low available VRAM and game scene transitions.
- **Metrics:** time to first token, effective decode tokens/s, prefill, end-to-end *first audible* latency, p95 capture-to-action deadline, model quality on fixed held-out coding/game tasks, VRAM peak, RAM use, GPU contention, frame-time p95/p99, OBS missed/encoded frames. Record variance and test output validity.
- **Promotion:** do not auto-enable any candidate unless it improves task quality or remains within tolerance, with no severe FPS/speech/cancel regression. Trigger fallback to a cheap reflex model or silence under resource pressure rather than running more parallel GPU jobs.

The official **llama.cpp SPEED-Bench** documents a baseline-vs-speculative procedure with matched prompts and reports draft acceptance, throughput and latency separately. A speculative method can worsen performance when the draft consumes scarce VRAM or accepts few tokens. Treat every alleged speedup as a hypothesis until tested on Star's device and concurrency profile.

## Game creation: grounded end-to-end Studio and Blender loop

Roblox announced on **November 4, 2026** expanded Studio MCP permission controls, Open Cloud management, Blender asset imports and associated skills. A **November 5** follow-up identifies a known HTTP allowlist issue for unpublished places. Use these capabilities only with specific allowed games and scopes:
- Generate a project specification and acceptance tests, including screenshots at multiple viewport sizes, collision checks and budgets.
- Develop Luau with Rojo/Luau analyzer/StyLua/selene as applicable; edit only approved Studio places and assets.
- Run *actual* Studio playtests with logged object-state checks and snapshots; don't confuse generated test descriptions with executed tests.
- Run independent visual judgment for UI, animation, character proportion, light, maps and physics interactions; capture reproducible before/after evidence.
- Repair bounded defects; compare complete task metrics; store accepted skill only after tests/holdouts; rollback to last passing version on regression.
- Keep monetization, publishing, accounts and interactions with public players behind explicit owner rules.

A small 2D Roblox minigame is a useful initial generalist benchmark: it requires original sprites, gameplay physics, UI, sounds, matchmaking logic, test automation and real user-facing aesthetics, yet can be iterated within an isolated test place.

## Integration and release gates

1. **Now implemented:** read-only OBS decision-time PID/TCP owner revalidation and 750 ms sample-age gate; **disabled unless the host is explicitly armed**.
2. **Windows private verification:** process-list and TCP ownership with real OBS bound exclusively to loopback, record recommendation overhead and poll cadence, ensure stale identity revokes even without a subsequent `sample()`. Observe only; do not start a stream.
3. **Physical receipt integration:** independently measure game *presented* frames, GPU UUID-pinned VRAM, playback-confirmed first audible times and OBS counters on one host monotonic clock; wire into current `HostLoadReceipt` without inventing zero for missing measurements.
4. **Private nonbroadcast rehearsal:** test game+local LLM+voice+avatar+OBS recording. Network stream-drop metrics are **not available** without a separately authorized active stream; use dedicated nonbroadcast QoS monitoring instead.
5. **Learning proof:** 30+ stratified practice/holdout scenes per target mechanic, matched baseline controls, retries and scenario-transfer acceptance. Compare actual rewards and deadlines, not model self-judgment.
6. **VTuber naturalness proof:** blinded comparisons of pre-registered matched conversations including silence, interruptions and genuine event grounding. Reject novelty that hurts viewer comprehension or audio reliability.
7. **Merge/publish:** this stacked draft depends on #1078 and earlier; run independent GitHub CI and Windows acceptance before merge. GitHub publishing is optional to Star's future local self-owned development forge, not its only internal source of truth.

### Primary sources (checked November 8, 2026)

- [OBS WebSocket v5 protocol, official](https://github.com/obsproject/obs-websocket/blob/master/docs/generated/protocol.md)
- [Gym-Anything-RT, October 27, 2026](https://arxiv.org/abs/2610.37567)
- [Gym-Anything for Robotics, October 29, 2026](https://arxiv.org/abs/2610.40565)
- [Gym-Anything, April 7, 2026](https://arxiv.org/abs/2604.06126)
- [Proact-VL, Microsoft Research / ICML 2026](https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/)
- [VoiceChat-TTS, August 13, 2026](https://arxiv.org/abs/2608.13831)
- [llama.cpp SPEED-Bench, official](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md)
- [Roblox Studio MCP November 4, 2026](https://devforum.roblox.com/t/studio-mcp-server-updates-open-cloud-access-in-your-mcp-client-and-asset-import-workflows/4975849)

**Claim boundary:** The only immediate production code effect is stricter OBS-resource *advice* freshness and process ownership at decision time. It does not yet improve measured tokens/second, game mastery, human likeness or production streaming. All such claims require independent real-world tests and explicit deployment.
