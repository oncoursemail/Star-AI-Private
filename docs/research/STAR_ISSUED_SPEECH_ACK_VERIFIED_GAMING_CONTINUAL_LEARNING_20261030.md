# STAR AI — authenticated-to-host speech-plan receipts, game learning, speed, knowledge and expressive VTubing

**Research and code revision:** 2026-10-30. **Evidence levels:** GitHub CI and source inspection; deterministic local-code regression candidates; primary-source research. **Not demonstrated:** GPU speedup, model-weight intelligence increase, real gameplay mastery, TTS naturalness, or an actual OBS stream.

## 1. Evidence-led finding in Star's current pipeline

The previous PR #841 head `1cda71a0da21fb85378057188b9e3a3252986cbf` passed the complete GitHub offline check suite (workflow `41119619012`: Python, frontend and Pyright-baseline jobs all successful). This is code-level verification, not an actual Windows gameplay or streaming test.

Reviewing `star/stream_director.py` exposed a missing **issued-proposal binding**. Before this change, `complete()` accepted an externally constructed `SpeechIntent` if its signal ID, event serial, session epoch, detail and deadline matched an existing queued event. None of those fields is secret. A host-adapter bookkeeping bug could therefore mark an unproposed event as spoken, consume the event, trigger viewer cooldown and create an "observed success reacted to" deduplication receipt, even though `propose()` had never issued the plan.

**Implemented on this branch:** retain only the exact, most recently returned `SpeechIntent` object per queued event; `complete()` rejects a copied/forged/stale object even if its fields match. Drop receipts on event expiry, priority eviction, disabled sessions, and acknowledged completion. The cache is bounded by the existing 48-event default/128-event maximum queue.

**Important boundary:** Python object identity authenticates only the in-process object that the planner offered. It does **not** prove the audio rendered, TTS completed, or OBS recorded anything. The host is still responsible for confirming playback before calling `complete(spoken=True)`. No voice playback, input, broadcast or model route is changed by this patch. Existing APIs remain advisory.

## 2. The next measurable improvement is not a bigger prompt: an end-to-end proof chain

Define a per-event local trace with one host monotonic clock:

`game-frame capture → observation evidence hash → bounded action proposal → host input dispatch/key-up → observed outcome → speech intent → first decoded PCM → device playback → OBS audible receipt → lip/face frame`.

Keep action proposals and speech utterances as separate, explicitly authorized systems. A game success needs an independently observed outcome, not a viewer claim, model narration or a screenshot of a fake popup. The audio callback must not block on LLMs or disk, and the model cannot extend its own key-hold ticket. Record metadata only; sensitive video/audio must stay in a private, short-retention capture store, never GitHub.

**Acceptance contract for an actual private Windows rehearsal (not measured yet):**
- 0 copy/forged proposal acknowledgments admitted, 0 receipts after session revoke, 0 issued intents retained after TTL.
- 0 model-reported "level complete" statements without independently evaluated game-state proof; record uncertainty for ambiguous visuals.
- Key-up watchdog proves every dispatched input was released, including focus loss and exceptions.
- Compare p50/p95/p99 event-to-OBS audible time, avatar A/V offset, first-audio underruns, game 1% low FPS, GPU peak MiB and CPU/RAM pressure.
- A fast response is not promoted if any paired general knowledge, Roblox creation or gameplay case becomes newly wrong, or if OBS fails to capture audio.
- Never call a quiet reaction a failure: deliberate silence under active gameplay is a desired streaming outcome.

## 3. Inference speed on an 8 GB gaming GPU: controlled experiments

The official [llama.cpp server documentation](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md) documents prompt-prefix cache reuse, slot-based processing and batching. The [SPEED-Bench reference](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md) measures completed requests and speculative-draft acceptance. These are options to benchmark, **not assumed speedups**.

Implement admission tiers without adding Python callbacks on the physical audio path:

| Priority | Examples | Failure policy |
| --- | --- | --- |
| P0 hard real-time | game key release, avatar frame presentation, audio device callback | Never wait for an LLM or network |
| P1 bounded interactive | visual keyframes, chat turn detector, short factual reaction, TTS playout | Short deadlines, cancel stale work |
| P2 optional | long-context reasoning, full game analysis, background Forge experiments, indexing | Pause/defer under frame or voice pressure |

On a shared RTX 4060 8 GB card, first measure actual VRAM used by game+OBS+avatar, then allocate observed headroom for an inference model. Compare identical GGUF/model revisions with cold/warm prefix cache, one/two slots, speculative decoding on/off, and CPU/GPU layer mixes. Hold prompts and game scenes constant; record throughput **and** first independently audible speech and frame pacing. Favor CPU for noncritical embeddings/retrieval/TTS only if measured transfer and contention improve the full system. Never assume CPU offload is faster.

Use the existing `stream_realtime_quality_gate.py` and `stream_workload_quality_matrix.py` to reject one-skill speed cherry-picking. Require full matched test rosters before recommending manual rehearsal; quality gates do not deploy models.

## 4. Autonomously playing games: a verifiable curriculum

[GameWorld](https://gameworld-bench.github.io/) supplies 34 browser games and 170 outcome-verifiable tasks spanning runner, arcade, platformer, puzzle and simulation genres. It evaluates true serialized game state rather than text descriptions of a win. Import its *method*, not its answers, into offline/private Star game labs.

Star already has `GameActionGate`, `GameMechanicProbeLab`, `GamePredictionLab`, `GameplaySkillBank` and `GameTransferEval`. The highest-value integration is a constrained game trial record connecting all five: `(game/version/hidden-seed, frame digest, predicted outcome, allowed symbolic action, dispatch receipt, independent scorer result, signed trial)`. Practice and held-out validation must not share outcomes. A false win never becomes a certified skill or a brag on stream.

Difficulty ladder: look/camera → movement and release → jump timing → UI interaction and inventory → enemy hazard recognition → longer navigation → cooperative private multiplayer → held-out transfer across visually different games. Measure independent objective completion and invalid input rates, not how much Star talks about understanding the game.

[EmbodiedCLBench, posted October 9, 2026](https://arxiv.org/abs/2610.13021) shows the need to test *compositional transfer* from acquired basic abilities to unseen advanced tasks; more experience does not automatically yield proportionate improvement. Build training/validation splits that genuinely differ in control timing, art style and goal sequence.

## 5. Creating polished games: inspect, execute, verify and repair

[Roblox OpenGameEval, posted October 1, 2026](https://github.com/Roblox/open-game-eval) tests 84 curated Studio tasks through executable scene and simulated play checks. Its research supports targeted object inspection before editing. [Roblox's April 9, 2026 Studio Playtest Agent beta](https://devforum.roblox.com/t/studio-beta-studio-assistant-mcp-playtest-agent/4566767) offers a built-in MCP-assisted playtest character, but is still beta.

Before Star builds a level, compile a **scene contract**: reachable spawn/objectives, floor and wall connectivity, prop bounding boxes, non-overlap zones, collision groups, NPC navigation, replicate-to-client rules, camera readability, mobile UI bounds, animation contact constraints, light/material palette and frame-time budget. A validator should return actual failing objects and screenshots/structured engine evidence to Core Forge; never let a textual "looks great" judge alone declare completion.

For Blender, verify normals, mesh topology, UVs, actual rig constraints and root-motion/foot-plant checks. For animations, compare rendered poses from multiple angles and flag intersections or wrist/grip mismatch. For Roblox, run scripted two-client playtests and exercise join/leave, interaction, physics and achievement persistence. Require all critical invariants, plus human-reviewed style quality, before calling a prototype shippable.

## 6. General knowledge and continual learning: separate facts from competencies

Star's own `stream_knowledge.py` already restricts streamed notes to reviewed, explicitly public-approved excerpts. Preserve this gate when expanding retrieval. Introduce freshness and source provenance rather than injecting thousands of unverified documents into a single prompt. Teach evidence retrieval, contradiction handling, uncertainty and explanation across math/science, language, software, art, history and everyday questions.

[AgentCL, posted June 1, 2026](https://arxiv.org/abs/2606.02461) emphasizes controlled task streams to distinguish useful transfer from noisy memory accumulation. [Mem2ActBench, posted January 13, 2026](https://arxiv.org/abs/2601.19935) evaluates whether persistent information is *applied to future actions*, not merely retrieved. Use them to structure Core Forge tests:
1. Pre-register held-out tasks and time/cost budgets.
2. Attempt baseline without the new memory/skill.
3. Allow learning on separate practice tasks, with evidence checksums and allowed licenses.
4. Re-run the previously unseen held-out tasks on the unchanged test environment.
5. Require per-task improvements, no severe regressions, and show storage and retrieval overhead.

An agent that accumulates retrieval files has not necessarily trained its neural weights or become generally intelligent. Core Forge should store experiment lineage, host verifiers, reversible versions and learning outcomes locally; GitHub stays an optional, owner-reviewed publication mirror.

## 7. Natural VTuber personality: speech timing, attention, memory and expression

[LiveKit's audio turn detector documentation](https://docs.livekit.io/agents/logic/turns/turn-detector/) describes semantic/acoustic turn prediction, including a minimum 250 ms VAD silence setting and adaptive endpointing choices. An opt-in local model should be evaluated with owner voice, teammates, in-game dialog, TTS echo and background music separately.

[Kyutai's Pocket TTS project](https://github.com/kyutai-labs/pocket-tts) documents CPU-streamable speech, including small English variants introduced in October 2026. Compare blind-listening quality, pronunciation, pauses, laughter behavior, first *audible* PCM and total CPU overhead against Star's existing voice. A small/fast model is not inherently a more expressive model. Only use Star-owned or properly consented voices.

Design Star as a consistent expressive **AI character**, not a person impersonator. Her eyes, blink cadence, twin tails and soft head/body motion should react to actual speech prosody, events and attention rather than random noise. State machine: `playing-focused`, `noticing`, `listening`, `responding`, `laughing`, `recovering`, `resting`. She should sometimes wait or gently self-correct, ask precise questions, and preserve episode memories only about things she actually experienced. Ensure reduced-motion support and stream/chat consent boundaries.

Sample rehearsal cases: dangerous platform jump while chat asks a question; ambiguous victory popup; user interruption during TTS; accidental OBS mute; another person speaking nearby; false-positive webcam/chat speaker attribution; failed game restart; successful hidden-seed transfer; outdated trivia fact. Grade audience-facing behavior independently of prompt elegance. Never claim human consciousness or make up a childhood.

## 8. Shipping policy and concrete next tasks

**Current branch change:** code-level, opt-in streaming planner receipt binding and deterministic regression tests. **No new model or controller enabled.** First pass full Python, Ruff, Pyright baseline gate and frontend CI at the final commit. Review that old streaming adapters only acknowledge the most recent object from `propose()`; a copied serialized `SpeechIntent` must now be re-proposed by the owning in-process director.

**Next controlled integration:** use a private game + local OBS rehearsal to produce an evidence trace, then run matched speed+quality gates. Create a small held-out GameWorld/OpenGameEval-style suite separate from practice before any self-upgrade. Only after measured improvements, enable features selectively with rollback and an explicit owner decision about publishing/streaming. The repository named `Star-AI-Private` is presently publicly visible; store no credentials, raw capture media or viewer identities here.

**Source freshness:** links and publication dates checked against official docs, project repositories and preprints on 2026-10-30. Results from external papers are not Star hardware benchmarks.
